---
title: "이미지 최적화 (11) 캐시 키에 path traversal 차단이 필요한 이유"
date: 2026-04-09 22:00:00 +0900
categories: [Backend, Security]
tags: [security, path-traversal, cache, nodejs]
---

{% include image-optimization-series.html current=11 %}

## 상황

디스크 캐시의 키를 URL path에서 만든다.

```
GET /stream-files/70?w=960&q=75
→ 캐시 파일: /app/cache/images/70_w960_q75.webp
```

`70`은 사용자 요청에서 온 값이다. 검증 없이 `path.join`에 넣으면 어떻게 되는가.

## 공격 시나리오

```
GET /stream-files/../../etc/passwd?w=960&q=75
```

검증 없는 코드:

```ts
// 위험
const cachePath = path.join(cacheDir, `${pathSegments.join('/')}_w${w}_q${q}.webp`);
// → /app/cache/images/../../etc/passwd_w960_q75.webp
// → /etc/passwd_w960_q75.webp
```

`path.join`은 `..`을 해석한다. 캐시 디렉토리를 벗어난 경로에 파일을 쓸 수 있다.

읽기도 마찬가지. 캐시 HIT 로직이 이 경로에서 `fs.readFile`을 하면, 캐시 디렉토리 바깥 파일을 읽어서 응답할 수 있다.

## 방어: 3중 검증

```ts
export function resolveCacheFilePath(options: {
  cacheDir: string | undefined;
  pathSegments: string[];
  width: number;
  quality: number;
}): string | null {
  const { cacheDir, pathSegments, width, quality } = options;

  if (!cacheDir) return null;

  // 1. 세그먼트가 1개가 아니면 거부 — 중첩 경로 자체를 차단
  if (pathSegments.length !== 1) return null;

  // 2. 숫자만 허용 — ../나 특수문자 원천 차단
  const fileId = pathSegments[0] ?? '';
  if (!/^\d+$/.test(fileId)) return null;

  // 3. 결과 경로가 cacheDir 안에 있는지 최종 확인
  const resolved = nodePath.join(cacheDir, `${fileId}_w${width}_q${quality}.webp`);
  if (!resolved.startsWith(cacheDir)) return null;

  return resolved;
}
```

| 검증 | 차단하는 것 |
|---|---|
| `pathSegments.length !== 1` | `a/b/c`, `../etc` 등 중첩 경로 |
| `/^\d+$/` | `..`, `%2e%2e`, 특수문자, 영문 |
| `startsWith(cacheDir)` | 위 두 검증을 우회하는 미지의 케이스 |

`null`을 반환하면 캐시를 건너뛰고 원본을 그대로 프록시한다. 거부가 아니라 캐시 스킵.

## 왜 함수로 격리하는가

이 검증이 route handler에 인라인돼 있으면:

- web `route.ts`와 worker `route.ts` 두 곳에 복사
- 한쪽만 고치면 나머지가 취약
- 리뷰어가 두 파일을 교차 비교해야 함

한 함수에 모으면 리뷰 포인트도 하나, 수정도 하나.

## 핵심

- 사용자 입력으로 파일 경로를 만들 때는 항상 traversal을 의심한다.
- `path.join`은 정규화를 하지만 방어를 하지는 않는다.
- 검증을 여러 겹 두되, 결과가 `null`(캐시 스킵)이면 서비스는 계속 동작한다. 차단이 아니라 안전한 fallback.
