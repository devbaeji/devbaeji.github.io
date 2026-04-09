---
title: "이미지 최적화 (3) Custom Loader — srcset은 살리고 프록시는 버리기"
date: 2026-04-07 12:00:00 +0900
categories: [Frontend, Next.js]
tags: [nextjs, image, custom-loader]
---

{% include image-optimization-series.html current=3 %}

## 요구사항

- `<Image>`의 클라이언트 최적화(srcset/lazy/CLS)는 유지
- `/_next/image` 서버 프록시는 우회
- 쿠키 인증은 브라우저 → 백엔드 직접 호출로 해결

## 선택지

| 옵션 | 동작 | 결과 |
|---|---|---|
| `unoptimized` | 프록시 스킵 | srcset, lazy, 포맷 변환 전부 꺼짐. 탈락 |
| 미들웨어 쿠키 우회 | `/_next/image` 요청에 쿠키 주입 | 이중 처리/캐시 분산 그대로. 탈락 |
| **Custom Loader** | URL 생성 함수 주입 | srcset 유지 + 프록시 우회. **채택** |

## 구현

```ts
export const streamFileLoader: ImageLoader = ({ src, width, quality }) => {
  const params = new URLSearchParams();
  params.set('w', String(width));
  if (quality) params.set('q', String(quality));
  return `${src}?${params.toString()}`;
};
```

```ts
// next.config.mjs
images: {
  loader: 'custom',
  loaderFile: './src/lib/image/streamFileLoader.ts',
}
```

결과:

```
GET /api/files/stream/123?w=128 → 백엔드 (쿠키 동봉) → 200, webp
```

`/_next/image`는 경로에서 사라졌다.

## 결과

| 문제 | 해결 |
|---|---|
| 쿠키 미전달 | 브라우저 직접 호출 → 쿠키 자동 동봉 |
| 이중 처리 | Next.js 서버 미개입 |
| 캐시 분산 | 백엔드 + 브라우저 HTTP 캐시 두 곳으로 정리 |
| srcset/lazy/CLS | 그대로 유지 |

## 핵심

> 프레임워크 기본 동작이 제약과 충돌할 때, "끄는 옵션"이 아니라 "부분 교체 지점"을 먼저 찾는다. `unoptimized`로 통째로 끄면 같이 쓰고 싶던 기능까지 잃는다.
