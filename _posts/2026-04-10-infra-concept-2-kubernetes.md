---
title: "인프라 개념 정리 (2) 쿠버네티스 — Pod, Deployment, Node, 클러스터"
date: 2026-04-10 15:20:00 +0900
categories: [Infra, Kubernetes]
tags: [kubernetes, pod, deployment, node, cluster]
---

## 전체 구조

```
클러스터
├── Control Plane (API Server, Scheduler, etcd)
└── Node (EC2)
    ├── Pod → 컨테이너
    ├── Pod → 컨테이너
    └── Pod → 컨테이너
```

## Pod

쿠버네티스 최소 실행 단위. 보통 Pod 1개 = 컨테이너 1개다.

Pod에 IP가 할당되고, 쿠버네티스는 Pod 단위로 상태를 관리한다. 재시작되면 IP가 바뀌고 로컬에 저장한 파일도 사라진다. 영구 저장이 필요하면 PVC를 마운트해야 한다.

```
Pod
└── 컨테이너
    ├── /app/apps/web         (코드)
    └── /app/apps/web/cache   (PVC 마운트)
```

## Deployment

Pod를 어떻게 배포하고 유지할지 정의한다.

```yaml
spec:
  replicas: 3
  template:
    spec:
      containers:
        - image: ecr/.../spation-workspace-web:latest
```

- `replicas: 3` — Pod 3개를 항상 유지. 하나 죽으면 자동 재시작
- 새 이미지 배포 시 롤링 업데이트 (무중단)
- 문제 생기면 이전 revision으로 롤백 가능

내부적으로 Deployment → ReplicaSet → Pod 순으로 관리된다. ReplicaSet은 Pod 수를 유지하는 역할이고, 직접 건드릴 일은 거의 없다.

## Node

Pod가 실제로 실행되는 서버. AWS에서는 EC2가 Node다. Scheduler가 자동으로 어느 Node에 Pod를 배치할지 결정한다.

## 배포 흐름

```
GitHub Actions → docker build & push → ECR
ArgoCD → Git 변경 감지 → kubectl apply
Deployment → ReplicaSet이 새 Pod 생성 (롤링) → 기존 Pod 종료
```
