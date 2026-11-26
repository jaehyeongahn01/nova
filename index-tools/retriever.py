#!/usr/bin/env python3
"""런타임 검색기: bm25_index.pkl을 로드해 질의 -> top-k 임상 섹션.

진료 코드(run.py)에서:
    from retriever import Retriever
    r = Retriever("bm25_index.pkl")
    for hit in r.search("우하복부 통증 발열 식욕부진", k=5, role="dx"):
        print(hit["title"], hit["section"], hit["score"])
표준 라이브러리만. 본문 텍스트는 인덱스에 없으므로, 필요하면 hit["file"]로 원문에서 섹션을 읽는다.
"""
from __future__ import annotations

import math
import pickle
import re
import unicodedata

EN_WORD = re.compile(r"[a-z0-9]+")
HANGUL = re.compile(r"[가-힣]+")


def tokenize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text).lower()
    toks: list[str] = []
    toks += EN_WORD.findall(text)
    for run in HANGUL.findall(text):
        if len(run) <= 3:
            toks.append(run)
        else:
            toks += [run[i:i + 2] for i in range(len(run) - 1)]
            toks += [run[i:i + 3] for i in range(len(run) - 2)]
    return toks


class Retriever:
    def __init__(self, index_path: str):
        with open(index_path, "rb") as fh:
            idx = pickle.load(fh)
        self.meta = idx["meta"]
        self.tfs = idx["tfs"]
        self.dls = idx["dls"]
        self.idf = idx["idf"]
        self.avgdl = idx["avgdl"]
        self.k1 = idx["k1"]
        self.b = idx["b"]

    def search(self, query: str, k: int = 5, role: str | None = None,
               lang: str | None = None):
        q = [t for t in tokenize(query) if t in self.idf]
        if not q:
            return []
        scores: list[tuple[float, int]] = []
        for i, tf in enumerate(self.tfs):
            if role and self.meta[i]["role"] != role:
                continue
            if lang and self.meta[i]["lang"] != lang:
                continue
            dl = self.dls[i]
            denom_base = self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            s = 0.0
            for t in q:
                f = tf.get(t)
                if f:
                    s += self.idf[t] * (f * (self.k1 + 1)) / (f + denom_base)
            if s > 0:
                scores.append((s, i))
        scores.sort(reverse=True)
        out = []
        for s, i in scores[:k]:
            m = self.meta[i]
            out.append({"score": round(s, 3), "id": m["id"], "title": m["title"],
                        "section": m["section"], "role": m["role"],
                        "source": m["source"], "file": m["file"]})
        return out


if __name__ == "__main__":
    import sys
    r = Retriever(str(__import__("pathlib").Path(__file__).parent / "bm25_index.pkl"))
    q = " ".join(sys.argv[1:]) or "right lower quadrant pain fever anorexia"
    for h in r.search(q, k=8):
        print(f'{h["score"]:7.2f}  [{h["role"]}] {h["title"][:55]:55s} | {h["section"]}')
