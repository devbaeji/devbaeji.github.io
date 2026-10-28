---
title: "[TIL] 무엇을 트랜잭션 안에 넣고 무엇을 커밋 이후로 미룰 것인가 — 그리고 아무것도 잡지 못하는 try-catch"
date: 2026-09-10 13:00:00 +0900
categories: [TIL]
tags: [backend, spring, transaction, jpa, event-driven, kotlin]
---

등록 API 하나에서 같은 메서드의 두 부수 작업이 서로 다른 경계로 갈렸다. 그리고 내가 넣은 방어 코드가 구조적으로 아무것도 잡을 수 없다는 걸 뒤늦게 알았다.

## 첨부는 안에, 알림은 커밋 뒤에

등록 메서드는 엔티티를 저장하고, 임시 저장소에 먼저 올라간 첨부를 방금 만든 엔티티에 귀속시키고, 외부 채널에 알림을 발행한다.

```kotlin
@Transactional
fun createReport(accountId: Long, request: CreateRequest): DetailResponse {
  val saved = repository.save(Report(...))

  commitStagedFiles(saved.id, request.fileUuids, accountId) // 트랜잭션 안
  publishReportCreatedEvent(saved)                          // 실행은 커밋 이후

  return saved.toDetail()
}
```

두 줄은 나란히 있지만 기준은 "실패했을 때 되돌릴 수 있는가"로 갈린다. 첨부 귀속은 본 데이터의 일부라 등록이 롤백되면 같이 사라져야 하고, 첨부 검증이 실패하면 등록도 없던 일이 돼야 한다. 커밋 서비스는 `@Transactional(propagation = Propagation.MANDATORY)` 라서 호출자 트랜잭션 밖에서 부르면 조용히 지나가지 않고 바로 실패한다.

외부 알림은 한 번 나가면 회수할 수 없다. 롤백될지 모르는 트랜잭션 안에서 쏘면 존재하지 않는 데이터에 대한 알림이 나가고, 채널이 페이로드의 링크를 바로 되가져오면 아직 커밋되지 않은 데이터를 조회하러 와서 404 를 받는다.

순서도 중요했다. 주석에 "staged 커밋을 알림보다 먼저, 같은 트랜잭션에서 한다. 순서를 뒤집거나 빠뜨리면 파일이 임시 경로에만 남아 일정 기간 뒤 사라지는데 컴파일·테스트·화면은 전부 통과한다"고 남겼다. 첨부 귀속을 빠뜨려도 등록 API 는 200 을 주고 상세 화면에도 파일이 보인다. 임시 파일의 수명 정책이 만료되고 며칠 뒤에야 "첨부가 사라졌다"는 제보로 드러날 버그라, 그때는 원인 커밋을 찾기 어렵다.

## AFTER_COMMIT 리스너가 시점을 대신 지킨다

"커밋 이후에 보낸다"를 사람이 지키는 규칙으로 두지 않고 리스너에 맡겼다.

```kotlin
@Async
@TransactionalEventListener(phase = TransactionPhase.AFTER_COMMIT, fallbackExecution = true)
fun onNotification(event: ReportCreatedEvent) { ... }
```

일반 `@EventListener` 라면 `publishEvent` 가 그 자리에서 리스너를 동기 호출한다. `@TransactionalEventListener` 는 현재 트랜잭션의 동기화 콜백으로 등록만 하고, 본문은 커밋이 성공한 뒤에 실행한다. 롤백되면 아예 실행되지 않는다. `fallbackExecution = true` 가 없으면 트랜잭션 밖에서 발행된 이벤트는 예외도 로그도 없이 스킵된다. 테스트에서만 알림이 안 나가거나 스케줄러 같은 경로에서 발행할 때 이 기본값을 모르면 엉뚱한 곳을 뒤지게 된다.

첨부도 같은 원리로 나눴다. 임시 경로에서 정식 경로로 객체를 복사하는 스토리지 왕복은 파일이 수십 개면 수 초가 걸려서 `AFTER_COMMIT` 리스너로 뺐다. 트랜잭션 안에는 참조 컬럼을 채우는 데까지만 남겼다.

## 내가 넣은 try-catch 는 아무것도 잡지 못했다

기능이 동작하는 걸 확인하고 내 코드를 다시 읽다가 발행부에서 걸렸다.

```kotlin
private fun publishReportCreatedEvent(report: Report) {
  // 알림 발행 실패가 등록 자체를 되돌리면 안 된다 — 다른 도메인과 같은 처리다.
  try {
    eventPublisher.publishEvent(ReportCreatedEvent(...))
  } catch (e: Exception) {
    logger.error(e) { "이벤트 발행 실패: id=${report.id}" }
  }
}
```

주석이 걱정하는 건 "알림이 실패해서 등록이 롤백되는 것"이다. 이 방어가 잡을 수 있는 예외를 하나씩 세어 봤다.

- 리스너는 `AFTER_COMMIT` 이다. 본문은 커밋이 끝난 뒤 실행되니, 거기서 무슨 예외가 나든 등록은 롤백될 수 없다.
- 리스너는 `@Async` 다. 다른 스레드의 예외는 이 `try` 로 전파되지 않고 `AsyncUncaughtExceptionHandler` 로 간다. 반환 타입이 `Unit` 이라 `Future` 도 없다.
- 남는 건 이벤트 객체를 만들고 `publishEvent` 로 등록하는 동안의 코드뿐이다. 그런데 거기서 나는 예외는 롤백돼야 할 버그다. `logger.error` 로 삼키면 등록은 성공하고 알림만 아무도 모르게 사라진다.

결국 이 코드는 드러나야 할 버그를 삼키고, "알림이 실패해도 안전하다"는 잘못된 안심까지 준다. 실제 안전장치는 리스너 어노테이션에 있는데 방어 코드는 발행부에 있으니, 나중에 누가 리스너를 `BEFORE_COMMIT` 으로 바꾸거나 `@Async` 를 떼도 "여기서 막고 있으니 괜찮다"고 읽을 수 있다.

이 try-catch 는 내가 판단해서 넣은 게 아니라 같은 이벤트를 발행하는 다른 도메인의 코드를 가져온 것이었다. 복사는 코드만 옮기고 전제는 옮기지 않는다. 원본을 쓸 때는 리스너가 동기였거나 트랜잭션 이벤트가 아니었을 수 있고, 그랬다면 그 방어는 타당했을 것이다(추정이다). 그 전제는 주석에 남지 않는다. 이후로는 기존 코드를 가져올 때 그 전제가 지금도 성립하는지 확인하고, 확인이 안 되면 "다른 도메인과 동일"이라고 쓰지 않는다. 근거처럼 보이지만 실제로는 근거를 찾지 않았다는 말에 가깝다.

## 방어는 소비부에 둔다

알림 실패에 필요한 재시도, 실패 이력, 반복 실패 격리는 외부 호출을 하는 리스너의 책임이다. 실제로 리스너 안에서는 구독 대상별 발송 루프를 개별 `try-catch` 로 감싸서 한 대상의 실패가 나머지를 막지 않게 하고 있다. 무엇을 왜 잡는지가 분명한 방어다.

`AFTER_COMMIT` 은 커밋된 것만 알린다는 순서는 보장하지만 전달은 보장하지 않는다. 커밋 직후 프로세스가 죽으면 이벤트는 사라진다. 더 강한 보장이 필요하면 알림 레코드를 같은 커밋으로 테이블에 남기고 별도 워커가 발송·재시도하는 transactional outbox 로 간다. 테이블·워커·중복 발송 대비가 붙으니 유실이 실제로 아픈 도메인에만 쓸 생각이다.

## 정리

방어 코드를 넣기 전에 그것이 잡을 수 있는 예외를 하나라도 셀 수 있는지 확인한다. 세어 보고 없으면 그 코드는 안전장치가 아니라 잘못된 안심의 근거가 된다.
