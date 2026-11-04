# 같은 입력으로 다음 검토 행동 선택

호출자가 한 가지 쟁점과 그 쟁점을 구분하는 입력을 정한다. 예를 들어 두 명이 탄 노선이 통과했다는 사실만으로 한 명이 탄 노선의 처리 방식을 설명할 수 없다. 검사와 현업 질문 모두 같은 1인 노선 입력을 가리키게 한다.

```json
{
  "context": {
    "task": "한 명만 태울 수 있는 유일한 노선을 허용하는가?",
    "comparison": {
      "input_id": "singleton-fixture-v1",
      "expected": {"input_id":"singleton-fixture-v1","value":"ok","source":"HR의 확정 답변 2번"}
    }
  },
  "actions": [
    {"id":"probe","kind":"counterexample","input_id":"singleton-fixture-v1","label":"해당 1인 노선 입력 실행"},
    {"id":"fix","kind":"proposal","input_id":"singleton-fixture-v1","label":"해당 1인 노선을 허용하도록 변경 제안"},
    {"id":"finish","kind":"stop","label":"종료"}
  ]
}
```

이 예를 packet.json으로 저장하고 `python3 scripts/next_action.py packet.json --model MODEL`을 실행하면 첫 행동은 probe다. 호출자가 실제 검사 후 comparison.observed에 같은 구조로 결과와 출처를 넣는다. ok이면 finish, infeasible이면 fix가 선택된다. 현업의 확정 응답이 없으면 expected를 생략하고 question 선택지를 제공한다. 일반적인 선호나 미확정 답은 history에만 둔다.

- 입력 ID는 호출자가 내용과 버전에 결합한다. 입력·비교 기준·구현이 바뀌면 해당 근거를 폐기한다. observed는 실제 실행에서, expected는 확정한 현업 판단에서 가져온다. 두 값은 같은 단위·기준의 정규화된 문자열이어야 한다. 수치 허용오차나 여러 지표를 묶는 규칙도 호출자가 정한다.
- 실행기는 현재 입력의 실제값이 없으면 counterexample, 기대값만 없으면 question, 같으면 stop, 다르면 proposal로 선택지를 좁힌다. 필요한 행동이 소진되면 미확인(Pending) 사유로 종료한다. 종료는 현재 입력과 비교 항목에만 적용한다.
- 후보가 하나이면 Python이 바로 선택한다. 같은 종류에 여러 후보가 남으면 Codex가 선택하고 반환된 ID를 다시 검사한다. 모델은 현업에게 직접 연락하거나 제안을 적용하지 않는다. 수정은 기존 design-review 절차의 사람 결정과 재검증을 거친다.
- 호출자는 결과와 이력을 갱신하고, 사용한 선택지를 제거하고, 횟수 한도를 둔다. stop은 항상 제공한다. comparison이 없는 예전 패킷은 미확인으로 끝나므로 input_id와 해당 행동의 input_id를 먼저 추가한다.

현업 답변과 본인의 결정이 생긴 시점에 [결정 기록](decision-log.md)에 같은 결정 ID로 남기고, 승인 후 검증한 결과를 이어 붙인다. 제안만 받은 상태에서는 본인의 선택이나 버린 이유를 추정하지 않는다.
