---
title: "[TIL] 메모리 필터 N+1 검색을 JOIN 단일 쿼리와 조회 전용 projection으로 바꾸기"
date: 2026-10-22 09:00:00 +0900
categories: [TIL]
tags: [backend, jpa, hibernate, querydsl, n-plus-one, projection, performance]
---

B2B SaaS 의 관리자 화면에는 "기존 회원을 조직 구성원으로 추가"하는 모달이 있고, 그 안에서 작업자 회원을 이름·이메일로 검색한다. 이 검색 API 를 N+1 구조에서 쿼리 2건 고정 구조로 바꿨다.

> 예제 코드는 실제 코드를 단순화하고 도메인 이름을 바꾼 것이다.

## 단순 검색이 1초 가까이 걸렸다

시작은 메트릭이었다. Prometheus 의 `http_server_requests_seconds` 를 Grafana 에서 URI 별로 보니, 작업자 검색 엔드포인트의 평균 응답이 1초에 가까웠다. 호출 수는 적어도 단순 검색치고는 느렸다.

이전 구현은 이랬다.

```kotlin
val members = memberRepository.findAllNotWithdrawnByType(MemberType.WORKER) // 1
members.mapNotNull { member ->
  workerProfileRepository.findByMemberId(member.id)?.let { profile ->      // N
    if (member.email.contains(query, ignoreCase = true) ||
        profile.name.contains(query, ignoreCase = true)) member to profile else null
  }
}
```

검색어와 상관없이 탈퇴하지 않은 작업자 전원을 읽고, 작업자마다 프로필을 따로 조회한 뒤, 서버 메모리에서 `contains` 로 걸렀다. 그래서 쿼리 수가 결과 수가 아니라 전체 작업자 수에 비례했다. 수정에 들어가기 전에 통합 테스트로 재 보니 작업자 2명일 때 47건, 30명일 때 137건이었다. 28명 늘 때 90건이 늘었으니 1명당 약 3건이다. 1건은 `findByMemberId` 이고 나머지 2건은 역방향 `@OneToOne` 때문이었다.

## 역방향 @OneToOne 은 LAZY 가 먹지 않았다

회원 엔티티의 프로필 연관 중 두 개가 `@OneToOne(mappedBy = "member", fetch = FetchType.LAZY)`, 즉 FK 가 반대편 테이블에 있는 관계였다. FK 를 가진 쪽은 FK 칼럼이 null 인지만 보면 프록시를 만들 수 있지만, 역방향은 연관 대상이 있는지 알려면 상대 테이블을 SELECT 해야 한다. 그래서 `LAZY` 가 사실상 무시되고, 회원 한 건을 로드할 때마다 프로필 테이블 두 곳에 SELECT 가 나갔다. 배치 페치(`default_batch_fetch_size`)도 이 경로에는 적용되지 않았다.

근본 해법은 바이트코드 강화(`enableLazyInitialization`)로 필드 단위 지연 로딩을 켜는 것이다. 효과는 확실하지만 모든 엔티티의 로딩 동작이 바뀌어 회귀 범위를 가늠하기 어려웠다. 그래서 "목록·집계 경로에서는 회원 엔티티를 로드하지 말고 projection 으로 조회한다"는 팀 규칙을 따라, 이 조회 경로에서만 회원 엔티티를 만들지 않기로 했다.

## 엔티티 대신 조회 전용 row 를 받았다

가장 오래 고민한 부분이다. JOIN 으로 회원·프로필 엔티티를 함께 가져와 기존 `MemberResponse.from(member, profile)` 을 재사용하면 깔끔해 보였다. 하지만 회원 엔티티가 영속성 컨텍스트에 올라가는 순간 역방향 프로필 SELECT 가 회원마다 다시 나간다. 작업자 프로필을 fetch join 으로 가져와도 나머지 역방향 두 개가 N+1 을 되살린다.

그래서 응답에 필요한 칼럼만 담는 `MemberSearchRow` 라는 조회 전용 data class 를 만들었다. 엔티티가 아니니 연관도 프록시도 더티 체킹도 없다. 소속 조직은 별도 IN 쿼리 한 번으로 일괄 조회해서 전체를 쿼리 2건으로 고정했다. 응답 형태는 그대로라 프론트 변경은 없었다. 상태를 바꾸고 불변식을 지키는 경로에서는 엔티티가 가치를 내지만, 화면에 뿌릴 목록은 행의 집합일 뿐이라 엔티티 그래프를 거칠 이유가 없다고 판단했다.

```kotlin
queryFactory
  .select(Projections.constructor(MemberSearchRow::class.java, member.id, member.email, workerProfile.name, /* ... */))
  .from(member)
  .join(member.workerProfile, workerProfile)
  .where(
    member.type.eq(MemberType.WORKER),
    member.status.ne(MemberStatus.WITHDRAWN),
    workerProfile.name.containsIgnoreCase(keyword).or(member.email.containsIgnoreCase(keyword)),
  ).orderBy(member.id.asc())
  .fetch()
```

## 빨라진 건 QueryDSL 때문이 아니다

변경 설명도 "QueryDSL 로 바꿨다"가 아니라 쿼리 모양으로 정리했다.

| 요소 | 이전 | 이후 |
|---|---|---|
| 조인 | 회원마다 프로필 별도 조회 | `member` JOIN `workerProfile` 한 번 |
| 필터 위치 | 서버 메모리 `contains` | DB `containsIgnoreCase` (이름 OR 이메일) |
| 읽는 범위 | 회원 엔티티 전체 + 연관 | 응답에 필요한 칼럼만 |

같은 SQL 은 JPQL `@Query` 의 `select new ...` 로도 만들 수 있다. 도구 이름으로 요약하면 다음 사람이 JPQL 코드에서 같은 문제를 만났을 때 해법을 떠올리지 못한다. QueryDSL 은 저장소의 커스텀 리포지토리가 이미 그 관례였고 Q타입으로 필드 참조가 컴파일 타임에 검증돼서 골랐을 뿐이다. `containsIgnoreCase` 는 앞쪽 와일드카드 LIKE 라 인덱스를 타지 않지만, 수백 행 규모에서는 DB 스캔 한 번이 수백 번의 라운드트립보다 훨씬 싸다. 부수 효과로 정렬이 ID 오름차순으로 고정됐다. 이전에는 전체 조회 순서에 의존했다.

`Projections.constructor` 는 select 절 순서대로 생성자에 위치 기반으로 값을 넣어서, 칼럼 순서나 타입이 어긋나도 컴파일은 통과하고 런타임에야 깨진다. 리뷰에서도 이 점을 지적받았다. 실제 쿼리를 타는 통합 테스트가 모든 응답 필드를 단언하게 해서 막고, `@QueryProjection` 전환(컴파일 타임 검증 대신 DTO 가 QueryDSL 에 묶인다)은 후속 검토로 남겼다. 응답 DTO 를 projection 대상으로 바로 쓰지 않은 건 기본값 인자가 붙은 Kotlin 생성자라 `Projections.constructor` 와 맞지 않았기 때문이다. 같은 리뷰의 "응답 매핑 중복" 지적은 `MemberResponse.from(row, organizations)` 오버로드를 기존 `from(member, profile)` 옆에 두는 것으로 바로 반영했다. 응답 필드가 바뀌면 두 경로를 함께 고치게 하려는 것이다.

## 응답 시간이 아니라 쿼리 수로 검증했다

응답 시간은 데이터량과 환경에 따라 흔들려서 회귀 테스트 기준으로 약하다. Hibernate `Statistics` 를 켜고 `prepareStatementCount` 를 비교했다. 작업자 2명과 30명으로 검색했을 때 쿼리 수가 같고 2건 이하인지를 단언한다. 나중에 누가 회원 엔티티를 다시 로드하게 바꾸면 바로 깨진다.

```kotlin
val small = statementsFor(2)
val large = statementsFor(30)
assertThat(large).isEqualTo(small)
assertThat(small).isLessThanOrEqualTo(2)
```

공용 DB 위에서 도는 통합 테스트라 다른 테스트의 데이터가 섞일 수 있어서, 테스트마다 `System.nanoTime()` 기반 고유 토큰을 이름에 넣고 그 토큰으로 검색해 범위를 좁혔다. 대소문자 무시 검색, 탈퇴 회원·프로필 없는 회원·다른 유형 회원 제외도 같은 클래스에서 검증했다.

수정 전 같은 골격에서 47건, 137건이던 쿼리가 수정 후 둘 다 2건이 됐다. 운영 응답 시간에서 데이터 규모를 역산하면 검색 1회당 약 1,000건이던 쿼리가 2건으로 줄고 응답은 약 1초에서 수십 ms 로 줄 것으로 예상한다. 배포 후 같은 메트릭으로 확인하기로 했다.

## 반영하지 않은 리뷰 지적

기준은 이번 변경의 목적(동작 보존 + 쿼리 수 고정)을 넘어서는가였다.

- **목록 검색 조건과 합치자**: 작업자 목록 화면은 소속 조직 이름으로도 찾는다. 합치면 이 모달의 검색 동작이 바뀐다. 겹치는 건 "작업자 유형·탈퇴 제외" 두 줄뿐이라 중복을 감수했다.
- **결과 상한(limit)이 없다**: 이전에도 없었고, 이번 변경으로 이미 "전원 조회"가 "검색어 일치분 조회"로 줄었다. 몇 건까지 보여줄지는 제품 결정이고, 성능 PR 에 섞으면 "결과가 잘린다"는 체감 변화가 같이 배포된다.

반영하지 않은 지적은 사유와 함께 PR 본문에 남겼다.

## 정리

조회 경로에서는 엔티티 그래프를 믿지 않고 SQL 의 모양을 직접 정했다. 역방향 `@OneToOne` 하나가 검색 1회를 쿼리 약 1,000건(운영 규모 추정)으로 만들 수 있다.
