---
title: "Kotlin copy()를 JPA Entity에서 쓰면 안 되는 이유"
date: 2026-01-29 17:20:00 +0900
categories: [Backend, JPA]
tags: [jpa, hibernate, kotlin, data-class, entity, bug]
---

## 실제 버그 사례

주문(Order)을 수정한 직후, `createdAt`이 **수정한 시간**으로 바뀌는 버그가 발생했어요.

새로고침하면 원래대로 돌아오는데, 수정 직후에만 이상하게 나오는 거예요.

**원인:** Kotlin data class의 `copy()`를 사용했기 때문이었어요.

---

## 문제 코드

```kotlin
@Entity
data class Order(
    @Id @GeneratedValue
    val id: Long = 0,
    val status: String,
    val amount: Int,
) : BaseEntity()

@Service
class OrderService(
    private val orderRepository: OrderRepository
) {
    @Transactional
    fun updateOrder(id: Long, newStatus: String) {
        val order = orderRepository.findById(id)

        // ❌ copy() 사용
        val updated = order.copy(status = newStatus)
        orderRepository.save(updated)
    }
}
```

---

## copy()가 문제인 이유

```kotlin
val updated = order.copy(status = newStatus)
```

이 코드는 **새로운 객체**를 만들어요.

```
원본 (DB에서 조회)        copy() 결과 (새 객체)
┌──────────────────┐    ┌──────────────────────┐
│ id: 1            │    │ id: 1                │
│ status: "PENDING"│ →  │ status: "COMPLETED"  │
│ createdAt:       │    │ createdAt:           │
│   2024-01-01     │    │   2024-01-15 ← 문제! │
│                  │    │   (Instant.now())    │
└──────────────────┘    └──────────────────────┘
```

새 객체가 만들어지면서 `BaseEntity`의 생성자가 다시 실행돼요:

```kotlin
abstract class BaseEntity {
    var createdAt: Instant = Instant.now()  // ← 새 객체 만들 때 실행됨!
}
```

그래서 `createdAt`이 현재 시간으로 덮어씌워지는 거예요.

---

## 해결 방법

**copy() 대신 직접 수정하면 돼요.**

```kotlin
@Entity
class Order(  // data class 제거
    @Id @GeneratedValue
    val id: Long = 0,
    var status: String,  // val → var
    var amount: Int,
) : BaseEntity()

@Service
class OrderService(
    private val orderRepository: OrderRepository
) {
    @Transactional
    fun updateOrder(id: Long, newStatus: String) {
        val order = orderRepository.findById(id)

        // ✅ 직접 수정
        order.status = newStatus

        // save() 불필요 - 더티 체킹이 자동 저장
    }
}
```

---

## Before vs After

| | Before (copy) | After (직접 수정) |
|---|---|---|
| Entity 필드 | `val` | `var` |
| 수정 방식 | `order.copy(...)` | `order.status = ...` |
| save() | 필요 | 불필요 |
| createdAt | 초기화됨 (버그) | 유지됨 (정상) |

---

## JPA와 Kotlin의 철학 차이

| | JPA | Kotlin data class |
|---|---|---|
| 가변성 | var (mutable) 권장 | val (immutable) 권장 |
| 수정 방식 | 필드 직접 수정 | copy()로 새 객체 |
| 상태 관리 | 영속성 컨텍스트가 추적 | 불변 객체 교체 |

JPA는 **가변 엔티티 + 더티 체킹**이 설계 철학이에요. 불변 객체 패턴과는 안 맞더라고요.

---

## 정리

- JPA Entity에서 `copy()` 사용하면 안 돼요
- `val` 대신 `var`로 선언하고 직접 수정
- [더티 체킹](/posts/jpa-dirty-checking)이 자동으로 UPDATE 처리해줘요
- 불변 객체를 쓰고 싶다면 JPA 대신 다른 프레임워크(jOOQ, Exposed 등) 고려

"불변 객체가 좋다"고 배워서 습관적으로 copy() 썼는데, JPA에서는 이게 버그 원인이 될 수 있다는 걸 알게 됐어요!

---

## 관련 글

- [JPA 더티 체킹이란?](/posts/jpa-dirty-checking)
- [JPA Auditing이란?](/posts/jpa-auditing)
