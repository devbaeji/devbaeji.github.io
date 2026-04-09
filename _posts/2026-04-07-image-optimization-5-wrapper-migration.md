---
title: "이미지 최적화 (5) 공통 래퍼와 마이그레이션 — 보존이 곧 리팩터링"
date: 2026-04-07 14:00:00 +0900
categories: [Frontend, Next.js]
tags: [nextjs, image, refactoring, migration]
---

> **📚 시리즈 안내**
> - (1) [왜 이미지에 인증이 필요한가 — CDN 대신 선택한 길]({% post_url 2026-04-07-image-optimization-1-auth-need %})
> - (2) [`/_next/image` 뜯어보기]({% post_url 2026-04-07-image-optimization-2-next-image-architecture %})
> - (3) [Custom Loader를 선택하기까지]({% post_url 2026-04-07-image-optimization-3-custom-loader %})
> - (4) [레티나와 imageSizes]({% post_url 2026-04-07-image-optimization-4-retina-imagesizes %})
> - **(5) 공통 래퍼와 마이그레이션 — 보존이 곧 리팩터링** ← 현재 글

## 마지막 퍼즐: 어떻게 강제할까?

지난 글에서 4가지 토큰(xsmall/small/medium/large)을 정했어요. 이제 문제는 "이걸 코드에서 어떻게 일관되게 쓰게 할 것인가"였어요.

### 옵션: 유틸 함수 vs 래퍼 컴포넌트

처음엔 유틸 함수를 떠올렸어요. 사이즈 토큰을 `width` 숫자로 풀어주는 함수요.

```ts
const w = thumbnailWidth('small'); // 100
<Image width={w} height={w} ... />
```

근데 이러면 강제력이 약했어요. 누군가 유틸을 안 쓰고 그냥 숫자를 적어버릴 수 있고, `loader`도 매번 따로 임포트해서 넣어야 하고요. 결정적으로 — 토큰의 의미를 코드에서 한눈에 못 봐요.

그래서 **얇은 래퍼 컴포넌트**로 가기로 했어요.

```tsx
// ThumbnailImage.tsx
type Props = Omit<ImageProps, 'loader'> & {
  size: 'xsmall' | 'small' | 'medium' | 'large';
};

export function ThumbnailImage({ size, ...rest }: Props) {
  return <Image loader={streamFileLoader} {...rest} />;
}
```

`size` 프롭은 받지만 폭/높이 값을 강제로 덮어쓰지는 않아요. 왜냐면 박스 크기는 부모 레이아웃마다 달라야 하거든요. `size` 프롭은 의미 표시이자 코드 리뷰 시 의도 전달용으로 두고, 실제 픽셀은 `width`/`height` 또는 부모 박스가 정해요. 토큰별 픽셀 후보군은 4편에서 정한 `imageSizes`가 알아서 골라줘요.

### app-commons에 안 둔 이유

우리 모노레포에는 `@app/commons`라는 공통 패키지가 있어요. 처음엔 거기에 두려고 했는데, **이 패키지는 Next.js에 묶이면 안 된다**는 원칙이 있었어요. (`next/image`를 import하는 순간 React Native나 일반 Node 환경에서 깨져요.)

그래서 commons에는 **토큰 상수와 타입**만 두고, 컴포넌트 자체는 각 Next.js 앱(`apps/web`, `apps/worker`) 안에 두기로 했어요. 같은 컴포넌트가 두 군데에 거의 그대로 있는 게 마음에 살짝 걸렸지만, 이게 바운더리를 지키는 비용이라고 생각했어요.

## 마이그레이션의 원칙: "보존"

여기서부터가 진짜 깨달음이었어요. 처음엔 단순히 "기존 `<img>`를 `<ThumbnailImage>`로 바꾸면 끝"이라고 생각했거든요. 그런데 작업하다보니 사고가 났어요.

### 사건 1: 채팅 이미지가 뜬금없이 거대해짐

채팅 메시지의 이미지 첨부 영역을 바꿀 때였어요. 원래 코드는 이런 모양이었어요.

```tsx
<div className="size-25"> {/* 100×100 박스 */}
  <img src={url} className="h-full w-full object-cover" />
</div>
```

저는 이걸 이렇게 바꿨어요.

```tsx
<div className="size-25">
  <ThumbnailImage size="small" src={url} fill className="object-cover" />
</div>
```

`fill` 프롭이 있으면 부모를 가득 채워주니까 깔끔할 거라고 생각했거든요. 결과는… 화면 절반을 잡아먹는 거대한 채팅 이미지였어요. 😅

원인은 `fill` 프롭이 **부모에 `position: relative`가 있어야** 동작한다는 거였어요. 부모는 그냥 `size-25`만 있었고요. 처음엔 "그럼 부모에 `relative`를 추가하자" 했는데, 같이 보던 분이 따끔하게 짚어주셨어요.

> "기존엔 `relative` 없이도 멀쩡했는데, 왜 추가해야만 하는 거예요? 기존 레이아웃이 달라지면 안 돼요. 픽셀 값만 토큰으로 컨트롤하는 거잖아요."

이 한마디가 머리를 망치로 친 느낌이었어요. 제가 했어야 할 건 **`<img>`를 `<Image>`로 갈아끼우는 것뿐**이었어요. 부모의 클래스에 손을 대는 순간, 그건 마이그레이션이 아니라 **의도하지 않은 리팩터링**이에요. 사이드 이펙트가 어디까지 갈지 모르고요.

그래서 `fill`을 버리고 명시적인 `width`/`height`로 돌아왔어요.

```tsx
<div className="size-25">
  <ThumbnailImage
    size="small"
    src={url}
    width={100}
    height={100}
    className="h-full w-full object-cover"
  />
</div>
```

부모 레이아웃은 손 안 댔어요. 박스 크기도 그대로, 전체 페이지 어디에서도 1픽셀도 안 움직였어요. 마이그레이션이 이래야 하는 거였어요.

### 사건 2: `unoptimized` 함정

워커앱에서 공지사항 첨부파일 썸네일을 바꿨어요. 그런데 네트워크 탭을 봤더니 `?w=` 쿼리가 안 붙어 있었어요. 그러니까 백엔드는 원본을 그대로 내려주고 있었던 거예요. 분명 `<ThumbnailImage>`로 바꿨는데?

원인은 한 줄이었어요.

```tsx
<Image unoptimized src={...} />
```

이전 작업자가 `/_next/image`가 401 에러를 내니까 임시로 `unoptimized`를 붙여뒀던 거예요(=3편에서 옵션 A로 검토했다 버린 그것). 그런데 `unoptimized`는 **loader를 통째로 우회해버려요**. 우리가 만든 `streamFileLoader`도 안 타요. 그래서 srcset도 없고, `?w=`도 없고, 그냥 원본이 가요.

`unoptimized`를 떼고 `<ThumbnailImage size="xsmall">`로 갈아끼우니 즉시 해결됐어요. **"loader를 정말 타고 있는지"** 는 마이그레이션할 때마다 네트워크 탭으로 확인해야 한다는 교훈이 남았어요.

## 캐싱이 정말 잘 되고 있는지 검증

마이그레이션이 끝났으니 캐시가 의도대로 동작하는지도 확인해야 했어요. 체크리스트를 만들어서 하나씩 봤어요.

- ✅ **요청 URL에 `?w=` 쿼리가 붙는가?** (붙으면 loader가 동작 중)
- ✅ **응답 body 사이즈가 원본보다 작은가?** (작으면 백엔드 리사이즈가 동작 중)
- ✅ **같은 페이지를 새로고침하면 두 번째에는 304 또는 disk cache?** (브라우저 캐시 OK)
- ✅ **Cache-Control 헤더에 적절한 max-age가 있는가?**
- ✅ **레티나 노트북과 일반 모니터에서 다른 사이즈를 받는가?** (DPR 분기 OK)
- ✅ **size 토큰별로 캐시가 독립적인가?** small → medium 토글 시 둘 다 캐시에 남는가

전부 통과했어요. 처음으로 마음이 놓였어요.

## 그리고 남은 일들

이번 작업으로 끝난 게 아니에요. 작업하면서 새로 나온 후속 과제들을 적어둬요.

- **공지사항 상세 페이지의 이미지 프리뷰 모달** — 이번에 `<ThumbnailImage>`로 바꾸면서 클릭 시 ImageViewer로 띄우는 로직도 같이 정리했어요. 이미지만 골라서 인덱스를 다시 매겨주는 부분이 까다로웠어요.
- **30장 일괄 업로드 부하 테스트** — 출퇴근 보고서에서 사진을 30장 한 번에 올리는 시나리오가 생겼어요. 리사이즈/캐시 쪽은 검증했지만, 업로드 자체의 동시성과 백엔드 부하는 별개의 일이에요. 이건 별도 작업으로 분리.
- **`FileValidationException` 500 버그** — 마이그레이션과 직접 관계는 없지만 작업 도중에 발견했어요. `GlobalExceptionHandler`에 핸들러가 없어서 모든 검증 실패가 500으로 떨어지고 있더라고요. 별도 티켓으로 등록해뒀어요.
- **`xlarge` 토큰?** — 디자이너분이 갤러리 모달에 좀 더 큰 사이즈가 필요하다고 하시면 그때 추가할 예정. 미리 만들지 않기로 했어요.

## 마치며 — 5편의 회고

이 시리즈를 시작할 때 풀려던 문제는 단순했어요. "썸네일이 너무 무거워요." 그런데 막상 들어가보니, 이 한 문장 뒤에는 인증 모델의 선택, Next.js 내부 동작의 이해, 디자이너분과의 토큰 합의, 그리고 **"마이그레이션은 보존이지 리팩터링이 아니다"** 라는 원칙까지 줄줄이 엮여 있었어요.

특히 사건 1에서 들었던 한마디 — "기존 레이아웃이 달라지면 안 돼요" — 가 이번 작업에서 가장 크게 남은 배움이에요. 코드를 더 좋게 만들고 싶다는 욕심이 마이그레이션의 안전성을 망가뜨리는 순간이 있다는 걸요. 다음에 비슷한 일을 할 때, 손을 대기 전에 한 번 더 멈춰서 "이건 마이그레이션의 범위인가, 아니면 리팩터링의 범위인가?" 를 물어볼 수 있게 됐어요.

긴 시리즈 읽어주셔서 감사합니다. 다음 작업기에서 또 만나요!
