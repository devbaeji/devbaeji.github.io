---
title: "[Insight] AI 코드가 만드는 보이지 않는 비용 — 보안, 기술 부채, 오픈소스, 법적 리스크 (4/5)"
date: 2026-03-13 22:30:00 +0900
categories: [Insight, AI]
tags: [ai, 보안, 기술부채, 오픈소스, 저작권, 바이브코딩]
---

> **데이터 수집 기간**: 2025.10 ~ 2026.03
> **출처**: Veracode, Georgetown CSET, Stack Overflow, Hackaday, MIT, Anthropic, 미국 대법원, EU AI Act 등
> **시리즈**: [1편 — 4파 의견 대립](/posts/ai-era-developer-direction) · [2편 — 시장과 주니어 위기](/posts/ai-era-market-and-junior-crisis) · [3편 — 커뮤니티 토론](/posts/ai-era-community-debates) · 4편 — 보이지 않는 비용 · [5편 — 생산성 역설과 새로운 기회](/posts/ai-era-productivity-paradox)

---

## 개요

AI 코딩 도구의 생산성 향상은 많이 논의되지만, **그 이면의 비용**에 대한 논의는 상대적으로 부족하다. 이 글에서는 보안 취약점, 기술 부채, 오픈소스 생태계 위기, 법적 리스크 — 네 가지 "보이지 않는 비용"을 정리한다.

---

## 1. AI 생성 코드의 보안 취약점

### 핵심 수치

Veracode의 2025 GenAI 코드 보안 리포트 (100개 이상 LLM, 4개 언어 테스트):

| 지표 | 수치 |
|------|------|
| AI 코드 취약점 (인간 대비) | **2.74배** |
| 설계 결함 또는 알려진 보안 취약점 포함 비율 | **62%** |
| 고위험 취약점 포함 코드베이스 비율 (50,000개 분석) | **68%** |
| 프로젝트당 평균 보안 이슈 수 | **4.2개** |
| XSS 방어 실패율 | **86%** |
| Log Injection 방어 실패율 | **88%** |

### 슬롭스쿼팅(Slopsquatting)

AI가 존재하지 않는 패키지를 추천하는 현상이 새로운 공격 벡터가 되고 있다:

1. AI가 존재하지 않는 패키지명을 추천
2. 공격자가 해당 이름으로 악성 패키지를 등록
3. 다른 개발자가 같은 AI 추천을 받고 설치
4. 시스템 접근 권한 탈취

### 실제 영향

- Aikido Security 2026 리포트: AI 생성 코드가 현재 **보안 침해 5건 중 1건의 원인**
- Fortune 50 기업: 2024.12~2025.6 사이 월간 보안 발견 건수가 1,000건에서 **10,000건으로 10배 증가** (Apiiro 연구)

---

## 2. 기술 부채의 폭증

### "AI는 개발자를 10배로 만든다 — 기술 부채를 만드는 데에서"

Stack Overflow 블로그 제목이 이 문제를 정확히 요약한다.

**Ox Security "Army of Juniors" 리포트:**
- 300개 오픈소스 프로젝트 평가 결과: AI 생성 코드는 "기능적으로는 우수하지만, **아키텍처 판단이 체계적으로 결여**"
- 10가지 아키텍처/보안 안티패턴 발견

**Sonar 연구:**
- AI 생성 코드 이슈의 **90% 이상이 "코드 스멜"** — 명확한 버그가 아닌, 유지보수 문제를 일으키는 결함

**Forrester 예측:**
- 2025년 기술 의사결정자의 50% 이상이 중간~심각한 기술 부채 직면
- 2026년에는 **75%**로 증가 전망

### AI 기술 부채의 3가지 벡터

1. **모델 버전 혼란**: 서로 다른 모델/버전으로 생성된 코드가 혼재
2. **코드 생성 비대화**: 간단한 해결책 대신 과잉 설계된 코드 양산
3. **조직 파편화**: 팀원마다 다른 AI 도구/설정 사용으로 일관성 붕괴

이 세 가지가 상호작용하며 **지수적으로 증가**하는 것이 핵심 문제.

### HN/GeekNews 현장 반응

GeekNews "LLM은 올바른 코드를 작성하지 않는다" 글에서:

> "아무리 프롬프트와 스킬을 잘 가져다 써도 AI가 만든 코드는 항상 어딘가 결함이 있었어요." — galaxy11111

HN "State of AI Code Quality" 스레드에서:

> *"Our execs keep pushing 'vibe-coding' and agentic coding, but IMO these are just tools."* — ilitirit
>
> 배칭 기능을 위해 수백 줄 + 여러 클래스로 된 AI 코드를 거절하고, 메서드 2개 + 필드 1개로 해결한 사례.

HN에서의 경고:

> *"The amount of issues and bugs is insane... my mental model of the codebase has severely degraded."* — mirsadm
>
> (이슈와 버그의 양이 미쳤다. 코드베이스에 대한 내 멘탈 모델이 심각하게 퇴화했다.)

---

## 3. 바이브 코딩이 오픈소스를 죽이고 있다

### 학술 논문 기반 분석

Central European University 연구팀이 논문 **"Vibe Coding Kills Open Source"**를 발표했다 (arxiv.org). AI가 오픈소스 의존성을 설치할 때 개발자와 메인테이너 사이의 상호작용을 단절시킨다는 분석이다.

### 핵심 메커니즘

바이브 코딩은 생산성을 높이지만, **메인테이너가 수익을 얻는 경로**를 차단한다:

| 경로 | AI 이전 | AI 이후 |
|------|---------|---------|
| 문서 방문 | 개발자가 직접 문서를 읽음 | AI가 학습 데이터에서 답변 |
| 버그 리포트 | 개발자가 이슈 등록 | AI가 워크어라운드 제시 |
| 커뮤니티 참여 | 포럼/디스코드 활동 | AI와의 1:1 대화로 대체 |
| 스폰서/후원 | 프로젝트 인지도 → 후원 | 인지도 감소 → 후원 감소 |

### 실제 사례

- **Tailwind CSS**: npm 다운로드는 꾸준히 증가했지만, 문서 트래픽 **약 40% 감소**, 수익 **약 80% 하락**
- **Stack Overflow**: ChatGPT 출시 후 6개월 만에 활동량 **약 25% 감소**
- **cURL 프로젝트**: Daniel Stenberg이 AI 제출물이 20%에 달하자 버그 바운티를 중단. AI 생성 제출물의 유효율은 **5%에 불과**

### 피드백 루프 우려

HN "The problem with vibe coding" 스레드에서:

> AI 생성 코드가 훈련 데이터셋에 들어가면서 **품질 저하의 피드백 루프**가 형성될 수 있다 — az09mugen

---

## 4. AI 코드의 법적 책임

### 미국 대법원 판결 (2026.3.2)

AI가 단독으로 생성한 작품의 저작권 등록 거부를 확정 (상고 기각):

> **AI만으로 생성된 코드는 저작권 보호를 받을 수 없다** → 누구나 자유롭게 사용 가능

### 법적 역설

AI 코드는 저작권 **보호를 못 받지만**, 타인의 저작권을 **침해할 수는 있다**.

- AI 생성 코드 샘플의 약 **35%에서 라이선스 불규칙** 발견
- 인간 개발자가 반복적 프롬프팅, 편집, 정제 등 **"충분한 창작적 기여"**를 했을 경우에만 저작권 보호 가능

### EU AI Act

2026년 8월부터 시행:
- GPAI 제공자에게 학습 데이터 요약 공개 및 저작권 유보 존중 의무
- 위반 시 **글로벌 매출의 3%** 벌금

### 요약

| 상황 | 법적 보호 |
|------|----------|
| AI 단독 생성 코드 | 저작권 보호 **불가** |
| 인간이 충분히 편집/정제한 AI 코드 | 저작권 보호 **가능** |
| AI가 타인 코드를 학습해 유사 코드 생성 | 저작권 **침해 가능** |

---

## 정리

AI 코딩의 "보이지 않는 비용" 4가지:

| 비용 | 핵심 수치 | 시간 지평 |
|------|----------|----------|
| 보안 취약점 | 인간 대비 **2.74배** | 즉각적 |
| 기술 부채 | 2026년 **75%** 기업 직면 예상 | 3~12개월 |
| 오픈소스 위기 | Tailwind 수익 **80% 하락** | 6~24개월 |
| 법적 리스크 | 코드 **35%** 라이선스 불규칙 | 지속적 |

---

## 참고 자료

- [Cybersecurity Risks of AI-Generated Code — Georgetown CSET](https://cset.georgetown.edu/publication/cybersecurity-risks-of-ai-generated-code/)
- [AI Code Security Crisis 2026 — GroweXX](https://www.growexx.com/blog/ai-code-security-crisis-2026-cto-guide/)
- [AI Can 10x Developers...in Creating Tech Debt — Stack Overflow](https://stackoverflow.blog/2026/01/23/ai-can-10x-developers-in-creating-tech-debt/)
- [AI-Generated Code Creates New Wave of Technical Debt — InfoQ](https://www.infoq.com/news/2025/11/ai-code-technical-debt/)
- [Vibe Coding Kills Open Source (논문) — arXiv](https://arxiv.org/abs/2601.15494)
- [How Vibe Coding Is Killing Open Source — Hackaday](https://hackaday.com/2026/02/02/how-vibe-coding-is-killing-open-source/)
- [All the Liability, None of the Protection — Paddo.dev](https://paddo.dev/blog/ai-code-copyright-void/)
- [US Supreme Court Declines AI Copyright Case — Morgan Lewis](https://www.morganlewis.com/pubs/2026/03/us-supreme-court-declines-to-consider-whether-ai-alone-can-create-copyrighted-works)
- [The $1.5 Billion Reckoning: AI Copyright 2026 — ComplexDiscovery](https://complexdiscovery.com/the-1-5-billion-reckoning-ai-copyright-and-the-2026-regulatory-minefield/)
