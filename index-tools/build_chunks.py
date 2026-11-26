#!/usr/bin/env python3
"""N.O.V.A. 진료지침 코퍼스 -> 임상 섹션 청크 추출 (빌드 1단계, 오프라인).

입력 : guidelines/ 아래 15,904개 .md (YAML 머리글 + Markdown 본문)
출력 : chunks.jsonl  (청크 1건 = 한 문서의 임상적으로 유용한 섹션 하나)
       build_report.json  (출처별 통계, 버린 섹션 집계 — 품질 점검용)

설계 요지
- 문서 전체가 아니라 '임상 섹션' 단위로 쪼갠다(진단/감별/치료 섹션만).
- 발간사·목차·패널·참고문헌·방법론 같은 노이즈 섹션은 버린다.
- 출처마다 구조가 달라 파싱 전략을 다르게 둔다(StatPearls는 섹션이 표준, 나머지는 보수적).
- 런타임이 아니라 빌드에서만 도는 코드라 표준 라이브러리만 쓴다(의존성 0).
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

GUIDELINES = Path(__file__).resolve().parent.parent / "guidelines"
OUT_CHUNKS = Path(__file__).resolve().parent / "chunks.jsonl"
OUT_REPORT = Path(__file__).resolve().parent / "build_report.json"

# ── 섹션 분류 ────────────────────────────────────────────────────────────────
# 진료 중 Doctor Agent에게 유용한 섹션(제목을 소문자로 정규화해 매칭).
# value = 섹션 역할 태그(검색 라우팅용): dx(진단/감별), hx(병력/진찰), tx(치료/처치), edu(교육/예방)
CLINICAL_SECTIONS_EN = {
    "history and physical": "hx",
    "evaluation": "dx",
    "differential diagnosis": "dx",
    "clinical significance": "dx",
    "treatment / management": "tx",
    "treatment": "tx",
    "management": "tx",
    "technique or treatment": "tx",
    "complications": "tx",
    "indications": "tx",
    "contraindications": "tx",
    "deterrence and patient education": "edu",
    "prognosis": "dx",
    "introduction": "dx",   # StatPearls Introduction엔 정의/핵심 임상상이 있어 약하게 포함
    "pearls and other issues": "dx",
    "recommendation": "tx",
    "recommendation summary": "tx",
    "practice considerations": "tx",
}
# 한국어 문서의 유용 섹션(KR_HealthInfo 등 표준 구조).
CLINICAL_SECTIONS_KO = {
    "개요": "dx",
    "요약문": "dx",
    "정의": "dx",
    "원인": "dx",
    "증상": "hx",
    "진단": "dx",
    "검사 목적": "dx",
    "검사 적응증 및 금기증": "dx",
    "검사 결과 해석": "dx",
    "치료": "tx",
    "치료 및 간호": "tx",
    "경과 및 합병증": "tx",
    "예방 및 관리": "edu",
    "주의사항 및 부작용": "tx",
    "환자 교육": "edu",
}
# 어떤 출처에서도 버리는 노이즈 섹션 제목(정규화 후 부분일치).
NOISE_SECTION_PAT = re.compile(
    r"(enhancing healthcare team|epidemiology|histopathology|pathophysiology|anatomy|"
    r"etiology|mechanism of action|administration|pharmacokinetic|monitoring|toxicity|personnel|"
    r"equipment|preparation|references?|참고문헌|발간사|목차|contents|개발위원|자문위원|패널|panel|"
    r"roster|disclosure|acknowledg|methodology|방법론|search string|evidence table|excluded studies|"
    r"기술적 전문가|technical expert|key informant|preface|abbreviation|약어|서문)",
    re.I,
)

# clean 모드에서 추가로 제외할 '논문 구조' 섹션(진료 지식이 아니라 논문 형식).
PAPER_STRUCT_PAT = re.compile(
    r"^(abstract|methods?|materials and methods|results?|discussion|conclusions?|"
    r"background|introduction to|objectives?|aim|limitations?|funding|conflict|"
    r"author contribution|data availability|supplementary)",
    re.I,
)

MIN_CHARS = 120        # 이보다 짧은 섹션은 신호가 약해 버림
MAX_CHARS = 4000       # 너무 긴 섹션은 앞부분만(런타임 토큰 절약). 빌드 보고에 잘림 표시
HEADER_RE = re.compile(r"^(#{1,3})\s+(.*?)\s*#*\s*$")
YAML_RE = re.compile(r"^---\s*$")


def norm(s: str) -> str:
    """헤더 제목 정규화: 마크다운 강조·mark 태그 제거, 소문자, 공백 축약."""
    s = re.sub(r"</?mark>", "", s)
    s = s.replace("*", "").replace("`", "").strip()
    s = unicodedata.normalize("NFC", s)
    return re.sub(r"\s+", " ", s).strip()


def parse_front_matter(lines: list[str]) -> tuple[dict, int]:
    """맨 위 YAML 머리글을 간단 파싱(표준 구조: key: "value"). 반환 (메타, 본문시작줄)."""
    meta: dict = {}
    if not lines or not YAML_RE.match(lines[0]):
        return meta, 0
    i = 1
    while i < len(lines) and not YAML_RE.match(lines[i]):
        m = re.match(r'^(\w+):\s*"?(.*?)"?\s*$', lines[i])
        if m:
            meta[m.group(1)] = m.group(2)
        i += 1
    return meta, i + 1  # YAML 닫는 '---' 다음 줄


def split_sections(body_lines: list[str]) -> list[tuple[str, str]]:
    """본문을 (헤더제목, 섹션본문) 목록으로. 문서 제목(단일 #)은 섹션으로 치지 않음."""
    sections: list[tuple[str, str]] = []
    cur_title, cur_buf = None, []
    for ln in body_lines:
        m = HEADER_RE.match(ln)
        if m:
            level, title = len(m.group(1)), norm(m.group(2))
            # 새 섹션 시작 — 직전 섹션 저장
            if cur_title is not None:
                sections.append((cur_title, "\n".join(cur_buf).strip()))
            cur_title, cur_buf = title, []
        else:
            if cur_title is not None:
                cur_buf.append(ln)
    if cur_title is not None:
        sections.append((cur_title, "\n".join(cur_buf).strip()))
    return sections


import os
MODE = os.environ.get("INDEX_MODE", "strict")  # strict(채택) | inclusive | clean


def section_role(title: str, lang: str) -> str | None:
    """섹션 제목 -> 역할 태그(dx/hx/tx/edu) 또는 None(버림).

    MODE 환경변수로 정책 전환(세 버전 비교용):
    - strict   : 허용 목록에 있는 섹션만 담는다(초기 버전 재현). 모르는 섹션 버림.
    - inclusive: 노이즈 섹션만 빼고 나머지 다 담는다. 모르는 섹션은 dx.
    - clean    : inclusive + 논문 구조 섹션(abstract/methods/results 등)도 노이즈로 제외.
    """
    t = title.lower()
    if NOISE_SECTION_PAT.search(t):
        return None
    if MODE == "clean" and PAPER_STRUCT_PAT.search(t):
        return None
    table = CLINICAL_SECTIONS_EN if lang != "ko" else CLINICAL_SECTIONS_KO
    if t in table:
        return table[t]
    for key, role in table.items():
        if key in t:
            return role
    if MODE == "strict":
        return None  # 허용 목록에 없으면 버림(초기 버전)
    # inclusive / clean: 역할 추정 후 담는다
    if re.search(r"(treatment|management|therapy|surg|drug|medication|치료|처치|수술|약물|관리)", t):
        return "tx"
    if re.search(r"(education|prevention|patient info|교육|예방|생활)", t):
        return "edu"
    if re.search(r"(history|physical|sign|symptom|병력|증상|진찰)", t):
        return "hx"
    return "dx"


def clean_text(s: str) -> str:
    """본문 정리: mark 태그·과한 마크다운·중복 공백 제거."""
    s = re.sub(r"</?mark>", "", s)
    s = re.sub(r"\[[^\]]*\]\([^)]*\)", lambda m: m.group(0).split("]")[0][1:], s)  # [text](url)->text
    s = re.sub(r"[*_`>#]+", " ", s)
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


def main() -> None:
    files = sorted(GUIDELINES.rglob("*.md"))
    if not files:
        sys.exit(f"no .md under {GUIDELINES}")
    report = {
        "total_files": len(files),
        "by_source": {},          # 출처 -> {files, chunks, no_clinical}
        "kept_roles": {"dx": 0, "hx": 0, "tx": 0, "edu": 0},
        "docs_without_clinical": [],
    }
    n_chunks = 0
    with OUT_CHUNKS.open("w", encoding="utf-8") as out:
        for f in files:
            source = f.parent.name
            rep = report["by_source"].setdefault(source, {"files": 0, "chunks": 0, "no_clinical": 0})
            rep["files"] += 1
            text = f.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            meta, start = parse_front_matter(lines)
            title = norm(meta.get("title", "")) or f.stem
            lang = meta.get("language", "en").strip().lower()
            lang = "ko" if lang in ("ko", "korean", "한국어") else "en"
            sections = split_sections(lines[start:])
            kept_here = 0
            for sec_title, sec_body in sections:
                role = section_role(sec_title, lang)
                if role is None:
                    continue
                body = clean_text(sec_body)
                if len(body) < MIN_CHARS:
                    continue
                truncated = len(body) > MAX_CHARS
                if truncated:
                    body = body[:MAX_CHARS]
                rec = {
                    "id": f"{f.stem}#{kept_here}",
                    "file": str(f.relative_to(GUIDELINES.parent)),
                    "source": source,
                    "title": title,
                    "lang": lang,
                    "section": sec_title,
                    "role": role,
                    "text": body,
                    "truncated": truncated,
                }
                out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_chunks += 1
                kept_here += 1
                rep["chunks"] += 1
                report["kept_roles"][role] += 1
            if kept_here == 0:
                # fallback: 섹션을 하나도 못 담은 문서는 통째로 날리지 말고
                # 제목 + 본문 앞부분을 1청크로 담는다(희귀 질환도 검색에 남기기 위해).
                # strict 모드(초기 버전 재현)에서는 fallback 비활성화.
                whole = clean_text("\n".join(
                    ln for ln in lines[start:] if not HEADER_RE.match(ln)))
                # 노이즈 문서(설문지·목차·명단 등)는 제목으로 걸러 fallback에서도 제외
                title_is_noise = bool(NOISE_SECTION_PAT.search(title.lower()) or re.search(
                    r"(설문지|매뉴얼|길라잡이|목차|발간|위원 명단|roster|disclosure)", title.lower()))
                if MODE != "strict" and len(whole) >= MIN_CHARS and not title_is_noise:
                    rec = {
                        "id": f"{f.stem}#0",
                        "file": str(f.relative_to(GUIDELINES.parent)),
                        "source": source,
                        "title": title,
                        "lang": lang,
                        "section": "(full document)",
                        "role": "dx",
                        "text": whole[:MAX_CHARS],
                        "truncated": len(whole) > MAX_CHARS,
                        "fallback": True,
                    }
                    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    n_chunks += 1
                    rep["chunks"] += 1
                    report["kept_roles"]["dx"] += 1
                    rep.setdefault("fallback", 0)
                    rep["fallback"] += 1
                else:
                    rep["no_clinical"] += 1
                    if len(report["docs_without_clinical"]) < 200:
                        report["docs_without_clinical"].append(str(f.relative_to(GUIDELINES.parent)))
    report["total_chunks"] = n_chunks
    OUT_REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"files={len(files)}  chunks={n_chunks}  -> {OUT_CHUNKS.name}")
    docs_no = sum(v["no_clinical"] for v in report["by_source"].values())
    print(f"docs with 0 clinical sections = {docs_no}")
    print("roles:", report["kept_roles"])
    print("\nby source (files / chunks / no-clinical):")
    for src, v in sorted(report["by_source"].items()):
        print(f"  {src:22s} {v['files']:6d} {v['chunks']:7d} {v['no_clinical']:6d}")


if __name__ == "__main__":
    main()
