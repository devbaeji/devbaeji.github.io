---
title: "이미지 최적화 (5) 래퍼 컴포넌트와 마이그레이션 사고"
date: 2026-04-07 14:00:00 +0900
categories: [Frontend, Next.js]
tags: [nextjs, image, refactoring, migration]
---

{% include image-optimization-series.html current=5 %}

## 과제

4편에서 정한 토큰을 코드에서 강제해야 한다. `<Image width={123}>` 같은 임의 값이 들어오면 캐시 파편화.

## 래퍼 선택

```tsx
type Props = Omit<ImageProps, 'loader'> & {
  size: 'xsmall' | 'small' | 'medium' | 'large';
};

export function ThumbnailImage({ size, ...rest }: Props) {
  return <Image loader={streamFileLoader} {...rest} />;
}
```

loader 주입을 한 곳에서 관리 + 타입으로 토큰 강제.

모노레포에서 `@app/commons`는 React Native에서도 쓰이므로 `next/image` import 불가. commons에는 토큰 상수/타입만, 래퍼는 각 Next.js 앱에 배치.

## 마이그레이션 사고 2건

### 사고 1: `fill` + `position: relative` 누락

```tsx
// 기존 — 정상 동작
<div className="size-25">
  <img src={url} className="h-full w-full object-cover" />
</div>

// 변경 — 이미지가 화면 절반을 덮음
<ThumbnailImage size="small" src={url} fill className="object-cover" />
```

`fill`은 부모에 `position: relative`를 요구한다. 기존 부모에는 없었다.

팀원 지적: "기존엔 `relative` 없이 멀쩡했는데 왜 추가? 픽셀 값만 토큰으로 바꾸는 작업이잖아요."

→ `fill` 포기. 명시적 width/height로 복귀. **부모 레이아웃 변경 0줄.**

### 사고 2: `unoptimized` 잔재

다른 앱에서 `?w=` 쿼리가 안 붙는 현상.

```tsx
<Image unoptimized src={...} />  // 이전 작업자가 401 회피로 넣은 코드
```

`unoptimized`는 loader 자체를 우회한다(3편). 우리 `streamFileLoader`가 안 탄다.

→ `unoptimized` 제거 + `<ThumbnailImage>` 치환. 체크리스트에 "네트워크 탭에서 `?w=` 확인" 추가.

## 검증 체크리스트

| 항목 | 통과 기준 |
|---|---|
| loader 동작 | 요청 URL에 `?w=` 존재 |
| 리사이즈 | 응답 body < 원본 |
| 브라우저 캐시 | 2회차 304 or disk cache |
| DPR 분기 | 레티나/일반이 다른 `w` 값 |

## 핵심

> 마이그레이션 = 동작 보존 + 구현 교체. 부모 레이아웃, 주변 로직은 건드리지 않는다. 마이그레이션과 리팩터링을 한 PR에서 섞으면 문제 원인을 구분할 수 없다.
