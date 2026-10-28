#!/usr/bin/env python3
"""카카오톡 오픈채팅 CSV의 "오늘의 백엔드 질문" 게시글을 questions.json 으로 정제하고 조회한다.

사용법:
  extract_questions.py --export [CSV]   # CSV → questions.json 병합 (신규 질문만 추가, id 유지)
  extract_questions.py --list           # 질문 목록 (id, 날짜, 포스트 여부, 질문)
  extract_questions.py --pending        # 아직 포스트하지 않은 질문만
  extract_questions.py --id 9           # 한 건의 전체 내용을 JSON으로 출력
  extract_questions.py --json           # 전체를 JSON 배열로 출력

조회 명령은 questions.json 만 읽는다. 원본 CSV는 --export 때만 필요하다.
--export 에서 CSV를 생략하면 ~/Downloads 의 최신 "KakaoTalk_Chat_하루 백엔드*.csv" 를 쓴다.
포스트 여부는 _posts/_drafts front matter 의 `interview_date: YYYY-MM-DD` 로 판단한다.
"""
import argparse
import csv
import glob
import json
import os
import re
import sys
import unicodedata

HEADERS = ("[오늘의 백엔드 질문]", "## 오늘의 백엔드 질문 ##", "**오늘의 백엔드 질문**")
REPOST_PREFIX = "톡게시판"
FOOTER_MARKERS = ("[인큐 커리어 서비스]", "[인큐커리어", "[홍보")
TAIL_MARKERS = ("꼬리 질문", "꼬리질문")
ANSWER_MARKERS = ("면접에서는 이렇게 답변하면", "이렇게 답변하면 좋습니다")

SKILL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
QUESTIONS_JSON = os.path.join(SKILL_DIR, "questions.json")
BLOG_ROOT = os.path.abspath(os.path.join(SKILL_DIR, "..", "..", ".."))


# ---------------------------------------------------------------- CSV 파싱

def find_default_csv():
    # macOS는 파일명을 NFD로 저장하므로 한글 패턴은 정규화한 뒤 비교한다.
    want = unicodedata.normalize("NFC", "KakaoTalk_Chat_하루 백엔드")
    files = [
        f for f in glob.glob(os.path.expanduser("~/Downloads/KakaoTalk_Chat_*.csv"))
        if unicodedata.normalize("NFC", os.path.basename(f)).startswith(want)
    ]
    if not files:
        sys.exit("CSV를 찾지 못했다: ~/Downloads/KakaoTalk_Chat_하루 백엔드*.csv")
    return max(files, key=os.path.getmtime)


def strip_footer(lines):
    for i, line in enumerate(lines):
        if line.strip().startswith(FOOTER_MARKERS):
            return lines[:i]
    return lines


def question_key(question):
    """어미만 다른 재게시("~막아 주나요?" vs "~막아 주는 걸까요?")를 같은 질문으로 보기 위한 키."""
    k = re.sub(r"(는\s*걸까요|나요|까요|인가요|을까요|요)\s*\?$", "", question)
    return re.sub(r"[\s\W]+", "", k)


def parse_message(msg):
    lines = msg.split("\n")
    header = lines[0].strip()
    body = [l.rstrip() for l in strip_footer(lines[1:])]
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    if not body:
        return None

    # 질문: 앞 3줄 안에서 '?' 또는 '~세요.'로 끝나는 첫 줄.
    # 없으면 설명문으로 시작하는 변형 형식이므로 첫 문장을 주제로 삼고 has_question=False 로 표시한다.
    q_idx, has_question = None, True
    for i, line in enumerate(body[:3]):
        if line.strip().endswith(("?", "세요.")):
            q_idx = i
            break
    if q_idx is None:
        has_question = False
        question = re.split(r"(?<=다\.)\s", body[0].strip(), maxsplit=1)[0]
        rest = body
    else:
        question = body[q_idx].strip()
        rest = body[q_idx + 1:]

    tail_questions, model_answer, explanation = [], [], []
    mode = "explain"
    for line in rest:
        s = line.strip()
        if any(m in s for m in TAIL_MARKERS) and len(s) < 40:
            mode = "tail"
            continue
        if any(m in s for m in ANSWER_MARKERS):
            mode = "answer"
            continue
        if mode == "tail":
            s2 = re.sub(r"^(ㄴ>|[-•]|\d+[.)])\s*", "", s)
            if s2:
                tail_questions.append(s2)
        elif mode == "answer":
            if s:
                model_answer.append(s)
        else:
            explanation.append(line)

    return {
        "header": header,
        "question": question,
        "has_question": has_question,
        "explanation": "\n".join(explanation).strip(),
        "tail_questions": tail_questions,
        "model_answer": " ".join(model_answer).strip(),
    }


def parse_csv(csv_path):
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    out, seen = [], set()
    for r in rows:
        msg = r["Message"].lstrip()
        if msg.startswith(REPOST_PREFIX) or not msg.startswith(HEADERS):
            continue
        parsed = parse_message(msg)
        if not parsed:
            continue
        key = question_key(parsed["question"])
        if key in seen:
            continue
        seen.add(key)
        parsed["key"] = key
        parsed["date"] = r["Date"][:10]
        parsed["posted_by"] = r["User"]
        out.append(parsed)
    return out


# ---------------------------------------------------------------- questions.json

def load_json():
    if not os.path.exists(QUESTIONS_JSON):
        sys.exit(f"{QUESTIONS_JSON} 이 없다. 먼저 --export 를 실행한다.")
    with open(QUESTIONS_JSON, encoding="utf-8") as f:
        return json.load(f)


def save_json(questions):
    with open(QUESTIONS_JSON, "w", encoding="utf-8") as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)
        f.write("\n")


def export(csv_path):
    """CSV의 질문을 questions.json 에 병합한다. 기존 항목의 id는 유지하고 신규만 뒤에 붙인다."""
    existing = []
    if os.path.exists(QUESTIONS_JSON):
        with open(QUESTIONS_JSON, encoding="utf-8") as f:
            existing = json.load(f)
    known = {q["key"] for q in existing}
    next_id = max((q["id"] for q in existing), default=0) + 1

    added = []
    for q in sorted(parse_csv(csv_path), key=lambda q: q["date"]):
        if q["key"] in known:
            continue
        q["id"] = next_id
        next_id += 1
        known.add(q["key"])
        added.append(q)

    merged = existing + added
    save_json(merged)
    print(f"# source: {csv_path}")
    print(f"# {QUESTIONS_JSON}")
    print(f"# total {len(merged)}, added {len(added)}")
    for q in added:
        print(f"{q['id']:>3} + {q['date']}  {q['question'][:90]}")


def posted_dates():
    dates = set()
    for path in glob.glob(os.path.join(BLOG_ROOT, "_posts", "*.md")) + glob.glob(
        os.path.join(BLOG_ROOT, "_drafts", "*.md")
    ):
        with open(path, encoding="utf-8") as f:
            head = f.read(2000)
        for m in re.finditer(r"^interview_date:\s*[\"']?(\d{4}-\d{2}-\d{2})", head, re.M):
            dates.add(m.group(1))
    return dates


# ---------------------------------------------------------------- CLI

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", nargs="?", help="--export 때 읽을 CSV 경로 (기본: ~/Downloads 최신 파일)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--export", action="store_true", help="CSV를 questions.json 에 병합")
    g.add_argument("--list", action="store_true", help="질문 목록 출력")
    g.add_argument("--pending", action="store_true", help="아직 포스트하지 않은 질문만 목록 출력")
    g.add_argument("--id", type=int, help="해당 id 한 건을 JSON으로 출력")
    g.add_argument("--json", action="store_true", help="전체를 JSON 배열로 출력")
    args = ap.parse_args()

    if args.export:
        export(args.csv or find_default_csv())
        return

    questions = load_json()
    done = posted_dates()
    for q in questions:
        q["posted"] = q["date"] in done

    if args.id:
        match = [q for q in questions if q["id"] == args.id]
        if not match:
            sys.exit(f"id {args.id} 없음 (1~{len(questions)})")
        print(json.dumps(match[0], ensure_ascii=False, indent=2))
        return
    if args.json:
        print(json.dumps(questions, ensure_ascii=False, indent=2))
        return

    posted = sum(q["posted"] for q in questions)
    rows = [q for q in questions if not (args.pending and q["posted"])]
    print(f"# {QUESTIONS_JSON}")
    print(f"# total {len(questions)}, posted {posted}, pending {len(questions) - posted}")
    for q in rows:
        mark = "✔" if q["posted"] else " "
        print(f"{q['id']:>3} {mark} {q['date']}  {q['question'][:90]}")


if __name__ == "__main__":
    main()
