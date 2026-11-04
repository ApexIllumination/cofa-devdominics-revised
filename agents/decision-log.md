# 결정의 당시 근거 기록하기

중요한 결정을 내릴 때 식별자 하나를 정한다(예: SHUTTLE-01). 현업 답변을 받은 시점, 본인이 결정을 내린 시점, 검사가 끝난 시점에 각각 한 건을 추가한다. 다음 행동 도구가 낸 수정 제안은 아직 본인의 결정이 아니다. actor에는 실제 발화자·결정자나 simulated를 쓰고 source에 DM 턴·승인 메시지·검사 출력 경로 등 확인할 위치를 넣는다. 확인할 수 없는 대안이나 이유는 unknown으로 둔다. 인증·자동 대화 수집 기능은 없다.

| kind | detail에 넣는 문자열 필드 |
|---|---|
| answer | answer (업무에 필요한 현업 답변) |
| decision | choice, reason, alternative, why_rejected |
| verification | input_id, expected, actual, status (pass / fail / pending) |

서로 다른 검사는 각각 기록한다. 실행 전이면 actual은 unknown, status는 pending이다. 나중에 검사를 실행하면 새 event_id로 추가한다. 정정할 때에도 새 event_id를 사용하고 이전 사건을 source에서 지목한다. 같은 결정에서 같은 event_id·같은 내용으로 재시도하면 중복되지 않는다. 값이 다르면 거절한다. 이 저널을 쓰면 기존 과제 상태 문서에는 결정 ID와 DB 위치만 적는다.

## CLI

프로젝트 폴더에서 사용한다. 아래는 실제 답변을 받은 상황을 가정한 예다. 각 명령에서 같은 DB를 지정한다. append는 표준입력으로 JSON 한 건을 받는다.

```sh
python3 cofa-kit-revised/scripts/decision_log.py --db decisions.sqlite append <<'JSON'
{"decision_id":"SHUTTLE-01","event_id":"dm-2","kind":"answer","actor":"현업 담당자","source":"DM 2번","detail":{"answer":"한 명이라도 통근 수단이 필요하면 1인 노선을 허용합니다."}}
JSON
python3 cofa-kit-revised/scripts/decision_log.py --db decisions.sqlite recall SHUTTLE-01
```

## 선택적 MCP

Python에 공식 SDK 패키지 `mcp>=1.10,<2`가 있는 환경에서 stdio로 연결한다. command는 그 환경의 python 절대경로, args는 아래처럼 지정한다. DB의 상위 디렉터리는 미리 만들어 둔다.

```json
{"mcpServers":{"decision-log":{"command":"/absolute/path/to/python","args":["/absolute/path/to/cofa-kit-revised/scripts/decision_mcp.py","--db","/absolute/path/to/workspace/decisions.sqlite"]}}}
```

대화에서 “SHUTTLE-01에 방금 현업이 확정한 답을 출처와 함께 남겨 줘”라고 요청하면 record_event를 호출한다. “내가 왜 그렇게 결정했지?”에는 recall_decision으로 당시 기록을 조회하고, 선택·버린 대안·검증 범위를 구분해 설명한다. SDK가 없으면 같은 DB를 표준 라이브러리 CLI로 사용할 수 있다.

기능 설계는 [Ryanpark3142의 결정 기록 및 작업 로그 도구](https://github.com/Ryanpark3142/cofa-kit/blob/4ab39c574b5f8a0623f64b8654d04ca0740ab771/docs/mcp.md)를 참고했다.

## 과거 통과의 현재 유효성

당시 이력은 recall로 본다. 지금 재사용할 때는 current 또는 MCP의 current_pass를 호출한다.

```sh
python3 cofa-kit-revised/scripts/decision_log.py --db decisions.sqlite current SHUTTLE-01 admit input-sha revision-sha --rule singleton
```

같은 decision_id에 HR의 확정 답을 answer로 남기면서 detail에 안정된 업무 규칙 ID인 rule_id를 붙인다. 정정 시 같은 rule_id와 새 event_id를 쓴다. 확인 전 단서와 새 방침을 구별한다. 실제 검사 뒤에는 다음 형식의 verification detail을 저장한다.

```json
{"input_id":"input-sha","expected":"ok","actual":"ok","status":"pass","check_id":"admit","revision":"revision-sha","answers":{"singleton":"dm-2"},"runs":1}
```

answers는 당시 검사에서 사용한 관련 규칙과 확정 답변 event_id의 대응이다. 검사 전 그 버전을 확보하고 실행 후에도 같은 참조로 기록한다. 실행하지 않았다면 runs=0, actual=unknown, status=pending이다. 이 방식은 같은 기준으로 정규화한 문자열의 일치를 검사한다. 허용 오차·단위가 있다면 검사기가 비교 기준을 먼저 적용한다. revision은 관련 구현·검사·설정 내용의 지문, input_id는 입력 내용 지문으로 호출자가 제공한다. 파일명이나 고정 문자열을 계속 보내면 변경을 감지할 수 없다.

current에는 현재 적용 대상인 **모든 관련 규칙**을 전달한다(--rule 반복 가능). 같은 검사·입력의 최신 완료 결과가 pass이고 구현/검사 지문·관련 규칙·그 답변 버전이 모두 맞으면 current_pass다. 변경은 stale, 미실행·새 입력은 not_run, 근거 없는 옛 기록이나 이후 범위 미지정 답변은 unbound, 유효한 실패는 failed다. current_pass만 재사용한다. 과거 기록은 삭제하지 않는다. 무관한 답은 별도의 rule_id로 기록하면 재검사하지 않는다. 자동 의미 분류와 실행 증명은 하지 않으므로 실제 실행 횟수와 관련 규칙 지정은 호출자의 책임이다.
