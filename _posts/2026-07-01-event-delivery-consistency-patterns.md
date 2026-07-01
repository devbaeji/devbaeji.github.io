---
title: "이벤트 전달·정합성 패턴 — 현업 표준으로 보는 dual-write 문제와 4가지 해법 (그리고 우리는 왜 best-effort를 골랐나)"
date: 2026-07-01 10:00:00 +0900
categories: [Backend, Event-Driven]
tags: [Transactional-Outbox, CDC, Debezium, Kafka, ActiveMQ, Spring, Transaction]
---

> **[실시간 활동 로그 파이프라인]({% post_url 2026-06-30-activity-log-1-problem-and-design %}) 시리즈의 심화편.**
> [4편]({% post_url 2026-06-30-activity-log-4-going-further %})에서 "Outbox·CDC·Kafka를 알지만 쓰지 않았다"고 적었다. 이 글은 그 판단의 근거를 한 층 더 판다. **AFTER_COMMIT 발행이 왜 dual-write 안티패턴인지**, 현업이 이 문제를 푸는 **4가지 표준 해법**은 각각 무엇이며, 그 스펙트럼 위에서 **우리는 왜 가장 싼 쪽(best-effort)을 의도적으로 골랐는지**를 코드 레벨로 정리한다. [브로커 한 개, 두 패턴]({% post_url 2026-07-01-broker-one-two-messaging-patterns %})이 "브로커 안에서 어떤 메시징 패턴을 쓰나"였다면, 이 글은 "이벤트를 정합성 있게 흘리는 법"이다.

---

이벤트 기반 아키텍처에서 가장 조용히, 그러나 가장 자주 사람을 무는 문제가 하나 있다. **"DB에는 커밋됐는데 이벤트는 발행이 안 된 상태"** 다. 로그에도 잘 안 남고, 재현도 어렵고, 나중에 "피드에 한 건이 왜 없지?"로 발견된다. 이게 dual-write 문제다.

먼저 핵심 원칙 하나를 못 박고 시작한다. 이 글 전체가 이 문장의 부연이다.

> **"정답은 데이터 중요도가 정한다."**
> 정합성을 일부 포기하는 것도, 절대 안 포기하는 것도 **둘 다 표준**이다. audit·알림·분석·활동피드는 best-effort로 싸게 가고, 돈·주문·재고·정산처럼 **반드시 전달돼야 하는 것만** Outbox/CDC로 승격한다.

## 1. dual-write 안티패턴 — 그리고 우리가 그 안에 있다는 인정

문제의 구조는 단순하다. 하나의 논리적 작업이 **두 개의 서로 다른 저장소에 쓰기(write)** 를 해야 할 때 생긴다.

1. 비즈니스 DB에 커밋 (예: 티켓 status를 SUSPENDED로 UPDATE)
2. 메시지 브로커에 이벤트 발행 (예: 큐로 `TicketChanged` 전송)

이 둘은 **하나의 원자적 트랜잭션으로 묶이지 않는다.** DB 트랜잭션과 브로커 전송은 서로 다른 시스템이라, 둘을 한 번에 커밋해줄 공용 트랜잭션 코디네이터가 (2단계 커밋을 도입하지 않는 한) 없다. 그래서 1은 성공하고 2는 실패하는 틈이 반드시 존재한다.

> **Dual-write**
>
> 하나의 논리 작업이 두 개 이상의 독립 저장소(DB + 브로커, DB + 캐시, DB + 검색엔진 등)에 각각 쓰기를 해야 하는데, 그 쓰기들을 하나의 원자적 트랜잭션으로 보장할 수 없는 상황.
>
> 순서를 어떻게 뒤집어도 틈은 안 사라진다. "발행 먼저 → DB 커밋"으로 바꾸면 이번엔 발행됐는데 커밋이 롤백돼 **없는 사건의 이벤트**가 나간다. "DB 먼저 → 발행"이면 커밋됐는데 발행이 실패해 **있는 사건의 이벤트가 증발**한다. 근본 해법은 순서 조정이 아니라 "이벤트를 DB와 같은 트랜잭션에 넣는 것"(Outbox)이거나 "DB 커밋 로그 자체를 이벤트원으로 삼는 것"(CDC)뿐이다.
{: .prompt-info }

솔직하게 인정하고 간다. **지금 우리 활동 로그 구조(AFTER_COMMIT 발행)가 바로 이 dual-write 형태다.** [3편]에서 다룬 대로, 비즈니스 트랜잭션이 커밋된 *후에* 큐로 발행하기 때문에, 커밋과 발행 사이에 프로세스가 죽거나 브로커가 잠깐 끊기면 그 이벤트는 어디에도 안 남는다. 이걸 숨기지 않고 드러내는 게 이 글의 출발점이다.

## 2. 우리 코드로 보는 트랜잭션 경계 — 같은 트리거, 네 가지 결과

dual-write를 이해하려면 "어디서, 어떤 트랜잭션 안에서 부가작업(audit 저장·큐 발행)을 실행하느냐"를 봐야 한다. 우리 코드에는 이 선택의 **좋은 예와 나쁜 예가 나란히** 들어 있다.

시작점은 하나다. 도메인 서비스가 비즈니스 트랜잭션(T1) 안에서 엔티티를 바꾼다.

```kotlin
// 도메인 서비스 — 비즈니스 트랜잭션 T1
@Transactional
fun changeStatus(ticketId: Long, status: TicketStatus) {
  val ticket = ticketRepository.findById(ticketId).orElseThrow()
  ticket.status = status          // dirty checking → flush 때 UPDATE
  // 여기서 부가작업(audit·큐)을 "어떻게" 트리거하느냐가 갈림길
}
```

flush 시점에 Hibernate가 `@PostUpdate` 콜백을 부르고, 우리 리스너가 도메인 이벤트를 **예약**한다. 주의할 점은 이 `publishEvent`가 실제 발행이 아니라, "T1이 커밋되면 그때 리스너들을 깨워라"는 **스프링 내부 이벤트 등록**이라는 것이다.

```kotlin
// EntityHistoryListener.kt — @PostUpdate, 아직 T1 내부. "예약"만 한다
@PostUpdate
fun postUpdate(entity: Any) = publishIfTrackable(entity, OperationType.UPDATE)

private fun publishIfTrackable(entity: Any, operationType: OperationType) {
  if (entity is HistoryTrackable<*>) {
    val history = entity.toHistorySnapshot(operationType, operationBy)
    // diff는 EntityHistoryInterceptor(onFlushDirty)가 미리 계산해 홀더에 담아둠(메모리, DB 아님)
    val changes = ActivityChangeHolder.get(entity) ?: emptyList()
    eventPublisher.publishEvent(EntityHistoryEvent(history, changes))  // ← T1 안, 발행 예약
  }
}
```

이 하나의 `EntityHistoryEvent`를 **두 개의 독립 리스너**가 AFTER_COMMIT에서 받는다. 그런데 둘의 트랜잭션 전략이 다르다.

audit 저장 리스너는 DB에 써야 하므로 **새 트랜잭션 T2를 연다.**

```kotlin
// EntityHistoryEventHandler.kt — audit: DB 쓰기 → 새 트랜잭션 필요
@TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
@Transactional(propagation = Propagation.REQUIRES_NEW)   // ← T1 밖, 새 T2
fun handle(event: EntityHistoryEvent) {
  entityManager.persist(event.history)   // *_history INSERT
}
```

큐 발행 릴레이는 DB를 안 쓰므로 **트랜잭션 자체가 없다.** 대신 발행 실패를 `runCatching`으로 흡수한다.

```kotlin
// ActivityEventRelay.kt — 큐 발행: DB 안 씀 → tx 불필요, best-effort
@TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)   // @Transactional 없음
fun onEntityHistory(event: EntityHistoryEvent) {
  val history = event.history
  if (history !is QueuePublishable) return          // ← opt-in 마커 게이트
  val message = ActivityEventMessage(
    entityType = history::class.simpleName ?: "Unknown",
    action = history.operationType.name,
    actorAccountId = history.operationBy,
    occurredAt = history.operationTimestamp,
    payload = objectMapper.valueToTree(history),
    changes = event.changes,
  )
  runCatching { jmsTemplate.convertAndSend(topic, message) }
    .onFailure { log.warn("활동 이벤트 발행 실패 type={}", history::class.simpleName, it) }
}
```

리뷰어가 던진 질문이 정확히 이 지점을 짚었다. *"부가작업이 잘못 묶이면 원래 트랜잭션과 엮이는 거 아닌가. REQUIRES_NEW는 트랜잭션을 하나 더 만들어서 괜찮을 듯한데."* 여기서 "엮인다"는 건 **부가작업(audit·큐)이 비즈니스 트랜잭션 T1 안에 함께 묶여서, 부가작업이 실패하면 본 비즈니스(티켓 변경)까지 롤백되는 상황**을 말한다. 같은 트리거라도 실행 위치와 트랜잭션 전략에 따라 결과가 네 가지로 갈린다.

| 방식 | 어디서 실행 | 트랜잭션 | 부가작업 실패하면 | 평가 |
|---|---|---|---|---|
| ① 서비스 메서드 안에서 직접 호출 | T1 내부 (커밋 전) | T1에 묶임 | 비즈니스까지 **같이 롤백** | 엮임 — 위험 ❌ |
| ② AFTER_COMMIT인데 REQUIRES_NEW 없이 DB 쓰기 | 커밋 후 (열린 tx 없음) | tx 없음 | DB 쓰기가 tx 없이 떠서 **보장 안 됨** | 불완전 ❌ |
| ③ AFTER_COMMIT + REQUIRES_NEW `(audit)` | 커밋 후 → 새 T2 | 새 T2 분리 | 비즈니스 유지, **audit만 유실** | 분리 성공 ✅ |
| ④ AFTER_COMMIT + tx 없음 `(큐 발행)` | 커밋 후 | tx 자체 불필요 | 비즈니스 유지, **큐만 유실(로그)** | DB 안 쓰니 OK ✅ |

①은 "엮임"의 정의 그대로다. 부가작업을 T1 안에서 직접 호출하면 그게 실패할 때 본 비즈니스까지 날아간다. ②는 흔한 착각인데, AFTER_COMMIT 시점엔 T1이 이미 닫혀 열린 트랜잭션이 없으므로, 여기서 `persist`를 부르면 트랜잭션 경계 밖 쓰기가 되어 보장되지 않는다. ③은 그래서 audit이 `REQUIRES_NEW`로 **새 T2를 명시적으로 여는** 것이고, ④는 큐 발행이 애초에 DB를 안 쓰니 트랜잭션이 필요 없어 가장 가볍다.

> **Q.** 큐 발행(④)이 "tx 없음"이라 안전하다면, audit(③)은 왜 굳이 `REQUIRES_NEW`로 트랜잭션을 하나 더 여나?
>
> **하는 일이 다르기 때문이다.** ④는 브로커로 메시지를 던질 뿐 DB에 안 쓴다. ③은 `*_history` 테이블에 `INSERT`를 해야 한다.
>
> DB 쓰기는 반드시 트랜잭션 안에서 일어나야 커밋·롤백이 보장된다. 그런데 AFTER_COMMIT 시점엔 T1이 이미 커밋돼 닫혀 있다. 여기서 그냥 `persist`를 부르면(②) 열린 트랜잭션이 없어 쓰기가 붕 뜬다. 그래서 audit은 `REQUIRES_NEW`로 **새 트랜잭션 T2를 열어** 그 안에서 INSERT하고 독립적으로 커밋한다. 큐 발행은 DB를 안 쓰니 이 문제 자체가 없어 tx를 생략한다.
>
> *진짜 기준은 "AFTER_COMMIT이냐"가 아니라 "그 리스너가 DB에 쓰느냐"다.* 쓰면 REQUIRES_NEW가 필수, 안 쓰면 tx 자체가 불필요. 이 한 줄이 ②③④를 가른다.
{: .prompt-info }

여기서 한 가지 정확성을 짚어둔다. `ActivityEventMessage`의 주석에는 예시로 `AttendanceHistory`가 적혀 있지만, **실제로 `QueuePublishable` 마커가 붙은 엔티티는 `TicketHistory` 하나뿐이다.** 즉 지금 큐에 흐르는 건 티켓 변경뿐이고, 나머지 `*_history`는 audit(③)만 타고 큐(④)로는 가지 않는다. 마커를 안 단 엔티티는 `if (history !is QueuePublishable) return`에서 걸러진다.

그리고 결정적인 점 — **③audit도 ④큐도 둘 다 best-effort다.** audit은 T2가 실패하면 audit만 유실되고, 큐는 발행이 실패하면 로그만 남긴다. 둘 다 본 비즈니스는 지킨다. 이게 dual-write를 "인정하고 격리한" 형태다. 문제를 없앤 게 아니라, **부가작업 실패가 본류를 오염시키지 않도록 분리**한 것이다. 이제 이 dual-write를 실제로 *없애는* 표준 해법들을 본다.

## 3. 현업 표준 4패턴 — 정합성 스펙트럼

dual-write를 다루는 방식은 "정합성을 얼마나 보장하느냐"의 스펙트럼으로 정리된다. 아래가 큰 그림이다.

| 패턴 | 정합성 | 핵심 메커니즘 | 운영 부담 | 적합 도메인 |
|---|---|---|---|---|
| ① Best-effort 비동기 | 일부 포기 | AFTER_COMMIT + `runCatching` | 없음 (앱만) | 감사로그·활동피드·분석·알림 |
| ② Transactional Outbox | 전달·정합성 보장 | 비즈니스+outbox 같은 T1 INSERT → 폴러 발행 | 낮음 (테이블+스케줄러) | 주문·결제·재고 등 유실 불가 |
| ③ CDC (Debezium) | 전달·정합성 보장 | DB 로그(binlog/WAL) 직접 → Kafka | 높음 (Debezium+Kafka) | 대규모·다수 서비스 |
| ④ Event Sourcing | 최상 | 이벤트가 진실의 원천, 상태는 재생 | 매우 높음 | 금융 원장 등 특수 도메인 |

### ① Best-effort 비동기 발행 — ≈ 지금 우리 구조

커밋 후 발행/기록을 따로 시도하고, 실패는 `runCatching`으로 로그에 흡수한다. 부가기능이 본 비즈니스를 못 막게 하는 **decoupling**이 목적이다. 위 2절의 ④가 정확히 이것이다.

- **장점**: 단순·빠름·본 비즈니스 보호. 추가 인프라 0.
- **단점**: 드물게 **조용한 유실**(커밋 성공 + 발행 실패). 재시도·재생 없음.
- **적합**: 한두 건 빠져도 화면이 안 망가지는 데이터. 활동 피드·분석·알림·audit.

### ② Transactional Outbox — 이벤트를 DB와 같은 트랜잭션에 넣는다

dual-write의 근본 원인이 "이벤트가 DB 트랜잭션 밖에 있다"는 것이라면, 해법은 명확하다. **이벤트를 DB 안으로 끌고 들어온다.** 비즈니스 데이터와 이벤트(outbox 행)를 **같은 트랜잭션 T1으로 INSERT**하면, 커밋되는 순간 이벤트도 원자적으로 함께 남는다. 브로커 전송이라는 위험한 원격 작업은 T1 밖으로 미룬다.

```kotlin
// 1) outbox 엔티티 — 비즈니스 테이블과 같은 DB에 산다
@Entity
@Table(name = "outbox_event")
class OutboxEvent(
  @Id @GeneratedValue val id: Long = 0,
  val aggregateType: String,          // "Ticket"
  val eventType: String,              // "TicketChanged"
  @Column(columnDefinition = "json")
  val payload: String,                // 직렬화된 메시지
  val createdAt: Instant = Instant.now(),
  var publishedAt: Instant? = null,   // 발행 성공 마킹 (null = 미발행)
)
```

```kotlin
// 2) 비즈니스 쓰기와 outbox INSERT를 "같은 T1"에 넣는다 — 여기가 핵심
@Transactional
fun changeStatus(ticketId: Long, status: TicketStatus) {
  val ticket = ticketRepository.findById(ticketId).orElseThrow()
  ticket.status = status                            // 비즈니스 변경
  outboxRepository.save(                            // 같은 트랜잭션에 이벤트도 INSERT
    OutboxEvent(
      aggregateType = "Ticket",
      eventType = "TicketChanged",
      payload = objectMapper.writeValueAsString(TicketChanged(ticketId, status)),
    ),
  )
  // 커밋되면 status 변경과 outbox 행이 "함께" 남거나 "함께" 롤백된다 (원자적)
}
```

```kotlin
// 3) 폴러/릴레이 — 커밋된 outbox를 읽어 브로커로 발행하고 성공 시 마킹
@Scheduled(fixedDelay = 1000)
@Transactional
fun relayOutbox() {
  val batch = outboxRepository.findTop100ByPublishedAtIsNullOrderByCreatedAt()
  for (e in batch) {
    runCatching { jmsTemplate.convertAndSend(topic, e.payload) }
      .onSuccess { e.publishedAt = Instant.now() }   // 성공해야만 마킹 → 실패 시 다음 폴에서 재시도
      .onFailure { log.warn("outbox 발행 재시도 대기 id={}", e.id) }
  }
}
```

핵심은 T1 안에 **로컬 INSERT만** 두는 것이다(안전). 위험한 원격 발행은 T1 밖 폴러로 미룬다. 발행이 실패하면 `publishedAt`이 null로 남아 다음 폴에서 다시 시도되므로, **성공할 때까지 재시도되는 at-least-once**가 된다. [microservices.io가 정리한 마이크로서비스의 사실상 표준 레시피](https://microservices.io/patterns/data/transactional-outbox.html)다.

> **Q.** Outbox 폴러가 발행에 성공하고 `publishedAt`을 마킹하기 직전에 프로세스가 죽으면 어떻게 되나? 그 이벤트는 유실되나?
>
> 유실되지 않는다. 대신 **중복 발행된다.**
>
> 발행은 성공했는데 `publishedAt` UPDATE가 커밋되기 전 죽으면, 그 outbox 행은 여전히 `publishedAt = null`이다. 다음 폴러가 이걸 미발행으로 보고 **한 번 더 발행**한다. 즉 Outbox는 "안 잃는 것(at-least-once)"은 보장하지만 "정확히 한 번"은 보장하지 못한다.
>
> 그래서 Outbox는 **반드시 멱등 소비자와 세트**로 쓴다. 메시지에 `eventId`를 실어 소비자가 이미 처리한 id면 무시하게 한다. 우리 `ActivityEventMessage.eventId`(UUID)가 정확히 그 자리다.
>
> *Outbox의 진짜 계약은 "무손실 + 중복 가능"이다.* 무손실은 outbox 테이블이, 중복 제거는 소비자 멱등성이 나눠 책임진다. 둘 중 하나만 있으면 반쪽짜리다.
{: .prompt-tip }

### ③ CDC (Change Data Capture) — DB 커밋 로그 자체를 이벤트원으로

Outbox는 outbox 테이블이라는 앱 레벨 장치를 추가한다. CDC는 한 발 더 나아가 **DB가 원래 쓰고 있던 트랜잭션 로그를 직접 읽는다.** Debezium 같은 도구가 MySQL binlog / PostgreSQL WAL을 tail하면서 커밋된 변경을 그대로 이벤트로 흘린다. **"커밋된 것 = 곧 이벤트"** 라 정합성이 DB 커밋에 자동으로 묶인다. 앱 코드는 거의 손대지 않는다.

여기서 잠깐 "트랜잭션 로그가 대체 뭐길래 이벤트원이 되나"를 짚고 가야 CDC의 운영 함정이 이해된다.

> **트랜잭션 로그 (binlog / WAL / redo)**
>
> DB가 데이터 파일을 실제로 갱신하기 **전에**, "무엇을 어떻게 바꿀지"를 먼저 순차 기록하는 append-only 로그. 원래 목적은 **크래시 복구** — 서버가 갑자기 죽어도 이 로그를 재생(replay)해 커밋된 트랜잭션을 되살린다(WAL = Write-Ahead Logging).
>
> 이 로그가 "커밋된 모든 변경을 순서대로 담은 신뢰할 수 있는 기록"이다 보니, 용도가 확장됐다. **복제**(replica가 로그를 재생해 따라옴) → **PITR**(특정 시점 복원) → **CDC**(로그를 읽어 외부로 이벤트 발행). CDC는 이 크래시 복구용 로그에 **또 하나의 독자(consumer)로 올라타는** 것이다.
>
> DB별로 이름과 형식이 다르다. MySQL은 **binlog**(ROW 포맷이면 변경 전/후 이미지를 다 담음), PostgreSQL은 **WAL + Logical Decoding + Replication Slot**, Oracle은 **Redo + Supplemental Logging**. Debezium은 이 각각을 읽어 통일된 이벤트로 변환한다.
{: .prompt-info }

CDC가 배치 ETL(주기적으로 테이블을 통째로 스캔해 diff)보다 나은 이유가 여기서 나온다. 로그 기반은 **지연이 초/밀리초 단위**고, 이미 DB가 쓰고 있는 로그를 읽을 뿐이라 **원본 DB 부하가 거의 없으며**, 배치 스캔이 놓치기 쉬운 **DELETE도 로그에 남아 자연히 캡처**된다. Debezium이 뱉는 이벤트는 대략 이런 형태다.

```json
{
  "op": "u",                        // c=create, u=update, d=delete, r=read(스냅샷)
  "before": { "id": 501, "status": "ACTIVE" },
  "after":  { "id": 501, "status": "SUSPENDED" },
  "source": { "table": "tickets", "ts_ms": 1719800000000, "pos": "..." }
}
```

흥미로운 건 이 `before`/`after`가 [2편]({% post_url 2026-06-30-activity-log-2-producer-diff %})의 Hibernate diff와 **같은 정보**라는 점이다. 우리는 그걸 앱 레벨 Interceptor로 잡고, CDC는 DB 로그 레벨로 잡는다. 정보는 같고 잡는 층이 다르다.

그런데 CDC는 공짜가 아니다. **크래시 복구용 로그에 올라타기 때문에 생기는 운영 함정**이 명확하다. 이게 우리가 CDC를 안 쓴 실제 근거다.

> **트랜잭션 로그를 이벤트원으로 쓸 때의 운영 함정**
>
> **① binlog 무한 증가 → 디스크 폭증.** binlog는 커밋마다 계속 쌓인다. 보존 정책(`binlog_expire_logs_seconds` 등)이 느슨하면 디스크가 찬다. 반대로 너무 짧게 잡으면 CDC 커넥터가 잠깐 죽은 사이 binlog가 이미 삭제돼 **이벤트를 영구 유실**한다. 보존 기간을 CDC 커넥터의 다운타임 SLA보다 길게 잡아야 한다.
>
> **② 비활성 replication slot → WAL 폭증 → DB 정지.** PostgreSQL은 replication slot이 "이 slot이 아직 안 읽은 WAL은 지우지 마라"고 DB에 지시한다. CDC 커넥터가 죽어 slot이 비활성으로 방치되면, DB는 그 slot을 위해 WAL을 **무한히 붙들고** 있다가 디스크가 차서 **DB 자체가 멈춘다**. `max_slot_wal_keep_size`로 상한을 걸어 slot을 포기시키는 안전장치가 필요하다(대신 그 slot의 CDC는 유실).
>
> **③ 보존 정책에 CDC SLA를 포함해야 한다.** 로그 보존은 원래 "복구에 며칠분이면 충분"이었지만, CDC를 붙이는 순간 "커넥터 최대 다운타임"이라는 새 제약이 추가된다. DBA와 앱 팀이 이 숫자를 합의하지 않으면 조용히 유실되거나 조용히 DB가 멈춘다.
{: .prompt-warning }

정리하면, CDC는 **정합성은 공짜로 주는 대신 운영 복잡도를 DB 인프라 층으로 옮긴다.** 대규모·다수 서비스 환경에선 이 트레이드오프가 남는 장사지만, POC·단일 앱·저볼륨에선 Debezium/Kafka 클러스터 운영과 위 함정 관리가 **명백한 오버엔지니어링**이다. 이게 [4편]에서 "CDC를 알지만 안 썼다"고 한 판단의 구체적 근거다.

### ④ Event Sourcing — 상태 대신 이벤트가 진실

상태를 저장하는 대신 **이벤트 자체를 진실의 원천**으로 삼고, 현재 상태는 이벤트를 재생해 만든다. "티켓이 지금 SUSPENDED"를 저장하는 게 아니라 "생성됨 → 배정됨 → 중단됨" 이벤트 열을 저장하고, 필요할 때 접어서 현재 상태를 계산한다. 정합성·이력추적이 최상급이지만 도입·운영·조회 모델 재구성 비용이 크다. 금융 원장처럼 "모든 변화의 완전한 감사 추적"이 도메인 요구인 곳에서 선택적으로 쓴다.

## 4. exactly-once는 신화다

여기까지 오면 자연스러운 질문이 나온다. "그래서 정확히 한 번 전달되게 하려면?" 답은 조금 허무하다.

> **"exactly-once 전달"은 사실상 불가능하다.** 분산 시스템에서 네트워크는 언제든 끊기고, "보냈는데 ack를 못 받은" 상황과 "아예 안 보내진" 상황을 발신자는 구분할 수 없다. 재시도하면 중복될 수 있고, 안 하면 유실될 수 있다. 이 딜레마에 완벽한 해는 없다.

그래서 현업의 실무 목표는 exactly-once가 아니라 그 **"효과"** 다.

- **at-least-once 전달** — 재시도로 절대 안 잃는다 (Outbox의 `publishedAt` 폴링, CDC의 로그 재개).
- **멱등 소비자** — 같은 이벤트가 두 번 와도 한 번만 반영한다 (`eventId`로 중복 무시).

이 둘을 곱하면 **결과적으로 exactly-once처럼 보이는 시스템**이 된다. 결제 시스템조차 이 방식을 쓴다. "정확히 한 번 보낸다"가 아니라 "여러 번 보내도 한 번만 처리된다"로 문제를 옮긴 것이다.

우리 코드에서 이 멱등 키 자리는 이미 확보돼 있다. `ActivityEventMessage.eventId`(UUID)가 그것이다. 지금은 best-effort라 재시도(at-least-once)가 없어 반쪽이지만, Outbox로 승격하는 순간 이 `eventId`가 중복 제거 키로 그대로 작동한다. **멱등 소비자를 미리 준비해두고, 전달 보장은 나중에 붙이는** 순서다.

```kotlin
// 소비자(미래) — eventId 유니크 제약으로 중복 흡수
fun consume(message: ActivityEventMessage) {
  if (activityRepository.existsByEventId(message.eventId)) return  // 이미 처리 → 무시(멱등)
  activityRepository.save(message.toEntity())                     // 최초만 적재
}
```

## 5. 결론 — 데이터 중요도가 정한다

네 패턴을 다 봤으니, 우리 활동 로그를 이 스펙트럼 위에 놓는다.

활동 로그는 **"지금 워크스페이스에서 무슨 일이 일어나는지"를 보여주는 피드**다. 분석·표시용이고, 천 건 중 한 건이 드물게 빠진다고 사업이 틀어지지 않는다. 복구 원본도 있다 — `*_history` 테이블이 남으니 최악의 경우 백필로 메운다. 이 데이터 중요도에는 **①best-effort가 정답**이다. 한 건을 안 잃으려고 outbox 테이블·폴러·재시도·마킹 컬럼을 다 들이면, 얻는 것보다 운영 복잡도가 크다. 지금 구조는 게을러서가 아니라 **맞아서** best-effort다.

반대 상황도 명확히 해둔다. 만약 이 이벤트가 정산·과금의 근거가 된다면 — 즉 **전달 보장 + 정합성이 목표**라면 — 주저 없이 **②Transactional Outbox로 승격**한다. 이벤트 캡처를 T1 안으로 끌고 들어오는 것이다. 이때 한 가지 주의: **기존 audit 인프라를 재활용해 "보장"을 만들려는 시도는 부적합하다.** audit(③)도 결국 T1↔T2로 분리된 best-effort라, audit의 정합성 틈을 그대로 물려받는다. 보장이 필요하면 audit에 얹지 말고 outbox를 새로 판다.

> **우리 결론**
>
> 활동 이벤트가 분석/피드용(유실 용인)이면 **①best-effort로 충분**하다 — 지금 구조가 정당하다.
> 전달 보장 + 정합성이 목표면 **②Transactional Outbox로** 간다(이벤트 캡처를 T1 안으로).
> **③CDC를 아직 안 부르는 이유**는 규모·운영 역량·데이터 중요도 — 셋 다 CDC의 운영 부담(Debezium/Kafka 클러스터, binlog/WAL 보존·slot 관리)을 정당화하지 못한다. 대규모·다수 서비스가 되는 날, 그때 다시 꺼낸다.
{: .prompt-tip }

같은 dual-write 문제 앞에서, 정합성을 일부 포기하는 것도(best-effort) 절대 안 포기하는 것도(Outbox/CDC) 둘 다 표준이다. **패턴을 몰라서 단순하게 간 게 아니라, 데이터 중요도를 재고 의도적으로 골랐다는 것** — 이게 이 글이 처음부터 관철한 한 문장이다.

> **정답은 데이터 중요도가 정한다.** audit·피드·분석·알림은 싸게, 돈·주문·재고·정산은 반드시. 그 사이 어디에 우리 데이터가 있는지를 먼저 정하면, 네 패턴 중 무엇을 고를지는 저절로 따라온다.

---

> **이어지는 글:** [실시간 활동 로그 파이프라인 (4) — 더 나아가서: Outbox·CDC·Kafka를 알지만 쓰지 않은 이유]({% post_url 2026-06-30-activity-log-4-going-further %})
> **관련 심화편:** [한 브로커, 두 메시징 패턴 — 채팅(STOMP 토픽)과 활동 로그(VirtualTopic 큐)]({% post_url 2026-07-01-broker-one-two-messaging-patterns %})
</content>
</invoke>
