---
title: "인프라 개념 정리 (4) ArgoCD와 GitOps"
date: 2026-04-10 15:40:00 +0900
categories: [Infra, Kubernetes]
tags: [argocd, gitops, kubernetes, cicd]
---

## GitOps

쿠버네티스 설정(Deployment, PVC, ConfigMap 등)을 Git 레포에 저장하고, 클러스터가 항상 Git 상태와 일치하도록 유지하는 방식이다.

Git이 "현재 인프라 상태의 원천"이 된다.

```
argocd-apps 레포 (YAML)    →    실제 클러스터
  Deployment: replicas=3   →   Pod 3개 실행 중
  PVC: 5Gi RWX             →   EFS 볼륨 마운트됨
```

기존 방식은 CI 파이프라인이 `kubectl apply`를 직접 날렸는데, 그러면 "지금 클러스터에 실제로 뭐가 배포되어 있는지"가 Git에 남지 않는다.

## ArgoCD

GitOps를 구현하는 도구다. `argocd-apps` 레포를 지켜보다가 변경이 생기면 클러스터에 자동으로 반영한다.

```
argocd-apps 레포 YAML 수정 & push
→ ArgoCD 변경 감지
→ kubectl apply (자동)
→ 클러스터 상태 업데이트
```

우리 프로젝트는 `ksd-eks`(개발)에 ArgoCD가 설치되어 있고, `ksd-prod-eks`(운영)도 연결되어 있어서 UI에서 dev/prod 앱을 한 곳에서 관리한다.

## REFRESH vs SYNC

직접 쓰면서 헷갈렸던 부분이다.

| | REFRESH | SYNC |
|---|---|---|
| 하는 일 | 현재 상태 다시 읽어옴 | Git 상태대로 클러스터 변경 |
| 서버 영향 | 없음 | 있음 (배포 발생) |

REFRESH는 ArgoCD 캐시 문제로 리소스 패널이 안 보일 때 쓰는 새로고침이다. SYNC가 실제 배포를 트리거한다.

## 전체 배포 흐름

```
코드 수정 → PR → merge

GitHub Actions
→ docker build & push → ECR
→ argocd-apps YAML의 이미지 태그 업데이트 & push

ArgoCD
→ 변경 감지 → kubectl apply
→ 롤링 업데이트 → 무중단 배포 완료
```
