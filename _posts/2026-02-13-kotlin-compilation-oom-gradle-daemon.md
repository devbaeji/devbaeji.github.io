---
title: "[Troubleshooting] Kotlin 빌드가 갑자기 OOM으로 터졌다 - JVM 메모리와 Gradle 데몬 이야기"
date: 2026-02-13 00:00:00 +0900
categories: [Troubleshooting]
tags: [kotlin, gradle, jvm, oom, memory, daemon]
---

## 이슈 파악

어제까지만 해도 잘 돌아가던 Spring Boot 프로젝트가 갑자기 빌드에서 터졌어요.

```
> Task :apps:api:kaptGenerateStubsKotlin

Error occurred during initialization of VM
java.lang.OutOfMemoryError: Initial heap size set to a larger value than the maximum heap size
```

코드를 한 줄도 수정한 적이 없는데, 갑자기 OOM이라니... 뭔가 이상했어요.

---

## 원인 분석

### Step 1: 에러 메시지 읽기

`OutOfMemoryError`라고 하면 "메모리가 부족하다"는 건데, 정확히 **어디의** 메모리가 부족한 걸까요?

이걸 이해하려면 먼저 JVM이 뭔지부터 알아야 했어요.

### Step 2: JVM과 힙 메모리 이해하기

**JVM(Java Virtual Machine)**은 Java/Kotlin 코드를 실행하는 가상 머신이에요. Java 프로세스 하나당 JVM 하나가 뜨고, 각 JVM은 자기만의 **힙 메모리(Heap Memory)**를 가져요.

```
┌──────────────────────────────────────┐
│            운영체제 (macOS)            │
│                                      │
│  ┌────────────┐  ┌────────────┐      │
│  │  JVM #1    │  │  JVM #2    │      │
│  │ (Spring)   │  │ (Gradle)   │      │
│  │            │  │            │      │
│  │ Heap: 2GB  │  │ Heap: 512MB│      │
│  └────────────┘  └────────────┘      │
│                                      │
│  ┌────────────┐                      │
│  │  JVM #3    │                      │
│  │ (Kotlin    │                      │
│  │  Compiler) │                      │
│  │ Heap: 512MB│                      │
│  └────────────┘                      │
└──────────────────────────────────────┘
```

여기서 중요한 건 **`-Xmx` 옵션**이에요. 이 값이 JVM이 사용할 수 있는 최대 힙 메모리를 결정해요.

- `-Xmx512m` → 최대 512MB까지 사용 가능
- `-Xmx2g` → 최대 2GB까지 사용 가능

### Step 3: Gradle 빌드 시 JVM이 몇 개 뜰까?

`./gradlew build`를 실행하면 JVM이 **3개**나 뜨더라고요.

```bash
ps aux | grep java
```

| 프로세스 | 역할 | 기본 `-Xmx` |
|---------|------|-------------|
| **Gradle Daemon** | 빌드 전체를 관리하는 데몬 | 512MB |
| **Kotlin Compiler Daemon** | Kotlin 코드를 컴파일 | 512MB |
| **Spring Boot** (bootRun 시) | 애플리케이션 실행 | 설정에 따름 |

여기서 놀라운 사실: **Gradle Daemon과 Kotlin Compiler Daemon은 빌드가 끝나도 죽지 않아요.**

### Step 4: 데몬은 왜 안 죽을까?

처음엔 "빌드 끝나면 당연히 프로세스가 종료되는 거 아니야?" 라고 생각했는데, 아니었어요.

**데몬(Daemon)**은 백그라운드에서 계속 대기하는 프로세스예요. Gradle이 데몬 방식을 쓰는 이유는:

1. **JVM 시작 비용 절감**: JVM을 새로 띄우는 데 수 초가 걸려요. 데몬을 재사용하면 이 시간을 아낄 수 있어요.
2. **코드 캐싱**: 이전 빌드의 컴파일 결과를 메모리에 캐싱해둬서 다음 빌드가 더 빨라져요.
3. **JIT 최적화 유지**: JVM은 자주 실행되는 코드를 네이티브로 최적화(JIT 컴파일)하는데, 데몬이 살아있으면 이 최적화가 유지돼요.

```
빌드 1회차: JVM 시작(3초) + 컴파일(10초) = 13초
빌드 2회차: 데몬 재사용(0초) + 컴파일(6초) = 6초  ← 훨씬 빠름!
```

대신 데몬이 **메모리를 계속 차지하고 있다**는 단점이 있어요. 기본적으로 **3시간** 동안 안 쓰면 자동 종료되는데, 개발하는 동안에는 계속 살아있어요.

### Step 5: 진짜 원인 - 시스템 메모리 압박

자, 여기서 핵심이에요. 코드를 하나도 안 바꿨는데 왜 OOM이 뜨는 걸까?

시스템 메모리 상태를 확인해봤어요.

```bash
# 시스템 전체 메모리 확인
sysctl hw.memsize
# hw.memsize: 25769803776 (24GB)

# 현재 메모리 사용 현황
vm_stat
```

macOS 활성 상태 보기에서 확인해보니:

| 항목 | 값 |
|------|-----|
| 물리 메모리 | 24GB |
| 사용 중인 메모리 | **약 21GB** |
| 스왑(Swap) 사용 | **약 15GB** |

**물리 메모리 24GB 중 21GB를 이미 쓰고 있었어요!** 그리고 스왑도 15GB나 쓰고 있었고요.

메모리를 많이 쓰고 있는 앱들을 확인해봤더니:

```bash
ps aux --sort=-%mem | head -20
```

| 앱 | 메모리 |
|----|--------|
| Chrome | ~2.1GB |
| Docker | ~1.4GB |
| Figma | ~1GB |
| Claude Code | ~619MB |
| Notion | ~576MB |
| Slack | ~539MB |
| ChatGPT | ~500MB |
| IntelliJ IDEA | ~400MB+ |

개발하면서 이것저것 다 띄워놓으니 메모리가 빠듯했던 거예요.

### Step 6: 퍼즐 완성

원인을 종합하면:

1. **Kotlin Compiler Daemon**의 기본 최대 힙 메모리는 **512MB** (`-Xmx512m`)
2. 시스템 물리 메모리 24GB 중 **21GB를 이미 사용 중**
3. OS가 Kotlin Compiler Daemon에게 512MB를 할당해주려고 했지만, **물리 메모리가 부족**해서 실패
4. 스왑까지 15GB나 쓰고 있어서 OS도 여유가 없었음

**코드가 바뀐 게 아니라, 시스템의 메모리 상태가 바뀐 거였어요.**

어제는 Chrome 탭을 적게 열었거나, Docker 컨테이너가 적었거나, 메모리에 여유가 있었겠지만 오늘은 이것저것 띄워놓다 보니 OOM이 발생한 거예요.

---

## 해결 방법

### 방법 1: 메모리 확보 (임시 해결)

당장 빌드해야 할 때는 메모리를 좀 비워주면 돼요.

```bash
# 안 쓰는 Gradle 데몬 전부 종료
./gradlew --stop

# Docker 컨테이너 정리
docker system prune
```

그리고 Chrome 탭 좀 닫고, 안 쓰는 앱을 종료하면 돼요.

### 방법 2: Kotlin Compiler 메모리 늘리기 (근본 해결)

프로젝트 루트에 `gradle.properties` 파일을 만들거나 수정해서 메모리를 넉넉하게 잡아줄 수 있어요.

```properties
# gradle.properties
kotlin.daemon.jvmargs=-Xmx2g
org.gradle.jvmargs=-Xmx2g
```

- `kotlin.daemon.jvmargs`: Kotlin Compiler Daemon의 힙 메모리
- `org.gradle.jvmargs`: Gradle Daemon의 힙 메모리

기본 512MB에서 2GB로 올리면 웬만해서는 OOM이 안 뜨더라고요.

### 방법 3: 데몬 비활성화 (메모리 아끼기)

메모리가 부족한 환경에서는 데몬을 아예 안 쓸 수도 있어요.

```bash
./gradlew build --no-daemon
```

빌드할 때마다 JVM을 새로 띄우니까 좀 느려지지만, 빌드 끝나면 메모리를 바로 반환해요.

---

## 유용한 진단 명령어

혹시 비슷한 상황이라면 아래 명령어들로 확인해보세요.

```bash
# 1. 시스템 전체 물리 메모리 확인
sysctl hw.memsize

# 2. 현재 떠있는 Java 프로세스 확인
ps aux | grep java

# 3. Java 프로세스별 메모리 사용량 (RSS 기준)
ps -eo pid,rss,command | grep java | grep -v grep

# 4. Kotlin Compiler Daemon의 -Xmx 확인
ps aux | grep kotlin | grep -v grep

# 5. 스왑 사용량 확인
sysctl vm.swapusage

# 6. 메모리 많이 쓰는 프로세스 순으로 정렬
ps aux --sort=-%mem | head -20
```

참고로 `ps` 명령어의 RSS(Resident Set Size)는 각 프로세스가 실제로 물리 메모리에 올려둔 크기예요. macOS 활성 상태 보기에서 보이는 "사용 중인 메모리"보다 작게 나오는데, 이는 커널 메모리, 압축된 메모리, GPU 메모리 등이 `ps`에는 안 잡히기 때문이에요.

---

## 배운 점

### 1. JVM 프로세스는 각각 독립적인 메모리를 가진다

Gradle 빌드를 한 번 하면 JVM이 3개(Gradle Daemon + Kotlin Compiler Daemon + 앱)까지 뜰 수 있어요. 각각 512MB씩이면 그것만으로 1.5GB예요.

### 2. 데몬은 편하지만 메모리를 먹고 있다

빌드 속도를 위해 데몬이 백그라운드에서 살아있는 건 좋지만, 메모리가 부족한 환경에서는 부담이 될 수 있어요.

### 3. OOM의 원인이 항상 코드에 있는 건 아니다

코드를 하나도 안 바꿨는데 OOM이 뜰 수 있어요. 시스템의 메모리 상태가 달라지면 같은 코드라도 실패할 수 있다는 걸 배웠어요.

### 4. 개발할 때 메모리 관리도 중요하다

Chrome, Docker, Figma, Slack, Notion... 개발하면서 이것저것 다 띄워놓다 보면 24GB도 부족해지더라고요. 가끔은 활성 상태 보기로 메모리 현황을 체크해보는 습관이 필요한 것 같아요.

---

## 마무리

"어제까지 됐는데 오늘 안 돼요"의 원인이 항상 코드에 있는 건 아니에요.

이번 경험으로 JVM 메모리 구조, Gradle 데몬의 동작 방식, 그리고 시스템 메모리가 빌드에 미치는 영향까지 한 번에 배울 수 있었어요. 다음에 비슷한 상황이 오면 당황하지 않고 진단할 수 있을 것 같아요!
