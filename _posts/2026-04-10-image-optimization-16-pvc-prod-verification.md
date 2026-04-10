---
title: "이미지 최적화 (16) 운영 PVC 검증 — 3 pod가 EFS 하나를 공유하고 있다"
date: 2026-04-10 15:00:00 +0900
categories: [Infra, Kubernetes]
tags: [kubernetes, efs, pvc, multi-pod, production]
---

{% include image-optimization-series.html current=16 %}

## 운영에 올라갔을까?

14편에서 EFS RWX로 여러 pod가 PVC 하나를 공유할 수 있다고 정리했는데, 실제 운영 클러스터에서 확인해보고 싶었어요.

개발 클러스터(`ksd-eks`)는 `kubectl`로 바로 붙는데, 운영 클러스터(`ksd-prod-eks`)는 별도로 접속해야 했어요.

## 운영 클러스터 접속

`~/.kube/config`에 섞지 않고, 별도 kubeconfig 파일로 분리했어요.

```bash
# 운영 클러스터 kubeconfig를 별도 파일에 저장
aws eks update-kubeconfig --name ksd-prod-eks --region ap-northeast-2 \
  --kubeconfig ~/.kube/baeji-prod-kubeconfig

# alias 등록 (~/.zshrc)
alias kprod="kubectl --kubeconfig=/home/ec2-user/.kube/baeji-prod-kubeconfig"
```

이렇게 하면 `k`는 개발, `kprod`는 운영으로 명확하게 분리돼요.  
Git 브랜치 체크아웃처럼 "전환"하는 게 아니라, 매 명령마다 어떤 클러스터를 쓸지 지정하는 방식이에요.

## PVC 확인

```bash
kprod -n production get pvc
```

```
NAME                                   STATUS   VOLUME                     CAPACITY   ACCESS MODES   STORAGECLASS    AGE
spation-workspace-web-image-cache      Bound    pvc-0b9f10f4-...           5Gi        RWX            efs-sc-nextjs   24h
spation-workspace-worker-image-cache   Bound    pvc-a8247680-...           5Gi        RWX            efs-sc-nextjs   2d
```

> 스크린샷 첨부 예정

**확인된 것:**
- `STATUS: Bound` — EFS 볼륨에 정상 연결됨
- `ACCESS MODES: RWX` — ReadWriteMany, 여러 pod 동시 마운트 가능
- web/worker 각각 PVC가 분리되어 있음

## web/worker를 왜 분리했나?

처음엔 "하나로 공유하면 안 되나?" 싶었는데, 분리하는 게 맞아요.

- web/worker가 요청하는 이미지 파라미터(`w`, `q`)가 다를 수 있어요
- 한 쪽 앱 문제로 캐시 날려도 다른 쪽에 영향 없음
- 앱 독립성 유지

## 3개 pod가 하나의 PVC를 공유

운영 web pod가 3개 떠 있는데, 셋 다 `spation-workspace-web-image-cache` PVC 하나를 마운트해요.

```
Deployment (replica: 3)
├── spation-workspace-web-58fbcdd898-qs7sg ──┐
├── spation-workspace-web-58fbcdd898-tpnfz ──┼── spation-workspace-web-image-cache (EFS, RWX)
└── spation-workspace-web-58fbcdd898-tzc5d ──┘
```

Pod A가 캐시를 쓰면 Pod B, C에서 즉시 읽힘. 어느 pod로 요청이 들어와도 캐시 HIT 가능.

> 3개 pod에서 동일 캐시 파일 목록 확인 스크린샷 첨부 예정
