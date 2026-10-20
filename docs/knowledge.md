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
`work open` 또는 개발 `init`로 생성한 작업·세션을
`harness on --provider codex --session SESSION_ID --task TASK_ID`로 결속합니다.
진행 중 관련 정정·상태 확인·맥락 압축은 같은 작업이며 무관한 일반 입력은 자동 처리하지 않습니다.
완료·abort는 결속을 해제하고 작업·지식·예산을 보존합니다. pause/blocker는 완료가 아닙니다.
`harness off SESSION_ID`는 호환 해제 명령이고 최신 세션을 임의 선택하지 않습니다.
`orchestration context SESSION_ID --task TASK_ID`로 해당 작업만 복원합니다.
구형 conversation-wide enabled 상태만으로 새 입력을 자동 처리하지 않습니다.

## 비개발 작업

```sh
python3 .loop/loop.py work open --kind explanation --title "저장 방식 설명" --provider codex --path /project --session SESSION_ID
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
| 새 `projects/<project.name--ID>/tasks/<task.title--ID>/현재-<title--ID>.md` | 파일명으로 내용을 구분하는 마지막 출력 |
| 같은 작업의 한국어 단계·제목·digest snapshot | 미완료·차단·완료의 각 cutoff 기록 |
| 프로젝트의 `topics/` 및 `topics/global/` | 프로젝트 범위 주제와 전역 주제를 구분하는 설명형 문서 |
| 한국어 프로젝트·주제·작업 색인 | 새 파일과 기존 관리 파일로 이동하는 링크 |
| `notes/` | 사람 메모; 승인·작업 지시로 자동 반영하지 않음 |

기존 `projects/<project-id>/tasks/<task-id>/current.md`, `interim/`, `final/`, `topics/<id>.md`
관리 경로는 이동·삭제하지 않습니다. 편집 충돌이나 생성 파일 삭제도 기존 경로에서 보존하며
새 복사본을 만들어 우회하지 않습니다. 한국어 색인은 그 파일들을 연결합니다.
새 경로는 표시 이름과 안정 ID를 함께 쓰며 최초 mapping을 고정해 제목 변경으로 매번 rename하지 않습니다.
같은 origin의 project ID·원본 scope/session/task identity는 표시 이름과 별개로 유지합니다.
소유권 manifest의 외부 version 1은 유지하며 새 layout 2 mapping과 문서 role 정보를 추가합니다.

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
사람이 수정했거나 소유권이 없는 파일은 보존합니다. `.obsidian`과 `notes/`도 덮어쓰지 않습니다.
출력 실패는 별도 전달 문제로 알리고 이미 저장한 원본 결과나 하네스 작업을 되돌리거나 막지 않습니다.

`$loop-work board serve` / `/loop-work board serve`는 같은 Markdown의 작업 카드·상세·추적·
사람 요청 화면을 localhost에서 열고 기본 브라우저를 실행합니다. `--no-open`이면 서버만 엽니다.
기본 공유 홈은 `python3 scripts/loop.py board serve`로 엽니다. 임의 별도 지식 홈은
`python3 scripts/loop.py --knowledge-home /absolute/knowledge board serve --vault /absolute/vault`처럼
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
