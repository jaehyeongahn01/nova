#!/usr/bin/env python3
"""희귀질환 검색 테스트. 지정한 인덱스 파일로 recall@5/7/10 + 순위."""
import json, sys
from pathlib import Path
from retriever import Retriever

HERE = Path(__file__).resolve().parent
KS = (5, 7, 10)

def first_rank(res, expect):
    exp=[e.lower() for e in expect]
    for i,h in enumerate(res,1):
        if any(e in h["title"].lower() for e in exp): return i
    return None

def main():
    idx = sys.argv[1] if len(sys.argv)>1 else str(HERE/"bm25_index.pkl")
    r = Retriever(idx)
    data = json.load(open(HERE/"eval_rare.json",encoding="utf-8"))
    ranks=[]
    print(f"[인덱스: {Path(idx).name}]")
    for q in data:
        res=r.search(q["q"], k=max(KS))
        rk=first_rank(res,q["expect"])
        ranks.append(rk)
        top=res[0]["title"][:40] if res else "(없음)"
        print(f"  {('#'+str(rk)) if rk else '없음':>5s}  {q['expect'][0][:24]:24s} | 1위: {top}")
    n=len(data)
    print("  " + "  ".join(f"recall@{k}={sum(1 for x in ranks if x and x<=k)}/{n}" for k in KS))

if __name__=="__main__":
    main()
