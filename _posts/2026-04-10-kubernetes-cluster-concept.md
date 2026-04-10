---
title: "쿠버네티스가 뭔지, 클러스터가 뭔지 드디어 이해했어요"
date: 2026-04-10 14:00:00 +0900
categories: [Infra, Kubernetes]
tags: [kubernetes, eks, cluster, argocd]
---

ArgoCD에서 PVC 상태 확인하려다가 "이게 왜 dev랑 prod 클러스터가 따로 있지?" 라는 의문이 생겼어요.  
찾아보다가 드디어 개념이 잡혔는데, 정리해봤습니다.

## 쿠버네티스가 뭔가요?

한마디로, **컨테이너를 자동으로 관리해주는 시스템**이에요.

Docker로 앱을 컨테이너로 만드는 건 알겠는데, 실제 운영에선 이런 일들이 생기잖아요:

- 컨테이너가 갑자기 죽었어요 → 누가 살려줘야 해요
- 트래픽이 갑자기 몰렸어요 → 컨테이너를 더 띄워야 해요
- 새 버전 배포해야 해요 → 서비스 중단 없이 교체해야 해요

이걸 일일이 사람이 하던 걸, 쿠버네티스가 알아서 처리해줘요.

```
Pod가 죽으면?     → 자동 재시작
트래픽 많으면?    → Pod 수 자동 증가 (HPA)
새 버전 배포?     → 롤링 업데이트로 무중단 교체
```

## 클러스터가 뭔가요?

**쿠버네티스가 관리하는 서버 묶음 하나**를 클러스터라고 해요.

```
클러스터
├── Control Plane (두뇌 역할 — 쿠버네티스가 결정을 내리는 곳)
└── Node 여러 대 (실제 앱이 돌아가는 서버들)
         ├── Pod A
         ├── Pod B
         └── Pod C
```

AWS에서는 EC2 인스턴스들이 Node가 되고, EKS(Elastic Kubernetes Service)가 Control Plane을 대신 관리해줘요. 직접 쿠버네티스 설치하고 유지보수할 필요 없이요.

## dev랑 prod를 왜 클러스터로 아예 분리해요?

"같은 클러스터 안에서 네임스페이스(`-n develop`, `-n production`)로 나눠도 되지 않나?"라고 생각했는데, 클러스터 자체를 분리하는 이유가 있더라고요.

| 이유 | 설명 |
|------|------|
| **장애 격리** | dev에서 리소스 폭주해도 prod에 전혀 영향 없어요 |
| **보안** | prod 클러스터 접근 권한을 훨씬 엄격하게 관리할 수 있어요 |
| **스펙 분리** | dev는 저사양, prod는 고사양 Node로 비용 절감 |
| **실수 방지** | dev에서 작업하다 실수로 prod에 명령 날리는 사고 차단 |

네임스페이스 분리만 해도 운영은 되긴 해요. 근데 진짜 클러스터가 완전히 분리되어 있으면, dev에서 무슨 짓을 해도 prod가 절대로 영향받지 않아요. 그래서 규모 있는 서비스는 대부분 클러스터를 나눠요.

## ArgoCD는 여기서 어떤 역할?

ArgoCD는 **멀티 클러스터를 한 곳에서 관리**할 수 있는 GitOps 도구예요.

```
ArgoCD
├── dev 클러스터 연결  → develop 앱들 배포/관리
└── prod 클러스터 연결 → production 앱들 배포/관리
```

그래서 ArgoCD UI에서 dev/prod 앱이 둘 다 보이는 거예요. 각각 다른 클러스터에 있는데 ArgoCD가 둘 다 붙잡고 있는 것.

## kubectl에서 클러스터 전환하는 법

`kubeconfig`에 여러 클러스터가 등록되어 있으면, `--context` 옵션으로 지정할 수 있어요.

```bash
# 등록된 컨텍스트(클러스터) 목록 확인
kubectl config get-contexts

# 특정 클러스터에 명령 실행
kubectl --context=<컨텍스트이름> get pods -n production

# 기본 컨텍스트 변경 (매번 --context 안 써도 되도록)
kubectl config use-context <컨텍스트이름>
```

AWS EKS 컨텍스트 이름은 보통 `arn:aws:eks:ap-northeast-2:<계정ID>:cluster/<클러스터이름>` 형태예요.

```bash
# EKS 클러스터 목록 조회
aws eks list-clusters --region ap-northeast-2

# kubeconfig에 클러스터 추가
aws eks update-kubeconfig --name <클러스터이름> --region ap-northeast-2
```

---

ArgoCD PVC 확인하려다가 개념 공부까지 하게 됐는데, 오히려 좋았어요.  
"이게 왜 이렇게 되어 있지?"라는 의문이 생겼을 때 파고드는 게 결국 더 잘 이해하는 방법인 것 같아요.
