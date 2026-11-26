"""로컬 디버깅용: 공개 샘플을 돌리면서 턴별 질문/진찰/응답을 실시간 출력한다.

제출물(run.py)은 전혀 수정하지 않는다. 대신 client의 say/exam/chat/diagnose를
얇게 감싸(wrap) 호출될 때마다 화면에 찍는다. 서버 동작은 원래 sample.py와 동일하다.

사용:
    python sample_verbose.py --list
    python sample_verbose.py --case <UUID>
환경변수: NOVA_API_BASE, NOVA_DEV_KEY, (검색용) NOVA_GUIDELINES_DIR
"""
import argparse
import os
import sys
import time

from nova_sdk import Client
from run import prepare, consult


def _short(text, n=200):
    text = str(text).replace("\n", " ")
    return text if len(text) <= n else text[:n] + "…"


class VerboseClient:
    """실제 Client를 감싸 say/exam/chat/diagnose를 가로채 로그를 찍는 프록시."""

    def __init__(self, inner):
        self._inner = inner
        self._turn = 0
        self._chat_calls = 0
        self._t0 = time.time()

    # consult()가 쓰는 메서드만 가로채고 나머지는 그대로 위임한다.
    def __getattr__(self, name):
        return getattr(self._inner, name)

    def _elapsed(self):
        return f"{time.time() - self._t0:5.1f}s"

    def session(self):
        s = self._inner.session()
        init = s.get("initial", {})
        print("─" * 70, flush=True)
        print(f"[시작정보] {_short(init.get('opening', ''))}", flush=True)
        print(f"[활력징후] {_short(init.get('vital_signs', ''))}", flush=True)
        print(f"[남은턴] {s.get('turns_remaining')}", flush=True)
        print("─" * 70, flush=True)
        return s

    def say(self, content, **kw):
        self._turn += 1
        print(f"\n[{self._elapsed()} 턴{self._turn}] 👨‍⚕️ SAY: {content}", flush=True)
        reply = self._inner.say(content, **kw)
        print(f"             🧑 환자: {_short(reply.get('content', ''))}"
              f"   (남은턴 {reply.get('turns_remaining')})", flush=True)
        return reply

    def exam(self, content, **kw):
        self._turn += 1
        print(f"\n[{self._elapsed()} 턴{self._turn}] 👨‍⚕️ EXAM: {content}", flush=True)
        reply = self._inner.exam(content, **kw)
        print(f"             🔎 소견: {_short(reply.get('result', ''))}"
              f"   (남은턴 {reply.get('turns_remaining')})", flush=True)
        return reply

    def chat(self, messages, **kw):
        self._chat_calls += 1
        # 매 호출을 다 찍으면 시끄러우니 호출 수만 가볍게 표시(10회마다).
        if self._chat_calls % 10 == 0:
            print(f"             · (Doctor 모델 호출 {self._chat_calls}회째…)", flush=True)
        return self._inner.chat(messages, **kw)

    def diagnose(self, *, note, diagnosis, **kw):
        print("\n" + "═" * 70, flush=True)
        print(f"[진단 제출]  주진단: {diagnosis}", flush=True)
        print(f"[Doctor 호출 총 {self._chat_calls}회 · 진료시간 {self._elapsed()}]", flush=True)
        print("─ S·O·A·P 기록 ─", flush=True)
        for sec in ("S", "O", "A", "P"):
            for field, val in (note.get(sec) or {}).items():
                val = str(val).strip()
                if val:
                    print(f"  [{sec}.{field}] {_short(val, 400)}", flush=True)
        print("═" * 70, flush=True)
        return self._inner.diagnose(note=note, diagnosis=diagnosis, **kw)


def main():
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--case", help="Published sample case ID (see --list)")
    group.add_argument("--list", action="store_true", help="List the published sample cases and their IDs")
    args = parser.parse_args()

    client = Client(token=os.environ["NOVA_DEV_KEY"], sample=True)
    if args.list:
        for case in client._request("GET", "/v1/sample/cases")["cases"]:
            print(case["case_id"], case["initial"]["opening"][:60])
        return

    model = prepare()
    client.create_sample(args.case)
    verbose = VerboseClient(client)
    result = consult(verbose, model)
    print("\n[서버 응답]", _short(result, 300), flush=True)


if __name__ == "__main__":
    main()
