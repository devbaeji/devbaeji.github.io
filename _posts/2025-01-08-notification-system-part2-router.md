---
title: "멀티채널 알림 시스템 구축기 (2) - notification-router 구현"
date: 2025-01-08 17:30:00 +0900
categories: [Backend, 알림 시스템]
tags: [aws, sqs, sns, lambda, typescript, serverless]
---

## 시리즈

| Part | 주제 |
|------|------|
| [Part 1](/posts/notification-system-part1-architecture) | 아키텍처 설계 |
| **Part 2** | notification-router 구현 (현재 글) |
| [Part 3](/posts/notification-system-part3-notifiers) | Notifier Lambda 구현 |
| [Part 4](/posts/notification-system-part4-localstack) | LocalStack으로 로컬 테스트 |
| [Part 5](/posts/notification-system-part5-deployment) | 배포 및 트러블슈팅 |

---

## notification-router의 역할

notification-router는 **메시지 분배기**예요. SQS에서 메시지를 받아서, `types` 배열을 보고 해당하는 SNS Topic들로 뿌려주는 역할이죠.

```
[SQS] ─── types: ["EMAIL", "FCM"] ───▶ [notification-router]
                                              │
                                              ├──▶ gmail-notifications SNS
                                              └──▶ fcm-notifications SNS
```

---

## Lambda 코드 구현

### 전체 구조

```typescript
// src/index.ts
import { SQSEvent, SQSBatchResponse, SQSRecord, Context } from 'aws-lambda';
import { SNSClient, PublishCommand } from '@aws-sdk/client-sns';

// LocalStack vs AWS 환경 자동 감지
const isLocalStack = !!process.env.LOCALSTACK_ENDPOINT;

// SNS Client 설정
const snsClient = new SNSClient({
  region: process.env.AWS_REGION || 'ap-northeast-2',
  ...(isLocalStack && {
    endpoint: process.env.LOCALSTACK_ENDPOINT,
    credentials: {
      accessKeyId: 'test',
      secretAccessKey: 'test',
    },
  }),
});
```

처음부터 **LocalStack 지원**을 염두에 뒀어요. `LOCALSTACK_ENDPOINT` 환경변수가 있으면 로컬 환경으로 인식하고, 없으면 실제 AWS를 사용해요.

### SNS Topic ARN 매핑

```typescript
const SNS_TOPIC_ARNS: Record<string, string> = {
  EMAIL: process.env.SNS_TOPIC_EMAIL ||
    'arn:aws:sns:ap-northeast-2:000000000000:gmail-notifications-sns-local',
  SLACK: process.env.SNS_TOPIC_SLACK ||
    'arn:aws:sns:ap-northeast-2:000000000000:slack-notifications-sns-local',
  KAKAO: process.env.SNS_TOPIC_KAKAO ||
    'arn:aws:sns:ap-northeast-2:000000000000:kakao-notifications-sns-local',
  FCM: process.env.SNS_TOPIC_FCM ||
    'arn:aws:sns:ap-northeast-2:000000000000:fcm-notifications-sns-local',
  SMS: process.env.SNS_TOPIC_SMS ||
    'arn:aws:sns:ap-northeast-2:000000000000:sms-notifications-sns-local',
};
```

환경변수로 ARN을 받고, 없으면 LocalStack 기본값을 사용해요. 이렇게 하면 **같은 코드**로 로컬과 AWS 양쪽에서 동작해요.

### 메시지 타입 정의

```typescript
interface MultiNotificationMessage {
  types: string[];
  recipients: {
    phoneNumber?: string;
    email?: string;
    slackChannelId?: string;
    kakaoUserId?: string;
    fcmTokens?: string[];
  };
  message: {
    title: string;
    body: string;
  };
  timestamp: string;
  metadata?: Record<string, any>;
}
```

API 서버에서 보내는 메시지 구조와 동일해요. TypeScript를 쓰니까 **타입 불일치를 컴파일 타임에 잡을 수** 있어서 좋더라고요.

### Handler 구현

```typescript
export const handler = async (
  event: SQSEvent,
  context: Context
): Promise<SQSBatchResponse> => {
  console.log('Notification Router Lambda invoked');

  const batchItemFailures: SQSBatchResponse['batchItemFailures'] = [];

  for (const record of event.Records) {
    try {
      await routeNotification(record);
      console.log(`✅ Successfully routed message: ${record.messageId}`);
    } catch (error) {
      console.error(`❌ Failed to route message ${record.messageId}:`, error);
      // 실패한 메시지는 다시 큐로 반환
      batchItemFailures.push({ itemIdentifier: record.messageId });
    }
  }

  return { batchItemFailures };
};
```

여기서 중요한 건 **`batchItemFailures`** 반환이에요. SQS 배치 처리에서 일부만 실패했을 때, 실패한 것만 다시 큐로 돌려보내는 기능이에요.

> 💡 **Partial Batch Response (부분 배치 응답)**
>
> SQS Lambda 트리거에서 `functionResponseType: ReportBatchItemFailures`를 설정하면,
> 10개 메시지 중 2개만 실패해도 **2개만 재시도**할 수 있어요.
>
> 이 설정이 없으면 1개라도 실패하면 10개 전체를 재시도해야 해요.
> 우리처럼 메시지별로 독립적인 처리가 필요한 경우 필수 설정이에요.

### 라우팅 로직

```typescript
async function routeNotification(record: SQSRecord): Promise<void> {
  const messageBody = JSON.parse(record.body) as MultiNotificationMessage;

  // types 배열 검증
  if (!messageBody.types || messageBody.types.length === 0) {
    throw new Error('Invalid message format: types array required');
  }

  // 각 타입별로 해당 SNS Topic에 publish
  const publishPromises = messageBody.types.map(async (type) => {
    const topicArn = SNS_TOPIC_ARNS[type];

    if (!topicArn) {
      console.warn(`⚠️ Unknown notification type: ${type}. Skipping.`);
      return;
    }

    const command = new PublishCommand({
      TopicArn: topicArn,
      Message: JSON.stringify(messageBody),
      Subject: `Notification: ${messageBody.message.title}`,
      MessageAttributes: {
        NotificationType: {
          DataType: 'String',
          StringValue: type,
        },
      },
    });

    await snsClient.send(command);
    console.log(`✅ Published to ${type} topic`);
  });

  await Promise.all(publishPromises);
}
```

`types` 배열을 순회하면서 **각 타입에 해당하는 SNS Topic으로 publish**해요. `Promise.all`로 병렬 처리해서 속도도 빠르고요.

---

## Serverless Framework 설정

### serverless.yml

```yaml
service: mytest-notification-router

provider:
  name: aws
  runtime: nodejs20.x
  region: ap-northeast-2
  stage: ${opt:stage, 'dev'}
  memorySize: 256
  timeout: 30
  environment:
    # SNS Topic ARNs - CloudFormation Ref 사용
    SNS_TOPIC_EMAIL:
      Ref: GmailNotificationsTopic
    SNS_TOPIC_SLACK:
      Ref: SlackNotificationsTopic
    SNS_TOPIC_KAKAO:
      Ref: KakaoNotificationsTopic
    SNS_TOPIC_FCM:
      Ref: FcmNotificationsTopic
    SNS_TOPIC_SMS:
      Ref: SmsNotificationsTopic
```

환경변수로 SNS Topic ARN을 주입하는데, 하드코딩하지 않고 **CloudFormation Ref**를 사용해요. 이렇게 하면 stage별로 다른 Topic을 자동으로 참조할 수 있어요.

### IAM 권한 설정

```yaml
provider:
  iam:
    role:
      statements:
        - Effect: Allow
          Action:
            - sns:Publish
          Resource:
            - Ref: GmailNotificationsTopic
            - Ref: SlackNotificationsTopic
            - Ref: KakaoNotificationsTopic
            - Ref: SmsNotificationsTopic
            - Ref: FcmNotificationsTopic
```

**최소 권한 원칙**을 따라서, 이 Lambda가 publish할 수 있는 Topic만 명시했어요. `sns:*`로 전체 권한을 주면 편하긴 한데, 보안상 좋지 않죠.

> 💡 **IAM 최소 권한 원칙, 왜 중요할까?**
>
> 처음엔 "귀찮은데 그냥 `*` 쓰면 안 되나?" 했어요.
>
> 근데 Lambda가 해킹당하거나 버그로 이상한 동작을 하면, 권한이 넓을수록 피해 범위가 커져요.
> 우리 Lambda는 SNS Publish만 하면 되니까, 딱 그것만 허용하는 게 맞아요.
>
> Serverless Framework의 좋은 점이, CloudFormation Ref로 **동적으로 리소스를 참조**할 수 있어서
> 하드코딩 없이도 최소 권한을 구현할 수 있다는 거예요.

### SQS 트리거 설정

```yaml
functions:
  lambda:
    handler: src/index.handler
    events:
      - sqs:
          arn: arn:aws:sqs:${self:provider.region}:${self:custom.accountId}:notification-mytest-workspace-${self:provider.stage}
          batchSize: 10
          maximumBatchingWindow: 5
          functionResponseType: ReportBatchItemFailures
```

| 옵션 | 설명 |
|------|------|
| `batchSize: 10` | 한 번에 최대 10개 메시지 처리 |
| `maximumBatchingWindow: 5` | 최대 5초까지 배치를 모음 |
| `functionResponseType` | 부분 실패 시 실패한 것만 재시도 |

### SNS Topics 생성

```yaml
resources:
  Resources:
    GmailNotificationsTopic:
      Type: AWS::SNS::Topic
      Properties:
        TopicName: gmail-notifications-${self:provider.stage}
        DisplayName: Gmail Notifications Topic

    SlackNotificationsTopic:
      Type: AWS::SNS::Topic
      Properties:
        TopicName: slack-notifications-${self:provider.stage}

    # ... 나머지 Topic들
```

SNS Topic도 **notification-router의 serverless.yml에서 함께 생성**해요. 이렇게 하면 배포할 때 Topic이 자동으로 만들어지고, 환경변수에 ARN이 주입돼요.

> 💡 **SNS Topic을 어디서 생성할지 고민**
>
> 두 가지 선택지가 있었어요:
> 1. **Terraform으로 별도 관리**: 인프라와 애플리케이션 분리
> 2. **Serverless Framework에서 함께 생성**: 배포가 한 번에 끝남
>
> 우리는 2번을 선택했어요. Topic이 router와 밀접하게 연관되어 있고,
> Serverless로 한 번에 배포하는 게 편했거든요.
>
> 단점은 **배포 순서를 신경 써야 한다**는 거예요.
> notifier들이 Topic을 구독하려면, router가 먼저 배포되어 있어야 해요.

---

## 에러 처리 전략

### 개별 메시지 실패

```typescript
for (const record of event.Records) {
  try {
    await routeNotification(record);
  } catch (error) {
    console.error(`❌ Failed to route message ${record.messageId}:`, error);
    batchItemFailures.push({ itemIdentifier: record.messageId });
  }
}
```

메시지 하나가 실패해도 다른 메시지는 계속 처리해요. 실패한 메시지만 `batchItemFailures`에 추가해서 **SQS가 알아서 재시도**하게 해요.

### SNS Publish 실패

```typescript
const publishPromises = messageBody.types.map(async (type) => {
  try {
    await snsClient.send(command);
  } catch (error) {
    console.error(`❌ Failed to publish to ${type} topic:`, error);
    throw error; // 하나라도 실패하면 전체 메시지를 재시도
  }
});

await Promise.all(publishPromises);
```

여기서 고민이 있었어요. EMAIL은 성공했는데 FCM만 실패하면?

현재 구현은 **하나라도 실패하면 전체 메시지를 재시도**해요. EMAIL이 중복 발송될 수 있죠.

> 💡 **멱등성(Idempotency) 문제, 어떻게 해결할까?**
>
> router에서 EMAIL + FCM을 같이 보낼 때, FCM만 실패하면 재시도 시 EMAIL이 중복 발송돼요.
>
> 해결 방법으로 고민한 것들:
> 1. **메시지 ID 기반 중복 체크**: notifier에서 이미 처리한 메시지는 스킵
> 2. **타입별 독립 재시도**: 실패한 타입만 따로 재시도 큐에 넣기
> 3. **수신자 레벨 중복 방지**: 이메일 주소 + 메시지 해시로 중복 체크
>
> 현재는 **알림 특성상 중복이 치명적이지 않아서** 단순하게 가고 있어요.
> 나중에 문제가 되면 1번 방식으로 개선할 예정이에요.

---

## 테스트

### 로컬 테스트 (LocalStack)

```bash
# LocalStack 시작
cd localstack && docker-compose up -d

# notification-router 로컬 실행
cd apps/lambdas/notification-router && pnpm run local
```

자세한 내용은 Part 4에서 다룰게요.

### 배포 및 테스트

```bash
# 배포
pnpm run deploy:dev

# 로그 확인
pnpm run logs:dev
```

---

## 다음 글 예고

다음 글에서는 **실제 알림을 발송하는 Notifier Lambda들**을 다룰 거예요.

- gmail-notifier: Nodemailer + Secrets Manager
- slack-notifier: Slack Webhook
- fcm-notifier: Firebase Admin SDK

---

## 시리즈 링크

- [Part 1: 아키텍처 설계](/posts/notification-system-part1-architecture)
- **Part 2: notification-router 구현** (현재 글)
- [Part 3: Notifier Lambda 구현](/posts/notification-system-part3-notifiers)
- [Part 4: LocalStack으로 로컬 테스트](/posts/notification-system-part4-localstack)
- [Part 5: 배포 및 트러블슈팅](/posts/notification-system-part5-deployment)
