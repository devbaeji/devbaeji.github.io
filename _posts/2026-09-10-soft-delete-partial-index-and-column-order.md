---
title: "[TIL] soft delete 테이블의 부분 인덱스와 복합 인덱스 컬럼 순서"
date: 2026-09-10 11:00:00 +0900
categories: [TIL]
tags: [backend, database, postgresql, index, soft-delete, jpa]
---

멀티테넌트 목록 화면의 조회 조건은 세 줄이었다. 테넌트 여러 개, 등록일 범위, 삭제되지 않은 것. 인덱스를 만들면서 삭제 조건을 인덱스에 넣을지, 두 컬럼 중 무엇을 앞에 둘지를 정해야 했다. 최종 인덱스는 이렇다(테이블·컬럼명은 일반화했다).

```sql
CREATE INDEX IF NOT EXISTS idx_reports_tenant_created
  ON reports (tenant_id, created_at)
  WHERE deleted_at IS NULL;
```

## 먼저 조회 경로를 전부 적었다

이 테이블은 물리 삭제를 하지 않는다([관측 시각과 소급 불가능성]({% post_url 2026-09-10-schema-change-timing-and-unrecoverable-history %})). 그래서 목록, 카운트 집계, 상세 조회 모두 `deleted_at IS NULL` 을 단다.

인덱스를 정하기 전에 이 테이블을 읽는 경로를 적어 봤다. 목록 페이징, 통계 화면의 테넌트별 건수 집계, 모바일 쪽 전량 조회. 셋 다 `tenant_id IN` + `created_at` 범위 + `deleted_at IS NULL` 로 조건 모양이 같았다. 세 경로가 한 인덱스로 모인다는 걸 확인하고 나서 정의를 확정했다.

## 삭제 조건은 인덱스 술어로

조건이 쿼리마다 바뀌지 않으니 살아 있는 행에만 인덱스를 거는 부분 인덱스로 했다. 인덱스가 작아지는 것도 있지만, 일반 인덱스였다면 훑어 온 엔트리 중 상당수를 `deleted_at` 확인 후 버려야 한다. 삭제분이 쌓인 테넌트일수록 그 비율이 올라간다.

부분 인덱스는 쿼리의 `WHERE` 가 인덱스 술어를 함의한다고 플래너가 쿼리 텍스트만 보고 증명할 수 있을 때만 쓰인다. `WHERE deleted_at IS NULL` 은 통과하지만 `WHERE (:includeDeleted = true OR deleted_at IS NULL)` 은 실행 시점 값이 `false` 여도 못 탄다. 조건이 술어보다 좁은 건(`deleted_at IS NULL AND status = 'OPEN'`) 괜찮고, 넓으면(삭제 포함) 안 된다. 이번에는 모든 조회 경로가 `deleted_at IS NULL` 을 리터럴로 쓰고 있어서 성립했다. "삭제 포함 조회" 옵션이 하나라도 있었다면 그 경로에는 다른 인덱스가 필요했을 것이다.

같은 테이블에 나중에 붙인 두 번째 부분 인덱스도 같은 방식이다. 참조 컬럼을 nullable 로 추가했더니 기존 행이 전부 `NULL` 이라, `WHERE ref_id IS NOT NULL` 로 실제 연결된 소수만 담았다.

`tenant_id` 단일 인덱스는 따로 남겨 뒀다. 참조 무결성 검사나 삭제분까지 보는 점검성 조회처럼 `deleted_at IS NULL` 을 걸지 않는 접근은 부분 인덱스를 쓸 수 없기 때문이다.

## 컬럼 순서는 등치가 앞, 범위가 뒤

`(tenant_id, created_at)` 은 테넌트로 먼저 묶고 그 안에서 등록일순으로 늘어선 구조다. `tenant_id IN (...)` + `created_at` 범위 조건이면 테넌트별로 연속된 구간 하나씩만 읽으면 되고, 이미 `created_at` 순이라 `ORDER BY created_at DESC` 정렬도 필요 없어 페이징에서 앞쪽 N건만 읽고 멈출 수 있다. `IN` 은 등치의 나열로 취급된다.

`(created_at, tenant_id)` 로 뒤집으면 선두가 범위 조건이라 기간 전체를 훑고, `tenant_id` 는 걸러내는 필터로만 쓰인다. 기간이 넓을수록 손해다.

## 선택적 기간 필터가 인덱스를 막았다

기간 필터가 선택 값이면 흔히 이렇게 한 문장으로 쓴다.

```sql
WHERE deleted_at IS NULL
  AND tenant_id IN (:tenantIds)
  AND (CAST(:dateFrom AS timestamp) IS NULL OR created_at >= :dateFrom)
  AND (CAST(:dateTo   AS timestamp) IS NULL OR created_at <= :dateTo)
```

`created_at` 조건이 파라미터와의 `OR` 에 갇혀 있어서, 기간을 지정해도 `tenant_id` 까지만 인덱스로 찾고 나머지는 필터가 된다. 그래서 값이 있을 때만 절을 붙이는 방식을 썼다.

```kotlin
val sb = StringBuilder("WHERE deletedAt IS NULL")
if (!tenantIds.isNullOrEmpty()) sb.append(" AND tenant.id IN :tenantIds")
if (dateFrom != null) sb.append(" AND createdAt >= :dateFrom")
if (dateTo != null) sb.append(" AND createdAt <= :dateTo")
```

파라미터 조합마다 쿼리 텍스트가 달라져 실행계획 캐시 효율이 떨어지고 조립 코드도 늘어난다. 그래서 응답 시간이 사용자에게 바로 보이는 페이징 목록만 조립형으로 두고, 집계 쿼리는 `OR` 형태로 뒀다.

조립형 조건에서는 하나를 계약으로 못 박았다. 테넌트 목록이 `null` 이면 "필터 없음(전체)", 빈 리스트면 "조회 범위 없음(빈 결과)"이다. 빈 리스트를 그대로 넘기면 위 코드에서 절이 안 붙어서, 권한 범위가 0인 사용자에게 전체 조회가 나간다. 그래서 빈 리스트는 쿼리를 만들기 전에 막았다.

인덱스 세 줄을 정하는 일은 결국 조회 경로를 전부 적어 보는 일이었다. 경로가 같은 조건 모양으로 모인다는 걸 확인하고 나서야 부분 인덱스와 컬럼 순서가 함께 정해졌다.
