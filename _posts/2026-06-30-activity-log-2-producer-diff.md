---
title: "실시간 활동 로그 파이프라인 (2) — 생산자 diff: 무엇이 바뀌었나"
date: 2026-06-30 09:10:00 +0900
categories: [Backend, 활동 로그 파이프라인]
tags: [Spring, Hibernate, ActiveMQ, CQRS]
---

> **시리즈: 실시간 활동 로그 파이프라인 — 큐 발행 단계**
> 1. [문제 정의와 설계 결정]({% post_url 2026-06-30-activity-log-1-problem-and-design %})
> 2. **생산자 diff — "무엇이 바뀌었나"를 발행 시점에 계산하기** ← 현재 글
> 3. [트랜잭션 경계와 발행 타이밍]({% post_url 2026-06-30-activity-log-3-transaction-and-publish %})
> 4. [더 나아가서 — Outbox·CDC·Kafka를 알지만 쓰지 않은 이유]({% post_url 2026-06-30-activity-log-4-going-further %})

---

[1편]({% post_url 2026-06-30-activity-log-1-problem-and-design %})에서 발행 경로의 뼈대를 세웠다. 메시지에는 history 스냅샷(`payload`)과 함께 `changes` 배열이 실린다. 이 글은 그 `changes` — **"이번 변경에서 무엇이 어떻게 바뀌었나"** 를 어떻게 계산하는지에 대한 기록이다.

활동 피드에 "담당자를 **1010 → 1012**로 변경했습니다"를 띄우려면, 변경 *후* 값(1012)만으론 부족하다. 변경 *전* 값(1010)도 있어야 한다. 그런데 이게 생각보다 까다로웠다.

## 1. `@PostUpdate`의 한계 — before가 없다

처음엔 audit이 쓰는 `@PostUpdate` 콜백에 diff를 얹으려 했다. 그런데 막혔다. JPA 라이프사이클 콜백은 **변경 후의 엔티티만** 준다.

```kotlin
@PostUpdate
fun postUpdate(entity: Any) {
  // entity.status == "SUSPENDED"  ← 현재값만 있음
  // 변경 전 값("ACTIVE")은?  ← 알 수 없음
}
```

`entity`는 이미 변경이 반영된 상태다. "전 값"을 알려면 별도로 어딘가에서 직전 스냅샷을 조회해 와야 한다. 실제로 우리 코드베이스의 다른 곳(요청관리 타임라인)은 `*_history` 테이블을 읽어 **인접 두 행을 비교**하는 방식으로 diff를 만든다. 동작은 하지만, 조회가 들어가고 "직전 행이 아직 없으면 비교가 어긋난다(stale)"는 문제가 따라온다.

발행 파이프라인에서는 이 조회를 없애고 싶었다.

## 2. 해결 — Hibernate `Interceptor.onFlushDirty`

Hibernate는 flush 시점에 더티 체킹을 한다. 즉 **로드된 원본(before)과 현재 상태(after)를 둘 다 메모리에 들고 있다.** 그걸 가로채면 된다. `org.hibernate.Interceptor`의 `onFlushDirty`가 정확히 그 둘을 인자로 준다.

```kotlin
@Component
@ConditionalOnProperty(name = ["activity.pipeline.enabled"], havingValue = "true")
class EntityHistoryInterceptor(
  private val activityDiffer: ActivityDiffer,
) : Interceptor {
  override fun onFlushDirty(
    entity: Any,
    id: Any,
    currentState: Array<Any?>,    // ← after
    previousState: Array<Any?>,   // ← before
    propertyNames: Array<String>, // ← 두 배열의 인덱스 의미
    types: Array<out Type>,
  ): Boolean {
    val changes =
      try {
        activityDiffer.diff(entity, propertyNames, previousState, currentState)
      } catch (e: Exception) {
        log.warn("ActivityDiffer.diff 실패 entity={}: {}", entity::class.simpleName, e.message)
        emptyList()
      }

    if (changes.isNotEmpty()) {
      ActivityChangeHolder.put(entity, changes)
    }
    return false   // 상태 배열을 수정하지 않음
  }
}
```

`previousState`와 `currentState`는 같은 길이의 배열이고, `propertyNames[i]`가 두 배열의 `i`번째 값이 무슨 필드인지 알려준다. **별도 DB 조회 0.** Hibernate가 어차피 더티 체킹을 위해 들고 있던 before를 그냥 빌려 쓰는 것이다.

이걸로 [1편]에서 언급한 "직전 행 stale" 문제가 **원천 제거**된다. 알고리즘은 인접 비교와 똑같지만, 소스가 DB 행이 아니라 메모리에 이미 있는 실제 DB 전이라는 게 다르다.

> Interceptor 등록은 별도 설정 클래스가 `HibernatePropertiesCustomizer`로 처리한다.
> ```kotlin
> props["hibernate.session_factory.interceptor"] = entityHistoryInterceptor
> ```

### 싱글톤인데 thread-safe한가?

Hibernate Interceptor는 세션 팩토리에 하나만 등록되는 싱글톤이다. 여러 스레드가 동시에 `onFlushDirty`를 때린다. 그래서 **인스턴스 필드에 상태를 절대 두지 않았다.** 모든 상태는 메서드 파라미터(before/after 배열)거나, 다음에 설명할 ThreadLocal 기반 홀더에만 둔다. 이건 트레이드오프가 아니라 필수다 — 안 지키면 요청 간 diff가 뒤섞이는 버그가 난다.

## 3. 두 콜백을 잇기 — `ActivityChangeHolder`

여기서 미묘한 문제가 생긴다. diff는 `onFlushDirty`에서 계산되는데, 이벤트 발행은 `@PostUpdate`에서 일어난다. 두 콜백은 다른 메서드다. `onFlushDirty`에서 만든 `changes`를 `@PostUpdate`까지 어떻게 전달하지?

키를 무엇으로 잡을까? id? 타입명? id+타입? 다 복잡하고 깨질 여지가 있다. 그런데 결정적인 사실 하나가 있었다.

> **`onFlushDirty`와 `@PostUpdate`는 같은 영속성 컨텍스트의 동일 엔티티 *인스턴스*를 받는다.**

같은 객체 레퍼런스라면 `IdentityHashMap`을 쓰면 된다. id나 타입명 매핑 없이, **객체 동일성(`===`)** 으로 정확히 상관된다.

```kotlin
object ActivityChangeHolder {
  private val RESOURCE_KEY = ActivityChangeHolder::class.java

  fun put(entity: Any, changes: List<ActivityChange>) {
    if (!TransactionSynchronizationManager.isActualTransactionActive()) return
    val map = getOrCreateMap()
    map[entity] = changes   // 키 = 엔티티 인스턴스 그 자체
  }

  fun get(entity: Any): List<ActivityChange>? {
    val map = TransactionSynchronizationManager.getResource(RESOURCE_KEY)
      as? IdentityHashMap<Any, List<ActivityChange>> ?: return null
    return map[entity]
  }
  // ...
}
```

홀더는 트랜잭션마다 새 `IdentityHashMap`을 `TransactionSynchronizationManager`(ThreadLocal 기반)에 bind하고, 트랜잭션 완료(commit/rollback) 시 unbind한다. ThreadLocal이라 스레드 간 격리가 공짜이고, 완료 시 정리하니 메모리 누수도 없다.

```kotlin
private fun getOrCreateMap(): IdentityHashMap<Any, List<ActivityChange>> {
  // ... 기존 맵 있으면 반환, 없으면 새로 만들어 bind
  TransactionSynchronizationManager.registerSynchronization(
    object : TransactionSynchronization {
      override fun afterCompletion(status: Int) {
        TransactionSynchronizationManager.unbindResourceIfPossible(RESOURCE_KEY)
      }
    },
  )
  // ...
}
```

그러면 `@PostUpdate`(리스너)는 이렇게 홀더에서 꺼내 이벤트에 실어 보낸다.

```kotlin
// EntityHistoryListener
val changes = ActivityChangeHolder.get(entity) ?: emptyList()
getInstance().eventPublisher.publishEvent(
  EntityHistoryEvent(history = history, changes = changes),
)
```

전체 상관 관계를 그림으로:

```
flush 시점                          @PostUpdate 시점
─────────                          ──────────────
onFlushDirty(entity, before, after)
   │ diff 계산
   │ holder.put(entity, changes) ──┐  (키 = entity 인스턴스)
                                    │
                          IdentityHashMap (tx 스코프)
                                    │
                                    └──> holder.get(entity) → changes
                                            EntityHistoryListener 가 꺼냄
                                            → EntityHistoryEvent(history, changes)
```

## 4. `ActivityDiffer` — 화이트리스트 레지스트리

diff의 실제 계산은 `ActivityDiffer`가 한다. 핵심 설계는 **"모든 필드를 자동으로 비교하지 않는다"** 는 것이다. 엔티티별로 **수동 화이트리스트**를 둔다.

```kotlin
private val REGISTRY: Map<KClass<*>, EntityDiffSpec> =
  mapOf(
    Ticket::class to
      EntityDiffSpec(
        mapOf(
          "status"      to FieldDiffRule("STATUS_CHANGED", ENUM_NAME),
          "priority"    to FieldDiffRule("PRIORITY_CHANGED", ENUM_NAME),
          "title"       to FieldDiffRule("TITLE_CHANGED", AS_IS),
          "description" to FieldDiffRule("DESCRIPTION_CHANGED", AS_IS),
          "assignee"    to FieldDiffRule("ASSIGNEE_CHANGED", ACCOUNT_ID),
          "location"    to FieldDiffRule("LOCATION_CHANGED", ENTITY_ID),
          "removedAt"   to FieldDiffRule("REMOVED", AS_IS),
        ),
      ),
  )
```

비교 루프는 단순하다 — `propertyNames`에서 화이트리스트 필드의 인덱스를 찾아 before/after를 맞대본다.

```kotlin
fun diff(entity, propertyNames, previousState, currentState): List<ActivityChange> {
  val spec = specFor(entity) ?: return emptyList()   // 미등록 엔티티 → 빈 리스트
  val changes = mutableListOf<ActivityChange>()
  for ((field, rule) in spec.fields) {
    val idx = propertyNames.indexOf(field)
    if (idx < 0) continue
    val from = rule.extract(previousState[idx])
    val to   = rule.extract(currentState[idx])
    if (from != to) {
      changes += ActivityChange(field, rule.changeType, from, to)
    }
  }
  return changes
}
```

### 왜 자동이 아니라 수동 매핑인가

"엔티티의 모든 더티 필드를 자동으로 diff하면 편하지 않나?" 싶지만, 수동 화이트리스트가 의도적인 선택이었다. 이유는 네 가지다.

1. **잡음 필드 제외.** `updatedAt`, `updatedBy` 같은 건 매번 바뀌지만 피드에 띄울 가치가 없다. 화이트리스트에 없으면 무시된다.
2. **`changeType` 부여.** 단순 "필드가 바뀜"이 아니라 `STATUS_CHANGED`, `ASSIGNEE_CHANGED` 같은 의미 라벨을 붙인다. 소비자(향후)가 이걸로 문구 템플릿을 고른다.
3. **status 전이 흡수.** 일시중단·재개·비활성화·완료는 전부 `status` 한 필드의 enum 전이다. 한 줄(`"status" to ...`)로 네 전이를 다 포착한다.
4. **soft-delete → REMOVED.** 우리 삭제는 hard delete가 아니라 `removedAt`에 타임스탬프를 찍는 soft-delete다. `status`는 안 바뀌니 status로는 안 잡힌다. `removedAt`의 `null → 타임스탬프` 전이를 `REMOVED`로 잡는다(복원 시 역방향도 같은 타입).

```kotlin
// status 하나로 SUSPENDED·ACTIVE·DEACTIVATED·COMPLETED 전이를 모두 포착
"status" to FieldDiffRule("STATUS_CHANGED", ENUM_NAME),
// 삭제는 soft-delete(removedAt만 set, status 불변) → status로는 안 잡힘
"removedAt" to FieldDiffRule("REMOVED", AS_IS),
```

## 5. 값은 id·코드만 — 이름은 절대 안 싣는다

추출기(`extract`)는 네 종류를 재사용한다.

| 추출기 | 동작 | 예시 |
|--------|------|------|
| `ENUM_NAME` | enum → name(코드 문자열) | `TicketStatus.ACTIVE` → `"ACTIVE"` |
| `AS_IS` | 스칼라 그대로 | `"엘리베이터 점검"`, `Instant`, `Boolean` |
| `ENTITY_ID` | 연관 → `getId()` | `Location` → `id` |
| `ACCOUNT_ID` | 연관 → `getAccountId()` | `WorkerProfile` → `accountId` |

여기서 **단호하게 지킨 원칙**: 연관(사람/대상) 필드는 **id만** 뽑는다. 이름은 절대 안 뽑는다.

```kotlin
data class ActivityChange(
  val field: String,       // "assignee"
  val changeType: String,  // "ASSIGNEE_CHANGED"
  val from: Any?,          // 1010  ← id, 이름 아님
  val to: Any?,            // 1012  ← id, 이름 아님
)
```

왜? 이름은 시간이 지나면 바뀐다. 발행 시점에 "홍길동"을 freeze해 두면, 그 사람이 개명하거나 탈퇴했을 때 피드에 옛 이름이 박제된다. **id만 저장하고, 표시할 때 join해서 현재 이름으로 푸는** 게 맞다(삭제된 대상은 `COALESCE`로 "(삭제됨)" 처리 예정). 이건 메시지를 가볍게 유지하는 효과도 있다.

> 연관 객체는 Hibernate 프록시일 수 있어서, id getter를 리플렉션으로 호출한다. `@Id` 프로퍼티면 프록시 초기화 없이 읽히고, 아니면 lazy-init이 1회 발생할 수 있다(트랜잭션 내, 이름 조회는 아님).

## 6. 결과 — `changes` 배열

티켓 상태와 담당자를 동시에 바꾸면 메시지의 `changes`는 이렇게 나온다.

```json
"changes": [
  { "field": "status",   "changeType": "STATUS_CHANGED",   "from": "ACTIVE", "to": "SUSPENDED" },
  { "field": "assignee", "changeType": "ASSIGNEE_CHANGED", "from": 1010,     "to": 1012 }
]
```

`status`는 enum 코드, `assignee`는 accountId. 이름은 어디에도 없다. UPDATE만 `changes`가 채워지고, INSERT/DELETE나 화이트리스트 미등록 엔티티는 빈 배열이다 (현재 `onSave`/`onDelete`는 구현하지 않았다 — 1차 범위에서 제외).

### 새 엔티티를 피드에 추가하는 법

[1편]의 `QueuePublishable` 마커와 합치면, 새 엔티티 편입은 딱 두 군데만 손대면 된다.

```kotlin
// ① 해당 XxxHistory 에 마커 추가 (큐 발행 opt-in)
class TicketScheduleHistory(...) : BaseHistoryEntity(...), QueuePublishable

// ② ActivityDiffer.REGISTRY 에 한 블록 추가 (diff 규칙)
TicketSchedule::class to EntityDiffSpec(
  mapOf(
    "status"      to FieldDiffRule("SCHEDULE_STATUS_CHANGED", ENUM_NAME),
    "scheduledAt" to FieldDiffRule("SCHEDULE_TIME_CHANGED", AS_IS),
  ),
),
```

발행 코드(`ActivityEventRelay`)는 한 줄도 안 건드린다. [1편]에서 발행 로직을 한 곳에 모은 보람이 여기서 나온다.

## 다음 편 예고

diff까지 계산해서 메시지를 조립했다. 그런데 **언제** 큐로 보내야 할까? diff는 커밋 *전*(flush)에 계산되는데, 발행은 커밋이 확정된 *후*에 해야 한다. 커밋이 롤백되면 발행하면 안 되니까.

[3편]({% post_url 2026-06-30-activity-log-3-transaction-and-publish %})에서는 트랜잭션 경계를 다룬다. 왜 발행을 `AFTER_COMMIT`에 두는지, audit은 `REQUIRES_NEW`로 새 트랜잭션을 여는데 큐 발행은 왜 트랜잭션을 아예 안 여는지, 그리고 "커밋은 됐는데 발행은 실패하는 틈(dual-write)"을 어떻게 best-effort로 다루는지.

---

> **이전 글:** [문제 정의와 설계 결정]({% post_url 2026-06-30-activity-log-1-problem-and-design %})
> **다음 글:** [트랜잭션 경계와 발행 타이밍]({% post_url 2026-06-30-activity-log-3-transaction-and-publish %})
