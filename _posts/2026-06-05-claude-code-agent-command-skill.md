---
title: "Claude Code 의 Agent · Slash Command · Skill — 어디에 두고 어떻게 부르나"
date: 2026-06-05 11:00:00 +0900
categories: [Tools, Claude Code]
tags: [claude-code, ai-agent, tooling, workflow, plugin-system]
---

> Claude Code 를 본격적으로 쓰기 시작하면 세 가지 확장 단위가 동시에 등장한다. **Agent**, **Slash Command**, **Skill** 이 그것이고, 또 각각이 **Project · User · Plugin** 의 세 자리에 살 수 있다. 곱하면 9 칸짜리 매트릭스가 생긴다.
> 이름이 겹치면 누가 이기는지, 어디에 두면 적절한지 정리한다.

---

## 1. 세 가지 확장 단위

### Agent (서브 에이전트)

메인 대화에서 위임받는 **격리 컨텍스트 작업자**. 자체 시스템 프롬프트와 도구 권한을 들고 자기 sub-context 에서 일한다. 결과만 메인으로 돌아온다.

- **호출**: 다른 에이전트가 `Task(subagent_type: "...")` 로 위임
- **실행 위치**: 격리된 sub-context (메인 컨텍스트 오염 방지)
- **파일**: `agents/{이름}.md`

용도: 토큰 비용이 큰 탐색, 평행 작업, 사람이 직접 부르지 않는 보조 작업자.

### Slash Command

**사용자가 직접 입력**하는 명령. 메인 컨텍스트 안에서 실행되어 대화 흐름이 끊기지 않는다.

- **호출**: 사용자가 `/{이름}` 입력
- **실행 위치**: 메인 대화 그대로
- **파일**: `commands/{이름}.md`

용도: 사용자가 출발점을 찍는 워크플로우 (`/synctypes`, `/release` 같은 것).

### Skill

메인 컨텍스트에 **주입되는 절차와 지식의 묶음**. 슬래시 커맨드와 호출 모양은 비슷하지만, **구조화된 폴더 + 보조 파일**을 가질 수 있다는 게 다르다.

- **호출**: 사용자 `/{이름}` 또는 자동 트리거
- **실행 위치**: 메인 대화 + skill 폴더 전체가 컨텍스트로 들어옴
- **파일**: `skills/{이름}/SKILL.md` + 부속 파일들

용도: 단일 마크다운으로 안 끝나는 워크플로우 — 체크리스트, 보조 스크립트, 템플릿이 같이 필요한 작업.

### 한 줄 요약

> Agent = 백그라운드 위임 작업자, Slash Command = 사용자 명령 한 줄로 실행되는 절차, Skill = 절차 + 부속 자원을 묶은 단위. 셋 다 마크다운 파일 + frontmatter 로 정의.

---

## 2. 어디에 살 수 있나 — 세 가지 scope

| Scope | 경로 | 특성 |
|-------|------|------|
| **Project** | `{repo}/.claude/agents/`, `commands/`, `skills/` | repo 에 커밋. 팀 공유. 해당 repo 작업 시에만 활성. **우선순위 최상위** |
| **User** | `~/.claude/agents/`, `commands/`, `skills/` | 로컬 머신 전역. 본인 전용. 모든 프로젝트에서 활성. 중간 우선순위 |
| **Plugin** | `~/.claude/plugins/marketplaces/{plugin}/...` | 마켓플레이스 설치·업데이트. semver 버전 관리. **네임스페이스 prefix** 가짐. 가장 낮은 우선순위 |

### 우선순위는 이렇게 결정된다

이름이 같은 게 여러 scope 에 있을 때:

1. **Project** (`.claude/...`)
2. **User** (`~/.claude/...`)
3. **Plugin** (`~/.claude/plugins/...`)

위에 있는 게 이긴다. 단순한 규칙이다.

---

## 3. 이름이 겹치면 — 핵심 메커니즘

여기가 처음에 가장 헷갈리는 부분이다.

### 플러그인은 자동 prefix 가 붙는다

플러그인의 commands/agents 는 호출 시 **`{plugin-name}:` 네임스페이스 prefix** 가 자동으로 붙는다. 예를 들어 `acme-toolkit` 이라는 플러그인의 `hotfix` 커맨드는 `/acme:hotfix` 로 부른다 (실제 prefix 는 플러그인 manifest 가 결정).

이 한 가지 덕분에:

- 프로젝트의 `/hotfix` 와 플러그인의 `/acme:hotfix` 는 **완전히 다른 이름**이 된다
- 따라서 충돌하지 않고 둘 다 살아있을 수 있다
- 사용자가 어느 쪽을 부르고 싶은지 prefix 유무로 명시적으로 선택

### 호출 예시

| 입력 | 실행되는 것 |
|------|-------------|
| `/hotfix` | 프로젝트의 `.claude/commands/hotfix.md` (project scope) |
| `/acme:hotfix` | 플러그인의 `commands/hotfix.md` (plugin scope) |
| `Task(subagent_type: "figma-dev")` | 프로젝트의 `.claude/agents/figma-dev.md` (project 우선) |
| `Task(subagent_type: "acme:figma-dev")` | 플러그인의 `agents/figma-dev.md` (명시 호출) |

같은 이름이어도 **접두사로 구분**되므로 충돌은 표면적이다. 프로젝트가 플러그인을 override 할 수도 있고(prefix 없이 호출), 둘 다 살려서 따로 부를 수도 있다(prefix 사용).

---

## 4. 의사결정 가이드 — 어디에 둘까

세 가지 자리 중 어디에 둘지 고민될 때의 기준이다.

### Project (`.claude/`) 에 두는 게 맞는 것

- 그 repo 만의 특화 규칙 (예: 특정 백엔드의 권한 DSL, OpenAPI 동기화 스크립트)
- 플러그인 동작을 **override** 해야 하는 경우 (예: 일반 `local-server` 위에 그 repo 의 포트 매핑을 덮어쓰기)
- repo 에 커밋해서 **팀원과 공유** 해야 하는 워크플로우

### User (`~/.claude/`) 에 두는 게 맞는 것

- 본인 전용 단축어 — 여러 프로젝트에서 쓰고 싶은 개인 워크플로우
- 실험적 슬래시 커맨드 — repo 를 더럽히지 않고 시험
- 다만 실제로 가장 적게 쓰이는 자리이기도 하다. 처음에는 user scope 가 비어 있는 채로 시작하는 사람이 많다

### Plugin 에 두는 게 맞는 것

- 여러 repo 가 공통으로 쓸 베이스 도구 — 한 곳에서 관리하고 모든 프로젝트에 배포
- 버전 관리가 필요한 워크플로우 — semver + 마켓플레이스 업데이트 사이클
- 일반화 가능 — placeholder(`{API_PATH}` 등) 로 추상화 가능한 절차

### 같은 도구가 양쪽에 있을 때

예를 들어 `kotlin-dev` 같은 백엔드 에이전트가 플러그인에도 있고 프로젝트에도 있는 경우.

- 플러그인 버전: 일반화된 Kotlin/Spring 작업 패턴
- 프로젝트 버전: 그 repo 의 권한 DSL, 마이그레이션 규칙 등 특화 사항 추가

이러면 **프로젝트가 자연스럽게 override** 되어 그 repo 작업 시엔 특화 버전이 활성된다. 다른 repo 로 가면 자동으로 플러그인의 일반 버전이 적용된다. **자리 자체가 정책**이 되는 셈이다.

---

## 5. 실전 케이스 — Project override 의 가치

플러그인 버전과 프로젝트 버전이 공존하는 패턴을 좀 더 풀어 보자.

가령 `browser-qa` 라는 Playwright 기반 QA 에이전트가 있다고 하자.

- **플러그인 버전 (120 줄 정도)**: 일반화된 Playwright 워크플로우. 어떤 프로젝트에서도 쓸 수 있는 베이스
- **프로젝트 버전 (300 줄 정도)**: 그 repo 의 도메인 (로그인 흐름, 권한 매트릭스, 데이터 시드) 위에서 동작하는 확장

이 둘이 같은 이름으로 양쪽에 살아 있어도 문제가 없다. 사용자가 그 프로젝트에서 `Task(subagent_type: "browser-qa")` 를 부르면 자동으로 프로젝트 버전이 응답한다. 다른 프로젝트에 가면 그 자리가 비어 있으니 자연스럽게 플러그인 버전이 응답한다.

**팀이 보기에 가장 좋은 점**: 누구도 "어느 걸 쓸지" 고민하지 않는다. 자리가 답을 안다.

---

## 6. 흔히 겪는 함정

### "왜 내 커맨드가 안 불려요?"

대부분의 경우 같은 이름의 user 또는 project scope 가 위에 있다. 우선순위 사다리를 확인하자.

### 플러그인 버전을 명시적으로 부르고 싶을 때

`prefix:` 를 붙여서 호출하면 우선순위를 우회할 수 있다. 예: `/acme:hotfix`, `Task(subagent_type: "acme:figma-dev")`.

### 실험은 user scope, 정착은 project scope

새 워크플로우를 만들 때 처음부터 repo 에 커밋하면 동료가 미완성을 보게 된다. user scope (`~/.claude/`) 에서 시험하고, 자리 잡으면 project 또는 plugin 으로 옮기는 게 부드럽다.

### Skill 과 Command 의 경계

단일 마크다운으로 끝나면 Command, 보조 파일·체크리스트·템플릿이 같이 필요하면 Skill. 처음엔 Command 로 시작했다가 부속이 늘어나면 Skill 로 승격하는 패턴이 자연스럽다.

---

## 7. 정리

| 측면 | Agent | Slash Command | Skill |
|------|-------|---------------|-------|
| 호출 주체 | 다른 에이전트 (`Task`) | 사용자 (`/`) | 사용자 또는 자동 |
| 실행 컨텍스트 | 격리 sub-context | 메인 대화 | 메인 대화 + skill 폴더 |
| 파일 형태 | 단일 md | 단일 md | 폴더 + 부속 |

| Scope | 자리 | 우선순위 | 적합한 경우 |
|-------|------|----------|------------|
| Project | `{repo}/.claude/` | 최상위 | 그 repo 특화·팀 공유·override |
| User | `~/.claude/` | 중간 | 개인 전용·실험 |
| Plugin | 마켓플레이스 | 기본 | 여러 repo 공통·버전 관리 |

> Claude Code 의 확장 시스템은 **9 칸짜리 매트릭스 + 자동 prefix 라는 규칙 하나**로 거의 모든 충돌을 해결한다.
> 그래서 처음 보면 복잡해 보이지만, 자리가 답을 정해 주는 구조라 손에 익으면 단순해진다.
> 새 도구를 추가할 때마다 "이건 어느 자리가 맞나" 한 번씩 멈춰서 정하기만 하면 된다.
