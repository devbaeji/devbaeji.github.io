---
title: "멀티채널 알림 시스템 구축기 (3) - Notifier Lambda 구현"
date: 2025-01-08 18:00:00 +0900
categories: [Backend, 알림 시스템]
tags: [aws, lambda, gmail, slack, fcm, firebase, nodemailer, typescript]
---

## 시리즈

| Part | 주제 |
|------|------|
| [Part 1](/posts/notification-system-part1-architecture) | 아키텍처 설계 |
| [Part 2](/posts/notification-system-part2-router) | notification-router 구현 |
| **Part 3** | Notifier Lambda 구현 (현재 글) |
| [Part 4](/posts/notification-system-part4-localstack) | LocalStack으로 로컬 테스트 |
| [Part 5](/posts/notification-system-part5-deployment) | 배포 및 트러블슈팅 |

---

## Notifier Lambda 개요

각 Notifier는 **SNS Topic을 구독**하고, 메시지가 오면 **실제 외부 서비스를 호출**해서 알림을 발송해요.

| Notifier | 외부 서비스 | 인증 방식 |
|----------|-----------|----------|
| gmail-notifier | Gmail SMTP | Google App Password |
| slack-notifier | Slack Webhook | Webhook URL |
| fcm-notifier | Firebase FCM | Service Account JSON |
| kakao-notifier | 카카오 알림톡 API | API Key |

---

## 1. gmail-notifier

### 핵심 로직

```typescript
import { SNSEvent, Context } from 'aws-lambda';
import { SecretsManagerClient, GetSecretValueCommand } from '@aws-sdk/client-secrets-manager';
import nodemailer from 'nodemailer';

// Gmail 인증 정보 캐시 (Lambda 재사용 시 성능 향상)
let cachedGmailCredentials: { user: string; password: string } | null = null;

async function getGmailCredentials() {
  if (cachedGmailCredentials) {
    return cachedGmailCredentials;
  }

  const secretName = process.env.GMAIL_SECRET_NAME || 'develop/apps/gmail';
  const command = new GetSecretValueCommand({ SecretId: secretName });
  const response = await secretsClient.send(command);

  const secret = JSON.parse(response.SecretString!);
  cachedGmailCredentials = {
    user: secret.username,
    password: secret.password,
  };

  return cachedGmailCredentials;
}
```

인증 정보는 **AWS Secrets Manager**에서 가져와요. 그리고 `cachedGmailCredentials`에 캐시해서 **Lambda가 재사용될 때 Secrets Manager 호출을 줄여요**.

> 💡 **Lambda에서 인증 정보 캐싱, 안전한가요?**
>
> Lambda는 실행이 끝나도 컨테이너가 바로 죽지 않아요. 다음 호출이 빨리 오면 같은 컨테이너에서 실행되거든요. (이걸 "웜 스타트"라고 해요)
>
> 그래서 **모듈 레벨 변수**에 인증 정보를 캐싱하면, 웜 스타트 시 Secrets Manager 호출을 건너뛸 수 있어요.
>
> 보안 걱정? Lambda 컨테이너는 **격리된 환경**이고, 메모리는 컨테이너가 죽으면 같이 사라지니까 괜찮아요.

### 이메일 발송

```typescript
async function sendEmail(notification: EmailNotificationMessage) {
  const credentials = await getGmailCredentials();

  const transporter = nodemailer.createTransport({
    service: 'gmail',
    auth: {
      user: credentials.user,
      pass: credentials.password,
    },
  });

  const mailOptions = {
    from: `mytest Workspace <${credentials.user}>`,
    to: notification.recipient,
    subject: notification.subject || 'mytest Workspace 알림',
    text: notification.message,
    html: `
      <div style="font-family: Arial, sans-serif; padding: 20px;">
        <h2>mytest Workspace 알림</h2>
        <p>${notification.message}</p>
        <hr>
        <p style="color: #999; font-size: 12px;">
          발송 시간: ${notification.timestamp}
        </p>
      </div>
    `,
  };

  await transporter.sendMail(mailOptions);
}
```

**Nodemailer**로 Gmail SMTP를 사용해요. `service: 'gmail'`만 설정하면 SMTP 호스트/포트는 알아서 설정되더라고요.

> 💡 **Gmail App Password vs OAuth2**
>
> Gmail 인증은 두 가지 방법이 있어요:
> 1. **App Password**: 2단계 인증 후 생성하는 16자리 비밀번호. 간단함.
> 2. **OAuth2**: 더 안전하지만 설정이 복잡하고, 토큰 갱신 로직 필요.
>
> 우리는 **App Password**를 선택했어요. 이유:
> - Lambda에서 OAuth 토큰 갱신 로직 관리가 번거로움
> - 발신 전용 계정이라 App Password로도 충분
> - Secrets Manager로 관리하면 언제든 변경 가능

### Secrets Manager에 저장하는 형식

```json
{
  "username": "noreply@yourcompany.com",
  "password": "abcd efgh ijkl mnop"
}
```

AWS 콘솔에서 `develop/apps/gmail` 이름으로 Secret 생성하면 돼요.

---

## 2. slack-notifier

### 핵심 로직

```typescript
import { IncomingWebhook } from '@slack/webhook';

async function sendSlackMessage(notification: SlackNotificationMessage) {
  const webhookUrl = notification.recipient.startsWith('http')
    ? notification.recipient
    : process.env.SLACK_WEBHOOK_URL;

  if (!webhookUrl) {
    throw new Error('Slack webhook URL not configured');
  }

  const webhook = new IncomingWebhook(webhookUrl);

  const slackMessage = {
    text: notification.message,
    blocks: [
      {
        type: 'header',
        text: {
          type: 'plain_text',
          text: notification.metadata?.title || 'mytest Workspace 알림',
        },
      },
      {
        type: 'section',
        text: {
          type: 'mrkdwn',
          text: notification.message,
        },
      },
      {
        type: 'context',
        elements: [
          {
            type: 'mrkdwn',
            text: `발송 시간: ${notification.timestamp}`,
          },
        ],
      },
    ],
  };

  await webhook.send(slackMessage);
}
```

Slack은 **Incoming Webhook**으로 메시지를 보내요. `@slack/webhook` 패키지가 있어서 간단하더라고요.

### Block Kit으로 꾸미기

```typescript
blocks: [
  {
    type: 'header',
    text: { type: 'plain_text', text: '작업 일정 배정' },
  },
  {
    type: 'section',
    text: { type: 'mrkdwn', text: '2025년 1월 10일 작업이 배정되었습니다.' },
  },
  {
    type: 'section',
    fields: [
      { type: 'mrkdwn', text: '*담당자*\n홍길동' },
      { type: 'mrkdwn', text: '*현장*\n서울시 강남구' },
    ],
  },
]
```

Slack Block Kit을 쓰면 **리치한 메시지**를 만들 수 있어요. `metadata.fields`로 추가 정보를 넘기면 자동으로 표 형태로 표시해요.

---

## 3. fcm-notifier

### Firebase 초기화

```typescript
import admin from 'firebase-admin';
import { SecretsManagerClient, GetSecretValueCommand } from '@aws-sdk/client-secrets-manager';

let firebaseInitialized = false;

async function initializeFirebase() {
  if (firebaseInitialized) {
    return;
  }

  const secretName = process.env.FIREBASE_SECRET_NAME || 'develop/apps/firebase';
  const command = new GetSecretValueCommand({ SecretId: secretName });
  const response = await secretsClient.send(command);

  const serviceAccount = JSON.parse(response.SecretString!);

  admin.initializeApp({
    credential: admin.credential.cert(serviceAccount),
  });

  firebaseInitialized = true;
}
```

Firebase Admin SDK는 **Service Account JSON**으로 인증해요. 이것도 Secrets Manager에 저장하고, **한 번만 초기화**하도록 플래그를 둬요.

### 멀티캐스트 전송

```typescript
async function sendFcmNotification(
  fcmTokens: string[],
  message: MultiNotificationMessage
) {
  await initializeFirebase();

  const fcmMessage: admin.messaging.MulticastMessage = {
    tokens: fcmTokens,
    notification: {
      title: message.message.title,
      body: message.message.body,
    },
    data: message.metadata?.data,
    android: {
      priority: 'high',
      notification: {
        sound: 'default',
      },
    },
    apns: {
      payload: {
        aps: {
          sound: 'default',
          badge: message.metadata?.badge ?? 1,
        },
      },
    },
  };

  const response = await admin.messaging().sendEachForMulticast(fcmMessage);

  console.log(`FCM sent: ${response.successCount} success, ${response.failureCount} failures`);
}
```

`sendEachForMulticast`를 쓰면 **여러 디바이스에 한 번에** 푸시를 보낼 수 있어요.

> 💡 **FCM 토큰 관리, 이게 제일 골치 아팠어요**
>
> FCM 토큰은 여러 이유로 **무효화**될 수 있어요:
> - 앱 삭제/재설치
> - 토큰 갱신 (iOS는 주기적으로 갱신됨)
> - 오랫동안 앱 미사용
>
> 그래서 전송 결과를 꼭 확인해야 해요:
>
> ```typescript
> if (response.failureCount > 0) {
>   response.responses.forEach((resp, idx) => {
>     if (!resp.success) {
>       const errorCode = resp.error?.code;
>       if (
>         errorCode === 'messaging/invalid-registration-token' ||
>         errorCode === 'messaging/registration-token-not-registered'
>       ) {
>         // 이 토큰은 DB에서 비활성화해야 함
>         failedTokens.push(fcmTokens[idx]);
>       }
>     }
>   });
> }
> ```
>
> 무효 토큰을 계속 사용하면 **FCM 할당량 낭비**고, 에러 로그도 쌓여요.
> 현재는 로그만 남기고 있는데, 나중에 **토큰 정리 Lambda**를 따로 만들 예정이에요.

### Android vs iOS 설정

```typescript
android: {
  priority: 'high',  // 중요 알림은 즉시 전달
  notification: {
    clickAction: 'FLUTTER_NOTIFICATION_CLICK',
    sound: 'default',
  },
},
apns: {
  payload: {
    aps: {
      sound: 'default',
      badge: 1,  // 앱 아이콘 배지 숫자
    },
  },
},
```

Android와 iOS는 **푸시 설정이 달라요**. 둘 다 지원하려면 이렇게 각각 설정해줘야 해요.

---

## 4. kakao-notifier

### 알림톡 vs 친구톡

```typescript
async function sendKakaoMessage(notification: KakaoNotificationMessage) {
  const kakaoApiKey = process.env.KAKAO_API_KEY;
  const kakaoSenderKey = process.env.KAKAO_SENDER_KEY;

  const messagePayload: any = {
    receiver_uuids: [notification.recipient],
  };

  if (notification.metadata?.templateId) {
    // 알림톡 (승인된 템플릿 사용)
    messagePayload.template_id = notification.metadata.templateId;
    messagePayload.template_args = notification.metadata.templateArgs;
  } else {
    // 친구톡 (자유 메시지)
    messagePayload.template_object = {
      object_type: 'text',
      text: notification.message,
      link: {
        web_url: 'https://mytest.com',
      },
    };
  }

  await fetch('https://kapi.kakao.com/v1/api/talk/friends/message/default/send', {
    method: 'POST',
    headers: {
      Authorization: `Bearer ${kakaoApiKey}`,
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: new URLSearchParams(messagePayload).toString(),
  });
}
```

> 💡 **카카오 알림톡, 생각보다 까다로웠어요**
>
> 알림톡은 **사전에 템플릿 승인**을 받아야 해요. 자유 메시지 안 됨.
> 친구톡은 자유 메시지가 되지만, 사용자가 **카카오톡 채널을 친구 추가**해야 해요.
>
> 우리는 두 가지를 모두 지원하도록 했어요:
> - `templateId`가 있으면 → 알림톡
> - 없으면 → 친구톡
>
> 근데 실제로는 알림톡 위주로 쓰고 있어요. 마케팅 동의 없이 보낼 수 있거든요.

---

## 공통 패턴: 로컬 환경 감지

모든 Notifier에 이 로직이 있어요:

```typescript
const isLocal = context.invokedFunctionArn.includes('000000000000')
  || context.functionName.includes('local');

if (isLocal) {
  console.log('🔧 로컬 환경: 메시지 전송 시뮬레이션');
  console.log({
    recipient: notification.recipient,
    message: notification.message,
  });
  return; // 실제 전송 안 함
}
```

LocalStack에서 실행하면 `invokedFunctionArn`에 `000000000000` (가짜 계정 ID)이 들어가요. 이걸 감지해서 **실제 외부 서비스 호출을 막아요**.

로컬에서 테스트할 때마다 진짜 이메일이 가면 곤란하잖아요. 😅

---

## 공통 패턴: 에러 처리

```typescript
for (const record of event.Records) {
  try {
    await processMessage(record);
    console.log(`✅ Successfully processed: ${record.messageId}`);
  } catch (error) {
    console.error(`❌ Failed: ${record.messageId}`, error);
    batchItemFailures.push({ itemIdentifier: record.messageId });
  }
}

return { batchItemFailures };
```

실패한 메시지만 **SQS에서 재시도**하도록 `batchItemFailures`에 추가해요. 성공한 건 다시 처리 안 하고요.

> 💡 **DLQ(Dead Letter Queue)로 빠진 메시지, 어떻게 처리할까?**
>
> 재시도를 계속 실패하면 결국 DLQ로 가요. 문제는 "왜 실패했는지" 파악하기가 어렵다는 거예요.
>
> 현재 해결책:
> 1. **CloudWatch에 상세 로그**: 실패 원인, 원본 메시지, 스택 트레이스
> 2. **DLQ 모니터링 알람**: DLQ에 메시지가 쌓이면 Slack 알림
> 3. **(계획 중)** DLQ 처리 Lambda: 메시지를 읽어서 수동 재처리 UI 제공
>
> 아직 완벽하진 않지만, 일단 **로그를 잘 남겨두면** 나중에 원인 파악이 수월해요.

---

## 의존성 (package.json)

```json
{
  "dependencies": {
    "@aws-sdk/client-secrets-manager": "^3.693.0",
    "nodemailer": "^7.0.0"
  }
}
```

```json
{
  "dependencies": {
    "@slack/webhook": "^7.0.2"
  }
}
```

```json
{
  "dependencies": {
    "firebase-admin": "^12.0.0"
  }
}
```

각 Notifier마다 필요한 의존성만 설치해요. Lambda 번들 크기를 줄이기 위해서요.

---

## 다음 글 예고

다음 글에서는 **LocalStack으로 로컬 테스트 환경**을 구축하는 방법을 다룰 거예요.

- Docker Compose로 LocalStack 실행
- SQS, SNS 자동 생성 스크립트
- Lambda 디버깅 (브레이크포인트까지!)

---

## 시리즈 링크

- [Part 1: 아키텍처 설계](/posts/notification-system-part1-architecture)
- [Part 2: notification-router 구현](/posts/notification-system-part2-router)
- **Part 3: Notifier Lambda 구현** (현재 글)
- [Part 4: LocalStack으로 로컬 테스트](/posts/notification-system-part4-localstack)
- [Part 5: 배포 및 트러블슈팅](/posts/notification-system-part5-deployment)
