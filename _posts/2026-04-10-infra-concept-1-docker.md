---
title: "인프라 개념 정리 (1) 도커 — 이미지, 컨테이너, 그게 뭔데?"
date: 2026-04-10 15:10:00 +0900
categories: [Infra, Docker]
tags: [docker, container, image, 개념정리]
---

쿠버네티스 공부하다 보니 도커 개념을 제대로 정리해두고 싶어졌어요.  
"이미지", "컨테이너"를 대충 쓰고 있었는데, 정확히 뭔지 정리해봤습니다.

## 도커 이미지

**앱을 실행하는 데 필요한 모든 것을 묶은 패키지**예요.

- OS 환경 (Ubuntu, Alpine 등)
- 런타임 (Node.js, JVM 등)
- 앱 코드
- 의존성 (node_modules, jar 등)
- 실행 명령어

`Dockerfile`로 만들고, `docker build`로 생성해요.

```dockerfile
FROM node:20-alpine
WORKDIR /app
COPY . .
RUN npm install
CMD ["node", "server.js"]
```

이미지는 **읽기 전용**이에요. 변경 불가.

## 도커 컨테이너

**이미지를 실행한 것**이에요.

```
이미지 (설계도) → 컨테이너 (실행 중인 인스턴스)
```

붕어빵 틀(이미지)로 붕어빵(컨테이너)을 여러 개 찍어낼 수 있어요.  
같은 이미지로 컨테이너 10개를 동시에 띄울 수 있고, 각각 독립적으로 실행돼요.

```bash
docker run nginx   # nginx 이미지로 컨테이너 실행
docker run nginx   # 또 하나 실행 — 독립적인 컨테이너
```

컨테이너는 **격리된 프로세스**예요. 서로 영향 없음.

## 왜 도커를 쓰나?

예전엔 이런 문제가 많았어요:

> "내 로컬에선 되는데 서버에서 안 돼요"

도커 이미지에 환경을 통째로 담으면, 어디서 실행해도 동일한 환경이에요.

```
개발자 맥북    →  동일한 이미지  →  AWS EC2 서버
테스트 서버    →  동일한 이미지  →  운영 서버
```

## 이미지는 어디에 저장?

**컨테이너 레지스트리**에 저장해요.

| 레지스트리 | 설명 |
|-----------|------|
| Docker Hub | 공개 레지스트리 (nginx, node 등 공식 이미지) |
| AWS ECR | AWS 전용 프라이빗 레지스트리 |
| GitHub Container Registry | GitHub 연동 |

우리 프로젝트는 AWS ECR에 이미지를 푸시하고, 쿠버네티스가 거기서 pull해요.

```
GitHub Actions CI/CD
→ docker build
→ docker push → AWS ECR
→ 쿠버네티스가 ECR에서 pull → 컨테이너 실행
```

## 정리

```
Dockerfile  →  docker build  →  이미지 (ECR에 저장)
                                    ↓
                              docker run
                                    ↓
                              컨테이너 (실행 중인 앱)
```

이미지는 설계도, 컨테이너는 그걸 실행한 것.  
같은 이미지로 컨테이너를 몇 개든 찍어낼 수 있어요.
