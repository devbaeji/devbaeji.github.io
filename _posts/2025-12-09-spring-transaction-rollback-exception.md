---
title: "예외별 트랜잭션 롤백, 어디까지 기본일까?"
date: 2025-12-09 20:00:00 +0900
categories: [Backend, Spring]
tags: [spring, transaction, rollback, exception]
---

3년 차 백엔드 개발자로 일하면서 트랜잭션 롤백 규칙을 한 번쯤 헷갈린다. 특히 "Checked 예외도 롤백될까?", "@Async에서 예외를 던졌는데 왜 커밋됐지?" 같은 상황이 자주 나왔다. 이번에 공식 문서와 경험을 정리했다.

## 1. 기본 룰 (Spring)
- Unchecked(RuntimeException, Error) → 기본적으로 롤백.
- Checked 예외 → 기본적으로 롤백 안 함. 예상 가능한 예외라고 보고 호출 쪽에서 처리하길 기대한다.
- 데이터 접근 예외 → Spring이 `DataAccessException`(런타임)으로 변환해 일관되게 롤백/처리가 가능하다.

> "Checked면 커밋된다"는 기억만 남기지 말고, 코드 흐름을 설계할 때 어느 계층에서 처리할지 같이 정하는 게 중요했다.
{: .prompt-info }

## 2. 왜 Checked는 기본 롤백이 아닐까?
Checked 예외는 "정상 흐름에서 발생할 수 있는 상황"으로 간주한다. 예를 들어 재고 부족, 외부 API 에러처럼 복구 가능하거나 호출자가 대안을 선택할 수 있는 경우다. 그래서 기본값은 커밋 유지다.

## 3. @Transactional로 원하는 대로 조정하기
비즈니스 요구에 따라 Checked도 롤백하거나, 반대로 특정 Unchecked는 커밋하게 만들 수 있다.

```java
// Checked 예외도 롤백
@Transactional(rollbackFor = NoProductInStockException.class)
public void order() { ... }

// 특정 런타임 예외는 커밋 유지
@Transactional(noRollbackFor = MyRuntimeException.class)
public void updateCacheOnly() { ... }
```

- 규칙이 겹치면 "가장 구체적으로 매칭"되는 규칙이 이긴다.
- 클래스 타입 매칭이 가장 안전하고, 문자열 패턴 매칭(rollbackForClassName 등)은 범위가 넓어지면 다른 규칙을 덮어쓴다.

## 4. 패턴 기반 규칙, 오매칭 주의
`"Exception"`처럼 넓은 패턴을 쓰면 대부분의 예외를 잡아먹어 다른 규칙이 무력화된다. 패키지까지 포함하거나, 아예 클래스 타입 매칭을 쓰는 편이 안전했다. 비슷한 이름의 예외나 중첩 클래스도 매칭될 수 있다는 점도 기억해두자.

## 5. 비동기·함수형 시나리오 (Spring 6.1+)
- Vavr `Try`가 `Failure`로 반환되면 롤백된다.
- `CompletableFuture`/`Future`를 반환하면, **반환 시점에 예외로 완료된 경우** 롤백된다. `@Async` 메서드에서도 동일하게 적용된다.

```java
@Transactional
public Try<String> saveWithTry() {
    return Try.of(() -> repository.save(...)); // Failure면 롤백
}

@Transactional @Async
public CompletableFuture<String> asyncSave() {
    try {
        return CompletableFuture.completedFuture(repository.save(...));
    } catch (DataAccessException ex) {
        return CompletableFuture.failedFuture(ex); // 실패로 완료 → 롤백
    }
}
```

## 6. CMT(EJB/CDI)와의 차이
- CMT 기본: Unchecked만 롤백, Checked는 커밋 유지. 필요 시 `@ApplicationException(rollback = true)`로 강제.
- Spring과 비슷하지만 어노테이션/프레임워크가 다르니 혼동 주의.

## 7. 프로그램 방식 트랜잭션
트랜잭션을 직접 시작/커밋/롤백하는 경우 예외 종류와 관계없이 **직접 `rollback()` 호출**해야 한다. 선언적 트랜잭션과 혼용할 땐 흐름이 꼬이지 않게 경계를 명확히 두는 게 안전했다.

## 8. 실무 체크리스트
- 서비스 레이어에서 Checked 예외를 런타임으로 래핑할지, 그대로 전달할지 규칙 정하기.
- 비즈니스 규칙 예외가 커밋되면 안 된다면 `rollbackFor`를 명시.
- 전역 예외 처리(@ControllerAdvice)와 트랜잭션 롤백 규칙이 충돌하지 않는지 확인.
- `@Async` + 트랜잭션 조합 시 반환 타입을 `CompletableFuture`로 두고 실패를 명확히 전달.
- 통합 테스트에서 예외별 커밋/롤백을 직접 검증해 둔다.

## 정리
기본값(Checked는 커밋, Unchecked는 롤백)을 이해하고, `rollbackFor/noRollbackFor`로 비즈니스 규칙을 명시하면 트랜잭션 흐름이 훨씬 예측 가능해진다. 최근에는 비동기/함수형 케이스까지 프레임워크가 다뤄주니, 팀 룰에 맞춰 명확히 선언해 두는 것이 좋다.
