---
title: "멀티채널 알림 시스템 구축기 (5) - 배포 및 트러블슈팅"
date: 2025-01-08 19:00:00 +0900
categories: [Backend, AWS]
tags: [serverless, aws, sns, lambda, cloudformation, deployment, troubleshooting]
---

## 시리즈

| Part | 주제 |
|------|------|
| [Part 1](/posts/notification-system-part1-architecture) | 아키텍처 설계 |
| [Part 2](/posts/notification-system-part2-router) | notification-router 구현 |
| [Part 3](/posts/notification-system-part3-notifiers) | Notifier Lambda 구현 |
| [Part 4](/posts/notification-system-part4-localstack) | LocalStack으로 로컬 테스트 |
| **Part 5** | 배포 및 트러블슈팅 (현재 글) |

---

## 배포 환경

드디어 LocalStack에서 충분히 테스트한 알림 시스템을 **실제 AWS에 배포**할 차례예요. Serverless Framework를 사용해서 배포합니다.

```bash
# 각 Lambda 배포 명령어
pnpm run deploy:dev   # dev 환경
pnpm run deploy:prod  # prod 환경
```

근데 배포하자마자 에러가 터졌어요. 😱

---

## 문제 상황: Topic does not exist

FCM 푸시 알림을 위한 `fcm-notifier` Lambda를 새로 만들고 배포하려는데, 이런 에러가 발생했어요.

![터미널 에러 메시지](/assets/img/posts/2025-01-08-serverless-sns/terminal-error.png)
_Serverless 배포 시 발생한 SNS Topic 에러_

```
Error:
CREATE_FAILED: LambdaSnsSubscriptionFcmnotificationsdev (AWS::SNS::Subscription)
Resource handler returned message: "Topic does not exist
(Service: Sns, Status Code: 404, Request ID: ef440541-7fc4-59dc-a627-64982a009534)"
```

AWS CloudFormation 콘솔에서도 스택이 `UPDATE_ROLLBACK_COMPLETE` 상태로 롤백된 걸 확인할 수 있었어요.

![CloudFormation 콘솔](/assets/img/posts/2025-01-08-serverless-sns/cloudformation-rollback.png)
_CloudFormation 스택이 롤백된 상태_

처음엔 IAM 권한 문제인가 싶어서 정책을 확인해봤는데, 권한은 정상이었어요.

---

## 원인 분석

에러 메시지를 다시 읽어보니 답이 있었어요. **"Topic does not exist"** - SNS Topic 자체가 없다는 거였죠.

### 우리 시스템의 SNS Topic 생성 위치

`fcm-notifier`의 `serverless.yml`을 보면, 이미 존재하는 SNS Topic ARN을 직접 참조하고 있어요:

```yaml
# apps/lambdas/fcm-notifier/serverless.yml
functions:
  lambda:
    handler: src/index.handler
    events:
      - sns:
          arn: arn:aws:sns:ap-northeast-2:225179063068:fcm-notifications-dev
```

그런데 이 `fcm-notifications-dev` Topic은 어디서 생성될까요? `notification-router`의 CloudFormation 리소스에서 생성돼요:

```yaml
# apps/lambdas/notification-router/serverless.yml
resources:
  Resources:
    FcmNotificationsTopic:
      Type: AWS::SNS::Topic
      Properties:
        TopicName: fcm-notifications-${self:provider.stage}
```

### 문제의 핵심

`fcm-notifier`를 배포하려면 `fcm-notifications-dev` Topic이 **이미 AWS에 존재해야** 해요. 그런데 이 Topic은 `notification-router` 배포 시 생성돼요.

즉, **배포 순서가 잘못된 거였어요**.

| Lambda | 역할 | 필요한 배포 순서 |
|--------|------|-----------------|
| notification-router | SNS Topic 생성 | **먼저** |
| fcm-notifier | SNS Topic 구독 | 나중에 |

새로운 알림 채널(FCM)을 추가하면서 `notification-router`에 `FcmNotificationsTopic` 리소스를 추가했는데, 이걸 배포하지 않고 `fcm-notifier`부터 배포하려고 했던 거죠.

> 💡 **왜 notification-router에서 SNS Topic을 생성할까?**
>
> 처음엔 "각 notifier가 자기 Topic을 만들면 되지 않나?" 생각했어요.
>
> 근데 그러면 문제가 생겨요. **notification-router가 publish할 Topic ARN을 미리 알 수 없거든요.**
>
> router 입장에서는 "EMAIL 타입이면 gmail-notifications Topic으로 보내야지"라고 알고 있어야 해요. 그래서 **router가 Topic을 소유**하고, notifier들이 **구독**하는 구조가 자연스러워요.
>
> 물론 다른 방법도 있어요:
> - Terraform으로 SNS Topic을 별도 관리
> - SSM Parameter Store에 Topic ARN 저장
>
> 우리는 "Serverless Framework로 한 번에 관리"하는 게 편해서 이 방식을 선택했어요.

---

## 해결

단순해요. SNS Topic을 생성하는 Lambda를 먼저 배포하면 돼요.

```bash
# 1. notification-router 먼저 (SNS Topic 생성)
cd apps/lambdas/notification-router
pnpm run deploy:dev

# 배포 완료 후 SNS Topic이 생성됨
# ✔ Service deployed to stack test-notification-router-dev

# 2. fcm-notifier 배포 (SNS Topic 구독)
cd apps/lambdas/fcm-notifier
pnpm run deploy:dev

# 이제 정상 배포됨
# ✔ Service deployed to stack test-fcm-notifier-dev
```

---

## 같은 스택에서 처리하는 방법

만약 Topic 생성과 구독을 **하나의 Lambda 프로젝트**에서 처리하고 싶다면, CloudFormation Ref를 사용할 수 있어요:

```yaml
functions:
  lambda:
    handler: src/index.handler
    events:
      - sns:
          arn:
            Ref: MyNotificationsTopic  # 같은 스택의 리소스 참조

resources:
  Resources:
    MyNotificationsTopic:
      Type: AWS::SNS::Topic
      Properties:
        TopicName: my-notifications-${self:provider.stage}
```

이 방식은 CloudFormation이 의존성을 자동으로 해결해서, Topic이 생성된 후 구독을 설정해요.

다만 우리 시스템처럼 **라우터와 notifier를 분리**한 구조에서는 이 방법을 쓸 수 없어요. SNS Topic은 라우터에서 생성하고, 각 notifier는 해당 Topic을 구독해야 하니까요.

---

## 배포 순서 자동화

### 1. 배포 스크립트 작성

```bash
#!/bin/bash
# deploy-notification-system.sh

echo "Deploying notification-router (creates SNS topics)..."
cd apps/lambdas/notification-router && pnpm run deploy:dev

echo "Deploying notifier lambdas..."
cd ../gmail-notifier && pnpm run deploy:dev &
cd ../slack-notifier && pnpm run deploy:dev &
cd ../fcm-notifier && pnpm run deploy:dev &
wait

echo "Done!"
```

### 2. CI/CD 파이프라인에서 순서 지정

GitHub Actions에서 job 의존성을 설정하면 돼요:

```yaml
jobs:
  deploy-router:
    runs-on: ubuntu-latest
    steps:
      - name: Deploy notification-router
        run: cd apps/lambdas/notification-router && pnpm run deploy:dev

  deploy-notifiers:
    needs: deploy-router  # router 배포 완료 후 실행
    runs-on: ubuntu-latest
    strategy:
      matrix:
        notifier: [gmail, slack, fcm, kakao]
    steps:
      - name: Deploy ${{ matrix.notifier }}-notifier
        run: cd apps/lambdas/${{ matrix.notifier }}-notifier && pnpm run deploy:dev
```

> 💡 **GitHub Actions matrix로 병렬 배포하기**
>
> notifier Lambda들은 서로 의존성이 없어서 **병렬로 배포**할 수 있어요.
> `strategy.matrix`를 사용하면 4개의 notifier가 동시에 배포돼서 시간을 절약할 수 있어요.
>
> 단, `needs: deploy-router`로 **router 배포 완료 후**에 실행되도록 해야 해요.

---

## 운영 중 트러블슈팅

### CloudWatch 로그 확인

```bash
# 로그 스트리밍
pnpm run logs:dev

# 또는 직접 AWS CLI로
aws logs tail /aws/lambda/notification-router-dev --follow
```

### DLQ(Dead Letter Queue) 메시지 확인

실패한 메시지는 DLQ로 가요. 콘솔에서 확인하거나 CLI로 확인할 수 있어요:

```bash
aws sqs receive-message \
  --queue-url https://sqs.ap-northeast-2.amazonaws.com/xxx/notification-dlq-dev \
  --max-number-of-messages 10
```

> 💡 **DLQ 메시지, 재처리는 어떻게?**
>
> 개발 중에 고민했던 부분이에요. DLQ에 쌓인 메시지를 어떻게 재처리할까?
>
> 몇 가지 방법이 있어요:
> 1. **수동 재처리**: 콘솔에서 메시지 확인 후 원본 큐로 다시 전송
> 2. **자동 재처리 Lambda**: DLQ를 구독하는 Lambda로 자동 재시도
> 3. **SQS Redrive**: AWS 콘솔의 "Start DLQ redrive" 기능 사용
>
> 우리는 현재 수동 확인 + SQS Redrive를 쓰고 있어요.
> 나중에 DLQ 메시지가 많아지면 자동 재처리 Lambda를 추가할 예정이에요.

### 흔한 에러들

| 에러 | 원인 | 해결 |
|------|------|------|
| Topic does not exist | 배포 순서 문제 | router 먼저 배포 |
| Access Denied | IAM 권한 부족 | sns:Publish 권한 추가 |
| Timeout | Lambda 타임아웃 | timeout 값 증가 또는 코드 최적화 |
| Rate Exceeded | SNS 발송 제한 | 배치 처리 또는 발송 간격 조절 |

---

## 시리즈를 마치며

5개의 글에 걸쳐 멀티채널 알림 시스템 구축 과정을 정리했어요.

### 배운 점들

1. **메시지 기반 아키텍처의 장점**: API 응답 시간과 알림 발송을 분리해서 서로 영향을 주지 않아요.

2. **SQS + SNS 조합**: SQS로 안정성(재시도, DLQ)을 확보하고, SNS로 채널별 분기를 쉽게 처리할 수 있어요.

3. **LocalStack의 가치**: 로컬에서 AWS 서비스를 테스트할 수 있어서 개발 속도가 빨라지고, 비용도 절약돼요.

4. **배포 순서의 중요성**: 마이크로서비스 아키텍처에서 공유 리소스의 배포 순서를 항상 고려해야 해요.

### 앞으로 할 일

- [ ] DLQ 자동 재처리 Lambda 추가
- [ ] 알림 발송 성공/실패 메트릭 수집 (CloudWatch Metrics)
- [ ] 알림 히스토리 저장 (DynamoDB)
- [ ] 사용자별 알림 설정 (채널 on/off)

이 시리즈가 비슷한 시스템을 구축하시는 분들께 도움이 되면 좋겠어요. 질문이나 피드백은 언제든 환영합니다! 🙌

---

## 시리즈 링크

- [Part 1: 아키텍처 설계](/posts/notification-system-part1-architecture)
- [Part 2: notification-router 구현](/posts/notification-system-part2-router)
- [Part 3: Notifier Lambda 구현](/posts/notification-system-part3-notifiers)
- [Part 4: LocalStack으로 로컬 테스트](/posts/notification-system-part4-localstack)
- **Part 5: 배포 및 트러블슈팅** (현재 글)
