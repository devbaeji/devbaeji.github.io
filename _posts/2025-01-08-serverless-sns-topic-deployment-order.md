---
title: "Serverless Framework에서 SNS Topic does not exist 에러 해결하기"
date: 2025-01-08 15:00:00 +0900
categories: [Troubleshooting]
tags: [serverless, aws, sns, lambda, cloudformation, deployment]
---

## 배경

현재 서비스에 **실시간 알림 시스템**을 구축하고 있습니다. 요구사항은 단순했습니다. 사용자에게 이메일, Slack, 카카오톡, FCM 푸시 등 다양한 채널로 알림을 보내야 했죠.

처음에는 API 서버에서 직접 알림을 발송하는 방식을 고려했지만, 몇 가지 문제가 있었습니다:

- 알림 발송이 실패하면 원래 요청까지 영향을 받음
- 알림 채널이 추가될 때마다 API 서버 코드를 수정해야 함
- 대량 알림 발송 시 API 서버에 부하가 집중됨

그래서 **비동기 메시지 기반 아키텍처**를 선택했습니다.

```
[API Server]
    → [SQS Queue] (메시지 버퍼)
        → [notification-router Lambda] (메시지 라우팅)
            → [SNS Topics] (채널별 토픽)
                → [gmail-notifier Lambda]
                → [slack-notifier Lambda]
                → [kakao-notifier Lambda]
                → [fcm-notifier Lambda]
```

API 서버는 SQS에 메시지만 던지고 바로 응답합니다. 이후 Lambda가 메시지를 소비하고, 알림 타입에 따라 적절한 SNS Topic으로 라우팅합니다. 각 notifier Lambda는 자신이 담당하는 Topic을 구독해서 실제 알림을 발송하는 구조입니다.

이 구조의 장점은 **느슨한 결합**입니다. 새로운 알림 채널이 필요하면 SNS Topic 하나와 Lambda 하나만 추가하면 됩니다. 기존 코드는 건드릴 필요가 없죠.

---

## 문제 상황

FCM 푸시 알림을 위한 `fcm-notifier` Lambda를 새로 만들고 배포하려는데, 이런 에러가 발생했습니다.

![터미널 에러 메시지](/assets/img/posts/2025-01-08-serverless-sns/terminal-error.png)
_Serverless 배포 시 발생한 SNS Topic 에러_

```
Error:
CREATE_FAILED: LambdaSnsSubscriptionFcmnotificationsdev (AWS::SNS::Subscription)
Resource handler returned message: "Topic does not exist
(Service: Sns, Status Code: 404, Request ID: ef440541-7fc4-59dc-a627-64982a009534)"
```

AWS CloudFormation 콘솔에서도 스택이 `UPDATE_ROLLBACK_COMPLETE` 상태로 롤백된 걸 확인할 수 있었습니다.

![CloudFormation 콘솔](/assets/img/posts/2025-01-08-serverless-sns/cloudformation-rollback.png)
_CloudFormation 스택이 롤백된 상태_

처음엔 IAM 권한 문제인가 싶어서 정책을 확인해봤는데, 권한은 정상이었습니다.

---

## 원인 분석

에러 메시지를 다시 읽어보니 답이 있었습니다. **"Topic does not exist"** - SNS Topic 자체가 없다는 거였죠.

### 우리 시스템의 SNS Topic 생성 위치

`fcm-notifier`의 `serverless.yml`을 보면, 이미 존재하는 SNS Topic ARN을 직접 참조하고 있습니다:

```yaml
# apps/lambdas/fcm-notifier/serverless.yml
functions:
  lambda:
    handler: src/index.handler
    events:
      - sns:
          arn: arn:aws:sns:ap-northeast-2:225179063068:fcm-notifications-dev
```

그런데 이 `fcm-notifications-dev` Topic은 어디서 생성될까요? `notification-router`의 CloudFormation 리소스에서 생성됩니다:

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

`fcm-notifier`를 배포하려면 `fcm-notifications-dev` Topic이 **이미 AWS에 존재해야** 합니다. 그런데 이 Topic은 `notification-router` 배포 시 생성됩니다.

즉, **배포 순서가 잘못된 거였습니다**.

| Lambda | 역할 | 필요한 배포 순서 |
|--------|------|-----------------|
| notification-router | SNS Topic 생성 | **먼저** |
| fcm-notifier | SNS Topic 구독 | 나중에 |

새로운 알림 채널(FCM)을 추가하면서 `notification-router`에 `FcmNotificationsTopic` 리소스를 추가했는데, 이걸 배포하지 않고 `fcm-notifier`부터 배포하려고 했던 거죠.

---

## 해결

단순합니다. SNS Topic을 생성하는 Lambda를 먼저 배포하면 됩니다.

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

만약 Topic 생성과 구독을 **하나의 Lambda 프로젝트**에서 처리하고 싶다면, CloudFormation Ref를 사용할 수 있습니다:

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

이 방식은 CloudFormation이 의존성을 자동으로 해결해서, Topic이 생성된 후 구독을 설정합니다.

다만 우리 시스템처럼 **라우터와 notifier를 분리**한 구조에서는 이 방법을 쓸 수 없습니다. SNS Topic은 라우터에서 생성하고, 각 notifier는 해당 Topic을 구독해야 하니까요.

---

## (추후) 배포 순서 관리

마이크로서비스 아키텍처에서 이런 의존성 문제는 흔하게 발생합니다. 몇 가지 방법으로 관리할 수 있습니다.

### 1. README에 배포 순서 문서화

```markdown
## 배포 순서

1. `notification-router` (SNS Topics 생성)
2. 각 notifier Lambda들 (병렬 배포 가능)
   - gmail-notifier
   - slack-notifier
   - kakao-notifier
   - fcm-notifier
```

### 2. 배포 스크립트 작성

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

### 3. CI/CD 파이프라인에서 순서 지정

GitHub Actions나 GitLab CI에서 job 의존성을 설정하면 됩니다.

---

## 정리

"Topic does not exist" 에러를 보면 권한 문제부터 의심하기 쉬운데, 사실 대부분은 **리소스가 아직 생성되지 않은 것**입니다.

해결 방법은 간단합니다:
1. 해당 SNS Topic이 AWS에 존재하는지 확인
2. 존재하지 않으면, 어떤 서비스가 생성하는지 파악
3. 생성하는 서비스를 먼저 배포

마이크로서비스 아키텍처에서 공유 리소스(SNS, SQS 등)를 다룰 때는 **배포 순서**를 항상 염두에 두어야 합니다. 가능하면 배포 스크립트나 CI/CD 파이프라인으로 자동화해두는 게 좋습니다. 수동으로 하면 언젠가 또 같은 실수를 하게 되니까요.
