---
title: "JPA에서 Soft Delete 구현하는 방법"
date: 2025-01-09 17:00:00 +0900
categories: [Backend, JPA]
tags: [jpa, soft-delete, spring]
---

## Soft Delete vs Hard Delete

### Soft Delete (논리적 삭제)

데이터를 실제로 삭제하지 않고, **삭제 플래그를 설정**하여 삭제된 것으로 표시하는 방법이다.

| 장점 | 단점 |
|------|------|
| 실수로 삭제된 데이터 복구 가능 | 추가 저장 공간 필요 |
| 데이터 히스토리 보존 | 쿼리에 삭제 여부 조건 필요 |

### Hard Delete (물리적 삭제)

데이터를 **실제로 삭제**하는 방법이다. 삭제된 데이터는 시스템에서 완전히 제거되어 복구할 수 없다.

| 장점 | 단점 |
|------|------|
| 저장 공간 절약 | 복구 불가능 |
| 쿼리 단순화 | 데이터 히스토리 손실 |

---

## JPA에서 Soft Delete 구현하기

Soft Delete를 구현하려면 두 가지를 지켜야 한다.

1. **삭제 시 DELETE 대신 UPDATE 실행** → `@SQLDelete`
2. **조회 시 삭제된 데이터 제외** → `@Where`

### @SQLDelete 어노테이션

`delete()` 호출 시 DELETE 쿼리 대신 **UPDATE 쿼리**가 실행되도록 설정한다.

```java
@SQLDelete(sql = "UPDATE cafe_policy SET deleted = true WHERE id = ?")
@Entity
public class CafePolicy extends BaseDate {

    @Id
    @GeneratedValue(strategy = IDENTITY)
    private Long id;

    private Integer maxStampCount;
    private String reward;
    private Integer expirePeriod;

    private Boolean deleted = Boolean.FALSE; // 기본값 FALSE

    // ...
}
```

> `@SQLDelete`도 영속성 컨텍스트에서 관리되다가 트랜잭션 종료 시 처리된다.
{: .prompt-info }

### @Where 어노테이션

모든 조회 쿼리에 **`WHERE deleted = false`** 조건을 자동으로 추가한다.

```java
@SQLDelete(sql = "UPDATE cafe_policy SET deleted = true WHERE id = ?")
@Where(clause = "deleted = false")
@Entity
public class CafePolicy extends BaseDate {

    @Id
    @GeneratedValue(strategy = IDENTITY)
    private Long id;

    private Integer maxStampCount;
    private String reward;
    private Integer expirePeriod;

    private Boolean deleted = Boolean.FALSE;

    // ...
}
```

---

## 전체 코드

```java
@NoArgsConstructor(access = PROTECTED)
@Getter
@SQLDelete(sql = "UPDATE cafe_policy SET deleted = true WHERE id = ?")
@Where(clause = "deleted = false")
@Entity
public class CafePolicy extends BaseDate {

    @Id
    @GeneratedValue(strategy = IDENTITY)
    private Long id;

    private Integer maxStampCount;

    private String reward;

    private Integer expirePeriod;

    private Boolean deleted = Boolean.FALSE;

    // ...
}
```

---

## 정리

| 어노테이션 | 역할 |
|-----------|------|
| `@SQLDelete` | delete() 호출 시 UPDATE 쿼리로 대체 |
| `@Where` | 모든 조회에 `deleted = false` 조건 추가 |

Soft Delete는 데이터 복구가 필요하거나 히스토리 보존이 중요한 경우 유용하다.
