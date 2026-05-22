---
title: "[Document AI] VLM과 HuggingFace — 이미지를 읽는 LLM (4/6)"
date: 2026-05-22 13:00:00 +0900
categories: [AI, Document AI]
tags: [vlm, multimodal, huggingface, gpt-4v, claude-vision, qwen-vl, transformers]
---

> **시리즈**
> (1) [임베딩과 Vector DB — 의미를 좌표로 다루는 법](/posts/doc-ai-part1-embedding-vector-db/)
> (2) [RAG 패턴 — LLM에 외부 지식을 주입하는 표준 방식](/posts/doc-ai-part2-rag-pattern/)
> (3) [LangChain과 LlamaIndex — RAG 보일러플레이트를 묶는 프레임워크](/posts/doc-ai-part3-langchain-llamaindex/)
> (4) **VLM과 HuggingFace — 이미지를 읽는 LLM** ← 현재 글
> (5) 비정형 문서 파싱 — PDF가 그렇게 어려운 이유
> (6) 전체 아키텍처 — Document AI 백엔드의 4-레이어 구조

여기까지의 RAG는 **텍스트만** 다뤘다. 하지만 현실의 문서는 표, 차트, 도장, 손글씨가 섞여 있다. 이걸 처리하려면 **VLM(Vision-Language Model)** 이 필요하다.

---

## VLM은 무엇인가

**정의**: 이미지를 입력으로 받아서 **텍스트로 설명/추출**할 수 있는 LLM.

```text
[입력] 송장 PDF 이미지
[프롬프트] "이 송장에서 발주번호, 금액, 날짜를 JSON으로 추출해줘"
[VLM 출력]
{
  "발주번호": "PO-12345",
  "금액": 1500000,
  "날짜": "2026-05-22"
}
```

전통적인 OCR이 "이미지 → 텍스트"만 했다면, VLM은 "이미지 → 의미 있는 구조화된 텍스트"까지 한 번에 한다. **OCR + 이해 + 출력 포맷 변환**이 하나의 모델 호출로 해결된다.

> **Multimodal**
>
> 텍스트·이미지·오디오·비디오 등 **여러 입력 양식(modality)을 동시에 처리**하는 모델 특성. VLM은 텍스트와 이미지 두 modality를 다루므로 멀티모달의 가장 흔한 형태다.
>
> 기존 LLM(텍스트 전용) → VLM(텍스트+이미지) → 옴니모달 모델(텍스트+이미지+오디오+비디오)로 확장되는 흐름이고, 2026년 현재 GPT-4o와 Gemini가 옴니모달의 대표주자다.
{: .prompt-info }

---

## 대표 VLM

| 모델 | 종류 | 특징 |
|---|---|---|
| **GPT-4o** | OpenAI API | 가장 안정적, 한국어 OK |
| **Claude 3.5 Sonnet/Opus** | Anthropic API | 문서/표 이해 강점, 긴 컨텍스트 |
| **Gemini 1.5/2.0** | Google API | 멀티이미지 다수 처리 |
| **Qwen2-VL** | 오픈소스 | 표/차트 강함, 한국어 OK |
| **InternVL** | 오픈소스 | 고해상도 문서, 4K 이미지 처리 |
| **LayoutLMv3** | 오픈소스 | 문서 레이아웃 특화 (위치 정보 포함) |
| **Nougat** (Meta) | 오픈소스 | 논문/수식 특화 |

선택 기준:

- 외부 데이터 송출 가능 → GPT-4o, Claude
- 사내 데이터, 격리 필요 → Qwen2-VL, InternVL (셀프호스팅)
- 문서 양식이 정형적 → LayoutLM (좌표 정보 활용)

> **Q.** 같은 이미지를 GPT-4o와 Claude에 보냈더니 응답이 다르다. 어떤 게 맞는지 어떻게 검증하나?
>
> **평가셋 + 일치율 측정**이 정답이다. 한 번의 비교로 결정하지 않는다.
>
> 절차:
> 1. **라벨링된 평가셋을 만든다** — 도메인 이미지 50~100장 + 사람이 추출한 정답 JSON
> 2. **각 모델에 같은 프롬프트로 돌린다** — 응답을 정답 JSON과 비교 (필드별 정확도)
> 3. **모델별 강점·약점이 나뉜다** — 예: Claude는 표 추출이 정확하지만 손글씨에 약함, GPT-4o는 그 반대
> 4. **앙상블 또는 라우팅** — 표가 많은 문서는 Claude, 손글씨는 GPT-4o로 자동 분기
>
> 단발성 비교는 위험하다. "내가 시도한 이미지 1장에 Claude가 더 좋게 보였다"는 표본 편향이고, 다른 도메인에선 정반대 결과가 나오기 쉽다.
>
> *진짜 가치는 평가셋 자체에 있다.* 일단 평가셋을 만들어두면 모델이 새로 나올 때마다 30분 안에 비교 가능해진다. 자체 평가셋 없이 모델을 고르는 건 "느낌으로 DB 고르는 것"과 같다.
{: .prompt-info }

---

## HuggingFace란

오픈소스 모델을 쓰려면 **HuggingFace**를 안 거치고 갈 수 없다.

한 줄로 요약하면 — **모델의 GitHub + 추론 라이브러리**.

- `huggingface.co/models` — 50만 개 넘는 모델 카탈로그. 누구나 업로드/다운로드 가능.
- `transformers` 라이브러리 — PyTorch 위에서 모델을 5줄로 실행하게 해주는 추상화 계층.

> **transformers 라이브러리**
>
> HuggingFace가 만든 Python 라이브러리. 어떤 종류의 모델이든 `AutoModel.from_pretrained("모델명")` 한 줄로 다운로드하고 실행할 수 있게 해주는 통일 인터페이스다.
>
> PyTorch 위에서 동작하지만, PyTorch의 내부 자료구조(Tensor, nn.Module)를 직접 다루지 않아도 된다. Spring Data가 JDBC 위에서 SQL을 가린 것과 비슷한 추상화 레벨이다.
{: .prompt-info }

백엔드 개발자에게 부담스럽지 않은 영역인 이유는, `pip install transformers` 후 단 몇 줄이면 추론이 시작되기 때문이다.

```python
# 개념적 예시
from transformers import AutoModel, AutoProcessor
from PIL import Image

model = AutoModel.from_pretrained("Qwen/Qwen2-VL-7B-Instruct")
processor = AutoProcessor.from_pretrained("Qwen/Qwen2-VL-7B-Instruct")

image = Image.open("invoice.png")
prompt = "이 송장에서 금액과 날짜를 추출해줘"

inputs = processor(images=image, text=prompt, return_tensors="pt")
output = model.generate(**inputs)
result = processor.decode(output[0])
```

여기서 한 가지 짚어두면 — 이 코드를 짜기 위해 Attention 메커니즘을 이해할 필요는 없다. **Spring Boot 쓴다고 JVM 구조를 알 필요가 없는 것과 같다.**

---

## API 호출 vs 셀프호스팅 — 의사결정 기준

실전에서 VLM을 도입할 때 가장 먼저 마주치는 결정이다.

### API 호출 (GPT-4o, Claude)

장점:

- 추론 인프라(GPU) 신경 안 써도 됨
- 모델 업데이트 자동
- 안정적, 첫 토큰 빠름

단점:

- 데이터가 외부로 나감 (회사 정책에 따라 NG)
- 토큰 단가 ↑ — 대량 처리 시 비용 부담
- 레이트 리밋 — 동시 처리량 제약

### 셀프호스팅 (Qwen2-VL, InternVL)

장점:

- 데이터가 사내에만 있음
- 대량 처리 시 단가 ↓ (GPU 감가상각만)
- 파인튜닝 가능

단점:

- GPU 인프라 필요 (A100/H100급)
- 추론 서빙 시스템(vLLM, TGI) 운영 노하우 필요
- 모델 업그레이드 수동

> **Q.** API에서 셀프호스팅으로 언제 옮길지 어떤 기준으로 정하나?
>
> **월간 토큰 비용이 GPU 임대료의 2~3배**가 되는 지점이 손익분기점이다.
>
> 계산은 단순하다.
> - A100 80GB 한 대 임대료(클라우드): 월 약 200~300만 원
> - GPT-4o 1M 토큰: 약 $5~15 (이미지 1장 = 수백~수천 토큰)
> - 송장 100만 장/월 처리 → 약 1억 토큰 → 월 $500~1500
>
> 이 시점이 되면 **셀프호스팅이 비용 절반 이하**가 된다. 하지만 옮기기 전에 셋을 확인해야 한다.
> 1. **모델 품질이 충분한가** — 평가셋으로 Qwen2-VL vs GPT-4o 정확도 차이가 5%p 이내인지
> 2. **운영 인력이 있는가** — GPU 모니터링, vLLM 튜닝, 모델 업데이트 담당이 필요
> 3. **트래픽이 예측 가능한가** — GPU는 미리 사두는 자산이라 트래픽이 흔들리면 낭비
>
> *대부분의 회사는 영원히 API로 가도 된다.* 셀프호스팅은 트래픽이 정말 클 때만 의미가 있다. PoC 단계나 트래픽이 일정치 않으면 API 유지가 훨씬 합리적이다.
{: .prompt-tip }

> **Q.** VLM 응답을 JSON으로 강제하려면 어떤 방법이 있나? "JSON으로 답해줘"라고 프롬프트에 써도 자꾸 텍스트가 섞여 나온다.
>
> **Structured Output**이나 **Function Calling**을 쓴다. 프롬프트 강제는 불안정하다.
>
> OpenAI, Anthropic, Google 모두 같은 기능을 제공한다 (이름만 다름).
> - OpenAI: `response_format={"type": "json_schema", ...}` — JSON 스키마를 모델 디코딩에 강제
> - Anthropic: `tools` 파라미터로 함수 시그니처 지정 — 모델이 그 형태로만 응답
> - Google: `response_schema` 파라미터
>
> 작동 원리는 같다. **디코딩 단계에서 스키마에 맞지 않는 토큰을 차단**한다. "프롬프트에 부탁"하는 게 아니라 **출력 자체가 강제되는** 방식이라 100% 가까운 정확도가 나온다.
>
> 오픈소스 모델에서는 `outlines`, `guidance`, `jsonformer` 같은 라이브러리가 같은 역할을 한다. 토큰 단위에서 valid한 JSON만 생성되도록 디코더를 제약한다.
>
> *프롬프트로 "JSON 형식으로만 답해줘"를 시도하는 건 첫 단계 정도로만 쓴다.* 운영 환경에선 반드시 구조 강제 기능을 쓴다. 그렇지 않으면 "JSON 앞뒤로 설명 텍스트가 붙는" 흔한 함정에 빠지고, 파싱 에러가 끊이지 않는다.
{: .prompt-info }

---

## 백엔드 개발자가 VLM을 다룰 때 부담스럽지 않은 이유

채용공고에서 "VLM 파인튜닝"이 우대사항으로 나오면 무겁게 느껴진다. 그런데 실제 업무를 풀어보면 다음 정도다.

| 업무 | 부담 정도 |
|---|---|
| API로 VLM 호출해서 응답 받기 | ⭐ (REST API 호출과 동일) |
| 응답 JSON 파싱/검증 | ⭐ (스키마 검증) |
| HuggingFace 모델 다운로드 후 추론 | ⭐⭐ (인프라 약간) |
| 셀프호스팅 vLLM 서빙 | ⭐⭐⭐ (DevOps 영역) |
| LoRA 파인튜닝 | ⭐⭐⭐⭐ (ML 영역, 우대사항) |
| 모델 아키텍처 수정 | ⭐⭐⭐⭐⭐ (석/박사 영역) |

채용공고의 필수 요건은 ⭐⭐ 수준까지다. 우대사항도 ⭐⭐⭐⭐ 정도. **백엔드 개발자가 학습으로 메울 수 있는 범위**다.

---

## 다음 편

VLM은 강력하지만, 입력으로 깔끔한 이미지가 들어와야 효과가 난다. 그런데 현실의 PDF는 그렇게 깔끔하지 않다. 다음 편은 **PDF가 왜 그렇게 어려운지** — 비정형 문서 파싱 영역을 정리한다.
