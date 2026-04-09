---
title: "이미지 최적화 (9) web/worker 중복 로직을 공통 패키지로 추출"
date: 2026-04-09 20:00:00 +0900
categories: [Frontend, Architecture]
tags: [nextjs, typescript, monorepo, refactoring, sharp, cache]
---

{% include image-optimization-series.html current=9 %}

## 문제

web/worker 양쪽 `route.ts`에 ~120줄의 동일 코드가 중복.

- 캐시 키 검증 (traversal 차단, fileId 숫자 검증)
- 원자적 디스크 쓰기 (tmp + rename)
- sharp WebP 변환 + 파라미터 파싱

보안 검증이 두 곳에 있으면 한쪽만 수정하는 실수가 난다.

## 폴더 구조 결정

**도메인 우선(`image/server/`)** vs 런타임 우선(`server/image/`).

`image/` 선택. 기존 `getImageSrc`, `kImageSizes` 같은 이미지 유틸과 한 곳에 모인다. `server/` 서브폴더는 barrel에서 제외하면 클라이언트 번들에 `fs`/`sharp`가 섞이지 않는다.

```
packages/app-commons/src/image/
├── index.ts           # client barrel
├── urls.ts            # getImageSrc
├── kImageSizes.ts     # 디자인 토큰
└── server/
    ├── index.ts       # server barrel
    ├── cache.ts       # fs 의존 — 캐시 읽기/쓰기
    └── optimize.ts    # sharp 의존 — 변환
```

`cache`와 `optimize`는 의존성이 완전히 달라서 분리. 독립 테스트/모킹 가능.

## 핵심 함수

### resolveCacheFilePath — 보안 검증을 한 곳으로

```ts
export function resolveCacheFilePath(options: {
  cacheDir: string | undefined;
  pathSegments: string[];
  width: number;
  quality: number;
}): string | null {
  if (!cacheDir) return null;
  if (pathSegments.length !== 1) return null;     // traversal 차단
  const fileId = pathSegments[0] ?? '';
  if (!/^\d+$/.test(fileId)) return null;          // 숫자 외 입력 차단
  return nodePath.join(cacheDir, `${fileId}_w${width}_q${quality}.webp`);
}
```

### writeCachedImageAtomic — 원자적 쓰기

```ts
const tmpPath = `${cachePath}.${process.pid}.tmp`;
await fs.writeFile(tmpPath, data);
await fs.rename(tmpPath, cachePath);  // POSIX rename = atomic
```

다른 프로세스가 반쯤 쓴 파일을 읽는 문제 방지.

## import 경로

| 경로 | 런타임 |
|---|---|
| `@myorg/app-commons/image` | universal |
| `@myorg/app-commons/image/server` | 서버 전용 |

기존 consumer는 barrel(`from '@myorg/app-commons'`)로 import → 변경 불필요.

## 효과

| 파일 | before | after |
|---|---|---|
| web `route.ts` | 267줄 | 192줄 |
| worker `route.ts` | 211줄 | 172줄 |

## 핵심

- 보안 검증은 중복이 아니라 **집중**이 필요하다. 여러 파일에 복사된 검증 로직은 하나를 고칠 때 나머지를 놓치는 패턴.
- 도메인 우선 폴더링(`image/server/`)이 런타임 우선(`server/image/`)보다 낫다. "이미지 코드 어디 있어?"에 단일 답이 나온다.
