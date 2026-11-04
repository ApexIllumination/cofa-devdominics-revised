# 로그인부터 내 정보 조회까지

로그인이 필요한 과제에서 먼저 제공 인증과 프레임워크의 세션 기능을 확인한다. 별도 인증이 없는 Python WSGI 단일 프로세스 데모라면 session_login.py를 프로젝트에 복사해 사용한다. verify는 과제의 계정을 검증하고 성공 시 서버가 확인한 사용자 ID를, 실패 시 None을 반환한다. 고정 계정과 암호는 포함하지 않는다.

```python
from session_login import with_login

application = with_login(my_wsgi_app, verify)
```

기본은 HTTPS 쿠키다. 로컬 HTTP를 사용하는 데모에서만 secure_cookie=False로 설정한다. 세션은 기본 한 시간 동안 유효하며 서버를 재시작하면 사라진다. 실제 서비스는 해당 조직의 인증과 세션 저장소를 사용한다.

| 화면 행동 | 같은 출처의 API 계약 |
| --- | --- |
| 로그인 | POST /api/login, JSON 본문 `{"id":"…","password":"…"}`. 성공 204(빈 본문), 잘못된 자격 증명 401. |
| 페이지 열기·새로고침 | GET /api/me → 200 `{"id":"…"}` 또는 401. 로그인 성공 직후에도 이 경로로 확인한다. |
| 내 업무 데이터 표시 | 과제 API를 별도로 호출한다. 서버의 my_wsgi_app은 `environ["kit.user_id"]`가 None이면 보호된 경로를 401로 거부하고, 값이 있으면 그 ID로 조회한다. 클라이언트가 보낸 ID를 신원으로 사용하지 않는다. |
| 로그아웃 | POST /api/logout, Content-Type: application/json, 본문 `{}`. 성공 204. 서버가 세션을 폐기한다. |

프론트는 204 응답에서 JSON을 읽지 않는다. 401일 때 로그인 화면으로 돌아가고, 업무 API의 5xx는 조회 오류로 표시한다. 통합 담당은 두 계정 전환, 새로고침, 로그아웃 후 옛 쿠키 재사용, 실제 업무 조회의 권한 분리를 확인한다. 외부 프론트에 임의 출처의 인증 요청을 허용하는 CORS 설정은 이 템플릿의 범위 밖이다.
