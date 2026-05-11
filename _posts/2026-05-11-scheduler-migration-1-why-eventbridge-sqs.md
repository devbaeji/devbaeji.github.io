---
title: "[Backend] Spring @Scheduled의 한계 — 왜 EventBridge + SQS로 옮길까 (1/2)"
date: 2026-05-11 14:00:00 +0900
categories: [Backend, Spring]
tags: [spring, scheduled, eventbridge, sqs, multi-pod, distributed-systems]
---

> **시리즈**
> (1) **Spring @Scheduled의 한계 — 왜 EventBridge + SQS로 옮길까** ← 현재 글
> (2) [절반만 이관된 SQS 마이그레이션 잔재 청소하기](/posts/scheduler-migration-2-cleanup-leftover/)

운영 서비스의 출퇴근 사전 생성, 알림 발송 같은 정기 작업이 *"AWS EventBridge → SQS → Spring Consumer"* 구조로 돼 있다. 처음 보면 *"`@Scheduled` 한 줄로 끝낼 일 아닌가"* 싶지만, 멀티 pod 환경에서 직접 부딪혀보면 그게 왜 안 되는지 명확하다.

이 글은 그 이유 + 면접에서 *"분산 환경 cron job 어떻게 처리하시겠어요?"* 라고 받았을 때 답할 정리.

## `@Scheduled` 가 실제 동작하는 방식

```kotlin
@Scheduled(cron = "0 */10 * * * *")
fun preCreateAttendances() { ... }
```

`@EnableScheduling` 이 켜지면 Spring 이 **각 JVM 안에 `ScheduledExecutorService` (백그라운드 스레드 풀)** 를 띄우고 cron 표현식에 맞춰 메서드를 호출한다.

핵심: **시계가 각 JVM 안에 따로 존재.** 외부 트리거 없음. 앱이 떠 있기만 하면 자기가 시간 재서 실행.

pod 가 3개면:

```
매 10분, cron tick 발생
   ├─ Pod A 의 JVM 타이머 → preCreateAttendances()
   ├─ Pod B 의 JVM 타이머 → preCreateAttendances()
   └─ Pod C 의 JVM 타이머 → preCreateAttendances()
```

같은 작업이 3번 동시에 실행. *"한 번만 발생해야 하는 이벤트"* (출퇴근 기록 1건, 푸시 1건) 한테는 치명적.

> **면접 질문 💼**
> *"Spring `@Scheduled` 를 멀티 인스턴스에서 그대로 쓰면 어떤 문제가 생기나요?"*
>
> 각 JVM 의 `ScheduledExecutorService` 가 독립 동작하므로 pod 수만큼 동시 실행. 추가 조정 없이는 *"정확히 한 번"* 보장 불가.

## 1차 후보: 분산 락 (ShedLock)

가장 간단한 해결책. 모든 pod 이 락을 잡으러 가서 먼저 잡은 pod 만 실행.

```kotlin
@Scheduled(cron = "0 */10 * * * *")
@SchedulerLock(name = "preCreateAttendances", lockAtMostFor = "5m")
fun preCreateAttendances() { ... }
```

락 저장소는 DB 테이블이나 Redis. 작은 규모면 충분.

다만 한계가 있다:

- **thundering herd 의 작은 버전** — 모든 pod 이 cron tick 마다 *"락 잡을게"* 시도. pod 100개면 100개가 동시에 락 저장소를 두드림
- **락 타이밍 사고 가능** — `lockAtMostFor` 가 짧으면 작업 중인데 락 풀려서 동시 실행, 길면 pod 죽었을 때 다음 실행 지연
- **재시도/DLQ 직접 구현** — SQS 가 무료로 주는 기능들
- **락 테이블이 핫스팟** — DB 부담 추가

## 2차 후보: 트리거를 외부로 (EventBridge → SQS)

AWS **EventBridge Scheduler** 가 cron 시계 역할. 시간 되면 메시지 1건을 SQS 큐에 enqueue. Spring Consumer 가 받아서 처리.

```
[EventBridge Scheduler]       ← AWS 매니지드 cron
        │  매 N분마다 메시지 1건
        ▼
[SQS Queue]
        │
   [Pod A] [Pod B] [Pod C]    ← 모든 pod 이 polling
        │
        └─ SQS 가 한 메시지를 "딱 한 pod" 한테만 lease
            처리 완료 → DeleteMessage
            처리 실패 → visibility timeout 후 재시도
```

핵심: **SQS 의 "1 메시지 = 1 consumer lease"** 모델. pod 이 100개여도 한 메시지는 1개 pod 만 처리. 분산 락 코드 없이 인프라 레벨에서 보장.

## EventBridge 가 실제로 뭘 하는가

EventBridge Scheduler 가 하는 일은 진짜 단순하다. **정해진 시간마다 SQS 큐에 JSON 메시지 1건을 넣는 게 전부.**

실제 운영 인프라 정의 (Terraform):

```hcl
eventbridge_scheduler_configs = {
  "notification-scheduler-prod" = {
    schedule_expression = "rate(5 minutes)"
    target_queue_key    = "notification-trigger"
    input_payload = jsonencode({
      type   = "notification"
      source = "eventbridge-scheduler"
    })
  }

  "attendance-scheduler-prod" = {
    schedule_expression = "rate(5 minutes)"
    target_queue_key    = "attendance-trigger"
    input_payload = jsonencode({
      type   = "attendance"
      source = "eventbridge-scheduler"
    })
  }
}
```

dev/prod 환경마다 알림용/출퇴근용 2개씩, 총 4개 스케줄러.

| 스케줄러 | 주기 | 대상 SQS 큐 | 메시지 페이로드 |
|---|---|---|---|
| notification-scheduler | **5분마다** | notification-trigger-queue | `{"type": "notification"}` |
| attendance-scheduler | **5분마다** | attendance-trigger-queue | `{"type": "attendance"}` |

EventBridge 는 메시지만 넣고 끝. 실제 작업은 Spring 측 SqsConsumer 가 받아서 처리.

```kotlin
// 알림 트리거 컨슈머
@SqsListener("\${aws.sqs.notification-trigger-queue-name}")
fun onMessage(message: BatchTriggerMessage) {
  if (message.type == "notification") {
    // 5종 알림 점검 묶음 실행
    scheduledNotificationService.sendUrgentWorkReminders()
    scheduledNotificationService.sendWorkStartReminders()
    scheduledNotificationService.sendCheckInDelayAlerts()
    scheduledNotificationService.sendWorkEndTimeAlerts()
    scheduledNotificationService.sendCheckOutMissingAlerts()
  }
}

// 출퇴근 트리거 컨슈머
@SqsListener("\${aws.sqs.attendance-trigger-queue-name}")
fun onMessage(message: BatchTriggerMessage) {
  if (message.type == "attendance") {
    attendancePreCreationService.preCreateAttendancesForUpcomingSchedules()
  }
}
```

쉽게 말하면 EventBridge 는 **"5분마다 종 울려주는 시계"**, Spring API 가 **"종소리 듣고 실제 작업 수행하는 사람"**. 실제 비즈니스 로직 (*"어느 사용자한테 무슨 알림을"*) 은 전부 Spring API 안에 있다.

> **면접 질문 💼**
> *"왜 EventBridge 가 직접 Lambda 나 ECS Task 를 부르지 않고 SQS 를 한 단계 거치나요?"*
>
> 1. **버퍼링** — Consumer 가 잠시 죽어도 SQS 에 메시지가 쌓여 있다가 살아나면 처리됨. 직접 호출이면 그 시간 동안 발생한 cron 은 유실.
> 2. **재시도** — Consumer 가 처리 중 실패하면 visibility timeout 후 SQS 가 자동 재배포. 직접 호출이면 재시도 로직 직접 구현 필요.
> 3. **부하 분산** — 한 메시지를 여러 pod 중 한 곳이 가져감. 직접 호출은 특정 인스턴스에 고정.
> 4. **느슨한 결합** — EventBridge 는 SQS 큐 이름만 알면 됨. Consumer 가 어떤 언어/플랫폼인지 무관.

## 그 뒤 — 발송 레이어 (Lambda + SNS fanout)

여기까지가 *"언제 알림 로직을 돌릴지"* 의 트리거 레이어. 트리거된 도메인 로직이 *"누구에게 무엇을 보낼지"* 결정한 다음, 실제 외부 채널(Gmail, FCM, Slack, Kakao 등) 로 발송하는 건 또 다른 파이프라인이다.

운영에서 확인한 발송 레이어 아키텍처:

```
[Spring API]
  NotificationFacadeService → NotificationService
  sqsTemplate.send(notification-queue, payload)
        │
        ▼
[SQS notification-queue]
        │
        ▼
[Lambda: notification-router]
  message.types 배열 보고 SNS Topic 으로 분기 (fanout)
        │
        ├──────┬──────┬──────┬──────┬──────┐
        ▼      ▼      ▼      ▼      ▼
   [SNS]  [SNS]  [SNS]  [SNS]  [SNS]
   gmail   fcm   slack  kakao   sms
     │      │      │      │      │
     ▼      ▼      ▼      ▼      ▼
  [gmail- [fcm-  [slack-[kakao-[sms-
   notifier]notifier]notifier]notifier]notifier]
   Lambda  Lambda  Lambda Lambda Lambda
     │      │      │      │      │
     ▼      ▼      ▼      ▼      ▼
   📧     📱     💬     💛     📨
   Gmail  FCM    Slack  Kakao  SMS

------------------------------------------
발송 결과 SQS → [Spring result-listener] → DB 기록
                                          (UserNotification 등)
```

레이어별 책임:

| 레이어 | 역할 | 구현체 |
|---|---|---|
| Spring API | 알림 도메인 로직 (누구한테/무엇을) | `NotificationFacadeService` |
| SQS | 비동기 큐 | `notification-queue` |
| Router Lambda | 메시지 타입별 SNS 분기 | `notification-router` |
| SNS Topic ×5 | 채널별 토픽 (fanout) | gmail / fcm / slack / kakao / sms |
| Channel Lambda ×5 | 실제 외부 API 호출 | `*-notifier` |
| 외부 서비스 | Firebase / Gmail / Slack / Kakao / SMS provider | — |
| 결과 수집 | 발송 결과 DB 기록 | `result-listener` |

> **면접 질문 💼**
> *"왜 Lambda 가 하나로 모든 채널을 발송하지 않고 SNS Topic 으로 fanout 하나요?"*
>
> 1. **채널별 독립 스케일링** — FCM 은 트래픽 많고 Slack 은 적다면, 각 Lambda 의 동시성 설정을 따로 튜닝 가능.
> 2. **장애 격리** — Gmail Lambda 가 죽어도 다른 채널은 정상 발송. 단일 Lambda 였으면 한 채널 실패가 전체 재시도로 번짐.
> 3. **권한 분리** — fcm-notifier 만 Firebase Secrets Manager 권한, gmail-notifier 만 SES 권한. 최소 권한 원칙 적용.
> 4. **다른 구독자 추가 용이** — SNS Topic 에 새 구독자 (예: 분석용 Lambda, CloudWatch Logs) 추가가 자유로움.
>
> SNS 의 핵심은 **publish-subscribe** 모델. 발행자(Router) 는 구독자가 누구인지 몰라도 됨.

> **면접 질문 💼**
> *"at-least-once delivery 가 멀티 레이어에서 어떻게 누적되나요?"*
>
> 이 파이프라인엔 SQS → Lambda → SNS → Lambda 까지 메시지가 4번 단계를 거친다. 각 단계가 at-least-once 라면 최악의 경우 **같은 푸시가 여러 번 발송될 수 있다**.
>
> 방어:
> - SQS 의 visibility timeout 적절히 설정 (Lambda 처리 시간보다 길게)
> - 발송 결과 DB 기록 시 idempotency key (메시지 ID 등) 로 중복 차단
> - 정 안 되면 SQS FIFO + 중복 제거 window 사용

## Visibility Timeout

> **면접 질문 💼**
> *"SQS 의 Visibility Timeout 이 뭔가요?"*
>
> Consumer 가 `ReceiveMessage` 로 메시지를 받는 순간, AWS 는 그 메시지를 큐에서 *삭제하지 않고* 일정 시간 동안 다른 consumer 에게 안 보이게 가린다. 그 시간 안에 `DeleteMessage` 호출되면 영영 삭제, 안 되면 다시 보여서 다른 consumer 가 가져감. 일종의 **lease** 메커니즘.

이 모델 덕에 *"처리 중인 메시지를 다른 pod 이 동시에 처리"* 가 자연스럽게 차단된다.

## at-least-once 의 함정

> **면접 질문 💼**
> *"SQS 가 at-least-once 라는 게 무슨 뜻인가요? 그럼 멱등성 처리가 왜 여전히 필요한가요?"*
>
> 같은 메시지가 **2번 이상 배달될 수 있다**는 뜻. 예시:
> - Consumer 가 처리는 다 했는데 `DeleteMessage` 직전에 죽음 → visibility timeout 후 재처리
> - 네트워크 지연으로 SQS 가 ACK 못 받음
>
> 그래서 consumer 코드는 **멱등** 해야 한다. 같은 메시지 2번 처리해도 결과가 같아야 한다. DB UNIQUE 제약, idempotency key, `INSERT ... ON CONFLICT DO NOTHING` 같은 기법 필요.

운영 코드에서는 `UNIQUE(schedule_id, account_id, work_date)` + `INSERT IGNORE` 패턴으로 멱등성 확보. SQS 가 lease 로 1 consumer 만 보장해도 그 consumer 가 retry 받을 수 있으므로 DB 단 방어가 필수.

## FIFO vs Standard

> **면접 질문 💼**
> *"SQS FIFO vs Standard 차이? 언제 뭘 쓰나요?"*
>
> | 항목 | Standard | FIFO |
> |---|---|---|
> | 순서 보장 | ❌ | ✅ (그룹별) |
> | 중복 제거 | ❌ (at-least-once) | ✅ (5분 window, exactly-once 가능) |
> | 처리량 | 무제한 | 초당 300건 (batching 3,000건) |
> | 가격 | 더 저렴 | 더 비쌈 |
>
> cron 트리거는 *"N분마다 1건"* 이라 처리량/순서 부담 없음 → **Standard** 로 충분. 결제처럼 *"같은 거래 두 번 처리되면 안 되는"* 경우는 FIFO.

## 정리

| 항목 | `@Scheduled` 단독 | `@Scheduled` + ShedLock | EventBridge → SQS |
|---|---|---|---|
| 멀티 pod 동작 | N개 동시 실행 ❌ | 1개만 실행 ✅ | 1개만 실행 ✅ |
| 외부 의존성 | 없음 | DB or Redis | AWS |
| cron 외부화 | ❌ | ❌ | ✅ |
| 재시도/DLQ | 직접 구현 | 직접 구현 | SQS 자동 |
| 운영 가시성 | 일반 앱 로그 | 일반 앱 로그 | CloudWatch 메트릭 |
| 로컬 개발 | 그냥 됨 | 그냥 됨 | LocalStack 등 필요 |
| AWS 락인 | 없음 | 없음 | 있음 |
| 적합한 규모 | 단일 pod / 토이 | 중소 규모 | 운영 트래픽 |

이미 AWS 위에서 돌고 있고 *"분산 락 직접 운영 vs 매니지드"* 트레이드오프에서 후자가 운영 안정성이 좋다면 EventBridge → SQS 가 정답에 가깝다.

---

다음 글에서는 이 마이그레이션이 *"인프라는 만들었는데 yml 플래그가 그대로 `true`"* 인 어정쩡한 상태로 한 달 넘게 운영되고 있었던 걸 발견하고 청소한 경험을 정리한다.

→ [(2) 절반만 이관된 SQS 마이그레이션 잔재 청소하기](/posts/scheduler-migration-2-cleanup-leftover/)
