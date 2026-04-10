---
title: "인프라 개념 정리 (2) 쿠버네티스 — Pod, Deployment, Node, 클러스터"
date: 2026-04-10 15:20:00 +0900
categories: [Infra, Kubernetes]
tags: [kubernetes, pod, deployment, node, cluster, 개념정리]
---

도커로 컨테이너를 만들었는데, 운영 환경에서 컨테이너를 어떻게 관리할까요?  
그게 쿠버네티스(k8s)가 하는 일이에요.

## 쿠버네티스가 왜 필요한가?

컨테이너 하나를 서버에서 실행하는 건 도커로 충분해요.  
근데 실제 운영에선 이런 일들이 생겨요:

- 컨테이너가 갑자기 죽었어요 → 누가 살려줘야 해요
- 배포 중에 서비스 중단이 생기면 안 돼요
- 트래픽이 몰리면 컨테이너를 더 띄워야 해요
- 수십 개의 컨테이너를 어떻게 관리하죠?

이걸 다 자동으로 해주는 게 쿠버네티스예요.

## 구조 한눈에 보기

```
클러스터 (Cluster)
├── Control Plane (두뇌)
│   ├── API Server  — 모든 명령을 받는 창구
│   ├── Scheduler   — 어떤 Node에 Pod를 배치할지 결정
│   └── etcd        — 클러스터 상태 저장소
│
└── Node (실제 서버, EC2)
    ├── Pod
    │   └── 컨테이너 (도커 이미지 실행)
    ├── Pod
    └── Pod
```

## Pod

**컨테이너를 감싸는 쿠버네티스의 최소 실행 단위**예요.

보통 Pod 1개 = 컨테이너 1개예요.  
Pod에 IP가 부여되고, 쿠버네티스는 Pod 단위로 관리해요.

```
Pod
└── 컨테이너 (도커 이미지로 실행된 앱)
    └── /app/apps/web (코드)
    └── /app/apps/web/cache (마운트된 PVC)
```

Pod가 죽으면 쿠버네티스가 새 Pod를 자동으로 띄워요.  
단, **Pod는 일회성**이에요 — 재시작되면 IP도 바뀌고 로컬 파일도 사라져요. (PVC에 저장한 것 제외)

## Deployment

**Pod를 어떻게 배포하고 관리할지 정의한 것**이에요.

```yaml
apiVersion: apps/v1
kind: Deployment
spec:
  replicas: 3          # Pod 3개 유지
  template:
    spec:
      containers:
        - image: ecr/.../spation-workspace-web:latest
```

Deployment가 있으면:
- Pod가 3개 항상 유지됨 (죽으면 자동 재시작)
- 새 이미지 배포 시 롤링 업데이트 (무중단)
- 문제 생기면 이전 버전으로 롤백 가능

## ReplicaSet

Deployment가 내부적으로 생성하는 것. Pod 수를 유지해주는 역할이에요.  
직접 건드릴 일은 거의 없고, `kubectl get rs`로 확인하는 정도예요.

```
Deployment
└── ReplicaSet (replicas: 3 유지 담당)
    ├── Pod A
    ├── Pod B
    └── Pod C
```

## Node

**Pod들이 실제로 실행되는 서버**예요. AWS에선 EC2 인스턴스가 Node가 돼요.

```
Node 1 (EC2)          Node 2 (EC2)
├── Pod A             ├── Pod C
└── Pod B             └── Pod D
```

쿠버네티스 Scheduler가 자동으로 어느 Node에 Pod를 배치할지 결정해요.  
Node가 죽으면 그 위의 Pod들이 살아있는 Node로 옮겨져요.

## 클러스터

**Control Plane + Node 여러 대를 묶은 단위**예요.

AWS EKS를 쓰면 Control Plane은 AWS가 관리해줘요.  
우리는 Node(EC2)만 관리하면 돼요.

```
ksd-eks (개발 클러스터)
└── Node들 (t3.medium 등 저사양)

ksd-prod-eks (운영 클러스터)
└── Node들 (t3.xlarge 등 고사양)
```

dev/prod를 클러스터 자체로 분리하면, dev에서 무슨 일이 생겨도 prod에 영향이 없어요.

## 실제 배포 흐름

```
GitHub Actions
→ docker build & push → ECR

ArgoCD (GitOps)
→ Git 변경 감지
→ kubectl apply
→ Deployment 업데이트
→ ReplicaSet이 새 Pod 생성 (롤링 업데이트)
→ 기존 Pod 종료
```

## 정리

| 개념 | 역할 |
|------|------|
| 클러스터 | 전체 k8s 환경 (Control Plane + Node들) |
| Node | Pod가 실행되는 실제 서버 (EC2) |
| Pod | 컨테이너를 감싸는 최소 실행 단위 |
| Deployment | Pod 수 유지 + 롤링 업데이트 정의 |
| ReplicaSet | Deployment가 관리하는 Pod 복제 담당 |
