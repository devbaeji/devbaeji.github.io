---
title: "WebSocket 인프라 재사용의 경계 — 전송은 공유하고, 페이로드와 인가는 갈라졌다"
date: 2026-07-16 09:00:00 +0900
categories: [Backend, WebSocket]
tags: [websocket, stomp, spring-messaging, activemq, react-query, system-design]
---

> **[어드민 채팅 cross-workspace 실시간 회귀]({% post_url 2026-06-01-admin-chat-cross-workspace-websocket %})의 후속.**
> 1편은 채팅 하나만 놓고 STOMP·ActiveMQ·React Query가 어떻게 맞물리는지 정리했다. 그 뒤 출퇴근 실시간 반영이 **세 번째 파이프라인**으로 들어오면서 같은 인프라를 재사용했는데, 재사용한 것과 재사용되지 않은 것이 꽤 선명하게 갈렸다. 이 글은 그 경계에 대한 기록이다.

---

우리 백엔드의 실시간 기능은 이제 셋이다. 채팅, 출퇴근 실시간 반영, 그리고 활동 로그 파이프라인.

이 중 앞의 둘은 같은 STOMP 엔드포인트(`/api/ws/chat`), 같은 브로커 릴레이(STOMP 61613 로컬 / 61614 SSL), 같은 인증 인터셉터를 쓴다. 활동 로그만 OpenWire(JMS)로 갈라진다. 브로커 하나 위에서 메시징 패턴이 왜 갈라지는지 — 유실 허용 여부, VirtualTopic, 내구 큐 — 는 [한 브로커, 두 메시징 패턴]({% post_url 2026-07-01-broker-one-two-messaging-patterns %})에서 이미 정리했으니 여기서 다시 다루지 않는다. 발행 타이밍(`AFTER_COMMIT`)과 best-effort 발행의 트레이드오프도 [활동 로그 (3) 트랜잭션 경계와 발행 타이밍]({% post_url 2026-06-30-activity-log-3-transaction-and-publish %})에 있다. 출퇴근 브로드캐스터도 같은 `@TransactionalEventListener(AFTER_COMMIT)` + `runCatching` 조합을 그대로 쓴다.

이 글의 관심사는 다른 데 있다. **채팅과 출퇴근은 프로토콜도 릴레이도 인터셉터도 같은데, 페이로드 설계와 인가에서 갈라졌다.** 세 앱(web/admin/worker)이 각자 갖고 있던 WebSocket 클라이언트 코드를 공통 패키지로 합치는 작업을 하면서 세 파이프라인을 나란히 놓고 볼 일이 있었고, 그때 이 경계가 눈에 들어왔다.

## 1. 같은 STOMP인데 페이로드가 정반대다

채팅 메시지는 **본문이 그대로 페이로드**다. `{"id":1234,"content":"...","sender":...}`가 토픽으로 흐른다.

출퇴근 알림은 정반대다. 브로드캐스터가 싣는 건 식별자와 변경 종류뿐이고, **값 스냅샷이 없다.**

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

출근 시각이 몇 시인지, 상태가 무엇으로 바뀌었는지는 메시지에 없다. "이 출퇴근 기록이 바뀌었다"만 알리고, 클라이언트는 그걸 신호로 REST를 다시 부른다.

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

[1편 §4]({% post_url 2026-06-01-admin-chat-cross-workspace-websocket %})에서 "WebSocket은 시그널, 진실값은 REST"라고 정리했던 그 패턴이다. 다만 그때는 **클라이언트가 payload를 안 보는** 것이었고(서버는 여전히 본문을 실어 보냈다), 이번엔 **서버가 payload에 값을 아예 안 싣는다.** 같은 원칙을 발행 측까지 밀어붙인 셈이다. 클라이언트 규율에 맡기던 걸 타입으로 못 박았다고 봐도 된다.

값을 안 싣는 이유는 일관성이다. 값을 실으면 그 값이 곧 진실이라고 가정하게 되는데, 알림이 재정렬되거나 하나 유실되면 화면이 서버와 다른 상태로 고착된다. 식별자만 던지고 REST로 다시 읽으면 알림이 중복되든 순서가 섞이든 최종 상태가 서버와 같아진다. 대가는 왕복 한 번이다.

반대로 채팅을 thin으로 만들면 손해만 본다. 메시지 본문 자체가 사용자가 기다리는 콘텐츠라, "새 메시지 있음"만 알리고 본문을 REST로 다시 받으면 왕복만 늘고 얻는 게 없다. 같은 패턴을 쓰는 다른 알림(작업 요청 목록 갱신)도 출퇴근과 같은 thin 쪽이다.

> **thin notification vs fat push**
>
> fat push는 왕복이 없는 대신 순서·유실이 곧 화면 오류가 된다. thin notification은 왕복 한 번을 더 내는 대신 알림이 중복·재정렬돼도 최종 상태가 수렴한다. **메시지 자체가 콘텐츠면 fat, 여러 화면이 공유하는 값이 틀리면 안 되면 thin.**
{: .prompt-info }

> **Q.** 출퇴근 알림에 상태값을 같이 실으면 REST 왕복 한 번을 아낄 수 있는데, 왜 안 하나?
>
> 아끼는 게 왕복 하나라면 잃는 건 정합성이다.
>
> 출퇴근 상태는 목록·요약·상세 여러 화면이 동시에 보고 있는 값이다. 알림에 값을 실어 그걸로 화면을 갱신하면, WebSocket이 잠깐 끊긴 사이의 알림을 놓쳤을 때 화면이 조용히 어긋난 채로 남는다. 어긋났다는 사실조차 알 방법이 없다. 식별자만 받고 REST로 읽으면 알림을 몇 개 놓쳤든 다음 알림 하나가 전체를 정정한다.
>
> *알림을 "정보"가 아니라 "트리거"로 보면 유실 설계가 단순해진다.* 트리거는 중복돼도 무해하고 놓쳐도 다음 것이 덮는다. 1편에서 30초 폴링을 안전망으로 둘 수 있었던 것도 같은 이유다 — 폴링과 WebSocket이 결국 같은 invalidate로 모인다.
{: .prompt-tip }

## 2. 인가는 재사용되지 않는다

출퇴근은 채팅 인프라를 통째로 재사용한다. 엔드포인트, 릴레이, `WebSocketAuthInterceptor`까지. 그런데 인가에서 막혔다.

SUBSCRIBE 시점 구독 검증에 쓰는 채팅용 접근 체커는 모바일 작업자 롤을 **`when` 분기에서 항상 거부**한다.

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

채팅 도메인 입장에선 정당한 규칙이다. 작업자는 채팅을 쓰지 않으니까. 문제는 출퇴근이 **작업자 본인이 주인공인 데이터**라는 것이다. 채팅 기준으로 짜인 인가를 그대로 물려받으니, 정작 자기 출퇴근 기록을 구독해야 할 사람이 막혔다.

여기서 선택지는 셋이었다. 채팅 체커에 "출퇴근이면 워커 허용" 분기를 넣거나(채팅 도메인이 출퇴근 규칙을 알게 되는 역방향 의존), 인가를 도메인별로 분리하거나, 인가에 안 걸리는 경로를 새로 파거나.

실제 코드는 목적지에 따라 뒤의 둘로 갈렸다.

**워크스페이스 토픽(`/topic/workspace.{id}.attendance`)** 은 도메인 분리를 택했다. 작업자 관리자 롤만 이 토픽을 구독할 수 있어야 하는데, 그 판정을 채팅 체커에 넣지 않고 출퇴근 도메인 전용 서비스로 뺐다.

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

인터셉터는 목적지를 보고 위임처를 고른다. 일반 사용자·어드민은 기존 채팅 체커를 그대로 재사용하고, 작업자만 출퇴근 전용 체커로 간다.

**개인 토픽(`/topic/attendance.account.{accountId}`)** 은 다른 경로다. 일반 작업자는 워크스페이스 토픽 대신 자기 계정 토픽을 구독하고, 인가는 "네 토픽이 맞냐"는 자기 확인 한 줄로 끝난다.

```kotlin
accountMatch != null -> principal.accountId == accountMatch.groupValues[1].toLong()
```

토픽이 두 갈래가 된 게 출퇴근 도메인의 요구에서 나온 게 아니라는 점이 남는다. 코드 주석에도 "WORKER 를 항상 거부하는 갭을 우회하기 위해"라고 적혀 있다. 개인 토픽 자체는 나쁘지 않다 — 워크스페이스와 무관하게 본인 작업만 보는 화면에는 오히려 더 정확한 단위고, fan-out 범위도 좁다. 다만 그 토픽이 생긴 계기가 도메인 요구가 아니라 남의 인가 제약이었다는 건 구분해서 기억해 둘 만하다.

> **From experience**
>
> WebSocket 인프라를 재사용한다고 할 때 실제로 재사용 가치가 있는 건 연결·릴레이·세션 관리였다. 인가는 아니었다. 전송 계층은 도메인을 몰라도 되지만 인가는 도메인 규칙 그 자체라, 두 번째 도메인이 붙는 순간 첫 번째 도메인의 규칙이 그대로 제약이 됐다. 채팅 체커에 분기를 더하는 대신 도메인 전용 체커를 분리하고 인터셉터가 목적지별로 위임하게 한 게 이 마찰에 대한 답이었다. **전송은 공유하고 인가는 분리한다** — 재사용 단위를 자르는 선이 여기였다.
{: .prompt-tip }

## 3. 토픽 문자열은 SSOT여야 한다 — 이유가 중복 제거가 아니다

채팅과 출퇴근 모두 토픽 목적지 문자열을 전용 객체 하나에 모아둔다. 1편에서 `ChatTopics`를 SSOT로 둔다고 짧게 적었는데, 출퇴근에서 같은 패턴을 반복하면서 이유가 분명해졌다.

```kotlin
object AttendanceTopics {
  fun workspaceAttendance(workspaceId: Long): String = "/topic/workspace.$workspaceId.attendance"
  val WORKSPACE_ATTENDANCE_PATTERN = Regex("""^/topic/workspace\.(\d+)\.attendance$""")

  fun accountAttendance(accountId: Long): String = "/topic/attendance.account.$accountId"
  val ACCOUNT_ATTENDANCE_PATTERN = Regex("""^/topic/attendance\.account\.(\d+)$""")
}
```

한 객체 안에 **발행 목적지**(`convertAndSend`가 쓰는 문자열)와 **구독 게이트 정규식**(인터셉터가 쓰는 패턴)이 나란히 있다. 이유는 중복 제거가 아니다. 두 곳이 각자 문자열을 만들면 포맷이 어긋나는 순간 두 가지 중 하나가 일어난다.

- 운이 좋으면 메시지가 전달되지 않는다. 바로 발각된다.
- 운이 나쁘면 게이트 정규식이 목적지와 안 맞아 **검증 대상에서 빠진다.** 인터셉터는 "게이팅 대상 아님 → 허용"으로 통과시킨다.

두 번째가 무서운 이유는 인가 검사가 사라졌는데 기능은 멀쩡히 동작한다는 것이다. 실제로 인터셉터는 패턴에 안 걸리는 목적지를 `return true`로 통과시킨다 — task-request 토픽이나 `/user` 큐 같은 게이팅 대상 아닌 목적지를 허용하기 위한 정당한 기본값인데, 정규식이 어긋나면 게이팅해야 할 토픽도 같은 문으로 빠져나간다.

1편 §1의 회귀가 떠오르는 대목이다. 그때는 프론트가 `workspace.0`이라는 죽은 토픽을 구독해서 **에러 한 줄 없이** 알림이 안 왔다. 문자열로 이어진 계약은 깨져도 빌드가 통과한다는 게 그때나 지금이나 같고, 다른 건 실패의 방향뿐이다. 그때는 전달이 안 되는 쪽으로(시끄럽게), 여기서는 인가가 빠지는 쪽으로(조용하게) 깨질 수 있다.

> **From experience**
>
> 토픽 문자열을 객체 하나에 모으는 걸 처음엔 관례로만 따랐는데, 출퇴근 토픽을 추가하면서 이유를 다시 봤다. 발행 목적지와 구독 인가 정규식이 문자열로만 연결돼 있으면 한쪽만 고쳐도 컴파일러가 아무 말을 안 한다. 시끄럽게 깨지는 쪽(전달 실패)은 QA에서 잡히지만 조용하게 깨지는 쪽(인가 우회)은 아무도 모른다. **조용한 실패가 가능한 결합이 있으면 그 결합은 한곳으로 모아야 한다**는 게 이 패턴을 반복한 이유였다.
{: .prompt-tip }

## 4. 정리

세 번째 파이프라인을 붙이면서 재사용의 경계가 이렇게 갈렸다.

| 층 | 재사용 여부 | 이유 |
|---|---|---|
| STOMP 엔드포인트·브로커 릴레이 | 그대로 재사용 | 전송은 도메인을 모른다 |
| 인증(CONNECT 시 JWT 검증) | 그대로 재사용 | 계정 확인은 도메인 무관 |
| 구독 인가(SUBSCRIBE 게이트) | **도메인별로 분리** | 인가는 도메인 규칙 그 자체 |
| 페이로드 설계 | **정반대로 설계** | 채팅은 본문이 콘텐츠, 출퇴근은 값이 공유 상태 |
| 토픽 문자열 관리 | 같은 패턴 반복 | 조용히 깨지는 결합이라 SSOT 강제 |

한 줄로 압축하면, **인프라를 재사용한다는 건 전송 계층을 재사용한다는 뜻이지 도메인 규칙까지 물려받는다는 뜻이 아니다.** 채팅이 먼저 자리를 잡은 인프라에 두 번째 도메인이 들어오니 그 경계가 인가에서 제일 먼저 드러났고, 페이로드에서 한 번 더 드러났다. 같은 브로커·같은 프로토콜이라도 [메시징 패턴이 요구사항 따라 갈렸던 것]({% post_url 2026-07-01-broker-one-two-messaging-patterns %})처럼, 같은 WebSocket 인프라라도 도메인이 다르면 갈려야 하는 층이 있다.

남은 숙제는 1편 §8에 적어둔 것들과 이어진다. 재연결 사이에 놓친 알림을 어떻게 보강할지 — 출퇴근은 thin notification이라 다음 알림 하나가 전체를 정정해주지만, 그 "다음 알림"이 한동안 안 오면 화면은 오래된 채로 남는다. 채팅 목록에 둔 30초 폴링 같은 안전망이 출퇴근에도 필요한지는 실제 사용 패턴을 보고 판단할 일이다.

---

> **관련 글:** [어드민 채팅 cross-workspace 실시간 회귀 — STOMP multi-subscribe로 해결한 이야기]({% post_url 2026-06-01-admin-chat-cross-workspace-websocket %}) · [한 브로커(ActiveMQ), 두 메시징 패턴]({% post_url 2026-07-01-broker-one-two-messaging-patterns %}) · [실시간 활동 로그 파이프라인 (3) — 트랜잭션 경계와 발행 타이밍]({% post_url 2026-06-30-activity-log-3-transaction-and-publish %})
