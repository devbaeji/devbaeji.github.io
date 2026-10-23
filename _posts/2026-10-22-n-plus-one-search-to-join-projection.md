---
title: "[TIL] 메모리 필터 N+1 검색을 JOIN 단일 쿼리와 조회 전용 projection으로 바꾸기"
date: 2026-10-22 09:00:00 +0900
categories: [TIL]
tags: [backend, jpa, hibernate, querydsl, n-plus-one, projection, performance]
---

> 이번 작업에서 마주친 기술 개념을, 나중에 면접/현업에서 "~와 ~의 차이는 이렇고, 경험상 ~했다"고 바로 꺼낼 수 있게 정리한다.

B2B SaaS의 관리자 화면에는 "기존 회원을 조직 구성원으로 추가"하는 모달이 있고, 그 안에서 작업자 회원을 이름·이메일로 검색한다. 이 검색 API 하나를 N+1 구조에서 쿼리 2건 고정 구조로 바꾼 작업을 정리한다.

> 예제 코드는 실제 코드를 단순화하고 도메인 이름을 바꾼 것이다.

## N+1은 어떻게 찾고, 왜 "검색 결과 수"가 아니라 "전체 데이터 수"에 비례했나

발견은 메트릭에서 시작했다. Prometheus의 `http_server_requests_seconds`를 Grafana에서 URI별로 보면, 작업자 검색 엔드포인트의 평균 응답이 1초에 가까웠다. 호출 수는 적지만 단순 검색치고 느린 것이 이상 신호였다.

이전 구현의 흐름은 다음과 같았다.

```kotlin
val members = memberRepository.findAllNotWithdrawnByType(MemberType.WORKER) // 1
members.mapNotNull { member ->
  workerProfileRepository.findByMemberId(member.id)?.let { profile ->      // N
    if (member.email.contains(query, ignoreCase = true) ||
        profile.name.contains(query, ignoreCase = true)) member to profile else null
  }
}
```

검색어와 무관하게 탈퇴하지 않은 작업자 **전원**을 읽고(1), 작업자마다 프로필을 따로 조회한 뒤(N), 서버 메모리에서 `contains`로 걸러냈다. 그래서 쿼리 수는 결과가 3명이든 0명이든 "전체 작업자 수"에 비례한다. 통합 테스트에서 작업자 2명일 때 47건, 30명일 때 137건이 나갔다. 28명 늘었을 때 90건이 늘었으니 1명당 약 3건씩 증가하는 구조다. 1건은 `findByMemberId`이고, 나머지는 다음 절의 역방향 `@OneToOne` 때문이다.

> **N+1 vs 메모리 필터**
>
> N+1은 "건당 추가 쿼리"이고, 메모리 필터는 "필요 없는 행까지 읽기"다. 둘이 겹치면 비용이 결과 수가 아니라 테이블 크기에 묶인다.
{: .prompt-info }

> **From experience**
>
> 관리자 모달의 검색이 평균 약 1초로 메트릭에 걸렸다. 코드를 보니 작업자 전원 조회 후 건별 프로필 조회, 서버 측 문자열 비교였다. 테스트에서 2명 47건, 30명 137건으로 "1명당 약 3건"이라는 기울기를 먼저 확인하고 나서 수정에 들어갔다.
{: .prompt-tip }

## 역방향 @OneToOne은 왜 LAZY를 선언해도 지연 로딩되지 않나

회원 엔티티에는 프로필 연관이 여러 개 있다. 그중 두 개는 `@OneToOne(mappedBy = "member", fetch = FetchType.LAZY)`, 즉 FK가 **반대편 테이블**에 있는 역방향 관계다.

Hibernate가 LAZY 연관을 프록시로 채우려면 "연관 대상이 있는지 없는지"를 먼저 알아야 한다. `@ManyToOne`이나 FK를 직접 가진 쪽의 `@OneToOne`은 내 행의 FK 칼럼이 null인지만 보면 되므로 프록시를 바로 만들 수 있다. 반면 역방향은 내 행에 FK가 없어서, null로 둘지 프록시를 둘지 판단하려면 결국 상대 테이블을 SELECT해야 한다. 그래서 `LAZY` 선언이 사실상 무시되고 회원 한 건을 로드할 때마다 프로필 테이블 두 곳에 SELECT가 나간다. 배치 페치(`default_batch_fetch_size`)도 이 경로에는 적용되지 않았다.

근본 해법은 바이트코드 강화(`enableLazyInitialization`)로 필드 단위 지연 로딩을 켜는 것이다. 다만 이는 모든 엔티티의 로딩 동작을 바꾸는 빌드 설정이라 이번 변경 범위에 넣지 않았다. 대신 "목록·집계 경로에서는 회원 엔티티를 로드하지 말고 projection으로 조회한다"는 팀 규칙을 따랐다.

> **역방향 @OneToOne의 LAZY**
>
> FK를 가진 쪽은 FK null 여부로 프록시를 만들 수 있지만, mappedBy 쪽은 존재 여부를 알려고 조회해야 하므로 LAZY가 동작하지 않는다. 해법은 바이트코드 강화, 관계 방향 재설계, 또는 엔티티를 아예 로드하지 않는 projection이다.
{: .prompt-info }

> **From experience**
>
> 1명당 3건 중 2건이 이 역방향 프로필 조회였다. 바이트코드 강화는 효과는 확실하지만 전 엔티티의 로딩 동작이 바뀌어 회귀 범위를 가늠하기 어려웠다. 그래서 "이 조회 경로에서는 회원 엔티티를 만들지 않는다"는 국소적 해법을 택했다.
{: .prompt-tip }

## 엔티티를 select할 것인가, 조회 전용 read model을 select할 것인가

수정 방향을 정할 때 가장 오래 고민한 지점이다. "객체지향적으로" 쓰면 JOIN 쿼리로 회원·프로필 엔티티를 함께 가져와 기존 `MemberResponse.from(member, profile)`을 그대로 재사용하는 쪽이 깔끔해 보인다. 하지만 회원 엔티티를 영속성 컨텍스트에 올리는 순간 위의 역방향 프로필 SELECT가 회원마다 다시 나간다. fetch join으로 작업자 프로필은 한 번에 가져와도, 역방향 두 개가 N+1을 재발시킨다.

그래서 엔티티 대신 응답에 필요한 칼럼만 담는 `MemberSearchRow`라는 조회 전용 data class를 만들었다. 엔티티가 아니므로 연관도, 프록시도, 더티 체킹도 없다. 응답 형태는 그대로 유지했고 프론트 변경은 없다.

판단 기준은 "객체지향은 쓰기와 도메인 규칙에, 조회는 납작한 read model로"다. 상태를 바꾸고 불변식을 지켜야 하는 경로에서는 엔티티가 가치를 낸다. 화면에 뿌릴 목록은 행(row)의 집합일 뿐이라, 엔티티 그래프를 경유할 이유가 없고 오히려 위 같은 숨은 쿼리의 통로가 된다. CQRS를 아키텍처 수준까지 도입하지 않아도 쿼리 메서드 단위에서 같은 분리를 적용할 수 있다.

> **엔티티 조회 vs DTO projection**
>
> 엔티티 조회는 변경 추적과 연관 탐색이 필요할 때, projection은 읽기만 하는 목록·검색일 때 고른다. projection은 연관 매핑의 로딩 함정을 원천 차단한다.
{: .prompt-info }

> **From experience**
>
> `from(member, profile)` 재사용이 매력적이었지만, 그 경로는 회원 엔티티 로드 = 역방향 프로필 2건이라는 비용을 다시 끌고 온다. 검색 모달은 읽기 전용이므로 칼럼 projection으로 받고, 소속 조직만 별도 IN 쿼리로 일괄 조회해 쿼리 2건으로 고정했다.
{: .prompt-tip }

## 빨라진 이유는 QueryDSL인가, 쿼리 모양인가

QueryDSL로 바꿔서 빨라진 것이 아니다. 효과를 낸 것은 쿼리의 모양 세 가지다.

| 요소 | 이전 | 이후 |
|---|---|---|
| 조인 | 회원마다 프로필 별도 조회 | `member` JOIN `workerProfile` 한 번 |
| 필터 위치 | 서버 메모리 `contains` | DB `containsIgnoreCase` (이름 OR 이메일) |
| 읽는 범위 | 회원 엔티티 전체 + 연관 | 응답에 필요한 칼럼만 |

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

같은 모양은 JPQL `@Query`의 `select new ...` 생성자 표현식으로도 만들 수 있다. QueryDSL을 고른 이유는 저장소의 커스텀 리포지토리가 이미 QueryDSL 관례로 작성돼 있고, Q타입 덕에 필드 참조가 컴파일 타임에 검증되기 때문이다. 부수 효과로 정렬이 ID 오름차순으로 고정됐다. 이전에는 전체 조회 순서에 의존했다.

> **Q.** 면접에서 "QueryDSL로 바꿔서 성능이 좋아졌다"고 말해도 되나?
>
> 정확한 설명이 아니다.
>
> 성능은 SQL이 결정한다. 라운드트립 수(N+1 → 고정), 필터를 어디서 하는지(애플리케이션 → DB), 전송량(엔티티 전체 → 필요한 칼럼)이 바뀐 것이 원인이고, 같은 SQL을 JPQL·네이티브 쿼리로도 만들 수 있다. 단, `containsIgnoreCase`는 앞쪽 와일드카드 LIKE라 인덱스를 타지 않는다. 그래도 수백 행 규모에서 DB 한 번의 스캔은 수백 번의 라운드트립보다 훨씬 싸다.
>
> *도구 선택의 근거는 성능이 아니라 유지보수(관례·타입 안전성)라고 분리해 말할 수 있어야 한다.*
{: .prompt-info }

> **From experience**
>
> 변경 설명을 "QueryDSL로 바꿨다"가 아니라 "JOIN 한 번, 검색어 필터는 DB에서, 필요한 칼럼만"으로 정리했다. 도구 이름으로 요약하면 다음 사람이 JPQL 기반 코드에서 같은 문제를 만났을 때 해법을 떠올리지 못한다. QueryDSL은 기존 커스텀 리포지토리 관례와 컴파일 타임 필드 참조 때문에 골랐을 뿐이다.
{: .prompt-tip }

## Projections.constructor와 @QueryProjection은 어떻게 다른가

`Projections.constructor`는 select 절의 표현식 순서·개수와 같은 생성자를 리플렉션으로 찾아 **위치 기반**으로 값을 넣는다. 칼럼 순서를 바꾸거나 타입이 어긋나도 컴파일은 통과하고, 실행 시점에야 생성자를 못 찾거나 엉뚱한 필드에 값이 들어간다. `@QueryProjection`은 DTO 생성자에 붙이면 Q-DTO가 생성돼 생성자 호출이 컴파일 타임에 검증되지만, DTO가 QueryDSL에 의존하게 된다.

응답 DTO를 직접 projection 대상으로 쓰지 않고 `MemberSearchRow`를 따로 둔 이유도 같은 맥락이다. 응답 DTO는 기본값 인자가 붙은 Kotlin 생성자라, 칼럼 수와 인자 수가 정확히 같은 생성자를 요구하는 `Projections.constructor`와 맞지 않았다. 매핑 코드는 `MemberResponse.from(row, organizations)` 오버로드로 기존 `from(member, profile)` 옆에 두어, 응답 필드가 바뀔 때 두 경로를 함께 고치도록 했다.

> **Projections.constructor vs @QueryProjection**
>
> constructor는 DTO를 순수하게 두는 대신 위치 바인딩 오류가 런타임에 드러나고, @QueryProjection은 컴파일 타임 안전성을 얻는 대신 DTO가 QueryDSL에 묶인다.
{: .prompt-info }

> **From experience**
>
> 리뷰에서 "위치 바인딩이라 런타임에 깨진다"는 지적을 받았다. 실제 쿼리를 타는 통합 테스트가 모든 응답 필드를 단언하도록 해서 방어했고, `@QueryProjection` 전환은 후속 검토로 남겼다. 같은 리뷰의 "응답 매핑 중복" 지적은 DTO `from` 오버로드로 바로 반영했다.
{: .prompt-tip }

## 성능 수정은 "빨라졌다"가 아니라 "쿼리 수가 고정됐다"로 검증한다

응답 시간은 데이터량·환경에 따라 흔들리므로 회귀 테스트의 기준으로 약하다. 대신 Hibernate `Statistics`를 켜고 `prepareStatementCount`를 비교했다. 작업자 2명과 30명으로 각각 검색했을 때 쿼리 수가 같고 2건 이하인지를 단언한다. 이 테스트는 "데이터가 늘어도 쿼리 수가 늘지 않는다"는 성질 자체를 고정하므로, 누군가 나중에 회원 엔티티를 다시 로드하도록 바꾸면 바로 깨진다.

```kotlin
val small = statementsFor(2)
val large = statementsFor(30)
assertThat(large).isEqualTo(small)
assertThat(small).isLessThanOrEqualTo(2)
```

공용 DB 위에서 도는 통합 테스트라 다른 테스트가 만든 데이터가 섞일 수 있다. 그래서 테스트마다 `System.nanoTime()` 기반 고유 토큰을 이름에 넣고, 그 토큰으로 검색해 단언 범위를 좁혔다. 같은 클래스에서 대소문자 무시 검색, 탈퇴 회원·프로필 없는 회원·다른 유형 회원 제외도 함께 검증했다.

> **응답 시간 단언 vs 쿼리 수 단언**
>
> 응답 시간은 환경 의존적이라 플래키하고, 쿼리 수는 데이터 규모에 대한 복잡도를 결정적으로 고정한다. N+1 회귀 방지에는 "N을 바꿔도 쿼리 수가 같다"를 단언한다.
{: .prompt-info }

> **From experience**
>
> 수정 전 같은 테스트 골격으로 2명 47건, 30명 137건을 확인했고, 수정 후 둘 다 2건이 됐다. 운영 응답 시간에서 데이터 규모를 역산하면 검색 1회당 약 1,000건이던 쿼리가 2건으로 줄고, 응답은 약 1초에서 수십 ms로 줄 것으로 예상했다. 배포 후 같은 메트릭으로 확인하기로 했다.
{: .prompt-tip }

## 리뷰 지적 중 무엇을 반영하고 무엇을 남기나

리뷰에서 받은 지적 중 두 가지는 반영하지 않았다. 판단 기준은 "이번 변경의 목적(동작 보존 + 쿼리 수 고정)을 넘어서는가"였다.

- **목록 검색 조건과 합치자**: 작업자 목록 화면의 검색 조건은 소속 조직 이름으로도 찾는다. 합치면 이 모달의 검색 동작이 바뀐다. 겹치는 부분은 "작업자 유형·탈퇴 제외" 두 줄뿐이라 중복을 감수했다.
- **결과 상한(limit)이 없다**: 이전에도 상한이 없었고, 이번 변경으로 "전원 조회"가 "검색어 일치분 조회"로 이미 줄었다. 몇 건까지 보여줄지는 화면 동작을 바꾸는 제품 결정이라 성능 수정과 분리했다.

> **DRY vs 동작 보존**
>
> 겉모양이 비슷한 조건이라도 의미(검색 대상 필드)가 다르면 합치는 순간 한쪽의 동작이 바뀐다. 리팩터링 PR에서는 중복 제거보다 동작 불변이 우선이다.
{: .prompt-info }

> **From experience**
>
> 성능 PR에 limit 추가까지 섞으면 "결과가 잘린다"는 사용자 체감 변화가 같이 배포된다. 반영하지 않은 지적은 사유와 함께 PR 본문에 남겨, 리뷰어가 무시한 것이 아니라 판단했다는 것을 알 수 있게 했다.
{: .prompt-tip }

## 마무리 — 이번 작업의 한 줄

조회 경로에서는 엔티티 그래프를 믿지 말고 SQL의 모양을 직접 설계한다 (역방향 `@OneToOne` 하나가 검색 1회를 쿼리 약 1,000건으로 만들 수 있다).
