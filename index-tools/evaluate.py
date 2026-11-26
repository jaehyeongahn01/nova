#!/usr/bin/env python3
"""검색 정확도 측정: 평가셋 질의로 recall@k 를 한국어/영어 각각 집계.

정답 판정: top-k 결과 중 하나라도 title에 expect 키워드가 들어가면 '맞음'.
"""
from __future__ import annotations

import json
from pathlib import Path

from retriever import Retriever

HERE = Path(__file__).resolve().parent


def hit_rank(results, expect) -> int | None:
    """정답 키워드가 처음 나타난 순위(1-based). 없으면 None."""
    exp = [e.lower() for e in expect]
    for i, r in enumerate(results, 1):
        t = r["title"].lower()
        if any(e in t for e in exp):
            return i
    return None


def main() -> None:
    r = Retriever(str(HERE / "bm25_index.pkl"))
    queries = json.load(open(HERE / "eval_queries.json", encoding="utf-8"))
    K = 5
    for mode in ("ko", "en"):
        hits5 = hits1 = 0
        print(f"\n{'='*72}\n[{mode.upper()} 질의]  recall@{K}\n{'='*72}")
        for q in queries:
            res = r.search(q[mode], k=K)
            rank = hit_rank(res, q["expect"])
            top = res[0]["title"][:40] if res else "(없음)"
            mark = f"✓ #{rank}" if rank else "✗   "
            if rank:
                hits5 += 1
                if rank == 1:
                    hits1 += 1
            print(f"  {mark}  {q[mode][:34]:34s} | 1위: {top}")
        n = len(queries)
        print(f"\n  recall@{K} = {hits5}/{n} = {hits5/n*100:.0f}%   "
              f"(1위 적중 = {hits1}/{n} = {hits1/n*100:.0f}%)")


if __name__ == "__main__":
    main()
