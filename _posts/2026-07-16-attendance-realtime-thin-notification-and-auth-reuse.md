---
title: "WebSocket 인프라 재사용의 경계 — 전송은 공유하고, 페이로드와 인가는 갈라졌다"
date: 2026-07-16 09:00:00 +0900
categories: [Backend, WebSocket]
tags: [websocket, stomp, spring-messaging, activemq, react-query, system-design]
---

> **[어드민 채팅 cross-workspace 실시간 회귀]({% post_url 2026-06-01-admin-chat-cross-workspace-websocket %})의 후속.**
> 1편은 채팅 하나만 놓고 STOMP·ActiveMQ·React Query가 어떻게 맞물리는지 정리했다. 그 뒤 출퇴근 실시간 반영이 같은 인프라 위에 들어왔는데, 재사용한 것과 재사용되지 않은 것이 선명하게 갈렸다.

---

우리 백엔드의 실시간 기능은 채팅, 출퇴근 실시간 반영, 활동 로그 파이프라인 셋이다. 앞의 둘은 같은 STOMP 엔드포인트(`/api/ws/chat`), 같은 브로커 릴레이(STOMP 61613 로컬 / 61614 SSL), 같은 인증 인터셉터를 쓰고, 활동 로그만 OpenWire(JMS)로 갈라진다. 그 갈림은 [한 브로커, 두 메시징 패턴]({% post_url 2026-07-01-broker-one-two-messaging-patterns %})에, 발행 타이밍(`AFTER_COMMIT` + `runCatching`)은 [활동 로그 (3)]({% post_url 2026-06-30-activity-log-3-transaction-and-publish %})에 정리했다. 출퇴근 브로드캐스터도 같은 조합을 쓴다.

세 앱(web/admin/worker)의 WebSocket 클라이언트 코드를 공통 패키지로 합치면서 파이프라인들을 나란히 놓고 보게 됐다. 채팅과 출퇴근은 프로토콜·릴레이·인터셉터가 같은데, 페이로드와 인가에서 갈라져 있었다.

## 페이로드가 정반대다

채팅은 본문이 그대로 페이로드다(`{"id":1234,"content":"...","sender":...}`). 출퇴근 알림은 식별자와 변경 종류만 싣고 값은 싣지 않는다.

```kotlin
/** 출퇴근 변경 thin notification payload — 값 스냅샷 없이 "변경됨"만 전달한다. */
data class AttendanceRealtimeNotification(
  val type: String,        // CHECK_IN / CHECK_OUT / UPDATE / CANCEL_CHECK_IN / CANCEL_CHECK_OUT
  val attendanceId: Long,
  val scheduleId: Long,
  val workspaceId: Long,
  val workDate: LocalDate,
  val ownerAccountId: Long,
)
```

클라이언트는 알림을 신호로만 쓰고 REST를 다시 부른다.

```ts
// 일반 작업자 출퇴근 실시간 훅 — 알림을 받으면 캐시를 invalidate 할 뿐
const event = JSON.parse(msg.body) as AttendanceRealtimeNotification;
if (event.type === 'CHECK_IN' || event.type === 'CHECK_OUT' /* ... */) {
  invalidateWorkLists(queryClient);
  void queryClient.invalidateQueries({
    queryKey: ['my-checked-in-attendances', event.workspaceId],
  });
}
```

[1편 §4]({% post_url 2026-06-01-admin-chat-cross-workspace-websocket %})의 "WebSocket은 시그널, 진실값은 REST"와 같은 원칙이다. 다만 1편에서는 서버가 본문을 실어 보내고 클라이언트가 안 볼 뿐이었고, 이번엔 서버가 값을 아예 안 싣는다. 클라이언트 규율에 맡기던 걸 타입으로 못 박은 셈이다.

출퇴근 상태는 목록·요약·상세 여러 화면이 같이 보는 값이다. 알림에 값을 실어 화면을 갱신하면 알림이 재정렬되거나 연결이 잠깐 끊겨 하나를 놓쳤을 때 화면이 어긋난 채 남고, 어긋났다는 것조차 모른다. 식별자만 받고 REST로 읽으면 중복되든 순서가 섞이든 다음 알림 하나가 전체를 정정한다. 대가는 왕복 한 번이다. 1편에서 30초 폴링을 안전망으로 둘 수 있었던 것도 폴링과 WebSocket이 같은 invalidate로 모이기 때문이다.

채팅은 반대로 본문 자체가 사용자가 기다리는 콘텐츠라 thin으로 만들면 왕복만 는다. 작업 요청 목록 갱신 알림은 출퇴근과 같은 thin 쪽이다.

## 인가는 재사용되지 않았다

출퇴근은 엔드포인트, 릴레이, `WebSocketAuthInterceptor`까지 채팅 것을 그대로 쓴다. 그런데 SUBSCRIBE 시점 구독 검증에 쓰는 채팅용 체커가 작업자 롤을 항상 거부했다.

```kotlin
// ChatAccessChecker
fun canAccessWorkspace(accountId: Long, accountType: AccountType, workspaceId: Long): Boolean =
  when (accountType) {
    // 워커는 채팅 미지원
    AccountType.WORKER -> false
    AccountType.USER -> { /* 현재 소속 워크스페이스만 */ }
    // ...
  }
```

작업자는 채팅을 안 쓰니 채팅 입장에선 맞는 규칙이다. 하지만 출퇴근은 작업자 본인이 주인공인 데이터라, 채팅 인가를 물려받으니 자기 기록을 구독해야 할 사람이 막혔다.

채팅 체커에 "출퇴근이면 워커 허용" 분기를 넣으면 채팅 도메인이 출퇴근 규칙을 알게 된다. 실제 코드는 목적지에 따라 둘로 갈렸다.

**워크스페이스 토픽(`/topic/workspace.{id}.attendance`)** 은 작업자 관리자 롤만 구독할 수 있어야 하는데, 그 판정을 출퇴근 도메인 전용 서비스로 뺐다.

```kotlin
/**
 * 채팅용 `ChatAccessChecker.canAccessWorkspace` 는 WORKER 를 항상 거부하므로, 워크스페이스
 * 토픽에 한해 WORKER 는 이 서비스로 별도 판정한다.
 * `ChatAccessChecker` 를 오염시키지 않기 위해 attendance 도메인 전용으로 분리했다.
 */
@Service
class AttendanceSubscriptionChecker(...) {
  fun isWorkerManagerOfWorkspace(accountId: Long, workspaceId: Long): Boolean = ...
}
```

인터셉터는 목적지를 보고 위임처를 고른다. 일반 사용자·어드민은 기존 채팅 체커로, 작업자만 출퇴근 전용 체커로 간다.

**개인 토픽(`/topic/attendance.account.{accountId}`)** 은 일반 작업자가 구독하고, 인가는 자기 토픽인지 확인하는 한 줄이다.

```kotlin
accountMatch != null -> principal.accountId == accountMatch.groupValues[1].toLong()
```

개인 토픽은 본인 작업만 보는 화면에 더 정확한 단위고 fan-out도 좁다. 다만 코드 주석에 "WORKER 를 항상 거부하는 갭을 우회하기 위해"라고 적혀 있듯, 생긴 계기는 도메인 요구가 아니라 채팅 인가 제약이었다.

결국 재사용 가치가 있었던 건 연결·릴레이·세션 관리였다. 전송 계층은 도메인을 몰라도 되지만 인가는 도메인 규칙 그 자체라, 두 번째 도메인이 붙자 첫 번째 도메인의 규칙이 그대로 제약이 됐다.

## 토픽 문자열을 한곳에 모으는 이유

토픽 문자열을 전용 객체에 모으는 건 1편의 `ChatTopics`부터 관례로 따랐는데, 출퇴근 토픽을 추가하면서 이유를 다시 봤다.

```kotlin
object AttendanceTopics {
  fun workspaceAttendance(workspaceId: Long): String = "/topic/workspace.$workspaceId.attendance"
  val WORKSPACE_ATTENDANCE_PATTERN = Regex("""^/topic/workspace\.(\d+)\.attendance$""")

  fun accountAttendance(accountId: Long): String = "/topic/attendance.account.$accountId"
  val ACCOUNT_ATTENDANCE_PATTERN = Regex("""^/topic/attendance\.account\.(\d+)$""")
}
```

발행 목적지(`convertAndSend`가 쓰는 문자열)와 구독 게이트 정규식(인터셉터가 쓰는 패턴)이 한 객체에 있다. 둘이 따로 문자열을 만들다 포맷이 어긋나면, 운이 좋으면 메시지가 안 가서 바로 드러난다. 운이 나쁘면 정규식이 목적지와 안 맞아 검증 대상에서 빠진다. 인터셉터는 패턴에 안 걸리는 목적지를 `return true`로 통과시키기 때문이다. task-request 토픽이나 `/user` 큐를 허용하려는 정당한 기본값인데, 정규식이 어긋나면 게이팅해야 할 토픽도 같은 문으로 빠져나간다. 인가가 사라졌는데 기능은 멀쩡히 동작하고, 컴파일러도 아무 말을 안 한다.

1편 §1의 회귀도 프론트가 `workspace.0`이라는 죽은 토픽을 구독해 에러 한 줄 없이 알림이 안 온 일이었다. 그때는 전달 실패로 시끄럽게, 여기서는 인가 우회로 조용하게 깨질 수 있다. 조용히 깨질 수 있는 결합이라 한곳에 모았다.

## 정리

| 층 | 재사용 여부 | 이유 |
|---|---|---|
| STOMP 엔드포인트·브로커 릴레이 | 그대로 재사용 | 전송은 도메인을 모른다 |
| 인증(CONNECT 시 JWT 검증) | 그대로 재사용 | 계정 확인은 도메인 무관 |
| 구독 인가(SUBSCRIBE 게이트) | **도메인별로 분리** | 인가는 도메인 규칙 그 자체 |
| 페이로드 설계 | **정반대로 설계** | 채팅은 본문이 콘텐츠, 출퇴근은 값이 공유 상태 |
| 토픽 문자열 관리 | 같은 패턴 반복 | 조용히 깨지는 결합이라 SSOT 강제 |

인프라를 재사용한다는 건 전송 계층을 재사용한다는 뜻이었지 도메인 규칙까지 물려받는다는 뜻이 아니었다. 그 경계가 인가에서 먼저, 페이로드에서 한 번 더 드러났다.

남은 건 재연결 사이에 놓친 알림이다. thin notification이라 다음 알림 하나가 전체를 정정하지만, 그 알림이 한동안 안 오면 화면은 오래된 채로 남는다. 채팅 목록의 30초 폴링 같은 안전망이 출퇴근에도 필요한지는 실제 사용 패턴을 보고 판단하려 한다.

---

> **관련 글:** [어드민 채팅 cross-workspace 실시간 회귀 — STOMP multi-subscribe로 해결한 이야기]({% post_url 2026-06-01-admin-chat-cross-workspace-websocket %}) · [한 브로커(ActiveMQ), 두 메시징 패턴]({% post_url 2026-07-01-broker-one-two-messaging-patterns %}) · [실시간 활동 로그 파이프라인 (3) — 트랜잭션 경계와 발행 타이밍]({% post_url 2026-06-30-activity-log-3-transaction-and-publish %})
