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

이 글은 그 이유와, 분산 환경에서 cron job 을 어떻게 처리할지에 대한 정리다.

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

{% include scheduler-trigger-arch.html %}

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

EventBridge 가 작업을 직접 호출하지 않고 SQS 를 한 단계 거치는 이유는 이렇다. Consumer 가 잠시 죽어도 메시지가 큐에 쌓여 있다가 살아나면 처리되고(직접 호출이면 그 사이 cron 은 유실), 처리 중 실패하면 visibility timeout 후 SQS 가 다시 내준다. 한 메시지는 여러 pod 중 한 곳만 가져가고, EventBridge 는 큐 이름만 알면 되니 Consumer 가 무엇으로 만들어졌는지 몰라도 된다.

## 그 뒤 — 발송 레이어 (Lambda + SNS fanout)

여기까지가 *"언제 알림 로직을 돌릴지"* 의 트리거 레이어. 트리거된 도메인 로직이 *"누구에게 무엇을 보낼지"* 결정한 다음, 실제 외부 채널(Gmail, FCM, Slack, Kakao 등) 로 발송하는 건 또 다른 파이프라인이다.

운영에서 확인한 발송 레이어 아키텍처:

{% include scheduler-dispatch-arch.html %}

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

Lambda 하나가 모든 채널을 보내지 않고 SNS Topic 으로 fanout 하는 건 채널을 서로 떼어 놓기 위해서다. 채널별 Lambda 의 동시성을 따로 튜닝할 수 있고, Gmail Lambda 가 죽어도 다른 채널은 정상 발송된다. 권한도 fcm-notifier 는 Firebase, gmail-notifier 는 SES 처럼 채널별로 최소한만 준다. 발행자(Router) 는 구독자가 누군지 몰라도 되니 분석용 Lambda 같은 구독자를 나중에 붙이기도 쉽다.

다만 메시지가 SQS → Lambda → SNS → Lambda 4단계를 거치고 각 단계가 at-least-once 라서, 최악의 경우 **같은 푸시가 여러 번 발송될 수 있다**. visibility timeout 을 Lambda 처리 시간보다 길게 잡고, 발송 결과를 기록할 때 메시지 ID 같은 idempotency key 로 중복을 막아야 한다.

## Visibility Timeout

Consumer 가 `ReceiveMessage` 로 메시지를 받으면, SQS 는 그 메시지를 *삭제하지 않고* 일정 시간 동안 다른 consumer 에게 안 보이게 가린다. 그 안에 `DeleteMessage` 가 호출되면 삭제되고, 아니면 다시 보여서 다른 consumer 가 가져간다. 일종의 **lease** 다.

이 모델 덕에 *"처리 중인 메시지를 다른 pod 이 동시에 처리"* 가 자연스럽게 차단된다.

## at-least-once 의 함정

SQS 는 at-least-once 라서 같은 메시지가 **2번 이상 배달될 수 있다**. Consumer 가 처리를 다 하고 `DeleteMessage` 직전에 죽으면 visibility timeout 후 재처리된다. 그래서 consumer 는 같은 메시지를 두 번 처리해도 결과가 같은 **멱등** 코드여야 한다.

운영 코드에서는 `UNIQUE(schedule_id, account_id, work_date)` + `INSERT IGNORE` 패턴으로 멱등성 확보. SQS 가 lease 로 1 consumer 만 보장해도 그 consumer 가 retry 받을 수 있으므로 DB 단 방어가 필수.

## FIFO vs Standard

| 항목 | Standard | FIFO |
|---|---|---|
| 순서 보장 | ❌ | ✅ (그룹별) |
| 중복 제거 | ❌ (at-least-once) | ✅ (5분 window, exactly-once 가능) |
| 처리량 | 무제한 | 초당 300건 (batching 3,000건) |
| 가격 | 더 저렴 | 더 비쌈 |

cron 트리거는 *"N분마다 1건"* 이라 처리량·순서 부담이 없어서 **Standard** 로 충분하다. 결제처럼 *"같은 거래가 두 번 처리되면 안 되는"* 경우라면 FIFO 를 고른다.

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

## 마무리: 트리거 + 발송 통합 그림

지금까지 살펴본 트리거 레이어와 발송 레이어를 한 장에 정리하면 이런 그림이 된다.

{% include scheduler-integrated-arch.html %}

위쪽(①) 은 *"5분마다 종 울려서 어떤 도메인 로직을 깨우기"*. 아래쪽(②) 은 *"깨어난 도메인이 결정한 알림을 외부로 fanout"*. 둘이 합쳐져서 *"AWS 매니지드 cron + 비동기 발송"* 한 줄짜리 설명의 풀스택 그림.

---

다음 글에서는 이 마이그레이션이 *"인프라는 만들었는데 yml 플래그가 그대로 `true`"* 인 어정쩡한 상태로 한 달 넘게 운영되고 있었던 걸 발견하고 청소한 경험을 정리한다.

→ [(2) 절반만 이관된 SQS 마이그레이션 잔재 청소하기](/posts/scheduler-migration-2-cleanup-leftover/)
