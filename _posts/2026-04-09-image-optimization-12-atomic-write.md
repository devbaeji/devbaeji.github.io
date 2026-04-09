---
title: "이미지 최적화 (12) 원자적 쓰기 — tmp + rename으로 파일 손상 방지"
date: 2026-04-09 23:00:00 +0900
categories: [Backend, Node.js]
tags: [nodejs, filesystem, cache, concurrency, posix]
---

{% include image-optimization-series.html current=12 %}

## 문제

여러 pod가 같은 EFS 볼륨에 캐시를 쓴다.

같은 이미지를 두 요청이 동시에 처리하면:

```
Pod A: writeFile('/app/cache/images/70_w960_q75.webp', buffer_a)  // 50% 진행
Pod B: readFile('/app/cache/images/70_w960_q75.webp')             // 반쯤 쓴 파일을 읽음
```

결과: 깨진 WebP 이미지가 응답으로 나간다. `writeFile`은 원자적이지 않다 — 큰 파일은 여러 번의 시스템 콜로 나눠 쓴다.

## 해결: tmp + rename

```ts
async function writeCachedImageAtomic(options: {
  cacheDir: string;
  cachePath: string;
  data: Buffer;
}): Promise<void> {
  const tmpPath = `${cachePath}.${process.pid}.tmp`;
  try {
    await fs.mkdir(cacheDir, { recursive: true });
    await fs.writeFile(tmpPath, data);     // 임시 파일에 완전히 쓴 뒤
    await fs.rename(tmpPath, cachePath);   // rename으로 교체
  } catch (error) {
    console.warn('[image-cache] write failed', { cachePath, error });
    try { await fs.unlink(tmpPath); } catch { /* orphan 정리 */ }
  }
}
```

### 왜 rename이 안전한가

POSIX `rename(2)`는 같은 파일시스템 내에서 **원자적**이다. 파일이 "있거나 없거나" 두 상태만 존재. "반쯤 교체된" 상태는 없다.

```
tmpPath에 쓰기 완료 → rename → cachePath가 순간 교체
                              (읽는 쪽은 이전 파일 or 새 파일만 봄)
```

### process.pid를 붙이는 이유

같은 파일에 대해 여러 프로세스가 동시에 tmp 파일을 만들 수 있다. pid를 붙이면 tmp 파일끼리 충돌하지 않는다.

```
Pod A: 70_w960_q75.webp.12345.tmp
Pod B: 70_w960_q75.webp.67890.tmp
```

둘 다 rename을 시도하면 나중에 실행된 쪽이 이긴다. 어느 쪽이든 완전한 파일이므로 문제없다.

## 실패 처리

```ts
catch (error) {
  console.warn('[image-cache] write failed', { cachePath, error });
  try { await fs.unlink(tmpPath); } catch { /* ignore */ }
}
```

- 쓰기 실패 시 orphan tmp 파일 정리
- `unlink` 자체가 실패해도 무시 (이미 없을 수 있음)
- 캐시 쓰기 실패가 요청 실패로 이어지지 않음 — 호출부에서 `void`로 fire-and-forget

```ts
// route.ts
void writeCachedImageAtomic({ cacheDir, cachePath, data: optimized });
```

`await` 안 함. 캐시 저장은 응답 속도에 영향을 주지 않는다.

## `writeFile` vs `tmp + rename`

| | `writeFile` 직접 | `tmp + rename` |
|---|---|---|
| 쓰기 중 읽기 | 깨진 파일 | 이전 파일 or 없음 |
| 쓰기 중 crash | 불완전 파일 잔존 | tmp만 잔존 (캐시 무관) |
| 동시 쓰기 | 내용 섞임 가능 | 마지막 rename이 승리 |

## 핵심

- `writeFile`은 원자적이지 않다. 동시 접근이 있는 캐시에 직접 쓰면 안 된다.
- POSIX `rename`은 같은 파일시스템 내에서 원자적. tmp에 완전히 쓰고 rename하면 "반쯤 쓴 파일"이 노출되지 않는다.
- 캐시 쓰기 실패는 서비스 실패가 아니다. fire-and-forget으로 응답 속도와 분리.
