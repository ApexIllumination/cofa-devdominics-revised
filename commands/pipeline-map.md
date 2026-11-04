# pipeline-map 명령 레시피

이 파일은 플랫폼 중립 명령 설명이다. `/pipeline-map`이라는 네이티브 슬래시 명령을 자동 등록하지 않는다. 사용하는 실행기가 사용자 명령을 지원하면 아래 동작을 해당 방식으로 연결하고, 그렇지 않으면 CLI를 직접 호출한다.

```sh
python3 /path/to/cofa-kit-revised/scripts/cofa.py --root /path/to/project check
python3 /path/to/cofa-kit-revised/scripts/cofa.py --root /path/to/project map
```

지도는 `.cofa/pipeline-map.json`에서 읽는다. `map`은 목적·진입점·흐름·의존성·실행 명령과 누락된 참조를 출력할 뿐 실제 코드를 전부 읽거나 명령을 실행하지 않는다. 최신 여부는 `check` 결과로 따로 확인한다.

변경이 있으면 관련 파일과 지도 설명을 대조하고, 실제 작업에 필요한 코드만 읽는다. 변경 파일 목록만 보고 문서를 자동 수정하거나 새 지문을 기록하지 않는다. 코드와 지도를 확인한 후 `snapshot`으로 기준 지문을 갱신한다.
