---
title: "이미지 최적화 (4) 레티나 × imageSizes — 디자인 토큰으로 캐시 키 축소"
date: 2026-04-07 13:00:00 +0900
categories: [Frontend, Next.js]
tags: [nextjs, image, retina, design-token]
---

{% include image-optimization-series.html current=4 %}

## 관찰

`width={100}`인데 네트워크에서 `?w=256`이 나간다.

## 원인: DPR × imageSizes

레티나(DPR 2)는 CSS 100px 박스에 200 물리 픽셀이 필요하다.

`<Image>`는 srcset에 1x/2x를 자동 생성하고, `w=` 후보값은 `imageSizes` 배열에서 선택된다.

```js
// Next.js 기본값 — 후보 8개
imageSizes: [16, 32, 48, 64, 96, 128, 256, 384]
```

100 요청 → 1x=128, 2x=256. 후보가 8개라 캐시가 8방향으로 갈린다.

## 결정: 디자인 토큰과 1:1 매핑

디자인 시스템에서 실제로 쓰는 썸네일 4종:

| 토큰 | CSS 폭 | 1x | 2x |
|---|---|---|---|
| xsmall | 80 | 80 | 160 |
| small | 100 | 100 | 200 |
| medium | 160 | 160 | 320 |
| large | 320 | 320 | 640 |

```js
images: {
  imageSizes: [80, 100, 160, 200, 320, 640],
  qualities: [75],
}
```

후보 8 → 6. 모든 값이 디자인 시스템이 쓰는 크기. quality도 단일값으로 통일.

## 검증

- 일반 모니터 + `size="small"` → `?w=100`
- 레티나 + `size="small"` → `?w=200`
- 레티나 + `size="large"` → `?w=640`

전부 6개 후보군 안.

## 핵심

> 자동 생성되는 후보군은 "제약해야 하는 설계 표면"이다. 디자인 시스템이 실제로 쓰는 값만 남기는 것이 캐시 효율의 출발점.
