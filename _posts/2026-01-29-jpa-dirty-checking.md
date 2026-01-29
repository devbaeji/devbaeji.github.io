---
title: "JPA 더티 체킹이란? save() 없이 자동 저장되는 이유"
date: 2026-01-29 17:00:00 +0900
categories: [Backend, JPA]
tags: [jpa, hibernate, kotlin, dirty-checking, transaction]
---

## 더티 체킹(Dirty Checking)이란?

JPA가 엔티티의 변경을 감지해서 **자동으로 UPDATE 쿼리를 실행**해주는 기능이에요.

"Dirty"는 "더러워진" = "변경된"이라는 뜻이에요.

---

## 예시 코드

```kotlin
@Service
class OrderService(
    private val orderRepository: OrderRepository
) {
    @Transactional
    fun updateOrderStatus(id: Long, newStatus: String) {
        val order = orderRepository.findById(id)

        order.status = newStatus  // 값만 바꿈

        // save() 안 해도 됨!
        // 트랜잭션 끝나면 JPA가 알아서 UPDATE 실행
    }
}
```

처음엔 "어? save() 안 불렀는데 왜 저장돼?" 싶었는데, 이게 더티 체킹이더라고요.

---

## 동작 원리

```
1. findById() 실행
   - DB에서 order 조회
   - JPA가 원본 스냅샷 저장해둠 (status = "PENDING")

2. order.status = "COMPLETED"
   - 메모리에서 값만 바뀜
   - 아직 DB는 그대로

3. 트랜잭션 끝 (@Transactional 메서드 종료)
   - JPA: "어? 원본이랑 다르네?" (더티 = 변경됨)
   - 자동으로 UPDATE 쿼리 실행
```

JPA가 처음 조회할 때 스냅샷을 찍어두고, 트랜잭션 끝날 때 비교하는 방식이에요.

---

## @Transactional이 필수인 이유

```kotlin
// ✅ 더티 체킹 동작함
@Transactional
fun updateOrder(id: Long, newStatus: String) {
    val order = orderRepository.findById(id)
    order.status = newStatus
    // 자동 저장됨
}

// ❌ 더티 체킹 동작 안 함
fun updateOrderNoTransaction(id: Long, newStatus: String) {
    val order = orderRepository.findById(id)
    order.status = newStatus
    // DB에 반영 안 됨!
}
```

더티 체킹은 트랜잭션이 커밋될 때 동작해요. `@Transactional`이 없으면 트랜잭션이 없으니까 더티 체킹도 동작하지 않아요.

---

## 정리

| 항목 | 설명 |
|------|------|
| 더티 체킹 | 엔티티 변경 감지 → 자동 UPDATE |
| 조건 | `@Transactional` 안에서 실행 |
| save() | 불필요 (호출해도 되지만 의미 없음) |

JPA 쓰면서 "왜 save() 안 해도 되지?" 궁금했다면, 이게 답이에요!
