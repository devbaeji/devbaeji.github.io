---
title: "인프라 개념 정리 (3) 쿠버네티스 스토리지 — EBS, EFS, PV, PVC, RWX"
date: 2026-04-10 15:30:00 +0900
categories: [Infra, Kubernetes]
tags: [kubernetes, pvc, pv, ebs, efs, rwx, storage, 개념정리]
---

이미지 캐시를 디스크에 저장하는 작업을 하면서 PVC, EFS, RWX 같은 개념들이 쏟아졌어요.  
처음엔 뭐가 뭔지 몰랐는데 하나씩 정리해봤습니다.

## Pod의 파일 저장 문제

Pod는 일회성이에요. 재시작되면 로컬 파일이 전부 사라져요.

```
Pod 재시작 전: /app/cache/image_1.webp 존재
Pod 재시작 후: /app/cache/ → 비어있음
```

캐시 파일을 Pod 밖에 영구 저장하려면 외부 볼륨이 필요해요.

## PV / PVC

**PV (PersistentVolume)**: 실제 저장소 (EBS, EFS 등)  
**PVC (PersistentVolumeClaim)**: Pod가 저장소를 요청하는 티켓

```
Pod → PVC (요청) → PV (실제 저장소)
```

Pod는 PVC만 알면 돼요. 실제로 어떤 저장소(EBS인지 EFS인지)인지 몰라도 됨.

```yaml
# Pod에서 PVC 마운트
volumes:
  - name: image-cache
    persistentVolumeClaim:
      claimName: web-image-cache-pvc   # PVC 이름만 지정
```

## EBS vs EFS

AWS에서 주로 쓰는 두 가지 스토리지예요.

| | EBS | EFS |
|---|---|---|
| 정식 명칭 | Elastic Block Store | Elastic File System |
| 타입 | 블록 스토리지 | 파일 스토리지 (NFS) |
| AccessMode | **RWO** (ReadWriteOnce) | **RWX** (ReadWriteMany) |
| pod 간 공유 | **불가** | **가능** |
| 속도 | ~1ms | ~5-10ms |
| 비용 | 낮음 | 높음 |
| 비유 | 노트북 내장 SSD | 공유 NAS 드라이브 |

EBS는 하나의 Node에만 붙어요. Pod가 여러 개면 공유 불가.  
EFS는 NFS 기반이라 여러 Node의 여러 Pod에서 동시에 읽고 쓸 수 있어요.

## AccessMode (RWO, RWX, ROX)

| 약자 | 이름 | 의미 |
|------|------|------|
| RWO | ReadWriteOnce | 하나의 Node에서만 읽기/쓰기 |
| RWX | ReadWriteMany | 여러 Node에서 동시 읽기/쓰기 |
| ROX | ReadOnlyMany | 여러 Node에서 읽기만 |

replica가 3개인 Deployment는 Pod가 3개 = 여러 Node에 배치될 수 있어요.  
EBS(RWO)는 하나의 Node에만 붙으니 캐시 공유 불가.  
EFS(RWX)라야 3개 Pod 모두 같은 볼륨을 마운트할 수 있어요.

## 실제 구성

```
Deployment (replica: 3)
├── Pod A (Node 1) ──┐
├── Pod B (Node 2) ──┼── PVC (web-image-cache) → EFS 볼륨 (RWX)
└── Pod C (Node 3) ──┘

Pod A가 /app/cache/70_w960_q75.webp 생성
→ Pod B, C에서 즉시 읽힘
```

```bash
# 운영 PVC 확인
kprod -n production get pvc

NAME                                 STATUS  CAPACITY  ACCESS MODES  STORAGECLASS
spation-workspace-web-image-cache    Bound   5Gi       RWX           efs-sc-nextjs
spation-workspace-worker-image-cache Bound   5Gi       RWX           efs-sc-nextjs
```

`STATUS: Bound` = EFS와 정상 연결  
`ACCESS MODES: RWX` = 여러 Pod 공유 가능

## StorageClass

PVC를 만들 때 어떤 종류의 스토리지를 쓸지 지정하는 것이에요.

```yaml
storageClassName: efs-sc-nextjs   # EFS 기반 StorageClass
```

클러스터에 EFS StorageClass가 미리 등록되어 있어야 해요.  
우리 프로젝트는 본부장님이 EFS CSI 드라이버와 StorageClass를 설정해두셨어요.

## 정리

```
Pod 재시작 → 로컬 파일 사라짐
     ↓ 해결
PVC (PersistentVolumeClaim) 마운트

replica 3개 → 각자 따로 캐시 쌓음 → HIT율 33%
     ↓ 해결
EFS (RWX) → 3개 Pod가 같은 볼륨 공유 → HIT율 정상
```

EBS는 빠르지만 혼자 쓰는 SSD, EFS는 조금 느리지만 여럿이 쓰는 공유 드라이브.  
replica가 2개 이상이면 캐시 공유에 EFS가 필수예요.
