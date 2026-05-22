---
name: writing-blog-posts
description: Use when creating or editing posts in _posts/*.md for devbaeji.github.io (Jekyll + Chirpy). Defines tone (formal plain-style), composition pattern, front matter, category taxonomy, image placement, code block tags, and Jekyll Liquid escape rules. For callout (prompt box) rules see the separate writing-blog-callouts skill.
---

# 블로그 포스트 작성 규칙

devbaeji.github.io (Jekyll + Chirpy 테마)의 모든 `_posts/*.md` 파일 작성·수정 시 이 규칙을 따른다.
callout(prompt 박스) 작성은 **별도 skill** `writing-blog-callouts`를 함께 참고한다.

## 글 작성 스타일

### 핵심 원칙

1. **실무자 시점에서 정리**
   - "운영해보면", "프로덕션에서는", "현실적으로는" 같은 경험 기반 표현
   - 배움 일기가 아니라 정리/레퍼런스에 가까운 글
   - "처음엔 몰랐는데", "이걸 배우면서" 같은 입문자 톤은 쓰지 않는다

2. **정확한 용어 + 백엔드 비유로 보조**
   - 업계 표준 용어는 그대로 사용 (RAG, Embedding, CQRS, IoC 등)
   - 개념은 친숙한 백엔드 비유로 보조 (예: "Spring의 IoC와 같다", "ETL의 연장선")
   - 용어를 풀어 쓰기보다 callout으로 별도 정리 (`writing-blog-callouts` skill 참고)

3. **격식 있는 평서체**
   - `~한다`, `~이다`, `~된다` 기본
   - `~합니다`, `~했어요`, `~하더라고요` 사용 금지
   - 구어체 어미 전반 회피

### 예시

```markdown
# 나쁜 예 (격식만 있고 통찰 없음)
Reusable Workflow를 활용하여 CI/CD 파이프라인을 최적화했습니다.

# 나쁜 예 (구어체)
GitHub Actions에서 같은 작업을 여러 번 반복하고 있었는데,
이걸 한 곳에서 관리하도록 바꿨어요. (Reusable Workflow라고 부르더라고요)

# 좋은 예
GitHub Actions에서 같은 step이 5개 워크플로우에 중복돼 있었다.
이걸 Reusable Workflow로 묶으니 변경점이 한 곳으로 모이고,
CI 평균 시간도 줄었다. 비유하자면 Spring의 @Configuration을
워크플로우 레벨로 끌어올린 것.
```

## 글 구성 패턴

긴 기술 글은 다음 흐름을 기본으로 한다.

1. **정의** — 한 문장으로 명확히
2. **백엔드 비유** — 친숙한 개념과 연결
3. **대표 도구/모델 표** — 선택지 비교
4. **코드 예시** — 5~20줄, 개념적 의사코드도 OK
5. **의사결정 기준** — 언제 무엇을 고를지

표와 코드 블록을 적극 활용한다. 줄글이 길어지면 표로 압축한다.
시리즈 글은 상단에 인덱스(이전 글 링크 포함)를 인용 블록으로 둔다.

## 파일 위치 & Front Matter

### 파일 위치
`_posts/YYYY-MM-DD-제목.md`

### Front Matter 형식

```yaml
---
title: "[카테고리] 제목"
date: YYYY-MM-DD HH:MM:SS +0900
categories: [대분류, 소분류]
tags: [태그1, 태그2]
---
```

## 카테고리 목록

| 대분류    | 소분류                                       |
|-----------|----------------------------------------------|
| Backend   | Spring, JPA, Kotlin, Java                    |
| Frontend  | React, Next.js, TypeScript, Design System    |
| Infra     | AWS, Docker, Kubernetes, CI/CD               |
| Database  | MySQL, PostgreSQL, Redis                     |
| DevOps    | GitHub Actions, Terraform                    |
| AI        | Document AI, RAG, LLM, Agent                 |
| Insight   | 트렌드, 회고                                  |
| TIL       | 일상적인 배움 기록                            |

## 이미지 추가

이미지는 `/assets/img/posts/` 폴더에 저장 후 사용:

```markdown
![이미지 설명](/assets/img/posts/파일명.png)
```

스크린샷 권장 크기: 가로 800px 이하

## 코드 블록 언어

자주 쓰는 언어 태그:

| 언어 | 태그 |
|------|------|
| Kotlin | `kotlin` |
| Java | `java` |
| TypeScript | `typescript` |
| Python | `python` |
| YAML | `yaml` |
| Bash | `bash` |
| SQL | `sql` |
| JSON | `json` |

## Jekyll Liquid 문법 주의

코드 블록 안에 `${{ }}` 같은 GitHub Actions 문법이 있으면 Jekyll이 오류를 낸다.
`{% raw %}` 태그로 감싸서 해결:

```markdown
{% raw %}
```yaml
key: ${{ hashFiles('**/*.lock') }}
```
{% endraw %}
```

## 미래 날짜 포스트가 안 보일 때

Jekyll은 기본적으로 미래 날짜 포스트를 빌드하지 않는다. `--future` 플래그 필요:

```bash
bundle exec jekyll serve --port 4000 --future
```

## 체크리스트

포스트를 추가/수정한 뒤 다음을 확인한다.

- [ ] 파일명이 `_posts/YYYY-MM-DD-제목.md` 패턴인가?
- [ ] front matter의 `categories`가 위 카테고리 목록 안에 있는가?
- [ ] 본문이 `~한다/~이다` 격식체로 통일됐는가? `~했어요`가 섞이지 않았는가?
- [ ] 시리즈 글이라면 상단 인덱스(인용 블록)에 모든 편 링크가 포함됐는가?
- [ ] callout이 필요하면 `writing-blog-callouts` skill 규칙을 따랐는가?
- [ ] 코드 블록 안 `${{ }}` 문법은 `{% raw %}`로 감쌌는가?
