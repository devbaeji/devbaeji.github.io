---
title: "Next.js SSR에서 CSR API 클라이언트 사용 시 발생하는 문제와 해결 방안"
date: 2025-12-24 13:00:00 +0900
categories: [Frontend, Next.js]
tags: [nextjs, ssr, csr, api, troubleshooting]
---

## 문제 상황

초대 링크 페이지를 개발하고 있었는데, 로컬에서는 잘 되던 게 개발 서버에 배포하니까 갑자기 안 되는 거다.

에러 메시지는 `Invalid URL`. 화면에는 "초대 링크가 유효하지 않습니다"라고 떴다.

분명 로컬에서는 됐는데... 뭐가 문제지?

---

## 원인을 찾아보자

### 일단 API 클라이언트 구조부터

우리 프로젝트는 API 클라이언트가 SSR/CSR 용도로 나뉘어 있었다.

```typescript
// client.ts (CSR용 - 브라우저에서 ALB 통해 외부 통신)
const baseUrl = process.env.NEXT_PUBLIC_EXTERNAL_API_URL ?? '';

// server-client.ts (SSR용 - K8s 내부 통신)
const baseUrl = process.env.K8S_INTERNAL_API_URL ?? process.env.NEXT_PUBLIC_EXTERNAL_API_URL ?? '';
```

| 클라이언트 | 용도 | 환경변수 |
|-----------|------|---------|
| `client.ts` | CSR (브라우저) | `NEXT_PUBLIC_EXTERNAL_API_URL` |
| `server-client.ts` | SSR (서버) | `K8S_INTERNAL_API_URL` |

### 문제의 코드

근데 초대 페이지가 **Server Component(SSR)**인데, CSR용 `client.ts`를 쓰고 있었다.

```typescript
// userInvitationsService.ts
import { getApiClient } from './client';  // ← 어? CSR용인데?

const { configuration } = getApiClient();
```

### 환경별로 뭐가 달랐나

| 환경 | `NEXT_PUBLIC_EXTERNAL_API_URL` | 실제 호출 | 결과 |
|------|-------------------------------|----------|------|
| 로컬 | `http://localhost:30001` | `http://localhost:30001/api/...` | ✅ 됨 |
| 배포 | 미설정 (`undefined`) | `/api/...` | ❌ 안됨 |

로컬에서는 `.env.local`에 URL이 설정되어 있어서 된 거였다.

### 근데 왜 배포 환경에는 설정 안 했지?

브라우저에서 `/api/*`로 요청하면 ALB가 알아서 백엔드로 라우팅해주는 구조라서, 굳이 설정 안 해도 됐던 거다.

```
브라우저 → /api/* 요청 → ALB가 백엔드로 라우팅 → 잘 됨
```

근데 **SSR은 K8s Pod 안에서 돌아간다**. ALB를 안 거친다.

```
K8s Pod (SSR) → /api/* 요청 → 어디로 보내야 하지...? → Invalid URL
```

Node.js는 브라우저처럼 상대 경로에 도메인을 자동으로 붙여주지 않는다. 그래서 터진 거다.

---

## 해결

### 일단 급한 불부터 끄자: Client Component로 변경

Server Component를 Client Component로 바꿔서 브라우저에서 API 호출하게 했다.

```typescript
// Before: Server Component
export default async function InvitePage({ params }) {
  const validation = await userInvitationsService.validateInviteToken(token);
  // ...
}

// After: Client Component
'use client';

export function InvitePageClient({ token }) {
  useEffect(() => {
    userInvitationsService.validateInviteToken(token)
      .then(setValidation);
  }, [token]);
  // ...
}
```

일단 이렇게 하니까 동작은 했다. 근데 이게 맞나?

### 근본적으로는: API 클라이언트를 통합하자

생각해보니까, SSR이든 CSR이든 같은 API 호출하는 건데 왜 클라이언트를 분리해놨지? 그냥 환경 보고 알아서 판단하면 되잖아.

```typescript
// client.ts (통합)
const getBaseUrl = () => {
  // SSR (Node.js 환경) - K8s 내부 네트워크로 API 호출
  if (typeof window === 'undefined') {
    return process.env.K8S_INTERNAL_API_URL ?? process.env.NEXT_PUBLIC_EXTERNAL_API_URL ?? '';
  }
  // CSR (브라우저 환경) - ALB를 통해 외부에서 API 호출
  return process.env.NEXT_PUBLIC_EXTERNAL_API_URL ?? '';
};
```

| 환경 | `typeof window` | 사용되는 URL |
|------|-----------------|-------------|
| SSR (K8s Pod) | `undefined` | `K8S_INTERNAL_API_URL` |
| CSR (브라우저) | `object` | 상대 경로 → ALB 라우팅 |

이렇게 하면 개발자가 "이건 SSR이니까 server-client 써야지~" 이런 거 신경 안 써도 된다.

---

## 정리

| 구분 | 분리 방식 | 통합 방식 |
|------|----------|----------|
| 클라이언트 파일 수 | 2개 | 1개 |
| 개발자 실수 가능성 | 높음 (이번처럼) | 낮음 |
| Server Component 사용 | import 조심해야 함 | 그냥 쓰면 됨 |

---

## 느낀 점

1. **SSR이랑 CSR은 실행되는 곳이 다르다**
   - SSR: K8s Pod 안에서 실행됨 → ALB 안 거침
   - CSR: 브라우저에서 실행됨 → ALB 거쳐서 백엔드 접근

2. **상대 경로는 브라우저에서만 먹힌다**
   - 브라우저: `/api/...` → 알아서 현재 도메인 붙여줌
   - Node.js: `/api/...` → 이게 뭔데? → 에러

3. **같은 API 호출하는데 클라이언트 분리할 필요 있나?**
   - 환경 자동 판단하게 만들면 실수할 일이 없다
   - `typeof window === 'undefined'`면 서버, 아니면 브라우저

로컬에서 되니까 당연히 될 줄 알았는데, 배포 환경이랑 로컬 환경이 다르다는 걸 다시 한번 느꼈다.
