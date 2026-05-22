---
title: "[Document AI] LangChain과 LlamaIndex — RAG 보일러플레이트를 묶는 프레임워크 (3/6)"
date: 2026-05-22 12:00:00 +0900
categories: [AI, Document AI]
tags: [langchain, llamaindex, framework, abstraction, boilerplate]
---

> **시리즈**
> (1) [임베딩과 Vector DB — 의미를 좌표로 다루는 법](/posts/doc-ai-part1-embedding-vector-db/)
> (2) [RAG 패턴 — LLM에 외부 지식을 주입하는 표준 방식](/posts/doc-ai-part2-rag-pattern/)
> (3) **LangChain과 LlamaIndex — RAG 보일러플레이트를 묶는 프레임워크** ← 현재 글
> (4) VLM과 HuggingFace — 이미지를 읽는 LLM
> (5) 비정형 문서 파싱 — PDF가 그렇게 어려운 이유
> (6) 전체 아키텍처 — Document AI 백엔드의 4-레이어 구조

지난 편에서 RAG의 6단계를 정리했다. 그걸 매번 직접 짜면 boilerplate가 끝없이 늘어난다. **LangChain**과 **LlamaIndex**는 이 boilerplate를 추상화한 프레임워크다.

---

## 백엔드 관점에서의 비유

| 프레임워크 | 비유 | 포지셔닝 |
|---|---|---|
| **LangChain** | Spring | 거의 모든 걸 다 함, 추상화 많음, 학습곡선 큼 |
| **LlamaIndex** | Spring Data | RAG에 특화, "데이터 인덱싱→검색"에 집중 |

LangChain은 RAG뿐 아니라 Agent, Tool 호출, 메모리, 평가까지 다 들어있는 **풀스택 LLM 프레임워크**다. LlamaIndex는 처음부터 "문서 → 인덱스 → 검색"에 초점을 맞춘 **데이터 중심 프레임워크**다.

둘 다 Python이 주류이고, JavaScript 버전도 있다.

> **Chain**
>
> 여러 LLM 호출과 도구를 **순차적으로 연결한 실행 단위**. "문서 로드 → 청킹 → 임베딩 → 검색 → LLM 호출"처럼 여러 단계를 하나의 호출 가능한 객체로 묶는다.
>
> Spring의 `@Configuration`이 빈들을 묶어 하나의 컴포넌트로 만드는 것과 유사한 추상화다. LangChain의 핵심 abstraction이라 이름이 "Lang**Chain**"이다.
{: .prompt-info }

---

## LangChain이 추상화하는 것

지난 편의 RAG 6단계를 LangChain 코드로 옮기면 이렇게 된다.

```python
# 개념적 예시 (실제 API와 약간 다를 수 있음)
from langchain.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.embeddings import OpenAIEmbeddings
from langchain.vectorstores import Chroma
from langchain.chains import RetrievalQA
from langchain.llms import OpenAI

# 1. 로드
loader = PyPDFLoader("policy.pdf")
docs = loader.load()

# 2. Chunking
splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=100)
chunks = splitter.split_documents(docs)

# 3. 임베딩 + Vector DB 저장
vectorstore = Chroma.from_documents(chunks, OpenAIEmbeddings())

# 4. 검색기
retriever = vectorstore.as_retriever(search_kwargs={"k": 5})

# 5. LLM과 결합
qa = RetrievalQA.from_llm(llm=OpenAI(), retriever=retriever)

# 6. 실행
answer = qa.invoke("환불 가능 기간이 어떻게 되나요?")
```

직접 짜면 200줄이 필요한 작업이 20줄로 줄어든다. **PoC를 빠르게 만들 때**의 가치는 명확하다.

> **Q.** LangChain을 쓰면 무엇을 얻고 무엇을 잃나? 직접 구현과의 트레이드오프는?
>
> **얻는 것은 속도, 잃는 것은 통제권**이다.
>
> 얻는 것:
> - 200줄 → 20줄로 보일러플레이트 압축
> - 표준 인터페이스(`Retriever`, `Chain`, `LLM`) — 컴포넌트 교체가 쉬움
> - PoC를 하루 안에 돌릴 수 있음
>
> 잃는 것:
> - 디버깅 어려움 — 추상화 계층이 깊어 "어디서 깨졌나" 추적이 까다롭다. callback handler를 등록해야 LLM에 들어간 실제 프롬프트가 보임
> - 비용 통제 어려움 — 체인 안에서 LLM이 몇 번 호출되는지 명시적이지 않음. 토큰 사용량 추적에 추가 코드 필요
> - 의존성 비대화 — `pip install langchain` 한 번에 100개 넘는 패키지가 끌려옴
>
> *현실적인 절충안은 단계별 도입이다.* PoC는 LangChain으로 빠르게 만든다 → 프로덕션에 가까워지면 **핵심 로직만 떼어내 직접 구현**한다. LangChain은 "참고 구현"으로 두고, 운영 코드는 가볍게 가져간다.
{: .prompt-tip }

---

## LlamaIndex가 다른 점

같은 작업을 LlamaIndex로 옮기면 더 짧아진다.

```python
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader

docs = SimpleDirectoryReader("./pdfs").load_data()
index = VectorStoreIndex.from_documents(docs)
query_engine = index.as_query_engine()
answer = query_engine.query("환불 가능 기간이 어떻게 되나요?")
```

5줄이다. 차이는 다음과 같다.

- **LangChain**: 모든 단계를 명시적으로 선언. 유연성 ↑, 디버깅 가능성 ↑.
- **LlamaIndex**: 기본값이 잘 잡혀 있어서 명시할 게 적음. 빠르게 시작 ↑.

처음 배운다면 LlamaIndex가 친절하고, 프로덕션으로 갈수록 LangChain의 표현력이 필요해진다.

> **Q.** LangChain과 LlamaIndex를 한 프로젝트에서 같이 쓸 수 있나?
>
> 가능하다. 실제로 둘을 혼합해서 쓰는 패턴이 흔하다.
>
> 둘 다 Python의 표준 자료구조(`dict`, `list`, `str`)를 인터페이스로 쓰기 때문에, LlamaIndex의 인덱스에서 검색한 결과를 LangChain의 체인에 넘기는 식으로 자연스럽게 연결된다. LlamaIndex는 `LlamaIndexRetriever`라는 LangChain 호환 래퍼도 공식 제공한다.
>
> 흔한 조합 패턴:
> - **인덱싱/검색은 LlamaIndex** — 청킹/임베딩/검색 기본값이 잘 잡혀 있음
> - **에이전트와 도구 호출은 LangChain** — 멀티 스텝 워크플로우, 메모리, Tool calling이 강함
>
> *경계는 "데이터 vs 흐름"으로 나누면 명확하다.* 데이터 파이프라인 = LlamaIndex, 실행 흐름 = LangChain. 한쪽만 고르려고 애쓰지 말고 강점이 있는 곳에 각각 쓴다.
{: .prompt-info }

---

## 현실 — 프로덕션에서는 그대로 안 쓴다

면접에서 알아두면 좋은 부분이다. **큰 시스템에선 LangChain/LlamaIndex를 그대로 안 쓰고 직접 짜는 곳이 많다.** 이유는 세 가지다.

### 1. Too magic — 디버깅 어려움

추상화 계층이 너무 깊다. 응답이 이상할 때 "어디서 깨진 건지" 추적이 힘들다. 어떤 프롬프트가 LLM에 들어갔는지, retrieval이 어떤 문서를 골랐는지 — 직접 짜면 print 한 줄이면 보이는 것을, LangChain에서는 callback handler를 등록해야 보인다.

### 2. 비용 통제 어려움

체인 안에서 LLM이 몇 번 호출되는지, 토큰을 얼마나 쓰는지 추적이 까다롭다. 회사 규모가 커지면 토큰 비용이 월 수천만 원까지 가는데, 이걸 LangChain 안에서 통제하기는 쉽지 않다.

### 3. 의존성 비대화

LangChain 하나 설치하면 dependency가 100개 넘게 끌려온다. 컨테이너 빌드 시간이 늘고, 보안 패치 부담도 커진다.

그래서 보통은 **PoC는 LangChain/LlamaIndex로 빠르게 만들고, 프로덕션에선 핵심 로직만 떼어내 직접 구현**하는 패턴을 쓴다.

> **Q.** 프로덕션에서 LangChain의 토큰 비용을 추적/제한하려면 어떻게 해야 하나?
>
> **외부 관측 도구 + 게이트웨이 레이어**가 정석이다. LangChain 내장 기능만으론 부족하다.
>
> 단계별 도구:
> - **Langfuse / LangSmith / Helicone** — 모든 LLM 호출의 프롬프트·응답·토큰·비용을 자동 trace. callback handler 한 줄 추가로 연동
> - **LiteLLM Proxy** — LLM 호출 앞단에 게이트웨이를 두고 사용자별/프로젝트별 토큰 한도, 캐싱, 모델 라우팅을 강제
> - **Redis 캐시** — 같은 질문은 LLM 재호출 없이 답변 반환
>
> 효과는 즉각적이다. Langfuse를 붙이면 **"어떤 사용자가, 어떤 체인에서, 토큰을 얼마나 썼는지"**가 대시보드에 바로 보인다. LiteLLM Proxy로 모델 라우팅을 켜면 쉬운 질문은 Haiku, 어려운 질문만 Sonnet으로 자동 분기돼서 비용이 절반 이하로 떨어지는 사례가 흔하다.
>
> *진짜 가치는 비용이 아니라 가시성이다.* 토큰 사용량이 측정 가능해지면, "어떤 프롬프트가 비싼지 / 어디서 낭비되는지 / 캐시 적중률은 얼마인지" 같은 운영 의사결정이 데이터 기반이 된다.
{: .prompt-tip }

---

## 그래도 알아둬야 하는 이유

직접 구현하더라도 두 가지 이유로 익숙해질 가치가 있다.

- **면접 키워드** — "LangChain/LlamaIndex 써봤어요?"는 거의 모든 AI 백엔드 면접에서 나온다.
- **레퍼런스 구현** — 어떻게 추상화하는지, 어떤 abstraction을 노출하는지 — 직접 짤 때도 좋은 참고가 된다.

> 결국 Spring을 안 쓰더라도 Spring의 IoC/AOP 개념을 알아둬야 하는 것과 같다.

---

## 다음 편

여기까지가 **텍스트 RAG의 전부**다. 다음 편부터는 한 단계 어려운 영역 — **이미지를 읽는 LLM(VLM)** 으로 들어간다.
