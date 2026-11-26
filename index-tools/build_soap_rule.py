#!/usr/bin/env python3
"""진료지침 문서 → SOAP 구조 인덱스 (규칙 기반 발췌, LLM 미사용).

- 섹션 제목을 SOAP 칸에 매핑해 '문서에 있는 내용 그대로' 담는다(지어내기 0).
- 질병 태그(disease) = 문서 title.
- 없는 칸(매핑 섹션이 없음)은 키 자체를 생략한다.
- 두 모드: full(섹션 거의 그대로) / compact(칸당 길이 상한, 49MB 겨냥).

출력: index_soap.jsonl (한 줄 = 한 문서). 선택적으로 .gz 압축.
빌더만으로 재생성 가능(파일 분실 대비). 표준 라이브러리만 사용.
"""
from __future__ import annotations

import argparse
import gzip
import json
import re
import unicodedata
from pathlib import Path

GUID = Path(__file__).resolve().parent.parent / "guidelines"
OUT = Path(__file__).resolve().parent / "index_soap.jsonl"

# ── 섹션 → (SOAP 그룹, 칸) 매핑 ──
# 영어(StatPearls 등) 섹션 제목 소문자 부분일치.
MAP_EN = [
    # 병력+진찰 섹션 → 증상(S.hpi)과 진찰소견(O.exam) 둘 다에 둔다.
    # (증상 정보는 진단에 핵심이라 S를 비워두지 않는다.)
    ("history and physical", ("S", "hpi"), ("O", "exam")),
    ("evaluation", ("P", "tests"),),            # 평가/검사 섹션 → 추가검사 계획 칸 하나로
    ("differential diagnosis", ("A", "differential"),),
    ("treatment / management", ("P", "treatment"),),
    ("treatment", ("P", "treatment"),),
    ("management", ("P", "treatment"),),
    ("technique or treatment", ("P", "treatment"),),
    ("complications", ("P", "disposition"),),
    ("prognosis", ("P", "follow_up"),),
    ("deterrence and patient education", ("P", "education"),),
    ("introduction", ("A", "evidence"),),
    ("clinical significance", ("A", "evidence"),),
    ("pearls and other issues", ("A", "evidence"),),
    ("indications", ("P", "treatment"),),
    ("recommendation", ("P", "treatment"),),
]
# 한국어(KR_HealthInfo 등) 섹션.
MAP_KO = [
    ("증상", ("S", "hpi"),),
    ("개요", ("A", "evidence"),),
    ("요약문", ("A", "evidence"),),
    ("정의", ("A", "evidence"),),
    ("원인", ("A", "evidence"),),
    ("진단 및 검사", ("P", "tests"),),
    ("진단", ("P", "tests"),),
    ("검사", ("P", "tests"),),
    ("증상 및 징후", ("S", "hpi"),),
    ("치료", ("P", "treatment"),),
    ("경과", ("P", "follow_up"),),
    ("합병증", ("P", "disposition"),),
    ("예방", ("P", "education"),),
    ("주의", ("P", "education"),),
]
# 버리는 노이즈 섹션(진료 판단에 불필요).
NOISE = re.compile(
    r"(enhancing healthcare team|epidemiology|histopathology|pathophysiology|anatomy|etiology|"
    r"surgical oncology|postoperative|mechanism|administration|pharmacokinet|monitoring|toxicity|"
    r"references?|참고문헌|발간|목차|contents|위원|panel|roster|disclosure|방법론|methodology|서문|"
    r"abbreviation|약어)", re.I)

ALL_FIELDS = {"S": ["cc", "hpi", "pmh", "fh", "sh", "ros"], "O": ["exam", "tests"],
              "A": ["evidence", "differential"],
              "P": ["tests", "treatment", "disposition", "follow_up", "education"]}

LEN = {"full": 1200, "compact": 400}   # 칸당 글자 상한
HEADER_RE = re.compile(r"^#{1,3}\s+(.*?)\s*#*\s*$")


def norm(s):
    s = re.sub(r"</?mark>", "", s).replace("*", "").replace("`", "")
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", s)).strip()


def clean(s):
    s = re.sub(r"</?mark>", "", s)
    s = re.sub(r"\[[^\]]*\]\([^)]*\)", lambda m: m.group(0).split("]")[0][1:], s)
    s = re.sub(r"[*_`>#]+", " ", s)
    s = re.sub(r"[ \t]+", " ", s)
    return re.sub(r"\n{2,}", " ", s).strip()


# 역학/통계성 문장(진단·치료 가치 낮음). 문장 단위로 걸러낸다.
EPI_PAT = re.compile(
    r"(prevalence|incidence|epidemiolog|million people|per 100,?000|most common\w* \w+ (cancer|disease|cause)|"
    r"affects? (approximately|about|roughly)?\s*\d|accounts? for\b.*%|유병률|발생률|명 이상|가장 흔한)",
    re.I)


def drop_epi_sentences(text: str) -> str:
    """문단에서 역학/통계 문장을 제거(진단·치료 칸에 섞이는 노이즈 감소)."""
    parts = re.split(r"(?<=[.!?。])\s+|(?<=다\.)\s*", text)
    kept = [p for p in parts if p and not EPI_PAT.search(p)]
    out = " ".join(kept).strip()
    # 전부 역학이라 비어버리면 원문 유지(빈 칸 방지)
    return out if len(out) >= 40 else text


def read_doc(path):
    text = path.read_text(encoding="utf-8", errors="replace")
    meta = {}
    m = re.search(r'^title:\s*"?(.*?)"?\s*$', text, re.M)
    meta["title"] = norm(m.group(1)) if m else path.stem
    ml = re.search(r'^language:\s*"?(\w+)"?\s*$', text, re.M)
    meta["lang"] = "ko" if (ml and ml.group(1).startswith("ko")) else "en"
    body = re.sub(r"^---.*?---\s*", "", text, count=1, flags=re.S)
    return meta, body


def split_sections(body):
    secs, title, buf = [], None, []
    for ln in body.splitlines():
        m = HEADER_RE.match(ln)
        if m:
            if title is not None:
                secs.append((title, "\n".join(buf).strip()))
            title, buf = norm(m.group(1)), []
        elif title is not None:
            buf.append(ln)
    if title is not None:
        secs.append((title, "\n".join(buf).strip()))
    return secs


def map_section(title, lang):
    t = title.lower()
    if NOISE.search(t):
        return []
    table = MAP_EN if lang != "ko" else MAP_KO
    for key, *targets in table:
        if key in t:
            return list(targets)
    return []


def build_soap(path, mode):
    meta, body = read_doc(path)
    lang = meta["lang"]
    soap = {}
    for sec_title, sec_body in split_sections(body):
        targets = map_section(sec_title, lang)
        if not targets:
            continue
        txt = clean(sec_body)
        if len(txt) < 40:
            continue
        for group, field in targets:
            # 임상 판단 칸(근거·치료·검사·처치)엔 역학 문장을 걸러 넣는다.
            val = drop_epi_sentences(txt) if field in ("evidence", "treatment", "tests", "disposition") else txt
            val = val[: LEN[mode]]
            if len(val) < 40:
                continue
            # 이미 그 칸에 내용이 있으면 더 긴 쪽 유지(중복 섹션 대비)
            cur = soap.get(group, {}).get(field, "")
            if len(val) > len(cur):
                soap.setdefault(group, {})[field] = val
    # 빈 그룹/칸 정리(없는 칸은 이미 생성 안 됨)
    soap = {g: fs for g, fs in soap.items() if fs}
    return {
        "doc_id": path.stem,
        "disease": meta["title"],
        "disease_norm": meta["title"].lower(),
        "lang": lang,
        "file": "guidelines/" + str(path.relative_to(GUID)),
        "soap": soap,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["full", "compact"], default="compact")
    ap.add_argument("--files", nargs="*", help="특정 .md만(시범)")
    ap.add_argument("--out", default=str(OUT))
    ap.add_argument("--gz", action="store_true", help="gzip 압축 저장")
    ap.add_argument("--preview", action="store_true", help="저장 않고 화면 출력(시범)")
    args = ap.parse_args()

    files = [Path(f).resolve() for f in args.files] if args.files else sorted(GUID.rglob("*.md"))

    recs, empty = [], 0
    for p in files:
        rec = build_soap(p, args.mode)
        if not rec["soap"]:
            empty += 1
            continue
        recs.append(rec)

    if args.preview:
        for r in recs:
            print("=" * 70)
            print(f'{r["disease"]} [{r["lang"]}]  (칸: {sum(len(v) for v in r["soap"].values())}개)')
            print(json.dumps(r["soap"], ensure_ascii=False, indent=1)[:1400])
        return

    out = args.out + (".gz" if args.gz else "")
    opener = (lambda: gzip.open(out, "wt", encoding="utf-8")) if args.gz else (lambda: open(out, "w", encoding="utf-8"))
    with opener() as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    size = Path(out).stat().st_size
    print(f"[{args.mode}{' +gz' if args.gz else ''}] 문서 {len(recs):,}건 (soap 없음 {empty}) → {out}")
    print(f"  크기: {size/1e6:.1f} MB")


if __name__ == "__main__":
    main()
