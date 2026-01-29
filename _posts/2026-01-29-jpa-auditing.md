---
title: "JPA Auditing이란? createdAt, updatedAt 자동 관리"
date: 2026-01-29 17:10:00 +0900
categories: [Backend, JPA]
tags: [jpa, hibernate, kotlin, auditing, spring-data]
---

## Auditing이란?

엔티티가 **생성/수정될 때 자동으로 시간을 기록**해주는 기능이에요.

문서 작성할 때 자동으로 찍히는 타임스탬프랑 같다고 보면 돼요.

```
┌─────────────────────────────┐
│  📄 문서                     │
│                             │
│  내용: 블라블라...            │
│                             │
│  ─────────────────────────  │
│  작성일: 2024-01-01 10:00   │  ← 자동으로 찍힘
│  수정일: 2024-01-15 15:30   │  ← 수정할 때마다 자동 갱신
└─────────────────────────────┘
```

---

## 설정 방법

### 1. 메인 클래스에 Auditing 활성화

```kotlin
@SpringBootApplication
@EnableJpaAuditing  // 이거 추가
class Application

fun main(args: Array<String>) {
    runApplication<Application>(*args)
}
```

### 2. BaseEntity 생성

```kotlin
@MappedSuperclass
@EntityListeners(AuditingEntityListener::class)
abstract class BaseEntity {

    @CreatedDate
    @Column(updatable = false)  // UPDATE 시 변경 방지
    var createdAt: Instant = Instant.now()

    @LastModifiedDate
    var updatedAt: Instant = Instant.now()
}
```

### 3. 엔티티에서 상속

```kotlin
@Entity
class Order(
    var status: String,
    var amount: Int,
) : BaseEntity()  // createdAt, updatedAt 자동 포함
```

이렇게 해두면 모든 엔티티에서 `createdAt`, `updatedAt`을 직접 관리할 필요가 없어요.

---

## 동작 방식

```kotlin
// 1. 새 주문 생성 (INSERT)
val order = Order(status = "PENDING", amount = 10000)
orderRepository.save(order)
// → createdAt = 2024-01-01 10:00 (자동)
// → updatedAt = 2024-01-01 10:00 (자동)

// 2. 나중에 수정 (UPDATE)
order.status = "COMPLETED"
// 트랜잭션 끝나면 자동 저장
// → createdAt = 2024-01-01 10:00 (그대로 유지!)
// → updatedAt = 2024-01-15 15:30 (자동 갱신)
```

`@Column(updatable = false)` 덕분에 `createdAt`은 수정할 때 바뀌지 않아요.

---

## 주요 어노테이션

| 어노테이션 | 동작 시점 | 설명 |
|-----------|----------|------|
| `@CreatedDate` | INSERT | 생성 시간 자동 기록 |
| `@LastModifiedDate` | INSERT, UPDATE | 수정 시간 자동 갱신 |
| `@CreatedBy` | INSERT | 생성자 자동 기록 |
| `@LastModifiedBy` | INSERT, UPDATE | 수정자 자동 기록 |

`@CreatedBy`, `@LastModifiedBy`를 쓰려면 `AuditorAware` 빈을 추가로 설정해야 해요.

---

## 정리

- Auditing = 생성/수정 시간 자동 기록
- `@EnableJpaAuditing` + `@EntityListeners` 설정 필요
- `@CreatedDate`, `@LastModifiedDate`로 필드 지정

매번 `createdAt = Instant.now()` 넣을 필요 없이 알아서 해주니까 편하더라고요!
