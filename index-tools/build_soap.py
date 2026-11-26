#!/usr/bin/env python3
"""진료지침 문서 → SOAP 구조 요약 인덱스 (LLM 기반, 오프라인 빌드).

각 문서를 LLM에게 읽혀 S·O·A·P 칸으로 재구성한다.
- 질병 태그(disease) = 문서 title.
- 없는 칸/빈 칸은 '키 자체를 생략'한다(빈 문자열로 남기지 않음).
- 문서에 실제로 있는 내용만 쓰도록 프롬프트로 강제(지어내기 금지).
- 두 모드: full(풍부) / compact(49MB 겨냥, 짧게).

모델 연결: OpenAI 호환 /v1/chat/completions 면 무엇이든 가능.
  로컬 Ollama(gpt-oss:20b) 또는 대회 개발용 모델(gpt-6.1-sol/luna) 등.
  환경변수:
    SOAP_LLM_URL   (기본 http://localhost:11434/v1)
    SOAP_LLM_MODEL (기본 gpt-oss:20b)
    SOAP_LLM_KEY   (없으면 미사용)
사용:
  python build_soap.py --sample 5                 # 임의 5개 시범(두 모드 각각)
  python build_soap.py --files a.md b.md          # 특정 파일만
  python build_soap.py --mode compact --out X.jsonl  # 전체 빌드(오래 걸림)
표준 라이브러리 + urllib만 사용.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

GUID = Path(__file__).resolve().parent.parent / "guidelines"
LLM_URL = os.environ.get("SOAP_LLM_URL", "http://localhost:11434/v1").rstrip("/")
LLM_MODEL = os.environ.get("SOAP_LLM_MODEL", "gpt-oss:20b")
LLM_KEY = os.environ.get("SOAP_LLM_KEY", "")

# SOAP 칸 정의(제출 기록과 동일 구조).
SOAP_SPEC = """S (주관적):
  cc  주호소: 대표 증상/주소
  hpi 현병력: 전형적 발병·경과·양상·악화완화·동반증상
  pmh 과거력·약물·알레르기: 관련 기저질환·약물 위험요인
  fh  가족력: 질병과 관련된 가족력
  sh  사회력: 흡연·음주·직업 등 관련 위험요인
  ros 계통문진: 물어봐야 할 (+)/(-) 동반 증상 체크 항목
O (객관적):
  exam  진찰 소견: 이 질병에서 기대되는 신체진찰 소견
  tests 검사 소견: (예선 무관하면 생략 가능)
A (평가):
  evidence     근거: 이 진단을 뒷받침하는 핵심 소견
  differential 감별진단: 반드시 배제할 유사 질환들
P (계획):
  tests       추가 검사: 확진에 필요한 검사와 이유
  treatment   치료: 약물·처치
  disposition 처치 결정: 입원/외래/의뢰 기준
  follow_up   추적: 재진·경고 증상
  education   환자 교육: 환자에게 설명할 내용"""

ALL_FIELDS = {
    "S": ["cc", "hpi", "pmh", "fh", "sh", "ros"],
    "O": ["exam", "tests"],
    "A": ["evidence", "differential"],
    "P": ["tests", "treatment", "disposition", "follow_up", "education"],
}

LEN_HINT = {
    "full": "각 칸은 핵심을 담되 2~5문장. 임상적으로 유용한 세부(수치·소견명)를 포함.",
    "compact": "각 칸은 1~2문장 또는 핵심 키워드 나열로 아주 짧게. 꼭 필요한 것만.",
}


def build_prompt(mode: str) -> str:
    return f"""너는 임상 지침 문서를 초진기록(SOAP) 틀로 요약하는 보조자다.
아래 '문서'의 내용만 근거로, 이 질병을 진료할 때 참고할 SOAP 요약을 작성하라.

[절대 규칙]
- 문서에 실제로 적힌 내용만 사용한다. 문서에 없는 사실·수치·약물명을 지어내지 않는다.
- 문서에서 해당 칸에 쓸 내용을 찾을 수 없으면, 그 칸(키)을 결과에서 '아예 생략'한다. 빈 문자열로 남기지 않는다.
- 환자 개별 수치가 아니라 '이 질병의 전형적 소견/권고'를 적는다(일반 지식화).
- 영어 문서면 영어로, 한국어 문서면 한국어로 작성한다.
- {LEN_HINT[mode]}

[SOAP 칸 설명]
{SOAP_SPEC}

[출력 형식] JSON 하나만 출력. 내용이 있는 칸만 포함(없는 칸 키는 생략):
{{"S":{{"cc":"...","hpi":"...","ros":"..."}},"O":{{"exam":"..."}},"A":{{"evidence":"...","differential":"..."}},"P":{{"treatment":"...","follow_up":"..."}}}}"""


def read_doc(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    meta = {}
    m = re.search(r'^title:\s*"?(.*?)"?\s*$', text, re.M)
    meta["title"] = (m.group(1) if m else path.stem).strip()
    ml = re.search(r'^language:\s*"?(\w+)"?\s*$', text, re.M)
    meta["lang"] = "ko" if (ml and ml.group(1).startswith("ko")) else "en"
    # YAML 머리글 제거 후 본문
    body = re.sub(r"^---.*?---\s*", "", text, count=1, flags=re.S)
    return meta, body.strip()


def call_llm(system: str, user: str, max_tokens=1500) -> str:
    body = {
        "model": LLM_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": max_tokens,
    }
    data = json.dumps(body).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if LLM_KEY:
        headers["Authorization"] = "Bearer " + LLM_KEY
    req = urllib.request.Request(LLM_URL + "/chat/completions", data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=300) as resp:
        payload = json.loads(resp.read())
    return payload["choices"][0]["message"]["content"] or ""


def parse_json(text):
    dec = json.JSONDecoder()
    for m in re.finditer(r"\{", text or ""):
        try:
            v, _ = dec.raw_decode(text, m.start())
        except ValueError:
            continue
        if isinstance(v, dict):
            return v
    return None


def clean_soap(obj):
    """빈 칸/빈 그룹 제거 + 허용 키만 유지(없는 칸은 키 자체 생략)."""
    out = {}
    if not isinstance(obj, dict):
        return out
    for group, fields in ALL_FIELDS.items():
        g = obj.get(group)
        if not isinstance(g, dict):
            continue
        kept = {}
        for f in fields:
            v = g.get(f)
            if isinstance(v, list):
                v = ", ".join(map(str, v))
            if isinstance(v, str) and v.strip():
                kept[f] = v.strip()
        if kept:
            out[group] = kept
    return out


def summarize_doc(path: Path, mode: str):
    meta, body = read_doc(path)
    body = body[:12000]  # 입력 상한(토큰 보호)
    system = build_prompt(mode)
    raw = call_llm(system, f"문서 제목: {meta['title']}\n\n문서:\n{body}")
    soap = clean_soap(parse_json(raw))
    return {
        "doc_id": path.stem,
        "disease": meta["title"],
        "disease_norm": re.sub(r"\s+", " ", meta["title"].lower()).strip(),
        "lang": meta["lang"],
        "file": "guidelines/" + str(path.relative_to(GUID)),
        "soap": soap,
    }, raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, help="임의 N개 시범(두 모드 각각 생성·비교)")
    ap.add_argument("--files", nargs="*", help="특정 .md 경로들")
    ap.add_argument("--mode", choices=["full", "compact"], default="full")
    ap.add_argument("--out", help="전체 빌드 결과 jsonl 경로")
    args = ap.parse_args()

    # 대상 파일 결정
    if args.files:
        files = [Path(f) for f in args.files]
    elif args.sample:
        allmd = sorted(GUID.rglob("US_StatPearls/*.md"))
        files = allmd[:: max(1, len(allmd) // args.sample)][: args.sample]
    else:
        ap.error("--sample 또는 --files 필요")

    modes = ["full", "compact"] if args.sample and not args.out else [args.mode]

    for mode in modes:
        print(f"\n{'='*70}\n[MODE={mode}]  모델={LLM_MODEL} @ {LLM_URL}\n{'='*70}")
        recs, times = [], []
        for p in files:
            t0 = time.time()
            try:
                rec, raw = summarize_doc(p, mode)
            except Exception as exc:
                print(f"  ! {p.name}: {exc}")
                continue
            dt = time.time() - t0
            times.append(dt)
            recs.append(rec)
            line = json.dumps(rec, ensure_ascii=False)
            print(f"\n  ── {rec['disease']} ({dt:.1f}s, 출력 {len(line)}바이트) ──")
            print("  " + json.dumps(rec["soap"], ensure_ascii=False)[:700])
        if times:
            avg = sum(times) / len(times)
            total = 14679
            print(f"\n  [{mode}] 평균 {avg:.1f}s/문서, 출력 평균 {sum(len(json.dumps(r,ensure_ascii=False)) for r in recs)//len(recs)}바이트")
            print(f"  → 전체 {total:,}개 추정: {avg*total/3600:.1f}시간, "
                  f"비압축 ≈ {sum(len(json.dumps(r,ensure_ascii=False)) for r in recs)//len(recs)*total/1e6:.0f}MB")
        if args.out:
            with open(args.out, "a", encoding="utf-8") as fh:
                for r in recs:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            print(f"  저장: {args.out} (+{len(recs)})")


if __name__ == "__main__":
    main()
