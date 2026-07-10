---
title: "실시간 활동 로그 파이프라인 (4) — 더 나아가서: Outbox·CDC·Kafka를 알지만 쓰지 않은 이유"
date: 2026-06-30 09:30:00 +0900
categories: [Backend, 활동 로그 파이프라인]
tags: [Spring, Hibernate, ActiveMQ, CQRS]
---

> **시리즈: 실시간 활동 로그 파이프라인 — 큐 발행 단계**
> 1. [문제 정의와 설계 결정]({% post_url 2026-06-30-activity-log-1-problem-and-design %})
> 2. [생산자 diff — "무엇이 바뀌었나"를 발행 시점에 계산하기]({% post_url 2026-06-30-activity-log-2-producer-diff %})
> 3. [트랜잭션 경계와 발행 타이밍]({% post_url 2026-06-30-activity-log-3-transaction-and-publish %})
> 4. **더 나아가서 — Outbox·CDC·Kafka를 알지만 쓰지 않은 이유** ← 현재 글

---

앞의 세 편에서 활동 로그 큐 발행 단계를 구현했다. 이 마지막 글은 한 발 물러서서 묻는다. **"이게 업계 표준에 비춰 어디쯤 있나, 그리고 우리는 왜 더 가지 않았나."**

이벤트 기반 아키텍처에는 잘 알려진 정석들이 있다. 그걸 다 알면서도, 우리는 의도적으로 절제했다. 핵심 원칙 하나를 먼저 말하면:

> **"정답은 데이터 중요도가 정한다."**
> 정합성을 일부 포기하는 것도, 절대 안 포기하는 것도 **둘 다 표준**이다.

## 1. 우리 구조를 표준 용어로 번역하면

우리가 한 일을 업계 패턴 이름으로 다시 쓰면 이렇게 된다.

| 우리 구현 | 업계 패턴 | 어디서 쓰나 |
|-----------|-----------|-------------|
| 메시지에 history 스냅샷 통째로 실음 | **Event-Carried State Transfer (ECST)** | 소비자가 원본 조회 없이 처리해야 하는 모든 곳 |
| `actorAccountId / action / entityType / payload` 봉투 | **Activity Streams 2.0** (actor·verb·object) | W3C 표준, 이종 이벤트 정규화 |
| 소비자가 조회 전용 테이블로 적재(향후) | **CQRS read-model projection** | 읽기/쓰기 모델 분리 |
| 워크스페이스 단위 단일 쿼리 필터 | **fan-out on read** | follow 그래프 없는 B2B 피드 |
| `eventId` UNIQUE 멱등 | **at-least-once + idempotent consumer** | 결제 포함 거의 모든 메시징 |
| Hibernate before/after diff | **변경 추적** (CDC와 같은 정보, 앱 레벨) | — |

골격은 표준과 부합한다. 문제는 "신뢰성"과 "복구" 영역인데, 거기서 우리는 의도적으로 덜 갔다.

## 2. dual-write 안티패턴, 그리고 우리가 그 안에 있다는 인정

[3편]에서 말했듯, AFTER_COMMIT 발행은 교과서적인 **dual-write 안티패턴**이다. "비즈니스 DB 커밋"과 "이벤트 발행"을 따로 하면, 커밋은 됐는데 발행이 실패하는 틈이 생긴다. 이걸 없애는 표준 사다리가 있다.

```
신뢰성 ↑
   │  ④ Event Sourcing      ── 이벤트가 진실의 원천. 금융 원장 등 특수 도메인
   │  ③ CDC (Debezium)      ── DB 로그(binlog/WAL)를 직접 읽어 Kafka로. 대규모 무침투
   │  ② Transactional Outbox── 비즈니스+이벤트를 같은 tx로 INSERT. 마이크로서비스 표준
   │  ① Best-effort 비동기  ── AFTER_COMMIT + runCatching.  ★우리 현재 위치★
   ▼
```

### ① Best-effort (우리)
커밋 후 발행을 따로 시도하고 실패는 `runCatching`으로 흡수. **장점**: 단순·빠름·본 비즈니스 보호. **단점**: 드물게 조용한 유실. **적합**: 감사로그·활동피드·분석·알림처럼 한두 건 빠져도 되는 데이터.

### ② Transactional Outbox
비즈니스 데이터 + 이벤트(outbox 행)를 **같은 트랜잭션으로 INSERT** → 커밋되면 이벤트도 원자적으로 함께 남는다. 별도 폴러/릴레이가 outbox를 읽어 큐로 발행하고 성공 시 마킹(성공할 때까지 재시도). [microservices.io](https://microservices.io/patterns/data/transactional-outbox.html)가 정리한 **마이크로서비스의 사실상 표준 레시피**다. T1 안엔 로컬 INSERT만 두니 [3편] 리뷰어가 말한 "엮임 회피" 원칙도 지킨다.

### ③ CDC (Change Data Capture)
**Debezium**이 DB 트랜잭션 로그를 직접 읽어 Kafka로 발행. outbox 테이블 없이도 "커밋된 것 = 곧 이벤트"라 정합성이 DB 커밋에 자동으로 묶인다. 앱 코드 거의 무변경, 고처리량. 대신 Debezium/Kafka 운영 부담. **대규모·다수 서비스에서 가장 흔한 실전 스택**이다. 흥미로운 건 CDC가 우리 Hibernate diff와 **같은 정보(before/after)** 를 잡는다는 점이다 — 우리는 그걸 앱 레벨 Interceptor로, CDC는 DB 로그 레벨로 한다.

### ④ Event Sourcing
상태를 저장하는 대신 **이벤트 자체를 진실의 원천**으로 삼고, 상태는 이벤트를 재생해 만든다. 정합성·이력추적이 강력하지만 도입·운영 비용이 크다. 금융 원장 등 특수 도메인용.

> **"exactly-once는 신화다."** 분산 시스템에서 정확히 한 번 전달은 사실상 불가능하다. 현업의 실무 목표는 *at-least-once 전달(재시도로 안 잃음) + 멱등 소비자(eventId로 중복 무시) = exactly-once "효과"*. 결제 시스템조차 이 방식을 쓴다. 우리가 [3편]에서 `eventId`를 미리 박아둔 이유다.

## 3. 고트래픽·실시간 잦은 곳은 뭘 더 하나 — vs 우리는 왜 안 했나

여기가 이 글의 핵심이다. **"몰라서 안 한 게 아니라, 알고 선택했다."**

### 신뢰성 — 우리는 best-effort로 충분
결제·주문·재고·정산처럼 **유실이 치명적인** 도메인은 ②Outbox나 ③CDC로 at-least-once를 보장한다. 한 건이라도 빠지면 돈이 틀어지니까.

우리 활동 로그는 다르다. **"활동 피드"** 다. 누가 언제 티켓 상태를 바꿨는지 보여주는 화면에서, 천 건 중 한 건이 드물게 빠진다고 사업이 망하지 않는다. 그 한 건을 안 잃으려고 Outbox 테이블, 폴러, 재시도 로직, 마킹 컬럼을 다 도입하면 — 얻는 것보다 운영 복잡도가 더 크다. 그래서 best-effort(G1)를 **의도적으로** 택했다. 필요해지면 Outbox로 승격할 경로는 열어뒀다(메시지 봉투는 그대로 재사용 가능).

### 메시지 버스 — Kafka 대신 이미 돌아가는 ActiveMQ
"이벤트 스트리밍" 하면 Kafka가 떠오른다. 재생 가능한 영속 로그가 강점이다. 그런데 우리가 필요한 건 다음과 같았고:

| 필요한 것 | Kafka | ActiveMQ (채택) |
|-----------|-------|-----------------|
| 다중 소비처 fan-out | 토픽 + 컨슈머그룹 | **VirtualTopic** 동일 |
| at-least-once + 멱등 | ✓ | ✓ (`event_id` UNIQUE) |
| 실시간 broadcast | (별도) | STOMP relay 보유 |
| 재생 가능 로그 | ✓ | ✗ |

fan-out·멱등·실시간은 ActiveMQ VirtualTopic으로 다 충족된다. Kafka의 진짜 차별점은 **재생 로그**(우리 한계 G2)인데, 이건 우리가 이미 가진 `*_history` 테이블 백필로 대체할 수 있다. 그리고 결정적으로 — **ActiveMQ는 이미 운영 중이다.** 채팅 시스템이 쓰고 있다. Kafka를 새로 띄우면 인프라·운영·학습 비용이 추가된다. 이미 있는 걸 재사용해서 인프라 추가 비용을 회피했다.

### 실시간 fan-out — 기존 채팅 StompBrokerRelay 재사용 (예정)
실시간 활동 로그의 어려운 부분은 "WS 서버가 여러 대일 때 모든 인스턴스의 구독자에게 어떻게 동시에 밀어주나(멀티 인스턴스 fan-out)"다. 이것도 새로 만들 필요가 없었다. 우리 채팅이 이미 `StompBrokerRelay`(ActiveMQ STOMP)로 이 문제를 풀고 있다. prod는 `enableStompBrokerRelay("/topic","/queue")`, 로컬은 `enableSimpleBroker` 폴백. 향후 적재 소비자가 `convertAndSend("/topic/workspace.{id}")`만 호출하면 외부 브로커가 전 인스턴스 fan-out을 책임진다.

정리하면 — **세 가지 다 "트레이드오프를 알고 의도적으로 선택"** 했다. 표준을 몰라서 단순하게 간 게 아니라, 우리 데이터 중요도와 이미 가진 인프라에 맞춰 절제한 것이다.

## 4. 솔직한 현재 한계

균형을 위해, 자랑만 하지 않고 한계도 적는다. 이건 약점이라기보다 "다음 단계에서 다룰 목록"이다.

| 코드 | 한계 | 대응 / 다음 단계 |
|------|------|------------------|
| **G1** | 발행이 best-effort → 커밋O·발행X의 드문 유실(dual-write) | 피드/분석용이라 의도적 수용. 보장 필요 시 **Transactional Outbox로 승격** |
| **G2** | 큐 휘발성 → 재생(replay) 로그 없음 (ActiveMQ는 소비 후 사라짐) | `*_history` 백필로 대체. Kafka 승격 시 해소 |
| **G3** | verb가 CRUD(INSERT/UPDATE/DELETE) → 다필드 단일 의도("배정") 표현 약함. Activity Streams 2.0은 의미 동사 권장 | 의미가 필요한 소수는 도메인이 verb를 명시 발행 |
| **G5** | 벌크 JPQL/native UPDATE는 `onFlushDirty`를 우회 → diff·이벤트 누락 | 기존 `@PostUpdate` audit과 **동일 한계(회귀 아님)**. 사용자 핵심 행동(상태·배정)은 managed 엔티티라 전부 잡힘 |

> **G4는 해소됐다.** 초기 설계엔 "직전 activity_event가 없으면 diff가 stale" 우려가 있었는데, [2편]의 생산자 diff(Hibernate before/after)로 **제거됐다.** 직전 행을 조회해 비교하는 게 아니라 Hibernate가 든 실제 DB 전이를 비교하므로, 직전 행 조회 자체가 없다.

### 미구현 — 소비자·조회·실시간
가장 큰 한계는 명확하다. **아직 발행까지만 됐다.** 소비자(`ActivityEventConsumer`), 적재 서비스, `activity_events` 테이블, 조회 API, 이름 join, WebSocket broadcast는 코드에 없다. 큐에 JSON이 쌓이는 것까지가 현재 검증 범위다.

## 5. 다음 단계 계획

발행이 단단해졌으니, 다음은 소비자다. 설계 방향은 이미 잡혀 있다.

```
큐 (구현됨) VirtualTopic.myapp.activity.events
   │
   ▼ 소비자 (순수 writer, DB 읽기 0이 목표)
   ① 멱등 (event_id UNIQUE) → ② category 추출 → ③ INSERT activity_events
   ④ convertAndSend("/topic/workspace.{id}")
   │
   ▼ 실시간 — StompBrokerRelay 전 인스턴스 fan-out (기존 채팅 재사용)
   ▼ 조회   — 최초 REST pull(이름 join) + 이후 WS push
```

소비자를 "DB 읽기 0의 순수 writer"로 만들 수 있는 건 [1편]의 ECST 덕분이다 — diff도 workspace_id도 이미 메시지/payload에 있다. 표시용 이름만 조회 시점에 join해서 푼다([2편]의 "id만 저장" 원칙).

한 줄 요약으로 시리즈를 닫는다.

> **ActiveMQ Pub/Sub 위에서 Event-Carried State Transfer로 자기완결 활동 이벤트를 흘리고, 생산자(Hibernate Interceptor) diff로 변경을 데이터화하며, (향후) 소비자가 CQRS 읽기모델로 프로젝션하고 workspace 단위 fan-out-on-read + StompBrokerRelay 멀티 인스턴스 WebSocket broadcast(기존 채팅 재사용)로 공유하는 구조.**
> 무손실(Outbox)·리플레이·의미 verb는 단계적 강화로 의도적으로 남겨뒀다.

## 참고 자료

- [microservices.io — Transactional Outbox](https://microservices.io/patterns/data/transactional-outbox.html) — 발행 신뢰성 패턴(G1 승격 경로)
- [Martin Fowler — CQRS](https://martinfowler.com/bliki/CQRS.html) — 읽기모델/프로젝션 원전
- [Debezium / CDC](https://debezium.io/documentation/) — before/after 캡처의 산업 표준
- [W3C Activity Streams 2.0](https://www.w3.org/TR/activitystreams-core/) — actor·verb·object·target 정규화
- [Spring Reference — WebSocket STOMP](https://docs.spring.io/spring-framework/reference/web/websocket/stomp.html) — `/topic/...` broadcast, relay
- [GetStream — Activity Feeds](https://getstream.io/activity-feeds/) — 피드·fan-out·실시간 실전 가이드

---

> **이전 글:** [트랜잭션 경계와 발행 타이밍]({% post_url 2026-06-30-activity-log-3-transaction-and-publish %})
> **시리즈 처음으로:** [문제 정의와 설계 결정]({% post_url 2026-06-30-activity-log-1-problem-and-design %})
