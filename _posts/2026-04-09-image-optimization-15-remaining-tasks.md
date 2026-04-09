---
title: "이미지 최적화 (15) 남은 과제 — 캐시를 운영하려면"
date: 2026-04-09 23:59:00 +0900
categories: [Backend, Architecture]
tags: [cache, monitoring, testing, eviction, sharp]
---

{% include image-optimization-series.html current=15 %}

## 현재 상태

디스크 캐시가 동작한다. 보안 검증(traversal, 인증), 원자적 쓰기, multi-pod 공유까지 갖췄다. 하지만 "동작한다"와 "운영할 수 있다"는 다르다.

코드를 다시 읽으면서 정리한 후속 과제.

---

## 1. 캐시 용량 관리가 없다

PVC가 5Gi다. 캐시 파일은 계속 쌓인다. 삭제 로직이 없다.

```
현재: 요청 → 캐시 MISS → 변환 → 저장 → (영원히 남음)
```

5Gi가 차면? `writeCachedImageAtomic`에서 `ENOSPC` 에러가 나고, 캐시 쓰기가 조용히 실패한다. 기존 캐시 HIT은 동작하지만, 새 이미지는 캐시되지 않는다.

### 고민

**TTL(시간 기반 만료)** vs **LRU(접근 빈도 기반 삭제)**.

- TTL: 구현이 단순. CronJob으로 `find /app/cache/images -mtime +7 -delete`. 7일 지난 파일 삭제. 하지만 매일 조회되는 인기 이미지도 7일이면 삭제됨.
- LRU: 접근 시간(atime) 기반으로 가장 오래 안 읽힌 파일부터 삭제. 인기 이미지는 살아남음. 하지만 NFS에서 atime 갱신이 비싸고, `noatime` 마운트 옵션이 걸려 있으면 동작 안 함.
- **용량 기반 임계값**: `du -s`로 전체 크기를 재고, 80%를 넘으면 오래된 것부터 정리. 현실적으로 가장 합리적.

아직 미구현. 당장은 5Gi가 충분하지만, 이미지 수가 늘면 반드시 필요하다.

## 2. 캐시 무효화 전략이 없다

파일 ID 70의 원본 이미지가 교체되면? 캐시에는 이전 버전이 남아있다.

```
t=0: 70_w960_q75.webp 캐시 생성 (원본 A)
t=1: 백엔드에서 파일 70의 원본이 B로 교체
t=2: 캐시 HIT → 여전히 원본 A 응답
```

### 고민

현재 서비스에서 이 시나리오가 실제로 발생하는가? 파일 ID는 불변(immutable)인가?

- 만약 파일 업로드 시 새 ID가 발급된다면 (append-only), 캐시 무효화가 필요 없다. 같은 ID = 같은 파일이 보장됨.
- 만약 같은 ID에 파일이 덮어씌워질 수 있다면, 백엔드에서 수정 시점을 전달받아 캐시 키에 포함해야 한다. `70_v1682000000_w960_q75.webp` 같은 식으로.

현재는 파일 ID가 불변이라 문제 없다. 하지만 정책이 바뀌면 가장 먼저 깨지는 부분.

## 3. 단위 테스트가 없다

commons의 `cache.ts`, `optimize.ts`에 테스트가 없다.

```
resolveCacheFilePath  → traversal 차단 검증
writeCachedImageAtomic → tmp 파일 정리, rename 실패 시 동작
readCachedImage       → ENOENT vs EACCES 분기
optimizeImageToWebp   → sharp 변환 결과 검증
parseOptimizeParams   → 경계값 (w=0, w=9999, q=-1)
```

### 고민

보안 관련 함수(`resolveCacheFilePath`)는 테스트가 가장 급하다. 입력 조합이 명확하고, 실패 시 영향이 크다.

```ts
// 이런 케이스들이 커버되어야 함
resolveCacheFilePath({ pathSegments: ['../etc/passwd'], ... }) // → null
resolveCacheFilePath({ pathSegments: ['70'], ... })            // → 정상 경로
resolveCacheFilePath({ pathSegments: ['70', 'sub'], ... })     // → null
resolveCacheFilePath({ pathSegments: ['abc'], ... })           // → null
```

sharp 변환 테스트는 실제 이미지 파일이 필요해서 세팅 비용이 높다. 우선순위가 낮다.

## 4. 모니터링이 없다

`X-Image-Cache: HIT/MISS` 헤더를 응답에 넣고 있지만, 이걸 수집하는 곳이 없다.

알아야 하는 것:
- 전체 HIT율은 몇 %인가?
- 캐시 디스크 사용량이 몇 %인가?
- sharp 변환 실패율은?

### 고민

**헤더 기반 수집** vs **로그 기반 수집**.

- 헤더: Nginx 접근 로그에서 `X-Image-Cache` 필드를 파싱. 별도 코드 변경 없이 가능. 하지만 Next.js가 직접 응답하므로 Nginx를 안 거칠 수 있다.
- 로그: `console.log`로 HIT/MISS를 찍고 CloudWatch에서 메트릭 필터. 간단하지만 로그 볼륨이 늘어남.
- **Prometheus counter**: `image_cache_hit_total`, `image_cache_miss_total` 카운터를 route handler에 추가. 가장 정확하지만 prom-client 의존성 추가 필요.

당장은 CloudWatch 로그 메트릭 필터가 가장 현실적. 코드 변경 없이 기존 로그에서 추출 가능.

## 5. orphan tmp 파일 정리

`writeCachedImageAtomic`에서 프로세스가 rename 전에 죽으면 `.tmp` 파일이 남는다. catch 블록에서 `unlink`를 시도하지만, 프로세스 자체가 죽으면 catch도 실행 안 됨.

```bash
# 현재 orphan tmp 파일 확인
kubectl exec <pod> -- find /app/cache/images -name '*.tmp' -mmin +10
```

10분 이상 된 `.tmp`는 orphan이다. 쓰기에 10분 걸릴 리 없으니.

CronJob이나 캐시 정리 스크립트에서 같이 처리하면 된다. 용량 관리(1번)와 묶어서 구현.

## 6. OPTIMIZABLE_IMAGE_TYPES 범위

```ts
const OPTIMIZABLE_IMAGE_TYPES = new Set([
  'image/jpeg', 'image/png', 'image/webp',
  'image/gif', 'image/avif', 'image/tiff',
]);
```

avif, tiff를 WebP로 변환하는 게 맞는가?

- avif → WebP: avif가 이미 WebP보다 효율적. 오히려 품질 손해.
- tiff: 이 서비스에서 tiff 이미지가 업로드되는 경우가 있는가?
- gif → WebP: 애니메이션 gif는 WebP 변환 시 첫 프레임만 남을 수 있음.

### 결론

실제 서비스 데이터를 보고 판단해야 한다. avif/tiff 요청이 0건이면 제거. gif가 있으면 animated WebP 지원 여부 확인 필요.

## 7. response.clone() 메모리 비용

```ts
const fallbackResponse = response.clone();
try {
  const buffer = Buffer.from(await response.arrayBuffer());
  // ... sharp 변환
} catch {
  return buildPassthroughResponse(fallbackResponse.body, ...);
}
```

`response.clone()`은 응답 본문 전체를 메모리에 복제한다. 10MB 이미지라면 clone 시점에 20MB를 점유.

### 고민

clone 없이 fallback하는 방법이 있는가?

- `arrayBuffer()`를 먼저 읽고, sharp 실패 시 원본 buffer를 그대로 응답하면 clone이 필요 없다.
- 하지만 원본의 `Content-Type`과 `Content-Disposition` 헤더도 필요한데, 이건 clone 없이도 접근 가능 (이미 변수에 저장하고 있음).

```ts
// clone 없는 대안
const buffer = Buffer.from(await response.arrayBuffer());
try {
  const optimized = await optimizeImageToWebp(buffer, { width, quality });
  return webpResponse(optimized);
} catch {
  return buildPassthroughResponse(new Uint8Array(buffer), contentType, ...);
}
```

buffer를 이미 읽었으므로 그걸 그대로 쓰면 된다. clone 자체가 불필요했을 수 있다.

---

## 우선순위 정리

| 과제 | 긴급도 | 난이도 | 이유 |
|---|---|---|---|
| 캐시 용량 관리 | 높음 | 중 | 5Gi 초과 시 새 캐시 불가 |
| 단위 테스트 (보안) | 높음 | 낮 | traversal 검증 커버리지 |
| 모니터링 | 중 | 낮 | 캐시 효과 측정 불가 |
| response.clone 제거 | 중 | 낮 | 메모리 절약, 코드 단순화 |
| orphan tmp 정리 | 낮 | 낮 | 용량 관리와 묶어서 처리 |
| OPTIMIZABLE_TYPES 정리 | 낮 | 낮 | 실 데이터 확인 후 |
| 캐시 무효화 | 낮 | 중 | 현재 ID 불변이라 불필요 |

## 핵심

- "동작한다"와 "운영할 수 있다"의 차이는 모니터링, 용량 관리, 테스트에 있다.
- 후속 과제를 나열하는 것보다 **왜 아직 안 했는지, 어떤 선택지가 있는지**를 남기는 게 낫다. 코드는 결과만 보여주지만, 의사결정 맥락은 문서에만 남는다.
