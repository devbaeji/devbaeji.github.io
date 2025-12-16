---
title: "Statement vs PreparedStatement: 차이점과 성능 최적화"
date: 2025-12-11 10:00:00 +0900
categories: [Backend, JDBC]
tags: [jdbc, mysql, statement, preparedstatement, sql-injection, performance]
---

## 들어가며

JDBC에서 SQL을 실행할 때 `Statement`와 `PreparedStatement` 두 가지 방법이 있다. 둘 다 SQL을 실행하지만, **사용 방식, 보안, 성능** 측면에서 큰 차이가 있다.

결론부터 말하면, **실무에서는 거의 항상 PreparedStatement를 사용한다**.

---

## Statement: 단순하지만 위험한 방식

`Statement`는 SQL을 문자열로 직접 작성해서 실행한다.

```java
Statement stmt = conn.createStatement();
String age = "30";
ResultSet rs = stmt.executeQuery("SELECT * FROM users WHERE age > " + age);
```

간단해 보이지만, 여기에 심각한 문제가 숨어 있다.

### SQL Injection 공격에 취약

만약 `age` 값이 사용자 입력이라면?

```java
String age = "30; DROP TABLE users; --";
ResultSet rs = stmt.executeQuery("SELECT * FROM users WHERE age > " + age);
```

실행되는 SQL:
```sql
SELECT * FROM users WHERE age > 30; DROP TABLE users; --
```

**users 테이블이 삭제된다.** 이게 바로 SQL Injection 공격이다.

---

## PreparedStatement: 안전하고 빠른 방식

`PreparedStatement`는 SQL 구조와 데이터를 분리한다.

```java
String sql = "SELECT * FROM users WHERE age > ?";
PreparedStatement pstmt = conn.prepareStatement(sql);
pstmt.setInt(1, 30);  // ?에 값을 바인딩
ResultSet rs = pstmt.executeQuery();
```

### SQL Injection 방지

악의적인 입력이 들어와도 안전하다.

```java
String userInput = "30; DROP TABLE users; --";
pstmt.setString(1, userInput);
```

실행되는 SQL:
```sql
SELECT * FROM users WHERE age > '30; DROP TABLE users; --'
```

**전체 입력값이 하나의 문자열로 처리된다.** SQL 구문으로 해석되지 않는다.

> PreparedStatement는 내부적으로 특수문자를 이스케이프 처리하여 SQL Injection을 원천 차단한다.
{: .prompt-tip }

---

## 성능 차이: Statement Caching

PreparedStatement의 또 다른 장점은 **성능**이다.

### SQL 실행 과정

데이터베이스가 SQL을 실행할 때 거치는 단계:

```
SQL 문자열 → 파싱 → 최적화 → 실행 계획 생성 → 실행
```

- **Statement**: 매번 전체 과정을 반복
- **PreparedStatement**: 파싱/최적화 결과를 캐싱하여 재사용

### 반복 실행 시 차이

1000명의 사용자를 조회한다고 가정하면:

**Statement 방식:**
```java
for (int i = 0; i < 1000; i++) {
    stmt.executeQuery("SELECT * FROM users WHERE id = " + i);
    // 매번: 파싱 → 최적화 → 실행 계획 → 실행
}
```

**PreparedStatement 방식:**
```java
PreparedStatement pstmt = conn.prepareStatement("SELECT * FROM users WHERE id = ?");
for (int i = 0; i < 1000; i++) {
    pstmt.setInt(1, i);
    pstmt.executeQuery();
    // 첫 번째만 파싱, 이후는 캐싱된 실행 계획 재사용
}
```

---

## MySQL JDBC Statement Caching 설정

MySQL JDBC 드라이버에서 Statement Caching을 제대로 활용하려면 설정이 필요하다.

### 기본 동작 이해

MySQL JDBC 드라이버는 기본적으로 **클라이언트 측에서 PreparedStatement를 에뮬레이트**한다. 바인드 파라미터가 클라이언트에서 SQL에 인라인되어 서버로 전송된다.

```
[클라이언트]                    [MySQL 서버]
PreparedStatement 생성
   ↓
파라미터 바인딩
   ↓
SQL 문자열로 변환
   ↓
────────────────────────────────→  SQL 실행
                                      ↓
←────────────────────────────────  결과 반환
```

### Server-side vs Client-side PreparedStatement

**Client-side (기본값):**
- 파라미터가 클라이언트에서 SQL에 인라인됨
- 네트워크 왕복 1회

**Server-side (`useServerPrepStmts=true`):**
- 서버에서 실행 계획을 캐싱
- 네트워크 왕복 2회 (prepare + execute)

> MySQL 8.0에서는 Client-side PreparedStatement가 Server-side보다 성능이 더 좋은 것으로 알려져 있다.
{: .prompt-info }

### 권장 JDBC 설정

```properties
jdbc:mysql://localhost:3306/mydb?
  useServerPrepStmts=false&
  cachePrepStmts=true&
  prepStmtCacheSize=500&
  prepStmtCacheSqlLimit=1024
```

| 설정 | 기본값 | 권장값 | 설명 |
|------|--------|--------|------|
| `cachePrepStmts` | false | **true** | Statement 캐싱 활성화 |
| `prepStmtCacheSize` | 25 | **500** | 캐시할 Statement 개수 |
| `prepStmtCacheSqlLimit` | 256 | **1024** | 캐싱할 SQL 최대 길이 |

> 기본값 25는 대부분의 애플리케이션에서 너무 작다. 애플리케이션의 SQL 종류에 맞게 조정하자.
{: .prompt-warning }

---

## 정리

| 항목 | Statement | PreparedStatement |
|------|-----------|-------------------|
| SQL 작성 | 문자열 연결 | 플레이스홀더 (?) 사용 |
| SQL Injection | **취약** | **안전** |
| 실행 계획 캐싱 | 불가능 | 가능 |
| 반복 실행 성능 | 낮음 | 높음 |
| 실무 사용 | 거의 안 함 | **표준** |

### 핵심 포인트

1. **보안**: PreparedStatement는 SQL Injection을 원천 차단
2. **성능**: 실행 계획 캐싱으로 반복 쿼리 성능 향상
3. **설정**: MySQL에서는 `cachePrepStmts=true`로 캐싱 활성화 필요

실무에서는 특별한 이유가 없다면 **항상 PreparedStatement를 사용**하자.

---

## 참고 자료

- [MySQL JDBC Statement Caching - Vlad Mihalcea](https://vladmihalcea.com/mysql-jdbc-statement-caching/)
