# N.O.V.A. 2026 Doctor Agent

N.O.V.A. 2026 대회에서 진료 에이전트를 개발한 코드입니다. 환자와 대화(SAY)하며 문진, 검사, 진단을 진행하는 에이전트이고, 진료지침을 검색(RAG)해 근거로 씁니다.

## 구성
- `agent/`: 최종 제출본(v32). `run.py`가 에이전트 본체이고 `nova_sdk.py`는 대회 SDK입니다.
- `index-tools/`: 진료지침 코퍼스를 청크로 나누고 BM25 인덱스와 SOAP 요약 인덱스를 만드는 스크립트, 검색기(`retriever.py`)와 평가 스크립트
- `docs/`: 개발 기획안, 제출 이력 화면

## 실행
API 키는 코드에 없고 환경변수로 받습니다.
```bash
export NOVA_DEV_KEY=...   # 샘플 검증용
python agent/sample.py
python agent/run_all_cases.py
```

## 올리지 않은 것
진료지침 원문 코퍼스와 생성된 인덱스 파일은 라이선스(재배포 제한)와 용량 때문에 제외했습니다. `index-tools`의 스크립트로 다시 만들 수 있습니다.
