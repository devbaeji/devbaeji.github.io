---
title: "이미지 최적화 (8) PV 캐시 동작 증명 — 3단 검증법"
date: 2026-04-09 19:00:00 +0900
categories: [Infra, Kubernetes]
tags: [nextjs, kubernetes, efs, cache, debugging, testing]
---

{% include image-optimization-series.html current=8 %}

## 문제

PV에 파일이 쌓이는 것까지 확인. 하지만 "두 번째 요청이 빠르다"만으로는 어떤 캐시가 응답했는지 구분 불가.

```
[브라우저 캐시] → [인메모리] → [PV 디스크] → [sharp 변환]
```

## 검증 1: curl로 브라우저 캐시 배제

```bash
# 1회차 — MISS
curl -sI "https://example.com/stream-files/61?w=1024&q=90" | grep x-image-cache
# x-image-cache: MISS

# 2회차 — HIT
curl -sI "https://example.com/stream-files/61?w=1024&q=90" | grep x-image-cache
# x-image-cache: HIT
```

증명: 쓰기 동작 + 서버까지 도달 후 HIT. 디스크 vs 인메모리는 미구분.

## 검증 2: 파드 재시작으로 인메모리 배제

```bash
kubectl -n develop rollout restart deploy/spation-workspace-worker
kubectl -n develop rollout status deploy/spation-workspace-worker

curl -sI "https://example.com/stream-files/61?w=1024&q=90" | grep x-image-cache
# x-image-cache: HIT
```

재시작 = 프로세스 메모리 초기화. 직후 HIT → 소스는 **PV 디스크뿐**.

## 검증 3: 파일 제거로 의존성 확정

```bash
kubectl -n develop exec <pod> -- mv \
    /app/cache/images/61_w1024_q90.webp \
    /app/cache/images/61_w1024_q90.webp.bak

curl -sI "https://example.com/stream-files/61?w=1024&q=90" | grep x-image-cache
# x-image-cache: MISS
```

파일 유무가 응답에 직접 영향 → 앱이 실제로 그 경로를 참조.

## 체크리스트

| # | 단계 | 배제 레이어 |
|---|---|---|
| 1 | curl로 요청 | 브라우저 |
| 2 | 프로세스 재시작 후 HIT 확인 | 인메모리 |
| 3 | 파일 이동 후 MISS 확인 | 앱 로직 검증 |

## 핵심

> "빠름"은 관찰이고, "PV에서 왔다"는 증명이다. 캐시 레이어를 하나씩 배제해서 "가능한 소스가 하나만 남는" 상태를 만드는 것이 증명.
