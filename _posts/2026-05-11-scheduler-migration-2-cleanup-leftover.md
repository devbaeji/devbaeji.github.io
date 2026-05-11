---
title: "[Backend] 절반만 이관된 SQS 마이그레이션 잔재 청소하기 (2/2)"
date: 2026-05-11 15:00:00 +0900
categories: [Backend, Spring]
tags: [spring, refactoring, dead-code, sqs, eventbridge, migration]
---

> **시리즈**
> (1) [Spring @Scheduled의 한계 — 왜 EventBridge + SQS로 옮길까](/posts/scheduler-migration-1-why-eventbridge-sqs/)
> (2) **절반만 이관된 SQS 마이그레이션 잔재 청소하기** ← 현재 글

[1편](/posts/scheduler-migration-1-why-eventbridge-sqs/) 에서 *"멀티 pod 정기 작업은 EventBridge → SQS 로 옮기는 게 안전하다"* 까지 정리. 운영 서비스는 이미 그렇게 옮겨놓은 상태였는데, 코드 보다 보니 *"옮긴 게 진짜 다 옮긴 건가"* 싶은 부분이 보였다.

가설 → 검증 → 잔재 발견 → 청소까지의 기록.

## 1차 가설 (틀림)

코드 리뷰 중 *"부하/race condition 처리는 어떻게 돼 있나"* 하고 도메인을 훑었다. 출퇴근/알림 쪽에 `@Scheduled` 어노테이션이 많이 보였고, 자연스럽게 가설이 떠올랐다:

> *"운영에서 매 cron tick 마다 모든 pod 이 동시에 같은 작업을 실행하고 있을 가능성. 푸시 N번 발송 사고 가능."*

확인해보니 **SQS 기반 배치로 옮긴 PR 이 이미 존재**했다. EventBridge → SQS → Consumer 구조도 잘 추가돼 있었다. **1차 가설은 틀림.**

## 2차 가설 (어색한 단서)

여기서 끝낼 수도 있었지만 한 가지 어색한 점이 남았다. SQS 로 옮겼다면 코드의 `@Scheduled` 는 왜 그대로?

```kotlin
@Component
@ConditionalOnProperty(
  name = ["scheduling.attendance.enabled"],
  havingValue = "true",
  matchIfMissing = false,
)
class AttendanceScheduler(
  private val service: AttendancePreCreationService,
) {
  @Scheduled(cron = "\${scheduling.attendance.cron:0 */10 * * * *}")
  fun preCreateAttendances() { ... }
}
```

`@ConditionalOnProperty` 가 단서.

> **면접 질문 💼**
> *"Spring 의 `@ConditionalOnProperty` 가 뭔가요? `matchIfMissing` 옵션은요?"*
>
> 특정 properties 값에 따라 빈을 등록할지 결정하는 어노테이션. `havingValue` 가 매칭되면 빈 등록, 아니면 스킵.
>
> `matchIfMissing` 은 *"yml 에 키가 아예 없을 때 어떻게 할지"* 의 기본값. `false` 면 키 없을 때 빈 등록 안 함 (안전), `true` 면 키 없어도 등록 (위험할 수 있음).
>
> **마이그레이션 중간 상태에서는 `false` 가 안전한 기본값.** 키를 깜빡 빼먹어도 자동 활성화되지 않는다.

*"전환 중인 코드 흔적"*. yml 의 enabled 가 어떻게 돼 있는지 확인:

```yaml
# application-production.yml
# EventBridge Scheduler 로 전환 완료 후 모든 enabled 를 false 로 변경
scheduling:
  attendance:
    enabled: true            # ← ???
    cron: "0 */10 * * * *"
  notification:
    enabled: false           # ← 얘는 false
```

주석은 *"전환 완료 후 모든 enabled 를 false 로 변경"*. 그런데 attendance 만 `true`, notification 만 `false`.

가설 수정: **전환이 절반만 끝났다.** EventBridge 도 살아있고 `@Scheduled` 도 살아있다.

## 검증: AWS CLI

```bash
$ aws scheduler list-schedules --region ap-northeast-2
attendance-scheduler-prod    | ENABLED
notification-scheduler-prod  | ENABLED
attendance-scheduler-dev     | ENABLED
notification-scheduler-dev   | ENABLED
```

EventBridge Scheduler 4개 다 ENABLED. Spring 측 `AttendanceTriggerSqsConsumer` 도 정상 존재. 즉 production 상태:

```
[EventBridge Scheduler]
        │ 매 5분마다 메시지 1건
        ▼
[SQS Queue] → [Pod A] SqsConsumer 처리 (의도된 1 pod) ✅

동시에:
[Pod A 의 @Scheduled] → 매 10분마다 호출  ← 잔재
[Pod B 의 @Scheduled] → 매 10분마다 호출  ← 잔재
[Pod C 의 @Scheduled] → 매 10분마다 호출  ← 잔재
```

cron tick 당 호출 수: **(EventBridge 1회) + (pod N회) = N+1 회**.

## 왜 데이터 사고는 안 났나

이 상태가 한 달 이상이었는데 사용자 컴플레인은 없었다. DB 스키마를 보면 답이 있다:

```sql
CREATE TABLE ticket_schedule_attendances (
  ...
  UNIQUE (schedule_id, account_id, work_date)
);
```

```kotlin
// PostgreSQL: INSERT ... ON CONFLICT DO NOTHING
repository.insertIgnoreDuplicate(attendance)
```

`UNIQUE` 제약 + `ON CONFLICT DO NOTHING`. **DB 가 마지막 방어선**. N+1 번 INSERT 가 날아가도 UNIQUE 키가 같으면 두 번째부터 조용히 무시.

> **면접 질문 💼**
> *"멱등성 처리 어떻게 하시나요? 코드 레벨 vs DB 레벨 차이는?"*
>
> 코드 레벨: 처리 전 *"이미 처리된 건지"* 조회 → 없으면 처리. 간단하지만 동시성 race 발생 가능 (TOCTOU 문제 — Time Of Check vs Time Of Use).
>
> DB 레벨: UNIQUE 제약 + `INSERT ... ON CONFLICT DO NOTHING` (PostgreSQL) 또는 `INSERT IGNORE` (MySQL). 동시 race 가 와도 DB 가 한 건만 살린다.
>
> **둘 다 적용**이 안전. 코드는 *"평소 경로의 99%"* 책임지고, DB 는 *"이상 상황의 1%"* 최후 방어. 이번 잔재 케이스에서 DB 가 사고를 막아줬다.

데이터 중복은 안 생겨도 **DB SELECT/INSERT 부하는 N+1배**. 모니터링 그래프 상 매 5~10분마다 DB CPU 가 살짝 튀는 패턴이 이것.

## 청소: 컴파일 무결성을 위한 커밋 순서

`AttendanceScheduler` 를 먼저 지우면 그걸 의존하는 `SchedulerController` 가 컴파일 안 됨. 의존 끊기 → 삭제 순서 필요.

### 커밋 1: yml false (즉시 효과)

```diff
 scheduling:
   attendance:
-    enabled: true
-    cron: "0 */10 * * * *"
+    enabled: false
```

이거 하나만 배포돼도 production 의 N개 `@Scheduled` 즉시 멎음. `@ConditionalOnProperty(matchIfMissing = false)` 덕에 빈 등록 자체가 스킵.

**가장 큰 효과를 가장 작은 변경으로.**

### 커밋 2: SchedulerController 의존 끊기

```kotlin
// Before
class SchedulerController(
  private val attendanceScheduler: AttendanceScheduler,  // 의존
)

// After
class SchedulerController(
  private val service: AttendancePreCreationService,  // 진짜 로직 직접
)
```

수동 실행 버튼은 유지하면서 의존성만 끊기. 다음 커밋에서 `AttendanceScheduler` 를 안전하게 지울 수 있게 됨.

### 커밋 3: AttendanceScheduler 삭제

의존이 없으니 파일 통째로 삭제. **-63줄.**

### 커밋 4: NotificationScheduler 삭제 + local yml 정리

notification 은 yml `false` 는 됐지만 클래스가 dead code. SqsConsumer 가 `ScheduledNotificationService` 직접 호출하므로 wrapper 불필요. **-152줄.**

총 4 커밋, **-215줄**.

## 배운 점

### 1. 동료의 정정도 의심해본다

1차 가설은 틀렸지만, 2차 가설은 맞았다. *"이미 옮겼다"* 라는 정정을 받아들이되 남아있는 어색함 (yml `true`) 을 한 번 더 검증한 게 진짜 잔재 발견으로 이어졌다.

**새 정보를 받되, 남은 의문은 끝까지 추적하기.**

### 2. 마이그레이션 = 전환 + 청소

PR 설명에 *"전환 완료 후 enabled false 처리 필요"* 라고 후속 작업이 명시돼 있었지만 한 달 넘게 잊혀졌다. notification 은 다른 작업하면서 같이 정리됐는데 attendance 는 누락.

체크리스트:

- [ ] 새 경로 추가
- [ ] 기존 경로 `@ConditionalOnProperty(matchIfMissing = false)` 게이트
- [ ] yml 플래그 `false` ← **자주 빠짐**
- [ ] wrapper 클래스 삭제 ← **자주 빠짐**
- [ ] 진짜 로직 (service) 은 손대지 않기
- [ ] 후속 작업은 Jira 티켓으로 끊어두기 (PR 설명에만 적으면 잊혀짐)

### 3. 의존 순서 + 빌드 무결성

청소 작업도 의존 그래프를 본다. 잎(leaf) 부터 지우면 안 됨 — 의존자부터 끊고 마지막에 잎 삭제. 각 커밋이 *"이 커밋만으로도 빌드 통과"* 가 보장되도록 쪼개면 revert 도 쉽다.

### 4. DB UNIQUE 제약 = 운영의 마지막 방어선

이번에 사고가 안 난 건 순전히 `UNIQUE` 덕분. *"이 이벤트는 같은 키에 대해 한 번만 발생해야 한다"* 가 도메인 룰이면 가능하면 **DB 스키마 레벨에 UNIQUE 를 거는 게** 안전. 마이그레이션 같은 일시적 카오스에서도 무결성을 지켜준다.

---

PR 4개 커밋, -215줄. 새로 만든 게 아니라 잊혀진 걸 마무리한 작업이라 화려하지 않지만, 운영 부담을 줄이는 의미 있는 작업.
