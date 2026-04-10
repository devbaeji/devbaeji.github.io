---
title: "인프라 개념 정리 (3) 쿠버네티스 스토리지 — EBS, EFS, PV, PVC, RWX"
date: 2026-04-10 15:30:00 +0900
categories: [Infra, Kubernetes]
tags: [kubernetes, pvc, pv, ebs, efs, rwx, storage]
---

이미지 디스크 캐시 작업(PRDT-3952)을 하면서 제대로 이해하게 된 개념들이다.

## Pod의 파일은 재시작하면 사라진다

Pod는 재시작되면 로컬 파일이 전부 날아간다. 캐시를 Pod 밖에 영구 저장하려면 외부 볼륨이 필요하다.

## PV / PVC

- **PV (PersistentVolume)**: 실제 저장소 (EBS, EFS 등)
- **PVC (PersistentVolumeClaim)**: Pod가 저장소를 요청하는 선언

Pod는 PVC 이름만 알면 된다. 실제 저장소가 EBS인지 EFS인지 몰라도 동작한다.

```yaml
volumes:
  - name: image-cache
    persistentVolumeClaim:
      claimName: web-image-cache-pvc
```

## EBS vs EFS

| | EBS | EFS |
|---|---|---|
| 타입 | 블록 스토리지 | 파일 스토리지 (NFS) |
| AccessMode | RWO | **RWX** |
| pod 간 공유 | 불가 | 가능 |
| 지연 | ~1ms | ~5-10ms |

EBS는 하나의 Node에만 붙는다. replica가 2개 이상이면 여러 pod가 같은 EBS를 마운트할 수 없다.

EFS는 NFS 기반이라 여러 Node의 여러 pod에서 동시에 읽고 쓸 수 있다.

## AccessMode

| 약자 | 의미 |
|------|------|
| RWO | 하나의 Node에서만 읽기/쓰기 |
| RWX | 여러 Node에서 동시 읽기/쓰기 |
| ROX | 여러 Node에서 읽기만 |

replica 3개 Deployment는 pod 3개가 서로 다른 Node에 배치될 수 있다. EBS(RWO)로는 캐시 공유 불가. EFS(RWX)여야 3개 pod 모두 같은 볼륨을 마운트할 수 있다.

## 실제 운영 PVC

```bash
kprod -n production get pvc

NAME                                 STATUS  CAPACITY  ACCESS MODES  STORAGECLASS
spation-workspace-web-image-cache    Bound   5Gi       RWX           efs-sc-nextjs
spation-workspace-worker-image-cache Bound   5Gi       RWX           efs-sc-nextjs
```

web/worker 각각 PVC를 분리했다. 하나로 공유할 수도 있지만, 앱 독립성과 장애 격리를 위해 분리하는 게 맞다.

## StorageClass

PVC 생성 시 어떤 스토리지를 쓸지 지정한다. `efs-sc-nextjs`는 EFS CSI 드라이버 기반으로 미리 등록된 StorageClass다.

```yaml
storageClassName: efs-sc-nextjs
```
