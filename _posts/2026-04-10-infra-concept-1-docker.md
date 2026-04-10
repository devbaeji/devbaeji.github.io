---
title: "인프라 개념 정리 (1) 도커 이미지와 컨테이너"
date: 2026-04-10 15:10:00 +0900
categories: [Infra, Docker]
tags: [docker, container, image, ecr]
---

쿠버네티스 작업을 하다 보니 도커 개념을 한 번 제대로 정리해두고 싶었다.

## 이미지

앱 실행에 필요한 모든 것을 묶은 패키지다. OS, 런타임, 코드, 의존성, 실행 명령어가 다 들어간다. `Dockerfile`로 정의하고 `docker build`로 생성한다.

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY . .
RUN npm install
CMD ["node", "server.js"]
```

이미지 자체는 읽기 전용이다. 빌드 후 변경되지 않는다.

## 컨테이너

이미지를 실행한 인스턴스다. 같은 이미지로 컨테이너를 여러 개 동시에 띄울 수 있고, 각각 격리된 상태로 실행된다.

쿠버네티스에서 replica를 3으로 설정하면, 동일한 이미지로 Pod 3개(컨테이너 3개)가 뜨는 게 이 원리다.

## 이미지 저장소 (레지스트리)

빌드한 이미지는 레지스트리에 push해서 저장한다. 우리 프로젝트는 AWS ECR을 쓴다.

```
GitHub Actions
→ docker build
→ docker push → AWS ECR
→ 쿠버네티스가 ECR에서 pull → 컨테이너 실행
```

ECR은 프라이빗 레지스트리라 인증된 AWS 계정만 pull할 수 있다. 공개 이미지(nginx, node 등)는 Docker Hub에서 가져온다.
