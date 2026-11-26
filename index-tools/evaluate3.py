#!/usr/bin/env python3
"""한→영 변환 후 검색 정확도: 대회 샘플 3건, 문진 단계별, top-5/7/10 순위."""
from __future__ import annotations

import json
from pathlib import Path

from retriever import Retriever

HERE = Path(__file__).resolve().parent
KS = (5, 7, 10)


def first_rank(results, expect):
    exp = [e.lower() for e in expect]
    for i, r in enumerate(results, 1):
        if any(e in r["title"].lower() for e in exp):
            return i
    return None


def main():
    r = Retriever(str(HERE / "bm25_index.pkl"))
    data = json.load(open(HERE / "eval_translated.json", encoding="utf-8"))
    stage_names = list(data[0]["stages"].keys())

    for s in data:
        print("=" * 74)
        print(f'{s["case"]}  정답: {s["diagnosis"]}')
        print("=" * 74)
        for stage in stage_names:
            q = s["stages"][stage]
            res = r.search(q, k=max(KS))
            rank = first_rank(res, s["expect"])
            rk = f"정답 #{rank}" if rank else "정답 없음"
            top3 = " / ".join(h["title"][:26] for h in res[:3])
            print(f'  [{stage}] {rk}')
            print(f'      질의: {q[:70]}')
            print(f'      top3: {top3}')
        print()

    # 단계별 요약 (3건 중 top-k 적중)
    print("=" * 74)
    print("요약: 각 문진 단계에서 정답을 top-k 안에 찾은 수 (3건 중)")
    print("=" * 74)
    for stage in stage_names:
        ranks = [first_rank(r.search(s["stages"][stage], k=max(KS)), s["expect"]) for s in data]
        line = f"  {stage:16s} "
        for k in KS:
            line += f"@{k}={sum(1 for rk in ranks if rk and rk <= k)}/3  "
        line += f"| 순위들: {ranks}"
        print(line)


if __name__ == "__main__":
    main()
