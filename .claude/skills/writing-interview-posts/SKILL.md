---
name: writing-interview-posts
description: Use when writing an "Interview" category post for devbaeji.github.io from the KakaoTalk open-chat CSV export of daily backend interview questions ("오늘의 백엔드 질문"), when the user asks to pick or list interview questions from that CSV, or when checking which questions were already posted.
---

# 기술면접 질문 포스트 작성

카카오톡 오픈채팅 "하루 백엔드 개발자 기술면접 문제"의 CSV 내보내기에서 질문을 골라
**Interview** 카테고리 포스트로 정리한다. 목표는 "질문 요약본"이 아니라
**질문 하나를 실무 레퍼런스 한 편으로 확장**하는 것이다.

**REQUIRED SUB-SKILL:** 톤·front matter·Liquid 규칙은 `writing-blog-posts`,
callout 규칙은 `writing-blog-callouts` 를 그대로 따른다. 이 스킬은 그 위에 얹는 추가 규칙만 담는다.

## 절차

### 1. 질문은 `questions.json` 에서 조회한다 (CSV를 직접 읽지 않는다)

원본 CSV는 잡담·입장 알림·재게시가 섞인 759행이고 헤더 형식이 네 번 바뀌었다.
스크립트가 이를 정제해 `.claude/skills/writing-interview-posts/questions.json` (로컬 전용, gitignore) 에 담고,
모든 조회는 이 JSON만 읽는다.

```bash
S=.claude/skills/writing-interview-posts/scripts/extract_questions.py
python3 $S --pending          # 아직 포스트하지 않은 질문 목록 (id, 날짜, 질문)
python3 $S --id 9             # 한 건의 질문·해설·꼬리질문·모범답안을 JSON으로
python3 $S --list             # 전체 목록 (✔ = 포스트 완료)
python3 $S --export [CSV]     # 새 CSV 내보내기가 왔을 때만: 신규 질문을 JSON에 병합
```

- `questions.json` 이 없다고 나오면 `--export` 를 먼저 실행한다. CSV 경로를 생략하면 `~/Downloads` 의 최신 `KakaoTalk_Chat_하루 백엔드*.csv` 를 쓴다.
- `--export` 는 병합이다. 기존 항목의 id를 유지하고 새 질문만 뒤에 붙이므로, 원본 CSV는 병합 뒤 지워도 된다.
- 포스트 완료 여부는 `_posts`·`_drafts` front matter의 `interview_date` 로 판단한다. JSON에는 저장하지 않는다.
- `has_question: false` 인 항목은 질문 없이 설명문으로 시작하는 게시글이다. 첫 문장을 보고 **면접 질문 형태로 직접 재구성**한다.
- 같은 질문이 어미만 바뀌어 재게시된 경우 스크립트가 한 건으로 합친다.

### 2. 질문 선택 기준

사용자가 지정하지 않았으면 `--pending` 목록에서 아래 순으로 고르고, 고른 이유를 한 줄로 알린다.

1. 기존 `_posts` 에 같은 주제의 TIL/Backend 글이 있어 **내 경험과 본문으로 연결할 수 있는 질문**
2. 실무에서 설계 결정으로 이어지는 질문 (락, 트랜잭션, 멱등성, 캐시, 배포 전략 등)
3. 정의만 묻는 질문 (TCP vs UDP 등)은 후순위

### 3. 출처와 저작권

- 원본 CSV와 `questions.json` 은 **커밋하지 않는다.** JSON에는 다른 참여자 대화는 없지만 운영자의 해설문이 들어 있다.
- 포스트로 가져오는 것은 **질문 문장과 꼬리질문 문장**까지다. 운영자의 해설·모범답안 문장은 그대로 옮기지 않고, 근거로만 참고해 본문을 새로 쓴다.
- 포스트 상단에 출처를 한 줄로 밝힌다(아래 구성 참고). 운영 업체명·링크는 넣지 않는다.

## 포스트 구성

Front matter는 `writing-blog-posts` 규칙에 `interview_date` 한 줄을 더한다. 이 값이 추적 키다.

```yaml
---
title: "[Interview] {질문을 결론형 제목으로 바꾼 한 줄}"
date: {오늘 YYYY-MM-DD} 09:00:00 +0900
categories: [Interview]
tags: [backend, interview, {주제 키워드 3~5개, 소문자-케밥}]
interview_date: {원 게시일 YYYY-MM-DD}
---
```

본문은 다음 순서로 구성한다. 각 항목은 실제로 존재하는 절이다.

1. **출처 인용 블록** — `> 질문 출처: 백엔드 기술면접 오픈채팅 "오늘의 백엔드 질문" ({원 게시일}). 해설과 실무 적용은 직접 정리한 내용이다.`
2. **질문과 결론** — 원 질문을 `##` 제목으로 두고, 첫 문단에서 결론을 한 문장으로 단정한다. "이 질문이 확인하려는 것"을 한 문단으로 덧붙인다.
3. **메커니즘** — 왜 그런지. 코드 5~20줄 또는 표. 개념 정의 박스(파랑) 1개는 여기에 둔다.
4. **실무 적용** — `## 실무에서는 어떻게 되는가` 절. 언제 이 답이 설계 결정으로 바뀌는지, 어떤 선택지가 있는지 표로 압축한다. 기존 포스트에 근거가 있으면 그 경험을 **본문 1인칭 서술**("~했다")로 한두 문장 연결하고 해당 포스트 링크를 건다. 경험 박스(`From experience`)는 쓰지 않는다. 근거가 되는 기존 포스트가 없으면 경험을 지어내지 않고, 사용자에게 "이 주제로 남길 실제 경험이 있는지" 한 번 묻는다.
5. **꼬리질문** — 스크립트가 뽑은 `tail_questions` 중 2~3개를 골라 **Q&A 박스(파랑, 4단 구조)** 로 본문 흐름 중간에 배치한다. 꼬리질문이 없는 게시글이면 본문에서 자연스럽게 파생되는 질문을 직접 만든다.
6. **정리** — 마지막 절. 글의 요점을 3~4문장으로 본문에서 도출해 적는다. 면접 답변 형식("면접에서 답할 때", 30초 답변)으로 쓰지 않는다 — 블로그는 포트폴리오로 제출될 수 있다. 운영자의 모범답안을 옮겨 적지 않는다.

callout은 정의 0~1 + Q&A 1~2로 꼭 필요한 것만 둔다.

## 체크리스트

- [ ] `interview_date` 가 front matter에 있고 `--list` 에서 ✔ 로 표시되는가?
- [ ] 운영자 해설 문장이 그대로 들어가지 않았는가? (본문은 `~한다` 체, 원문은 `~합니다` 체라 섞이면 바로 드러난다)
- [ ] 경험 서술이 있다면 기존 포스트 링크 또는 사용자가 확인한 실제 경험에 근거하는가?
- [ ] "면접에서 답할 때"·면접 대비 안내 같은 프레이밍이 본문에 없는가?
- [ ] `writing-blog-posts`·`writing-blog-callouts` 체크리스트를 통과하는가?
