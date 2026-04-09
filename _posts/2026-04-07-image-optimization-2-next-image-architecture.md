---
title: "이미지 최적화 (2) /_next/image 동작 구조"
date: 2026-04-07 11:00:00 +0900
categories: [Frontend, Next.js]
tags: [nextjs, image, optimization]
---

{% include image-optimization-series.html current=2 %}

## `<img>` vs `<Image>`

| | `<img>` | `<Image>` |
|---|---|---|
| src | 그대로 요청 | 가공 |
| srcset | 수동 | 자동 생성 (DPR, viewport) |
| lazy load | 수동 | 기본 |
| CLS 방지 | 수동 | 기본 |
| 이미지 가공 | 없음 | `/_next/image` 프록시로 리사이즈/WebP |

## `/_next/image` 동작

`<Image src="/api/files/stream/123" width={100} />` 사용 시 실제 요청:

```
/_next/image?url=%2Fapi%2Ffiles%2Fstream%2F123&w=256&q=75
```

Next.js 서버가 하는 일:

1. `url` 파라미터의 원본을 fetch (프록시)
2. `sharp`로 리사이즈 + WebP 변환
3. `.next/cache/images/`에 디스크 캐시
4. `Cache-Control` 헤더와 함께 응답

## 첫 시도 — 실패

```tsx
<Image src={`/api/files/stream/${fileId}`} width={100} height={100} />
```

결과: **401 / 403**.

`/_next/image`는 **Next.js 서버가** 백엔드를 fetch 한다. 브라우저 쿠키를 들고 가지 않는다. 1편에서 선택한 쿠키 인증과 안 맞는다.

정리하면 세 가지 문제:

1. **쿠키 미전달** — 인증 충돌
2. **이중 처리** — 백엔드도 리사이즈 가능한데 Next.js가 또 리사이즈
3. **캐시 분산** — 백엔드 캐시 + Next.js 캐시 이중화

## 핵심

> `<Image>`의 가치는 리사이즈가 아니라 srcset/lazy/CLS 등 클라이언트 메타데이터 생성이다. 서버 기능과 프론트 기능은 분리 가능하다.
