---
title: "Spring Security JWT 인증에서 Principal 타입 불일치 문제 해결하기"
date: 2025-12-17 15:00:00 +0900
categories: [Backend, Spring]
tags: [spring-security, jwt, kotlin, troubleshooting]
---

## 문제 발견

공지사항 기능을 개발하면서 작성자 ID를 어떻게 처리할지 고민하던 중, JWT 인증 구조를 살펴보게 되었습니다.

처음에는 프론트엔드에서 `accountId`를 폼 데이터로 함께 전송하려고 했으나, 보안상 **백엔드에서 JWT 토큰으로부터 자동 추출**하는 것이 더 안전한 방법이라는 결론에 도달했습니다.

```kotlin
// Controller에서 기대하는 방식
@PostMapping
fun createAnnouncement(
    @AuthenticationPrincipal userPrincipal: UserPrincipal,  // JWT에서 추출된 사용자 정보
    @RequestBody request: CreateAnnouncementRequest,
) {
    val userId = userPrincipal.id  // 작성자 ID
    // ...
}
```

그런데 코드를 분석하던 중 **잠재적인 타입 불일치 문제**를 발견했습니다.

---

## 문제 분석

### JWT 인증 필터 구조

`JwtAuthenticationFilter`에서 JWT 토큰을 파싱하고 `SecurityContext`에 인증 정보를 설정하는데, **두 가지 다른 경로**가 존재했습니다.

```kotlin
// JwtAuthenticationFilter.kt (수정 전)

private fun authenticateToken(token: String, request: HttpServletRequest) {
    val email = jwtUtil.extractEmail(token)
    val accountType = jwtUtil.extractAccountType(token)
    val accountId = jwtUtil.extractAccountId(token)

    // 경로 1: JWT에 accountId 클레임이 있는 경우
    if (accountRole != null && accountId != null) {
        val authToken = UsernamePasswordAuthenticationToken(
            accountId,  // ← Long 타입 (숫자)
            null,
            authorities,
        )
        SecurityContextHolder.getContext().authentication = authToken
    }
    // 경로 2: accountId가 없는 경우
    else {
        val userDetails = userDetailsService.loadUserByUsername(email, accountType)
        val authToken = UsernamePasswordAuthenticationToken(
            userDetails,  // ← UserPrincipal 타입 (객체)
            null,
            userDetails.authorities,
        )
        SecurityContextHolder.getContext().authentication = authToken
    }
}
```

### 문제점

| 경로 | Principal 타입 | Controller 기대 타입 | 결과 |
|------|---------------|---------------------|------|
| 경로 1 (accountId 있음) | `Long` | `UserPrincipal` | **타입 불일치** |
| 경로 2 (accountId 없음) | `UserPrincipal` | `UserPrincipal` | 정상 |

JWT 구조에 따라 어떤 경로로 가느냐에 따라 **동작이 달라지는 불안정한 상태**였습니다.

### JWT 토큰 구조 확인

우리 시스템의 JWT 토큰은 `generateAccessTokenForAccount()` 메서드에서 생성됩니다:

```kotlin
// JwtUtil.kt
fun generateAccessTokenForAccount(account: Account): String {
    return Jwts.builder()
        .subject(account.email)
        .claim("type", TokenType.ACCESS.name)
        .claim("accountId", account.id)        // ← accountId 포함!
        .claim("accountRole", account.accountType.name)
        .issuedAt(now)
        .expiration(expiryDate)
        .signWith(secretKey)
        .compact()
}
```

따라서 대부분의 요청이 **경로 1**로 처리되어, `Long` 타입의 principal이 설정됩니다.

하지만 Controller에서는:

```kotlin
@AuthenticationPrincipal userPrincipal: UserPrincipal
```

`UserPrincipal` 타입을 기대하고 있어서, **런타임에 타입 캐스팅 에러**가 발생할 수 있는 상황이었습니다.

---

## 해결 방법

두 경로 모두 **일관되게 `UserPrincipal`을 principal로 설정**하도록 수정했습니다.

```kotlin
// JwtAuthenticationFilter.kt (수정 후)

} else if (accountRole != null && accountId != null) {
    // Account 기반 토큰 (USER 또는 ADMIN)
    if (jwtUtil.validateToken(token)) {
        // UserPrincipal을 로드하여 Controller에서 일관되게 사용할 수 있도록 함
        val userDetails: UserDetails = userDetailsService.loadUserByUsername(email, accountType)

        val authToken = UsernamePasswordAuthenticationToken(
            userDetails,  // ← UserPrincipal을 principal로 사용
            null,
            userDetails.authorities,
        )
        authToken.details = WebAuthenticationDetailsSource().buildDetails(request)
        SecurityContextHolder.getContext().authentication = authToken

        logger.debug("Account 기반 인증 성공: $email (accountId=$accountId)")
    } else {
        throw JwtAuthenticationException("토큰이 유효하지 않습니다")
    }
}
```

### 수정 전후 비교

| 항목 | 수정 전 | 수정 후 |
|------|--------|--------|
| 경로 1 Principal | `Long` (accountId) | `UserPrincipal` |
| 경로 2 Principal | `UserPrincipal` | `UserPrincipal` |
| Controller 호환성 | 불안정 | 안정 |
| DB 조회 | 없음 (경로 1) | 있음 |

---

## 트레이드오프

### 장점
- **일관성**: 모든 Controller에서 `@AuthenticationPrincipal UserPrincipal`로 통일
- **안정성**: 타입 불일치 런타임 에러 방지
- **확장성**: `UserPrincipal`의 다양한 속성 활용 가능 (`id`, `email`, `name`, `accountType` 등)

### 단점
- **DB 조회 추가**: 매 요청마다 `userDetailsService.loadUserByUsername()` 호출
- 다만, 이는 기존 경로 2에서도 수행하던 작업이고, 캐싱을 통해 최적화 가능

---

## 배운 점

1. **JWT 인증 흐름 전체를 파악하자**
   - 토큰 생성 → 파싱 → principal 설정 → Controller 사용까지 일관성 확인

2. **타입 안정성은 런타임 전에 확보하자**
   - `@AuthenticationPrincipal`이 기대하는 타입과 실제 설정되는 타입 일치 확인

3. **보안 관련 데이터는 백엔드에서 처리하자**
   - 프론트엔드에서 `accountId`를 전송하는 것보다 JWT에서 추출하는 것이 안전

---

## 결론

단순히 "작성자 ID를 어떻게 전달할까?"라는 질문에서 시작해서, JWT 인증 구조의 잠재적 문제점을 발견하고 해결할 수 있었습니다.

코드를 작성할 때는 **현재 동작하는지**뿐만 아니라, **모든 경로에서 일관되게 동작하는지**를 확인하는 것이 중요하다는 것을 다시 한번 느꼈습니다.
