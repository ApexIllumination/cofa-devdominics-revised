# 외부 UI 스킬 선택

과제의 실제 화면과 사용자가 막힌 행동을 먼저 확인한다. 새 업무 화면은 Impeccable로 시작할 수 있고, 이미 문제가 좁혀졌으면 아래 한 행에서 바로 시작한다. 선택한 도구의 결과는 [verify-results](../skills/verify-results/SKILL.md)에 넘겨 제품 동작으로 확인한다.

| 언제 | 검토한 원본 파일 | 어떻게 사용하나 |
|---|---|---|
| 새 업무 화면·정보 위계 | [pbakaus/impeccable · impeccable](https://github.com/pbakaus/impeccable/blob/f864521bbb1c9350e8f6cf7742c139a04a1020af/.agents/skills/impeccable/SKILL.md) | 기본 디자인 파트너. 사용자·결정·주요 행동을 전달한다. [기존 연결 절차](impeccable.md)를 사용한다. |
| 같은 컴포넌트의 상태 비교 | [jakubkrehel/skills · state-machine](https://github.com/jakubkrehel/skills/blob/60bf140e43c98b248e6594487384ec967e89d98a/skills/state-machine/SKILL.md) | 화면 하나에서 빈 상태·선택 중·한도 도달 등의 차이가 중요한 경우에 명시적으로 선택한다. 실제 코드에 있는 상태를 임시 미리보기에서 전환하고 제품 진입점에서도 다시 확인한다. |
| 기존 React 컴포넌트 조합 | [shadcn-ui/ui · shadcn](https://github.com/shadcn-ui/ui/blob/8a3536678a528cc012b9e62484290e79d0be410f/skills/shadcn/SKILL.md) | components.json과 설치된 컴포넌트를 먼저 확인한다. shadcn 프로젝트이거나 사용자가 도입을 택한 경우에만 해당 컴포넌트 문서를 따른다. 일반 React+Tailwind 작업의 기본 의존성으로 추가하지 않는다. |
| 전환 효과가 조작을 방해함 | [emilkowalski/skills · review-animations](https://github.com/emilkowalski/skills/blob/f1090bec277140d02ed202440185ad9d02ac1490/skills/review-animations/SKILL.md) | 검토할 전환과 문제를 지정한다. 예를 들어 비교 패널을 빠르게 열고 닫을 때의 중단·포커스·모션 감소 설정을 확인한다. 이미 동작하는 화면에 효과를 추가하기 위한 기본 단계로 쓰지 않는다. |
| 화면의 시각 리뷰만 요청 | [Superfuture/design-review · 체크리스트](https://github.com/Superfuture/design-review/blob/d4d2609b53fccb475d11490e2c6261e5eb2f0c5d/design-review/skills/design-review/checklist.md) | 체크리스트만 참고해 문제 요소·사용자 영향·수정 우선순위를 남긴다. 같은 목적의 Impeccable critique와 하나를 고른다. 원본 실행 스킬은 사용 이벤트와 지속 식별자를 전송하므로 이 경로에서는 호출하지 않는다. |
| 접근성 문제 진단 | [addyosmani/web-quality-skills · accessibility](https://github.com/addyosmani/web-quality-skills/blob/afa8da942115f2961fdbfa80807ea0b232ff6c00/skills/accessibility/SKILL.md) | 특정 화면의 버튼 이름·역할·키보드 탐색을 점검하고 수정 전후 같은 동작을 비교한다. 실제 실행한 감사와 문서 검토를 구분한다. |
| 실제 스크린리더 청취 필요 | [wshobson/agents · screen-reader-testing](https://github.com/wshobson/agents/blob/7e2fb559cf4b824b27f1fec49fe88f7511066d26/plugins/accessibility-compliance/skills/screen-reader-testing/SKILL.md) | 스크린리더·브라우저 조합을 정해 동적 알림, 표 머리글, 선택 버튼이 어떻게 읽히는지 확인할 때만 사용한다. 접근성 트리 조회만 했다면 청취는 미확인이다. |
| 허용된 로컬 브라우저 회귀 검사 | [anthropics/skills · webapp-testing](https://github.com/anthropics/skills/blob/ca45fc496a3436251f191354091d557da31c15b5/skills/webapp-testing/SKILL.md) | Playwright를 쓸 수 있는 개발 환경에서 핵심 조작을 재현한다. 예를 들어 안 두 개 선택 → 비교값 읽기 → 한 안 교체를 확인한다. Cofa 시험에서는 EXAM.md의 화면 조작 범위를 먼저 적용한다. |
| 시각 콘셉트를 지정한 포트폴리오 | [MengTo/Skills · editorial-portfolio-chapters](https://github.com/MengTo/Skills/blob/1de14e21b2ba8937c0f7f6ddca581cf7cd9d94af/agent-skills/web-design/editorial-portfolio-chapters/SKILL.md) | 작업물을 중심에 둔 포트폴리오·스튜디오 소개 화면을 요청받은 경우의 레퍼런스다. 운영 대시보드에는 기본 적용하지 않는다. |

## 프로젝트에서 연결하기

[README의 디자인 자료 준비 절차](../README.md#웹-과제의-디자인-자료-자동-준비)를 실행했다면 출력된 로컬 파일을 직접 읽는다. 현재 세션에 해당 스킬이 있으면 선택한 작업과 대상 파일을 구체적으로 지정한다. 별도 체크아웃이면 표 링크의 커밋·경로에 해당하는 파일을 직접 읽는다. 상대 참조와 보조 스크립트는 그 스킬 디렉터리를 기준으로 찾는다. 표의 링크는 검토 버전을 고정한 참조이며 kit를 clone해도 다른 도구가 설치되지는 않는다. 사용 가능한 사본이나 허용된 접근 경로가 없으면 같은 검증 목표를 기존 도구로 수행하고 무엇을 확인했는지 기록한다. 프로젝트가 사용하는 컴포넌트·도구의 버전이 다르면 해당 버전의 호환성을 확인한다. 외부 문서의 설치, 통계 전송, 원격 서비스 연결은 자동으로 실행하지 않는다.

## 셔틀 화면에 적용하는 예

“선택 불가 사유를 비용보다 먼저 보여 줘”는 Impeccable로 보낸다. “선택 0개·1개·2개일 때 버튼이 서로 혼동된다”면 해당 컴포넌트에 state-machine을 선택한다. “Tab으로 이동하면 어느 노선의 버튼인지 모르겠다”면 accessibility로 접근성 이름을 확인하고, 제품에서 ‘균형형 네트워크 비교 선택 해제’처럼 대상과 행동이 함께 전달되는지 재검증한다. 직접 청취를 요청했을 때만 스크린리더 검사로 이어간다. 정원·마감·비용 계산의 기준은 [decision-rules](../skills/decision-rules/SKILL.md)가 맡는다.
