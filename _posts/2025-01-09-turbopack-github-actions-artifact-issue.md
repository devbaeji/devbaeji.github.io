---
title: "[Troubleshooting] 로컬에서는 되는데 CI에서 안 돼요 - Turbopack과 GitHub Actions artifact 업로드 이슈"
date: 2025-01-09 18:00:00 +0900
categories: [Troubleshooting]
tags: [github-actions, turbopack, nextjs, ci-cd, artifact]
---

## 이슈 파악

평화로운 금요일, 배포 파이프라인이 실패했습니다.

```
Error: The path for one of the files in artifact is not valid:
/apps/admin/.next/server/chunks/[externals]_node:inspector_7a4283c6._.js

Contains the following character: Colon :

Invalid characters include: Double quote ", Colon :, Less than <,
Greater than >, Vertical bar |, Asterisk *, Question mark ?
```

**이상한 점**: 로컬에서 `pnpm run build`를 실행하면 정상적으로 빌드됩니다.

```bash
# 로컬
$ cd apps/admin && pnpm run build
✓ Build completed successfully
```

개발자라면 누구나 한 번쯤 겪어봤을 그 상황... **"로컬에서는 되는데요?"**

---

## 원인 분석

### Step 1: 에러 메시지 정확히 읽기

에러를 다시 읽어보면:

```
The path for one of the files in artifact is not valid
```

**"빌드 실패"가 아니라 "artifact 업로드 실패"**입니다!

GitHub Actions 워크플로우를 확인해보면:

```yaml
# deploy-admin.yml
- name: Build App
  run: cd apps/admin && pnpm run build:docker  # ✅ 여기는 성공

- name: Upload build artifacts  # ❌ 여기서 실패!
  uses: actions/upload-artifact@v4
  with:
    path: apps/admin/.next
```

빌드는 성공했지만, 빌드 결과물을 artifact로 업로드하는 단계에서 실패한 것입니다.

### Step 2: 문제의 파일 찾기

로컬에서 콜론이 포함된 파일을 검색해봤습니다.

```bash
$ find apps/admin/.next -name '*:*'

./.next/server/chunks/[externals]_node:inspector_7a4283c6._.js
./.next/server/chunks/ssr/[externals]_node:inspector_7a4283c6._.js
./.next/standalone/apps/admin/.next/server/chunks/[externals]_node:inspector_7a4283c6._.js
...
```

`node:inspector`는 Node.js 내장 모듈입니다. 이 모듈명이 그대로 파일명에 사용되면서 콜론(`:`)이 포함된 것이었습니다.

### Step 3: 왜 로컬에서는 문제가 없을까?

| 환경 | 파일시스템 | 콜론(`:`) 허용 |
|------|-----------|---------------|
| 로컬 (macOS) | APFS | ✅ 허용 |
| GitHub Actions (Linux) | ext4 | ✅ 허용 |
| artifact 업로드 | **NTFS 호환 체크** | ❌ **금지** |

GitHub Actions의 `upload-artifact`는 Windows(NTFS) 호환성을 위해 파일명을 검사합니다.

NTFS에서 금지된 문자: `" : < > | * ? \r \n`

**로컬에서는 빌드만 하고 끝이지만, CI에서는 빌드 후 artifact 업로드라는 추가 단계가 있습니다.** 이 단계에서 NTFS 호환성 체크에 걸린 것입니다.

### Step 4: 콜론 파일은 왜 생기는가?

`package.json`을 확인해보니:

```json
{
  "scripts": {
    "build": "next build --turbopack",
    "build:docker": "next build --turbopack"
  }
}
```

**Turbopack**이 범인이었습니다!

Turbopack은 Vercel이 Rust로 만든 차세대 번들러로, Webpack보다 훨씬 빠릅니다. 하지만 아직 실험적인 기능이 많습니다.

Turbopack이 `node:inspector` 같은 Node.js 내장 모듈을 청크 파일로 만들 때, 모듈명을 그대로 파일명에 사용해서 콜론이 포함된 파일이 생성된 것입니다.

---

## 해결 방법

### 방법 1: Turbopack 제거 (간단하지만 아쉬움)

```json
{
  "scripts": {
    "build:docker": "next build"  // --turbopack 제거
  }
}
```

단점: Turbopack의 빠른 빌드 속도를 포기해야 합니다.

### 방법 2: 빌드 결과물 압축 후 업로드 (채택!)

Turbopack을 유지하면서 artifact 업로드 문제를 해결하는 방법입니다.

**핵심 아이디어**: 콜론이 포함된 파일명도 **tar로 압축하면** 아카이브 내부에 안전하게 보관됩니다. artifact로는 압축 파일만 업로드하면 됩니다!

#### Before (문제 발생)

```yaml
# deploy-admin.yml
- name: Upload build artifacts
  uses: actions/upload-artifact@v4
  with:
    path: |
      apps/admin/.next          # ❌ 콜론 파일 포함
      apps/admin/package.json
      apps/admin/public
```

#### After (해결)

```yaml
# deploy-admin.yml

# 빌드 결과물을 tar로 압축 (파일 이름에 특수문자 문제 해결)
- name: Create build archive
  run: |
    tar -czf build-output.tar.gz \
      openapi-specs/openapi-spec-base.json \
      packages/ksd-app-commons/src/openapi/base/generated \
      apps/admin/.next \
      apps/admin/next.config.ts \
      apps/admin/package.json \
      apps/admin/public

- name: Upload build artifacts
  uses: actions/upload-artifact@v4
  with:
    name: shared-output
    overwrite: true
    path: build-output.tar.gz   # ✅ 압축 파일만 업로드
    retention-days: 1
```

배포 단계에서는 압축을 해제해서 사용합니다.

---

## 배운 점

### 1. 에러 메시지를 정확히 읽자

"빌드 실패"와 "artifact 업로드 실패"는 다릅니다. 에러 메시지를 대충 읽으면 엉뚱한 곳에서 삽질합니다.

### 2. 로컬과 CI의 차이를 이해하자

| 차이점 | 설명 |
|--------|------|
| 파일시스템 | macOS(APFS) vs Linux(ext4) vs Windows(NTFS) |
| 추가 단계 | CI에만 있는 artifact 업로드, 캐시 등 |
| 환경변수 | 로컬과 CI의 환경변수 차이 |

### 3. 로컬에서 CI 에러 재현하기

```bash
# CI에서 문제가 되는 파일 찾기
find .next -name '*:*' 2>/dev/null
```

이 명령어로 콜론이 포함된 파일을 미리 찾을 수 있습니다.

### 4. 새로운 도구는 검증 후 사용하자

Turbopack은 빠르지만 아직 실험적입니다. 프로덕션 CI/CD 파이프라인에서는 예상치 못한 엣지 케이스가 있을 수 있습니다.

---

## 마무리

**"로컬에서는 되는데요?"**

이 말이 나오면 로컬과 CI 환경의 차이를 체계적으로 분석해보세요:

1. OS / 파일시스템 차이
2. CI에서만 실행되는 단계 (artifact, 캐시 등)
3. 환경변수 차이
4. 의존성 버전 차이

대부분의 경우 원인을 찾을 수 있습니다. 오늘의 삽질이 내일의 경험이 됩니다!
