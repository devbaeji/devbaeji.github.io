---
title: "Next.js Image vs img: Private S3 프록시 구조에서 Image가 안 되는 이유"
date: 2025-12-24 15:00:00 +0900
categories: [Frontend, Next.js]
tags: [nextjs, image, s3, cdn, proxy, troubleshooting]
---

## 문제 상황

공지사항에 첨부파일 기능을 추가하고 있었다. 파일 업로드 전 미리보기도 보여주고, 기존 파일은 S3에서 불러와서 썸네일도 보여줘야 했다.

처음에 Next.js의 `<Image>` 컴포넌트를 썼는데... 로컬에서는 되다가 안 되다가 하고, 개발 서버에서는 아예 안 됐다.

코드를 뜯어보니까 우리 프로젝트의 파일 접근 구조가 생각했던 것과 달랐다.

---

## 기본 개념부터 정리하자

### Blob URL이 뭐야?

파일을 업로드하기 전에 미리보기를 보여주고 싶을 때가 있다. 근데 파일은 아직 서버에 안 올라갔는데 어떻게 보여주지?

이럴 때 쓰는 게 **Blob URL**이다.

```typescript
// 사용자가 파일 선택
const file = event.target.files[0];

// 브라우저 메모리에 있는 파일을 URL로 변환
const blobUrl = URL.createObjectURL(file);
// 결과: "blob:http://localhost:3000/a1b2c3d4-e5f6-..."
```

| 특징 | 설명 |
|-----|------|
| 위치 | 브라우저 메모리에만 존재 |
| 수명 | 페이지 닫으면 사라짐 |
| 서버 접근 | 불가능 (브라우저만 알고 있음) |
| 용도 | 업로드 전 미리보기 |

그니까 Blob URL은 **"서버에 안 올리고 브라우저에서만 잠깐 쓰는 가짜 URL"**이라고 보면 된다.

### `<img>` vs `<Image>` 뭐가 다른데?

#### 네이티브 `<img>` 태그

```html
<img src="https://example.com/image.jpg" />
```

브라우저가 직접 URL로 가서 이미지를 가져온다. 단순하다.

```
브라우저 → 이미지 URL → 이미지 다운로드 → 화면에 표시
```

#### Next.js `<Image>` 컴포넌트

```tsx
import Image from 'next/image';

<Image src="https://example.com/image.jpg" width={200} height={200} />
```

얘는 좀 다르다. **Next.js 서버가 중간에 끼어든다**.

```
브라우저 → Next.js 서버 (/_next/image?url=...) → 원본 이미지 다운로드 → 리사이즈/포맷 변환 → 브라우저에 전달
```

왜 이렇게 복잡하게 하냐고? **이미지 최적화** 때문이다.

| 기능 | 설명 |
|-----|------|
| 자동 리사이즈 | 디바이스 크기에 맞게 이미지 크기 조절 |
| 포맷 변환 | WebP 같은 최신 포맷으로 변환 (용량 감소) |
| Lazy Loading | 스크롤해서 보일 때만 로딩 |
| 캐싱 | 한번 최적화한 이미지는 캐싱 |

좋은 거 맞다. 근데 문제는 **Next.js 서버가 원본 이미지에 접근할 수 있어야 한다**는 거다.

---

## 우리 프로젝트 구조 파악하기

### 처음에 생각한 구조

"S3에 파일 저장하니까 Presigned URL 쓰겠지?"

```
브라우저 → S3 Presigned URL → S3 버킷
```

### 실제 구조

코드를 까보니까 완전 달랐다.

```kotlin
// FileController.kt
@GetMapping("/{fileId}/stream")
fun streamFile(@PathVariable fileId: Long): ResponseEntity<InputStreamResource> {
    val fileEntity = fileService.getFileEntity(fileId)

    // 백엔드가 S3에서 직접 가져옴
    val s3Object = s3Client.getObject(
        GetObjectRequest.builder()
            .bucket(bucketName)
            .key(fileEntity.s3Key)
            .build()
    )

    // 브라우저에 스트리밍
    return ResponseEntity.ok()
        .body(InputStreamResource(s3Object))
}
```

**API 프록시 패턴**을 쓰고 있었다:

```
브라우저 → /api/files/{id}/stream → Spring Boot API → S3 Private Bucket
                                         ↑
                                   백엔드가 S3 접근
                                   (S3 자격증명은 서버에만 있음)
```

| 구분 | Presigned URL 방식 | API 프록시 방식 (우리 구조) |
|-----|-------------------|-------------------------|
| S3 접근 | 브라우저가 직접 | 백엔드가 대신 |
| URL 형태 | `s3.../file?signature=...` | `/api/files/123/stream` |
| 인증 | URL에 토큰 포함 | API 레벨 (JWT/쿠키) |
| S3 자격증명 | 노출 안 됨 (서명만) | 서버에만 존재 |

---

## 그래서 뭐가 문제였냐면

### 케이스 1: Blob URL

```tsx
const blobUrl = URL.createObjectURL(file);

// ❌ 안 됨
<Image src={blobUrl} ... />
```

Blob URL은 브라우저 메모리에만 있다고 했다. Next.js 서버가 `blob:http://localhost:3000/...` 이 URL로 접근하려고 해봤자, 서버는 이게 뭔지 모른다.

```
Next.js 서버: "blob:http://...? 이게 뭔데? 접근 불가!"
```

### 케이스 2: API 프록시 URL (우리 구조)

우리 프로젝트의 파일 URL은 이렇게 생겼다:

```typescript
// API가 반환하는 downloadUrl
const fileUrl = "/api/files/123/stream";

// getFullApiUrl() 적용 후
const fullUrl = "https://api.example.com/api/files/123/stream";
```

`next.config.mjs`에 API 도메인을 등록해놨다:

```js
// next.config.mjs
images: {
  remotePatterns: [
    { hostname: 'localhost', port: '30001' },
    { hostname: 'workspaces.dev.example.kr' },
  ],
},
```

도메인 등록했으니까 될 것 같지? **안 된다**.

왜냐하면 **인증 문제**:

```
┌─────────────────────────────────────────────────────────────┐
│  브라우저가 직접 요청 (<img> 사용)                             │
│                                                              │
│  브라우저 → /api/files/123/stream                            │
│          → 쿠키/JWT 헤더 자동 포함                            │
│          → API 서버: "인증됨, OK"                             │
│          → S3에서 파일 가져와서 응답                           │
│          → ✅ 성공                                           │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  Next.js Image 최적화 서버가 요청 (<Image> 사용)              │
│                                                              │
│  브라우저 → Next.js 서버 (/_next/image?url=...)              │
│          → Next.js가 원본 URL로 요청                         │
│          → /api/files/123/stream                            │
│          → 쿠키/JWT 없음! (서버 대 서버 통신)                  │
│          → API 서버: "인증 안됨, 401 Unauthorized"            │
│          → ❌ 실패                                           │
└─────────────────────────────────────────────────────────────┘
```

`<img>`는 브라우저가 직접 요청해서 쿠키가 자동으로 붙는다.
`<Image>`는 Next.js 서버가 대신 요청하는데, 서버는 사용자의 쿠키를 모른다.

---

## 해결: 그냥 `<img>` 쓰자

```tsx
// Before: 복잡하게 분기 처리
{isImage && thumbnailUrl ? (
  previewUrl ? (
    <img src={previewUrl} ... />      // Blob URL
  ) : (
    <Image src={thumbnailUrl} ... />  // API URL → ❌ 인증 실패!
  )
) : ...}

// After: 그냥 다 img로 통일
{isImage && thumbnailUrl ? (
  /* eslint-disable-next-line @next/next/no-img-element */
  <img src={thumbnailUrl} ... />
) : ...}
```

ESLint가 `<img>` 쓰지 말라고 경고하는데, 주석으로 무시해줬다. 이유가 있으니까.

| URL 종류 | Next.js Image | 네이티브 img |
|---------|---------------|-------------|
| Blob URL | ❌ 서버 접근 불가 | ✅ 브라우저가 직접 접근 |
| API 프록시 URL (인증 필요) | ❌ 인증 전달 안됨 | ✅ 쿠키 자동 포함 |
| Public URL (인증 불필요) | ✅ 최적화됨 | ✅ 동작 (최적화 없음) |

**인증이 필요한 API 프록시 구조에서는 `<img>`가 정답이다.**

---

## 다른 접근 방식들과 비교

우리 구조 말고 다른 방식들은 어떨까?

### 방식 1: Presigned URL

```
브라우저 → S3 Presigned URL → S3
          (URL에 임시 토큰 포함)
```

```typescript
// 서버에서 Presigned URL 생성
const presignedUrl = s3.getSignedUrl('getObject', {
  Bucket: 'my-bucket',
  Key: 'files/image.jpg',
  Expires: 3600  // 1시간
});

// 결과: https://bucket.s3.../image.jpg?X-Amz-Signature=...&X-Amz-Expires=3600
```

| 장점 | 단점 |
|-----|------|
| 브라우저가 S3에 직접 접근 (빠름) | URL 만료 시간 관리 필요 |
| 백엔드 부하 없음 | URL이 매번 달라서 캐싱 비효율 |
| S3 자격증명 노출 안됨 | Next.js Image에서 불안정 |

**Next.js Image와의 호환성:**

Presigned URL 자체는 IP 제한이 기본값이 아니라서, 만료 전이면 Next.js 서버도 접근 가능하다.

문제는 **타이밍과 캐싱**:
```
1. Presigned URL 생성 (1시간 유효)
2. Next.js Image가 가져와서 최적화 후 캐싱 → ✅ 성공

... 2시간 후 ...

3. Next.js 캐시 만료, 원본 다시 요청
4. 같은 Presigned URL 사용 → ❌ 이미 만료됨!
```

그리고 Presigned URL은 매번 signature가 달라지니까, 같은 파일인데도 다른 URL로 인식되어 캐시 효율이 떨어진다.

### 방식 2: CDN (CloudFront)

```
브라우저 → CloudFront (CDN) → S3
          (전 세계 엣지 서버에서 캐싱)
```

**CDN이 뭐야?**

CDN(Content Delivery Network)은 전 세계에 분산된 서버 네트워크다.

```
┌─────────────────────────────────────────────────────────────┐
│  CDN 없이                                                    │
│                                                              │
│  한국 사용자 ───────────────────────────→ 미국 S3 서버        │
│                     (느림, 멀어서)                            │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  CDN 있으면                                                  │
│                                                              │
│  한국 사용자 ──→ 서울 CDN 엣지 서버 (캐싱됨) ──→ 빠름!         │
│                        ↑                                     │
│                  최초 1회만 원본 요청                          │
│                        ↓                                     │
│                    미국 S3 서버                               │
└─────────────────────────────────────────────────────────────┘
```

| 장점 | 단점 |
|-----|------|
| 전 세계 어디서든 빠름 | 추가 비용 발생 |
| URL이 항상 같음 (캐싱 효율적) | 설정 복잡도 증가 |
| Next.js Image와 완벽 호환 | 캐시 무효화 관리 필요 |

**Public CDN 설정하면:**
```
URL: https://cdn.example.com/files/image.jpg
     ↑ 항상 같은 URL, 인증 불필요, 만료 없음
```

Next.js Image가 완벽하게 동작한다.

### 방식 3: API 프록시 (우리 현재 구조)

```
브라우저 → Backend API → S3
          (백엔드가 중계)
```

| 장점 | 단점 |
|-----|------|
| 인증 로직 통합 관리 | 백엔드 부하 증가 |
| S3 구조 완전 은닉 | 응답 속도 느림 (중계) |
| 접근 제어 유연함 | Next.js Image 사용 불가 |

---

## 구조별 비교 정리

| 구분 | API 프록시 (현재) | Presigned URL | CDN (Public) |
|-----|-----------------|---------------|--------------|
| **인증** | API 레벨 | URL 토큰 | 없음 (Public) |
| **속도** | 느림 (중계) | 빠름 | 가장 빠름 |
| **백엔드 부하** | 높음 | 없음 | 없음 |
| **URL 형태** | 항상 같음 | 매번 다름 | 항상 같음 |
| **Next.js Image** | ❌ 인증 문제 | ⚠️ 만료 문제 | ✅ 완벽 호환 |
| **비용** | 서버 비용 | S3 비용만 | CDN 추가 비용 |

---

## 앞으로 개선할 점

현재 API 프록시 구조의 문제점:
1. **백엔드 부하**: 모든 파일 요청이 백엔드를 거침
2. **이미지 최적화 불가**: Next.js Image 사용 못함
3. **느린 응답**: 중계 과정에서 지연 발생

### 개선 방향: CDN 도입

```
┌─────────────────────────────────────────────────────────────┐
│  현재 구조                                                   │
│                                                              │
│  브라우저 → API 서버 → S3                                    │
│             (부하, 느림)                                      │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  개선 후                                                     │
│                                                              │
│  브라우저 → CloudFront CDN → S3                              │
│             (캐싱, 빠름)                                      │
│                                                              │
│  + Next.js Image 최적화 가능                                 │
│  + 백엔드 부하 감소                                           │
│  + 전 세계 빠른 응답                                          │
└─────────────────────────────────────────────────────────────┘
```

보안이 필요한 파일은 CloudFront Signed URL이나 Signed Cookie로 처리할 수 있다.

---

## 정리

| 상황 | 해결책 |
|-----|-------|
| Blob URL (미리보기) | `<img>` 사용 |
| API 프록시 URL (인증 필요) | `<img>` 사용 |
| Presigned URL | `<img>` 권장 (만료 이슈) |
| Public CDN URL | `<Image>` 사용 가능 |

현재 상황에서 최선의 선택:
- **API 프록시 구조**에서는 `<img>`가 맞다
- 이미지 최적화 포기하는 대신 인증 문제 없이 동작

나중에 개선:
- **CloudFront CDN** 붙이면 `<Image>` 최적화 혜택 + 빠른 로딩 가능
- 보안 레벨에 따라 Public CDN 또는 Signed URL 선택

---

## 느낀 점

1. **코드부터 까보자**
   - "Presigned URL 쓰겠지" 추측했다가 완전 다른 구조였음
   - 실제 코드 확인하는 게 제일 정확하다

2. **Next.js `<Image>`는 마법이 아니다**
   - 중간에 서버가 끼어들어서 최적화하는 거다
   - 서버가 원본에 인증 없이 접근할 수 있어야 함

3. **인증이 필요한 리소스는 단순하게**
   - 복잡하게 최적화하려다가 인증 문제로 터질 수 있다
   - 브라우저가 직접 요청하는 `<img>`가 확실함

4. **아키텍처 트레이드오프**
   - API 프록시: 보안 좋음, 성능 나쁨
   - CDN: 성능 좋음, 설정 복잡
   - 상황에 맞게 선택하면 된다

단순하게 `<img>`로 바꾸니까 깔끔하게 해결됐다. CDN은 나중에 성능 이슈 생기면 그때 고민해도 늦지 않다.
