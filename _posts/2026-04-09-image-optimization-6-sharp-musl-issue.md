---
title: "이미지 최적화 (6) sharp가 Alpine에서 안 돌아간 이유"
date: 2026-04-09 09:00:00 +0900
categories: [Infra, Docker]
tags: [nextjs, sharp, docker, alpine, musl, glibc, debugging]
---

{% include image-optimization-series.html current=6 %}

## 증상

dev 배포 직후 모든 이미지 요청 500. 로컬에서는 정상.

## 오진 경로

| 가설 | 결과 |
|---|---|
| 쿠키 인증 미전달 | 쿠키 정상 |
| upstream API 에러 | API 정상 |
| content-type 매칭 | 수정했으나 500 유지 |

## 사용자 영향 차단 먼저

디버깅 장기화에 대비. sharp 실패 시 원본 스트림 fallback 추가 → 배포. 화면은 뜨지만 전 요청이 fallback = 최적화 0회.

## 진짜 원인: `kubectl logs`

```
Error: Could not load the "sharp" module using the linuxmusl-x64 runtime
```

sharp는 `libvips` C 라이브러리의 네이티브 바인딩이다. OS × CPU × libc 조합마다 별도 바이너리.

```
[GitHub Actions: ubuntu/glibc]     [K8s Pod: alpine/musl]
  pnpm install                       require('sharp')
  → @img/sharp-linux-x64 (glibc)    → "musl인데 glibc 바이너리뿐"
  → docker build → 이미지 ─────────→ 💥
```

`pnpm install`은 설치 호스트 기준으로 하나만 받는다. CI는 ubuntu(glibc), 런타임은 alpine(musl).

이전에 안 터진 이유: `/_next/image` 빌트인은 sharp를 lazy load. custom route는 top-level import → Next.js file tracing이 glibc 바이너리만 standalone에 복사.

## 해결: `node:20-slim`

```dockerfile
# before
FROM node:20-alpine AS runner
# after
FROM node:20-slim AS runner
```

빌드/런타임 libc를 glibc로 통일. 이미지 +30MB (170→200MB). Node.js 네이티브 생태계(canvas, bcrypt, prisma 등) 대부분 glibc 가정이라, sharp만 때우면 동일 삽질 반복.

## 핵심

- `package.json`은 JS 의존성이 아니라 **바이너리 의존성**일 수 있다. `*.node` 파일이 있으면 빌드/실행 환경의 OS/libc/CPU를 맞춰야 한다.
- "로컬에서 되는데요"는 환경이 문제를 숨기고 있다는 증거.
- 500을 만나면 앱 로그 전에 `kubectl logs`가 1순위.
