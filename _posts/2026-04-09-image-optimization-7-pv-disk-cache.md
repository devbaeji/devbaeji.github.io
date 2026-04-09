---
title: "이미지 최적화 (7) EFS PV 캐시 — env 한 줄 누락 디버깅"
date: 2026-04-09 18:00:00 +0900
categories: [Infra, Kubernetes]
tags: [nextjs, kubernetes, efs, pvc, argocd, cache, debugging]
---

{% include image-optimization-series.html current=7 %}

## 문제

파드 재시작마다 sharp 변환 캐시 유실. 매 배포마다 cold cache.

## 구성

replica 다중 → `ReadWriteOnce`(EBS) 불가 → `ReadWriteMany`(EFS) 선택.

```yaml
# PVC
accessModes: [ReadWriteMany]
storageClassName: efs-sc-nextjs
storage: 5Gi

# Deployment patch
mountPath: /app/cache/images
```

ArgoCD sync 후 마운트 정상, 쓰기 가능.

## 증상: `.webp`가 안 쌓임

이미지 요청 발생 중인데 `/app/cache/images`에 파일 없음. 응답 헤더:

```
x-image-cache: MISS
x-image-optimized: true
```

모든 요청이 MISS.

## 오진 → 방향 전환

첫 가설: `.next/cache/images` 경로 문제 → `next.config` 캐시 핸들러 조사.

방향 전환 계기: `X-Image-Cache`는 **Next.js 기본 헤더가 아니다.** 앱이 직접 찍는 커스텀 헤더. 이 앱은 `route.ts`에서 자체 캐시 로직을 돌린다.

코드 확인:

```
process.env.IMAGE_CACHE_DIR → 값 있으면 캐시, 없으면 스킵
```

## 진짜 원인

```
PVC ✅  volumeMount ✅  IMAGE_CACHE_DIR ❌
```

앱이 캐시 경로를 모름 → 매 요청마다 변환만 수행, 저장 안 함.

## 수정: env 한 줄

```yaml
env:
  - name: IMAGE_CACHE_DIR
    value: /app/cache/images   # volumeMount 경로와 반드시 동일
```

양쪽 파일에 상호 참조 주석 추가. 한쪽만 바뀌면 동일 장애 재발.

## 핵심

- **"K8s 정상"과 "기능 정상"은 다른 문제다.** PVC bound, mount 성공, 권한 정상 — 그래도 앱이 그 리소스를 인식하는 접점(env)이 없으면 기능은 죽는다.
- 커스텀 헤더가 디버깅 첫 단서가 됐다. 프레임워크 기본 응답 형태를 알면 "내 코드가 개입한 흔적"을 빠르게 식별할 수 있다.
- mountPath와 IMAGE_CACHE_DIR의 일치는 시스템 어디에도 강제되지 않는다. 주석이 최소 방어.
