---
title: "이미지 최적화 (6) sharp가 Alpine에서 안 돌아가요 — musl vs glibc 삽질기"
date: 2026-04-09 09:00:00 +0900
categories: [Infra, Docker]
tags: [nextjs, sharp, docker, alpine, musl, glibc, debugging]
---

> **📚 시리즈 안내**
> - (1) [왜 이미지에 인증이 필요한가 — CDN 대신 선택한 길]({% post_url 2026-04-07-image-optimization-1-auth-need %})
> - (2) [`/_next/image` 뜯어보기]({% post_url 2026-04-07-image-optimization-2-next-image-architecture %})
> - (3) [Custom Loader를 선택하기까지]({% post_url 2026-04-07-image-optimization-3-custom-loader %})
> - (4) [레티나와 imageSizes]({% post_url 2026-04-07-image-optimization-4-retina-imagesizes %})
> - (5) [공통 래퍼와 마이그레이션 — 보존이 곧 리팩터링]({% post_url 2026-04-07-image-optimization-5-wrapper-migration %})
> - **(6) sharp가 Alpine에서 안 돌아가요 — musl vs glibc 삽질기** ← 현재 글

## 배포했더니 이미지가 안 떠요

시리즈 5편까지 마치고 **custom loader 구조를 개발 서버에 배포**했어요. 로컬에선 잘 되던 게 dev에 올라가자마자 이미지가 전부 깨지더라고요. 콘솔을 보니:

```
GET /stream-files/12345?w=136&q=75  →  500 Internal Server Error
```

모든 `<Image>` 요청이 500. 그냥 전부요.

처음엔 "쿠키 인증이 제대로 안 넘어가나?" 싶어서 인증 쪽을 한참 봤어요. 그런데 쿠키는 정상이었고, API 서버도 멀쩡히 이미지를 내려주고 있었어요. 뭔가 **그 다음 단계**에서 터지는 거더라고요.

## 진단 로그부터 박고 보기

원인을 모르겠으니 일단 route 안에 진단 로그부터 깔았어요.

```ts
// apps/web/src/app/stream-files/[...path]/route.ts
console.error('[stream-files] upstream request failed', {
  path: pathString,
  apiUrl,
  status: response.status,
  // ...
});
```

그러고 content-type 매칭도 의심해봤어요. API가 `image/jpeg; charset=binary` 같이 파라미터 붙여 내려주는 경우가 있는데, 제가 코드에선 `OPTIMIZABLE_TYPES.has(contentType)`로 **완전 일치**만 체크하고 있었거든요.

```ts
// 수정 전
if (OPTIMIZABLE_TYPES.has(contentType)) { ... }

// 수정 후
const baseContentType = (contentType.split(';')[0] ?? '').trim().toLowerCase();
if (OPTIMIZABLE_TYPES.has(baseContentType)) { ... }
```

근데 이걸 고쳐도 500은 그대로였어요. 아, content-type 문제는 아니구나.

## "최적화 실패해도 원본은 보여주자"

디버깅이 길어지니까 일단 **사용자 경험은 살리자** 싶어서 fallback 경로부터 만들었어요.

```ts
if (width && OPTIMIZABLE_TYPES.has(baseContentType)) {
  const fallbackResponse = response.clone();  // 원본 보존
  try {
    const optimized = await sharp(buffer).resize(...).webp(...).toBuffer();
    return new NextResponse(optimized, { ... });
  } catch (error) {
    console.error('[stream-files] image optimization failed', { error });
    // sharp 실패해도 원본 스트림 그대로 내려주기
    return new NextResponse(fallbackResponse.body, { ... });
  }
}
```

배포하고 봤더니 화면이 뜨긴 떠요. 근데 **최적화는 하나도 안 되고 전부 원본**이 내려가는 상황. fallback 로그는 모든 요청마다 찍히고 있었어요.

`console.error`에 찍힌 `error` 객체를 자세히 보니 이런 문구가 있더라고요.

## 진짜 원인: 쿠버네티스 로그를 보고 알았어요

Pod 로그를 타고 들어가 보니까 드디어 진짜 메시지가 나왔어요.

```
⨯ Error: Failed to load external module sharp-20c6a5da84e2135f:
  Error: Could not load the "sharp" module using the linuxmusl-x64 runtime

Possible solutions:
- Ensure optional dependencies can be installed:
    npm install --include=optional sharp
- Ensure your package manager supports multi-platform installation:
    See https://sharp.pixelplumbing.com/install#cross-platform
- Add platform-specific dependencies:
    npm install --os=linux --libc=musl --cpu=x64 sharp
- Consult the installation documentation:
    See https://sharp.pixelplumbing.com/install

    at Context.externalRequire [as x] (.next/server/chunks/[turbopack]_runtime.js:535:15)
    at module evaluation (.next/server/chunks/[root-of-the-server]__908f530d._.js:2:18178)
    ...
```

`linuxmusl-x64 runtime`이라는 단어가 눈에 들어왔어요. "어? 이거 libc 이야기 같은데?"

## 원인 분석: sharp는 순수 JS가 아니었다

sharp는 사실 **순수 JavaScript가 아니에요**. 속도 때문에 내부적으로 `libvips`라는 C 라이브러리를 호출하는 **네이티브 바인딩** 라이브러리거든요. 그래서 `.node` 확장자의 바이너리를 같이 씁니다.

이 바이너리는 **OS + CPU + libc 조합마다 따로 컴파일**되어야 해요. sharp 설치 시 `package.json`에 이렇게 되어 있어요.

```json
"optionalDependencies": {
  "@img/sharp-linux-x64": "...",       // glibc용 (Ubuntu, Debian…)
  "@img/sharp-linuxmusl-x64": "...",   // musl용 (Alpine)
  "@img/sharp-darwin-arm64": "...",    // macOS M1/M2
  ...
}
```

`npm install`이나 `pnpm install`을 실행할 때 **그 컴퓨터의 OS에 맞는 것 하나만** 자동으로 받아와요. 나머지는 optional이니까 스킵.

### 그럼 뭐가 문제였냐면

우리 빌드 파이프라인이 이렇게 돌고 있었어요.

```
[GitHub Actions 러너]              [쿠버네티스 Pod]
ubuntu-latest (glibc)              node:20-alpine (musl)
        │                                  │
        │ pnpm install                     │
        ▼                                  │
node_modules/sharp                         │
  └─ @img/sharp-linux-x64/  ← glibc용만 설치 │
                                           │
        │ next build                       │
        ▼                                  │
.next/standalone/                          │
  └─ node_modules/sharp/    ← glibc 바이너리 복사
        │                                  │
        │ docker build                     │
        └──────────► 이미지 ─────────────► │
                                           │
                                  require('sharp')
                                           ▼
                                  "저는 linuxmusl-x64에서 도는데
                                   linux-x64 바이너리뿐이네요 😢"
```

**빌드는 glibc 위에서, 실행은 musl 위에서** 되고 있었어요. 두 libc는 **ABI가 서로 호환이 안 돼서** 바이너리를 맞바꿔 쓸 수 없어요.

### 왜 지금까지는 안 터졌을까?

예전엔 Next.js 이미지 최적화를 `/_next/image` (Next 빌트인)가 처리했거든요. Next 빌트인은 sharp를 런타임에 lazy load 하는데, 이미지 최적화 요청이 없으면 아예 호출도 안 돼요.

그런데 이번 **custom loader 리팩토링**(시리즈 3편 참고)으로 우리가 직접 만든 `/stream-files` route 안에서 sharp를 `import`하기 시작했어요. Next의 **file tracing**이 "아 이 route는 sharp가 필요하구나" 하고 `.next/standalone`에 `node_modules/sharp`를 통째로 복사해 넣었어요. 그 복사본이 **glibc 바이너리만** 들어있었던 거고요.

즉, 시리즈 3편이 원인(?)이에요. 😅

## 해결법 비교

sharp 공식 문서랑 여기저기 뒤져서 세 가지 방법을 찾았어요.

### 방법 A: 런타임을 빌드에 맞추기 → `node:20-slim`

Dockerfile의 base image를 바꾸는 거예요.

```dockerfile
# 변경 전
FROM node:20-alpine AS runner

# 변경 후
FROM node:20-slim AS runner
```

딱 한 줄.

- `slim`은 **Debian 기반**이라 **glibc**를 써요.
- GitHub Actions 러너가 Ubuntu(glibc)니까, 런타임도 glibc로 맞추면 바이너리가 그대로 동작해요.

### 방법 B: 빌드에서 musl 바이너리까지 같이 받기

`.npmrc`에 설정을 추가하는 방법도 있어요.

```
# .npmrc
supported-architectures[libc][]=musl
supported-architectures[libc][]=glibc
```

이러면 `pnpm install` 할 때 glibc, musl 바이너리 **둘 다** 다운로드해요. Alpine도 그대로 쓸 수 있고요.

### 방법 C: Docker runtime 단계에서 musl sharp 재설치

```dockerfile
FROM node:20-alpine AS runner
# ... standalone COPY
RUN cd apps/web && npm install --os=linux --libc=musl --cpu=x64 sharp --no-save
```

Alpine 유지하면서 runtime 단계에서 sharp만 다시 설치하는 방법이에요.

### 비교표

| 항목 | A. slim | B. .npmrc | C. runtime install |
|---|---|---|---|
| 변경 복잡도 | ⭐ 1줄 | 중간 | 높음 |
| 미래 확장성 (다른 네이티브 모듈) | ✅ 자동 해결 | ❌ 매번 설정 추가 | ❌ 매번 Dockerfile 수정 |
| 로컬 개발자 영향 | 없음 | macOS에서도 musl 바이너리 다운로드 | 없음 |
| 빌드 파이프라인 영향 | 없음 | `.npmrc` 수정 | Dockerfile 복잡화 |
| 이미지 크기 | +30MB | 0 | sharp 중복분만큼 |
| 런타임 성능 | 동일 | 동일 | 동일 |
| 롤백 난이도 | 1줄 되돌림 | 설정 되돌림 | 여러 줄 되돌림 |

## 저는 A(slim)를 골랐어요

가장 크게 끌린 이유는 **미래 확장성**이었어요.

sharp만 그런 게 아니라, Node.js 생태계의 네이티브 모듈(canvas, bcrypt, prisma engine, puppeteer…) 상당수가 glibc를 기본으로 가정하고 있더라고요. B나 C로 sharp만 해결하면, 나중에 다른 네이티브 모듈 도입할 때 **똑같은 삽질을 또** 해야 해요.

### "30MB 커진다는데 괜찮아요?"

사실 이게 제일 걱정이었어요. 그래서 찾아봤어요.

- **이미지 크기**: 170MB → 200MB (+30MB)
- **빌드 속도**: 동일 (베이스 이미지는 CI 캐시에 잡힘)
- **런타임 성능**: 동일 (Node.js 엔진 자체는 같음)
- **Pull 시간**: +1~3초 (처음 한 번)
- **Pod 시작 시간**: cold start 한 번 +1~2초

결론: **사용자는 전혀 체감 못 해요.** 2026년 기준 30MB는 Docker 이미지 세계에선 '작다'에 가까워요.

### alpine을 왜 쓰고 있었을까?

궁금해서 찾아봤어요. alpine은 수 년 전에 "작고 가볍다"로 유행했어요. 그땐 이미지 크기가 정말 중요했거든요. 그런데:

1. Node.js 생태계는 대부분 **glibc를 가정**해요.
2. musl libc는 DNS resolver, malloc 동작이 살짝 달라서 **미묘한 버그**가 생기기도 해요.
3. 30MB 차이는 이제 무의미해요.

그래서 요즘엔 Node.js Docker 베스트 프랙티스도 **`slim`이나 `distroless`를 권장**하는 추세래요. 특히 네이티브 모듈 쓰면 거의 무조건 slim이에요.

## 한 가지 더: Fallback은 남겨둬요

Dockerfile을 고쳐도 **fallback 로직은 그대로 유지**하기로 했어요. 이유는:

- sharp가 로드되더라도 **corrupt image**, **OOM**, **예상 못 한 포맷** 같은 경우에 변환이 실패할 수 있어요.
- 그때 500을 내려주면 화면이 깨져요. 원본이라도 보여주는 게 훨씬 나아요.

그래서 PR을 두 개로 나눴어요.

1. **Route fallback 개선** — 이미 머지. sharp 변환 실패 시 원본 스트림 폴백. 영구 안전망.
2. **Dockerfile base image 교체** — 근본 원인 해결 (인프라 변경이라 별도 진행).

### Fallback 동작 정리

| 실패 케이스 | 동작 |
|---|---|
| sharp 모듈 load 실패 (musl 문제) | 원본 스트림 200 ✅ |
| sharp 변환 실패 (corrupt/OOM) | 원본 스트림 200 ✅ |
| 최적화 불가능한 MIME (pdf 등) | 원본 그대로 ✅ |
| upstream API 4xx/5xx | 그 상태 그대로 전달 (숨기지 않음) |
| 서명 URL 검증 실패 | 403 (보안상 중요) |
| 예상 못 한 route 예외 | 500 (디버깅 가시성) |

"sharp 최적화만 실패한 경우"에 한해서만 원본으로 폴백하는 거예요. 인증 실패나 upstream 실패까지 다 200으로 바꾸면 그건 **무서운 버그**거든요.

## 배운 것들

이번에 얻은 교훈 세 가지.

### 1. "의존성이 진짜로 의존하는 것"을 봐야 한다

저는 `package.json`에 `"sharp": "^0.34.0"` 적혀 있는 걸 보고 "JS 라이브러리"라고만 생각했어요. 근데 sharp는 실제로는 `libvips`라는 **C 라이브러리 위에서 도는 바인딩**이었어요. 그래서 **실행 환경의 OS, CPU, libc**까지 의존해요.

`node_modules`에 들어가는 것들 중에서 `.node` 파일이 있으면 네이티브 바인딩이에요. 그때부턴 "빌드 환경 = 실행 환경"이 맞는지 신경 써야 해요.

### 2. 로컬에서 잘 되는 게 의심스럽다

로컬(macOS ARM)에선 `@img/sharp-darwin-arm64`가 설치돼서 아무 문제 없이 돌아요. 저는 "코드는 멀쩡한데?"라고 생각했지만, 사실 **로컬이 문제를 숨기고 있던 거**였어요.

CI/CD에서 "빌드되면 OK"도 아니에요. CI 러너(Ubuntu)랑 프로덕션(Alpine)이 또 달라요. **빌드가 성공한다고 런타임도 성공한다는 보장은 없다**는 걸 체감했어요.

### 3. 쿠버네티스 로그를 진작 봤어야 했다

제가 route에 깔아둔 `console.error`는 사실 **rethrown된 에러**만 찍고 있었어요. 진짜 원인 메시지("linuxmusl-x64 runtime")는 Next.js 내부에서 찍히는데, 이건 **Pod의 stdout**으로만 나오고 있었거든요.

500 에러를 만났을 때 먼저 했어야 할 건:

1. `kubectl logs <pod>` 먼저 보기
2. 그 다음에 route 디버깅

저는 반대로 했어요. 🙃

## 마무리

custom loader로 갈아타면서 예상 못 한 인프라 이슈를 만났어요. 코드는 건드리지 않고 **Dockerfile 한 줄**만 바꾸면 되는 문제였는데, 거기까지 가는 길이 꽤 멀었어요.

돌이켜보면:

- **증상**: 500 에러
- **1차 의심**: 인증 / content-type → 아니었음
- **2차 방어**: fallback 추가 → 화면은 뜸, 최적화는 안 됨
- **3차 추적**: Pod 로그에서 진짜 원인 발견
- **근본 해결**: base image 교체 (승인 대기 중)
- **영구 안전망**: fallback 로직은 유지

프론트엔드 작업하다가 **libc**라는 단어까지 만날 줄은 몰랐어요. 시리즈의 엔딩이 이럴 줄이야. 😅

그래도 이번에 Docker 베이스 이미지 선택 기준 하나, "네이티브 모듈을 쓴다면 glibc 계열(slim)을 쓰자"를 확실히 배운 것 같아요. 다음에 비슷한 삽질은 안 할 수 있겠죠… 아마도요.
