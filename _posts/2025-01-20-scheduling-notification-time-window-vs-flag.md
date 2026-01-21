---
title: "[Spring] 스케줄링 알림 구현하다 중복 발송 버그 만든 썰"
date: 2025-01-20 15:00:00 +0900
categories: [Backend, Spring]
tags: [spring, scheduler, notification, kotlin]
---

## 들어가며

작업자 관리 시스템을 만들면서 스케줄링 알림을 구현하게 됐다. 작업 시작 전 리마인더, 출근 지연 알림 등 5가지 알림을 주기적으로 보내야 했는데...

결론부터 말하면 **같은 알림이 1분마다 계속 오는 버그**를 만들었다.

---

## 요구사항

구현해야 할 알림은 이랬다.

| 알림 종류 | 발송 시점 | 조건 |
|---------|---------|------|
| 긴급 작업 알림 | 작업 시작 3시간 전 | CRITICAL 우선순위 |
| 작업 시작 예정 알림 | 작업 시작 1시간 전 | - |
| 출근 지연 알림 | 작업 시작 10분 후 | 미출근 상태 |
| 작업 종료 시간 알림 | 작업 종료 30분 후 | 미퇴근 상태 |
| 퇴근 누락 알림 | 작업 종료 3시간 후 | 미퇴근 상태 |

처음엔 단순하게 생각했다. "스케줄러 돌리면서 시간 체크해서 보내면 되겠지?"

---

## 첫 번째 구현: Time Window 방식

구글링 좀 하다가 "Time Window" 방식을 알게 됐다. 스케줄러가 5분마다 돌면서 현재 시간이 "발송 시점 ~ 발송 시점 + 5분" 사이면 보내는 방식.

```kotlin
@Scheduled(cron = "0 */5 * * * *")  // 5분마다 실행
fun sendWorkStartReminders() {
    val attendances = repository.findPendingAttendances(today)

    for (attendance in attendances) {
        if (isWithinWindow(attendance, now)) {
            sendNotification(attendance)
        }
    }
}

private fun isWithinWindow(attendance: Attendance, now: ZonedDateTime): Boolean {
    val targetTime = attendance.startTime.minus(Duration.ofHours(1))  // 1시간 전
    val windowEnd = targetTime.plus(Duration.ofMinutes(5))  // 5분 윈도우

    return now >= targetTime && now < windowEnd
}
```

로직은 이해가 됐다. 작업 시작이 14:00이면:

```
- targetTime = 13:00 (1시간 전)
- windowEnd = 13:05
- 13:00 ~ 13:05 사이에 스케줄러가 돌면 알림 발송
```

개발 서버에 올려서 테스트했는데 잘 됐다. "오 깔끔하네" 하고 넘어감.

---

## 그리고 버그 발생

문제는 로컬에서 테스트할 때 터졌다.

개발 서버는 5분마다 스케줄러가 도는데, 로컬에서 빠르게 테스트하려고 **1분마다 돌도록** 바꿨다. 근데 윈도우 크기는 그대로 5분...

```yaml
# 내가 한 짓
scheduling:
  cron: "0 */1 * * * *"  # 1분마다 실행
  window-minutes: 5       # 윈도우는 5분 그대로
```

결과?

```
13:00 스케줄러 실행 → 윈도우(13:00~13:05) 내 → 알림 발송!
13:01 스케줄러 실행 → 윈도우(13:00~13:05) 내 → 알림 발송!
13:02 스케줄러 실행 → 윈도우(13:00~13:05) 내 → 알림 발송!
13:03 스케줄러 실행 → 윈도우(13:00~13:05) 내 → 알림 발송!
13:04 스케줄러 실행 → 윈도우(13:00~13:05) 내 → 알림 발송!
```

**같은 알림이 5번 옴.**

테스트하는데 폰에서 알림이 1분마다 계속 울려서 "뭐지?" 했다. 로그 까보니까 같은 attendance_id로 5번 발송된 거였다.

---

## 원인 파악

한참 헤매다가 깨달음.

> 스케줄러 주기(1분)와 윈도우 크기(5분)가 안 맞으면, 윈도우 안에서 스케줄러가 여러 번 돌면서 중복 발송된다.

즉, **스케줄러 주기 = 윈도우 크기**여야 한다.

```
스케줄러 5분 주기 + 윈도우 5분 = OK (한 번만 발송)
스케줄러 1분 주기 + 윈도우 5분 = 5번 발송
스케줄러 1분 주기 + 윈도우 1분 = OK (한 번만 발송)
```

---

## 일단 급한 불 끄기

환경별로 설정을 분리했다.

```yaml
# application-local.yml
scheduling:
  notification:
    window-minutes: 1
    cron: "0 */1 * * * *"

# application-develop.yml
scheduling:
  notification:
    window-minutes: 5
    cron: "0 */5 * * * *"
```

이렇게 하니까 일단 중복은 안 생겼다. 근데 뭔가 찜찜했다.

---

## 이 방식의 한계

곰곰이 생각해보니 Time Window 방식은 근본적인 문제가 있었다.

1. **타이밍 이슈**: 스케줄러가 13:00:30에 실행되면? 13:00:00 ~ 13:01:00 윈도우를 놓칠 수 있음
2. **서버 장애**: 해당 윈도우 시간에 서버가 죽어있으면 알림 영구 누락
3. **"정확히 1번" 보장 불가**: 결국 윈도우 방식만으로는 한계가 있음

그래서 다른 방식을 찾아봤다.

---

## 더 나은 방법들

구글링하면서 찾은 방법들이다.

### 1. Flag 방식

엔티티에 "발송했는지 여부"를 저장하는 방식.

```kotlin
@Entity
class TicketScheduleAttendance(
    // ...

    @Column(name = "work_start_reminder_sent_at")
    var workStartReminderSentAt: Instant? = null,
)
```

```kotlin
fun sendWorkStartReminders() {
    val attendances = repository.findPendingAttendances(today)
        .filter { it.workStartReminderSentAt == null }  // 안 보낸 것만

    for (attendance in attendances) {
        if (shouldSend(attendance)) {
            sendNotification(attendance)
            attendance.workStartReminderSentAt = Instant.now()  // 발송 기록
        }
    }
}
```

이러면 아무리 스케줄러가 여러 번 돌아도 한 번만 발송된다. 단점은 알림 종류마다 필드가 늘어난다는 것.

### 2. Job Queue 방식

알림을 "예약 작업"으로 등록해두고, 워커가 처리하는 방식.

```sql
CREATE TABLE scheduled_jobs (
    id BIGINT PRIMARY KEY,
    type VARCHAR(50),          -- 'WORK_START_REMINDER'
    target_id BIGINT,
    scheduled_at TIMESTAMP,
    status VARCHAR(20),        -- PENDING → COMPLETED
    executed_at TIMESTAMP
);
```

작업 배정할 때 미리 알림 작업도 등록해두고, 스케줄러가 `PENDING` 상태인 것만 처리하고 `COMPLETED`로 바꾸는 방식. 더 정교한데 테이블이 하나 더 필요하다.

### 3. Idempotency Key 방식

발송할 때 고유 키를 만들어서 중복 체크.

```sql
-- 'work_start_reminder_attendance_123_2025-01-20' 같은 키로 중복 방지
INSERT INTO sent_notifications (idempotency_key, sent_at) VALUES (?, ?)
```

결제 시스템에서 많이 쓰는 방식이라고 한다. 기존 엔티티 수정 없이 별도 테이블로 관리.

---

## 뭘 선택할까

| 방식 | 복잡도 | 중복방지 | 언제 쓸까 |
|-----|-------|---------|---------|
| Time Window | 낮음 | 약함 | 빠르게 만들 때 |
| Flag | 낮음 | 강함 | 알림 종류가 고정적일 때 |
| Job Queue | 중간 | 강함 | 규모가 클 때 |
| Idempotency Key | 중간 | 강함 | 엔티티 수정이 어려울 때 |

---

## 결론

일단 지금은 Time Window + 환경별 설정으로 급한 불은 껐다.

근데 제대로 하려면 Flag 방식으로 고도화해야 할 것 같다. 알림이 5종류로 고정이라 필드 5개 추가하면 되니까. 나중에 시간 나면 리팩토링해야지.

교훈: **스케줄러 주기랑 윈도우 크기는 맞춰야 한다.** 안 그러면 1분마다 알림 온다.

---

## 참고

- [Spring @Scheduled 문서](https://docs.spring.io/spring-framework/docs/current/javadoc-api/org/springframework/scheduling/annotation/Scheduled.html)
