#!/usr/bin/env python3
"""chunks.jsonl -> 질병(문서)별 보기 쉬운 정리본.

출력
- disease_catalog.csv   : 엑셀로 바로 열기. 문서 1행 = 질병/주제 하나.
    컬럼: 제목, 출처, 언어, 섹션수, 역할(dx/hx/tx/edu 유무), 섹션목록, 파일
- disease_catalog.json  : 같은 내용의 JSON(프로그램용).
"""
from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHUNKS = HERE / "chunks.jsonl"


def main() -> None:
    # 문서(파일) 단위로 섹션을 모은다
    docs: dict[str, dict] = {}
    sections_by_doc: dict[str, list] = defaultdict(list)
    with CHUNKS.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            key = r["file"]
            if key not in docs:
                docs[key] = {"title": r["title"], "source": r["source"],
                             "lang": r["lang"], "file": r["file"]}
            sections_by_doc[key].append((r["section"], r["role"]))

    rows = []
    for key, d in docs.items():
        secs = sections_by_doc[key]
        roles = sorted({role for _, role in secs})
        rows.append({
            "제목": d["title"],
            "출처": d["source"],
            "언어": "한국어" if d["lang"] == "ko" else "영어",
            "섹션수": len(secs),
            "진단(dx)": "O" if "dx" in roles else "",
            "병력증상(hx)": "O" if "hx" in roles else "",
            "치료(tx)": "O" if "tx" in roles else "",
            "교육(edu)": "O" if "edu" in roles else "",
            "섹션목록": " | ".join(s for s, _ in secs),
            "파일": d["file"],
        })
    # 제목순 정렬(한국어 먼저 보기 좋게 언어/제목)
    rows.sort(key=lambda x: (x["언어"], x["제목"]))

    csv_path = HERE / "disease_catalog.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:  # utf-8-sig: 엑셀 한글 깨짐 방지
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    json_path = HERE / "disease_catalog.json"
    json_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"문서(질병/주제) {len(rows):,}건 -> {csv_path.name}, {json_path.name}")
    print(f"  한국어 {sum(1 for r in rows if r['언어']=='한국어'):,} · "
          f"영어 {sum(1 for r in rows if r['언어']=='영어'):,}")


if __name__ == "__main__":
    main()
