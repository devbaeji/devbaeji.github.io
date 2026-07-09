---
title: "한 브로커(ActiveMQ), 두 메시징 패턴 — 채팅(STOMP 토픽)과 활동 로그(VirtualTopic 큐)를 왜 다르게 구현했나"
date: 2026-07-01 09:00:00 +0900
categories: [Backend, Event-Driven]
tags: [ActiveMQ, STOMP, JMS, WebSocket, Spring]
---

> **[실시간 활동 로그 파이프라인]({% post_url 2026-06-30-activity-log-1-problem-and-design %}) 시리즈의 심화편.**
> 4편에서 "ActiveMQ를 새로 띄우지 않고 이미 채팅이 쓰는 걸 재사용했다"고 적었다. 그런데 같은 브로커를 재사용하면서도 채팅과 활동 로그는 **의도적으로 다른 메시징 패턴**으로 구현했다. 이 글은 그 "왜 다르게 짰나"에 대한 기록이다.

---

우리 백엔드에는 Amazon MQ(ActiveMQ) 브로커가 하나 떠 있다. 원래는 채팅용이었다. [활동 로그 파이프라인]({% post_url 2026-06-30-activity-log-4-going-further %})을 만들면서 이 브로커를 그대로 재사용했는데, 재사용했다고 해서 **같은 방식으로** 쓴 건 아니다. 오히려 정반대에 가깝다.

- **채팅**: STOMP relay + **토픽(Topic)** — 접속 중인 브라우저에 실시간으로 밀어준다.
- **활동 로그**: OpenWire(JMS) + **VirtualTopic → Consumer 큐** — 백엔드 리스너가 내구 큐에서 꺼내 처리한다.

프로토콜도, destination 종류도, 내구성도, 소비 의미도 전부 다르다. 하나의 브로커 위에서 이렇게 갈라진 이유는 단순하다. **요구사항이 다르면 맞는 메시징 패턴도 다르다.** "동작한다"가 아니라 "요구사항 → 패턴"의 매핑을 알고 골랐다는 게 이 글의 핵심이다.

## 1. 두 구조를 한 표로

먼저 전체 대비부터 놓는다. 이 표의 각 행이 왜 그렇게 갈렸는지를 이후 절에서 하나씩 푼다.

| 축 | 채팅 | 활동 로그 파이프라인 |
|---|---|---|
| 목적 | 브라우저에 실시간 push | 서버 간 이벤트 처리(감사/활동 로그) |
| 소비자 | WebSocket 클라이언트(브라우저) | 백엔드 JMS 리스너 |
| 프로토콜 | STOMP relay | OpenWire(JMS) |
| destination | Topic (fan-out) | VirtualTopic → `Consumer.*` 큐 |
| 내구성 | 비내구(non-durable), 유실 허용 | 내구 큐, 컨슈머 다운 시 보존 |
| 처리 의미 | 접속자 전원 브로드캐스트 | 그룹당 1회 처리 + 그룹 간 fan-out |
| 포트(local / dev·prod) | STOMP 61613 / 61614(SSL) | OpenWire 61616 / 61617(SSL) |

같은 호스트, 같은 계정(`ACTIVEMQ_*` env 재사용), 심지어 설정 파일 주석에도 "STOMP relay와 다른 점은 프로토콜·포트뿐"이라고 적어뒀다. 물리적으로는 한 브로커다. 논리적으로는 완전히 다른 두 파이프다.

## 2. 채팅 = STOMP 토픽 — "지금 보고 있는 사람에게만"

채팅의 요구는 명확하다. 채팅방에 **접속 중인** 사람들의 브라우저에 메시지를 즉시 띄우는 것. 여기서 두 가지 성질이 나온다.

- **실시간 push가 목적**이다. 브라우저는 JMS 리스너를 돌릴 수 없으니, WebSocket 위에 STOMP를 얹어 브로커가 클라이언트로 직접 프레임을 밀어준다.
- **유실을 허용**해도 된다. 메시지 원본은 이미 DB에 저장된다. 브로커는 "실시간 전달" 채널일 뿐이라, 접속 안 한 사람은 받지 못해도 그만이다(재접속 시 DB에서 히스토리를 다시 읽는다).

그래서 destination이 **토픽**이다. 토픽은 그 순간 구독 중인 세션 전원에게 복제해 던지고, 아무도 안 듣고 있으면 그냥 버린다. 정확히 "접속자 전원 브로드캐스트, 나머지는 유실 허용"이라는 요구와 맞는다.

```kotlin
// WebSocketConfig.kt — 배포 환경은 외부 브로커로 relay
config
  .enableStompBrokerRelay("/topic", "/queue")
  .setRelayHost(relayHost)
  .setRelayPort(relayPort)          // dev/prod 61614 (SSL)
  .setClientLogin(relayLogin)
  .setClientPasscode(relayPasscode)
// SSL이면 ReactorNettyTcpClient에 .secure()
config.setApplicationDestinationPrefixes("/app")  // 클라 → 서버
config.setUserDestinationPrefix("/user")           // 개인 큐
```

토픽 이름은 한 객체(`ChatTopics`)에 모아 SSOT로 둔다.

```kotlin
// ChatTopics.kt
fun room(roomId: Long): String = "/topic/chat.$roomId"
fun roomTyping(roomId: Long): String = "/topic/chat.$roomId.typing"
fun workspaceChatNotify(workspaceId: Long): String =
  "/topic/workspace.$workspaceId.chat-notify"
```

`StompBrokerRelay`를 쓰는 결정적 이유는 **멀티 인스턴스 fan-out**이다. WebSocket 서버가 여러 대일 때, 방 참가자들은 서로 다른 인스턴스에 붙어 있을 수 있다. 각 인스턴스의 인메모리 브로커로는 다른 인스턴스의 구독자에게 닿지 못한다. 외부 ActiveMQ를 공용 브로커로 두고 전 인스턴스가 relay하면, `convertAndSend("/topic/chat.42")` 한 번으로 어느 인스턴스에 붙은 참가자든 전부 받는다.

> **STOMP relay vs SimpleBroker**
>
> `enableStompBrokerRelay`는 STOMP 프레임을 **외부 브로커(ActiveMQ)** 로 넘겨 브로커가 라우팅·fan-out을 맡는다. 멀티 인스턴스에서 인스턴스 경계를 넘어 브로드캐스트가 된다.
>
> `enableSimpleBroker`는 Spring 앱 **프로세스 내부 메모리** 에 브로커를 둔다. 외부 의존성이 없어 로컬·CI에 편하지만, 브로드캐스트가 그 인스턴스 안에서만 유효하다.
>
> 우리 로컬은 `activemq.stomp.relay.enabled: false`라 SimpleBroker 폴백이다. 단일 인스턴스라 그걸로 충분하다.
{: .prompt-info }

## 3. 활동 로그 = VirtualTopic + Consumer 큐 — "죽어도 쌓였다가 처리"

활동 로그의 요구는 채팅과 근본적으로 다르다. 소비자가 **브라우저가 아니라 백엔드**다. 티켓 변경 이벤트를 받아 `activity_events` 테이블에 적재하고(향후), 알림을 만들고, 분석에 넣는 **서버 측 처리**가 목적이다. 여기서 두 성질이 뒤집힌다.

- **내구성이 필요**하다. 적재 소비자가 배포·장애로 잠깐 죽어도, 그 사이 발생한 이벤트가 사라지면 피드에 구멍이 난다. 컨슈머가 다시 뜰 때까지 브로커가 **큐에 쌓아두고** 있어야 한다.
- **그룹당 정확히 1회 처리 + 그룹 간 fan-out**이 필요하다. 적재 소비자가 멀티 인스턴스로 3대 떠 있으면, 한 이벤트를 3번 적재하면 안 된다(그룹 안에선 1대만 처리). 반대로 나중에 "알림 소비자 그룹", "분석 소비자 그룹"을 붙이면 **각 그룹은 모든 이벤트를 독립적으로** 받아야 한다.

이 두 요구를 정확히 채워주는 게 ActiveMQ의 **VirtualTopic**이다. 발행은 토픽으로 하되, 각 소비 그룹은 자기 이름이 붙은 **내구 큐**로 복제본을 받는다. Kafka의 컨슈머 그룹과 사실상 같은 의미다.

```
                       발행 (JMS, pubSubDomain=true)
                       VirtualTopic.myapp.activity.events
                                  │  브로커가 그룹별 큐로 복제
        ┌─────────────────────────┼─────────────────────────┐
        ▼                         ▼                         ▼
Consumer.loader.VirtualTopic…  Consumer.notifier.V…   Consumer.analytics.V…
  (적재 그룹, 큐)                (알림 그룹, 큐)          (분석 그룹, 큐)
  인스턴스 3대가                 그룹 내 1회 처리          그룹 내 1회 처리
  경쟁 소비 → 그룹당 1회
```

발행 쪽 JMS 설정은 채팅과 대비된다. 채팅은 STOMP지만, 활동 로그는 **OpenWire(JMS) `JmsTemplate`** 으로 발행하고, VirtualTopic이므로 `pubSubDomain=true`다.

```kotlin
// ActivityJmsConfig.kt
@Bean
fun activityConnectionFactory(): ConnectionFactory =
  ActiveMQConnectionFactory(brokerUrl).apply {   // OpenWire: tcp:// or ssl://
    userName = user
    this.password = this@ActivityJmsConfig.password
  }

@Bean
fun activityMessageConverter(): MessageConverter =
  MappingJackson2MessageConverter().apply {
    setTargetType(MessageType.TEXT)   // JMS TextMessage, 본문 = JSON
    setTypeIdPropertyName("_type")
  }

@Bean
fun activityJmsTemplate(...): JmsTemplate =
  JmsTemplate(connectionFactory).apply {
    isPubSubDomain = true             // VirtualTopic으로 발행
  }
```

구독 쪽(`Consumer.*` 큐)은 반대로 **큐이므로 `pubSubDomain=false`** 다. fan-out은 이미 VirtualTopic이 큐를 나눠줄 때 끝났으니, 리스너 입장에선 평범한 큐 소비다.

```kotlin
// ActivityDebugConsumer.kt — 큐 소비이므로 pubSubDomain=false
@Bean
fun activityDebugListenerFactory(): DefaultJmsListenerContainerFactory =
  DefaultJmsListenerContainerFactory().apply {
    setConnectionFactory(connectionFactory)
    setPubSubDomain(false)           // fan-out은 VirtualTopic이 처리
  }
```

> **VirtualTopic**
>
> ActiveMQ가 "토픽의 fan-out"과 "큐의 내구·경쟁소비"를 합쳐주는 관례다. `VirtualTopic.<이름>`으로 발행하면, 브로커가 각 소비 그룹마다 `Consumer.<group>.VirtualTopic.<이름>` 이라는 **내구 큐**를 만들어 복제본을 넣는다.
>
> 한 그룹 안에서는 여러 컨슈머가 그 큐를 경쟁 소비(그룹당 1회 처리), 그룹끼리는 각자 큐라서 서로 독립(fan-out). 컨슈머가 다 죽어도 큐에 메시지가 쌓여 있다가 복구 시 처리된다 — 이게 일반 토픽에는 없는 내구성이다.
{: .prompt-info }

## 4. 바꿔 쓰면 왜 틀리나

두 패턴을 서로 바꿔 끼우면 각각 무엇이 깨지는지가, 이 선택이 임의가 아니라는 증거다.

| 잘못된 선택 | 무엇이 깨지나 |
|---|---|
| 활동 로그를 **일반 토픽**으로 | ① 적재 소비자가 배포/장애로 죽은 동안 이벤트 **유실**(토픽은 안 듣는 순간 버림). ② 멀티 인스턴스가 모두 구독하면 한 이벤트를 **N번 중복 처리**(그룹당 1회 개념이 없음). |
| 채팅을 **내구 큐**로 | ① 브라우저 push엔 과한 내구성 — 접속 안 한 유저마다 큐에 메시지가 **적체**되어 브로커 부담. ② 큐는 경쟁 소비라, 한 방에 여러 세션이 붙으면 메시지가 세션들에 **나뉘어** 가고 전원 브로드캐스트가 깨진다. |

핵심은 **"내구성"과 "fan-out 의미"** 두 축이다. 채팅은 (비내구, 구독자 전원) 조합이 맞고, 활동 로그는 (내구, 그룹당 1회 + 그룹 간 fan-out) 조합이 맞는다. 브로커가 같다고 이 두 축을 같게 두면 반드시 한쪽이 틀어진다.

> **Q.** 활동 로그도 결국 "여러 소비처에 뿌린다"인데, 채팅처럼 그냥 토픽 쓰면 안 되나?
>
> 안 된다. 겉보기 fan-out은 같아 보여도 **내구성 요구가 다르다.**
>
> 채팅 토픽은 "지금 듣는 사람에게만, 못 들으면 버림"이다. 브라우저 소비자는 늘 붙었다 떨어졌다 하고, 못 받은 메시지는 DB 히스토리로 복구하니 유실이 허용된다. 반면 활동 로그의 소비자는 백엔드다. 배포로 30초 죽은 사이 들어온 티켓 변경 이벤트가 토픽이라 증발하면, 그 30초치 활동은 **어디에도 안 남는다**(활동 로그 자체가 소스라 복구원이 없다). VirtualTopic의 `Consumer.*` 큐는 이 30초를 큐에 담아뒀다가 컨슈머가 뜨면 밀어준다.
>
> *진짜 차이는 fan-out이 아니라 "컨슈머 부재 구간을 견디는가"다.* 그래서 같은 브로커라도 채팅은 토픽, 활동 로그는 VirtualTopic 큐로 갈라진다.
{: .prompt-tip }

## 5. 구현하며 부딪힌 함정 — 순환 참조로 앱이 안 뜬다

이론만으로는 안 나오는 함정이 하나 있었다. dev에서 큐를 눈으로 확인하려고 디버그 구독자를 붙이다가 **Spring 부팅이 통째로 실패**했다.

원인은 JMS 설정 클래스 구조였다. `@Configuration @EnableJms` 클래스 안에 `@JmsListener` 메서드와, **그 리스너가 참조하는 `containerFactory @Bean`** (`DefaultJmsListenerContainerFactory`)을 **같이** 뒀다. 그러면 config 빈을 만드는 도중에 `JmsListenerAnnotationBeanPostProcessor`가 아직 생성 중인 팩토리 빈을 요구한다.

```
Requested bean is currently in creation: Is there an unresolvable
circular reference or an asynchronous initialization dependency?
  → BeanCurrentlyInCreationException → 앱 기동 실패
  → 컨테이너에선 CrashLoopBackOff
```

해결은 **리스너를 별도 `@Component`로 분리**하는 것이었다. 팩토리 `@Bean`은 `@Configuration`에 남기고, `@JmsListener`만 다른 컴포넌트로 뺐다. 실제로 이렇게 고쳐서 정상 기동했고, 그 흔적이 코드 주석에 남아 있다.

```kotlin
// ActivityDebugConsumer.kt
// NOTE: @JmsListener를 이 설정 클래스에 직접 두면 컨테이너 팩토리 빈 생성과
// 순환 참조("bean is currently in creation")가 발생하므로, 리스너는
// 별도 ActivityDebugListener 컴포넌트로 분리한다.

@Configuration
@EnableJms
@ConditionalOnProperty(name = ["activity.debug.consumer"], havingValue = "true")
class ActivityDebugConsumer(...) {
  @Bean
  fun activityDebugListenerFactory(): DefaultJmsListenerContainerFactory = ...
}

@Component   // ← 리스너는 분리
@ConditionalOnProperty(name = ["activity.debug.consumer"], havingValue = "true")
class ActivityDebugListener {
  @JmsListener(destination = QUEUE, containerFactory = "activityDebugListenerFactory")
  fun onMessage(body: String) { ... }
}
```

함정은 여기서 끝이 아니었다. 디버그 구독자는 `@ConditionalOnProperty(activity.debug.consumer=true)`로 게이팅되는데, 이 빈은 `activityConnectionFactory`에 의존한다. 그런데 그 팩토리는 **`activity.pipeline.enabled=true`일 때만** 생성된다. 즉 두 플래그가 어긋나면 또 못 뜬다.

> **Q.** `debug.consumer=true`인데 `pipeline.enabled=false`면 어떻게 되나?
>
> 앱이 기동에 실패한다.
>
> `ActivityDebugConsumer`는 `activityConnectionFactory`를 주입받는데, 그 팩토리 빈은 `ActivityJmsConfig`에 걸린 `@ConditionalOnProperty(activity.pipeline.enabled=true)` 때문에 pipeline이 꺼져 있으면 아예 존재하지 않는다. 존재하지 않는 빈을 주입하려니 `UnsatisfiedDependency`로 부팅이 깨진다.
>
> 그래서 두 플래그는 **세트로** 켜져야 한다. dev는 둘 다 ON(`pipeline.enabled: true`, `debug.consumer: true`)으로 큐 적재를 검증하고, **운영 yml은 `debug.consumer: false`로 고정**해 아예 큐 생성·구독을 원천 차단했다. prod yml 주석에도 "debug.consumer=true이면서 pipeline.enabled=false이면 activityConnectionFactory 부재로 기동 실패하므로 false 고정"이라고 근거를 박아뒀다.
>
> *조건부 빈은 "이 빈이 의존하는 다른 조건부 빈"까지 함께 봐야 한다.* 플래그를 독립적으로 다루면 조합에서 터진다.
{: .prompt-danger }

## 6. 큐는 "구독하는 순간" 생긴다 — 채팅과 같은 원리

VirtualTopic의 `Consumer.*` 큐는 콘솔에서 수동으로 만들 필요가 없다. **컨슈머가 구독하는 순간 ActiveMQ가 자동 생성**한다. 이건 채팅 토픽이 `convertAndSend` 하는 순간 생기는 것과 같은 원리다 — destination은 선언이 아니라 사용으로 만들어진다.

```kotlin
// ActivityDebugListener.kt
private const val QUEUE = "Consumer.qa.VirtualTopic.myapp.activity.events1"
```

이 리스너가 뜨면 `Consumer.qa.VirtualTopic.myapp.activity.events1` 큐가 브로커에 생긴다. 반대로 앱이 죽어 있으면(=아무도 구독 안 하면) 콘솔에 큐가 **안 보이는 것도 정상**이다. "큐가 없다"가 아니라 "아직 아무도 구독을 안 했다"는 뜻이다. 이걸 모르면 "왜 콘솔에 큐가 없지?" 하고 한참 헤맨다.

## 7. 콘솔에서 보는 법 — 어느 탭에서 뭐가 보이나

마지막으로 실무 팁. 두 패턴은 ActiveMQ 웹 콘솔에서 **서로 다른 탭**에 뜬다. 이걸 알아야 디버깅이 빠르다.

- **채팅 destination → Topics 탭.** 채팅은 대부분 토픽이라 `queues.jsp`가 아니라 `topics.jsp`에서 봐야 한다. STOMP의 `/topic/`·`/queue/` 접두사는 **프레임 상 타입 표시일 뿐**이라, 콘솔엔 접두사를 뗀 이름(`chat.42`)으로 보인다.
- **활동 로그 `Consumer.*` → Queues 탭.** VirtualTopic 원본은 Topics에, 그룹별 복제 큐는 Queues에 뜬다. 실제 메시지가 쌓이는 곳은 큐 쪽이다.

> **로컬에서 채팅이 도커 브로커 콘솔에 안 뜨는 이유**
>
> 로컬은 `activemq.stomp.relay.enabled: false`라 채팅이 **인메모리 SimpleBroker**로 돈다. 즉 채팅 토픽은 Spring 앱 프로세스 안에만 있고, 도커로 띄운 ActiveMQ 콘솔엔 **채팅 관련 destination이 하나도 안 뜬다.**
>
> 반면 활동 로그는 로컬에서도 OpenWire로 실제 도커 브로커에 발행하므로(`pipeline.enabled: true`), `Consumer.qa.VirtualTopic...` 큐는 콘솔 Queues 탭에 보인다. "채팅은 콘솔에 없고 활동 로그만 있는" 로컬의 비대칭이 여기서 나온다.
{: .prompt-warning }

## 정리

같은 브로커 위에서 두 패턴이 갈라진 걸 한 줄로 압축하면 이렇다.

> **채팅은 (비내구 토픽 + STOMP relay)로 "접속자 전원 실시간 push, 유실 허용"을, 활동 로그는 (내구 VirtualTopic 큐 + OpenWire JMS)로 "컨슈머 부재를 견디는 그룹당 1회 처리 + 그룹 간 fan-out"을 구현했다.**

브로커를 재사용한 건 인프라 비용 절감이지만, 패턴까지 재사용하지 않은 건 요구사항이 달랐기 때문이다. 실시간 전달과 내구 처리, 전원 브로드캐스트와 그룹 소비 — 이 축들이 다르면 "같은 ActiveMQ"라도 서로 다른 도구가 된다. 메시지 브로커를 고르는 일보다, **고른 브로커 안에서 어떤 메시징 패턴을 쓰느냐**가 실제 설계의 대부분을 결정한다.

---

> **관련 시리즈:** [실시간 활동 로그 파이프라인 (1) — 문제 정의와 설계 결정]({% post_url 2026-06-30-activity-log-1-problem-and-design %}) · [(4) 더 나아가서: Outbox·CDC·Kafka를 알지만 쓰지 않은 이유]({% post_url 2026-06-30-activity-log-4-going-further %})
</content>
</invoke>
