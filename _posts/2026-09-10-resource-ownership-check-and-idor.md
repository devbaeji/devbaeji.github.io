---
title: "[TIL] 인가를 통과했는데도 남는 구멍 — 리소스 소유권 검증과 IDOR"
date: 2026-09-10 15:00:00 +0900
categories: [TIL]
tags: [backend, security, authorization, idor, spring, kotlin]
---

같은 저장소 안에서 같은 모양의 문제를 서로 다르게 처리한 두 서비스를 발견했다. 오래된 도메인의 조회 헬퍼는 이랬다.

```kotlin
private fun findRequest(tenantId: Long, requestId: Long): Request =
  requestRepository.findById(requestId).orElseThrow {
    RequestNotFoundException()
  }.also { r ->
    if (r.tenant.id != tenantId) throw RequestNotFoundException()
    if (r.deletedAt != null) throw RequestNotFoundException()
  }
```

나중에 만들어진 도메인은 이랬다.

```kotlin
private fun findActive(id: Long): Report =
  reportRepository.findByIdAndDeletedAtIsNull(id) ?: throw ReportNotFoundException()
```

두 번째 함수는 `tenantId` 를 받지 않는다. 컨트롤러는 분명히 받는데도 그렇다.

```kotlin
@GetMapping("/{id}")
fun getReport(
  @PathVariable id: Long,
  @RequestParam tenantId: Long,
): ResponseEntity<ReportDetailResponse> =
  withAccess(
    inTenant(tenantId).user(),
    ...
  ) {
    ResponseEntity.ok(reportService.getReport(id))   // tenantId 가 여기서 사라진다
  }
```

`tenantId` 는 게이트를 통과하는 데만 쓰이고 조회에는 넘어가지 않았다. 상세 조회·수정·삭제 세 경로가 모두 같았다.

## 아무도 보지 않는 관계

파라미터는 `tenantId` 와 리소스 `id` 두 개다. 게이트는 `계정 ↔ tenantId` 만 검증하고, 조회는 `id` 만 쓴다. 그래서 `id ↔ tenantId` 관계는 아무도 검증하지 않는다. 내가 권한을 가진 테넌트 A 로 게이트를 통과한 뒤 테넌트 B 리소스의 `id` 를 넘기면 그대로 열린다. 인증·인가는 통과했는데 식별자가 가리키는 객체가 내 범위인지는 확인하지 않는 결함, IDOR 다.

프런트엔드는 항상 올바른 `tenantId` 를 보내니 화면에는 아무 증상이 없다. QA 는 통과하고, 정상 입력만 넣는 단위 테스트도 통과하고, 정적 분석은 두 파라미터 사이의 도메인 관계를 모른다. 그래서 더 위험하다.

[권한 게이트 DSL]({% post_url 2026-09-10-access-dsl-limits-and-boolean-queries %})이 잘 만들어져 있을수록 착각도 강해진다. `withAccess(inTenant(tenantId).user(), ...)` 를 보면 테넌트 스코프가 이미 걸린 것처럼 읽히지만, 실제로 검증하는 건 "이 계정이 그 테넌트에 속하는가"뿐이다. 같은 도메인의 작업자 분기도 마찬가지였다. 검사기가 `canReadDetail(reportId, tenantId, accountId)` 처럼 세 인자를 다 받지만, 안은 `관리자 역할인가(accountId, tenantId) || 연계 요청의 배정자인가(reportId, accountId)` 라는 OR 였다. 앞 항이 참이면 `reportId` 는 평가되지 않는다. 인자 목록에 있다고 관계를 검증하는 건 아니었다.

원인은 새 도메인을 만들 때 기존 조회 헬퍼를 그대로 가져오지 않고 "삭제 여부만 보면 되겠지"로 단순화한 데 있었다. 방어 코드는 기능이 아니라서 요구사항에도, 화면에도, 테스트에도 잡히지 않는다.

## 조회 시그니처에 스코프를 강제했다

막는 방법은 세 가지를 놓고 봤다.

| 방법 | 강제력 | 비용 |
|---|---|---|
| 호출부마다 수동 검증 | 없음 — 잊으면 끝 | 낮음 |
| 조회 시그니처에 스코프 강제 (`findByIdAndTenantId`) | 높음 — 인자를 안 주면 컴파일 실패 | 낮음 |
| 리포지토리 레벨 필터 (Hibernate `@Filter`, 멀티테넌시) | 매우 높음 — 전역 | 높음, 예외 경로 처리 필요 |

첫 번째는 이미 실패한 방법이다. 기존 도메인에 검증이 있었는데도 새 도메인이 가져오지 않았다. 세 번째는 확실하지만, 켜는 순간 테넌트를 가로질러 조회해야 하는 운영·관리자 경로가 전부 예외 처리 대상이 된다. 이 규모에서는 과하다고 봤다.

그래서 두 번째로 갔다. 조회 메서드를 `findByIdAndTenantIdAndDeletedAtIsNull(id, tenantId)` 로 바꾸면 `tenantId` 없이는 컴파일이 안 된다. 서비스 시그니처에도 `tenantId` 가 올라가고, 컨트롤러가 받아만 두고 버리던 값이 끝까지 흐른다. 기억해야 하는 규칙을 타입이 강제하는 제약으로 옮기는 셈이다. 기존 도메인과 형태도 같아져서, 다음에 새 도메인을 만드는 사람이 참고할 원본이 하나로 정해진다.

실패 응답은 기존 도메인을 따라 404 가 맞다고 봤다. 기존 도메인은 테넌트 불일치와 soft delete 모두에 같은 `NotFoundException` 을 던진다. 403 을 주면 "그 id 의 리소스는 존재한다"는 사실이 새어서, id 를 순회하며 남의 테넌트에 무엇이 있는지 지도를 그릴 수 있다. 하나로 접으니 호출부가 분기할 것도 없다.

## 교차 스코프 테스트를 남겼다

접근 통제 테스트는 "권한 없는 계정이면 403" 만 쓰기 쉬운데, 이번에 샌 곳은 "권한 있는 계정이 다른 범위의 id 를 넘기는" 경우였다. 그래서 테넌트 A 계정으로 테넌트 B 리소스 id 를 호출해 404 를 기대하는 테스트를 상세·수정·삭제에 하나씩 넣었다. 이후로는 새 도메인의 조회 헬퍼를 만들 때 같은 저장소에서 가장 오래된 동종 도메인과 나란히 놓고 비교한다.

## 정리

권한 게이트는 요청한 주체를 검증하고, 소유권 검증은 요청 대상 객체를 검증한다. 파라미터가 둘인데 한쪽만 보고 있으면 둘 사이의 관계는 아무도 보지 않는다.
