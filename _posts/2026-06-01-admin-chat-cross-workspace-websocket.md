---
title: "어드민 채팅 cross-workspace 실시간 회귀 — STOMP multi-subscribe 로 해결한 이야기"
date: 2026-06-01 15:00:00 +0900
categories: [Backend, Realtime]
tags: [websocket, stomp, activemq, react-query, spring-messaging, system-design]
---

> 워크스페이스 단위 채팅을 **여러 워크스페이스를 가로지르는 어드민 드로어** 로 개선하다가, 실시간 알림이 누락되는 회귀를 만났다.
> 원인은 백엔드가 아니라 **프론트 구독 토픽** 한 줄이었고, 해결도 한 줄이었다. 다만 그 한 줄 뒤에 STOMP·ActiveMQ·React Query 가 어떻게 맞물려 있는지 정리해 둘 가치는 충분했다.

---

## 1. 문제 상황

어드민 페이지의 채팅 기능은 원래 다음과 같은 구조였다.

- 채팅방은 **워크스페이스 단위**로 소속됨
- URL 이 `/workspaces/{id}/...` 형태라 화면이 항상 "내가 보고 있는 워크스페이스가 무엇인지" 알 수 있음
- 그래서 WebSocket 구독도 자연스럽게 `/topic/workspace.{id}.chat-notify` 한 개만 걸어두면 충분

문제는 어드민이 **여러 워크스페이스를 동시에 관리**한다는 점이었다. 매번 워크스페이스 페이지를 들락거리며 채팅을 확인하는 게 불편해서, GNB(상단 글로벌 내비게이션) 에 채팅 아이콘을 두고 **드로어로 전체 워크스페이스의 채팅을 한 곳에서 보는 UI** 를 추가하기로 했다.

여기서 회귀가 발생했다.

### 증상

- 드로어를 열어도, 다른 워크스페이스에서 새 메시지가 와도 **목록·미읽 배지가 갱신되지 않음**
- 채팅방을 한 번 클릭하면 그 워크스페이스의 알림만 부분 회복
- 메시지를 보낸 쪽에서는 정상 — 백엔드는 잘 publish 하고 있음

### 원인 분석

```ts
// 회귀 전: 워크스페이스 페이지에 종속된 훅
useAdminChatWebSocket(workspaceId, activeChatRoomId);
// → URL params 에서 workspaceId 가 항상 유효한 숫자로 들어옴
// → /topic/workspace.{14}.chat-notify 정확히 구독

// 회귀 후: 드로어가 URL 무관하게 떠 있음
const [activeWorkspaceId] = useState<number>(0); // ← URL이 안 알려줌
useAdminChatWebSocket(activeWorkspaceId /* 0 */, null);
// → /topic/workspace.0.chat-notify ← 아무도 publish 안 하는 죽은 토픽
```

UI 컨텍스트(어떤 워크스페이스를 보고 있는지) 에 의존해서 구독 토픽이 결정되던 코드가, **UI 컨텍스트가 없어진 cross-workspace 진입점**에서는 의미를 잃어버린 것이다.

그림으로 보면 회귀의 본질이 한눈에 들어온다. 백엔드 publish 토픽은 그대로(`workspace.14`)인데, 프론트가 구독하는 토픽만 `workspace.0` 으로 어긋나 있다.

{% include chat-ws-regression-arch.html %}

핵심은 `workspaceId` 라는 단일 변수의 **의미가 바뀐 것**이다. 페이지 시절엔 "내가 보고 있는 워크스페이스"(URL이 보장)였지만, 드로어에선 "내가 클릭한 채팅방의 워크스페이스"(선택 전엔 0)가 됐다. 에러 한 줄 없이 조용히 죽은 토픽을 구독하니, 네트워크 탭에 REST GET 조차 안 찍혀 원인 추적이 더뎠다.

---

## 2. 해결 방향 3가지

### A안 — 프론트 multi-subscribe (증상 패치, 빠름)

어드민이 속한 모든 워크스페이스 목록을 받아서 **각 토픽을 동시 구독**.

- 백엔드 변경 0
- 변경 비용 ~5줄
- 단점: 워크스페이스 100개면 구독 100개. 권한 변경 시 재구독 필요

### B안 — 사용자 큐(user queue) 로 전환 (구조적 리팩토링)

`/topic/...` 대신 `/user/{accountId}/queue/admin-chat-notify` 같은 **사용자 전용 큐**로 전환. 백엔드가 "이 메시지를 받을 어드민들"을 결정해서 1:1 push.

- 구독은 늘 한 개
- 권한 로직이 백엔드 한 곳에 단일화
- 채팅 외 알림 모듈(공지/작업 요청 등)도 같은 패턴이라 영향 범위가 큼 → **별도 티켓이 합당**

### C안 — 회피 (회귀 인정 + 다음 PR로)

활성 워크스페이스만 실시간, 나머지는 staleTime 만료 시 refetch. 변경 0이지만 회귀가 그대로 남음.

### 선택

**A안 채택 + B안 별도 티켓 분리**.

근거:
1. 회귀를 PR 안에서 봉합 가능 (디자인 QA 차단 해소)
2. 운영 스케일(워크스페이스 ~10개, 어드민 ~5명) 에서 구독 수 부담 미미
3. B안은 구조 개선이라 단독 분석·롤아웃이 더 안전

---

## 3. 인프라 플로우 (A안 채택 후)

메시지 한 건이 거치는 길:

{% include chat-ws-infra-flow.html %}

구독(FE→broker)과 발행(Service→broker)이 broker 를 가운데 두고 만난다. 프론트는 broker 가 ActiveMQ 인지 인메모리인지 모른 채 `subscribe` 한 줄만 건다.

### 레이어별 책임

| 레이어 | 무엇을 하나 |
|--------|-------------|
| **Frontend** (`@stomp/stompjs`) | STOMP frame 송수신, `client.subscribe(destination, cb)` 으로 콜백 등록, 자동 재연결 |
| **WebSocket transport** | 브라우저 ↔ 서버 TCP 업그레이드 (`ws://...`) |
| **Spring WebSocket 종단** | STOMP endpoint 노출, CONNECT frame 인증 interceptor |
| **ActiveMQ Artemis** | **topic fan-out** — 1건 publish 를 구독자 N명에게 복제 |
| **ChatMessageService** | `messagingTemplate.convertAndSend("/topic/...", payload)` 로 publish |

### 환경 분기

```kotlin
// 운영: ActiveMQ Artemis 로 relay
config.enableStompBrokerRelay("/topic", "/queue")
  .setRelayHost(host).setRelayPort(61613)

// 로컬/CI: Spring 내장 인메모리 broker
config.enableSimpleBroker("/topic", "/queue")
```

프론트 코드는 양쪽 환경에서 동일. STOMP 가 표준 프로토콜이라 가능한 일이다.

### STOMP 가 wire 에서 보내는 것

```text
SUBSCRIBE
id:sub-0
destination:/topic/workspace.14.chat-notify
ack:auto

\0
```

```text
MESSAGE
subscription:sub-0
destination:/topic/workspace.14.chat-notify
content-type:application/json

{"id":1234,"content":"...","sender":...}\0
```

텍스트 프로토콜이라 WebSocket DevTools 로 그대로 볼 수 있다.

---

## 4. 실시간 카운트 업데이트 — 두 가지 트리거 + 안전망

다음은 자주 헷갈리는 부분. **WebSocket payload 자체는 UI 에 쓰지 않는다.**

```ts
client.subscribe("/topic/workspace.14.chat-notify", () => {
  // payload 본문은 안 봄. "어디서 뭔가 일어났다" 시그널로만 사용.
  queryClient.invalidateQueries({ queryKey: chatKeys.adminRoomsAll });
  queryClient.invalidateQueries({ queryKey: chatKeys.adminUnreadCount });
});
```

invalidate 가 일어나면 React Query 가 active 쿼리를 자동 refetch → 네트워크 탭에 `GET /api/v1/chats` + `GET /api/v1/chats/unread-count` 가 찍힌다. **WebSocket → REST GET** 의 흐름이 만들어지는 이유다.

### 왜 payload 를 직접 안 쓰나

1. **스키마 변경에 견고** — payload 형태가 바뀌어도 프론트 영향 없음. 서버 진실값을 한 번 더 받아오기만 하면 됨
2. **여러 데이터를 한 번에 갱신** — 채팅방 목록, 미읽 합산, 정렬 등을 일관되게 다시 받음

### 3중 트리거

세 갈래의 트리거가 결국 같은 invalidate 로 모이고, 그 뒤 REST 로 서버 진실값을 다시 받는 구조다.

{% include chat-ws-triggers-flow.html %}

| 트리거 | 발화 시점 | 호출되는 GET |
|--------|----------|--------------|
| WebSocket 콜백 | 메시지 도착 즉시 | `GET /chats` + `GET /chats/unread-count` |
| refetchInterval 폴링 | 30초 주기 (`refetchInterval: 30_000`) | `GET /chats/unread-count` (안전망) |
| mutation 성공 | 채팅방 생성, markAsRead, 메시지 전송 등 | 같은 키 invalidate |

WebSocket 콜백이 1차, 폴링이 안전망, mutation 이 사용자 액션 즉시 반영용이다. WebSocket 이 끊김과 재연결 사이에 흘려보낸 이벤트는 30초 안에 폴링이 정정해준다.

```ts
// 30초 폴링 (안전망)
export function useAdminTotalUnreadCount() {
  return useQuery({
    queryKey: chatKeys.adminUnreadCount,
    queryFn: () => api.getAdminUnreadCount(),
    refetchInterval: 30_000,
  });
}
```

---

## 5. DB 인덱스 보강

cross-workspace 집계 쿼리가 점진적으로 느려지지 않도록 인덱스 두 개를 추가했다.

```sql
-- 어드민 채팅방 목록 조회 핫패스
CREATE INDEX idx_chat_rooms_ws_status_updated
  ON chat_rooms (workspace_id, status, updated_at DESC);
```

- `WHERE workspace_id IN (...) AND status = ?` + `ORDER BY updated_at DESC` 가 단일 인덱스로 처리됨
- 좌측 prefix 활용으로 `workspace_id` 단독 조회에도 재사용

```sql
-- 30초 폴링되는 미읽 합산 쿼리용 (partial index)
CREATE INDEX idx_chat_room_members_account_active
  ON chat_room_members (account_id, left_at)
  WHERE left_at IS NULL;
```

partial 로 만든 이유는 **합산 대상이 활성 멤버뿐**이기 때문. `left_at IS NULL` 행만 인덱싱해서 크기와 lookup 비용을 줄였다.

---

## 6. 회고

### 한 줄 변경 뒤의 깊이

회귀 봉합 자체는 코드 ~5줄이었다. 그런데 그 5줄이 어떤 영향을 미치는지 설명하려면 STOMP → WebSocket → ActiveMQ → Spring → React Query 까지 5개 레이어를 모두 짚어야 했다. **실시간 시스템은 항상 그런 식**으로 보인다 — 변경은 작아도 머릿속 모델은 전체를 알아야 한다.

### "WebSocket 으로 데이터 받는다" 는 오해

처음 합류한 사람들이 거의 항상 묻는다: "WebSocket 으로 받는 데이터를 그냥 화면에 뿌리면 안 되나요?" 짧게 답하면 가능하다. 하지만 그러면 **payload 스키마와 UI 상태가 직결**되고, 메시지 누락이나 순서 역전이 곧바로 UI 버그가 된다. **WebSocket 은 시그널, 진실값은 REST** 라는 패턴은 그 결합도를 떼어내는 가장 단순한 방법이다.

### 인프라가 표준이면 코드는 단순해진다

`client.subscribe(...)` 한 줄이 로컬에서는 Spring SimpleBroker 로, 운영에서는 ActiveMQ Artemis 로 흘러간다. 프론트는 둘의 차이를 모른다. STOMP 라는 표준 한 겹이 있어서 broker 를 갈아끼울 수 있고, 로컬 개발이 운영과 같은 코드로 돌아간다.

### B안은 언제 갈까

운영 워크스페이스가 100개를 넘어가거나, 권한 변경이 잦아져 재구독 로직이 복잡해지면 그때가 B안 시점이다. 지금은 A안의 단순함이 더 큰 가치. 회귀 봉합과 구조 개선은 같은 PR 에서 같이 하지 않는다.

---

## 7. 정리

| 측면 | 회귀 발생 시점 | A안 적용 후 |
|------|---------------|-------------|
| 구독 토픽 수 | 1개 (활성 워크스페이스) | N개 (소속 워크스페이스 전부) |
| 구독 수와 UI 컨텍스트 결합 | 강결합 | 분리됨 |
| 백엔드 변경 | — | 없음 |
| 카운트 갱신 트리거 | WebSocket only | WebSocket + 30초 폴링 + mutation invalidate |
| DB 부하 | 단일 워크스페이스 쿼리 | cross-workspace 집계 (인덱스 보강 완료) |

> 실시간 시스템은 보이지 않는 곳에서 많은 일이 일어난다. 그래서 **시각화 한 장**이 회의 시간을 가장 많이 줄여준다. 다음 비슷한 회귀를 만나면, 이 그림을 펴고 시작할 예정이다.

---

## 8. 인프라 허점과 개선 고민

A안으로 회귀는 봉합했지만, 그 과정에서 **현재 인프라의 약한 고리들**도 같이 보였다. 운영 스케일에서는 아직 문제가 안 드러나지만 미리 정리해 둘 가치가 있다.

### 8-1. 식별된 허점

#### broker 단일 장애점

ActiveMQ 인스턴스가 하나면 broker 가 죽는 순간 모든 실시간 알림이 멈춘다. Spring relay 가 broker 와 끊기면 `convertAndSend` 가 조용히 누락될 수 있고, 프론트는 30초 폴링으로 채팅 목록·미읽은 부분 회복하지만 활성 채팅방 메시지는 폴링이 없어 사실상 무응답이 된다.

#### WebSocket 끊김 사이의 메시지 누락

모바일 네트워크 전환, LB idle timeout(보통 60초), 브라우저 백그라운드 등으로 WebSocket 은 생각보다 자주 끊긴다. 끊긴 사이의 메시지는 재연결 이후에도 받지 못한다. STOMP durable subscription 을 쓰지 않기 때문이다. 채팅방 목록·미읽은 폴링이 정정해주지만, 활성 채팅방의 메시지 본문은 정정 메커니즘이 없다.

#### 권한 변경 시 구독 정합성

어드민이 워크스페이스에서 빠진 직후에도 프론트는 한동안 그 토픽을 계속 구독하고 있다. 토픽 자체가 사라지지 않으니 broker 도 거부하지 않는다. 다음 페이지 새로고침까지 권한 없는 메시지를 수신할 가능성이 남는다.

#### 인증 만료와 long-lived connection

WebSocket 인증은 `CONNECT` frame 한 번에만 일어난다. 세션이 만료돼도 연결은 살아있어 메시지가 계속 흐른다. REST 는 곧장 401 이 나는데 WebSocket 만 멀쩡한 상황 — 보안 관점에서 정합성이 깨진다.

#### 관측 도구 부재

토픽별 메시지량, 구독자 수, publish 실패율, broker 메모리 같은 실시간 지표가 잡히지 않는다. 회귀가 났을 때도 "왜 안 오지?" 부터 시작해야 한다.

### 8-2. 단기 개선 — 운영 스케일 내에서 바로

| 항목 | 조치 | 비용 |
|------|------|------|
| WS 끊김 즉시 인지 | 프론트에서 connection state 를 GNB 상태 dot 으로 노출 (이미 있음). 추가로 끊김이 N 초 이상이면 staleTime 강제 0 | 1줄 |
| 재연결 후 보강 | `client.activate()` 재성공 직후 모든 active query 강제 invalidate | 훅 1개 |
| Active room 폴링 안전망 | 활성 채팅방 메시지에도 60s polling 추가 (브라우저 보이는 동안만) | 훅 1개 |
| 인증 만료 sync | WebSocket interceptor 에서 토큰 만료 임박 시 서버가 `DISCONNECT` frame 보내 강제 재인증 | 백엔드 핸들러 1개 |
| 기본 메트릭 | ActiveMQ 관리 콘솔 + Spring `WebSocketSessionRegistry` 카운트를 Grafana 에 노출 | 인프라 작업 |

### 8-3. 중장기 설계 고민

#### B안(user queue) 으로 가야 하는 시점
A안은 "어드민 N명이 본인이 속한 WS 전부 구독" 구조라 **broker fan-out 부담이 (어드민 수 × WS 수) 에 비례**한다. 다음 임계점에서 재검토:

- 워크스페이스 100개 돌파
- 어드민 50명 돌파
- 권한 변경 빈도 증가

이때는 `/user/{accountId}/queue/admin-chat-notify` 로 전환해서 **구독을 1개로 단순화**하고 권한 결정을 백엔드에 단일화한다. 채팅 외 알림 모듈(공지/작업 요청)도 동일 패턴이라 함께 정리.

#### Broker HA / cluster
ActiveMQ Artemis 의 master-slave 또는 cluster 구성으로 SPOF 해소. Spring relay 측은 multi-host 설정 + 자동 failover. **장애 시 메시지 보존**까지 원하면 persistent message + journal 디스크 설계가 들어간다.

#### Outbox + 비동기 발행
현재는 REST API 트랜잭션 안에서 `convertAndSend` 가 동기 실행된다. broker 가 잠시 느려지면 **사용자 요청 latency 가 그대로 영향**받는다. **트랜잭션 outbox 패턴** 으로 분리하면:

1. DB 에 메시지 row insert (트랜잭션 안)
2. 별도 워커가 outbox 를 polling 해서 broker 에 publish
3. 발행 성공 시 outbox row 삭제

장점: API 응답 안정성 + publish 실패 시 재시도 자동화 + at-least-once 보장
단점: 코드 복잡도, 약간의 지연

#### 클라이언트 push 보완 (web push / FCM)
WebSocket 은 **브라우저가 열려 있을 때만** 동작한다. 어드민이 다른 앱을 보고 있거나 닫아 두면 실시간이 의미 없어진다. 중요한 알림은 web push 또는 모바일 푸시로 보완. 이미 worker-app 에는 FCM 이 있으니 admin 도 같은 채널을 쓰는 게 자연스럽다.

#### 관측·알람
- 토픽별 publish/consume 카운터를 Prometheus 로 수집
- WebSocket 활성 세션 수, 평균 연결 시간, 끊김 빈도 대시보드
- broker 연결 끊김 / publish 실패율 임계 초과 시 Slack 알람

### 8-4. 어디부터 손볼까

회귀 봉합 직후 바로 들어가야 할 일과 천천히 가도 되는 일을 구분해 본다.

**바로 해야 할 것 (다음 스프린트 안)**

- 재연결 직후 강제 invalidate, active room 폴링 안전망 — 사용자 데이터 정합성. 비용이 거의 안 든다
- 기본 메트릭 노출 (활성 세션 수, publish 카운터) — 다음 장애 때 원인 파악 속도가 달라진다
- 인증 만료 sync — 보안 정합성. 늦출수록 잠재 사고

**스케일이 커지면 손볼 것**

- B안(user queue) 전환 — 워크스페이스 100개 또는 어드민 50명을 넘으면
- Broker HA 구성, outbox 패턴 — 트래픽·중요도가 올라가면
- Web push 보완 — 어드민이 브라우저를 닫고 있는 시간이 길어진다는 데이터가 보이면

### 8-5. 메모

이런 정리는 **사고가 나기 전에** 해두는 게 훨씬 싸다. 사고가 나면 모두가 같은 화면 앞에서 동시에 배우게 된다 — 그건 비싸다. 회귀를 봉합한 PR 의 회고 단계에서 이런 표 한 장을 같이 남겨두면, 다음 누군가가 같은 영역을 만질 때 출발점이 된다.
