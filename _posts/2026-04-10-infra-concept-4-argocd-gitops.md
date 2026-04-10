---
title: "인프라 개념 정리 (4) ArgoCD와 GitOps — 배포를 Git으로 관리한다는 게 뭔 말이야"
date: 2026-04-10 15:40:00 +0900
categories: [Infra, Kubernetes]
tags: [argocd, gitops, kubernetes, deployment, cicd, 개념정리]
---

ArgoCD를 쓰면서 "GitOps"라는 말을 계속 봤는데, 그게 정확히 뭔지 정리해봤어요.

## 기존 배포 방식

예전엔 CI/CD가 이렇게 동작했어요.

```
코드 push
→ GitHub Actions
→ docker build & push
→ kubectl apply (직접 배포 명령)
```

파이프라인이 쿠버네티스에 직접 배포 명령을 날려요.  
문제는 **"현재 실제 서버 상태"가 어디에도 기록이 안 된다**는 거예요.

## GitOps

**배포 상태를 Git으로 관리**하는 방식이에요.

쿠버네티스 설정(Deployment, PVC, ConfigMap 등)을 Git 레포에 저장하고, **실제 클러스터가 항상 Git 상태와 일치하도록** 자동으로 맞춰요.

```
Git 레포 (argocd-apps)     →    실제 클러스터
  Deployment: replicas=3   →   Pod 3개 실행 중
  PVC: 5Gi RWX             →   EFS 볼륨 마운트됨
```

Git이 "진실의 원천(Source of Truth)"이에요.

## ArgoCD

GitOps를 실현하는 도구예요. Git 레포를 지켜보다가 변경이 생기면 클러스터에 자동 반영해요.

```
개발자가 argocd-apps 레포에 YAML 수정 & push
         ↓
ArgoCD가 변경 감지
         ↓
kubectl apply (자동)
         ↓
클러스터 상태 업데이트
```

직접 `kubectl apply`를 안 해도 돼요. Git에 올리면 끝.

## ArgoCD UI에서 보이는 것

```
App 상세 화면 (리소스 트리)

Deployment
└── ReplicaSet
    ├── Pod A  ← 초록 = Healthy
    ├── Pod B  ← 초록 = Healthy
    └── Pod C  ← 초록 = Healthy

PersistentVolumeClaim  ← 원통 모양 아이콘
ConfigMap
Service
```

각 리소스의 현재 상태를 Git에 정의된 상태와 비교해서 보여줘요.

**Synced**: Git과 클러스터 상태 일치  
**OutOfSync**: 클러스터가 Git과 다른 상태 → SYNC 버튼으로 맞춰야 함

## REFRESH vs SYNC

헷갈렸던 부분인데, 완전히 달라요.

| | REFRESH | SYNC |
|---|---|---|
| 하는 일 | 현재 상태를 다시 읽어옴 | Git 상태대로 실제 클러스터를 변경 |
| 서버 영향 | **없음** | **있음** (배포 발생) |
| 언제 쓰나 | UI가 최신 상태 안 보일 때 | 실제 배포할 때 |

REFRESH는 그냥 "새로고침"이라 언제 눌러도 돼요.  
SYNC가 실제 배포를 트리거하는 버튼이에요.

## 멀티 클러스터 관리

ArgoCD는 여러 클러스터를 한 곳에서 관리할 수 있어요.

```
ArgoCD (개발 클러스터에 설치)
├── ksd-eks (개발) 연결     → develop 네임스페이스 앱 관리
└── ksd-prod-eks (운영) 연결 → production 네임스페이스 앱 관리
```

그래서 ArgoCD UI에 dev/prod 앱이 둘 다 보이는 거예요.

## 전체 배포 흐름 정리

```
[개발자]
코드 수정 → PR → merge → main 브랜치

[GitHub Actions]
→ docker build
→ ECR에 이미지 push
→ argocd-apps 레포의 YAML에 이미지 태그 업데이트 & push

[ArgoCD]
→ argocd-apps 레포 변경 감지
→ 자동 Sync (또는 수동 SYNC 클릭)
→ kubectl apply
→ 롤링 업데이트 시작
→ 새 Pod 생성 → 기존 Pod 종료
→ 무중단 배포 완료
```

Git 레포 하나(`argocd-apps`)가 운영 인프라의 진실의 원천이 되는 거예요.
