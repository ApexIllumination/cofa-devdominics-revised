# 로그인부터 계정 전환까지 통합 점검

서로 다른 결과를 가진 **테스트 계정 두 개**를 준비한다. 아래 한 흐름을 같은 브라우저 세션에서 확인한다. 로그인 API만 통과하거나 화면에 성공 문구만 뜬 것으로 전체 통과를 기록하지 않는다.

| 직접 할 일 | 기대 결과 |
| --- | --- |
| 로그아웃 상태에서 보호 데이터를 요청하고 A로 로그인 | 서버는 처음에 401. 로그인 후에는 A의 실제 데이터가 보임 |
| 같은 조회 버튼을 두 번 사용 | 두 번째 조회도 완료. 요청 중에는 중복 클릭을 막음 |
| 개발 환경에서 조회 1회만 503으로 실패시킨 뒤 같은 버튼으로 재시도 | 오류가 드러나고 오래된 결과는 사라짐. 다시 누르면 A의 결과와 원래 버튼이 돌아옴 |
| 새로고침한 뒤 조회 | 로그인 유지, 같은 A 결과 |
| 로그아웃한 뒤 B로 로그인해서 조회 | 로그아웃하면 서버는 보호 데이터에 401. B 화면에는 A 결과가 없고 B 결과만 보임 |
| 다른 탭에서 로그아웃한 뒤 원래 탭에서 조회 | 다음 요청에서 401. 로그인 화면으로 돌아가며 이전 결과가 사라짐 |

Cofa에서는 [시험 규칙](../../EXAM.md)에 따라 참가자가 제공 Browser에서 직접 확인한다. 안전하게 오류를 재현할 수 없다면 해당 행은 미확인으로 기록한다. 아래 자동화는 **로컬 개발용**이다.

## 기존 앱에 자동 검사 연결

로컬에 Playwright와 브라우저가 준비된 환경에서 실행한다. 앱은 같은 출처 쿠키 세션을 사용하고 로그아웃은 JSON POST에 204를 반환해야 한다. 인증 계약이 다르면 해당 검사를 먼저 조정한다.

1. [설정 예제](example/config.json)를 복사해 보호 GET 경로, 로그아웃 경로, 재시도 버튼 문구, 테스트 계정별 ID와 예상 결과 텍스트를 정한다. 결과에는 서로 다른 짧은 식별값을 쓴다.
2. 화면 요소에 `data-testid`를 연결한다: `id`, `password`, `login`, `identity`, `read`, `result`, `logout`. 기존 이름을 쓰면 설정의 `testIds`로 대응시킨다(예: `{"read":"fetch-assignment"}`). identity와 result는 각각 ID와 기대 텍스트 하나만 표시하는 요소여야 한다.
3. `node check.cjs http://127.0.0.1:8000 설정파일.json`. 설치된 Google Chrome은 `CHROME_CHANNEL=chrome`으로 선택한다. 503 한 건만 브라우저에서 주입하고 나머지 조회·세션 무효화는 실제 로컬 서버를 사용한다. 실패하면 종료 코드가 0이 아니다.

## 예제만 실행하기

Node/npm, Python 3가 있는 로컬에서 kit 루트 기준으로 실행한다. 임시 폴더를 쓰므로 앱이나 kit 의존성은 바뀌지 않는다.

```sh
demo_dir=$(mktemp -d)
cp -R templates "$demo_dir/"
cd "$demo_dir"
npm init -y >/dev/null
npm install react react-dom esbuild playwright
npx playwright install chromium
npx esbuild templates/web-smoke/example/app.tsx --bundle --outfile=app.js
python3 templates/web-smoke/example/server.py app.js 8123
```

서버를 유지한 채 다른 터미널에서 위 임시 폴더로 이동해 실행한다.

```sh
node templates/web-smoke/check.cjs http://127.0.0.1:8123 templates/web-smoke/example/config.json
```

예제는 기존 [세션 템플릿](../session-login/README.md)에 테스트 전용 계정 두 개와 보호 조회 한 개를 붙인다. 실제 제품에는 예제 계정이나 오류 주입 기능을 복사하지 않는다.
