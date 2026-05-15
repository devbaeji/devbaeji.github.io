---
title: "[Frontend] 회고 — AI 페어로 디자인 시스템 만든 1년 — 디자인 시스템 시리즈 (8/9)"
date: 2026-05-22 10:00:00 +0900
categories: [Frontend, Design System]
tags: [retrospective, ai-workflow, claude-code, design-system, lessons-learned]
mermaid: true
---

> **시리즈**
> (1) [공통 UI를 독립 npm 패키지로 분리하기](/posts/design-system-part1-package-split/)
> (2) [Figma 디자인 토큰을 단일 진실 소스로 만들기](/posts/design-system-part2-token-design/)
> (3) [JSON → CSS Variables → Tailwind v4 변환 스크립트 해부](/posts/design-system-part3-converter-script/)
> (4) [48개 컴포넌트를 CVA + Semantic 토큰으로 통일하기](/posts/design-system-part4-cva-components/)
> (5a) [Figma 영역을 코드로 옮기는 실전 자동화](/posts/design-system-part5a-figma-porting/)
> (5b) [아직 빈 구멍 — 무엇이 부족하고 어떻게 메울 것인가](/posts/design-system-part5b-gaps-and-roadmap/)
> (6) [AI 에이전트로 패키지 개발 자동화하기](/posts/design-system-part6-ai-agent-infra/)
> (7) [소비자 측 검증 — 자체 ESLint 룰 만들기](/posts/design-system-part7-eslint-rules/)
> (8) **회고: AI 페어로 디자인 시스템 만든 1년** ← 현재 글

1년 동안 AI(Claude Code)와 페어로 디자인 시스템을 만들었다. 단순히 "AI에게 코드 짜라고 시켰다"가 아니라, **무엇을 AI에게 위임하고 무엇을 사람이 결정했는지** 의 경험이 쌓였다. 이 편은 그 경험의 정직한 회고다. 일반론 말고 우리 케이스에서 실제로 효과 있던 것, 안 됐던 것, 다시 한다면 다르게 할 것.

---

## 1. AI 위임 매트릭스 — 무엇을 누구에게

가장 중요한 결정은 **"이 작업을 사람이 할까 AI가 할까"** 다. 1년 운영하면서 굳어진 분류:

<style>
.ai-matrix { display: grid; grid-template-columns: 40px 1fr 1fr; grid-template-rows: auto 1fr 1fr 40px; gap: 12px; max-width: 760px; margin: 2.5rem auto 1.5rem; font-family: inherit; }
.ai-matrix .y-label { grid-column: 1; grid-row: 2 / 4; writing-mode: vertical-rl; transform: rotate(180deg); display: flex; align-items: center; justify-content: center; font-size: 0.8rem; color: #888; font-weight: 600; letter-spacing: 0.05em; }
.ai-matrix .x-label { grid-column: 2 / 4; grid-row: 4; text-align: center; padding-top: 0.4rem; font-size: 0.8rem; color: #888; font-weight: 600; letter-spacing: 0.05em; }
.ai-matrix .quad { padding: 1.1rem 1.2rem; border-radius: 10px; border: 1px solid; display: flex; flex-direction: column; min-height: 180px; }
.ai-matrix .quad-title { font-weight: 700; font-size: 1rem; margin-bottom: 0.2rem; letter-spacing: -0.02em; }
.ai-matrix .quad-desc { font-size: 0.78rem; color: #888; margin-bottom: 0.9rem; }
.ai-matrix .quad-chips { display: flex; flex-wrap: wrap; gap: 0.35rem; }
.ai-matrix .chip { display: inline-block; padding: 0.28rem 0.65rem; border-radius: 5px; font-size: 0.78rem; line-height: 1.3; font-weight: 500; }

/* 라이트 모드 (기본) */
.ai-matrix .q-tl { grid-column: 2; grid-row: 2; background: rgba(250, 204, 21, 0.08); border-color: rgba(250, 204, 21, 0.35); }
.ai-matrix .q-tl .quad-title { color: #ca8a04; }
.ai-matrix .q-tl .chip { background: rgba(250, 204, 21, 0.2); color: #78350f; }

.ai-matrix .q-tr { grid-column: 3; grid-row: 2; background: rgba(239, 68, 68, 0.08); border-color: rgba(239, 68, 68, 0.35); }
.ai-matrix .q-tr .quad-title { color: #dc2626; }
.ai-matrix .q-tr .chip { background: rgba(239, 68, 68, 0.2); color: #7f1d1d; }

.ai-matrix .q-bl { grid-column: 2; grid-row: 3; background: rgba(34, 197, 94, 0.08); border-color: rgba(34, 197, 94, 0.35); }
.ai-matrix .q-bl .quad-title { color: #16a34a; }
.ai-matrix .q-bl .chip { background: rgba(34, 197, 94, 0.2); color: #14532d; }

.ai-matrix .q-br { grid-column: 3; grid-row: 3; background: rgba(59, 130, 246, 0.08); border-color: rgba(59, 130, 246, 0.35); }
.ai-matrix .q-br .quad-title { color: #2563eb; }
.ai-matrix .q-br .chip { background: rgba(59, 130, 246, 0.2); color: #1e3a8a; }

/* 다크 모드 (Chirpy 토글 기준) */
html[data-mode="dark"] .ai-matrix .q-tl .quad-title { color: #fbbf24; }
html[data-mode="dark"] .ai-matrix .q-tl .chip { background: rgba(250, 204, 21, 0.16); color: #fde68a; }
html[data-mode="dark"] .ai-matrix .q-tr .quad-title { color: #f87171; }
html[data-mode="dark"] .ai-matrix .q-tr .chip { background: rgba(239, 68, 68, 0.18); color: #fecaca; }
html[data-mode="dark"] .ai-matrix .q-bl .quad-title { color: #4ade80; }
html[data-mode="dark"] .ai-matrix .q-bl .chip { background: rgba(34, 197, 94, 0.18); color: #bbf7d0; }
html[data-mode="dark"] .ai-matrix .q-br .quad-title { color: #60a5fa; }
html[data-mode="dark"] .ai-matrix .q-br .chip { background: rgba(59, 130, 246, 0.18); color: #bfdbfe; }

/* 시스템 다크 모드 fallback (Chirpy 토글이 시스템 설정을 따라갈 때 대비) */
@media (prefers-color-scheme: dark) {
  html:not([data-mode="light"]) .ai-matrix .q-tl .quad-title { color: #fbbf24; }
  html:not([data-mode="light"]) .ai-matrix .q-tl .chip { background: rgba(250, 204, 21, 0.16); color: #fde68a; }
  html:not([data-mode="light"]) .ai-matrix .q-tr .quad-title { color: #f87171; }
  html:not([data-mode="light"]) .ai-matrix .q-tr .chip { background: rgba(239, 68, 68, 0.18); color: #fecaca; }
  html:not([data-mode="light"]) .ai-matrix .q-bl .quad-title { color: #4ade80; }
  html:not([data-mode="light"]) .ai-matrix .q-bl .chip { background: rgba(34, 197, 94, 0.18); color: #bbf7d0; }
  html:not([data-mode="light"]) .ai-matrix .q-br .quad-title { color: #60a5fa; }
  html:not([data-mode="light"]) .ai-matrix .q-br .chip { background: rgba(59, 130, 246, 0.18); color: #bfdbfe; }
}

/* 모바일 반응형 */
@media (max-width: 640px) {
  .ai-matrix { grid-template-columns: 24px 1fr; grid-template-rows: auto repeat(4, 1fr) 30px; }
  .ai-matrix .y-label { grid-row: 2 / 6; }
  .ai-matrix .x-label { grid-column: 1 / 3; grid-row: 6; }
  .ai-matrix .q-tl { grid-column: 2; grid-row: 2; }
  .ai-matrix .q-tr { grid-column: 2; grid-row: 3; }
  .ai-matrix .q-bl { grid-column: 2; grid-row: 4; }
  .ai-matrix .q-br { grid-column: 2; grid-row: 5; }
}
</style>

<div class="ai-matrix">
  <div class="y-label">결정 영향 작음 ─────────── 결정 영향 큼</div>

  <div class="quad q-tl">
    <div class="quad-title">사람 검토 후 AI</div>
    <div class="quad-desc">자기완결적 · 영향 큼</div>
    <div class="quad-chips">
      <span class="chip">릴리스 노트 작성</span>
      <span class="chip">PR 본문 템플릿</span>
    </div>
  </div>

  <div class="quad q-tr">
    <div class="quad-title">사람만</div>
    <div class="quad-desc">컨텍스트 풍부 · 영향 큼</div>
    <div class="quad-chips">
      <span class="chip">네이밍 컨벤션 결정</span>
      <span class="chip">토큰 계층 구조</span>
      <span class="chip">Breaking Change 판단</span>
      <span class="chip">UI 트레이드오프</span>
    </div>
  </div>

  <div class="quad q-bl">
    <div class="quad-title">AI에게 위임</div>
    <div class="quad-desc">자기완결적 · 영향 작음</div>
    <div class="quad-chips">
      <span class="chip">재귀 traversal 로직</span>
      <span class="chip">정규식 normalizer</span>
      <span class="chip">JSON 파싱 함수</span>
    </div>
  </div>

  <div class="quad q-br">
    <div class="quad-title">AI와 사람 페어</div>
    <div class="quad-desc">컨텍스트 풍부 · 영향 작음</div>
    <div class="quad-chips">
      <span class="chip">CSS 번들링 전략</span>
      <span class="chip">토큰 마이그레이션 스크립트</span>
    </div>
  </div>

  <div class="x-label">적은 컨텍스트 ─────────── 많은 컨텍스트</div>
</div>

### 1-1. AI에게 위임 (좌하 분면)

**조건**: 컨텍스트 자기완결적 + 결정 영향 제한적

- **재귀 traversal**: 중첩 객체를 평탄화하는 로직. 정답이 있고 검증 가능.
- **정규식 normalizer**: box-shadow의 중복 length 제거 같은 정해진 변환.
- **JSON 스키마 변환**: A 형식 → B 형식 매핑.

이런 건 AI가 잘한다. 코드의 정확도가 결과로 즉시 검증되니까.

### 1-2. AI + 사람 페어 (우하 분면)

**조건**: 컨텍스트 풍부 + 결정 영향 제한적

- **CSS 번들링 전략**: Radix Themes + tokens + figma-tokens 합치는 순서. AI가 초안 짜고 사람이 우선순위 확인.
- **마이그레이션 스크립트**: v1.x.x → v2.0.0 토큰 변경 일괄 적용. AI가 짜고 사람이 검토.

### 1-3. 사람 검토 후 AI (좌상 분면)

**조건**: 컨텍스트 자기완결적 + 결정 영향 큼

- **릴리스 노트 톤**: AI가 변경사항 자동 추출 → 사람이 톤·강조점 결정.
- **PR 본문 작성**: AI가 기본 템플릿 생성 → 사람이 영향도 평가 추가.

### 1-4. 사람만 (우상 분면)

**조건**: 컨텍스트 풍부 + 결정 영향 큼

- **네이밍 컨벤션**: `atomic-`/`semantic-` prefix 같은 시스템 전체에 영향 주는 결정.
- **토큰 계층 구조**: 2-레이어 vs 3-레이어 같은 아키텍처 결정.
- **Breaking Change 판단**: 어디까지가 PATCH고 어디부터가 MAJOR인지.
- **UI 트레이드오프**: Storybook v10 vs Ladle 같은 도구 선택.

AI는 결정 옵션을 제시할 수 있지만, **결정 자체는 사람**이어야 한다. 이유는 다음 섹션에서.

> **Q.** AI가 더 똑똑해지면 이 매트릭스의 우상 분면도 결국 AI가 할 수 있게 되지 않나? 임시 처방 아닌가?
>
> 부분적으로 맞다. AI의 컨텍스트 처리 능력이 늘면 우하 → 우상으로 영역이 이동할 거다.
>
> 하지만 우상 분면이 완전히 사라지진 않을 거라고 본다. 이유는 세 가지.
>
> 책임 소재 — 잘못된 Breaking Change 결정의 책임은 사람이 져야 한다. AI에게 "왜 v2.0.0으로 올렸어?"라고 추궁할 수 없다. 조직 정렬 — 네이밍 컨벤션은 디자이너·기획자와의 합의가 필요한데 AI는 그 자리에 못 들어간다. 장기 결정 — 토큰 계층은 5년짜리 의사결정인데 AI는 *지금 시점의* 최적해를 줄 뿐, 5년 후 변화를 예측 못 한다.
>
> 결정의 결과를 *사람이 감당해야 하는 영역*은 영원히 사람의 자리. 다만 AI가 옵션 제시·근거 정리·트레이드오프 시각화를 더 잘하게 되면서, 사람의 결정이 더 빠르고 정확해지는 방향으로는 갈 거다.
{: .prompt-info }

---

## 2. AI가 잘한 것 — 실측

1년 동안의 작업 패턴을 돌아보며 AI가 정말 효과적이었던 케이스 5가지.

### 2-1. 1,265줄 변환 스크립트의 80%

`generate-figma-tokens.js`의 핵심 로직 — 재귀 traversal, opacity 추출, shadow normalizer — 의 80%는 AI 초안에서 거의 그대로 살아남았다. 사람은 다음만 했다:
- 함수 분리 (한 큰 함수 → 5개 작은 함수)
- 주석 추가
- 예외 케이스 보완 (빈 객체, 누락 키 등)

AI 단독은 약했지만 사람의 가이드(JSDoc 주석으로 명세 먼저 작성)와 결합되니 강력.

### 2-2. CLAUDE.md 룰 적용

가장 효과 컸던 부분. 룰을 적은 만큼 AI가 그 룰을 따라 코드를 생성한다.

```
v1.x.x 시절: bg-blue-70 (Tailwind 기본 색)
v2.0.0 도입 후 CLAUDE.md 갱신: bg-atomic-blue-70 강제
→ AI가 새 코드를 만들 때마다 자동으로 atomic-/semantic- prefix 사용
```

룰 갱신 한 줄이 곧 코드 일관성 자동 강제. 사람이 일일이 검토하지 않아도 됨.

### 2-3. 점진적 마이그레이션

v1.x.x → v2.0.0 토큰 prefix 변경 같은 대규모 마이그레이션:

```
명령: "src/ 안의 모든 bg-blue-X를 bg-atomic-blue-X로 바꿔.
       단, hover:, focus: 같은 모디파이어도 같이.
       동적 className은 손대지 마."

결과: 1시간 안에 200+ 파일 마이그레이션. 사람이 1주일 걸릴 일.
```

### 2-4. 컴포넌트 패턴 복제

"Button 패턴을 따라 새 Toast 컴포넌트 만들어줘" 한 줄로:
- CVA 구조 정확히 따라옴
- compoundVariants 매트릭스 자동 채움
- data-component attribute 자동 추가
- semantic 토큰만 사용

기존 컴포넌트가 일관됐기 때문에 AI도 일관되게 따라옴.

### 2-5. 테스트 코드 생성

Storybook story, ESLint 룰 테스트 케이스 — 정답이 있는 영역에서 강함. 사람은 "이 케이스 추가해줘" 한 줄로 끝.

> **Q.** AI 위임을 더 늘리면 신입 개발자의 학습이 정체되지 않나? "AI가 다 해주니까" 식으로 코드 작성 기초가 약해질 텐데.
>
> 1년 굴려보면서 가장 자주 받은 질문이고, 가장 명확하게 답할 수 있는 질문이기도 하다.
>
> 정체된다. 그냥 "AI에게 시켜"로 가면 신입은 *왜 그 코드가 그렇게 짜였는지*를 모른 채로 넘어간다. 우리 팀이 이걸 막은 방식은 *AI가 짠 코드를 PR 리뷰에서 의도적으로 깊이 파헤치는 문화*였다. "왜 compoundVariants가 이 순서야?", "이 prefix가 왜 필요해?" 같은 질문을 신입에게 묻는다. AI는 답할 수 없으니까 신입이 직접 찾아봐야 한다.
>
> AI 위임은 *코드 양산*을 가속할 뿐, *학습*은 여전히 사람의 일이다. 오히려 AI가 빠르게 정답 후보를 던져주니까 신입이 "왜 그 답인지"를 빠르게 검증할 수 있는 환경이 됐다. 학습 곡선의 모양이 *느리고 평탄*에서 *빠르고 가파름*으로 바뀐 셈.
{: .prompt-info }

---

## 3. AI가 못한 것 — 정직하게

### 3-1. 네이밍 결정

`atomic-` vs `primitive-` vs `core-` 중 뭘 prefix로 쓸까. AI에게 물으면 "셋 다 흔한 패턴입니다"라고 답함. **결정을 못 함.**

결정은 "디자이너와의 합의", "기존 코드와의 정합성", "팀의 직관" 같은 비기술적 요소가 섞여야 가능. AI는 옵션을 정리할 뿐.

### 3-2. 트레이드오프 균형

"빌드 시간 5초 vs 번들 크기 -10KB" 같은 트레이드오프 결정. AI는 양쪽 장단점을 정리할 수 있지만 **우리 팀에 무엇이 더 중요한지** 는 모름. 빌드 시간이 중요한 팀과 번들 크기가 중요한 팀이 다른 선택을 함.

### 3-3. 장기 결정

"v2.0.0으로 갈까 v1.1.0으로 갈까". 미래의 호환성·마이그레이션 비용·사용자 경험을 종합 판단해야 함. AI는 지금 시점의 코드 영향만 봄.

### 3-4. 회의에서의 합의

디자이너와 "이 토큰 구조 어떻게 갈까" 토론하는 자리. AI는 거기 없다. 사람이 합의를 도출하고 결과를 가져와서 AI에게 구현 위임.

### 3-5. 도메인 특수 룰

"우리 회사의 브랜드 컬러는 brandABlue다" 같은 도메인 사실은 CLAUDE.md에 명시해야 AI가 안다. 명시 없으면 일반론적 답변. AI가 자체 학습으로 도메인 지식을 갖추는 게 아님.

> **Q.** CLAUDE.md를 갱신하는 것도 결국 사람이다. 그 시간은 누가 어떻게 만드나?
>
> 솔직히 자주 빠뜨린다. CLAUDE.md 갱신은 *코드 변경의 부수 작업*이라 PR 리뷰에서 자주 누락된다.
>
> 우리가 정착시킨 패턴 두 가지. 첫째, *PR 템플릿에 "CLAUDE.md 갱신 필요?" 체크박스*. 디자인 토큰 룰이 바뀌거나 새 패턴이 도입될 때 PR 작성자가 의도적으로 확인. 둘째, *금요일 1~2시간 인프라 day*. sprint 외 시간이라 압박 없이 누적된 갱신 사항을 한 번에 처리.
>
> 그래도 가끔은 빠진다. 빠지면 AI가 옛 룰을 따라 코드를 짜고, PR 리뷰에서 "어? 이거 옛날 패턴인데?" 발견되면 그제서야 CLAUDE.md를 본다. *실패가 발견되면 그때 룰 갱신*하는 reactive 패턴도 같이 굴린다. proactive + reactive 둘 다.
{: .prompt-info }

---

## 4. 일하는 방식의 변화

1년 동안 일하는 방식이 구조적으로 바뀌었다.

### Before (AI 도입 전)

```
1. 시안 받음 → 2. 직접 보면서 코드 짬 → 3. 테스트 → 4. PR → 5. 리뷰 → 6. 머지
```

각 단계가 직렬. 한 명이 모든 단계를 거침.

### After (AI 페어)

```
1. 시안 받음
2. figma-dev에 분석 위임 → Delta Report
3. (병렬) typescript-dev로 패치 / ui-qa로 검증 페이지 준비
4. 사람이 결과 검토 + 통합
5. release skill로 PR + 머지 흐름
6. ui-qa로 시각 회귀 검증
```

각 단계가 *위임 가능한 작업*과 *사람의 결정*으로 분리됨. 사람은 검토와 결정에 집중.

### 시간 사용의 재분배

<style>
.time-shift { display: grid; grid-template-columns: 1fr 1fr; gap: 24px; max-width: 820px; margin: 2.5rem auto; font-family: inherit; }
.time-shift .side { padding: 1.2rem 1.3rem; border-radius: 12px; border: 1px solid; }
.time-shift .side-label { font-size: 0.7rem; font-weight: 800; letter-spacing: 0.12em; text-transform: uppercase; margin-bottom: 0.3rem; }
.time-shift .side-title { font-weight: 700; font-size: 1rem; margin-bottom: 1.2rem; letter-spacing: -0.02em; }
.time-shift .row { display: grid; grid-template-columns: 1fr 40px; gap: 8px; align-items: center; margin-bottom: 0.6rem; }
.time-shift .row-label { font-size: 0.82rem; }
.time-shift .row-value { font-size: 0.85rem; font-weight: 700; text-align: right; color: #555; font-family: 'SF Mono', Menlo, monospace; }
.time-shift .bar-wrap { grid-column: 1 / 3; height: 8px; background: rgba(120, 120, 120, 0.12); border-radius: 4px; overflow: hidden; margin-bottom: 0.6rem; }
.time-shift .bar { height: 100%; border-radius: 4px; }
.time-shift .c-code { background: #94a3b8; }
.time-shift .c-test { background: #f59e0b; }
.time-shift .c-pr { background: #8b5cf6; }
.time-shift .c-review { background: #22c55e; }
.time-shift .c-infra { background: #ef4444; }

.time-shift .before { background: rgba(120, 120, 120, 0.05); border-color: rgba(120, 120, 120, 0.25); }
.time-shift .before .side-label { color: #888; }
.time-shift .after { background: rgba(34, 197, 94, 0.05); border-color: rgba(34, 197, 94, 0.3); }
.time-shift .after .side-label { color: #16a34a; }

html[data-mode="dark"] .time-shift .row-value { color: #ccc; }
html[data-mode="dark"] .time-shift .bar-wrap { background: rgba(255, 255, 255, 0.08); }

@media (max-width: 640px) {
  .time-shift { grid-template-columns: 1fr; }
}
</style>

<div class="time-shift">
  <div class="side before">
    <div class="side-label">Before · AI 도입 전</div>
    <div class="side-title">작업 시간 분배</div>

    <div class="row"><span class="row-label">💻 코드 작성</span><span class="row-value">50%</span></div>
    <div class="bar-wrap"><div class="bar c-code" style="width: 50%"></div></div>

    <div class="row"><span class="row-label">🧪 테스트와 검증</span><span class="row-value">20%</span></div>
    <div class="bar-wrap"><div class="bar c-test" style="width: 20%"></div></div>

    <div class="row"><span class="row-label">📄 PR과 문서</span><span class="row-value">15%</span></div>
    <div class="bar-wrap"><div class="bar c-pr" style="width: 15%"></div></div>

    <div class="row"><span class="row-label">🎯 결정과 리뷰</span><span class="row-value">15%</span></div>
    <div class="bar-wrap"><div class="bar c-review" style="width: 15%"></div></div>
  </div>

  <div class="side after">
    <div class="side-label">After · AI 페어</div>
    <div class="side-title">작업 시간 분배</div>

    <div class="row"><span class="row-label">💻 코드 작성</span><span class="row-value">15%</span></div>
    <div class="bar-wrap"><div class="bar c-code" style="width: 15%"></div></div>

    <div class="row"><span class="row-label">🧪 테스트와 검증</span><span class="row-value">10%</span></div>
    <div class="bar-wrap"><div class="bar c-test" style="width: 10%"></div></div>

    <div class="row"><span class="row-label">📄 PR과 문서</span><span class="row-value">5%</span></div>
    <div class="bar-wrap"><div class="bar c-pr" style="width: 5%"></div></div>

    <div class="row"><span class="row-label">🎯 결정과 리뷰</span><span class="row-value">50%</span></div>
    <div class="bar-wrap"><div class="bar c-review" style="width: 50%"></div></div>

    <div class="row"><span class="row-label">⚙️ AI 인프라 유지</span><span class="row-value">20%</span></div>
    <div class="bar-wrap"><div class="bar c-infra" style="width: 20%"></div></div>
  </div>
</div>

흥미로운 변화 두 가지:
1. **결정/리뷰가 절반 이상 차지**: 코드 양산이 아니라 *방향성*에 시간 씀.
2. **AI 인프라 유지가 20% 등장**: CLAUDE.md, .claude/ 자체를 가꾸는 시간이 새 작업 카테고리로.

> **Q.** "AI 인프라 유지에 20% 쓴다"가 의외였다. 비용이 아니라 투자로 볼 수 있나?
>
> 투자다. 다만 *명시적으로 시간을 배정하지 않으면 안 한다*.
>
> 비용은 의무적으로 들여야 하지만 직접 가치를 안 만들고, 투자는 지금 들이면 미래에 더 큰 효과로 돌아온다. AI 인프라 유지(CLAUDE.md 갱신, skill 개선, 새 hook 추가)는 후자다. 룰 한 줄 추가하면 그 후 모든 AI 호출이 그 룰을 따른다. 누적 효과가 크다.
>
> 그런데 압박 받는 sprint에선 가장 먼저 잘리는 게 인프라 시간이다. "당장 티켓 처리하기도 바쁜데 CLAUDE.md 갱신할 시간이 어디 있나"가 흔한 함정.
>
> 우리 팀은 매주 금요일 1~2시간을 "AI 인프라 day"로 박아뒀다. sprint 외 작업이라 압박 안 받고, 그 시간엔 *집중적으로 인프라만* 본다. 이 패턴이 누적 효과를 보장했다.
>
> Google SRE의 *toil reduction* 원칙과 같다. toil 50% 초과 시 인프라 개선을 강제하는 식으로 시간을 명시적으로 배정해야 한다.
{: .prompt-info }

---

## 5. 다시 시작한다면 다르게 할 것

### 5-1. CLAUDE.md를 더 일찍 더 깊이

처음 몇 달은 CLAUDE.md가 짧았다. 룰이 부족해서 AI가 "일반적인" 코드를 만들었고, 사람이 매번 수정했다.

다시 한다면: **첫 주에 컨벤션 결정 → 즉시 CLAUDE.md에 박제**. 룰 한 줄이 백 번의 수정을 막음.

### 5-2. 측정 시스템을 처음부터

"얼마나 자동화됐는가"를 정량 측정하지 못했다. "체감상 빨라졌다"는 강력한 주장이 못 됨.

다시 한다면: **첫 sprint부터 메트릭 5개 선정 → 자동 수집**. Jira ticket cycle time, MCP token usage, ESLint 위반 수, PR review iteration, ui-qa PASS 비율. 1년 후 데이터가 강력한 증거.

### 5-3. 표준 도구를 더 검토

자체 release skill을 만들기 전에 changesets, release-please를 더 깊이 봤어야 함. 표준 도구의 호환성과 커뮤니티 지원은 무시 못 함.

다시 한다면: **표준 도구 1주 prototype → 우리 케이스에 안 맞으면 자체 빌드**. 자체 빌드 후 표준 도구가 따라잡으면 마이그레이션 비용.

### 5-4. 에이전트 역할 분리를 처음부터

처음엔 모든 걸 "Claude에게 묻기"였다. 권한 격리 없음. 한 컨텍스트에서 분석·코드·검증 다 함. 컨텍스트 폭주.

다시 한다면: **figma-dev / typescript-dev / ui-qa 같은 역할 분리를 첫 달부터**. 권한 격리 + 컨텍스트 절약 + 재시도 용이성. 한 번 굳히면 운영 수월.

### 5-5. 측정 부재 → 결정 부재

지표가 없으면 "이 자동화가 정말 효과 있나"를 판단 못 함. → "그냥 계속 한다" 또는 "그냥 안 한다"로 끝남.

다시 한다면: 모든 자동화 도입 시 **"이걸 어떻게 측정할까"** 를 함께 결정. 측정 못 하는 자동화는 만들지 말기.

> **Q.** 이 패턴을 다른 팀에 추천한다면 가장 큰 장벽은?
>
> 도구가 아니라 *조직 문화*가 가장 큰 장벽이다. 우리 팀이 잘 굴린 이유는 디자이너·기획자·개발자가 *토큰 컨벤션을 사전 합의*했기 때문. AI 인프라가 아무리 잘 깔려도 합의가 없으면 AI가 만들어내는 코드 일관성이 무의미하다.
>
> 도구 차원의 장벽은 두 번째. Claude Code 같은 AI 에이전트 도구의 도입 비용, ESLint flat config 마이그레이션, Tailwind v4 학습 곡선. 다 1~2주짜리 작업이라 도구는 *극복 가능한 장벽*이다.
>
> 진짜 어려운 건 첫 번째. *디자이너가 토큰 시스템에 동의하지 않으면* — 예를 들어 "디자이너는 Figma에서 자유롭게 만들고 싶다"가 우선이면 — 토큰 일관성을 코드로 강제할 길이 없다. 이 합의가 안 된 팀에 우리 패턴을 그대로 가져다 쓰라고 하면 6개월 안에 무너진다고 본다.
>
> 추천할 때 항상 먼저 묻는다. "디자이너가 토큰 시스템을 같이 가꿔갈 의사가 있나요?" 이 답이 yes여야 그 다음 도구 이야기를 한다.
{: .prompt-info }

---

## 6. 이 시리즈를 다 쓰고 나서

8편을 다 쓰면서 정리된 메타 관찰:

### 6-1. 정직함이 진짜 자산

5b편(허점 공개)을 쓸 때 망설였다. "이렇게 단점 까면 누가 좋게 보겠나" 싶었다. 결과는 정반대. **단점을 인식하고 측정 가능한 개선 계획을 세울 수 있는 능력**이 시니어다움의 정의에 가까웠다.

### 6-2. 시리즈로 쪼개야 의미가 산다

처음엔 한 편으로 다 쓸 생각이었다. 8편으로 쪼개니 각 편이 독립적으로 검색 노출 + 인용 가능. 한 편 7000자보다 8편 6000자 × 8 = 48000자가 누적 가치가 더 컸음. 콘텐츠 마케팅 관점.

### 6-3. 도식이 글의 절반

각 편마다 Mermaid 다이어그램 4~7개. 다이어그램이 없었다면 글 길이가 두 배가 됐을 것이고 이해도는 절반이 됐을 것. **시각화에 글의 절반을 투자**.

### 6-4. AI가 글을 쓰는 게 아니라, AI와 함께 쓰는 것

이 시리즈 자체도 AI 페어로 썼다. AI가 초안을 빠르게 만들고, 사람이 다음을 결정:
- 어느 사례를 인용할지
- 어느 톤으로 갈지
- 어느 부분을 더 깊이 들어갈지
- 어느 부분을 잘라낼지

AI 단독으로는 "일반론적인 디자인 시스템 글"만 나옴. 사람의 도메인 컨텍스트가 결합되어야 *우리 케이스*가 됨.

---

## 7. 시리즈를 마치며 — 한 줄 요약

> "디자인 시스템은 단일 진실 소스를 코드 레벨까지 끌어내리는 자동화 시스템이고,
> AI는 그 자동화의 어떤 단계는 위임받고 어떤 단계는 사람의 결정을 기다린다.
> 그 분기점을 명확히 한 팀이 빠르게 가고, 안 한 팀은 AI를 써도 사람만큼 느리다."

이 시리즈가 비슷한 길을 가는 누군가에게 한 조각이라도 도움이 됐다면, 우리가 1년 동안 들인 비용이 가치 있었다고 말할 수 있겠다.

---

**시리즈 이전 편**: [소비자 측 검증 — 자체 ESLint 룰 만들기](/posts/design-system-part7-eslint-rules/)
**시리즈 처음**: [공통 UI를 독립 npm 패키지로 분리하기](/posts/design-system-part1-package-split/)
