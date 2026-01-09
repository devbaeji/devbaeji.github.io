---
title: "Charles Proxy로 모바일 앱 API 요청 디버깅하기"
date: 2025-01-09 15:00:00 +0900
categories: [Troubleshooting, Tools]
tags: [charles-proxy, mobile, debugging, ios, android, api]
---

## 왜 Charles Proxy가 필요할까?

모바일 앱에서 API 요청이 제대로 가는지 확인하고 싶을 때가 있어요.

- "분명 API 호출했는데 왜 데이터가 안 들어가지?"
- "요청 헤더에 토큰이 제대로 들어갔나?"
- "응답은 뭐가 오는 거지?"

웹 브라우저는 개발자 도구(F12)로 네트워크 탭을 볼 수 있는데, 모바일 앱은 그게 안 되잖아요.

**Charles Proxy**를 사용하면 모바일 앱의 모든 네트워크 요청을 가로채서 볼 수 있어요!

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│  모바일 앱   │────▶│ Charles Proxy │────▶│   API 서버   │
│  (iPhone)   │◀────│  (내 맥북)     │◀────│             │
└─────────────┘     └──────────────┘     └─────────────┘
                           │
                           ▼
                    요청/응답 모니터링
```

---

## 설치 및 기본 설정

### 1. Charles Proxy 설치

```bash
# macOS (Homebrew)
brew install --cask charles

# 또는 공식 사이트에서 다운로드
# https://www.charlesproxy.com/download/
```

30일 무료 체험이 있고, 그 이후에도 30분마다 재시작하면 계속 쓸 수 있어요. (구매하면 더 편함)

### 2. 프록시 포트 확인

Charles 실행 후:
- **Proxy → Proxy Settings** 메뉴
- 기본 포트: `8888`

### 3. 맥 IP 주소 확인

```bash
# Wi-Fi IP 확인
ipconfig getifaddr en0

# 예: 192.168.0.10
```

---

## 모바일 기기 설정

### iPhone 설정

1. **설정 → Wi-Fi → 연결된 네트워크의 (i) 버튼**
2. 맨 아래 **HTTP 프록시 → 수동 설정**
3. 입력:
   - 서버: `192.168.0.10` (맥 IP)
   - 포트: `8888`

### Android 설정

1. **설정 → Wi-Fi → 연결된 네트워크 길게 누르기 → 네트워크 수정**
2. **고급 옵션 → 프록시 → 수동**
3. 입력:
   - 프록시 호스트: `192.168.0.10`
   - 프록시 포트: `8888`

---

## HTTPS 트래픽 보기 (SSL Proxying)

기본적으로 HTTPS 요청은 암호화되어 내용을 볼 수 없어요. Charles의 SSL 인증서를 설치하면 복호화해서 볼 수 있어요.

### 1. Charles 인증서 다운로드

모바일 기기의 브라우저에서:
```
http://chls.pro/ssl
```

접속하면 인증서 파일이 다운로드돼요.

### 2. iPhone에서 인증서 설치

1. **설정 → 일반 → VPN 및 기기 관리**
2. 다운로드한 프로파일 선택 → **설치**
3. **설정 → 일반 → 정보 → 인증서 신뢰 설정**
4. **Charles Proxy CA** 활성화

### 3. Android에서 인증서 설치

1. **설정 → 보안 → 암호화 및 사용자 인증 정보**
2. **인증서 설치 → CA 인증서**
3. 다운로드한 인증서 선택

### 4. Charles에서 SSL Proxying 활성화

1. **Proxy → SSL Proxying Settings**
2. **Enable SSL Proxying** 체크
3. **Include** 목록에 추가:
   - Host: `*` (모든 호스트)
   - Port: `443`

또는 특정 도메인만:
```
*.api.yourapp.com:443
```

---

## 실제 디버깅 예시

### Authorization 헤더 누락 발견

제가 실제로 겪었던 케이스예요.

**증상**: 같은 API인데 한 앱에서는 DB 저장이 되고, 다른 앱에서는 안 됨

**Charles에서 본 요청 비교**:

```http
# 앱 A (정상 동작)
POST /api/tickets/schedules HTTP/1.1
Host: api.spation.com
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
Content-Type: application/json

{"ticketId": 123, "assigneeId": 456}
```

```http
# 앱 B (DB 저장 안 됨)
POST /api/tickets/schedules HTTP/1.1
Host: api.spation.com
Content-Type: application/json

{"ticketId": 123, "assigneeId": 456}
```

**Authorization 헤더가 없었어요!**

응답은 둘 다 200으로 왔는데, 앱 B는 인증 실패로 처리되어 실제 저장이 안 됐던 거예요.

### 유용한 Charles 기능들

**1. Filter로 특정 도메인만 보기**

- 하단의 **Filter** 입력창에 도메인 입력
- 예: `api.spation.com`

**2. 요청 수정해서 다시 보내기 (Compose)**

1. 요청 우클릭 → **Compose**
2. 헤더나 바디 수정
3. **Execute**로 다시 전송

**3. 응답 가로채서 수정하기 (Breakpoints)**

1. 요청 우클릭 → **Breakpoints**
2. 해당 URL 요청 시 Charles가 멈춤
3. 요청/응답 수정 후 전달 가능

**4. 느린 네트워크 시뮬레이션 (Throttling)**

- **Proxy → Throttle Settings**
- 3G, LTE 등 느린 환경 테스트

---

## 트러블슈팅

### "연결할 수 없음" 에러

1. **같은 Wi-Fi인지 확인** - 맥과 모바일이 같은 네트워크여야 함
2. **방화벽 확인** - macOS 방화벽이 Charles를 막고 있을 수 있음
3. **프록시 설정 재확인** - IP와 포트가 정확한지

### HTTPS 내용이 안 보임

1. SSL 인증서 설치했는지 확인
2. iPhone은 **인증서 신뢰 설정**까지 해야 함
3. Charles에서 SSL Proxying이 활성화됐는지 확인

### 앱이 연결을 거부함 (SSL Pinning)

일부 앱은 보안을 위해 특정 인증서만 신뢰해요. (SSL Pinning)

이 경우 Charles 인증서를 거부해서 연결이 안 돼요.

**해결 방법**:
- 개발 중인 앱이라면 디버그 빌드에서 SSL Pinning 비활성화
- 프로덕션 앱은 기본적으로 우회 불가 (보안 기능이니까요)

---

## 대안 도구들

| 도구 | 장점 | 단점 |
|-----|-----|-----|
| **Charles Proxy** | GUI 편함, 기능 많음 | 유료 (무료 체험 있음) |
| **Proxyman** | macOS 네이티브, 깔끔한 UI | macOS 전용 |
| **mitmproxy** | 무료, CLI 기반 | 러닝커브 있음 |
| **Fiddler** | 무료, Windows 친화적 | macOS에서 좀 불편 |

저는 Charles가 익숙해서 계속 쓰고 있어요.

---

## 마무리

모바일 앱 디버깅할 때 Charles Proxy는 정말 유용해요.

- API 요청/응답을 눈으로 확인
- 헤더 누락, 잘못된 파라미터 바로 발견
- 네트워크 환경 시뮬레이션

처음 설정할 때 SSL 인증서 설치가 좀 번거롭지만, 한 번 해두면 두고두고 쓸 수 있어요.

특히 "앱에서는 됐는데 서버에 안 들어갔어요" 같은 애매한 이슈 디버깅할 때 진짜 시간 절약됩니다!
