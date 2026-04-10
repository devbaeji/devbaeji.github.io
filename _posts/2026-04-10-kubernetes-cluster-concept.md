---
title: "쿠버네티스와 클러스터 — ArgoCD 쓰다가 정리하게 된 개념들"
date: 2026-04-10 14:00:00 +0900
categories: [Infra, Kubernetes]
tags: [kubernetes, eks, cluster, argocd]
---

ArgoCD에서 PVC 상태 확인하다가 "dev랑 prod 클러스터가 왜 따로 있지?"라는 의문이 생겼다. 정리해봤다.

## 쿠버네티스

컨테이너 자동 관리 시스템이다. Pod가 죽으면 재시작, 트래픽 많으면 Pod 수 증가, 배포 시 롤링 업데이트로 무중단 교체. 이걸 사람이 직접 하던 걸 자동화한 것.

## 클러스터

쿠버네티스가 관리하는 서버 묶음이다.

```
클러스터
├── Control Plane (두뇌 — 결정을 내리는 곳)
└── Node 여러 대 (앱이 실제로 돌아가는 서버, EC2)
         └── Pod들
```

AWS EKS를 쓰면 Control Plane은 AWS가 관리한다. Node(EC2)만 신경 쓰면 된다.

## dev/prod를 클러스터로 분리하는 이유

같은 클러스터 안에서 네임스페이스(`-n develop`, `-n production`)로 나누는 방법도 있다. 근데 우리 프로젝트는 클러스터 자체를 분리(`ksd-eks`, `ksd-prod-eks`)해놨다.

이유는 단순하다.

- dev에서 리소스 폭주해도 prod에 영향 없음
- prod 클러스터 접근 권한을 별도로 엄격하게 관리
- dev는 저사양, prod는 고사양 Node로 비용 분리
- dev 작업 중 실수로 prod에 명령 날리는 사고 원천 차단

## ArgoCD가 두 클러스터를 한 곳에서 관리

ArgoCD 자체는 `ksd-eks`에 설치되어 있는데, `ksd-prod-eks`도 연결해놔서 UI에서 둘 다 보인다.

```
ArgoCD
├── ksd-eks      → develop 앱 관리
└── ksd-prod-eks → production 앱 관리
```

## 운영 클러스터 접속

`~/.kube/config`에 등록하지 않고 별도 파일로 분리했다. 개발/운영 config를 섞으면 실수로 잘못된 클러스터에 명령 날릴 수 있어서다.

```bash
# 운영 kubeconfig를 별도 파일에 저장
aws eks update-kubeconfig --name ksd-prod-eks --region ap-northeast-2 \
  --kubeconfig ~/.kube/baeji-prod-kubeconfig

# ~/.zshrc
alias k="kubectl"                                                                      # 개발 (기본 ~/.kube/config → ksd-eks)
alias kprod="kubectl --kubeconfig=/home/ec2-user/.kube/baeji-prod-kubeconfig"         # 운영 (ksd-prod-eks)
```

`k`는 개발, `kprod`는 운영. Git 브랜치 체크아웃처럼 전환하는 게 아니라, 명령마다 어떤 kubeconfig를 쓸지 명시하는 방식이다.

```bash
# 개발
k -n develop get pods
k logs -n develop -f spation-workspace-api-xxx

# 운영
kprod -n production get pods
kprod -n production get pvc
```
