---
title: "실시간 활동 로그 파이프라인 (1) — 문제 정의와 설계 결정"
date: 2026-06-30 09:00:00 +0900
categories: [Backend, 활동 로그 파이프라인]
tags: [Spring, Hibernate, ActiveMQ, CQRS]
---

> **시리즈: 실시간 활동 로그 파이프라인 — 큐 발행 단계**
> 1. **문제 정의와 설계 결정** ← 현재 글
> 2. [생산자 diff — "무엇이 바뀌었나"를 발행 시점에 계산하기]({% post_url 2026-06-30-activity-log-2-producer-diff %})
> 3. [트랜잭션 경계와 발행 타이밍]({% post_url 2026-06-30-activity-log-3-transaction-and-publish %})
> 4. [더 나아가서 — Outbox·CDC·Kafka를 알지만 쓰지 않은 이유]({% post_url 2026-06-30-activity-log-4-going-further %})

---

어드민에서 "지금 워크스페이스에서 무슨 일이 일어나고 있는지"를 실시간 피드로 보여주고 싶다는 요구가 들어왔다. 누가 티켓 상태를 바꿨는지, 담당자를 누구로 배정했는지, 근무를 시작했는지가 시간순으로 흐르는 화면. 흔한 "Activity Feed"다.

이 글은 그 첫 단추 — **"이벤트를 큐에 발행하는 데까지"** — 를 어떻게 설계하고 왜 그렇게 결정했는지에 대한 기록이다. 소비자가 큐에서 꺼내 DB에 적재하고, 조회 API를 만들고, WebSocket으로 실시간으로 밀어주는 건 **다음 단계**라 이 시리즈에서는 "예고"로만 다룬다. 먼저 발행만 단단히 해두는 게 목표였다.

## 1. 범위를 먼저 잘랐다

기능 전체를 그리면 이렇게 된다.

```
도메인 변경  →  [발행]  →  큐  →  [소비/적재]  →  DB  →  [조회 API]  →  WebSocket 실시간
   (티켓 등)    ★이번★          (ActiveMQ)     (미구현)   (미구현)        (미구현)
```

전체를 한 PR에 다 넣으면 리뷰도 검증도 어렵다. 그래서 **"발행까지"** 로 1차 범위를 못박았다. 발행 경로만 먼저 안정화하면, 큐에 실제로 어떤 JSON이 쌓이는지를 눈으로 확인하면서 소비자 스키마를 차분히 설계할 수 있다. 큐는 생산자와 소비자를 시간적으로 분리해 주는 경계라서, 이렇게 단계를 끊기에 자연스러운 지점이기도 했다.

> 이 결정의 부수 효과: 현재 코드에는 소비자도, `activity_events` 테이블도, 조회 API도 없다. 큐에 메시지가 쌓이는 것까지가 검증 대상이다.

## 2. 핵심 결정 ① — 기존 audit 인프라에 "올라탄다"

우리 백엔드에는 이미 변경 이력(audit)을 남기는 인프라가 있었다. 엔티티가 바뀌면 `*_history` 테이블에 스냅샷을 쌓는 구조다. 흐름은 이랬다.

```
엔티티 변경 → @PostPersist/@PostUpdate/@PostRemove
           → EntityHistoryListener 가 스냅샷 생성
           → ApplicationEventPublisher.publishEvent(EntityHistoryEvent)
           → (AFTER_COMMIT) EntityHistoryEventHandler 가 *_history INSERT
```

여기서 고민했다. 활동 로그를 위해 **별도의 변경 감지 경로**를 또 만들 것인가, 아니면 이미 잘 돌고 있는 이 이벤트 흐름에 **수신자 하나를 더 붙일** 것인가.

후자를 택했다. `EntityHistoryListener`가 던지는 `EntityHistoryEvent` 하나에 큐 발행 리스너(`ActivityEventRelay`)를 **형제 구독자**로 추가했다. 변경을 감지하고 스냅샷을 만드는 코드는 이미 검증돼 있으니, 나는 "그 이벤트를 받아서 큐로 보내는 부분"만 새로 쓰면 된다.

```kotlin
// 발신자는 그대로 — 리스너가 flush 때 한 번 던진다
eventPublisher.publishEvent(
  EntityHistoryEvent(history = history, changes = changes),
)
```

이렇게 하면 audit 저장(`EntityHistoryEventHandler`)과 큐 발행(`ActivityEventRelay`)이 **같은 원인(이벤트)에서 갈라져 나온 독립 구독자**가 된다. 둘은 서로의 완료를 기다리지 않고, 한쪽이 실패해도 다른 쪽에 영향이 없다. 발신자 코드는 한 줄도 안 고치고 수신자만 추가하는, 깔끔한 fan-out이다.

### 발행 코드를 한 곳에 모은 이유

발행 로직을 도메인 서비스마다 흩뿌리지 않고 `ActivityEventRelay` **한 클래스**에 모았다. 도메인 서비스는 "티켓 상태를 바꾼다"는 자기 일만 하고, "그게 활동 로그가 된다"는 사실은 모른다. 발행은 이벤트를 구독하는 릴레이가 중앙에서 책임진다.

이 선택의 실질적 이득은 **새 엔티티를 피드에 편입시킬 때 드러난다.** 발행 코드를 건드릴 필요가 없다. 마커 인터페이스 하나만 붙이면 된다 (다음 항목).

## 3. 핵심 결정 ② — `QueuePublishable` opt-in 마커

`*_history`를 남기는 엔티티는 14종쯤 된다. 그렇다고 그게 전부 활동 피드에 나가야 하는 건 아니다. 어떤 엔티티를 큐로 보낼지를 명시적으로 고를 장치가 필요했다.

마커 인터페이스로 해결했다.

```kotlin
/**
 * 활동 이벤트 큐 적재 대상 표시용 마커 인터페이스 (플래그).
 *
 * history 엔티티가 이 마커를 구현하면, audit(*_history) 저장과 별개로
 * ActivityEventRelay가 해당 변경을 ActiveMQ 큐에도 발행한다.
 * 마커가 없는 엔티티는 audit만 수행하고 큐로는 가지 않는다(opt-in).
 */
interface QueuePublishable
```

릴레이는 이렇게 게이트한다.

```kotlin
@TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
fun onEntityHistory(event: EntityHistoryEvent) {
  val history = event.history
  if (history !is QueuePublishable) return   // ← opt-in 게이트
  // ... 메시지 만들어 큐로 발행
}
```

**메서드가 하나도 없는** 게 핵심이다. 릴레이가 history 스냅샷을 통째로 직렬화해서 싣기 때문에, 엔티티별 매핑 디스크립터 같은 게 필요 없다. 마커는 그냥 "큐에 보낼지 말지"만 표시하는 플래그다. 현재 이 마커를 단 건 `TicketHistory` 하나뿐이라, 실제로 큐에 흐르는 건 티켓 변경뿐이다.

```kotlin
class TicketHistory(
  // ... 스냅샷 필드들
) : BaseHistoryEntity(...),
  QueuePublishable   // ← 이 한 줄이 opt-in
```

스케줄·근무 같은 다른 엔티티를 나중에 편입할 때는, 해당 `XxxHistory`에 `: QueuePublishable`만 추가하면 발행 경로에 자동으로 올라탄다. (정확히는 diff 레지스트리 등록도 한 블록 필요한데, 그건 [2편]({% post_url 2026-06-30-activity-log-2-producer-diff %})에서.)

## 4. 핵심 결정 ③ — ECST(Event-Carried State Transfer)

메시지에 "무엇을" 실을 것인가. 두 방향이 있다.

| 방식 | 메시지 내용 | 소비자가 하는 일 |
|------|------------|------------------|
| **얇은 이벤트 (notification)** | `"티켓 501이 바뀜"` 만 | 소비자가 다시 DB를 조회해 상세를 채움 |
| **ECST** | history 스냅샷 **통째로** | 소비자가 메시지만으로 적재 가능 (DB 조회 0) |

후자, **Event-Carried State Transfer**를 택했다. 메시지가 자기완결적이라 소비자가 메시지를 받아 적재할 때 원본 DB를 다시 조회할 필요가 없다. history 스냅샷에는 `id`, `title`, `status`, `workspaceId`, `assigneeId` 등 그 시점의 상태가 다 들어 있으니까.

```kotlin
val message = ActivityEventMessage(
  entityType = history::class.simpleName ?: "Unknown",
  action = history.operationType.name,            // INSERT / UPDATE / DELETE
  actorAccountId = history.operationBy,
  occurredAt = history.operationTimestamp,
  payload = objectMapper.valueToTree(history),     // ← 스냅샷 통째 (ECST)
  changes = event.changes,                         // ← diff (2편 주제)
)
```

이렇게 하면 소비자를 **"DB 읽기 0의 순수 writer"** 로 설계할 여지가 생긴다. 메시지에 이미 모든 게 있으니, 소비자는 멱등 체크하고 INSERT만 하면 된다. (단, 표시용 *이름*은 예외다 — `assigneeId`는 실어도 "홍길동"이라는 이름은 안 싣는다. 이름은 시간이 지나면 바뀌니까 조회 시점에 join해서 푸는 게 맞다. 이 원칙은 [2편]({% post_url 2026-06-30-activity-log-2-producer-diff %})에서 자세히.)

## 5. 결과 — 발행 경로의 전체 그림

지금까지 결정을 코드 흐름으로 이으면 이렇게 된다.

```
도메인 변경 (티켓 status/assignee UPDATE)
   │
   ▼ Hibernate flush
EntityHistoryInterceptor.onFlushDirty   ← before/after diff 계산 (2편)
   │  결과를 ActivityChangeHolder 에 저장
   ▼ @PostUpdate (같은 엔티티 인스턴스)
EntityHistoryListener
   │  스냅샷 생성 + 홀더에서 changes 꺼냄
   │  → publishEvent(EntityHistoryEvent(history, changes))
   ▼ AFTER_COMMIT
ActivityEventRelay
   │  history is QueuePublishable 게이트
   │  → ActivityEventMessage 조립 → jmsTemplate.convertAndSend (best-effort)
   ▼
ActiveMQ Topic : VirtualTopic.myapp.activity.events
   (JMS TextMessage, 본문 = JSON)
```

전체는 `activity.pipeline.enabled=true`일 때만 켜진다. dev는 기본 ON, prod는 미설정이라 OFF다. 비활성이면 Hibernate Interceptor 자체가 등록되지 않아 오버헤드가 0이다.

```kotlin
@Component
@ConditionalOnProperty(name = ["activity.pipeline.enabled"], havingValue = "true")
class EntityHistoryInterceptor(...) : Interceptor { ... }
```

## 다음 편 예고

발행 경로의 뼈대는 섰다. 그런데 위 그림에서 가장 까다로웠던 건 **"무엇이 바뀌었나(diff)"를 발행 시점에 계산하는 부분**이었다. `@PostUpdate`는 변경 *후* 값만 주고 *전* 값을 안 준다. before가 없으면 "ACTIVE → SUSPENDED" 같은 전이를 만들 수가 없다.

[2편]({% post_url 2026-06-30-activity-log-2-producer-diff %})에서는 이 문제를 Hibernate `Interceptor.onFlushDirty`로 어떻게 풀었는지, 그리고 `IdentityHashMap` 트랜잭션 홀더로 두 콜백을 어떻게 상관시켰는지를 다룬다.

---

> **다음 글:** [생산자 diff — "무엇이 바뀌었나"를 발행 시점에 계산하기]({% post_url 2026-06-30-activity-log-2-producer-diff %})
