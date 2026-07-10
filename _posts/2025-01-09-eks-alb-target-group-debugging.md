---
title: "EKS에서 ALB Target Group이 Unhealthy인데 서비스는 동작한다? 삽질 기록"
date: 2025-01-09 14:00:00 +0900
categories: [Infra, Kubernetes]
tags: [eks, alb, target-group, kubernetes, troubleshooting]
---

## 문제 발견

어느 날 AWS 콘솔에서 로드밸런서 대상그룹(Target Group)을 확인하다가 이상한 걸 발견했어요.

**여러 대상그룹이 `unhealthy` 상태인데, 서비스는 정상 동작하고 있었거든요.**

```
k8s-develop-mytest-12505a9270 → 10.0.1.25   unhealthy (ResponseCodeMismatch)
k8s-develop-mytest-2b5390ae61 → 10.0.2.149  unhealthy (ResponseCodeMismatch)
k8s-develop-develops-8666b8a80f → 10.0.1.144  unhealthy (ResponseCodeMismatch)
```

"unhealthy면 트래픽이 안 가야 하는 거 아닌가?" 싶었는데, 실제로는 잘 동작하더라고요.

---

## 왜 Unhealthy인데 동작할까?

### ALB의 "Fail-Open" 동작

AWS ALB에는 재밌는 동작 방식이 있어요.

| 타겟 상태 | ALB 동작 |
|----------|----------|
| 일부 healthy | healthy 타겟에만 라우팅 |
| **전부 unhealthy** | **모든 타겟에 라우팅 (fail-open)** |

**모든 타겟이 unhealthy면, 503 에러를 내는 것보다 일단 시도라도 해보자**는 철학이에요.

그래서 헬스체크는 실패하지만 실제 서비스는 동작했던 거예요.

---

## 인프라 구조 파악하기

문제를 해결하려면 먼저 구조를 이해해야 했어요.

### EKS + ALB + Ingress 구조

```
인터넷 요청
    │
    ▼
┌─────────────────────────────────────────┐
│         AWS ALB (Application LB)         │
│  ┌─────────────────────────────────────┐ │
│  │ 리스너 규칙: 조건별로 대상그룹 분기   │ │
│  └─────────────────────────────────────┘ │
└─────────────────────────────────────────┘
    │
    │  대상그룹별로 라우팅
    │
    ├── workspace.api.xxx  ──▶  Target Group A ──▶ API Pod
    │
    ├── worker.api.xxx     ──▶  Target Group B ──▶ API Pod (동일)
    │
    └── dev.mytest.com    ──▶  Target Group C ──▶ Web Pod
```

### Ingress가 뭐지?

처음엔 Ingress가 뭔지 헷갈렸어요.

**Ingress = "이 URL로 들어오면 이 서비스로 보내라"는 라우팅 규칙**

```yaml
# 예시: Ingress 설정
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: mytest-workspace-web-ingress
  annotations:
    alb.ingress.kubernetes.io/healthcheck-path: /api/health
spec:
  rules:
    - host: dev.mytest.com
      http:
        paths:
          - path: /*
            backend:
              service:
                name: mytest-workspace-web
                port: 3000
```

EKS에서 Ingress를 만들면, **AWS Load Balancer Controller**가 자동으로:
1. ALB 생성
2. 대상그룹 생성
3. 리스너 규칙 설정

을 해줘요. Terraform이나 ArgoCD에서 직접 ALB를 만드는 게 아니라, **Ingress 리소스를 통해 자동 생성**되는 거예요.

---

## 진단 과정

### 1단계: 대상그룹 헬스 상태 확인

```bash
# 모든 대상그룹의 헬스 상태 조회
for arn in $(aws elbv2 describe-target-groups --query 'TargetGroups[*].TargetGroupArn' --output text); do
  echo "--- $(echo $arn | awk -F'/' '{print $2}') ---"
  aws elbv2 describe-target-health --target-group-arn $arn \
    --query 'TargetHealthDescriptions[*].[Target.Id,TargetHealth.State,TargetHealth.Reason]' \
    --output table
done
```

결과를 보니 `ResponseCodeMismatch`가 잔뜩 있었어요.

### 2단계: 헬스체크 설정 확인

```bash
aws elbv2 describe-target-groups --names k8s-develop-mytest-12505a9270 \
  --query 'TargetGroups[0].{Path:HealthCheckPath,Port:HealthCheckPort,ExpectedCodes:Matcher.HttpCode}' \
  --output table
```

```
+---------------+-------+---------------+
| ExpectedCodes | Path  | Port          |
+---------------+-------+---------------+
| 200           | /     | traffic-port  |
+---------------+-------+---------------+
```

**문제 발견!**

헬스체크가 `/` (루트 경로)로 설정되어 있는데:
- Next.js 앱은 `/`에서 로그인 페이지로 **302 리다이렉트**
- 기대값은 `200`인데 `302`가 오니까 **ResponseCodeMismatch**

### 3단계: 대상그룹 태그로 Ingress 매핑 확인

대상그룹 태그를 보면 어떤 Ingress에서 생성됐는지 알 수 있어요.

```
ingress.k8s.aws/resource: develop/mytest-workspace-web-ingress-internal-mytest-workspace-api:80
```

태그 형식: `{namespace}/{ingress-name}-{service-name}:{port}`

---

## 이상한 현상: 같은 API인데 결과가 다르다?

디버깅 중에 더 이상한 걸 발견했어요.

```
┌──────────────────┐      ┌──────────────────┐
│  worker.api.xxx  │─────▶│                  │
└──────────────────┘      │   동일한 API Pod   │──▶ DB 적재 ❌
                          │                  │
┌──────────────────┐      │                  │
│ workspace.api.xxx│─────▶│                  │──▶ DB 적재 ✅
└──────────────────┘      └──────────────────┘
```

**같은 Pod인데, 도메인에 따라 DB 적재가 되기도 하고 안 되기도 했어요.**

API 로그를 보니 둘 다 요청이 들어오고 응답도 나가더라고요. 그런데 하나는 저장이 안 됨.

### 결론: 완전히 다른 이슈였음

알고 보니 **프론트엔드 앱에서 Authorization Bearer 토큰을 안 보내고 있었어요.**

- workspace 앱: 토큰 정상 전송 → 인증 성공 → DB 저장 ✅
- worker 앱: 토큰 누락 → 인증 실패 (하지만 200 응답) → DB 저장 ❌

인프라 문제인 줄 알았는데, 프론트엔드 문제였던 거예요. 😅

---

## 해결 방법

### 1. 헬스체크 경로 수정 (Ingress annotation)

```yaml
metadata:
  annotations:
    # Next.js 앱
    alb.ingress.kubernetes.io/healthcheck-path: /api/health

    # Spring Boot API
    alb.ingress.kubernetes.io/healthcheck-path: /actuator/health
```

### 2. Next.js에 헬스체크 엔드포인트 추가

```typescript
// apps/web/src/app/api/health/route.ts
import { NextResponse } from 'next/server';

export async function GET() {
  return NextResponse.json({ status: 'ok' }, { status: 200 });
}
```

### 3. Spring Boot는 이미 있음

```yaml
# application.yml
management:
  endpoints:
    web:
      base-path: /actuator
      exposure:
        include: health
```

`/actuator/health` 경로로 헬스체크하면 돼요.

---

## 배운 점

1. **Unhealthy여도 동작할 수 있다**
   - ALB의 fail-open 동작 때문에 모든 타겟이 unhealthy면 트래픽이 감

2. **헬스체크 경로 설정이 중요하다**
   - `/`로 체크하면 리다이렉트나 404 때문에 실패할 수 있음
   - 명시적인 health 엔드포인트를 만들고 그 경로로 체크

3. **인프라 문제라고 단정짓지 말자**
   - 같은 Pod인데 결과가 다르면, 요청 자체가 다른 건 아닌지 확인
   - 이번엔 Authorization 헤더 누락이 원인이었음

4. **Ingress와 대상그룹의 관계**
   - Ingress 하나당 대상그룹이 생성됨
   - 같은 서비스를 여러 Ingress에서 참조하면 대상그룹도 여러 개

---

## 유용한 디버깅 명령어 모음

```bash
# 1. 대상그룹 목록
aws elbv2 describe-target-groups \
  --query 'TargetGroups[*].[TargetGroupName]' --output table

# 2. 대상그룹 헬스 상태
aws elbv2 describe-target-health \
  --target-group-arn <arn>

# 3. 헬스체크 설정 확인
aws elbv2 describe-target-groups --names <name> \
  --query 'TargetGroups[0].{Path:HealthCheckPath,ExpectedCodes:Matcher.HttpCode}'

# 4. Kubernetes Ingress 확인
kubectl get ingress -n develop -o wide

# 5. Pod 상태 확인
kubectl get pods -n develop -o wide

# 6. API 로그 실시간 확인
kubectl logs -f -n develop -l app=mytest-workspace-api --tail=100
```

---

## 결론

AWS 콘솔에서 "unhealthy" 빨간불을 보면 당황스럽지만, 차근차근 구조를 파악하면 원인을 찾을 수 있어요.

이번 경험으로 EKS + ALB + Ingress의 관계를 확실히 이해하게 됐고, **인프라 문제처럼 보여도 실제론 애플리케이션 문제일 수 있다**는 것도 배웠습니다.
