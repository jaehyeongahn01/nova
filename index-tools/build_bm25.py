#!/usr/bin/env python3
"""chunks.jsonl -> BM25 역색인 (빌드 2단계, 오프라인). 표준 라이브러리만.

출력 : bm25_index.pkl  — 런타임에서 로드해 search(query)로 top-k 청크 반환.
토크나이즈
- 영어: 소문자, [a-z0-9]+ 단어. 한국어: 2~3글자 음절 n-gram(형태소 분석기 없이도 동작).
- 제목(질환명)은 본문보다 가중치를 크게 둔다(제목 매칭은 강한 신호).
BM25 파라미터는 표준값(k1=1.5, b=0.75).
"""
from __future__ import annotations

import json
import math
import pickle
import re
import sys
import unicodedata
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHUNKS = HERE / "chunks.jsonl"
OUT = HERE / "bm25_index.pkl"

TITLE_REPEAT = 3   # 제목 토큰을 본문에 이만큼 더 섞어 가중(간단한 field boosting)
EN_WORD = re.compile(r"[a-z0-9]+")
HANGUL = re.compile(r"[가-힣]+")


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).lower()
    toks: list[str] = []
    toks += EN_WORD.findall(text)
    # 한국어: 음절 bigram + trigram (부분 매칭에 강함)
    for run in HANGUL.findall(text):
        if len(run) <= 3:
            toks.append(run)
        else:
            toks += [run[i:i + 2] for i in range(len(run) - 1)]
            toks += [run[i:i + 3] for i in range(len(run) - 2)]
    return toks


def main() -> None:
    if not CHUNKS.exists():
        sys.exit("run build_chunks.py first")
    doc_tokens: list[list[str]] = []
    meta: list[dict] = []
    df: dict[str, int] = {}
    with CHUNKS.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            toks = tokenize(r["title"]) * TITLE_REPEAT + tokenize(r["text"])
            doc_tokens.append(toks)
            meta.append({"id": r["id"], "file": r["file"], "source": r["source"],
                         "title": r["title"], "section": r["section"], "role": r["role"],
                         "lang": r["lang"]})
            for t in set(toks):
                df[t] = df.get(t, 0) + 1

    N = len(doc_tokens)
    avgdl = sum(len(t) for t in doc_tokens) / max(N, 1)
    # 각 문서를 term-frequency dict로 압축 저장(공간 절약)
    tfs: list[dict[str, int]] = []
    dls: list[int] = []
    for toks in doc_tokens:
        tf: dict[str, int] = {}
        for t in toks:
            tf[t] = tf.get(t, 0) + 1
        tfs.append(tf)
        dls.append(len(toks))
    idf = {t: math.log(1 + (N - n + 0.5) / (n + 0.5)) for t, n in df.items()}

    index = {"meta": meta, "tfs": tfs, "dls": dls, "idf": idf,
             "avgdl": avgdl, "N": N, "k1": 1.5, "b": 0.75,
             "title_repeat": TITLE_REPEAT}
    with OUT.open("wb") as fh:
        pickle.dump(index, fh, protocol=pickle.HIGHEST_PROTOCOL)
    print(f"docs={N}  vocab={len(idf)}  avgdl={avgdl:.1f}  -> {OUT.name} "
          f"({OUT.stat().st_size/1e6:.1f} MB)")


if __name__ == "__main__":
    main()
