#!/usr/bin/env python3
"""검색 정확도 측정 v2: top-5/7/10 비교 + 대회 샘플 3건(진짜 정답) 포함.

- 20개 모의질의(eval_queries.json): ko/en 각각 recall@5,7,10
- 대회 샘플 3건(eval_samples.json): 한국어 첫마디 / 한국어 증상 / 영어 세 가지 입력으로 각 top-k
"""
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


def recall_at(rank, k):
    return rank is not None and rank <= k


def run_set_20(r):
    queries = json.load(open(HERE / "eval_queries.json", encoding="utf-8"))
    print("="*72)
    print("A. 모의질의 20개 — top-k 별 recall")
    print("="*72)
    for mode in ("ko", "en"):
        ranks = [first_rank(r.search(q[mode], k=max(KS)), q["expect"]) for q in queries]
        line = f"  [{mode.upper()}] "
        for k in KS:
            hit = sum(recall_at(rk, k) for rk in ranks)
            line += f"recall@{k}={hit}/{len(queries)}({hit/len(queries)*100:.0f}%)   "
        print(line)


def run_samples(r):
    samples = json.load(open(HERE / "eval_samples.json", encoding="utf-8"))
    print("\n" + "="*72)
    print("B. 대회 샘플 3건 — 입력 방식별, top-k 별 순위")
    print("="*72)
    for mode, label in (("ko_opening", "한국어 첫마디"), ("ko_symptoms", "한국어 증상요약"), ("en", "영어 의학용어")):
        print(f"\n  ── 입력: {label} ──")
        for s in samples:
            res = r.search(s[mode], k=max(KS))
            rank = first_rank(res, s["expect"])
            top3 = " / ".join(h["title"][:24] for h in res[:3])
            rk = f"#{rank}" if rank else "없음"
            print(f'    {s["case"]} ({s["diagnosis"][:18]:18s}) 정답순위 {rk:>5s} | top3: {top3}')
    # 요약: 입력 방식별 top-k 적중 수(3건 중)
    print("\n  ── 요약 (3건 중 정답을 top-k 안에 찾은 수) ──")
    for mode, label in (("ko_opening", "한국어 첫마디"), ("ko_symptoms", "한국어 증상요약"), ("en", "영어 의학용어")):
        ranks = [first_rank(r.search(s[mode], k=max(KS)), s["expect"]) for s in samples]
        line = f"    {label:12s} "
        for k in KS:
            line += f"@{k}={sum(recall_at(rk,k) for rk in ranks)}/3  "
        print(line)


def main():
    r = Retriever(str(HERE / "bm25_index.pkl"))
    run_set_20(r)
    run_samples(r)


if __name__ == "__main__":
    main()
