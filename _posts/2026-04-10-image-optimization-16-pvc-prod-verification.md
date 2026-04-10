---
title: "이미지 최적화 (16) 운영 PVC 검증 — 3 pod가 EFS 하나를 공유한다"
date: 2026-04-10 15:00:00 +0900
categories: [Infra, Kubernetes]
tags: [kubernetes, efs, pvc, multi-pod, production]
---

{% include image-optimization-series.html current=16 %}

14편에서 EFS RWX로 여러 pod가 PVC를 공유할 수 있다고 설계했는데, 실제 운영에서 확인해봤다.

## 운영 클러스터 접속

개발 클러스터(`ksd-eks`)는 기본 `kubectl`로 붙는데, 운영 클러스터(`ksd-prod-eks`)는 `~/.kube/config`에 등록하지 않고 별도 파일로 분리했다. 운영 접속 기록을 개발 config와 섞지 않기 위해서다.

```bash
aws eks update-kubeconfig --name ksd-prod-eks --region ap-northeast-2 \
  --kubeconfig ~/.kube/baeji-prod-kubeconfig

# ~/.zshrc
alias kprod="kubectl --kubeconfig=/home/ec2-user/.kube/baeji-prod-kubeconfig"
```

`k`는 개발, `kprod`는 운영. 브랜치 체크아웃처럼 전환하는 게 아니라 매 명령마다 어떤 kubeconfig를 쓸지 지정하는 방식이다.

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

- `Bound` — EFS 볼륨에 정상 연결
- `RWX` — 여러 pod 동시 마운트 가능
- web/worker 각각 PVC 분리 (앱 독립성 유지)

web/worker를 하나의 PVC로 공유할 수도 있지만 분리가 맞다. 파라미터(`w`, `q`)가 달라 캐시 키가 달라지고, 한 쪽 문제가 다른 쪽에 영향 주지 않아야 하기 때문이다.

## 3개 pod가 하나의 PVC를 공유

운영 web pod 3개가 `spation-workspace-web-image-cache` PVC 하나를 동시 마운트하고 있다.

```
├── spation-workspace-web-58fbcdd898-qs7sg ──┐
├── spation-workspace-web-58fbcdd898-tpnfz ──┼── spation-workspace-web-image-cache (EFS, RWX)
└── spation-workspace-web-58fbcdd898-tzc5d ──┘
```

어느 pod로 요청이 들어와도 같은 볼륨을 보기 때문에 캐시 HIT율이 replica 수와 무관하게 유지된다.

> 3개 pod 동일 캐시 파일 목록 확인 스크린샷 첨부 예정
