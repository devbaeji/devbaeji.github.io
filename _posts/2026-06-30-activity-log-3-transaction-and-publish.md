---
title: "실시간 활동 로그 파이프라인 (3) — 트랜잭션 경계와 발행 타이밍"
date: 2026-06-30 09:20:00 +0900
categories: [Backend, 활동 로그 파이프라인]
tags: [Spring, Hibernate, ActiveMQ, CQRS]
---

> **시리즈: 실시간 활동 로그 파이프라인 — 큐 발행 단계**
> 1. [문제 정의와 설계 결정]({% post_url 2026-06-30-activity-log-1-problem-and-design %})
> 2. [생산자 diff — "무엇이 바뀌었나"를 발행 시점에 계산하기]({% post_url 2026-06-30-activity-log-2-producer-diff %})
> 3. **트랜잭션 경계와 발행 타이밍** ← 현재 글
> 4. [더 나아가서 — Outbox·CDC·Kafka를 알지만 쓰지 않은 이유]({% post_url 2026-06-30-activity-log-4-going-further %})

---

[2편]({% post_url 2026-06-30-activity-log-2-producer-diff %})에서 diff까지 실은 메시지를 조립했다. 이제 마지막 질문이다. **언제 큐로 보내야 하나?**

이건 단순한 타이밍 문제가 아니다. 잘못 묶으면 "큐 발행이 실패했다고 티켓 상태 변경까지 롤백되는" 사고가 난다. 부가기능(활동 로그)이 본 비즈니스(티켓 변경)를 인질로 잡으면 안 된다. 실제로 코드 리뷰에서도 이 지점에 코멘트가 달렸다.

> 💬 리뷰어: "잘못 묶이면 원래 있는 트랜잭션과 엮이는 거 아닌가 모르겠습니다. REQUIRES_NEW는 트랜잭션을 하나 더 만들어서 괜찮을 듯한데."

이 글은 그 "엮임"을 어떻게 원천 차단했는지에 대한 기록이다.

## 1. "엮인다"는 게 정확히 뭔가

"엮인다" = **부가작업(audit/큐)이 비즈니스 트랜잭션(T1) 안에 함께 묶여서, 부가작업이 실패하면 본 비즈니스까지 롤백되는 상황.**

같은 트리거(티켓 변경)를 어떻게 다느냐에 따라 결과가 갈린다. 네 가지 방식을 표로 비교하면:

| 방식 | 어디서 실행 | 트랜잭션 | 부가작업 실패하면 | 평가 |
|------|------------|----------|-------------------|------|
| ① 서비스 메서드 안에서 직접 발행 | T1 내부 (커밋 전) | **T1에 묶임** | 비즈니스까지 같이 롤백 | ❌ 엮임 — 위험 |
| ② AFTER_COMMIT인데 REQUIRES_NEW 없이 DB 쓰기 | 커밋 후 (열린 tx 없음) | **tx 없음** | DB 쓰기가 보장 안 됨/에러 | ❌ 불완전 |
| ③ AFTER_COMMIT + REQUIRES_NEW | 커밋 후 → 새 T2 | **새 T2 분리** | 비즈니스 유지, audit만 유실 | ✅ 분리 성공 |
| ④ AFTER_COMMIT + 트랜잭션 없음 | 커밋 후 | **tx 자체 불필요** | 비즈니스 유지, 큐만 유실(로그) | ✅ DB 안 쓰니 OK |

audit 저장(`EntityHistoryEventHandler`)은 DB에 써야 하므로 **③**을 쓴다. 우리 큐 발행(`ActivityEventRelay`)은 **④** — 한 발 더 나아가 DB를 아예 안 쓰니 트랜잭션 자체가 필요 없다.

## 2. 발행은 AFTER_COMMIT — 커밋된 사실만 발행한다

발행을 커밋 *전*에 하면 안 된다. 트랜잭션이 롤백되면 "일어나지 않은 일"을 큐에 흘리게 된다. 그래서 `@TransactionalEventListener(phase = AFTER_COMMIT)`을 쓴다. Spring이 트랜잭션 커밋이 확정된 뒤에만 이 리스너를 호출한다.

```kotlin
@Component
@ConditionalOnProperty(name = ["activity.pipeline.enabled"], havingValue = "true")
class ActivityEventRelay(
  @Qualifier("activityJmsTemplate") private val jmsTemplate: JmsTemplate,
  @Value("\${activity.pipeline.topic}") private val topic: String,
  private val objectMapper: ObjectMapper,
) {
  @TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT)
  fun onEntityHistory(event: EntityHistoryEvent) {
    val history = event.history
    if (history !is QueuePublishable) return

    val message = ActivityEventMessage(
      entityType = history::class.simpleName ?: "Unknown",
      action = history.operationType.name,
      actorAccountId = history.operationBy,
      occurredAt = history.operationTimestamp,
      payload = objectMapper.valueToTree(history),
      changes = event.changes,
    )
    runCatching {
      jmsTemplate.convertAndSend(topic, message)
      log.info("활동 이벤트 큐 발행 ▶ ...")
    }.onFailure {
      log.warn("활동 이벤트 발행 실패 type={}", history::class.simpleName, it)
    }
  }
}
```

이 리스너에는 `@Transactional`이 **없다.** 큐에 보내기만 하고 DB는 안 쓰니, 트랜잭션이 필요 없다. 비즈니스 T1과 엮일 여지가 **원천적으로** 없다.

audit 핸들러는 다르다. AFTER_COMMIT 시점엔 T1이 이미 끝나 열린 트랜잭션이 없는데, history INSERT는 트랜잭션이 필요하다. 그래서 `REQUIRES_NEW`로 새 T2를 연다. 두 핸들러를 나란히 보면:

```
                      도메인 변경 (T1)
                           │ commit
                           ▼ AFTER_COMMIT (T1 밖)
        ┌──────────────────┴──────────────────┐
        ▼                                      ▼
EntityHistoryEventHandler            ActivityEventRelay
  @AFTER_COMMIT                         @AFTER_COMMIT
  REQUIRES_NEW → 새 T2                  @Transactional 없음
  (DB에 history INSERT)                 (큐에 발행만, DB 안 씀)
   기존 audit · 형제 ②                   이번 PR · 형제 ③
```

둘은 **순서대로 의존하는 게 아니라**, T1 커밋이라는 같은 원인에서 갈라져 나온 **형제(독립 구독자)** 다. ③(큐)은 ②(audit)의 완료를 기다리지 않고, 한쪽이 죽어도 다른 쪽이 산다. 장애가 격리된다.

## 3. diff는 커밋 *전*, 발행은 커밋 *후* — 타이밍이 다르다

여기서 헷갈리기 쉬운 지점이 있다. "큐 발행이 트랜잭션을 안 쓴다"는 말과, [2편]의 "diff는 flush에서 계산된다"는 말이 충돌하는 것처럼 보인다.

충돌하지 않는다. **두 작업의 타이밍이 다르다.**

```
T1 (비즈니스 트랜잭션) 안에서:
   ... 도메인 변경 ...
   flush → onFlushDirty → diff 계산 → ActivityChangeHolder.put()   ← 커밋 전
   commit
─────────────────────────────────────────── T1 종료
AFTER_COMMIT (T1 밖):
   ActivityEventRelay → jmsTemplate.convertAndSend()                ← 커밋 후
```

- **diff 계산**은 T1 안의 flush에서 끝나고 `ActivityChangeHolder`에 담긴다. 단 이건 **메모리 홀더**라 DB 쓰기가 아니다. T1에 부담을 주지 않는다.
- **발행**은 AFTER_COMMIT에 일어난다. 이건 큐 I/O지 DB I/O가 아니다.

즉 "T1 안에서 무거운 부가작업을 한다"는 우려가 없다. diff는 메모리 연산이고, 진짜 외부 I/O(큐 발행)는 커밋 후로 미뤘다.

## 4. best-effort — dual-write의 틈을 인정하다

`runCatching { jmsTemplate.convertAndSend(...) }`. 발행 실패는 로그로 흡수하고 끝이다. 재시도도, 보상도 없다. 이건 의도적이다.

문제는 분명히 있다. AFTER_COMMIT은 이미 T1이 커밋된 뒤다. 그 사이에 발행이 실패하면 — **커밋은 됐는데(티켓은 바뀜) 발행은 안 된(피드엔 안 뜸)** 상태가 된다. 이게 교과서적인 **dual-write 안티패턴**이다. "비즈니스 DB 커밋"과 "이벤트 발행"을 서로 다른 작업으로 따로 하면 둘 사이에 정합성 틈이 생긴다.

이걸 없애는 정석은 [4편]에서 다룰 Transactional Outbox다. 그런데 우리는 **의도적으로 best-effort를 택했다.** 활동 로그는 피드/분석용이라, 한두 건이 드물게 빠져도 본 비즈니스에 영향이 없다. 반대로 이걸 무손실로 만들겠다고 Outbox를 도입하면 인프라와 코드 복잡도가 크게 는다. 데이터 중요도에 맞춰 비용을 절제한 것이다. (이 트레이드오프 판단을 [4편]에서 업계 레퍼런스와 함께 자세히 다룬다.)

> 이게 우리 알려진 한계 **G1**이다. 문서에도 "best-effort → 커밋O·발행X의 드문 유실. 피드/분석용이라 의도적 수용. 보장 필요 시 Transactional Outbox로 승격"이라고 명시해 뒀다.

## 5. 멱등키와 VirtualTopic — 미래 소비자를 위한 포석

발행까지가 1차 범위지만, 메시지와 토픽 명명에 **미래 소비자를 위한 두 가지 포석**을 깔아뒀다.

### 멱등키 (`eventId`)

```kotlin
data class ActivityEventMessage(
  val eventId: UUID = UUID.randomUUID(),   // ← 멱등키
  // ...
)
```

분산 메시징에서 "정확히 한 번 전달(exactly-once)"은 사실상 불가능하다. 현업의 실무 목표는 **at-least-once 전달 + 멱등 소비자**다. 소비자가 같은 메시지를 두 번 받아도, `eventId`로 중복을 흡수하면 결과는 한 번 처리한 것과 같다. 발행 단계에서 미리 UUID를 박아두면, 향후 소비자가 `event_id UNIQUE` 제약 하나로 멱등성을 보장할 수 있다.

### VirtualTopic 명명

발행 토픽은 `VirtualTopic.myapp.activity.events`다. ActiveMQ의 VirtualTopic은 **하나의 토픽을 여러 소비자 그룹이 각자 fan-out으로 받아갈 수 있게** 해준다. 지금은 소비자가 없지만, 이름을 이렇게 잡아두면 나중에 적재 소비자, 알림 소비자, 분석 소비자를 **서로 독립적으로** 붙일 수 있다. 큐를 "공용 활동 이벤트 버스"로 보는 시각이다.

JMS 설정은 이렇게 돼 있다 — Topic이라 `pubSubDomain=true`, 본문은 JSON `TextMessage`.

```kotlin
@Bean
fun activityMessageConverter(): MessageConverter =
  MappingJackson2MessageConverter().apply {
    setTargetType(MessageType.TEXT)   // ← JMS TextMessage, 본문 = JSON
    setTypeIdPropertyName("_type")
    setObjectMapper(objectMapper)
  }

@Bean
fun activityJmsTemplate(...): JmsTemplate =
  JmsTemplate(connectionFactory).apply {
    isPubSubDomain = true             // ← Topic (fan-out)
    this.messageConverter = messageConverter
  }
```

---

## 인터랙티브 — 한 단계씩 눌러보며 확인

지금까지 설명한 T1·T2·AFTER_COMMIT·큐 발행이 실제로 어떤 순서로 실행되는지, 아래 스테퍼에서 **▶ 다음**·**◀ 이전**·**↺ 처음** 으로 단계별로 확인할 수 있다. 왼쪽 막대 = 트랜잭션이 살아있는 구간, 오른쪽 = 그 순간 실행되는 실제 코드 (노란 줄이 하이라이트). 코드 패널이 넓어 **전체 화면(새 창)** 에서 보는 것을 권장한다.

<p>
  <a href="/assets/interactive/activity-tx-lifecycle.html" target="_blank" rel="noopener"
     style="display:inline-block;padding:11px 20px;border-radius:10px;background:#0969da;color:#fff;font-weight:700;text-decoration:none">
    ▶ 트랜잭션 생명주기 인터랙티브 스테퍼 열기 (새 창)
  </a>
</p>

---

## 6. 큐에 실제로 쌓이는 JSON

지금까지의 모든 결정이 합쳐지면, 큐에는 이런 JSON이 쌓인다. **전송 형식은 JMS TextMessage이고, 본문이 JSON**이다 (plain text가 아니라 직렬화된 JSON).

```json
{
  "eventId":        "d1eb…uuid",            // 멱등키 (UUID)
  "entityType":     "TicketHistory",         // history::class.simpleName
  "action":         "UPDATE",                // INSERT / UPDATE / DELETE
  "actorAccountId": 7001,                     // operationBy (시스템/배치는 null)
  "occurredAt":     "2026-06-30T01:00:00Z",  // operationTimestamp (Instant)
  "payload": {                               // history 스냅샷 통째 (ECST)
    "id": 501, "title": "엘리베이터 점검", "status": "SUSPENDED",
    "workspaceId": 8, "assigneeId": 1012, "…": "(TicketHistory 스냅샷 전체)"
  },
  "changes": [                               // 생산자 diff. UPDATE만, 그 외 []
    { "field": "status",   "changeType": "STATUS_CHANGED",   "from": "ACTIVE", "to": "SUSPENDED" },
    { "field": "assignee", "changeType": "ASSIGNEE_CHANGED", "from": 1010,     "to": 1012 }
  ]
}
```

주의할 점 하나: **top-level에 `workspaceId` 필드가 없다.** workspace_id는 `payload`(TicketHistory 스냅샷) 안에만 있다. 소비자가 워크스페이스로 필터링하려면 `payload.workspaceId`에서 꺼내야 한다(소비자 단계에서 top-level enrich를 재도입할 예정). 1차 범위에선 생산자가 굳이 끌어올리지 않았다.

## 다음 편 예고

여기까지가 "큐 발행 단계"의 전부다. 발행 경로(1편) → 생산자 diff(2편) → 트랜잭션 경계와 발행(3편). 소비자·DB 적재·조회·WebSocket은 다음 단계다.

마지막 [4편]({% post_url 2026-06-30-activity-log-4-going-further %})은 한 발 물러서서 큰 그림을 본다. 우리가 한 선택들 — best-effort 발행, ActiveMQ 재사용, 기존 채팅 인프라로 fan-out — 을 Transactional Outbox, CDC/Debezium, Kafka, Event Sourcing, Activity Streams 2.0, CQRS 같은 업계 표준 패턴과 나란히 놓고, **"기술은 알지만 우리 상황에 맞게 절제했다"** 는 트레이드오프를 정리한다. 솔직한 현재 한계와 다음 단계 계획도 함께.

---

> **이전 글:** [생산자 diff — "무엇이 바뀌었나"를 발행 시점에 계산하기]({% post_url 2026-06-30-activity-log-2-producer-diff %})
> **다음 글:** [더 나아가서 — Outbox·CDC·Kafka를 알지만 쓰지 않은 이유]({% post_url 2026-06-30-activity-log-4-going-further %})
