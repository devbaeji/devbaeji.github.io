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

## 한 가지 놓친 부분: 로컬에선 어떻게 테스트?

청소 직후 PR 리뷰 받다가 지적 받은 부분. 운영은 EventBridge → SQS 로 돌지만 **로컬엔 EventBridge/SQS 인프라가 없다.** `@Scheduled` 클래스를 다 지웠으니 로컬에서 cron 시뮬레이션이 불가능.

수동 1회 실행 API (`POST /api/v1/scheduler/attendance/pre-create`) 는 남아있긴 한데, *"1분마다 자동 실행되게 해놓고 데이터가 쌓이는 걸 한참 지켜보고 싶다"* 같은 시나리오를 못 함.

### 보강: `@Profile("local")` + `@ConditionalOnProperty` 이중 게이팅

운영 코드에 dev 편의 코드가 섞이는 걸 막으려고 **로컬 전용** 클래스를 별도로 분리.

```kotlin
@Component
@Profile("local")
@ConditionalOnProperty(
  name = ["scheduling.attendance.enabled"],
  havingValue = "true",
  matchIfMissing = false,
)
class LocalAttendanceScheduler(
  private val service: AttendancePreCreationService,
) {
  @Scheduled(cron = "\${scheduling.attendance.cron:0 */10 * * * *}")
  fun preCreateAttendances() {
    service.preCreateAttendancesForUpcomingSchedules()
  }
}
```

이중 안전장치:
- `@Profile("local")` → develop/production 환경에선 **빈 등록 자체 안 됨**
- `@ConditionalOnProperty(matchIfMissing = false)` → local 이어도 yml `enabled=false` 면 동작 안 함

평소엔 비활성, *"cron 시뮬이 필요한 날만"* 토글:

```yaml
# application-local.yml
scheduling:
  attendance:
    enabled: true              # 평소엔 false
    cron: "0 */1 * * * *"      # 1분으로 줄여서 빠른 검증
```

### 환경별 동작 매트릭스

| 환경 | EventBridge → SQS | LocalScheduler | 수동 트리거 API |
|---|---|---|---|
| **local** | ❌ 인프라 없음 | ✅ enabled=true 토글 시 cron | ✅ |
| **develop** | ✅ 매 5분 | ❌ @Profile 차단 | ✅ |
| **production** | ✅ 매 5분 | ❌ @Profile 차단 | ❌ @Profile 차단 |

운영 빌드에는 `LocalAttendanceScheduler` 빈이 아예 안 올라오니까, 코드는 있어도 운영 영향 0.

> **면접 질문 💼**
> *"같은 작업을 환경마다 다른 방식으로 실행하고 싶을 때 Spring 에선 어떻게 분리하나요?"*
>
> `@Profile` 로 환경별 빈 게이팅. `@ConditionalOnProperty` 와 조합하면 *"local 이어도 토글 안 켜면 동작 안 함"* 같은 이중 안전장치. 운영 코드에 dev 편의 코드가 섞이는 걸 막을 수 있다.
>
> 예) `@Profile("local") + @ConditionalOnProperty(enabled, matchIfMissing=false)` →
> - develop/production: 빈 자체가 컨텍스트에 안 올라옴 (실수로 활성화 불가)
> - local 기본: 비활성 (안전한 기본값)
> - local + yml 토글: 활성화

### 클래스 분리 vs 같은 클래스 + 어노테이션

처음엔 *"기존 `AttendanceScheduler` 를 살려두고 `@Profile("local")` 만 추가하면 되지 않나"* 도 고민했다. 다만 **새 클래스 (`LocalAttendanceScheduler`) 로 분리**하는 게 더 깔끔하다:

- 클래스 이름 자체가 *"이건 로컬 전용 코드"* 라고 말함 (인지적 부담 ↓)
- 운영 코드 디렉토리에 *"운영에선 안 도는 코드"* 가 섞이지 않음
- 진짜 도메인 로직(`AttendancePreCreationService`) 은 그대로, wrapper 만 환경별

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

### 5. 운영 코드와 개발 편의의 분리

청소 PR 에서 처음엔 `@Scheduled` 를 통째로 지웠다가, *"로컬엔 EventBridge 없는데 어떻게 테스트?"* 지적을 받고 로컬 전용 wrapper 를 다시 추가. *"운영 일관성"* 과 *"개발 편의"* 가 충돌할 때:

- 같은 클래스에 `@Profile + @ConditionalOnProperty` 만 붙이지 말고
- **이름부터 의도가 드러나는 별도 클래스** (`LocalAttendanceScheduler`) 로 분리
- 이중 게이팅으로 *"실수로 운영에서 활성화"* 가 원천 차단되게

운영 빌드의 ApplicationContext 에는 `LocalXxxScheduler` 빈이 아예 안 올라오니까, 코드 존재만으로 운영 영향 0.

---

PR 5개 커밋. 정리(-215줄) + 로컬 편의(+130줄). 새 기능을 만드는 것보다, 이미 만든 걸 어떻게 깔끔하게 마무리하느냐가 더 어렵다는 걸 다시 느꼈다.
