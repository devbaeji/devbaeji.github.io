---
title: "[Backend] 절반만 이관된 SQS 마이그레이션 잔재 청소하기 (2/2)"
date: 2026-05-11 15:00:00 +0900
categories: [Backend, Spring]
tags: [spring, refactoring, dead-code, sqs, eventbridge, migration, over-engineering]
---

> **시리즈**
> (1) [Spring @Scheduled의 한계 — 왜 EventBridge + SQS로 옮길까](/posts/scheduler-migration-1-why-eventbridge-sqs/)
> (2) **절반만 이관된 SQS 마이그레이션 잔재 청소하기** ← 현재 글

[1편](/posts/scheduler-migration-1-why-eventbridge-sqs/) 에서 *"멀티 pod 정기 작업은 EventBridge → SQS 로 옮기는 게 안전하다"* 까지 정리. 운영 서비스는 이미 그렇게 옮겨놓은 상태였는데, 코드 보다 보니 *"옮긴 게 진짜 다 옮긴 건가"* 싶었다.

이 글은 두 가지 시행착오 기록이다:
1. **마이그레이션 잔재를 발견한 과정** (가설 → 동료 정정 → 재의심)
2. **청소 작업을 over-engineering 했다가 simple 로 돌아간 과정** (5 커밋 → 1 커밋)

전제: 운영이 의도한 트리거 구조는 *오른쪽 (After)* 인데, 실제로는 *왼쪽 (Before)* + *오른쪽 (After)* 가 **동시에** 살아있었다. 1편 의 시각화를 다시 가져오면:

{% include scheduler-trigger-arch.html %}

## 1차 가설 (틀림)

코드 리뷰 중 *"부하/race condition 처리는 어떻게 돼 있나"* 하고 도메인을 훑었다. 출퇴근/알림 쪽에 `@Scheduled` 가 많이 보였고 가설이 떠올랐다:

> *"운영에서 매 cron tick 마다 모든 pod 이 동시에 같은 작업을 실행 중일 가능성. 푸시 N번 발송 사고 가능."*

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
class AttendanceScheduler(...) {
  @Scheduled(cron = "\${scheduling.attendance.cron:0 */10 * * * *}")
  fun preCreateAttendances() { ... }
}
```

`@ConditionalOnProperty` 가 단서.

> **면접 질문 💼**
> *"Spring 의 `@ConditionalOnProperty` 와 `matchIfMissing` 옵션은?"*
>
> 특정 properties 값에 따라 빈을 등록할지 결정. `havingValue` 매칭 시 등록, 아니면 스킵.
>
> `matchIfMissing` 은 *"yml 에 키가 아예 없을 때 어떻게 할지"* 의 기본값. `false` 면 키 없을 때 빈 등록 안 함 (안전), `true` 면 키 없어도 등록 (위험).
>
> **마이그레이션 중간 상태에서 `false` 가 안전한 기본값.** 키를 깜빡 빼먹어도 자동 활성화되지 않는다.

yml 의 enabled 확인:

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

주석은 *"전환 완료 후 모든 enabled 를 false 로 변경"*. 그런데 attendance 만 `true`. notification 만 `false`. **전환이 절반만 끝났다.**

AWS CLI 로 EventBridge 확인:

```bash
$ aws scheduler list-schedules --region ap-northeast-2
attendance-scheduler-prod    | ENABLED
notification-scheduler-prod  | ENABLED
```

production 의 상태:
- EventBridge 가 5분마다 메시지 → SQS → SqsConsumer (1 pod) ✓
- 동시에 모든 pod 의 `@Scheduled` 도 10분마다 호출 ❌

cron tick 당 호출 수: **(EventBridge 1회) + (pod N회) = N+1 회**.

## 왜 데이터 사고는 안 났나

DB 스키마를 보면 답:

```sql
CREATE TABLE ticket_schedule_attendances (
  ...
  UNIQUE (schedule_id, account_id, work_date)
);
```

`UNIQUE` 제약 + `INSERT ... ON CONFLICT DO NOTHING`. **DB 가 마지막 방어선**. N+1 번 INSERT 가 날아가도 두 번째부터는 조용히 무시.

> **면접 질문 💼**
> *"멱등성 처리, 코드 레벨 vs DB 레벨 차이는?"*
>
> 코드 레벨: 처리 전 *"이미 처리된 건지"* 조회 → 없으면 처리. 동시성 race 발생 가능 (TOCTOU 문제 — Time Of Check vs Time Of Use).
>
> DB 레벨: UNIQUE 제약 + `INSERT ... ON CONFLICT DO NOTHING` (PG) / `INSERT IGNORE` (MySQL). 동시 race 가 와도 한 건만 살림.
>
> **둘 다 적용**이 안전. 코드는 *"평소 경로의 99%"*, DB 는 *"이상 상황의 1%"* 최후 방어. 이번 잔재에서 DB 가 사고를 막아줬다.

데이터 중복은 없었지만 **DB SELECT/INSERT 부하는 N+1배**. 모니터링 그래프 상 매 5~10분마다 DB CPU 가 살짝 튀는 패턴이 이것.

## 1차 청소 시도 (over-engineering)

여기서 *"청소 작업"* 을 했는데, **5 커밋이나 들어간 게 함정**이었다. 시간순으로:

1. **yml `false` 처리** (production/develop)
2. *"이참에 `AttendanceScheduler` 클래스도 dead code 니까 지우자"* → SchedulerController 의존 끊기
3. `AttendanceScheduler.kt` 삭제
4. `NotificationScheduler.kt` 삭제
5. *"잠깐, 로컬에선 EventBridge 없는데 어떻게 cron 테스트?"* → `LocalAttendanceScheduler`, `LocalNotificationScheduler` 새로 만듦

**5번에서 멈췄어야 했다.** 이미 4번까지 가서 클래스 삭제했고, 그 영향으로 로컬 cron 이 사라졌고, 다시 wrapper 를 만든 꼴. *"같은 기능 하는 클래스를 지우고 이름만 바꿔서 다시 만든"* 왕복 낭비.

PR 리뷰 받다가 지적 받은 핵심 질문:

> *"그냥 yml flag 만 환경별로 바꾸면 되는 거 아니야? 클래스를 왜 지웠어?"*

다시 보니 정말 맞는 말이다. `AttendanceScheduler` 의 `@ConditionalOnProperty(matchIfMissing = false)` 가 이미 게이트 역할을 하고 있었다:

| 환경 | yml `scheduling.attendance.enabled` | 결과 |
|---|---|---|
| production | `false` (변경 후) | 빈 등록 안 됨 → `@Scheduled` 안 돔 ✓ |
| develop | `false` (변경 후) | 동일 ✓ |
| local | `true` (그대로) | 빈 등록 → `@Scheduled` 돔 ✓ |

**클래스 손댈 필요 없이 yml 만 바꾸면 끝.**

## 2차 청소 (simple)

PR 을 hard reset 하고 다시 시작.

```diff
# application-production.yml
 scheduling:
   attendance:
-    enabled: true
-    cron: "0 */10 * * * *"
+    enabled: false  # EventBridge → SQS 경로로 이관됨

# application-develop.yml — 동일 변경

# application-local.yml — 손대지 않음 (enabled: true 그대로)
```

**1 커밋, 2 파일, +3 -5 줄.** 끝.

비교:

| 방안 | 커밋 | 파일 | +추가 | -삭제 |
|---|---|---|---|---|
| 1차 시도 (over-engineering) | 5 | 6 | +130 | -215 |
| **2차 시도 (simple)** | **1** | **2** | **+3** | **-5** |

운영 동작은 동일. 로컬 cron 도 그대로 살아있음. 변경량은 1/50.

## 배운 점

### 1. 동료의 정정도 의심해본다

1차 가설은 틀렸지만, 2차 가설은 맞았다. *"이미 옮겼다"* 라는 정정을 받아들이되 남은 어색함 (yml `true`) 을 한 번 더 검증한 게 진짜 잔재 발견으로 이어졌다.

**새 정보를 받되, 남은 의문은 끝까지 추적하기.**

### 2. Minimum viable diff — "가장 작은 변경" 을 먼저 고민

이번 PR 의 가장 큰 교훈. 처음엔 *"이참에 dead code 도 같이 청소하자"* 라는 욕심으로 5 커밋을 만들었지만, 실제로 운영 문제를 해결하는 데 필요한 건 yml 2줄이었다.

> **면접 질문 💼**
> *"리팩토링 PR 사이즈를 어떻게 결정하시나요?"*
>
> *"이 문제를 해결하는 데 정말 필요한 최소 변경이 무엇인지"* 부터 정의. dead code 청소, 네이밍 개선, 추상화 같은 부가 작업은 별도 PR 로 분리. 한 PR 에 여러 의도가 섞이면 리뷰가 어려워지고 revert 도 곤란해진다.
>
> 이번 케이스: 운영 잔재 청소(yml flag flip) 와 dead code 정리(클래스 삭제) 는 별개 의도였는데 한 PR 에 묶었다가 dead code 가 진짜 dead 가 아니었음 (로컬 cron 용)을 뒤늦게 발견.

### 3. `@ConditionalOnProperty` + `matchIfMissing=false` 의 위력

이 한 줄 안전장치가 이미 있었기 때문에 yml 하나만 바꾸면 끝났다. 만약 클래스에 게이팅이 없었다면 진짜로 클래스를 삭제해야 했을 것.

> **면접 질문 💼**
> *"환경마다 다른 동작이 필요할 때 Spring 에선 어떻게 분리하나요?"*
>
> `@Profile` + `@ConditionalOnProperty` 조합. 이번 케이스처럼 *"운영에선 false 가 기본, 로컬에선 true 가 기본"* 같은 환경별 동작 분기를 별도 클래스 추가 없이 같은 클래스로 처리 가능.

### 4. 마이그레이션 = 전환 + 청소

원본 PR 설명에 *"전환 완료 후 enabled false 처리 필요"* 라고 후속 작업이 명시돼 있었지만 한 달 넘게 잊혀졌다.

체크리스트:
- [ ] 새 경로 추가 (예: SQS Consumer)
- [ ] 기존 경로 `@ConditionalOnProperty(matchIfMissing = false)` 게이트
- [ ] yml 플래그 `false` ← **자주 빠짐**
- [ ] 후속 작업은 Jira 티켓으로 끊어두기 (PR 설명에만 적으면 잊혀짐)

### 5. DB UNIQUE 제약 = 운영의 마지막 방어선

이번에 사고가 안 난 건 순전히 `UNIQUE` 덕분. *"이 이벤트는 같은 키에 대해 한 번만"* 이 도메인 룰이면 **DB 스키마 레벨에 UNIQUE** 거는 게 안전. 마이그레이션 같은 일시적 카오스에서도 무결성을 지켜준다.

---

PR 5 커밋 → 1 커밋. 잘못 든 길도 길 가는 과정이긴 하지만, *"이 문제를 푸는 데 필요한 가장 작은 변경"* 부터 묻는 습관이 있었다면 더 빨리 도착했을 거다.
