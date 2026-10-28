---
title: "[TIL] 권한 DSL이 표현하지 못하는 갈래, 그리고 '있는가'를 목록으로 답하는 쿼리"
date: 2026-09-10 14:00:00 +0900
categories: [TIL]
tags: [backend, spring, jpa, kotlin, authorization, query-optimization]
---

상세 조회 하나에 접근 게이트를 붙이다가 두 가지를 겪었다. 하나는 권한 DSL로 표현할 수 없는 조건을 어디에 둘지였고, 다른 하나는 그 판정을 구현한 쿼리가 실은 목록 조회였다는 것이다.

## DSL로 표현할 수 없는 갈래

이 코드베이스는 컨트롤러에서 `withAccess(...)` 한 줄로 권한을 건다. 규칙을 나열하면 OR 로 묶이고, 하나라도 통과하면 핸들러가 실행된다. 컨트롤러만 훑어도 "누가 이 API 를 부를 수 있는가"를 알 수 있다는 게 장점이다.

```kotlin
withAccess(
  inTenant(tenantId).user(),
  worker().managerOf(tenantId),
  admin().permissions(REQUEST_VIEW),
) { service.get(id) }
```

이번 상세 화면의 게이트는 두 갈래였다. ① 해당 조직의 관리자 역할이거나, ② 그 보고를 참조하는 하위 요청에 배정된 실무자이거나. ②는 인증 컨텍스트만으로는 답할 수 없다. 요청 테이블을 조회해서 배정자에 이 계정이 있는지 봐야 한다.

②를 빠뜨리면 배정된 실무자가 원본 보고에서 403 을 받는다. 첨부 사진은 하위 요청으로 승계되지 않으니, 그 사람은 사진 없이 요청 본문만 보고 현장에 가게 된다.

DSL 에는 이런 경우를 위한 탈출구가 있다. 계정 타입, 실패 메시지, `(accountId) -> Boolean` 람다를 받는 규칙이다.

```kotlin
allowIf(AccountType.WORKER, "이 보고에 접근할 권한이 없습니다") { accountId ->
  reportAccessChecker.isAssigneeOfLinkedRequest(id, accountId)
}
```

`worker().assigneeOfLinkedRequestOf(id)` 같은 체이닝을 DSL 에 하나 더 만드는 방법도 있었지만, 그러면 DSL 이 도메인 리포지토리를 알게 되고 도메인이 늘 때마다 메서드가 따라 늘어난다. 반대로 람다 안에 로직을 바로 쓰면 권한 로직이 컨트롤러 곳곳으로 흩어진다.

그래서 인증 컨텍스트만으로 답할 수 있는 조건은 DSL 에 두고, 도메인 조회가 필요한 조건은 `ReportAccessChecker.isAssigneeOfLinkedRequest` 처럼 이름 있는 컴포넌트로 뺀 뒤 `allowIf` 로 한 번만 연결했다.

컨트롤러 KDoc 에는 게이트가 두 갈래인 이유와 빠뜨리면 생기는 일을 적었다. 이 규칙은 나중에 누가 중복처럼 보고 지워도 컴파일 에러도 테스트 실패도 나지 않고, 특정 역할의 403 으로만 드러나기 때문이다. 목록 조회에는 ②를 열지 않았다는 것도 같이 적었다. 상세는 링크를 아는 사람만 열지만 목록은 전량이 노출되니 범위가 다르다.

## "있는가"를 목록 조회로 답하고 있었다

판정 컴포넌트는 이렇게 생겼다.

```kotlin
@Transactional(readOnly = true)
fun isAssigneeOfLinkedRequest(reportId: Long, accountId: Long): Boolean =
  requestRepository
    .findByReportIdAndDeletedAtIsNullOrderByRequestedAtDesc(reportId)
    .any { it.assignee?.id == accountId }
```

처음엔 권한을 옳게 판정하는지만 보고 넘어갔다. 며칠 뒤 삭제 가능 여부 판정에서 같은 모양을 보고서야 패턴이라는 걸 알았다.

```kotlin
private fun hasLinkedRequest(reportId: Long): Boolean =
  requestRepository
    .findByReportIdAndDeletedAtIsNullOrderByRequestedAtDesc(reportId).isNotEmpty()
```

둘 다 동작하고 테스트도 통과한다. 그런데 필요한 답은 boolean 하나인데 하는 일은 목록 조회였다.

- 매칭되는 행을 전부 엔티티로 매핑해 영속성 컨텍스트에 올리지만, 쓰이는 건 `any {}`·`isNotEmpty()` 의 결과 하나다. `readOnly = true` 라 flush 는 막히지만 읽어 온 비용은 그대로다.
- 메서드 끝의 `OrderByRequestedAtDesc` 는 상세 화면의 "연계된 요청" 목록을 최신순으로 보여주려고 만든 것이다. 이걸 판정에 재사용하면서 의미 없는 `ORDER BY` 가 매번 실행되고 있었다.
- `it.assignee?.id` 는 `@ManyToOne(fetch = FetchType.LAZY)` 연관이다. 프록시 초기화 없이 FK 를 돌려줄 수도 있지만, 매핑 조건에 따라 행마다 쿼리가 나갈 수도 있다([계산 프로퍼티 뒤에 숨은 N+1]({% post_url 2026-09-10-hidden-n-plus-one-behind-computed-property %})). 코드만 읽어서는 쿼리가 몇 번 나가는지 확답할 수 없었다.

한 보고에 달리는 요청은 지금 많아야 서너 건이다. 하지만 그 상한을 보장하는 제약은 스키마에 없고, 그보다 `findBy...isNotEmpty()` 는 읽는 사람에게 "목록이 필요한가 보다"라고 말한다는 게 더 걸렸다.

## exists 로 바꿨다

```kotlin
fun existsByReportIdAndAssigneeIdAndDeletedAtIsNull(reportId: Long, assigneeId: Long): Boolean
fun existsByReportIdAndDeletedAtIsNull(reportId: Long): Boolean
```

`exists` 파생 쿼리는 엔티티를 만들지 않고 첫 매칭 행에서 멈춘다. `ORDER BY` 도 사라진다. `assignee_id` 비교가 WHERE 절로 내려가니 LAZY 프록시를 따질 일 자체가 없어졌고, 참조 컬럼에 걸어 둔 부분 인덱스도 그대로 탄다.

## 같은 파일 안에 대조군이 있었다

같은 서비스의 목록 응답 코드는 오히려 잘 짜여 있었다. id 목록을 한 번에 넘겨 `GROUP BY` 로 집계한 뒤 `Map` 으로 붙였고, 첨부 유무도 id 집합으로 한 번에 판정했다([집계값을 저장할 것인가 셀 것인가]({% post_url 2026-09-10-denormalized-counter-when-not-to-store %})). 목록에서는 N+1 을 의식했는데 판정에서는 놓친 것이다.

목록은 느려지면 화면에서 바로 티가 난다. 권한 판정은 성공하면 로그도 없고, 느려도 "상세가 좀 느리네" 정도로 묻힌다. 피드백이 돌아오지 않는 자리라 성능을 안 보게 된 것 같다. 이후로는 리포지토리 메서드를 재사용할 때 이름 끝의 `OrderBy` 를 신호로 본다. 정렬이 붙어 있으면 화면용으로 만든 메서드이고, 그걸 판정에서 쓰고 있다면 `existsBy` 로 바꿀 자리일 가능성이 높다.
