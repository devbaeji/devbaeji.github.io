---
title: "[TIL] PVC 알림을 보다가 찾은 이미지 캐시 쓰기 실패 — 공유 EFS 에서 mkdir 이 ENOENT 를 낸 이유"
date: 2026-10-27 09:00:00 +0900
categories: [TIL]
tags: [kubernetes, efs, nfs, nodejs, cache, troubleshooting]
---

운영 중인 Next.js 앱 세 개(web·admin·worker)는 이미지 프록시 결과(HEIC 변환, 리사이즈한 webp)를 디스크에 캐시한다. 운영에서는 여러 pod 가 EFS 볼륨 하나를 PVC 로 같이 마운트해서 캐시를 공유한다.

## 시작은 PVC 알림이었다

어느 날 admin pod 가 `FailedScheduling` 이라는 알림이 왔다.

```
0/5 nodes are available: pod has unbound immediate PersistentVolumeClaims
```

그날 admin 에 이미지 캐시용 PVC 를 처음 붙인 배포가 나갔다. StorageClass 는 EFS 동적 프로비저닝에 `volumeBindingMode: Immediate` 였다. PV 가 만들어져 바인딩되기까지 스케줄러가 pod 를 올리지 못한 것이다. 이벤트 시각과 pod 기동 시각을 맞춰 보니 약 10초 차이였고, 재시작도 없었다. 첫 프로비저닝 때만 생기는 일시적 지연이라 조치 없이 닫았다.

## 같은 경로에서 다른 경고가 쌓이고 있었다

알림을 확인하면서 그 시간대의 컨테이너 로그도 같이 봤는데, 같은 캐시 경로에서 이런 경고가 섞여 있었다.

```
[image-cache] write failed ENOENT: no such file or directory, mkdir '/app/cache/images/u{사용자ID}'
```

admin 만의 문제가 아니었다. 몇 달 전부터 PVC 를 쓰던 web·worker 에도 똑같이 있었다. 로그 보관 기간(30일)을 끝까지 거슬러 올라가도 이미 나고 있었고, 최근 트래픽이 늘면서 worker 는 하루 11·42·28·15건, admin 은 하루 17건까지 늘었다.

그동안 아무도 몰랐던 건 캐시 쓰기가 실패해도 warn 로그만 남기고 응답은 정상으로 나가기 때문이다. 사용자는 이상을 못 느끼고, 서버만 다음 요청에서 HEIC 변환을 다시 한다. 장애가 아니라 비용으로 새고 있었다.

## 동시에 처음 만들 때만 실패했다

캐시 경로는 사용자별 하위 디렉토리(`{root}/u{N}/{파일명}`)였고, 쓰기 전에 `fs.mkdir(dirname, { recursive: true })` 를 불렀다.

에러 메시지만 보면 부모 디렉토리가 없는 것처럼 읽힌다. 하지만 같은 루트 아래의 다른 쓰기는 대부분 성공하고 있었다. 실패한 시각을 모아 보니 **여러 pod 가 같은 사용자 디렉토리를 같은 초에 처음 만들 때만** 났고, 한 번 시작되면 약 30초 동안 이어졌다.

Node 의 recursive mkdir 은 중간에 어느 단계가 실패했든 처음 넘긴 경로를 에러에 그대로 찍는다. 메시지에 적힌 경로가 실제로 없던 경로라는 보장이 없다는 걸 이번에 알았다.

원인은 NFS 클라이언트의 lookup 캐시로 추정했다. 재현해서 증명하지는 않았다.

1. pod A, B 가 거의 동시에 `u{N}` 을 찾고, 둘 다 "없음"을 받아 클라이언트에 캐시한다.
2. A 가 mkdir 에 먼저 성공한다.
3. B 의 mkdir 은 `EEXIST` 를 받고, recursive mkdir 은 그 경로가 디렉토리인지 다시 확인한다.
4. 그 확인이 캐시된 "없음"을 보고 `ENOENT` 로 끝난다.

실패가 30초쯤 이어지는 것도 NFS 디렉토리 속성 캐시의 기본 유지 시간(`acdirmin` 30초)과 맞았다. 로컬 디스크였다면 생기지 않았을 문제다.

## 재시도 대신 디렉토리를 없앴다

ENOENT 가 나면 잠깐 기다렸다 다시 시도하는 방법도 있었다. 하지만 그건 캐시가 풀리는 타이밍에 기대는 방법이다. 따져 보니 사용자 디렉토리는 캐시 키를 사용자별로 나누려는 것일 뿐 꼭 디렉토리일 필요가 없었다. 그래서 사용자를 파일명 접두로 붙였다.

```typescript
// 변경 전: {root}/u{userKey}/{fileId}_w{w}_q{q}_v2.webp
// 변경 후: {root}/u{userKey}.{fileId}_w{w}_q{q}_v2.webp
return nodePath.join(cacheDir, userKey !== undefined ? `u${userKey}.${fileName}` : fileName);
```

모든 파일이 이미 있는 볼륨 루트 바로 아래에 생기니 pod 끼리 디렉토리를 만들 일 자체가 없다. 로컬 개발에서는 캐시 루트가 `/tmp` 아래라 지워져 있을 수 있어서 루트 mkdir 은 남겼다.

## 평평하게 만들면서 따라온 두 가지

**키 경계.** 디렉토리일 때는 `/` 가 사용자와 파일을 확실히 갈랐는데, 파일명으로 합치면 그 역할을 `.` 이 맡는다. 값 안에 `.` 이 들어갈 수 있으면 서로 다른 사용자·파일 조합이 같은 파일명이 될 수 있다. userKey 와 fileId 모두 `.` 을 허용하지 않게 검증하고, 경계가 섞이는 입력과 공용 키가 사용자 접두를 흉내 내는 입력을 테스트로 고정했다.

**tmp 파일명.** 캐시는 tmp 파일에 쓴 뒤 `rename` 으로 바꿔 넣는데, tmp 이름에 `process.pid` 를 쓰고 있었다. 컨테이너는 PID 네임스페이스가 따로라서 같은 이미지의 pod 들은 PID 가 같을 수 있다. 공유 볼륨에서 두 pod 가 같은 이미지를 동시에 캐시하면 같은 tmp 에 겹쳐 쓰게 된다. `randomUUID()` 로 바꿨다.

```typescript
const tmpPath = `${cachePath}.${randomUUID()}.tmp`;
await fs.mkdir(nodePath.dirname(cachePath), { recursive: true });
await fs.writeFile(tmpPath, data);
await fs.rename(tmpPath, cachePath);
```

두 가지 모두 코드 리뷰를 거치며 보강했다.

## 정리

처음 알림은 별일 아니었지만, 같은 경로의 로그를 같이 본 덕분에 한 달 넘게 묻혀 있던 실패를 찾았다. 로컬 디스크를 전제로 짠 코드를 공유 볼륨에 올리면 "디렉토리가 있으면 있는 것", "PID 는 유일하다" 같은 가정이 깨질 수 있다. 이번에는 재시도로 버티기보다 여러 pod 가 함께 만드는 디렉토리와 겹칠 수 있는 이름을 없애는 쪽을 택했다.
