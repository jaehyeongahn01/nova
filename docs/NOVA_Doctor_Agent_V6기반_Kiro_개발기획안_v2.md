# N.O.V.A. 2026 Doctor Agent 개발 기획안 v2
## V6 기반 점진적 리팩터링 / Kiro 구현용 개발 명세서

---

# 0. 가장 중요한 전제

이번 개발은 **새로운 `run.py`를 처음부터 다시 만드는 프로젝트가 아니다.**

기준 베이스라인은 현재 성능이 가장 안정적이었던 **V6 코드**다.

기준 제출:

```text
submission_v6_20261014_124601.zip
```

제출 화면 기준:

```text
v6-gate-aci-dedup
샘플 검증: 66.8

동일 계열 V6 리더보드:
261014_v6
리더보드: 58.6
```

따라서 개발 원칙은 다음과 같다.

> **V6에서 이미 잘 동작하는 부분은 최대한 유지하고, 새로운 기능을 한 번에 갈아엎지 않고 단계적으로 보조 레이어로 추가한다.**

> **새 기능이 안정적으로 기존 기능을 대체하는 것이 확인되기 전까지 기존 로직을 삭제하지 않는다.**

---

# 1. 프로젝트 목표

현재 V6를 안정적인 진료 엔진으로 유지하면서 아래 기능을 순차적으로 추가한다.

```text
V6
↓
Structured Patient State
↓
Medical Retrieval
↓
Candidate Tracker
↓
Phase Controller
↓
Action Candidate Selection
↓
Intermediate Review
↓
Final Audit
```

최종 목표:

> 환자의 정보를 구조화해 지속적으로 기록하고, 현재 환자 상태를 의료 지식 DB와 비교하여 감별진단 후보를 갱신하며, GPT-OSS가 후보 질환을 가장 잘 구분할 질문과 진찰 후보를 생성하도록 한 뒤, 단계별 검토를 거쳐 충분한 근거가 확보되면 진단과 SOAP를 제출하는 적응형 Doctor Agent를 구현한다.

---

# 2. 왜 V6를 기준으로 하는가

현재 제출 결과를 보면:

```text
V6 gate-aci-dedup     66.8
V7 rag                64.0
V8 information_gain   46.0~46.1
V8 hybrid fixed       45.2
```

즉 V6 이후의 아이디어가 모두 나쁜 것은 아니지만, 실제 구현 결과에서는 새로운 로직을 한꺼번에 추가했을 때 기존 성능이 손상된 정황이 있다.

따라서 이번 개발에서는 다음 방식을 따른다.

```text
기존 V6 기능
= 검증된 기본 동작

새 기획안 기능
= V6 위에 추가되는 보조 기능
```

새 기능은 반드시 하나씩 추가하고 샘플 검증한다.

---

# 3. 최우선 개발 원칙

## 3.1 KEEP

V6에서 아래 기능은 우선 보존한다.

```text
N.O.V.A SDK 호출 방식
client.say()
client.exam()
client.chat()
client.diagnose()

NovaError / retry 처리
시간 제한 처리
턴 관리
SAY / EXAM validation
기존 dedup
기존 gate
기존 fallback
최종 SOAP submission 형식
JSON parsing
```

---

## 3.2 MODIFY

아래 부분은 V6의 동작을 유지하되 점진적으로 수정한다.

```text
현재 상황을 GPT에게 전달하는 context 구성
다음 질문/EXAM 선택 방식
질환 후보 관리
진료 종료 판단
SOAP 생성 입력
```

---

## 3.3 ADD

새롭게 추가할 핵심 기능:

```text
Structured Patient State
Evidence Ledger
BM25 Retrieval
Candidate Tracker
Phase Controller
Action Candidate Generator
Action Selector
Intermediate Review
Final Audit
```

---

## 3.4 DELETE LAST

다음 기능들은 새 시스템이 안정적으로 대체된 것이 확인된 뒤에만 제거한다.

```text
V6 기존 question selection logic
V6 기존 gate 일부
V6 기존 단순 next-step reasoning
V6 기존 context 조립 방식
```

원칙:

> **기존 로직을 먼저 삭제한 뒤 새 로직을 넣지 않는다.**

---

# 4. 전체 아키텍처

최종 구조:

```text
                       ┌──────────────────┐
                       │ index_soap.jsonl │
                       └────────┬─────────┘
                                ↓
                       BM25 Retrieval
                                ↓
                            Medical KB
                                │
                                │
환자 서버 ──→ V6 run.py ──→ Patient State
   ↑              │               │
   │              │               ├─ Evidence Ledger
   │              │               ├─ Asked Concepts
   │              │               └─ Candidate Tracker
   │              │
   │              ↓
   │           GPT-OSS
   │              ↓
   │      행동 후보 / 감별진단
   │              ↓
   │        Action Selector
   │              ↓
   └──── SAY / EXAM
```

---

# 5. 핵심 설계 원칙

## 단계는 정해두되 질문은 환자 상태에 따라 변한다

Part 1~8의 **목표는 고정**한다.

하지만 실제 질문 순서를 고정하지 않는다.

예:

```text
Part 1 = 초기 환자 파악
```

이라고 해서 모든 환자에게 같은 질문 5개를 순서대로 묻지 않는다.

```text
흉통 환자
→ 호흡곤란 / 방사통 / 실신 / 발한 우선

복통 환자
→ 위치 / 이동 / 오심 / 설사 / 배뇨증상 우선
```

따라서:

```text
현재 Phase
↓
Patient State
↓
미확인 중요 정보
↓
GPT가 질문/EXAM 후보 생성
↓
run.py가 후보 필터링 및 선택
↓
SAY / EXAM 실행
```

---

# 6. Structured Patient State

V6의 transcript는 유지한다.

단, transcript 옆에 구조화된 Patient State를 추가한다.

예:

```json
{
  "phase": 4,
  "turn": 12,

  "patient": {
    "age": 25,
    "sex": "male",
    "chief_complaint": "abdominal pain"
  },

  "vitals": {
    "raw": {},
    "abnormal": ["mild tachycardia"]
  },

  "positive": [
    "RLQ pain",
    "nausea"
  ],

  "negative": [
    "diarrhea",
    "hematuria"
  ],

  "unknown": [
    "pain migration",
    "anorexia"
  ],

  "history": {
    "onset": "12 hours ago",
    "pmh": [],
    "medications": [],
    "allergy": null,
    "family_history": [],
    "social_history": []
  },

  "exam": [],

  "asked_concepts": [
    "pain_location",
    "onset",
    "diarrhea",
    "hematuria"
  ],

  "candidates": [],

  "critical_missing": []
}
```

중요:

```text
Positive
Negative
Unknown
```

은 반드시 구분한다.

`hematuria (-)`와 `hematuria를 아직 묻지 않음`은 절대 같은 상태로 처리하지 않는다.

---

# 7. Evidence Ledger

Patient State는 reasoning용이고, Evidence Ledger는 SOAP grounding용이다.

예:

```json
{
  "opening": [
    {
      "fact": "chief complaint: abdominal pain",
      "source": "opening"
    }
  ],

  "say": [
    {
      "turn": 1,
      "question": "어디가 가장 아픈가요?",
      "answer": "오른쪽 아랫배요.",
      "normalized_fact": "RLQ pain (+)"
    }
  ],

  "exam": [
    {
      "turn": 8,
      "request": "우하복부 압통 확인합니다",
      "result": "압통 있음",
      "normalized_fact": "RLQ tenderness (+)"
    }
  ]
}
```

규칙:

```text
Medical DB의 일반 지식
≠ 환자에게 실제 확인한 사실
```

최종 SOAP에는 Evidence Ledger에 존재하는 내용만 사용한다.

---

# 8. Phase 구조

최종 목표는 Part 1~8이다.

```text
Part 1  Initial Assessment
Part 2  Subjective Completion
Part 3  Initial Medical Retrieval
Part 4  Broad Diagnostic Exploration
Part 5  Differential Discrimination
Part 6  Intermediate Review
Part 7  Top-3 Verification
Part 8  Final Audit
```

단, 첫 구현부터 복잡한 8단계 state machine으로 만들 필요는 없다.

초기 MVP에서는 아래처럼 4개 상위 Phase로 묶어도 된다.

```text
Phase A
= Part 1 + Part 2

Phase B
= Part 3 + Part 4

Phase C
= Part 5 + Part 6 + Part 7

Phase D
= Part 8
```

V6에 안정적으로 붙은 뒤 세부 Part로 분리한다.

---

# 9. Part 1 — Initial Assessment

목표:

> 환자가 왜 왔는지 기본 임상 상황을 빠르게 파악한다.

권장:

```text
최소 3 patient turns
최대 5 patient turns
```

기본 수집 목표:

```text
Chief complaint
Onset
Location / Character / Severity
주요 동반 증상
Opening vital abnormality 관련 정보
```

예:

```text
Opening:
25M
"배가 아파요."
HR 112
BP 118/72
```

GPT에게 현재 상태에서 Part 1 질문 후보를 생성하도록 한다.

출력 예:

```json
{
  "priority_questions": [
    {
      "concept": "pain_location",
      "question": "어디가 가장 아픈가요?",
      "reason": "복통 위치 확인"
    },
    {
      "concept": "onset",
      "question": "언제부터 아팠나요?",
      "reason": "급성/만성 구분"
    }
  ]
}
```

---

# 10. Opening Vital Sign 처리

V6의 기존 logic이 있다면 우선 유지한다.

추가로 간단한 Rule을 사용할 수 있다.

```text
HR ↑
→ fever / pain / dehydration / bleeding / palpitation 관련 확인

BP ↓
→ dizziness / syncope / bleeding / dehydration

Temp ↑
→ 감염성 증상 관련 질문

RR ↑
→ dyspnea / chest pain / respiratory symptom
```

활력징후 하나만으로 질환을 단정하지 않는다.

---

# 11. Part 1 종료 후 Patient State 정리

Part 1 종료 후 GPT가 지금까지의 정보를 JSON으로 정리한다.

```text
Opening
+
Part 1 transcript
↓
GPT
↓
Patient State JSON
```

예:

```json
{
  "positive": [
    "RLQ abdominal pain",
    "nausea"
  ],

  "negative": [],

  "unknown": [
    "pain migration",
    "diarrhea",
    "hematuria",
    "fever"
  ]
}
```

---

# 12. Part 2 — Subjective Completion

목표:

> SOAP의 S를 무조건 전부 채우는 것이 아니라, 현재 진단에 중요한 Subjective 정보만 추가한다.

대상:

```text
HPI
PMH
Medication
Allergy
FH
SH
ROS
```

모든 환자에게 기계적으로 가족력/흡연/음주/직업을 묻지 않는다.

GPT에게:

```text
현재 Patient State에서
진단적으로 중요하지만 아직 확인하지 않은
Subjective 정보는 무엇인가?
```

를 요청한다.

없으면 Part 2는 바로 종료할 수 있다.

---

# 13. Part 3 — Initial Medical Retrieval

여기서 `index_soap.jsonl`을 본격 사용한다.

중요:

```text
index_soap.jsonl 전체
→ GPT에게 전달하지 않음
```

검색 구조:

```text
Patient State
↓
Search Query
↓
bm25_soap_index.pkl
↓
Top 10~20 record
↓
index_soap.jsonl
↓
관련 의료 지식 추출
↓
중복/저관련성 제거
↓
Top 3~7 knowledge
↓
GPT
```

---

# 14. `index_soap.jsonl`의 역할

이 파일은 실제 환자의 SOAP가 아니다.

역할:

```text
Disease Knowledge Base
```

즉:

```text
"이 질환에서는 어떤 증상/진찰/진단/치료 특징이 있는가?"
```

를 검색하기 위한 참고 지식이다.

환자 SOAP에 직접 복사하지 않는다.

---

# 15. `bm25_soap_index.pkl`

역할:

```text
index_soap.jsonl에서
현재 환자와 관련된 record를 빠르게 찾는 검색 색인
```

권장 구조:

```python
{
    "version": "soap_v1",
    "bm25": bm25_object,
    "doc_ids": [...],
    "record_count": ...
}
```

중요:

```text
BM25 결과
= 관련 문서 후보

BM25 결과
≠ 질환 진단 결과
```

---

# 16. Retrieval Query

Patient State를 기반으로 clinical search query를 만든다.

예:

```text
25 male
acute right lower quadrant abdominal pain
nausea
no diarrhea
```

다만 negative 정보를 BM25에 어떤 방식으로 넣을지는 실험한다.

초기에는 positive finding 중심 query가 더 안전할 수 있다.

예:

```text
right lower quadrant abdominal pain nausea acute onset
```

---

# 17. Part 3 — Candidate Disease 생성

검색 문서와 Patient State를 GPT에게 제공한다.

목표:

```text
관련 문서 제목을 그대로 질병 후보로 쓰지 않는다.
```

GPT가 실제 감별진단을 생성한다.

예:

```json
{
  "candidates": [
    {
      "disease": "Acute appendicitis",
      "reason": "RLQ pain and nausea"
    },
    {
      "disease": "Ureteral stone",
      "reason": "acute abdominal pain"
    },
    {
      "disease": "Gastroenteritis",
      "reason": "abdominal pain with nausea"
    }
  ]
}
```

초기 후보 목표:

```text
최대 5~7개
```

---

# 18. Candidate Tracker

각 질환마다 Evidence Card를 관리한다.

```json
{
  "disease": "Acute appendicitis",

  "support": [
    "RLQ pain",
    "nausea"
  ],

  "against": [],

  "unknown": [
    "pain migration",
    "anorexia",
    "RLQ tenderness"
  ],

  "safety_priority": "medium"
}
```

초기에는 확률값을 만들지 않는다.

```text
Appendicitis = 82%
```

와 같은 숫자는 사용하지 않는다.

대신:

```text
support
against
unknown
```

으로 관리한다.

---

# 19. Part 4 — Broad Diagnostic Exploration

반복:

```text
SAY / EXAM
↓
환자 결과
↓
Transcript 업데이트
↓
Patient State 업데이트
↓
Evidence Ledger 업데이트
↓
BM25 검색
↓
Candidate Tracker 업데이트
↓
다음 행동
```

---

# 20. Retrieval 빈도

## BM25

Local CPU 검색이므로 매 턴 돌려도 된다.

## GPT 전체 재평가

매 턴 하지 않는다.

다음 조건에서 호출한다.

```text
3 patient turns 경과
OR
새로운 Red Flag 등장
OR
강한 특징적 finding 등장
OR
Top candidate가 크게 변함
OR
후보가 지나치게 많음
OR
중요한 EXAM 결과가 새로 나옴
```

---

# 21. 질문 전략

초반:

```text
syndrome 파악
```

후반:

```text
disease discrimination
```

예:

```text
Appendicitis
Ureteral stone
Gastroenteritis
```

모두 abdominal pain이 있으므로:

```text
"복통 있나요?"
```

는 정보가치가 낮다.

대신:

```text
Pain migration?
Hematuria?
Diarrhea?
```

같은 차별 질문을 우선한다.

---

# 22. Part 5 — Differential Discrimination

후보가 약 3~5개로 줄어들면 진입한다.

GPT 입력:

```text
Patient State
+
Candidate Tracker
+
관련 Knowledge
+
asked_concepts
```

GPT 출력:

```json
{
  "actions": [
    {
      "type": "SAY",
      "concept": "pain_migration",
      "content": "통증 위치가 이동했나요?",
      "targets": ["acute appendicitis"],
      "reason": "appendicitis 감별"
    },

    {
      "type": "SAY",
      "concept": "hematuria",
      "content": "소변에 피가 보였나요?",
      "targets": ["ureteral stone"],
      "reason": "요로결석 감별"
    },

    {
      "type": "EXAM",
      "concept": "rlq_tenderness",
      "content": "우하복부 압통 확인합니다",
      "targets": ["acute appendicitis"],
      "reason": "충수염 진찰"
    }
  ]
}
```

---

# 23. Action Selector

중요:

**V8의 Information Gain 구조를 바로 메인 제어기로 사용하지 않는다.**

현재 성능 결과상 V8 information gain 계열의 성능이 V6보다 크게 낮았으므로, 처음에는 단순하고 해석 가능한 Rule 기반으로 시작한다.

초기 Filter:

```text
이미 물은 concept → 제외
30자 초과 → 제외
EXAM 형식 부적절 → 제외
현재 후보와 무관함 → 감점
Red Flag 확인 → 가점
Top 후보를 구분 → 가점
현재 Phase 목표와 부합 → 가점
```

개념적 score:

```text
Action Score
=
Discrimination Value
+
Safety Value
+
Phase Relevance
-
Duplicate Penalty
-
Turn Cost
```

Information Gain은 이후 보조 점수로 추가한다.

---

# 24. V8 Information Gain 활용 원칙

V8 코드를 그대로 가져오지 않는다.

가능하면 나중에:

```text
Action Selector의 보조 score
```

로만 활용한다.

예:

```text
Final Score
=
Rule-based Score
+
0.2 * InformationGainScore
```

같은 방식으로 실험 가능하다.

초기 버전에서는 Information Gain을 사용하지 않아도 된다.

---

# 25. Part 6 — Intermediate Review

환자 턴을 사용하지 않는다.

`client.chat()`을 이용한 내부 reasoning 단계다.

GPT 검토:

```text
1. 현재 가장 가능성 높은 질환은?
2. 놓친 위험 질환은?
3. 현재 evidence의 모순은?
4. 아직 꼭 필요한 정보는?
5. 현재 질문 전략이 편향되어 있는가?
```

출력:

```json
{
  "ranking": [
    "Acute appendicitis",
    "Ureteral stone",
    "Gastroenteritis"
  ],

  "missed_dangerous_diagnoses": [],

  "contradictions": [],

  "critical_missing": [
    "RLQ tenderness"
  ]
}
```

정보가 부족하면 Part 5 또는 Part 4로 복귀한다.

---

# 26. Part 7 — Top-3 Verification

후보를 Top 3 정도로 좁힌다.

각 후보:

```text
Support
Against
Unknown
```

을 유지한다.

예:

```text
#1 Appendicitis

Support
+ RLQ pain
+ nausea
+ pain migration

Against
- fever 없음

Unknown
? RLQ tenderness
```

여기서 Top 1을 지지하는 질문만 하지 않는다.

반드시 경쟁 후보를 지지/반박할 evidence도 확인한다.

목적:

```text
confirmation bias 방지
```

---

# 27. Part 8 — Final Audit

진단 직전 마지막 내부 검토.

GPT 출력 예:

```json
{
  "top_diagnosis": "Acute appendicitis",

  "support": [
    "migratory RLQ pain",
    "nausea",
    "RLQ tenderness"
  ],

  "against": [],

  "dangerous_alternatives_checked": true,

  "critical_missing": [],

  "contradictions": [],

  "ready_to_diagnose": true
}
```

GPT의 `ready_to_diagnose=true`만으로 종료하지 않는다.

V6 gate + 새 Rule을 함께 사용한다.

---

# 28. Phase 전환 조건

GPT 임의 확률에 의존하지 않는다.

예:

```text
"Appendicitis confidence = 91%"
```

를 기준으로 이동하지 않는다.

대신 측정 가능한 조건을 사용한다.

| 단계 | 이동 조건 |
|---|---|
| Part 1 | 최소 3턴 + 핵심 initial info 확보, 최대 5턴 |
| Part 2 | relevant subjective 정보 확보 또는 추가 가치 낮음 |
| Part 3 | 첫 Retrieval 및 candidate 생성 |
| Part 4 | Candidate가 약 3~5개로 안정 |
| Part 5 | 후보 간 차별 evidence가 충분히 생김 |
| Part 6 | 중간 검토 완료 |
| Part 7 | Top 1 안정 + 주요 경쟁 질환 검증 |
| Part 8 | critical missing 없음 + safety check 완료 |

필요 시 이전 단계로 복귀 가능.

---

# 29. 기존 V6 Gate 활용

V6에 이미 gate가 있다면 삭제하지 않는다.

초기에는 새 Phase Controller와 병렬 사용한다.

예:

```text
기존 V6 gate
+
new phase readiness
+
safety condition
```

을 모두 이용해 종료 판단.

새 gate가 충분히 안정적이라고 확인되면 기존 gate의 일부를 정리한다.

---

# 30. GPT Prompt 역할 분리

기존 V6 prompt는 바로 삭제하지 않는다.

새 prompt는 보조 기능으로 추가한다.

추천:

```text
PATIENT_STATE_PROMPT
INITIAL_QUESTION_PROMPT
MISSING_INFO_PROMPT
DIFFERENTIAL_PROMPT
ACTION_GENERATION_PROMPT
REVIEW_PROMPT
FINAL_AUDIT_PROMPT
RECORD_PROMPT
```

가능하면 JSON 형식을 강제한다.

---

# 31. GPT 응답 처리

GPT가 반환한 JSON text를 기존 V6의 JSON parsing 방식으로 Python dict로 변환한다.

흐름:

```text
run.py
↓
GPT prompt
↓
JSON response text
↓
parse_json()
↓
Python dict
↓
Patient State / Candidate / Action update
```

---

# 32. `prepare()` 변경

V6의 `prepare()` 구조를 유지하면서 Knowledge assets를 추가한다.

개념:

```python
def prepare():

    records = load_jsonl(
        "knowledge/index_soap.jsonl"
    )

    bm25_data = load_pickle(
        "knowledge/bm25_soap_index.pkl"
    )

    return {
        "records": records,
        "bm25": bm25_data
    }
```

주의:

기존 V6에서 prepare에 다른 기능이 있으면 삭제하지 않고 함께 유지한다.

---

# 33. `consult()` 변경

V6 `consult()`를 완전히 새로 쓰지 않는다.

기존 loop에 기능을 삽입한다.

개념:

```python
def consult(client, model):

    session = client.session()

    # V6 기존 초기화 유지
    transcript = []

    # 신규
    state = initialize_patient_state(session)
    evidence = initialize_evidence_ledger(session)

    while not v6_or_new_stop_condition(...):

        # 신규 phase
        phase = determine_phase(state)

        # 필요 시 retrieval
        if should_retrieve(state):
            retrieved = retrieve_medical_knowledge(...)

        # 기존 V6 next action logic 유지 가능
        # 단, 일정 단계부터 candidate actions를 보조로 사용

        actions = generate_candidate_actions(...)

        action = select_action_with_v6_fallback(
            actions,
            state,
            existing_v6_logic
        )

        reply = execute_action(client, action)

        # 기존 transcript 유지
        update_transcript(...)

        # 신규 state/evidence
        update_patient_state(...)
        update_evidence_ledger(...)
        update_candidates(...)

    audit = final_audit(...)

    note, diagnosis = write_record_grounded(...)

    return client.diagnose(
        note=note,
        diagnosis=diagnosis
    )
```

핵심:

```text
V6 loop
+
new state/retrieval/reasoning
```

형태로 시작한다.

---

# 34. Fallback 전략

새 로직 실패 시 V6가 동작할 수 있도록 한다.

예:

```text
Patient State parsing 실패
→ 기존 transcript 기반 V6 logic 사용

BM25 loading 실패
→ Retrieval 없이 V6 계속

Candidate GPT JSON 실패
→ 기존 V6 next-step logic 사용

Action 후보 없음
→ 기존 V6 next-step logic 사용

Final Audit 실패
→ V6 write_record 사용
```

이 구조는 초기 개발에서 매우 중요하다.

---

# 35. Turn Budget

초기 target:

```text
18~25 patient actions
```

Hard limit 예시:

```text
30~35
```

단 V6의 기존 turn 설정이 있다면 먼저 유지하고 샘플 결과를 본 뒤 조정한다.

---

# 36. 개발 버전 전략

이 프로젝트는 반드시 버전별로 기능 하나씩 추가한다.

## V6.1 — State

추가:

```text
Structured Patient State
Asked Concepts
Positive / Negative / Unknown
```

나머지는 최대한 V6 유지.

평가 목표:

```text
V6 66.8 대비 큰 성능 하락 없음
```

---

## V6.2 — Retrieval

추가:

```text
index_soap.jsonl
BM25
Top-K medical context
```

기존 V6 action logic은 최대한 유지.

---

## V6.3 — Candidate Tracker

추가:

```text
Candidate 5~7
Support
Against
Unknown
```

---

## V6.4 — Phase Controller

처음에는 4단계 상위 Phase로 구현.

```text
Initial
Broad Differential
Discrimination
Final
```

안정되면 Part 1~8로 세분화.

---

## V6.5 — Action Candidate

GPT가 행동 하나가 아니라 3~5개 후보 생성.

기존 V6 action과 비교하며 선택.

---

## V6.6 — Review / Audit

추가:

```text
Intermediate Review
Top-3 Verification
Final Audit
```

---

## V6.7 — Optimization

마지막에 Information Gain, Look-ahead 등을 보조 기능으로 실험.

---

# 37. 버전별 평가 기준

각 버전마다 최소 아래를 기록한다.

```text
총 Sample Score
Information Gathering
Diagnostic Reasoning
Safety
Communication
Efficiency
평균 patient turns
GPT calls
중복 질문 횟수
실행 실패 여부
SOAP hallucination 여부
```

새 기능을 추가한 뒤 score가 크게 하락하면 다음 단계로 넘어가지 않는다.

---

# 38. AB 비교 원칙

예:

```text
V6
vs
V6.1 State
```

비교.

그 다음:

```text
V6.1
vs
V6.2 Retrieval
```

비교.

여러 기능을 한 번에 추가하지 않는다.

그래야 어떤 기능이 점수를 올리고 내렸는지 알 수 있다.

---

# 39. Retrieval 안전 원칙

`index_soap.jsonl`은 현재 완벽한 SOAP DB가 아니다.

따라서 아래처럼 사용한다.

```text
DB
→ 일반 medical knowledge

Patient Evidence
→ 실제 환자 사실
```

DB 내용을 환자 사실로 복사하지 않는다.

또한 BM25 결과 제목을 질환명으로 바로 사용하지 않는다.

---

# 40. Medical DB Filtering

가능하면 Retrieval 전에 아래 문서는 제외 또는 낮은 가중치를 준다.

```text
veterinary medicine
medical physics
비임상 guideline
순수 기술/교육 guideline
현재 환자 진료와 무관한 문서
```

초기에는 title/source 기반 blacklist 또는 whitelist를 사용할 수 있다.

---

# 41. Action Selector 초기 버전

초기에는 단순 Rule 기반.

우선순위:

```text
1. Red Flag / Safety
2. Top 후보 간 차별력
3. 아직 미확인 핵심 finding
4. 현재 Phase 목표
5. 중복 여부
6. Turn cost
```

Information Gain은 나중에 추가한다.

---

# 42. 최종 SOAP

SOAP Writer는 반드시 Evidence Ledger를 primary source로 사용한다.

입력:

```text
Opening data
Evidence Ledger
Final diagnosis
관련 치료/계획 knowledge
```

주의:

```text
S / O
→ 실제 환자 evidence만

A / P
→ 환자 evidence + reasoning + medical knowledge 활용 가능
```

단 A에서도 근거는 실제 환자 evidence를 명시한다.

---

# 43. 코드 구조 제안

개발 중:

```text
nova-agent/
│
├─ run.py
├─ requirements.txt
│
├─ knowledge/
│   ├─ index_soap.jsonl
│   └─ bm25_soap_index.pkl
│
├─ agent/
│   ├─ phase_controller.py
│   ├─ state_manager.py
│   ├─ candidate_tracker.py
│   └─ action_selector.py
│
├─ retrieval/
│   ├─ bm25_search.py
│   └─ query_builder.py
│
├─ prompts/
│   ├─ patient_state.txt
│   ├─ initial_question.txt
│   ├─ differential.txt
│   ├─ action_generation.txt
│   ├─ review.txt
│   └─ final_audit.txt
│
└─ record/
    ├─ evidence_ledger.py
    └─ soap_writer.py
```

최종 제출 시 대회 규격에 맞춰 패키징.

---

# 44. Kiro 구현 우선순위

Kiro는 처음부터 Part 1~8 전체를 구현하지 말고 다음 순서로 작업한다.

```text
STEP 1
V6 코드 구조 분석
↓
KEEP / MODIFY / DELETE 후보 표시

STEP 2
Structured Patient State 추가
↓
기존 V6 동작 유지 확인

STEP 3
BM25 Retrieval 연결
↓
기존 V6 action logic 유지

STEP 4
Candidate Tracker 추가

STEP 5
Phase Controller 추가

STEP 6
GPT Action Candidates 추가

STEP 7
Intermediate Review / Final Audit

STEP 8
샘플 반복 평가 후 최적화
```

---

# 45. Kiro에게 주는 핵심 지시문

아래 내용을 가장 중요한 구현 지침으로 사용할 것.

> 첨부한 `submission_v6_20261014_124601.zip`의 V6 코드를 기준으로 개발한다.

> V6에서 이미 안정적으로 동작하는 N.O.V.A SDK interaction, retry, JSON parsing, turn/time 관리, dedup, gate, SAY/EXAM validation, fallback, SOAP submission 구조는 최대한 유지한다.

> 기존 V6 로직을 전면 재작성하지 않는다.

> 새 기능은 `Structured Patient State → BM25 Retrieval → Candidate Tracker → Phase Controller → Action Candidate Selection → Intermediate Review → Final Audit` 순서로 단계적으로 추가한다.

> 새로운 기능은 처음에는 기존 V6 로직의 대체가 아니라 보조 레이어로 붙인다.

> 기존 기능을 삭제해야 할 경우, 새 기능이 해당 역할을 안정적으로 대체하는 것이 샘플 검증에서 확인된 후 제거한다.

> 새 기능이 실패하면 기존 V6 logic으로 fallback할 수 있어야 한다.

> `index_soap.jsonl`은 일반 의료 Knowledge Base로 사용하고, 실제 환자 fact source로 사용하지 않는다.

> 최종 SOAP의 S/O에는 Opening, SAY response, EXAM result 등 실제 환자에서 확인한 정보만 사용한다.

> V8의 Information Gain 로직은 초기 핵심 제어기로 사용하지 말고, 전체 시스템이 안정된 뒤 Action Selector의 보조 score로만 실험한다.

> 각 버전은 한 번에 하나의 주요 기능만 추가하고, V6 기준 점수와 비교한다.

---

# 46. 최종 개발 철학

이번 프로젝트의 목표는:

```text
V6를 버리고 더 복잡한 Agent를 만드는 것
```

이 아니다.

목표는:

```text
현재 가장 잘 동작하는 V6의 강점을 보존
        ↓
Patient State로 기억력 강화
        ↓
Retrieval로 의료 지식 보강
        ↓
Candidate Tracker로 reasoning 구조화
        ↓
Phase Controller로 진료 과정 안정화
        ↓
Action Selector로 질문 효율 개선
        ↓
Final Audit으로 누락/안전성 개선
```

이다.

최종적으로:

> **V6의 안정성 + 구조화된 환자 기억 + 의료 지식 검색 + 단계적 감별진단 + 안전한 종료 판단**

을 결합한 Doctor Agent를 만드는 것이 목표다.
