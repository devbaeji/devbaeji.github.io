---
title: "[TIL] 계산 프로퍼티 뒤에 숨은 N+1과 batch fetch의 한계"
date: 2026-09-10 12:00:00 +0900
categories: [TIL]
tags: [backend, jpa, hibernate, n-plus-one, kotlin, performance]
---

목록 API 의 조회 경로를 보다가 찾은 건 "N+1 이 방치돼 있다"가 아니었다. 작성자는 N+1 을 알고 있었고, 눈에 보이는 쪽은 이미 막아 두었다. 연계 건수와 첨부 유무는 페이지 전체 ID 를 모아 한 번에 조회하고 있었다([집계값을 저장할 것인가 셀 것인가]({% post_url 2026-09-10-denormalized-counter-when-not-to-store %})에서 다룬 결정의 결과다).

```kotlin
val page = reportRepository.findByFilters(tenantIds, dateFrom, dateTo, keyword, pageable)
// 연계 건수·첨부 유무는 행마다 조회하면 N+1 이 된다. 페이지 전체를 한 번에 묶어 온다.
val ids = page.content.map { it.id }
val linkedCounts = countLinkedRequests(ids)
val withAttachment = entityIdsWithAttachment(ids)
```

그런데 같은 파일의 매핑 함수는 이랬다.

```kotlin
private fun Report.toListItem(linkedCount: Long, hasAttachment: Boolean) =
  ReportListItemResponse(
    tenantId = tenant.id,
    tenantName = tenant.name,       // LAZY @ManyToOne
    reporterName = reporter.name,   // LAZY @ManyToOne + 계산 프로퍼티
    reporterType = reporter.accountType,
    ...
  )
```

`repository.find...` 가 적힌 조회는 리뷰에서 보이니 막혔고, `tenant.name`·`reporter.name` 처럼 필드 접근 한 줄로 보이는 조회는 그대로 남아 있었다.

## 조인이 있다고 연관이 채워지지는 않는다

조회 리포지토리의 JPQL FROM 절은 이랬다.

```
FROM Report r
LEFT JOIN r.reporter reporter
LEFT JOIN reporter.userProfile reporterUserProfile
LEFT JOIN reporter.workerProfile reporterWorkerProfile
LEFT JOIN reporter.adminProfile reporterAdminProfile
```

나도 처음엔 이 LEFT JOIN 들을 보고 연관은 이미 채워졌겠지 하고 넘어갔다. 그런데 SQL 로그를 보니 응답 매핑 시점에 프록시 초기화 쿼리가 줄줄이 나가고 있었다. 이 조인들은 WHERE 절에서 세 프로필의 이름을 LIKE 검색하려는 것이었다. `SELECT r` 은 `Report` 만 올리고 `r.reporter` 는 프록시로 남는다. 연관까지 초기화하려면 `JOIN FETCH` 여야 한다. `tenant` 는 아예 조인도 없이 WHERE 의 `r.tenant.removedAt IS NULL` 경로 탐색만 있어서, SQL 조인은 생기지만 엔티티는 로드되지 않는다. 그 뒤로는 조인 절보다 SELECT 절이 무엇을 반환하는지를 먼저 본다.

## batch fetch 는 줄일 뿐이고, 안 통하는 매핑이 있다

이 프로젝트는 배치 페치를 전역으로 켜 두었다.

```yaml
hibernate:
  # 지연 로딩 프록시/컬렉션을 IN 절로 묶어 N+1 완화 (N → ceil(N/100)).
  # Hibernate 기본값은 -1(배치 페치 비활성) 이므로 명시적으로 켠다.
  default_batch_fetch_size: ${JPA_BATCH_FETCH_SIZE:100}
```

쌓인 프록시를 `WHERE id IN (...)` 으로 묶으니, 20건 페이지면 `tenant` 초기화 1회, `reporter` 초기화 1회다. 쿼리가 사라지는 게 아니라 차수가 바뀐다.

문제는 `reporter.name` 이 컬럼이 아니라 계산 프로퍼티라는 점이었다.

```kotlin
val name: String
  get() = when (accountType) {
    AccountType.USER -> userProfile?.name ?: email
    AccountType.ADMIN -> adminProfile?.name ?: email
    AccountType.WORKER -> workerProfile?.name ?: email
  }
```

호출부에서는 필드 읽기와 똑같이 생겼지만, 실행하면 계정 유형에 따라 또 다른 지연 연관을 건드린다. Java 였다면 `getName()` 이라도 보였을 텐데, Kotlin 프로퍼티 문법이 쿼리를 감춘다.

게다가 세 프로필 중 둘은 FK 가 반대편에 있는 역방향 `@OneToOne(mappedBy = ...)` 다. 값이 null 인지 알려면 상대 테이블을 봐야 하니 `LAZY` 를 선언해도 프록시를 만들 수 없다. 계정이 로드될 때마다 두 프로필 테이블에 SELECT 가 바로 나가고, 배치 페치도 적용되지 않는다. 계산해 보면 20건 목록의 쿼리는 대략 4개(목록, count, `tenant` 배치, `reporter` 배치) + 서로 다른 보고자 수 × 2 다. 보고자가 12명이면 24개가 더 붙는다. 엔티티에도 이미 "목록/집계 경로에서는 계정 엔티티를 로드하지 말고 필요한 컬럼만 projection으로 조회한다"는 주석이 남아 있었다.

## 경로마다 다른 도구를 썼다

"그럼 전부 `JOIN FETCH` 로" 하기 전에 페이징을 따져야 했다. fetch join 과 페이징이 충돌하는 건 컬렉션(to-many)일 때다. 행이 자식 수만큼 늘어나 SQL `LIMIT` 을 못 쓰고 Hibernate 가 전부 읽어 메모리에서 페이징한다(`HHH000104`). `tenant`·`reporter` 는 to-one 이라 행이 늘지 않으니 페이징과 같이 써도 된다. 연계 건수·첨부 유무를 따로 배치 조회한 기존 코드도 이 구분을 따른 셈이다.

| 방법 | 커버 범위 | 한계 |
|---|---|---|
| 전역 `default_batch_fetch_size` | 코드 수정 없이 모든 지연 로딩 | 프록시 불가 매핑(역방향 to-one)엔 무효 |
| `JOIN FETCH` / `@EntityGraph` | to-one 연관 완전 제거 | 컬렉션은 페이징과 충돌 |
| ID 묶음 배치 조회 | 집계·존재 여부(to-many) | 호출부가 직접 짜야 함 |
| DTO projection | 필요한 컬럼만, 엔티티 자체를 안 올림 | 조회 전용, 재사용성 낮음 |

전역 배치 페치는 안전망으로만 두고, 목록·집계처럼 트래픽이 몰리는 읽기 경로는 따로 다뤘다. 목표는 한 쿼리로 끝내는 게 아니라 쿼리 수를 행 수와 무관한 상수로 고정하는 것이었다. 역방향 `@OneToOne` 이 얽힌 이름 조회는 매핑 자체가 배치를 허용하지 않으니, 계정 엔티티를 올리지 않고 projection 으로 끊었다. 목록은 읽기 전용이고 화면이 쓰는 필드도 정해져 있어서 엔티티를 통째로 올릴 이유가 없었다.

## 정리

N+1 은 반복문 안에 조회 코드가 있는지로만 찾을 게 아니었다. 이 프로퍼티 접근이 정말 필드 읽기인지를 봐야 한다. 배치 페치는 비용을 상수로 눌러 줄 뿐이고, 매핑이 프록시를 허용하지 않으면 조용히 효과가 없어진다.
