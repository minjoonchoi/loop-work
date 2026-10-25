# 공통 작업과 로컬 지식

에이전트는 새 요청 전에 지식과 이전 결정을 읽고, 부족하거나 바뀐 부분만 조사합니다.
사용자는 목표를 전달합니다. 아래 명령과 JSON 작성은 에이전트의 내부 작업입니다.

## 요청 해석

| 요청 | 처리 |
| --- | --- |
| “기능을 완성해 줘”, “이 오류를 고쳐 줘” | 개발 목표와 검토 루프 |
| “왜 오류가 나는지 설명해 줘” | 설명과 근거 확인; 코드 변경 없음 |
| “문서를 정리해 줘”, “계획만 세워 줘” | 해당 결과 작성과 내용 확인 |
| “왜 멈췄어?”, 실행 중 보완 지시 | 기존 상태 확인·보완; 중복 작업 생성 없음 |

같은 세션 ID를 여러 디렉터리에서 사용합니다. 다른 대화의 ID를 최근 기록이라는 이유로 선택하지
않습니다. 새 대화도 프로젝트 지식은 읽을 수 있지만 세션·작업에 한정된 답변은 분리합니다.

## 작업 단위 결속

`$loop-work <작업 내용>` 또는 `/loop-work <작업 내용>`은 한 작업에만 적용합니다.
`work open --explicit-skill` 또는 개발 `init --explicit-skill`로 생성한 작업·세션을
`harness on --provider codex --session SESSION_ID --task TASK_ID`로 결속합니다.
진행 중 관련 정정·상태 확인·맥락 압축은 같은 작업이며 무관한 일반 입력은 자동 처리하지 않습니다.
완료·abort는 결속을 해제하고 작업·지식·예산을 보존합니다. pause/blocker는 완료가 아닙니다.
`harness off SESSION_ID`는 호환 해제 명령이고 최신 세션을 임의 선택하지 않습니다.
`orchestration context SESSION_ID --task TASK_ID`로 해당 작업만 복원합니다.
구형 conversation-wide enabled 상태만으로 새 입력을 자동 처리하지 않습니다.

## 비개발 작업

```sh
python3 .loop/loop.py work open --explicit-skill --kind explanation --title "저장 방식 설명" --provider codex --path /project --session SESSION_ID
python3 .loop/loop.py work goal WORK_ID --input /temporary/goal.json
python3 .loop/loop.py work start WORK_ID
python3 .loop/loop.py work delegate WORK_ID --input /temporary/assignment.json --path /project
python3 .loop/loop.py work assess WORK_ID --input /temporary/assessment.json --path /project
python3 .loop/loop.py work finish WORK_ID --input /temporary/result.json
```

작업 생성에서 받은 세션·작업 ID로 결속하고 관련 명령에 `--session SESSION_ID`를 사용합니다. 여러 디렉터리는 `--path`를 반복합니다.
`--provider`는 대화, 선택적인 `--worker`는 작업 CLI이며 생략하면 같은 공급자를 씁니다.
위임은 [위임 규칙](../rules/delegation.md)의 필드를 모두 채웁니다. 여러 경로에 연결된 작업은
위임할 때 한 경로를 명시해야 합니다. 위 순서는 후보를 내부 검토해 채택한 경우입니다.
worker-output 품질 실패는 같은 위임을 더 높은 허용 프로필로 재실행합니다. V2 입력·fixture
수리는 같은 프로필의 연결된 standalone revision으로 처리하며 누적 시도·예산을 보존합니다.
팀은 revision 1만 지원하며 후보 검토 후 같은 계획으로 이어 실행합니다. 사용자에게 평가 JSON이나 다음 프롬프트를 요구하지 않습니다.
유형은 `document`, `explanation`, `research`, `review`, `planning`입니다.
`development`는 기존 개발 엔진에 위임하므로 `work finish`로 완료할 수 없습니다.

| 입력 | 필드 |
| --- | --- |
| 목표 | `outcome`, `deliverable`, `criteria[{id, description}]`, `decisions`, `open_questions`, `execution.routing`과 선택적 실행 한도 |
| 결과 | `summary`, `outputs`, `checks[{criterion_id, satisfied, evidence}]`, 선택적 `knowledge` |
| 결정 | `answer`, `basis`, `applies_to`, 원래 답변의 `evidence` |

`goal_setting → working → completed`로 진행하며 `blocked`·`aborted`도 기록합니다.
미해결 질문이 있으면 시작하지 않습니다. 시작한 목표는 고정됩니다. 모든 완료 조건을 근거와 함께
확인해야 완료할 수 있으며, 미충족 조건은 작업 중 상태로 남습니다. 별도 검토 모델이나 반복 횟수는 없습니다.
내용 충족 여부는 에이전트가 실제 전달물을 확인해 기록하는 것으로, 스크립트의 독립 검증은 아닙니다.

`execution`의 기본 한도는 `max_worker_calls: 40`, `worker_timeout_seconds: 600`,
`max_run_seconds: 14400`입니다. 작업 시작 뒤에는 고정되며 새 위임 ID나 재개로 초기화하지 않습니다.
에이전트는 시작 전 `execution.routing`에 사용 가능한 모델·effort 풀을 채웁니다.
`LOOP_ROUTING_PROFILE`로 준비된 정책을 가져올 수도 있습니다. 예제 목표 JSON은 이 설정을
채우기 위한 뼈대이며 CLI 기본 모델로 자동 실행하지 않습니다. [라우팅 규칙](../rules/routing.md)을 따릅니다.

기본 상태 복원은 작은 `orchestration context`로 하고 필요한 상세만 `work context WORK_ID`에서 확인합니다.
발견 사항은 `work note WORK_ID --text TEXT --evidence REF`,
장애는 typed 근거 입력을 사용하는 `work block WORK_ID --input BLOCK_JSON`로 기록합니다
([입력 형식](operations.md#typed-block-and-retirement)). 복구는 `work resume WORK_ID`,
종료는 `work abort WORK_ID --reason TEXT`입니다. 완료 결과는 파일 변경 이후에도 과거 기록으로 남습니다.

## 지식 항목

다음은 형식 예시이며, 실제 기록에는 직접 확인한 파일과 결과를 씁니다.

```json
{
  "id": "notes-storage",
  "title": "메모 저장과 재조회 방식",
  "kind": "fact",
  "scope": "project",
  "status": "confirmed",
  "summary": "메모는 로컬 JSON 파일에 저장되며 다음 실행에서 다시 읽습니다.",
  "why": "프로그램을 종료해도 저장한 메모를 조회할 수 있습니다.",
  "uncertainty": "동시 쓰기 충돌은 아직 검증하지 않았습니다.",
  "evidence": ["src/storage.py:save/load", "tests/test_storage.py:test_reload"],
  "paths": ["src/storage.py", "tests/test_storage.py"]
}
```

| 구분 | 값과 의미 |
| --- | --- |
| 범위 | `global` 공통 선호, `project` 한 프로젝트, `checkout` 한 작업 트리, `session` 한 대화, `task` 한 작업 |
| 상태 | `confirmed` 근거가 있는 결론, `draft` 초안, `hypothesis` 가설, `superseded` 대체된 내용 |
| 종류 | `fact`, `decision`, `artifact`, `finding` |
| 표시 제목 | 새 항목은 한 줄 60자 이하의 한국어 명사구 `title`; 결론 `summary`와 분리 |
| 선택 필드 | `why`, `details` 최대 다섯 개, `uncertainty`, 외부 정보의 `expires_at` |

결정은 원래 `basis`와 `applies_to`가 필요합니다. 같은 ID의 범위·소유 프로젝트를 조용히 바꿀 수 없습니다.
소스 분석은 전체 근거 파일을 `paths`에 넣습니다. `src/`는 파일 추가·삭제를 포함하고 `.`은 전체를
감시합니다. 외부 서비스의 실제 상태는 파일 해시로 알 수 없으므로 필요할 때 다시 확인합니다.

```sh
python3 .loop/loop.py knowledge context --path /project --session SESSION_ID
python3 .loop/loop.py knowledge remember --path /project --session SESSION_ID --input /temporary/topic.json --observed REVISION
```

분석 전에 받은 `revision`을 사용합니다. 분석 도중 파일이 달라지면 저장을 거절합니다.
변경 후 근거를 다시 확인해 같은 ID로 갱신합니다. 조회만으로 오래된 결론을 새 사실로 바꾸지 않습니다.
`work finish`에 새 `knowledge`와 `observed_revision`을 넣으면 결과와 지식을 한 트랜잭션으로 기록합니다.

상세 맥락의 `sources`에는 작업 위치에서 관측한 경로·해시와 파일명 기반 역할 힌트가 최대 24개
표시됩니다. 현재 목표로 관련 후보를 우선 보여줄 뿐 내용을 읽거나 의미를 확정하지는 않습니다.
에이전트가 필요한 PRD·목업·API·설계 자료를 조사할 출발점이며, 검색 결과가 없다는 이유만으로
자료가 없다고 판단하지 않습니다. 기록한 원본 의존성이 바뀌면 관련 지식을 재확인하고,
영향받는 문서·코드는 현재 요청 범위에서 조사·갱신합니다.

## 조회와 읽기 쉬운 문서

| 명령 | 용도 |
| --- | --- |
| `knowledge context [--query TEXT] [--limit 20] [--offset 0]` | 현재 지식, 재확인 항목, 초안, 작업 이력 |
| `knowledge get topic\|task\|delegation ID` | 전체 단일 기록과 문서 복구 |
| `knowledge history topic\|task\|delegation ID` | 현재 기록과 이전 버전 |
| `knowledge projects` | 프로젝트·작업 위치 목록 |
| `knowledge attach --path PATH [--project PROJECT_ID]` | 디렉터리 연결·이동 후 위치 갱신 |

맥락 JSON은 분류별 기본 20개와 전체 개수, 남은 페이지를 반환합니다. Markdown에는 분류별 다섯 개와
나머지의 조회 경로를 표시합니다. 페이지 밖의 자료도 보존하며, 읽기 전에 없다고 판단하지 않습니다.

`views/task/<id>.md`는 결과·상태·근거·다음 에이전트 행동을, `views/topic/<id>.md`는 결론·범위·상태·근거를
표시합니다. `views/delegation/<id>.md`는 위임 범위·산출물·완료 조건·적용 파일·장애를 표시합니다.
위임의 새 발견은 작업 범위의 초안으로 저장하며, 확인 후에만 확정 지식으로 갱신합니다.
`views/context/`는 조회 시점에 확인한 적용 가능성을 보여줍니다. 각 문서는 전체 JSON을 연결합니다.
확정 상태만으로 현재 유효하다고 간주하지 않으며, 재사용 전에 맥락을 확인합니다.

원본은 SQLite와 개발 상태 JSON입니다. Markdown은 이 데이터로 생성하며 수작업으로 편집하지 않습니다.
반복 조회는 같은 문서를 갱신하고 새 서술 문서를 쌓지 않습니다. 변화 없는 지식은 이전 시각과 버전을 유지합니다.
형식 검사는 빈 값·임시 문구·중복·길이 초과를 거절하고, 표현과 정확성은
[작성 규칙](../rules/writing.md)에 따라 확인합니다. 긴 설명 자체를 잘라내는 제한은 아닙니다.

## Obsidian 문서 공간

`make install`은 `~/.loop-work/vault` 하나를 준비합니다. Obsidian에서 **Open folder as vault**로
이 폴더를 열면 됩니다. 앱의 전역 vault 등록·플러그인·동기화 설정은 바꾸지 않습니다.

| 위치 | 역할 |
| --- | --- |
| `안내.md` | 전체 문서 공간의 읽기·편집 안내 |
| `프로젝트/<프로젝트 이름--8자리 식별자>/목록.md` | 프로젝트의 작업·지식으로 이동하는 목록 |
| 같은 프로젝트의 `프로젝트 안내.md` | 사람이 정리하고 편집하는 프로젝트 설명 |
| 같은 프로젝트의 `지식/<짧은 제목--8자리 식별자>.md` | 설계 결정·발견·회고 등 재사용할 지식 |
| 같은 프로젝트의 `작업/<작업 이름--8자리 식별자>/진행 현황.md`와 `작업 문서.md` | 생성된 현재 실행 기록과 별도의 사람 편집 문서 |
| 작업의 `기록/중간/`, `기록/완료/` | 기준 시점과 digest를 보존하는 과거 기록 |
| 작업의 `기록/위임/`, `협업/`, `사용자 검토/`, `피드백/`, `종료/` | 작업과 관련된 개별 실행·판단 기록 |
| `공통 지식/` | 전역 범위의 재사용 지식 |
| `개인 메모/` | 사람 메모; 승인·작업 지시로 자동 반영하지 않음 |

예를 들어 `프로젝트/인증 서비스--b9f31c2a/작업/권한 검사 수정--3ad10e62/진행 현황.md`에서
현재 결과를 읽고, 같은 폴더의 `기록/완료/`에서 당시 완료 근거를 확인합니다. 접미사 8자리는
동일한 이름을 구분하는 표시용 해시이며 전체 프로젝트·작업 ID를 대신하지 않습니다.
폴더 이름과 제목을 간결하게 유지하고 목록을 중복 생성하지 않습니다. 이름이 바뀌어도
고정된 관리 경로와 원래 scope/session/task 정체성은 유지합니다.

현행 runtime은 단일 layout 3만 읽고 씁니다. 기존 layout은 별도 보존형 변환 도구로 전환하며
runtime에 구형 경로 해석·별칭·자동 fallback을 두지 않습니다.
계획은 `python3 scripts/reorganize_vault.py --knowledge-home KB --vault VAULT --plan /absolute/plan.json`으로
생성하고 내용을 확인한 뒤 `python3 scripts/reorganize_vault.py --apply /absolute/plan.json --expected-plan-sha256 SHA256`로 적용합니다.
출력된 계획 해시를 그대로 사용합니다. 적용은 계획에 고정한 관리 문서와 사람 위키의 원문을
vault 외부 백업에 보존하고 새 구조로 전환하므로 탐색 목록에 구형 구조를 중복 노출하지 않습니다.
사람 위키 본문은 보존하며 연결된 생성 원본 링크만 새 경로로 바꿉니다. 기존 메모·미관리 문서·설정은
옮기지 않습니다. 편집 충돌·누락·예약 경로가 있으면 전체 전환을 거절하고, 새 복사본으로 우회하지 않습니다. 외부 소유권 manifest version은 1, layout은 3, 문서 envelope는 3입니다.

지식의 `title`은 짧은 한국어 명사구이며 결론 전체는 본문 `결론`에 남깁니다. 본문은 결론,
활용 목적, 확인한 내용, 적용 범위와 한계, 근거 순서로 읽습니다. 실제 내용이 없는 섹션은
생략합니다. 이전 title 없는 기록을 새 사실로 바꾸지 않고 짧은 발췌에는 `…`를 표시합니다.
긴 기록 ID·해시·JSON 링크는 접힌 원본 정보에 두며 초안·가설·미검증 경계는 본문에서 드러냅니다.
사용자 검토 문서는 질문·모든 선택지·응답·실행 여부를 읽기 쉽게 보여 주고 원문 JSON을 보존합니다.

고정 제목·상태 설명·출력 경계는 한국어이고, 에이전트가 쓰는 task title·summary·why·details·
uncertainty도 한국어로 작성합니다. 고유명사/API는 유지하고 사용자 원문·인용·code·명령·경로·
증거·hash·JSON key/enum은 번역하지 않습니다. 별도로 요청한 외국어 결과물은 그 언어로 유지하되
추적 설명은 한국어로 남깁니다. 기존 영어 결론을 exporter가 임의 번역하거나 원본 입력을
한글 유무로 거절하는 기능은 아닙니다.

현재 문서는 마지막 export cutoff이며 실제 source freshness는 원본 orchestration/DB context에서 확인합니다.
원본에 `evidence_current=false`가 반영되면 완료 기록의 현재 뷰를 미완료/재확인으로 표시하며
과거 최종 snapshot은 유지합니다. exporter가 실제 소스를 새로 검증하는 것은 아닙니다.
이전 미완료·실패 기록을 나중 성공으로 덮거나 파일명만으로 QA·승인을 판정하지 않습니다.
다음 정상 export 또는 사용자가 실행하는 `make install` backfill에서 소유권 검사에 따라 갱신됩니다.
이번 구현 자체가 실제 사용자 vault를 동기화하거나 기존 DB 위치를 옮기지는 않습니다.

표준 공유 지식 홈(`~/.loop-work/data`와 재사용 중인 기존 shared 홈)은 선택된 task·topic·
delegation·team·human-request·feedback·retirement 기록의 DB transaction이 commit된 뒤
자동 출력합니다. 임의의 별도 지식 홈이나 벤치마크/테스트용 임시 홈은 기본적으로 출력하지 않습니다.
Python API의 `KnowledgeBase(..., vault_home=ABS_PATH)`로 명시 선택하거나 `vault_home=False`로
끄며, `sync_vault()`는 모델 호출 없이 기존 기록과 task history를 다시 출력합니다.
설치 초기의 기존 DB backfill도 같은 출력 경계를 사용합니다. 출력 오류는 경고/진단으로
남기며 스킬 설치를 막거나 빈 DB·새 작업을 만들지 않습니다.
`vault_status()`와 지식 홈의 `vault-export-status.json`은 출력 오류·충돌을 보여 주는 진단이며
작업 완료/승인 판정이 아닙니다. 파일 소유권 pin은 지식 홈의 `vault-owned.json`에 보존합니다. 소유권 files pin·게시 예약(reservations)과 타깃별
`vault-export-initialized-<targethash>.json`도 지식 홈 백업에 포함하며, 이전에 내보낸 타깃의
manifest를 잃으면 새 경로·복사본으로 우회하지 않고 해당 문서 출력만 중단합니다.
작업 원본 SQLite/JSON 저장은 계속되며, 원래 소유권 자료를 복구하기 전에는 재출력을 성공으로 표시하지 않습니다.

보드의 표시·문서 데이터는 vault Markdown에서 읽습니다. SQLite·개발 상태 JSON은 실행·권한·
검증 상태의 원본이며, 누락된 문서를 DB 화면으로 몰래 대신하지 않습니다. Markdown 본문과
사람 노트는 읽기·편집 대상으로 보존하되, 파일명·상태 라벨·frontmatter 편집으로 목표·예산·승인·
게이트를 바꾸지 않습니다. 관리 manifest에 기록된 hash가 맞는 생성 파일만 갱신하며,
사람이 수정했거나 소유권이 없는 파일은 보존합니다. `.obsidian`과 `개인 메모/`·기존 사용자 메모도 덮어쓰지 않습니다.
출력 실패는 별도 전달 문제로 알리고 이미 저장한 원본 결과나 하네스 작업을 되돌리거나 막지 않습니다.

`$loop-work board` / `/loop-work board` 또는 설치된 Loop Work.app은 macOS에서 같은
Markdown의 작업 카드·상세·추적·사람 요청을 데스크톱 Tauri 2/React 창으로 엽니다. Rust bridge를 통한 내부 인증 API를 사용하며 외부 브라우저 기능은 제공하지 않습니다. `board start`는 backend만 준비하고, Linux는 하네스와 텍스트 CLI를 지원합니다.
기본 공유 홈은 `python3 scripts/loop.py board open`로 엽니다. 임의 별도 지식 홈은
`python3 scripts/loop.py --knowledge-home /absolute/knowledge board open --vault /absolute/vault`처럼
vault도 명시하며 다른 홈의 문서를 대신 선택하거나 자동 export를 켜지 않습니다.
문서 revision과 runtime 요청 revision이 맞지 않거나 메타데이터가 없으면 안전하지 않은 응답/실행을
막고 진단합니다. 응답·승인은 실제 사람의 원문으로만 기록하며 허용 resume 실행은 별도 명시 행동입니다.
실행이 commit된 뒤 문서 출력만 실패했다면 같은 실행을 재제출하지 않습니다.

보고서의 `.loop`·지식 홈·원본 소스 링크는 로컬 근거입니다. vault만 다른 컴퓨터에 보내면
해당 파일이 함께 전달되지 않으므로 이식 가능한 근거로 단정하지 않습니다. 실제 공유에는
요청 범위의 Markdown·필요한 근거 파일을 함께 전달하고 제외된 audit 링크를 구분합니다.

## 프로젝트 이동과 보존

같은 Git origin의 HTTPS·SSH 주소는 프로젝트 하나로 묶고 작업 트리는 구분합니다.
origin이 없는 Git worktree는 공통 Git 디렉터리, 일반 디렉터리는 로컬 파일시스템 식별자를 사용합니다.
같은 파일시스템에서 디렉터리 이름이 바뀌면 다시 연결해 위치를 갱신합니다. 원격 주소가 없는 복사본이나
파일시스템 간 이동은 기존 프로젝트임을 확인한 뒤 `--project`로 연결합니다.

새 지식 홈의 기본 위치는 `~/.loop-work/data/`이며 `LOOP_KB_HOME` 또는 전역 옵션
`--knowledge-home PATH`로 명시 선택하면 그 위치를 우선합니다. 기존
`~/.local/share/loop-work/` 또는 legacy `loop-dev` DB가 있으면 원래 위치를 재사용합니다.
여러 기본 후보 경로에 DB가 함께 있으면 원래 지식 홈을 명시하며, 기존 DB·실행 기록을 새 경로로 자동 이동하지 않습니다. 개발 상태는 각 저장소의 `.loop/state/`에 남습니다.
백업·이동에는 필요한 두 위치를 포함합니다. 자동 클라우드 동기화는 없습니다.
내부 기록도 금지한 요청은 기록 없이 처리하며, 자격 증명은 지식에 저장하지 않습니다.

## 프로젝트별 사람 편집 위키

보드는 vault의 생성된 실행 기록과 사람이 편집하는 위키를 구분합니다. 프로젝트·작업 위키는
검증된 current 기록을 내보낸 뒤 한 번 생성합니다. 처음에는 작성 시점과 당시 개요를 한국어로 표시하고 현재 진행 현황으로 연결합니다.
실제 원문·결과·검증 정보는 별도 실행 기록에서 읽습니다.
이후 exporter는 위키를 갱신하거나 삭제된 위키를 재생성하지 않습니다. 원래 영문 증거·코드·
사용자 원문은 번역하거나 다른 의미로 바꾸지 않습니다.

프로젝트 위키는 프로젝트 폴더의 `프로젝트 안내.md`, 작업 위키는 `진행 현황.md`와 같은
폴더의 `작업 문서.md`입니다. `vault-owned.json`의 별도 `wiki_documents`는 고정된
문서 연결과 최초 생성 소유권을 보존합니다. 생성된 실행 문서의 `files` pin을 위키 저장으로
갱신하지 않습니다. 소유하지 않은 파일과 충돌한 경로는 나중에 파일이 지워져도 자동 채택하지
않습니다. 기존 current가 수정·삭제되면 위키가 남아 있어도 실행 권한을 복구하지 않습니다.

웹 편집은 실제 Markdown을 즉시 저장합니다. 위키의 표시 이름과 최상위 H1을 함께 바꾸되,
기계 ID·고정 경로·프로젝트 identity·목표 제목·phase·QA·예산·승인 원문은 바꾸지 않습니다.
API의 `body_markdown`은 이 H1을 제외한 독립 본문입니다. Obsidian에서 H1이나 본문을 바꾸면
다음 조회가 실제 파일을 읽습니다. 생성된 실행 기록과 과거 snapshot은 이 편집 API의 대상이 아닙니다.

저장은 `operation_id`, `expected_revision`, `title`, `body_markdown`을 요구합니다.
같은 작업 ID와 같은 입력의 재시도는 기존 저장 receipt를 반환하며, 다른 입력으로 같은 ID를
재사용하거나 외부 수정으로 revision이 바뀌면 409 충돌로 거절합니다. 제목은 한 줄 200자,
본문은 UTF-8 520,192바이트 이내입니다. 제한을 맞추려고 원문을 자동으로 자르지 않습니다.

저장 중에는 no-follow 경로 검증과 배타적 게시를 사용하고 이전 파일을 같은 폴더의
`.loop-work-revisions/`에 보존합니다. 감지된 경합에서는 외부 파일을 덮어쓰지 않고 원본과
충돌 정보를 남깁니다. Obsidian처럼 하네스 lock에 참여하지 않는 외부 writer와 일반 파일시스템
전체에 완전한 비교·교체 원자성을 보장하지 않습니다. 충돌한 초안은 새 원문을 확인한 뒤
사람이 명시적으로 병합해야 합니다. 저장 receipt는 지식 홈의 `wiki-operations/`에 별도로 남습니다.

보드의 완료 열은 현재 완료 근거가 긍정적으로 확인된 경우만 사용합니다. 미응답 사람 요청,
pause, 오래되거나 없는 완료 근거는 사용자 확인 필요로 우선 분류하고 과거 completed 원문은
보존합니다. 기술 차단·abort는 별도 중단 열에 표시하며 분류만으로 실행 상태를 바꾸지 않습니다.

위키 최초 본문은 생성 당시의 시각과 한계를 표시한 스냅샷입니다. 빈 체크박스나
미작성 결과를 실제 지식처럼 채우지 않습니다. 목표 정의·완료 뒤의 실제 목표, 기준,
결과, 확인 근거와 산출물은 위키가 연결하는 별도의 실행 원본 문서에서 갱신됩니다.
사람 위키는 이 과정에서 수정·삭제 여부와 무관하게 재작성하거나 재생성하지 않습니다.

저장 제출본은 게시 전 별도 보존합니다. 게시 후 관측한 내용의 fingerprint가 제출본과
다르면 성공으로 응답하지 않고 409 충돌을 반환하며, 외부 현재 원문·이전 원문·제출본을
복구 가능한 파일로 남깁니다. 외부 편집기와의 완전한 파일시스템 트랜잭션을 보장하지는 않습니다.

## 일반 입력의 작업 없는 프로젝트 기억

일반 프롬프트를 하네스 작업으로 만들 필요는 없습니다. 현재·미래의 명시 작업에 관련된 사실이나
사용자 결정만 기존 `knowledge remember`로 프로젝트 topic에 남깁니다. 모든 입력을 자동 저장하거나
대화 원문을 통째로 내보내지 않습니다. 기록 금지와 비밀정보 제한을 지킵니다.

```sh
python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" knowledge context --path "$PROJECT_ROOT"
python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" knowledge remember --path "$PROJECT_ROOT" --observed REVISION --input /temporary/project-memory.json
```

입력은 기존 topic 형식을 사용합니다. `scope: "project"`, 실제 출처의 `evidence`와 결정의
`basis`/`applies_to`를 보존합니다. `--task`는 생략해 `source_task_id`를 null로 유지합니다.
동일 대화의 이미 확인된 session만 `--session`으로 전달하며, ID가 없으면 생략합니다.
최신 기록을 골라 대화 ID를 추측하거나 새 session을 만들지 않습니다. reference-only 출처를
직접 읽은 원문처럼 기록하지 않습니다. 작성 요약은 한국어로, 실제 사용자 문장과 코드·출처는 그대로 둡니다.

이 기억 저장 자체는 topic 문서만 내보내며 새 task·활성화·실행 호출·추가 권한을 만들지 않습니다.
이미 명시한 작업에 대한 관련 정정은 일반 문장이어도 기존 feedback/control 규칙으로 같은 작업을
이어가며 소진한 예산을 유지합니다. 무관한 일반 요청의 기억 저장과 이 경로를 혼동하지 않습니다.
나중의 명시 작업은 해당 topic ID/revision과 원래 출처를 선택해 읽습니다. 원래 소유권·판단 범위를
작업으로 이동하거나 읽기만으로 최신성·사용자 승인·완료를 부여하지 않습니다.
Board에는 `--explicit-skill`로 실제 명시 호출 출처가 기록된 작업만 표시합니다.
저수준·과거 작업은 숨겨져도 KB/vault에서 삭제되거나 출처가 재작성되지 않습니다.

정보만 있는 프로젝트의 Board 위키는 실제 project index Markdown이 있을 때만 표시합니다.
topic 문서만 저장되었고 index가 없으면 해당 기억은 Obsidian에서 읽으며 Board 프로젝트 항목은
없을 수 있습니다. DB 정보로 누락된 문서를 대체하지 않습니다. 모든 Board 범위의 출력 진단은
식별자 없는 집계이며, CLI/KB의 상세 export 진단은 변경하지 않습니다.


macOS 설치는 사용자 `~/Applications/Loop Work.app` 또는 TARGET `.loop/Loop Work.app`도
준비합니다. 앱 창과 Obsidian은 같은 vault Markdown을 읽으며 새 DB나 숨은 작업 목록을 만들지
않습니다. 창 닫기/재열기는 문서 추적의 수명주기일 뿐 명시 작업 출처·승인·예산을 바꾸지 않습니다.
앱 종료 시 미저장·충돌·응답 미확인 초안을 보호합니다. 원문과 한국어 위키·지식 경로 및
삭제/외부 수정 보존 정책은 네이티브 화면에서도 동일합니다.

강제 종료나 WebContent 프로세스 종료 뒤 저장 전 메모리 초안을 복구하는 기능은 지원하지 않습니다.
이미 CAS로 저장이 확인된 Markdown은 디스크에 보존되며, 앱 crash 시 backend EOF 정리와 초안 복구는 별개의 보장입니다.
