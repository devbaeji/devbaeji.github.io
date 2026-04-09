---
title: "이미지 최적화 (14) Multi-pod 캐시 공유 — EFS ReadWriteMany"
date: 2026-04-09 23:45:00 +0900
categories: [Infra, Kubernetes]
tags: [kubernetes, efs, pvc, cache, multi-pod]
---

{% include image-optimization-series.html current=14 %}

## 문제

운영 환경은 pod가 3개다.

```
Pod A: /app/cache/images/70_w960_q75.webp  ← 캐시 생성
Pod B: /app/cache/images/                  ← 파일 없음?
Pod C: /app/cache/images/                  ← 파일 없음?
```

각 pod가 자기 로컬 디스크를 쓰면, 캐시 HIT율이 replica 수에 반비례한다. 3 pod면 최대 HIT율이 33%.

## EBS vs EFS

| | EBS (블록 스토리지) | EFS (파일 스토리지) |
|---|---|---|
| 프로토콜 | 블록 디바이스 | NFS v4 |
| accessModes | ReadWriteOnce | **ReadWriteMany** |
| pod 간 공유 | 불가 | 가능 |
| 지연 | ~1ms | ~5-10ms |
| 비용 | 낮음 | 높음 |

EBS는 하나의 pod에만 붙는다. replica가 2개 이상이면 쓸 수 없다.

## EFS + ReadWriteMany 구성

```yaml
# PVC
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: web-image-cache-pvc
spec:
  accessModes:
    - ReadWriteMany        # 핵심
  storageClassName: efs-sc
  resources:
    requests:
      storage: 5Gi
```

```
Pod A ──┐
Pod B ──┼── EFS 볼륨 (/app/cache/images)
Pod C ──┘
```

Pod A가 캐시를 생성하면, Pod B, C에서 즉시 읽을 수 있다. NFS 기반이라 파일 단위 공유가 된다.

## 동시 쓰기 안전성

3개 pod가 같은 이미지를 동시 요청하면?

```
Pod A: write 70_w960_q75.webp.12345.tmp → rename
Pod B: write 70_w960_q75.webp.67890.tmp → rename
Pod C: read  70_w960_q75.webp            → ?
```

12편에서 다룬 **atomic write**(tmp + rename)가 여기서 빛난다.

- tmp 파일에 `process.pid`가 붙어 충돌 없음
- `rename`은 POSIX 원자적 — Pod C는 이전 파일 또는 완성된 새 파일만 봄
- 마지막 rename이 이김. 어느 쪽이든 완전한 파일이므로 결과는 동일

만약 `writeFile`을 직접 썼다면, Pod C가 Pod A의 반쪽짜리 파일을 읽을 수 있었다.

## EFS 지연과 캐시

EFS는 EBS보다 느리다 (~5-10ms vs ~1ms). 그래도 origin fetch(백엔드 API → S3 → sharp 변환)보다는 훨씬 빠르다.

```
캐시 MISS: origin fetch + sharp 변환 → ~200-500ms
캐시 HIT (EFS): fs.readFile → ~5-10ms
```

40-100배 빠르다. NFS 오버헤드는 무시할 수 있는 수준.

## 검증

```bash
# pod 목록 확인
kubectl -n production get pods -l app=test-app-web

# 3개 pod 모두에서 같은 캐시 파일이 보여야 함
kubectl -n production exec <pod-1> -- ls -lh /app/cache/images
kubectl -n production exec <pod-2> -- ls -lh /app/cache/images
kubectl -n production exec <pod-3> -- ls -lh /app/cache/images
```

동일 파일 목록 = 공유 정상.

## 핵심

- replica가 2개 이상이면 `ReadWriteOnce`(EBS)는 캐시 공유에 쓸 수 없다.
- EFS `ReadWriteMany`로 모든 pod가 같은 볼륨을 마운트하면, 한 pod의 캐시가 전체에 즉시 반영된다.
- 공유 스토리지에서 동시 쓰기가 안전하려면 atomic write가 전제. 12편의 tmp + rename 패턴이 없으면 깨진 파일이 공유된다.
