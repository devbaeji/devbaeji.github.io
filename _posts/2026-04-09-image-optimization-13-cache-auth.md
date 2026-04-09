---
title: "이미지 최적화 (13) 캐시 HIT에도 인증이 필요한 이유"
date: 2026-04-09 23:30:00 +0900
categories: [Backend, Security]
tags: [security, auth, cache, nextjs]
---

{% include image-optimization-series.html current=13 %}

## 상황

디스크 캐시가 있으면 origin fetch를 건너뛴다. 그런데 origin fetch를 건너뛰면 **백엔드의 권한 체크도 건너뛴다**.

```
[캐시 HIT] → 디스크에서 읽기 → 응답
              ↑ 백엔드 안 거침
```

캐시 HIT 경로에 인증 체크가 없으면, accessToken 없는 요청도 캐시된 이미지를 받을 수 있다.

## 공격 시나리오

```
1. 정상 사용자가 /stream-files/70?w=960&q=75 요청 → 캐시 생성
2. 비인증 사용자가 같은 URL 요청
3. 캐시 HIT → 권한 체크 없이 이미지 응답
```

워크스페이스/티켓 단위로 접근 제어가 있는 서비스에서 이건 정보 유출이다.

## 방어

```ts
// 캐시 HIT 경로에 accessToken 체크
if (cachePath && accessToken) {
  const cached = await readCachedImage(cachePath);
  if (cached) {
    return new NextResponse(new Uint8Array(cached), {
      headers: {
        'Content-Type': 'image/webp',
        'Cache-Control': 'private, max-age=31536000, immutable',
        'X-Image-Cache': 'HIT',
      },
    });
  }
}
```

`accessToken`이 없으면 캐시 조회 자체를 안 한다. 이후 로직에서 origin fetch → 백엔드 권한 체크를 거친다.

## web의 서명 URL fallback

web은 accessToken 없이 서명 URL(`exp`/`sig`)로 접근하는 경우가 있다 (외부 공유 링크 등).

```ts
if (!accessToken && expires && signature) {
  const verification = verifySignedUrl(fileId, expires, signature);
  if (!verification.valid) {
    return new NextResponse(null, { status: 403 });
  }
}
```

서명 URL 경로에서는 캐시 HIT을 쓰지 않는다. 매번 origin을 거친다.

| 경로 | 캐시 사용 | 이유 |
|---|---|---|
| accessToken 있음 | O | 백엔드 인증 통과한 사용자 |
| 서명 URL | X | 만료/서명 검증이 매 요청 필요 |
| 둘 다 없음 | X | 비인증 → origin에서 401/403 |

## 캐시가 보안 경계를 넘는 순간

캐시는 성능 최적화 도구지만, 인증이 있는 리소스에 적용하면 **보안 경계**가 된다.

```
캐시 없을 때:  요청 → 인증 → 리소스
캐시 있을 때:  요청 → [캐시 HIT?] → 리소스
                       ↑ 인증이 여기에 있어야 함
```

캐시 레이어를 추가하면서 인증 레이어를 건너뛰는 경로가 생기지 않는지 확인하는 것이 핵심.

## 핵심

- 캐시 HIT이 origin을 건너뛴다 = 권한 체크를 건너뛴다. 인증된 사용자만 캐시를 조회할 수 있어야 한다.
- 서명 URL은 만료 시간이 있으므로 캐시와 함께 쓸 수 없다.
- 성능 레이어를 추가할 때마다 "이 경로에서 보안 체크가 빠지지 않는가"를 확인한다.
