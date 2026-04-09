---
title: "이미지 최적화 (3) Custom Loader를 선택하기까지"
date: 2026-04-07 12:00:00 +0900
categories: [Frontend, Next.js]
tags: [nextjs, image, custom-loader]
---

> **📚 시리즈 안내**
> - (1) [왜 이미지에 인증이 필요한가 — CDN 대신 선택한 길]({% post_url 2026-04-07-image-optimization-1-auth-need %})
> - (2) [`/_next/image` 뜯어보기]({% post_url 2026-04-07-image-optimization-2-next-image-architecture %})
> - **(3) Custom Loader를 선택하기까지** ← 현재 글
> - (4) [레티나와 imageSizes]({% post_url 2026-04-07-image-optimization-4-retina-imagesizes %})
> - (5) [공통 래퍼와 마이그레이션]({% post_url 2026-04-07-image-optimization-5-wrapper-migration %})

## 정리해보면 문제는 세 가지였어요

지난 글에서 `<Image>`를 그냥 갖다 붙였더니 무너졌다고 했잖아요. 며칠 끙끙대다가 노트에 적어보니 문제가 셋으로 정리되더라고요.

1. **쿠키가 안 따라가요.** `/_next/image`의 서버가 우리 백엔드를 fetch 할 때, 사용자 브라우저의 쿠키를 자동으로 들고 가지 않아요. 그래서 401/403이 나요.
2. **이중 처리예요.** 백엔드 이미 리사이즈 다 해주는데, `/_next/image`가 또 리사이즈해요. CPU와 디스크가 두 번 나가요.
3. **캐시가 갈라져요.** 백엔드 캐시 따로, Next.js 캐시 따로. 둘이 안 만나요.

그러니까 우리에게 진짜 필요한 건 "Next.js가 이미지 자체를 가공해주는 능력"이 아니라 **"Next.js가 디바이스에 맞춰 적절한 URL을 골라주는 능력"** 이었어요. srcset, lazy, blur, CLS 방지 같은 거요.

## 옵션 비교

머릿속에 있던 선택지들을 하나씩 따져봤어요.

### 옵션 A: `unoptimized` 프롭

`<Image unoptimized />`를 쓰면 `/_next/image` 프록시를 통째로 건너뛰어요. 깔끔해 보이죠? 그런데 동시에 **srcset, 자동 포맷 변환, 디바이스 픽셀 비율 분기까지 다 같이 꺼져요**. 우리가 원했던 "클라이언트 측 최적화" 자체가 사라져요. 이건 차라리 `<img>`로 돌아가는 거랑 똑같았어요.

> ⚠️ 이거 나중에 사고 한 번 칩니다. (5편에서 등장)

### 옵션 B: 미들웨어로 쿠키 우회

Next.js 미들웨어에서 `/_next/image` 요청을 가로채서 쿠키를 강제로 붙여주는 방법도 있었어요. 가능은 한데 — 위 1번 문제만 풀 뿐이고, **2번(이중 처리)과 3번(캐시 분리)은 그대로**예요. 게다가 미들웨어에 이런 우회 로직이 들어가면 다음 사람이 보고 "이게 뭐지" 할 게 뻔했어요.

### 옵션 C: Custom Loader

문서를 더 보다가 `loader` 프롭이라는 게 눈에 들어왔어요. `<Image>`에 함수를 넘기면, 그 함수가 **각 srcset 후보의 URL을 직접 만들 수 있어요**. 즉, "Next.js가 srcset은 만들어줘. 그런데 각 URL은 내가 정할게"가 가능해요.

```ts
type ImageLoader = (params: { src: string; width: number; quality?: number }) => string;
```

이걸 보고 나서야 머릿속이 정리됐어요. 우리가 원하는 게 정확히 이거였잖아요.

- 백엔드의 리사이즈 능력을 그대로 쓰고 싶다 → 우리가 URL을 만든다
- 쿠키가 자동으로 가야 한다 → 브라우저가 직접 우리 백엔드를 호출하면 됨 (`/_next/image`를 거치지 않음)
- 캐시가 한 곳이면 좋겠다 → 백엔드의 리사이즈 결과만 캐시되고, 브라우저는 그걸 다시 캐시
- srcset/lazy/blur는 살리고 싶다 → `<Image>`가 알아서 해줌

## 우리 Custom Loader는 이렇게 생겼어요

```ts
// streamFileLoader.ts
export const streamFileLoader: ImageLoader = ({ src, width, quality }) => {
  // src: "/api/files/stream/123" 같은 우리 백엔드 URL
  const params = new URLSearchParams();
  params.set('w', String(width));
  if (quality) params.set('q', String(quality));
  return `${src}?${params.toString()}`;
};
```

설정에서 한 번만 등록해주면 끝나요.

```ts
// next.config.mjs
images: {
  loader: 'custom',
  loaderFile: './src/lib/image/streamFileLoader.ts',
}
```

이렇게 했더니 브라우저가 만드는 요청이 이렇게 바뀌었어요.

```
GET /api/files/stream/123?w=128 → 백엔드 (쿠키 자동 동봉) → 200, 작은 webp
GET /api/files/stream/123?w=256 → 백엔드 → 200, 조금 더 큰 webp
```

`/_next/image`는 어디에도 없어요. 우리가 원했던 그림이에요.

## 얻은 것들

- ✅ **인증이 자연스럽게 풀려요.** 브라우저 → 백엔드 직접 호출이라 쿠키가 그대로 따라가요. 1편에서 정한 인증 모델과 충돌이 없어요.
- ✅ **이중 처리가 사라져요.** 백엔드가 한 번만 리사이즈하고, Next.js 서버는 이미지 처리에 손을 안 대요.
- ✅ **캐시가 한 줄로 정렬돼요.** 백엔드의 리사이즈 캐시 + 브라우저 HTTP 캐시. 디스크 두 군데에서 같은 일 안 해요.
- ✅ **srcset/lazy/CLS 방지는 그대로 살아요.** `<Image>`의 좋은 점은 다 가져왔어요.

## 그래도 남은 고민

여기서 끝나면 좋겠는데, 한 가지가 마음에 걸렸어요.

`<Image width={100} height={100} />`이라고 적었는데, 실제로 srcset에는 어떤 값들이 들어갈까요? 정확히 100px 한 장만 받을까요? 아니면 200px(레티나용)도 같이 받을까요? 그건 누가 정하는 걸까요?

이걸 모르고 그냥 쓰면, 우리가 "100px만 받으면 돼" 라고 생각해도 실제로는 256px이나 384px 같은 엉뚱한 사이즈를 받고 있을 수도 있어요. 다음 편에서 이 부분 — **`imageSizes`와 레티나** 이야기를 풀어볼게요. 디자이너분과 사이즈 토큰을 어떻게 합의했는지도요.
