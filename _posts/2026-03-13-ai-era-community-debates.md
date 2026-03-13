---
title: "[Insight] AI 시대 개발자 — GeekNews·HN 커뮤니티 토론 모음 (3/5)"
date: 2026-03-13 22:20:00 +0900
categories: [Insight, AI]
tags: [ai, 개발자, geeknews, hackernews, 커뮤니티, 바이브코딩]
---

> **데이터 수집 기간**: 2025.10 ~ 2026.03
> **출처**: GeekNews(news.hada.io), Hacker News, Reddit
> **시리즈**: [1편 — 4파 의견 대립](/posts/ai-era-developer-direction) · [2편 — 시장과 주니어 위기](/posts/ai-era-market-and-junior-crisis) · 3편 — 커뮤니티 토론 · [4편 — 보이지 않는 비용](/posts/ai-era-hidden-costs) · [5편 — 생산성 역설과 새로운 기회](/posts/ai-era-productivity-paradox)

---

## 이 글에 대해

[1편](/posts/ai-era-developer-direction)에서는 유명인들의 의견을, [2편](/posts/ai-era-market-and-junior-crisis)에서는 시장 데이터를 정리했다. 이 글에서는 **현직 개발자들의 실제 토론**을 댓글 원문과 함께 정리한다. CEO 발언이나 보고서보다 현장감이 있는 이야기들이다.

---

## GeekNews 토론

### "60살인데요. Claude Code 덕분에 다시 열정이 불타오르네요"

60세 프로그래머가 Claude Code 덕분에 ASP/COM/VB6 시대의 흥분을 수십 년 만에 다시 경험했다는 글. 50개 이상의 댓글이 달리며 세대 간 시각 차이가 드러났다.

**긍정 진영 (주로 40~60대):**

> "삽질 10년 이상의 경험이 있을 때 LLM이 더 효과적" — eyedroot

> (50대) 웹 스택 변화에 지쳐 코딩을 중단했으나 Claude Code가 "궁극의 치트키" — burnstek

> (66세) 최근 몇 개월간 미디어 앱, 식료품 목록, iOS 워치 앱 완성 — meebee

**우려 진영 (주로 20~30대, 현직 시니어):**

> (60대, 곧 은퇴) 에이전트가 "설계/구현/테스트의 만족감을 빼앗음", 산업혁명 직조공 비유 — kitd

> (Principal Engineer) 수십 년 전문 지식이 "대폭 평가절하", 의욕 상실 — samiv

> (Staff Engineer) 주니어 채용 감소로 전문가 성장 경로 차단 우려 — bri3d

> (40년 경력) 89개 종속성 번들 vs 2.7KB 도구 비교 — AI 결과를 결국 재작성해야 함 — codazoda

**세대 갈등:**

> "HN 댓글자는 40~60대 기득권층, 신입/중간 경력자가 실제 위험" — tavavex

> UX 분야 2009년부터 경력, "사라져가는 직업", 집 매각으로 대비 — rps93

핵심 분석: **"코드 조각 맞추기"를 즐기는가 vs "작동 시스템 구축"을 즐기는가**에 따라 AI에 대한 평가가 갈린다 (ACCount37).

---

### "LLM은 올바른 코드를 작성하지 않는다" (댓글 16개)

**찬반이 분명하게 갈린 토론:**

> "간단한 성능관련 success criteria조차 주지 않으면 어떻게 되는지 잘 보여주는 사례. 성능 조건을 명시하지 않고 최적의 성능 결과를 기대하는 건 AI를 사용하는 사람의 일종의 태만" — jokerized

> "Georgehotz도 AI를 일종의 컴파일러로만 의식하고 쓰고 있습니다. 설계나 구조 또는 선택에 있어서는 아직 인간의 판단이 필요하죠... 전반적으로 AI에게 주도권을 맡겨버리면 굳이 개발자가 할 필요가 없어요" — skrevolve

> "모델의 특징을 파악하고 적절한 프롬프트와 스킬 워크플로우를 찾아내어 적용할 때쯤이면 이미 신형 모델이 나오는데.... 에이전트를 현재 제대로 쓸 수 있는지조차 의문" — armila

---

### "AI 시대에 코드 리뷰, 어떻게 해야할까?"

15년차 CTO가 정-반-합 구조로 분석한 글. 댓글에서 논리적 메타 비판이 나왔다.

> "반, 합은 아직은 비현실적이라는 생각이 드네요. 코드는 계속 사용되는 것이고, LLM은 확률적이기 때문에 사람이 자기가 짠 코드를 (아직은) 모두 읽을 필요가 있습니다." — vk8520

> "중간 지점의 오류 (Argument to Moderation): 두 극단적인 주장이 있을 때, 그 중간 지점이 진실이거나 최선의 해결책일 것이라고 단정 짓는 논리입니다." — pencil6962

---

### "AI가 개발자를 대치할 수 있을까?" (2025.02)

> "아주 간단하게 기획서만 넣으면 개발이 완료되는 수준이 올 경우 대체되었다 평가할 수 있겠음. 근데 이 날이 언제 오려나" — tominam2

> "20년전에도 개발자를 대체할 수 있다고 온갖 영업과 기사들이 난무했었는데 지금은 그 시절을 닷컴버블이라고 부르더라고요" — gurugio

> "정의할 문제는 크게 많아지지 않는 상황에 생산성이 비약적으로 증가하여 소수가 큰 생산성을 가지게 되진 않을지 우려. 개발 조직을 대체할 수는 없지만, **많은 비율의 개발자는 대체할 수 있다**고 생각됩니다." — devdha

> "AI가 대체하는건 소프트웨어 개발조직이 아니라 **PM, PO 조직**일 겁니다." — serithemage

---

### "Claude Code 한국어 플레이북" — AI Slop 논쟁

59챕터 가이드에 대한 토론에서 **AI 생성 저품질 콘텐츠(AI Slop)**에 대한 논쟁이 벌어졌다.

> "긍정적인 댓글이 어뷰징은 아니더라도 최소한 품앗이가 아닌지 의심되는군요. 당장 첫 페이지부터 말이 안 되는데" — crawler

> "AI Slop도 글이라고 동기부여 해줘야 한다는 의견은 동의할 수가 없습니다." — crawler

> (반론) "GeekNews 정도 되는 규모의 웹사이트에서 최소한의 품앗이를 따진다는 것 자체가..." — princox

첫 페이지의 Copilot 비교 오류를 여러 사람이 지적하자 작성자가 빠르게 수정 대응하기도 했다.

---

### "Claude Code, 코드 리뷰 기능 공개"

> "요즘 Anthropic의 릴리즈 속도가 미쳤네요. 개발 도구를 개선하면서, 그걸로 자기네 개발 자체도 빠르게 만드는 **플라이휠 구성이 끝난 듯**" — xguru

> "클러드로 코드를 생성하고, 클러드로 코드를 리뷰하고.." — princox

PR당 $15~25 비용에 대한 우려도 제기됐다.

---

## Hacker News 토론

### 에이전틱 코딩의 실제 증거 ("Do you have any evidence that agentic coding works?")

**가장 통찰력 있는 댓글:**

> *"Fatal flaw: letting agents build from scratch. Success requires agents working on existing human-architected codebases with established conventions. Agents excel at following patterns, not designing architecture."* — resonious
>
> (치명적 결함: 에이전트에게 처음부터 만들게 하는 것. 성공하려면 인간이 설계한 기존 코드베이스에서, 수립된 컨벤션 위에서 작업해야 한다. 에이전트는 패턴을 따르는 건 잘하지만 아키텍처를 설계하진 못한다.)

> *"Doesn't save tremendous time due to review overhead, but serves as effective unblocker and rubber duck."* — sirwhinesalot
>
> (리뷰 오버헤드 때문에 시간 절약은 크지 않지만, 효과적인 '막힘 해소'와 '러버덕 디버깅' 역할)

**5,000줄 한계:**

> *"At 5,000 lines, pure agentic approaches degraded into 'slop'."* — dgunay
>
> (5,000줄에서 순수 에이전틱 접근은 '슬롭'으로 퇴화)

---

### "Vibe Coding" vs. Reality (221포인트 최다 공감)

> *"I think the bigger 'AI hype vs. Reality' gap is about the productivity numbers people casually throw around, like '10x as productive' or even 100x."* — rtfeldman
>
> (더 큰 격차는 사람들이 가볍게 던지는 생산성 수치 — '10배' 혹은 '100배')

YC 파트너들이 배치 전체에서 그런 극적인 개선을 관찰했어야 하지만, 실제로는 그렇지 않았다는 지적.

**현직 경험 공유:**

> 오프쇼어 개발자 2명이 무분별한 LLM 사용으로 유지보수 불가능한 코드를 만들어 해고됨 — redleggedfrog

> 코딩 경험 없는 18명의 전문가에게 기능적 소프트웨어를 만들게 한 성공 경험 — dr_dshiv

---

### AI가 소프트웨어 엔지니어를 대체하지 못하는 이유

**트랙터 비유에 대한 반박:**

> *"The tractor analogy keeps coming up... The question for software isn't whether AI creates efficiency. It's whether there's somewhere else for displaced engineers to go."* — augusteo
>
> (소프트웨어에서의 질문은 AI가 효율을 만드느냐가 아니라, 대체된 엔지니어들이 갈 곳이 있느냐)

> *"Combine tractors deleted jobs. You can't say there are as many combine tractor drivers as there were crop pickers..."* — direwolf20

**가장 가슴 아픈 실제 경험:**

> 8년 만에 해고당하고 간호학으로 전직 중 — "AI is eating my career." — paul7986

---

### Anthropic 노동시장 보고서 HN 토론 (333포인트)

> *"I was at a big tech for last 10 years, quit my job last month — I feel 50x more productive outside than inside."* — vb7132

> *"The amount of issues and bugs is insane... my mental model of the codebase has severely degraded."* — mirsadm
>
> (이슈와 버그의 양이 미쳤다. 코드베이스에 대한 내 멘탈 모델이 심각하게 퇴화했다.)

> 20,000줄의 XNA 게임을 PhaserJS로 여러 번 변환 시도 → "한 번도 작동하지 않았고 근처에도 못 갔다" — Madmallard

---

### AI 코드 품질 ("2025 State of AI Code Quality")

**팀 리더의 현장 경험:**

> *"Our execs keep pushing 'vibe-coding' and agentic coding, but IMO these are just tools."* — ilitirit
>
> 배칭 기능을 위해 수백 줄 + 여러 클래스로 된 AI 코드를 거절하고, 메서드 2개 + 필드 1개로 해결한 사례.

> *"AI has become very capable of solving problems of low-to-intermediate complexity. But it requires extreme discipline to vet the code afterward."* — wbharding
>
> (AI가 낮은~중간 복잡도 문제 해결에 능하지만, 이후 검증에 극도의 훈련이 필요하다)

---

## 커뮤니티 전반에서 반복되는 핵심 논점

여러 커뮤니티를 관통하는 공통 주제를 정리하면:

### 1. 가치가 "생성"에서 "검증"으로 이동
AI가 코드 생산 비용을 0에 가깝게 만들면서, 진짜 가치는 그 코드가 맞는지 판단하는 능력에 있다.

### 2. 5,000줄 한계와 3개월 벽
에이전틱 코딩은 소규모에서 효과적이지만, 5,000줄 이상 또는 3개월 이상 프로젝트에서 "슬롭"으로 퇴화하는 패턴.

### 3. 대기업 vs 소규모 팀의 극적 격차
대기업에서는 회의/보안 검토/시스템 통합 등 비코딩 업무가 많아 AI 효과가 제한적. 소규모 팀에서는 "50배 생산성" 체감.

### 4. 아웃소싱 역사의 반복
과거 오프쇼어링 열풍과 같은 패턴을 밟고 있다는 시각이 강하다.

### 5. "프로그램 vs 제품"
바이브 코딩은 "프로그램"은 만들 수 있지만, 유지보수 가능한 "제품"은 만들지 못한다.

### 6. 멘탈 모델의 퇴화
AI를 많이 쓸수록 개발자 자신의 코드베이스 이해도가 떨어지는 역설.

---

## 참고 자료

- [LLM은 올바른 코드를 작성하지 않는다 — GeekNews](https://news.hada.io/topic?id=27296)
- [60살인데요. Claude Code 덕분에 — GeekNews](https://news.hada.io/topic?id=27295)
- [AI 시대에 코드 리뷰, 어떻게 해야할까? — GeekNews](https://news.hada.io/topic?id=27316)
- [AI가 개발자를 대치할 수 있을까? — GeekNews](https://news.hada.io/topic?id=19207)
- [Claude Code 코드 리뷰 기능 공개 — GeekNews](https://news.hada.io/topic?id=27362)
- ["Vibe Coding" vs. Reality — HN](https://news.ycombinator.com/item?id=43448432)
- [Do you have any evidence that agentic coding works? — HN](https://news.ycombinator.com/item?id=46691243)
- [Labor market impacts of AI — HN](https://news.ycombinator.com/item?id=47268391)
- [2025 State of AI Code Quality — HN](https://news.ycombinator.com/item?id=44257283)
- [AI will not replace software engineers — HN](https://news.ycombinator.com/item?id=46766493)
