---
title: "모노레포에서 OpenAPI 타입을 중앙 집중 관리하는 방법"
date: 2025-12-10 10:00:00 +0900
categories: [Architecture, 설계 패턴]
tags: [monorepo, openapi, typescript, frontend, architecture]
---

## 서론: OpenAPI란 무엇이고, 왜 사용하는가?

### OpenAPI Specification이란?

[OpenAPI Specification(OAS)](https://en.wikipedia.org/wiki/OpenAPI_Specification)은 RESTful API를 기술하는 표준 명세이다. 원래 Swagger Specification으로 알려졌으며, API의 엔드포인트, 요청/응답 형식, 인증 방식 등을 JSON이나 YAML 형식으로 정의한다.

```yaml
# OpenAPI 스펙 예시
paths:
  /users/{id}:
    get:
      summary: 사용자 조회
      parameters:
        - name: id
          in: path
          required: true
          schema:
            type: integer
      responses:
        '200':
          description: 성공
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/UserResponse'
```

### 왜 OpenAPI를 사용하게 되었나?

프론트엔드와 백엔드가 분리된 환경에서 가장 흔한 문제는 **API 스펙 불일치**다.

```typescript
// 백엔드가 응답을 변경했는데 프론트엔드가 모른다면?
interface UserResponse {
  id: number;
  name: string;  // 백엔드는 이미 fullName으로 변경했는데...
}
```

이런 문제를 해결하기 위해 OpenAPI를 도입했다:

1. **단일 진실 공급원**: 백엔드 API 스펙이 자동으로 문서화됨
2. **타입 자동 생성**: 스펙에서 TypeScript 타입을 자동으로 생성
3. **컴파일 타임 검증**: API 변경 시 프론트엔드에서 즉시 타입 에러 발생

### 2024-2025 OpenAPI 트렌드

OpenAPI는 현재 **꾸준히 성장하는 추세**다.

| 지표 | 현황 |
|------|------|
| REST API 점유율 | 전체 웹 서비스의 83% ([RapidAPI Developer Survey](https://jsonconsole.com/blog/rest-api-vs-graphql-statistics-trends-performance-comparison-2025)) |
| OpenAPI 성장세 | GraphQL이 2022년 정점 후 횡보하는 동안 OpenAPI는 꾸준히 성장 ([WunderGraph](https://wundergraph.com/blog/graphql_rest_openapi_trend_analysis_2023)) |
| 업계 표준 채택 | IATA 같은 산업 표준이 OpenAPI 스펙 파일 요구 ([OpenAPI Initiative](https://www.openapis.org/blog/2024/12/23/openapi-initiative-newsletter-december-2024)) |

**API-First Development**가 새로운 표준이 되면서, API 계약을 먼저 정의하고 비즈니스 로직을 구현하는 **Contract-First 개발** 방식이 OpenAPI와 함께 주목받고 있다.

### OpenAPI vs GraphQL: 언제 무엇을 선택할까?

| 상황 | 추천 |
|------|------|
| 단순 CRUD, 캐싱 중요 | REST + OpenAPI |
| 복잡한 데이터 관계, 모바일 최적화 | GraphQL |
| 레거시 시스템 통합 | REST + OpenAPI |
| 빠른 프로토타이핑 | 팀 숙련도에 따라 선택 |

> GraphQL을 채택한 팀의 89%가 유사 프로젝트에서 다시 선택하겠다고 응답했다 ([Apollo GraphQL Developer Survey 2024](https://jsonconsole.com/blog/rest-api-vs-graphql-statistics-trends-performance-comparison-2025)). 하지만 REST가 여전히 83%의 점유율을 가지므로, OpenAPI 기반 REST API도 충분히 좋은 선택이다.
{: .prompt-info }

### OpenAPI 타입 생성의 장점

[TypeScript 타입 자동 생성](https://profy.dev/article/react-openapi-typescript)의 핵심 이점:

- **일관성 보장**: 생성된 타입이 항상 최신 API 스펙을 반영
- **시간 절약**: 대규모 API에서 수작업 타입 정의 불필요
- **개발자 경험 향상**: IDE IntelliSense 지원으로 API 탐색 용이
- **코드 품질 개선**: 프론트엔드-백엔드 불일치를 컴파일 타임에 감지

```typescript
// 수동 타입 정의 → 실수와 불일치 위험
interface UserResponse {
  id: number;
  name: string; // 오타? 누락된 필드?
}

// OpenAPI 자동 생성 → 항상 정확
// generated/models/UserResponse.ts
export interface UserResponse {
  id: number;
  fullName: string;
  email: string;
  createdAt: string;
  // ... 백엔드와 100% 일치
}
```

---

## 본론: 기존 구조의 문제점

OpenAPI 타입 생성을 도입했지만, 각 앱별로 개별 생성하는 구조에서 새로운 문제가 발생했다.

```
apps/
├── web/src/lib/api/generated/     # Web 전용 OpenAPI 타입
├── admin/src/lib/api/generated/   # Admin 전용 OpenAPI 타입
└── worker/src/lib/api/generated/  # Worker 전용 OpenAPI 타입
```

### 문제점 1: 코드 중복

세 앱이 동일한 백엔드 API를 사용하는데, 똑같은 타입 정의가 3곳에 중복 생성되었다.

```typescript
// apps/web/src/lib/api/generated/models/TicketResponse.ts
export interface TicketResponse {
  id: number;
  title: string;
  // ...
}

// apps/admin/src/lib/api/generated/models/TicketResponse.ts
export interface TicketResponse {
  id: number;
  title: string;
  // ... (완전히 동일한 코드)
}

// apps/worker/src/lib/api/generated/models/TicketResponse.ts
export interface TicketResponse {
  id: number;
  title: string;
  // ... (또 동일한 코드)
}
```

### 문제점 2: 동기화 이슈

백엔드 API가 변경되면 3번의 generate 명령을 실행해야 했다.

```bash
pnpm run generate:api:web
pnpm run generate:api:admin
pnpm run generate:api:worker
```

하나라도 빼먹으면 앱 간 타입 불일치가 발생했다. 실제로 Web에서는 새 필드가 있는데 Admin에서는 없는 상황이 종종 발생했다.

### 문제점 3: 공통 컴포넌트 개발의 어려움

앱 간에 공유되는 컴포넌트를 만들 때, OpenAPI 타입을 어디서 import할지 애매했다.

```typescript
// 공통 컴포넌트를 만들고 싶은데...
// Web의 타입을 쓸까? Admin의 타입을 쓸까?
import { UserResponse } from '@/lib/api/generated/models'; // 어느 앱의?
```

### 문제점 4: 빌드 시간 증가

각 앱 빌드 시마다 OpenAPI 타입 생성이 포함되어 전체 CI/CD 시간이 불필요하게 길어졌다.

---

## 해결: @shared/app-commons 패키지 도입

### 새로운 구조

```
packages/
└── shared-app-commons/
    ├── src/
    │   ├── openapi/
    │   │   └── base/
    │   │       ├── api.ts       # API 클라이언트
    │   │       ├── models.ts    # 모든 타입 정의
    │   │       └── runtime.ts   # 런타임 유틸리티
    │   ├── components/
    │   │   ├── avatar/          # 공통 Avatar 컴포넌트
    │   │   └── badge/           # 공통 Badge 컴포넌트
    │   └── hooks/               # 공통 훅
    └── package.json

apps/
├── web/      # @shared/app-commons에서 import
├── admin/    # @shared/app-commons에서 import
└── worker/   # @shared/app-commons에서 import
```

### 빌드 의존성 체인

```
shared-ui-resources (빌드)
       ↓
shared-app-commons (빌드) ← OpenAPI 타입 생성 포함
       ↓
web / admin / worker (빌드)
```

---

## 구체적인 마이그레이션 작업

### Step 1: @shared/app-commons 패키지 생성

```bash
mkdir -p packages/shared-app-commons/src
```

`package.json` 설정:

```json
{
  "name": "@shared/app-commons",
  "version": "0.1.0",
  "exports": {
    ".": {
      "types": "./dist/index.d.ts",
      "import": "./dist/index.mjs",
      "require": "./dist/index.js"
    },
    "./openapi/base/api": {
      "types": "./dist/openapi/base/api.d.ts",
      "import": "./dist/openapi/base/api.mjs",
      "require": "./dist/openapi/base/api.js"
    },
    "./openapi/base/models": {
      "types": "./dist/openapi/base/models.d.ts",
      "import": "./dist/openapi/base/models.mjs",
      "require": "./dist/openapi/base/models.js"
    }
  },
  "scripts": {
    "build": "pnpm run generate:api:base && tsup",
    "generate:api:base": "openapi-generator-cli generate -i ../../openapi-specs/openapi-spec-base.json -g typescript-fetch -o ./src/openapi/base/generated"
  }
}
```

### Step 2: OpenAPI 스펙 통합

기존에 앱별로 다운로드하던 스펙을 하나의 base 스펙으로 통합한다.

```bash
# 기존 (3개 파일)
openapi-specs/web-api.json
openapi-specs/admin-api.json
openapi-specs/worker-api.json

# 변경 후 (1개 파일)
openapi-specs/openapi-spec-base.json
```

### Step 3: 모든 앱의 Import 경로 수정

**Before:**

```typescript
// apps/web/src/hooks/useTickets.ts
import type { TicketResponse } from '@/lib/api/generated/models';
import { TicketApi } from '@/lib/api/generated/api';
```

**After:**

```typescript
// apps/web/src/hooks/useTickets.ts
import type { TicketResponse } from '@shared/app-commons/openapi/base/models';
import { TicketApi } from '@shared/app-commons/openapi/base/api';
```

### Step 4: 기존 generated 폴더 삭제

```bash
rm -rf apps/web/src/lib/api/generated
rm -rf apps/admin/src/lib/api/generated
rm -rf apps/worker/src/lib/api/generated
```

### Step 5: 빌드 스크립트 수정

루트 `package.json`:

```json
{
  "scripts": {
    "build:commons": "cd packages/shared-app-commons && pnpm run build",
    "build:docker:web": "pnpm run build:commons && cd apps/web && pnpm run build",
    "build:docker:admin": "pnpm run build:commons && cd apps/admin && pnpm run build",
    "build:docker:worker": "pnpm run build:commons && cd apps/worker && pnpm run build"
  }
}
```

### Step 6: 공통 컴포넌트 이전

기존에 각 앱에 중복 존재하던 공통 컴포넌트들을 패키지로 이동한다.

```typescript
// packages/shared-app-commons/src/components/avatar/UserAvatar.tsx
import type { UserResponse } from '../../openapi/base/models';

interface UserAvatarProps {
  user: UserResponse;
  size?: 'small' | 'medium' | 'large';
}

export function UserAvatar({ user, size = 'medium' }: UserAvatarProps) {
  // ...
}
```

---

## 개선된 점

### 1. 단일 진실 공급원 (Single Source of Truth)

| 항목 | Before | After |
|------|--------|-------|
| 타입 정의 위치 | 3곳 (중복) | 1곳 (패키지) |
| 동기화 필요 | 수동 3회 실행 | 자동 (빌드 시) |
| 타입 불일치 위험 | 높음 | 없음 |

### 2. 개발 경험 향상

```typescript
// 어느 앱에서든 동일한 import 경로
import type { TicketResponse, UserResponse } from '@shared/app-commons/openapi/base/models';
import { UserAvatar } from '@shared/app-commons/components/avatar';
```

### 3. 빌드 효율성

```bash
# Before: 각 앱 빌드마다 OpenAPI 생성
web build (30s) + admin build (30s) + worker build (30s) = 90s

# After: 한 번만 생성
commons build (10s) + web (25s) + admin (25s) + worker (25s) = 85s
# + 캐시 활용 시 더 빠름
```

### 4. 공통 로직 재사용성

OpenAPI 타입에 의존하는 공통 컴포넌트와 훅을 한 곳에서 관리할 수 있다.

```
@shared/app-commons/
├── components/
│   ├── avatar/      # UserAvatar, WorkerAvatar
│   └── badge/       # StatusBadge
└── hooks/
    └── useUserStatus.ts
```

---

## 정리

| 개선 항목 | 효과 |
|-----------|------|
| 코드 중복 제거 | 3곳 → 1곳 |
| 동기화 문제 해결 | 자동화된 빌드 체인 |
| 공통 컴포넌트 기반 마련 | 타입과 UI를 함께 관리 |
| 개발자 경험 향상 | 일관된 import 경로 |

모노레포 환경에서 여러 앱이 동일한 백엔드를 공유할 때, 타입 시스템을 패키지로 분리하는 것은 유지보수성과 개발 효율성 모두를 높이는 좋은 패턴이다.

---

## 참고 자료

- [OpenAPI Specification - Wikipedia](https://en.wikipedia.org/wiki/OpenAPI_Specification)
- [OpenAPI Initiative Newsletter – December 2024](https://www.openapis.org/blog/2024/12/23/openapi-initiative-newsletter-december-2024)
- [REST API vs GraphQL: 2025 Statistics & Trends](https://jsonconsole.com/blog/rest-api-vs-graphql-statistics-trends-performance-comparison-2025)
- [React & REST APIs: End-To-End TypeScript Based On OpenAPI Docs](https://profy.dev/article/react-openapi-typescript)
- [Is GraphQL dying? 2023 Trend Analysis](https://wundergraph.com/blog/graphql_rest_openapi_trend_analysis_2023)
