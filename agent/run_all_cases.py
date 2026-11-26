"""로컬 디버깅용: 공개 샘플 '여러 개'를 한 번에 순서대로 돌리고, 턴별 대화를
화면에 실시간 출력하면서 동시에 결과 파일(results_all.txt)로도 저장한다.

제출물(run.py)은 전혀 수정하지 않는다. client의 say/exam/chat/diagnose를
얇게 감싸(wrap) 호출될 때마다 로그를 찍는다. 서버 동작은 sample.py와 동일하다.

증례 간 상태 공유 금지(대회 규칙) → 케이스마다 prepare()와 세션을 새로 만든다.

사용:
    python run_all_cases.py                 # 공개 샘플 '전부' 순서대로
    python run_all_cases.py --list          # 공개 샘플 ID 목록만
    python run_all_cases.py --case A --case B   # 지정한 UUID만(여러 번 가능)
환경변수: NOVA_API_BASE, NOVA_DEV_KEY, (검색용) NOVA_GUIDELINES_DIR
"""
import argparse
import os
import sys
import time

from nova_sdk import Client
from run import prepare, consult

OUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results_all.txt")


def _short(text, n=200):
    text = str(text).replace("\n", " ")
    return text if len(text) <= n else text[:n] + "…"


class _Tee:
    """화면과 파일에 동시에 쓴다."""
    def __init__(self, *streams):
        self._streams = streams

    def write(self, s):
        for st in self._streams:
            st.write(s)
            st.flush()

    def flush(self):
        for st in self._streams:
            st.flush()


class VerboseClient:
    """실제 Client를 감싸 say/exam/chat/diagnose를 가로채 로그를 찍는 프록시."""

    def __init__(self, inner, out):
        self._inner = inner
        self._out = out
        self._turn = 0
        self._chat_calls = 0
        self._t0 = time.time()

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def _p(self, *args):
        print(*args, file=self._out, flush=True)

    def _elapsed(self):
        return f"{time.time() - self._t0:5.1f}s"

    def session(self):
        s = self._inner.session()
        init = s.get("initial", {})
        self._p("─" * 70)
        self._p(f"[시작정보] {_short(init.get('opening', ''))}")
        self._p(f"[활력징후] {_short(init.get('vital_signs', ''))}")
        self._p(f"[남은턴] {s.get('turns_remaining')}")
        self._p("─" * 70)
        return s

    def say(self, content, **kw):
        self._turn += 1
        self._p(f"\n[{self._elapsed()} 턴{self._turn}] SAY: {content}")
        reply = self._inner.say(content, **kw)
        self._p(f"             환자: {_short(reply.get('content', ''))}"
                f"   (남은턴 {reply.get('turns_remaining')})")
        return reply

    def exam(self, content, **kw):
        self._turn += 1
        self._p(f"\n[{self._elapsed()} 턴{self._turn}] EXAM: {content}")
        reply = self._inner.exam(content, **kw)
        self._p(f"             소견: {_short(reply.get('result', ''))}"
                f"   (남은턴 {reply.get('turns_remaining')})")
        return reply

    def chat(self, messages, **kw):
        self._chat_calls += 1
        if self._chat_calls % 10 == 0:
            self._p(f"             · (Doctor 모델 호출 {self._chat_calls}회째…)")
        return self._inner.chat(messages, **kw)

    def diagnose(self, *, note, diagnosis, **kw):
        self._p("\n" + "═" * 70)
        self._p(f"[진단 제출]  주진단: {diagnosis}")
        self._p(f"[Doctor 호출 총 {self._chat_calls}회 · 진료시간 {self._elapsed()}]")
        self._p("─ S·O·A·P 기록 ─")
        for sec in ("S", "O", "A", "P"):
            for field, val in (note.get(sec) or {}).items():
                val = str(val).strip()
                if val:
                    self._p(f"  [{sec}.{field}] {_short(val, 400)}")
        self._p("═" * 70)
        return self._inner.diagnose(note=note, diagnosis=diagnosis, **kw)


def _list_cases(dev_client):
    return dev_client._request("GET", "/v1/sample/cases")["cases"]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--list", action="store_true", help="공개 샘플 ID 목록만 출력")
    parser.add_argument("--case", action="append", default=[],
                        help="돌릴 UUID(여러 번 지정 가능). 생략하면 공개 샘플 전부.")
    args = parser.parse_args()

    base_client = Client(token=os.environ["NOVA_DEV_KEY"], sample=True)

    cases = _list_cases(base_client)
    if args.list:
        for c in cases:
            print(c["case_id"], c["initial"]["opening"][:60])
        return

    # 돌릴 대상 결정: --case 지정이 있으면 그것만, 없으면 전부.
    if args.case:
        target_ids = args.case
    else:
        target_ids = [c["case_id"] for c in cases]

    logfile = open(OUT_PATH, "w", encoding="utf-8")
    out = _Tee(sys.stdout, logfile)

    print(f"\n총 {len(target_ids)}개 케이스를 순서대로 실행합니다. 결과 저장: {OUT_PATH}\n",
          file=out, flush=True)

    summary = []
    for i, case_id in enumerate(target_ids, 1):
        print("\n" + "#" * 70, file=out, flush=True)
        print(f"# 케이스 {i}/{len(target_ids)} — {case_id}", file=out, flush=True)
        print("#" * 70, file=out, flush=True)
        try:
            # 증례마다 새 prepare()와 새 세션(상태 공유 금지).
            model = prepare()
            client = Client(token=os.environ["NOVA_DEV_KEY"], sample=True)
            client.create_sample(case_id)
            verbose = VerboseClient(client, out)
            result = consult(verbose, model)
            print("\n[서버 응답]", _short(result, 300), file=out, flush=True)
            summary.append((case_id, verbose._turn, verbose._chat_calls, "OK"))
        except Exception as exc:
            print(f"\n[오류] 케이스 {case_id} 실행 중 예외: {type(exc).__name__}: {exc}",
                  file=out, flush=True)
            summary.append((case_id, "-", "-", f"ERROR: {type(exc).__name__}"))

    # 전체 요약표.
    print("\n" + "=" * 70, file=out, flush=True)
    print("[전체 요약]  케이스 / 턴수 / Doctor호출 / 상태", file=out, flush=True)
    for cid, turns, calls, status in summary:
        print(f"  {cid}  턴 {turns}  호출 {calls}  {status}", file=out, flush=True)
    print("=" * 70, file=out, flush=True)
    logfile.close()


if __name__ == "__main__":
    main()
