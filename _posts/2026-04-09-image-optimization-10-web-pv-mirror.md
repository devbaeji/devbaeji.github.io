---
title: "이미지 최적화 (10) web PV 미러링 구성과 검증"
date: 2026-04-09 21:00:00 +0900
categories: [Infra, Kubernetes]
tags: [nextjs, kubernetes, efs, pvc, argocd, cache, verification]
---

{% include image-optimization-series.html current=10 %}

## 상황

worker PV 캐시 완료(7편). commons 추출 완료(9편). web에 동일 인프라만 추가하면 된다.

## 구성: PVC + volumeMount + env

```yaml
# PVC — worker와 동일 스펙, name만 변경
name: test-app-web-image-cache
accessModes: [ReadWriteMany]
storageClassName: efs-sc-nextjs
storage: 5Gi

# volumeMount
mountPath: /app/cache/images

# env
IMAGE_CACHE_DIR: /app/cache/images
```

## 초기에 놓친 것

**1. mountPath를 `/app/apps/web/.next/cache/images`로 설정**

Next.js 기본 캐시 경로를 따라갔는데, 이 앱은 `_next/image` 캐시가 아니라 커스텀 route handler가 `IMAGE_CACHE_DIR`을 읽는다. 경로가 무관. worker 규약(`/app/cache/images`)으로 수정.

**2. IMAGE_CACHE_DIR env 누락**

7편과 같은 실수. PVC + mount만 있고 env 없으면 캐시 경로를 모른다.

## 검증 결과

```
$ kubectl -n develop exec <pod> -- ls -lh /app/cache/images
total 528K
-rw-r--r--. 1 nextjs 65533 6.1K Apr  9 06:44 54_w960_q75.webp
-rw-r--r--. 1 nextjs 65533 162K Apr  9 06:47 67_w960_q75.webp
-rw-r--r--. 1 nextjs 65533 122K Apr  9 06:47 68_w960_q75.webp
...
```

pod 삭제 → 새 pod에서 동일 파일 확인. 영속성 검증 완료.

## 배포 후 검증 커맨드

```bash
NS=develop
APP=test-app-web   # worker는 test-app-worker
POD=$(kubectl -n $NS get pod -l app=$APP -o jsonpath='{.items[0].metadata.name}')

# 1. 인프라
kubectl -n $NS exec $POD -- printenv IMAGE_CACHE_DIR
kubectl -n $NS exec $POD -- df -h /app/cache/images

# 2. 캐시 동작
kubectl -n $NS exec $POD -- ls -lh /app/cache/images

# 3. 영속성
kubectl -n $NS delete pod $POD
sleep 10
NEW_POD=$(kubectl -n $NS get pod -l app=$APP -o jsonpath='{.items[0].metadata.name}')
kubectl -n $NS exec $NEW_POD -- ls -lh /app/cache/images
```

## 핵심

- 인프라 구성 체크리스트는 **PVC → volumeMount → env** 3종 세트. 하나라도 빠지면 기능이 죽는다.
- 경로 규약은 첫 구현에서 확립하고, 이후 앱은 그대로 따른다.
- 검증 커맨드를 문서화하면 다음 배포에서 "이거 어떻게 확인하더라" 시간이 사라진다.
