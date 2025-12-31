---
title: "[GitHub Actions] CI/CD 파이프라인 최적화 - OpenAPI 생성 3번에서 1번으로 줄이기"
date: 2025-12-30 15:00:00 +0900
categories: [Infra, CI/CD]
tags: [github-actions, openapi, ci-cd, devops]
---

## 들어가며

저희 팀은 Next.js 기반의 웹 서비스를 운영하고 있습니다. Web, Worker(모바일 웹), Admin 총 3개의 프론트엔드 앱과 Spring Boot API 서버로 구성되어 있는데요.

어느 날 PR을 올렸는데 빌드가 안 돌아가는 거예요. 확인해보니 이런 메시지가 떠 있었습니다.

> The job was not started because an Actions budget is preventing further use.

GitHub Actions 무료 사용 시간을 초과해버린 거였어요.

사실 OpenAPI 스펙 생성이 3번씩 돌아가고 있다는 건 알고 있었어요. "나중에 시간 나면 고쳐야지" 하면서 덮어두고 있었는데, 더 이상 미룰 수가 없게 됐습니다.

---

## 문제 상황

저희 프로젝트는 OpenAPI Generator로 백엔드 API 스펙에서 TypeScript 타입을 자동 생성합니다.

문제는 CI/CD 구조였습니다.

```
build-check-web.yaml    → OpenAPI 생성 → Web 빌드
build-check-admin.yaml  → OpenAPI 생성 → Admin 빌드
build-check-worker.yaml → OpenAPI 생성 → Worker 빌드
```

각 워크플로우가 독립적으로 OpenAPI 스펙을 생성하고 있었습니다.

공통 패키지를 수정하는 PR을 올리면 3개 워크플로우가 전부 트리거되고, 똑같은 작업이 3번 실행됩니다.

OpenAPI 생성 과정:
1. Spring Boot API 서버 실행 (Testcontainers로 MySQL 띄우기)
2. `/v3/api-docs` 엔드포인트 호출해서 스펙 JSON 다운로드
3. OpenAPI Generator로 TypeScript 타입 생성
4. 공통 패키지 빌드

이게 3번 반복되니까 CI 시간도 길어지고, Actions 사용량도 급격히 늘어났습니다.

---

## 개선 1: Reusable Workflow로 공통 로직 분리

OpenAPI 생성 로직을 Reusable Workflow로 분리했습니다.

{% raw %}
```yaml
# .github/workflows/openapi-generate.yaml
name: Generate OpenAPI Spec and Types

on:
  workflow_call:
    inputs:
      artifact-name:
        type: string
        default: 'openapi-spec'

jobs:
  generate:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout code
        uses: actions/checkout@v6

      # OpenAPI 스펙 생성 및 타입 생성 로직...

      - name: Upload packages build
        uses: actions/upload-artifact@v4
        with:
          name: ${{ inputs.artifact-name }}
          path: |
            openapi-specs/openapi-spec-base.json
            packages/app-commons/dist
            packages/ui-resources/dist
```
{% endraw %}

`workflow_call`을 사용하면 다른 워크플로우에서 함수처럼 호출할 수 있습니다.

```yaml
# deploy-web.yml
jobs:
  openapi:
    uses: ./.github/workflows/openapi-generate.yaml
    with:
      artifact-name: shared-output

  build:
    needs: openapi
    steps:
      - uses: actions/download-artifact@v4
```

이제 OpenAPI 생성 로직이 한 곳에서 관리됩니다.

---

## 개선 2: 캐싱으로 중복 빌드 제거

API 소스 코드가 변경되지 않았으면 OpenAPI를 다시 생성할 필요가 없습니다.

`actions/cache`를 활용해서 해결했습니다.

{% raw %}
```yaml
- name: Cache packages build
  id: openapi-cache
  uses: actions/cache@v4
  with:
    path: |
      openapi-specs/openapi-spec-base.json
      packages/app-commons/src/openapi/base/generated
      packages/app-commons/dist
      packages/ui-resources/dist
    key: packages-build-${{ hashFiles('apps/api/src/**', 'packages/app-commons/src/**', 'packages/ui-resources/src/**') }}
```
{% endraw %}

캐시 키를 `hashFiles()`로 생성합니다. API 소스 코드와 패키지 소스 코드의 해시값을 조합해서 키를 만들어요.

- API 코드가 바뀌면 → 해시가 바뀜 → 캐시 miss → 새로 빌드
- API 코드가 그대로면 → 해시 동일 → 캐시 hit → 빌드 스킵

```yaml
- name: Setup JDK 21
  if: steps.openapi-cache.outputs.cache-hit != 'true'

- name: Build packages
  if: steps.openapi-cache.outputs.cache-hit != 'true'
```

GitHub Actions 캐시는 같은 리포지토리 내에서 공유됩니다.

1. `deploy-web`이 먼저 실행 → 캐시 miss → 빌드 후 캐시 저장
2. `deploy-worker`가 실행 → 캐시 hit → 빌드 스킵
3. `deploy-admin`이 실행 → 캐시 hit → 빌드 스킵

워크플로우는 3개지만, 실제 빌드는 1번만 일어납니다.

---

## 개선 3: Build Check 워크플로우 통합

배포 워크플로우는 각 앱별로 분리되어 있는 게 맞지만, PR 빌드 체크는 하나로 통합할 수 있습니다.

`dorny/paths-filter`를 사용해서 3개의 build-check 워크플로우를 통합했습니다.

{% raw %}
```yaml
# .github/workflows/build-check.yaml
jobs:
  changes:
    runs-on: ubuntu-latest
    outputs:
      web: ${{ steps.filter.outputs.web }}
      admin: ${{ steps.filter.outputs.admin }}
      worker: ${{ steps.filter.outputs.worker }}
    steps:
      - uses: dorny/paths-filter@v3
        id: filter
        with:
          filters: |
            web:
              - 'apps/web/**'
              - 'packages/app-commons/**'
            admin:
              - 'apps/admin/**'
              - 'packages/app-commons/**'
            worker:
              - 'apps/worker/**'
              - 'packages/app-commons/**'

  openapi:
    uses: ./.github/workflows/openapi-generate.yaml

  build-web:
    needs: [changes, openapi]
    if: needs.changes.outputs.web == 'true'

  build-admin:
    needs: [changes, openapi]
    if: needs.changes.outputs.admin == 'true'

  build-worker:
    needs: [changes, openapi]
    if: needs.changes.outputs.worker == 'true'
```
{% endraw %}

PR에서 Web 앱만 수정했다면:
- `changes` job이 `web: true, admin: false, worker: false` 출력
- `openapi` job 1번 실행
- `build-web`만 실행, 나머지는 스킵

---

## 결과

| 항목 | 이전 | 개선 후 |
|------|------|---------|
| Build Check 워크플로우 | 3개 | 1개 |
| OpenAPI 생성 횟수 | 3번 | 1번 |
| 캐시 활용 | 없음 | API 소스 해시 기반 |
| 불필요한 빌드 | 모든 앱 빌드 | 변경된 앱만 |

---

## 정리

- `workflow_call`: 공통 로직을 Reusable Workflow로 분리
- `actions/cache` + `hashFiles()`: 소스 코드 해시 기반 캐싱
- `dorny/paths-filter`: 변경된 파일 기반 조건부 실행

CI/CD 파이프라인은 한번 세팅하면 잘 안 건드리게 되는데, 가끔 들여다보면 개선할 포인트가 보입니다.
