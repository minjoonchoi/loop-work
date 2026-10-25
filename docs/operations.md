# 개발 운영과 검증

이 문서는 개발 게이트와 장애 복구를 다룹니다. 문서·설명·조사·계획의 수행과 공통 지식은
[공통 작업과 지식 운영](knowledge.md)을 따릅니다. 비개발 작업에 두 CLI나 개발 루프를 요구하지 않습니다.

## 작업 시작과 해제

스킬과 작업 내용을 함께 명시하면 한 작업을 목표 설정 → 작업으로 수행합니다.
에이전트는 task/session 생성 후 `harness on --provider PROVIDER --task TASK_ID`로 결속합니다.
관련 정정·진행 질문만 같은 작업을 이어가고 완료·abort 시 자동 결속을 해제합니다.
무관한 일반 입력은 자동 적용하지 않습니다. bare 스킬은 내용만 한 번 묻고 상태를 만들지 않습니다.
pause/blocker는 기록·예산을 보존하며 진행 확인만으로 재개하지 않습니다.
`off`는 기존 바인딩의 호환 해제이며 세션·작업을 새로 만들지 않습니다.
이전 conversation-wide 활성 기록만으로 입력을 포획하지 않으며 최신 세션을 추측하지 않습니다.

스킬 등록 방식은 2026-10-13에 확인한 [Codex 공식 문서](https://learn.chatgpt.com/docs/build-skills)와
[Claude Code 공식 문서](https://code.claude.com/docs/en/skills)를 따릅니다.
Codex는 `.agents/skills/loop-work/agents/openai.yaml`의 `allow_implicit_invocation: false`,
Claude는 `.claude/skills/loop-work/SKILL.md`의 `disable-model-invocation: true`를 사용합니다.
공통 본문은 `skills/loop-work/SKILL.md` 한 곳에서 관리하고 설치 때 환경별 어댑터를 생성합니다.
`make install`은 `scripts/install.py --link --workspace`로 실행됩니다. 사용자 요청에 따라
Obsidian 존재를 확인하고 없으면 기존 Homebrew를 사용해 설치하며, `~/.loop-work/vault`와
그 `.obsidian` 폴더를 준비합니다. macOS에서는 프로젝트 로컬 Tauri 2/Rust 빌드로 `Loop Work.app`을 컴파일해
사용자 `~/Applications/Loop Work.app` 또는 TARGET의 `.loop/Loop Work.app`에 설치합니다.
기존 비소유·수정·심링크 앱 bundle은 덮어쓰지 않습니다. 필요한 Rust·Node 빌드 도구가 없으면 명확히 실패하고
전역 toolchain을 자동 설치하지 않습니다. GUI의 npm/cargo 의존성은 프로젝트 로컬로 설치·빌드하며
Python backend에 패키지 의존성을 추가하지 않습니다. Python 표준 라이브러리 backend는 macOS/Linux에서 유지하고
네이티브 전면은 macOS 전용입니다. 기존 vault·앱 설정·사용자 노트는 덮어쓰지 않고 Obsidian의
전역 vault 등록·동기화·플러그인은 설정하지 않습니다. 이 설치 단계 외 하네스 런타임은
Python 표준 라이브러리로 실행하고 저수준 설치/벤치마크가 brew를 호출하지 않습니다.

기존 앱이나 `obsidian` 실행 파일이 확인되면 앱 설치를 건너뜁니다. 앱이 없을 때 자동 설치는
기존 Homebrew를 사용합니다. OS 이름만으로 설치 가능 여부를 단정하지 않고, brew 실행 결과와
설치 후 앱 확인으로 판정합니다. Homebrew 부재·brew 실패·설치 후
앱 확인 실패는 원인을 보고하며 성공으로 표시하지 않습니다. Homebrew 자체를 자동 설치하지 않습니다.
앱에서는 `~/.loop-work/vault` 폴더를 직접 열면 됩니다. vault export가 실패해도 원본 작업과 DB를
실패/미완료로 되돌리지는 않으며 원인을 별도로 확인합니다.

신규 공유 DB는 `~/.loop-work/data`를 쓰고 기존 shared DB는 자동 이동 없이 재사용합니다.
표준 공유 홈의 DB commit 뒤 결과 문서를 vault에 출력하며, 임의 별도/임시 지식 홈은 기본
출력이 꺼져 있습니다. 출력 충돌은 지식 홈의 `vault-export-status.json`에서 확인합니다.
설치 초기에도 기존 선택 DB가 있으면 records/history를 backfill하며, 빈 DB나 새 세션·목표를
만들기 위해 초기화를 강제하지 않습니다. 사람이 수정한 생성 Markdown이나 출력 오류는 파일을
보존하고 경고·출력 상태로 표시하되 그 이유만으로 스킬 설치/갱신을 막지 않습니다. 앱 설치나
안전 경로 충돌 실패와 문서 출력 미완료를 구분합니다. 원본 DB가 정상인데 사람이 수정한
Markdown이 보호된 경우, 해당 노트를 덮거나 DB 완료 상태를 바꾸지 말고 문서 전달 문제로 다룹니다. Python API `sync_vault()`는 기존 기록/history의
뷰만 다시 만들며 새 모델 호출·근거 검증·승인·완료 판정을 하지 않습니다.

설치는 사용자 스킬 경로를 `~/.local/share/loop-work/install`에 연결합니다.
프로젝트 범위는 `make TARGET=/absolute/project install`이며 `.loop/install`을 사용합니다.
런타임/규칙은 원본 저장소를 참조합니다. 원본 이동 뒤에는 새 위치에서 재설치해 연결합니다.
재설치 전에는 기존 경로를 사용할 수 없습니다. 본문/메타데이터 변경 뒤에도 재설치합니다. 해제는 같은 범위에서 `make uninstall`입니다.
기존 `python3 scripts/install.py --target PATH` 복사 설치는 독립/봉인 환경에 남겨 둡니다.
`make uninstall`과 연결 설치 전환은 기존 복사 설치를 제거하지 않습니다. 설치/해제는 반복
실행 가능하며 충돌은 변경 전에 거절합니다. 해제 뒤에도 목표·상태·지식 기록과 Obsidian 앱·vault는 보존됩니다.
설치/갱신/해제 뒤에는 새 대화 또는 호스트의 스킬 새로고침/재시작 절차를 사용합니다.
해제는 현재 대화에 로드된 지침을 지우지 않습니다. 진입 파일이 없으면 자동 처리를 중단하고
알리며, 다른 경로로 우회하거나 새 세션을 만들지 않습니다.

## 첫 실행

1. 작업 CLI가 로컬 터미널에서 설치·로그인되어 있는지 확인합니다. 반대 CLI가 설치돼 있으면
   교차 검토하고, 없으면 같은 제공자의 새 독립 호출로 검토합니다.
2. 대상 저장소에 하네스를 설치하고 Claude Code 또는 Codex를 엽니다.
3. Claude Code는 `/loop-work <작업 내용>`, Codex는 `$loop-work <작업 내용>`으로 한 작업을 시작합니다.
   관련 정정·상태 확인은 같은 작업을 이어가며 완료·abort 시 결속을 해제합니다.
   무관한 일반 요청에는 자동 적용하지 않고, 새 작업에는 스킬과 작업 내용을 다시 명시합니다.
4. 에이전트가 `execution.routing`에 작업자·검토자의 명시적 모델·effort 풀을 구성하고
   읽기 전용 분석을 `delegate`로 실행해 작업 CLI도 확인합니다. `orchestrator`는 대화 환경,
   `implementer`는 작업 CLI입니다. 중첩 호출 제한이 있으면 우회하지 않고 시작 전에 사용할
   작업 도구를 정합니다. 하네스의 수정안 적용·테스트에 필요한 권한과 외부 환경도 준비합니다.
5. `doctor`는 설치·버전만 확인합니다. `plan-review`는 첫 제공자 선택을 기록하고 실제 호출로
   인증·필요한 플래그·읽기 도구·구조화 결과를 확인합니다. 같은 목표의 선택은 고정되며
   선택한 CLI의 인증·권한·실행 실패로 다른 제공자를 재시도하지 않습니다.

사용자가 조사·질문·검토·재시도 절차를 프롬프트로 설명할 필요는 없습니다. 에이전트가
저장된 규칙과 맥락으로 수행합니다. 명시한 작업을 진행하는 동안에는 별도 운영 프롬프트가 필요 없습니다.
개발을 요청하지 않은 설명·질문·읽기 전용 검토·계획 전용 요청에는 개발 실행을 만들지 않습니다.

실제 사용자의 인증을 대신하거나 임의로 API 키를 생성하지 않습니다. CLI 기존 인증과
설정을 사용하며, 사용자·조직의 권한 제한을 우회하지 않습니다. 이미 설정된 훅은 실행될
수 있으므로 사전 단계에서 입력 대기 여부를 확인합니다. 실행 중 외부 프로세스가 입력을
기다리더라도 명령의 stdin은 EOF이고 시간 제한이 적용됩니다.

## 작업·검토 어댑터

Codex는 `exec`, `--output-schema`, `--output-last-message`, `--ephemeral`을 사용합니다.
승인 정책은 `never`, 샌드박스는 `read-only`입니다. 사용자에게 승인 프롬프트를 띄워
기다리는 방식으로 작업하거나 검토하지 않습니다. 일반 디렉터리 작업에는 `--skip-git-repo-check`를 추가합니다.

Claude는 print 모드와 `--output-format json`, `--json-schema`를 사용하며
`structured_output`을 검증합니다. `dontAsk`와 읽기 도구 목록을 지정하고 별도 MCP 없이
호출합니다. 기존 권한에서 거절된 동작은 우회하지 않고 실패로 기록합니다.

목표 설정 때 사용할 모델·effort 풀을 준비하고 고정합니다. `LOOP_ROUTING_PROFILE`로 가져올
수 있으며 실제 선택은 [라우팅 규칙](../rules/routing.md)의 작업 수요와 비용 순위를 따릅니다.
모든 호출에 모델·effort를 명시하고 CLI 기본값으로 대체하지 않습니다. 검토자는 preflight에서
반대 CLI가 설치되어 있으면 해당 공급자를, 없으면 worker 공급자의 fresh 호출을 선택하고
그 선택을 목표에 고정·기록합니다. 선택된 CLI의 인증·권한·실행 실패로 공급자를 바꾸지 않습니다.

작업 도구는 수정안을 구조화 후보로 반환하며 파일을 직접 쓰지 않습니다. 메인이 목표와
완료 조건의 근거를 확인해 `assess`로 채택한 뒤 하네스가 허용 경로·해시·피드백을 재확인해
적용합니다. 폐기한 후보는 다음 작업의 사실로 전달하지 않습니다. worker-output 품질 실패는
같은 위임을 더 높은 허용 프로필로 재실행합니다. V2 입력·fixture 수리는 연결된 standalone
revision으로 같은 프로필을 유지하며 누적 시도·예산을 보존합니다(팀은 revision 1 한정).
내부 절차이므로 사용자 확인을 추가하지 않습니다.
위임 필드와 복구는 [위임 규칙](../rules/delegation.md)을 따릅니다.

공식 연동 문서(2026-10-13 확인):

- [Codex 비대화형 실행](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Codex CLI 명령](https://learn.chatgpt.com/docs/cli/reference)
- [Claude Code 프로그램 실행](https://code.claude.com/docs/en/headless)
- [Claude Code CLI 참조](https://code.claude.com/docs/en/cli-reference)

## 장애 처리

| 상황 | 처리 |
| --- | --- |
| 사전 질문/결정 미완성 | 구현하지 않고 사전 단계에서 구체화 |
| 테스트 실패/검토 지적 | 로그와 근거를 읽고 구현 수정, 같은 게이트 재시도 |
| CLI 미설치/로그인 오류 | 시작 전에는 준비를 완료, 실행 중에는 blocked와 원인 기록 |
| 검토 형식 오류/타임아웃 | 통과 처리하지 않고 blocked; 한도 내 복구 후 resume |
| 검토 또는 검증 중 입력 파일 변경 | 결과 무효화, 변경 원인을 확인한 뒤 다시 검증 |
| 목표/규칙/엔진 변경 | non-retryable blocked; 임의로 기준을 바꾸지 않음 |
| 실행 중 새로운 업무 결정 필요 | 질문을 기다리지 않고 근거·미완료 범위·재개 조건 기록 |
| 재시도/전체 시간 한도 초과 | 완료로 표시하지 않고 blocked, 동일 목표를 무한 반복하지 않음 |
| 세션 맥락 유실 | 같은 환경에서 context 명령의 파일을 읽고 이어감 |

전체 시간 한도는 게이트와 위임 진입, 외부 명령 실행 시 확인합니다. 대화가 다음 지시를
준비하는 동안 별도 감시 프로세스가 동작하지는 않습니다. 위임의 실패·차단 결과는 대화가
검토해 기존 권한 안에서 후속 작업을 정하고, 해결할 수 없으면 부모 목표를 `block`합니다.

재시도 가능한 장애는 기존 권한 내에서 에이전트가 고치고 `resume`합니다. 목표나 허용 범위가
달라져야 한다면 원래 실행을 성공으로 마감하지 않습니다. 기존 목표를 중단하고 새로운
목표의 사전 질문·검토부터 진행합니다. 같은 폴더에서 복수 목표를 동시에 실행하지 않습니다.

## 중단 후 재개

진행 중 같은 작업의 관련 요청은 `harness status`와 그 작업 기록을 먼저 읽습니다. 작업 생성·결속 결과의
`task_id`·`session_id`·`knowledge_home`·`rules_home`·`entrypoint`를 맥락 압축 때도 유지하고, 첫 목표부터 `--session`으로 연결합니다.
폴더를 옮겨도 원래 실행 파일의 절대 경로를 사용합니다. 목표 완료는 작업 결속을 해제합니다. 이후 무관한 요청은 자동 처리하지 않습니다. 사용자가 ID를
입력하거나 “이전 분석을 재사용해 줘”라고 요청할 필요가 없습니다. `session context`에서
`reusable`은 유효한 주제 요약, `stale`은 변경된 근거와 재확인할 주제,
`goal_history`는 과거 결정·구현 진행·노트입니다. 과거 목표의 답변은 원래 범위에서 재사용합니다.

조사·답변·구현 변경 직후 에이전트가 `session remember`로 관련 주제를 갱신합니다.
템플릿은 `analysis.example.json`, `decision.example.json`이며, 입력 파일도 `.loop/state/`에
둡니다. 분석하기 전 읽은 `revision`을 `--observed`에 전달하므로 조사 도중 코드가 바뀌면
덮어쓰지 않고 변경 내용을 먼저 확인합니다. 코드 변경 없이 반복 조회하면 원래 분석을 유지합니다.

| 상황 | 세션 분석 처리 |
| --- | --- |
| 같은 세션에서 새 목표 시작 | 기존 분석을 읽고 새 목표와의 차이만 진단 |
| 관련 파일 수정·추가·삭제·이름 변경 | 의존하는 주제만 재확인 대상으로 표시 |
| 규칙 또는 브랜치 변경 | 전체 주제의 적용 가능성을 다시 확인 |
| 코드 내용이 같은 새 커밋 | 분석 재사용; 완료 검증 증거는 기존 정책대로 만료 |
| 같은 질문이 다시 필요해 보임 | 원래 답변과 적용 범위를 먼저 확인; 새 결정만 질문 |
| 서로 다른 Claude/Codex 대화 | 별도 세션; 프로젝트 지식은 공유하되 다른 세션의 답변·권한은 선택하지 않음 |

기존 목표의 세션 연결이 없는 이전 버전 상태는 첫 맥락 조회에서 새 ID를 한 번 배정합니다.
이미 실행 중이거나 동결된 목표에는 설치 업데이트를 적용할 수 없습니다. 해당 실행을
기존 버전으로 마치거나 종료한 뒤 설치 스크립트로 업데이트합니다.

```sh
python3 "ENTRYPOINT" --knowledge-home "KNOWLEDGE_HOME" context my-goal
```

반환된 `context` 파일의 `state`, `next`, `latest_gate`, `notes`를 읽습니다. 구현 중 세션이
끝났다면 다음 작업을 이어가고, 게이트 실행 중 종료됐다면 잔여 프로세스와 로그를 확인합니다.
작업 위임이 `running` 또는 `interrupted`에 남았다면 원본·적용 파일·잔여 프로세스를 먼저
확인한 뒤 같은 입력에 `--recover REASON`을 붙여 재시도합니다. 중단 복구는 범위 변경이나
예산 초기화를 허용하지 않습니다.
기록에 `inflight`가 남아 있으면 해당 게이트를 호출했을 때 중단 상태를 감지합니다. 이후
`resume`하여 재검증합니다. 이미 소비한 시도 횟수와 시간 한도는 유지합니다.

상태·로그를 삭제해서 시도 횟수를 초기화하거나 성공 이력을 만들지 않습니다. 외부에서
강제 종료한 프로세스는 자식 프로세스가 남았는지 먼저 확인합니다. 정상 시간 초과·사용자
인터럽트는 엔진이 프로세스 그룹을 종료합니다.

## 완료와 전달

`finish`는 개발 검증 완료를 기록합니다. 커밋·PR·병합·배포는 자동 엔진 부작용에 포함되지
않습니다. 사전 합의된 전달 수준에 맞춰 대화가 별도의 명시적인 도구 호출로 위임하고 실제 결과를 보고합니다.
커밋을 만들 예정이라면 최종 finish 전에 만듭니다. 완료 뒤 코드나 HEAD를 바꾸면 기존 완료
기록의 `evidence_current`는 false가 됩니다.

## 이 저장소의 검증 범위

[개발 규칙](../rules/workflow.md#4-execute-the-entire-loop-without-further-user-questions)의
`check_failure_policy`는 신규 `fail_fast`/선택 `diagnostic_continue`이며 기존 누락은 continue입니다.
`not_run_checks`는 미실행이고 최종 fresh 전체검사·독립 검토를 대신하지 않습니다.
관련 GUI handoff의 default argv·source 밖 fixture·설치 후 근거·feature/cache와 ENOSPC 진단은
[위임 규칙](../rules/delegation.md#prepare-one-assignment)을 따릅니다. 긴 native 실행은 관측된
마지막 완료 단계와 timeout/증거종류를 알리고, 무변화 대기는 [진행 기록](../rules/writing.md#progress-and-interim-deliverables)대로 설명합니다.


`verify_tauri_native.py`는 `preflight.json`에 write probe·capacity 관측을 남기고,
`progress.json`에는 최대 64개 시작/종료 event와 current_stage/last_completed_stage/last_native_stage를 둡니다.
임의 공간 threshold나 cache 삭제·이동은 하지 않습니다. `run-failure.json`은
timeout/interrupted/storage_enospc와 마지막 단계를 보존합니다. 증거는
`shipping_native_lifecycle` / `test_only_native_webview_actual_api`로 구분하며 composition은
`synthetic_events`, `physical_gui_input_verified=false`로 한정합니다.

```sh
python3 -m unittest discover -s tests -v
git diff --check
```

표준 라이브러리만으로 테스트합니다. 임시 저장소와 가짜 실행 파일을 사용하여 실제
서브프로세스 생성, 인자 전달, JSON 처리, 실패·시간 초과·재시도·재개, 상태 전이와 설치를
검증합니다. 두 실제 CLI의 로그인된 모델 호출이나 AI 검토의 품질을 검증한 테스트는 아닙니다.
CI는 Linux/macOS와 Python 3.10/3.12 조합으로 같은 테스트를 실행합니다.
Python unittest discovery는 Cargo가 PATH에 있다는 이유만으로 GUI를 빌드하지 않습니다. 실제 native
Rust 검사는 준비된 macOS의 별도 명시 gate에서 실행합니다. 캐시·toolchain이 준비된 개발자가
unittest 안에서도 같은 검사를 실행하려면 `LOOP_NATIVE_TESTS=1 python3 -m unittest discover -s tests -p test_desktop_native.py -v`
를 사용합니다. 이 opt-in은 `--locked --offline` 실패를 숨기거나 의존성을 다운로드하지 않습니다.
Linux Python suite는 opt-in과 Cargo가 있어도 native 빌드를 호출하지 않습니다. 해당 플랫폼의
실제 실행 근거와 플랫폼 분기를 mock한 단위 회귀는 구분해 보고합니다.

로그와 프롬프트에는 프로젝트 맥락이 포함될 수 있습니다. `.loop/state/`는 Git에서
제외됩니다. 이를 첨부하거나 다른 컴퓨터로 옮길 때는 필요한 범위만 의도적으로 전달합니다.

## 명시적으로 고정한 runtime 사본

연결 설치는 원본 checkout의 runtime·규칙을 참조하므로 원본 수정이 다른 프로젝트의
진행 중 실행을 stale 상태로 만들 수 있습니다. 새 장기 실행을 시작하거나 live-linked
runtime이 바뀔 수 있다면 preflight 전에 snapshot의 명시적 선택을 검토합니다.
별도 사본이 필요한 새 실행은 아래 명령으로 현재 실행 소스만 새 절대 디렉터리에
복사할 수 있습니다. 도구가 추가됐다고 자동으로 선택되거나 기존 바인딩이 바뀌지는 않습니다.

```sh
python3 scripts/runtime.py snapshot --destination /absolute/new-runtime
# 기존 목표의 engine pin과 정확히 같은 소스일 때만 복사하려면:
python3 scripts/runtime.py snapshot --destination /absolute/new-runtime --expect-digest ENGINE_DIGEST
```

상위 디렉터리는 미리 존재하는 실제 경로여야 하며 symlink 경로와 기존 destination은
거절합니다. 원본·사본의 내용과 실행 비트, 원본 전후 안정성, 새 Python 프로세스에서
계산한 engine digest를 확인하고 `runtime-manifest.json`과 절대 `entrypoint`·`rules_home`을
반환합니다. engine digest는 package Python·기본 Markdown 규칙·canonical skill 본문과
메타데이터를 봉인합니다. templates와 진입 스크립트는 별도 파일 pin으로 보존합니다.
설정·인증·프로젝트·목표·state·지식 DB는 복사하지 않습니다.

선택한 절대 `entrypoint`·`rules_home`·engine digest를 동일한 `session_id`·
`knowledge_home`과 함께 보존합니다. 새 실행에서도 어떤 runtime을 선택했는지 명시합니다.

반환된 사본은 이후 원본 변경과 분리됩니다. 설치나 기존 세션의 runtime을 자동 전환하지
않으며 동결된 목표의 seal도 바꾸지 않습니다. 현재 소스가 기존 engine pin과 다르면
`--expect-digest`는 실패하므로, 이미 변경된 소스를 과거 버전처럼 복구해 주는 기능이
아닙니다. 기존 실행의 runtime 선택은 보존하고 새 실행의 명시적 진입점으로 사용합니다.
출판 중 실패로 destination이 남으면 검증된 사본으로 사용하지 말고 확인용으로 보존합니다.

## Typed block and retirement

`block --reason` / `work block --reason`는 더 이상 공개 입력이 아닙니다. 다음 JSON을
파일로 저장해 `python3 scripts/loop.py block GOAL --input BLOCK_JSON` 또는
`python3 scripts/loop.py work block TASK --input BLOCK_JSON`에 전달합니다.
`abort --reason`은 그대로 유지됩니다.

```json
{
  "version": 1,
  "kind": "external",
  "reason": "Required service remains unavailable; pinned diagnostic records the failure.",
  "scope": "task",
  "retryable": true,
  "evidence": [{"ref": "/absolute/diagnostic.txt", "sha256": "MODE_AWARE_FILE_PIN"}]
}
```

`sha256`는 raw content SHA가 아니라 `loop_work.storage.file_hash`의 기존 mode-aware
file pin입니다. worker packet에 설명된 pin 형식을 그대로 사용합니다.
근거는 canonical absolute 실제 파일이어야 합니다. `user_pause`는 기록된 명시적 사용자
pause와 `retryable: true`가 필요합니다. `budget_exhausted`는 실제 전체 호출·시간 또는
미통과 gate 한도 소진을 확인하며 `retryable: false`여야 합니다. 한 assignment의 3회
실패만으로 전체 작업 예산 소진을 선언할 수 없습니다. 입력 검사는 분류·pin·예산의
정합성을 검증하며 문장의 진실을 자동 판정하지 않습니다. 호스트 hook/daemon이나
자동 재개를 보장하지 않으며 명시적 pause/stop은 계속 존중합니다.

거절·차단·실패한 단위를 승인된 대체 작업으로 퇴역하려면 다음 입력을
`retire GOAL --input RETIRE_JSON` 또는 `work retire TASK --input RETIRE_JSON`에 전달합니다.

```json
{
  "version": 1,
  "assignment_id": "old-unit",
  "reason": "Accepted split units now cover the original obligation.",
  "replacements": ["accepted-unit"],
  "coverage": {
    "assignment:old-criterion": ["accepted-unit"],
    "goal:goal-criterion": ["accepted-unit"]
  },
  "evidence": [{"ref": "/absolute/current-proof.txt", "sha256": "MODE_AWARE_FILE_PIN"}]
}
```

coverage에는 원 단위의 모든 criterion 및 연결된 goal criterion을 넣습니다. 대체 단위는
같은 task의 승인된 `done`이어야 하며 goal 매핑은 해당 goal에 기여하는 단위를 가리켜야
합니다. 결과·평가 receipt와 현재 기여·평가 근거 pin을 검증합니다. 다른 파일을 편집한
정상 consumer 때문에 producer의 과거 전체 checkout digest만 달라진 것은 거절하지
않습니다. 자기 참조·순환·미승인·오래된 근거는 허용하지 않습니다. 원래 실패 상태와
누적 시도는 그대로 남습니다. 근거가 바뀌면 완료 barrier가 복원되며, 갱신한 근거로
같은 공개 명령을 다시 호출하면 이전 receipt hash를 보존한 새 receipt를 추가합니다.
최신 실질 feedback을 승인된 worker가 소비하는 조건과 fresh final gate는 별도 필수입니다.

## Assignment v2 and bounded repair

기존 unversioned v1 계약은 유지합니다. V2는 `schema_version: 2`, `work_unit_id`(id와
동일), `request_revision`, `previous_request_hash`, `correction_ledger`를 요구합니다.
첫 revision의 이전 hash는 null입니다. standalone은 직전 pinned 거절 평가가
`assignment_input`/`orchestrator_fixture`와 `repair_contract_same_profile`을 지정한
경우에만 연속 revision을 허용합니다. 팀은 현재 revision 1만 지원합니다. 동일 work unit의
attempt/history/budget을 공유합니다. 같은 ID의 revision은 cap을 보존하고, 정규화된
정확히 동일한 기여를 다른 이름으로 제출하는 경우를 탐지합니다. 의미가 같은 모든
paraphrase를 탐지한다고 보장하지 않습니다. 기준·부모
기여·금지 사항·수요를 낮추는 revision은 허용하지 않습니다. 수요를 높이는 수리는 유지된
frozen profile이 새 요구를 충족할 때만 실행하며, 미충족이면 호출을 소비하지 않고 차단합니다.

V2 criterion은 `id`, `description`, `execution_owner`, `verification_mode`를 갖습니다.
현재 portable read-only worker의 사용 가능한 조합은 worker/source_inspection 또는
orchestrator/orchestrator_receipt입니다. `candidate_test`는 예약된 이름이지만 현재 모든
worker kind에서 실행 전 거절합니다. orchestrator 소유 항목은 worker 출력에서
`satisfied: null`로 남기고, 승인 시에는 모든 criterion에 true와 외부 pinned 근거가 필요합니다.

평가는 worker-output 품질 실패와 입력·fixture 수리를 구분합니다. 전자는 가능한 더 강한
profile, 후자는 같은 profile의 연결된 revision을 사용합니다. provider 실행·stale evidence를
실제 내용 후보의 품질 거절로 위장할 수 없습니다. 응답의 `assignment.retry`에 있는
`can_retry_same_profile`, `can_escalate`, `attempts_remaining`, `calls_remaining`,
`time_remaining`, `stop_reason`, `next_profile`, `requires_recovery`를 확인합니다. 단위 cap이나
profile ceiling은 전체 task 중단 근거가 아닙니다. 설정·권한 복구는 기존 권한 안에서만 합니다.

`correction_ledger` 항목은 id/criterion_id/origin/expected/observed/source_ref/source_hash/
validation_owner/resolution_status/supersedes를 보존합니다. 이전 행을 삭제·수정하지 말고
같은 criterion의 새 행으로 supersede합니다. refs는 읽기 권한이나 거절된 본문의 재사용
권한이 아닙니다. API·버전·digest 같은 정확한 문자열을 요약 중 변형하지 않습니다.

V2 결과는 기존 전체 write/delete 외에 다음 exact-base patch를 선택할 수 있습니다.

```json
{"path":"docs/result.md","operation":"patch","base_hash":"BASE_MODE_AWARE_PIN","result_hash":"RESULT_MODE_AWARE_PIN","edits":[{"start":0,"end":3,"content":"new"}]}
```

patch는 dispatch 당시 존재한 base 파일에만 적용합니다. 새 파일은 `write`를 사용합니다.
start/end는 UTF-8 byte offset이며 문자 경계·비중첩·base/result pin을 검증한 뒤 기존
적용 경로로 변환합니다. raw patch receipt는 보존됩니다. 파일별 atomic replace이며
여러 파일의 crash-atomic transaction을 보장하지 않습니다. review routing은 관련 작업의
high complexity/risk/uncertainty를 보존합니다. 파일 수·언어 metadata는 관측 정보이며
비용 최적화나 품질 개선 실증으로 해석하지 않습니다.

## 보드 열기와 문서 추적

macOS에서는 Finder의 Loop Work.app 또는 Codex `$loop-work board`, Claude Code
`/loop-work board`를 사용합니다. `board`만 적으면 `open`으로 처리하며 기존 진입점·지식 홈·
session/task를 유지합니다. off 상태를 켜거나 새 목표·세션을 만들지 않습니다. `open`은 macOS Tauri 2/React 창을 열며 번들 React 화면과 내부 인증 API를 사용합니다. `start`는 앱이나 브라우저 없이 backend만 준비합니다. Linux는 하네스와 텍스트 CLI를 지원하며 데스크톱 앱은 지원하지 않습니다.
요청한 로컬 앱 열기에 다시 승인을 묻지 않습니다.

```sh
python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" board open --session "$SESSION_ID" --port 0
# 선택된 작업만: --task "$TASK_ID"
# 임의 별도 KB: 같은 명령에 --vault /absolute/vault 명시
```

앱 시작 실패와 서버 실패를 구분하고 열린 창을 확인하지 못했으면 성공으로 보고하지 않습니다.
임의로 브라우저로 전환하거나 이미 실행한 서버를 중복 시작하지 않습니다. 작업 카드·상세·추적·사람 요청의
표시 데이터는 vault Markdown이며, SQLite/JSON은 실행·권한·검증 상태를 확인합니다.
문서가 없거나 확인할 수 없으면 DB 내용을 숨은 대체 화면으로 채우지 않고 진단합니다.

생성된 task current와 human-request 문서는 `loop_work` JSON frontmatter로 문서 식별·원래
record와 지식 홈을 연결합니다. 관리 문서의 본문 편집은 실제 Markdown에서 표시하고,
개인 `notes/`는 보존하되 자동 수집·노출하지 않습니다. 메타데이터나 본문을 바꿔 승인·완료·QA
권한을 얻을 수 없습니다. 화면은 실제 문서 revision과 runtime 요청
revision을 함께 검사합니다. stale·소유권/범위 불일치는 원문과 진단을 확인하고 새로고침하며
자동 재제출하지 않습니다. 원래 task/control/budget/source guard는 그대로 적용됩니다.

vault의 고정 project/task `current.md` 경로는 소유 manifest가 없더라도 안전한 범위에서
읽기 전용으로 발견할 수 있습니다. 작업 문서는 현재 runtime 작업에 명시 loop-work 출처가 있고
연결 정보가 일치할 때만 표시하며, 해당 runtime 작업이 없거나 출처가 불명확하면 숨깁니다.
소유 pin이 없는 문서는 읽기 전용이며 응답/실행 권한을 만들지 않습니다. 하나의 중간 문서가 없거나 안전하지 않아도 다른 정상
기록은 유지합니다. 범위를 제한하지 않은 Board도 export 경로·작업 ID·제목·개별 오류를
공개하지 않고 식별자 없는 집계 진단만 표시합니다. CLI/KB의 상세 로컬 export 진단은 그대로
유지하며, Board에서 세부 정보를 숨겼다는 사실을 출력 오류가 없다는 뜻으로 해석하지 않습니다.

응답은 실제 사람의 원문이고 허용된 `resume_task` 실행은 별도 명시 행동입니다. action이
commit됐는데 vault 출력만 실패한 경우에는 기록된 action 결과와 export 오류를 나눠 표시하고
실행을 반복하지 않습니다. 보드에는 임의 명령·모델 호출·QA 통과·자동 병합 기능이 없습니다.
기존 요청 생성·대체 관리는 아래 human 호환 CLI를 사용합니다.

## 사람의 결정과 수동 조치

`$loop-work human` / `/loop-work human`은 활성화보다 먼저 분기하여 원래
entrypoint·knowledge home·세션·작업·활성 상태를 유지하면서 사람에게 남은
요청을 처리합니다. 뒤에 `list|show|request|respond|execute`를 지정합니다.
별도 스킬을 설치하지 않으며 human만 사용하면 harness 활성화·해제나 새 목표 생성이 없습니다.
상세 지침은 이 모드에서만 [human 규칙](../rules/human.md)을 읽습니다.
답변은 사용자가 명시한 원문만 기록합니다. 작업자 제안이나 무응답을
승인으로 바꾸지 않습니다. 바인딩이 불명확하면 최신 작업을 임의 선택하지 않습니다.

```sh
python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" human list --session "$SESSION_ID"
python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" human show "$REQUEST_ID"
python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" human respond "$REQUEST_ID" --input "$RESPONSE_JSON" --expected-revision "$REVISION"
```

응답 파일은 `{"decision":"answer","text":"사용자의 원문"}` 형식입니다. decision 요청에는
`answer`, approval에는 `approve`/`reject`, manual_action에는 `resolved`를 사용합니다.
질문·선택지·근거·action·현재 revision을 확인한 뒤 제출합니다. revision 충돌은 새 상태를
다시 확인해야 하며 기존 응답을 덮거나 자동 재제출하지 않습니다. 새 사람 소유 요청은
`human request TASK_ID --input REQUEST_JSON`으로 등록합니다. 입력 필드는 `id`, `kind`,
`title`, `question`, `options`, `action`, 선택적인 `evidence`와 `supersedes`이며 현재 `--help`를 확인합니다.

```sh
python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" human execute "$REQUEST_ID" --expected-revision "$REVISION"
```

사람 요청은 macOS의 `board open` 또는 텍스트 CLI로 처리합니다. 응답과 실행은 별개이며, 위 명령은 사용자가 요청한 승인/해결된
`resume_task`만 수동으로 실행합니다. 기존 작업자/팀 이력 등 안전하게 재개할 수 없는
상태는 차단될 수 있습니다. 차단 근거를 확인하고 기존 작업 절차로 해결하며 새 작업이나
예산 초기화로 우회하지 않습니다. 작업 재개는 모델 호출·QA 통과·커밋·푸시·자동 병합을
뜻하지 않습니다. 스킬과 UI는 임의 명령 실행 권한이나 외부 작업 승인을 만들지 않습니다.

이전 요청이 stale이면 원래 근거나 답변을 수정하지 않습니다. 현재 작업과 근거를 확인해
새 요청에 같은 작업의 `supersedes: ["이전-request-ID"]`를 명시합니다. pending·stale·declined
요청의 이력은 보존되고, 새 요청은 pending에서 시작해 별도 답변/승인이 필요합니다.
대체 등록은 과거 승인 승계나 자동 재실행을 뜻하지 않습니다.

## 보드의 작업 보완과 일시 중지

진행 중 해당 작업의 보완·제약·pause·resume은 대기 중인 사람 요청 없이 직접 입력할 수 있습니다.
UI는 원문과 operation ID, 현재 task/control/vault revision을 함께 전송합니다. 충돌 시 새 상태를
읽고 원문을 보존하며 다른 작업에 자동 재적용하지 않습니다. 5초 간격의 표시 갱신은 작성 중인
입력을 보존하고, 조회 실패 시 오래된 상세·제어를 유효한 상태로 보여 주지 않습니다.
resume는 pause 피드백만 해제하므로 `blocked` phase 해결은 원래 작업 절차에서 수행합니다.
동기 작업의 pause/off는 runtime 관찰·관리 subprocess polling에서 반영됩니다. 실제 중단 여부와
소비한 호출·남은 작업을 기록하며 외부 프로세스 전체 즉시 취소나 적용 내용 rollback을 보장하지 않습니다.

## 독립 CLI와 관리형 보드

사용자 설치의 `~/.local/bin/loop-work` 또는 프로젝트 설치의 `.loop/bin/loop-work`는
스킬이 반환하는 설치 `loop.py`와 같은 runtime을 실행합니다. 별도 Python 패키지나 PATH
설정을 설치하지 않습니다. 실행 권한·내용은 설치 manifest로 추적하며, 비소유 파일·symlink·
사용자 수정 충돌은 install/uninstall 전에 거절합니다. 구형 manifest는 그대로 업그레이드할 수 있습니다.

`board start`는 선택한 KB의 `board-service/` 아래 권한 0600의 상태·로그와 lock을 사용합니다.
설정 digest는 KB/vault/session/task/project와 runtime을 구분합니다. 서버가 반환하는 capability,
instance nonce, config ID, PID가 일치하는 실제 HTTP readiness를 확인해야 running으로 보고합니다.
동시에 시작하거나 다시 시작하면 같은 instance를 재사용합니다. 포트 충돌·실행 실패는 로그를
남기고 성공으로 표시하지 않으며, 공개 lifecycle 출력에는 capability URL을 포함하지 않습니다. `start`는 backend만 준비하고 앱을 자동 실행하지 않습니다.

`board status`는 stopped/starting/running/failed/unknown을 구분합니다. 응답 불일치나 응답 없는
running 기록은 unknown이며 자동 프로세스 종료나 중복 start를 하지 않습니다. `board stop`은
loopback capability와 nonce로 인증된 서버에 shutdown을 요청하고 서버의 stopped 기록을 기다립니다.
PID 재사용이나 기존 미관리 foreground 서버는 종료하지 않습니다. 이미 stopped이면 재실행은 안전합니다.
설치 해제는 실행 명령·소유 설치 자산을
제거하고 DB/vault/상태·로그는 보존합니다. 서버 중지는 설치 해제 전에 별도로 요청하세요.

`--project ID`로 서버를 고정하면 다른 project query·상세·위키·질문·저장·제어 요청을 거절합니다.
프로젝트 검색은 `GET /api/projects?query=...&sort=name|updated`, 목록은
`GET /api/board?project_id=ID&include_closed=1`을 사용합니다. 프로젝트·작업 위키는
`GET/POST /api/projects/:id/wiki`, `/api/tasks/:id/wiki?project_id=ID`이며 저장 필드는
`operation_id`, `expected_revision`, `title`, `body_markdown`만 허용합니다.
문서 변경은 실행/QA/승인 권한을 부여하지 않습니다.

위키 저장 HTTP JSON은 1MiB로 제한하며 상한 초과는 413으로 거절합니다. 본문을 자동 절단하지
않습니다. 이 전송 상한과 위키 본문 UTF-8 520192바이트·제목 200자 검증은 별도입니다.
기존 질문 응답·제어 API의 64KiB 전송 제한은 유지합니다.

보드의 중단 열은 폐기된 작업을 `중단·폐기`, 기술 문제로 막힌 작업을 `기술적 차단`으로
구분하며 `state_reason`에 작업의 원래 사유를 전달합니다. 사용자 일시정지·응답 대기는
계속 `사용자 확인 필요`가 우선합니다. 프로젝트의 최근 변경 정렬은 해당 범위의 작업
기록과 프로젝트·작업 위키 수정 시각을 함께 사용하므로 Obsidian 외부 편집도 반영합니다.

개발 완료 표시는 최종 게이트·소스·피드백뿐 아니라 동결된 계약·발견·규칙·현재 하네스
입력도 읽기 전용으로 대조합니다. 누락·불일치는 과거 완료 기록을 남긴 채 사용자 확인이
필요한 상태로 표시합니다. 미결 사람 요청은 Markdown이 없거나 오래되어도 확인 필요
분류에 반영하며, 보이지 않는 질문·응답 원문을 데이터베이스에서 대신 표시하지 않습니다.

프로젝트 범위의 목록·본문은 선택 범위만 표시합니다. 제어·응답·재개 직전에는 표시 범위와
별개로 공유 작업의 모든 프로젝트 사본과 해당 요청 사본의 보존된 소유 해시를 검사합니다.
다른 사본이 수정되거나 삭제되면 선택한 사본이 그대로여도 실행을 거절하며, 다른 프로젝트의
문서 경로·본문은 오류에 노출하지 않습니다. 누락된 사본은 자동 재생성하지 않습니다.

## 일반 대화 기억과 명시 작업 출처

실제 `$loop-work <작업>` / `/loop-work <작업>` 분기의 내부 생성에만
`work open --explicit-skill` 또는 `init --explicit-skill`을 사용합니다.
플래그 없는 저수준 생성은 유지되지만 Board 작업에는 나타나지 않습니다. 과거 작업의 출처를
소급 변경하거나 vault 복사로 보드 권한을 만들지 않습니다. 정보만 있는 프로젝트는 실제 project index Markdown이 있을 때만 작업 수 0으로
프로젝트 위키를 읽을 수 있습니다. topic 문서만 있고 index가 없으면 Obsidian 지식으로 남으며
Board의 프로젝트 항목에는 나타나지 않을 수 있습니다. DB 프로젝트 정보로 화면을 대신 채우지 않습니다.

일반 입력에서 현재·미래 작업에 필요한 사실·사용자 결정은 [작업 없는 기억](knowledge.md#일반-입력의-작업-없는-프로젝트-기억)으로
선별 보존합니다. task/session/활성화를 만들지 않고, 확인된 기존 session만 선택적으로 사용합니다.
실제 출처·원문·적용 범위를 보존하며 전체 프롬프트를 자동 수집하지 않습니다.


## 데스크톱 창과 서버의 수명주기

TARGET 설치 launcher의 `board open|start|status|stop`은 `--project`를 생략해도 설치한 프로젝트 범위를 일관되게 사용합니다. 기존 연결의 사용자 지정 프로젝트 ID를 유지하며 다른 `--project`는 거절합니다. 아직 연결되지 않은 TARGET의 `status`/`stop`은 전역 서버를 조회·시작·중지하지 않고 `stopped`를 반환합니다. 설치 기록이 앱을 소유한다고 명시하는데 앱이 없거나 손상된 경우에는 범위 없는 서버로 전환하지 않습니다. 앱을 설치하지 않은 기존 저수준 서버 전용 설치는 기존 동작을 유지합니다.

Finder/Dock에서 Loop Work.app을 열거나 `loop-work board open`을 사용합니다.
창 닫기는 앱을 숨기고 Dock에서 다시 열면 창을 복원합니다. Cmd-Q 종료 시 저장되지 않은
위키·IME 조합·충돌·저장 응답 미확인은 한국어 확인으로 보호하며, 작업의 pause/resume나
승인으로 해석하지 않습니다. 자동 Dock 고정·로그인 항목·전역 앱 설정은 변경하지 않습니다.

앱 helper가 새로 만든 backend만 종료/입력 EOF 때 소유 nonce를 확인해 닫습니다.
`board start`가 먼저 만든 서버에 앱이 연결했거나 기존 CLI 서버를 재사용했다면 앱 종료로
서버를 끄지 않습니다. 같은 KB/vault/session/task/project 설정의 `board status`와 `board stop`이
그 관리 경계입니다. 외부 브라우저 및 공개 foreground serve 명령은 제공하지 않습니다.


### native 검증 보고 읽기

1. 일반 배포 binary의 실제 startup/quit 4경우는 앱 시작과 소유·재사용·교체 backend 종료 경계의
   근거입니다. 이 결과만으로 populated 작업 편집이나 시각화·승인·제어까지 검증됐다고 쓰지 않습니다.
2. `native-qa`는 기본 비활성 feature이며 별도 감사 binary에서만 사용합니다. 실제 Tauri WebView와
   기존 Rust `board_request` → Python API를 거쳐 임시 populated vault의 편집·응답/승인·제어,
   창 hide/reopen과 종료 deadline을 확인한 실행을 별도 report로 보존합니다.
3. programmatic DOM/IME composition/media-query 검사는 `physical_gui_input_verified=false`로 명시합니다.
   물리 OS 입력·실제 IME 조작이나 모든 접근성 환경의 검증으로 확대하지 않습니다. 일반 앱에는
   감사 명령을 노출하지 않으며 승인·예산·Python engine 계약을 바꾸지 않습니다.
4. 실패 진단은 제한된 private audit 경로로 다룹니다. capability·nonce·helper 원문을 frontend나
   일반 로그로 출력하지 않습니다. 실제 결과와 실패를 보존하고, 완료하지 않은 부모 목표를
   완료로 표시하거나 inconclusive 벤치마크를 품질·속도 향상 근거로 바꾸지 않습니다.

감사 report의 `feature: "native-qa"`, `shipping_binary: false`, `report.real_tauri_ipc: true`,
`report.api_proxy_shim: false`는 별도 감사 binary에서 실제 Rust IPC를 사용했다는 구분입니다. native dialog는
실제로 표시한 뒤 QA observer가 cancel하는 검사이며, 실제 사용자의 dialog 클릭은 검증하지 않습니다.


### 종료 확인과 사람 요청의 불명확한 전송

종료 요청은 `request_id`별 guard를 유지합니다. 저장 await 전뿐 아니라 저장 후에도 모든 미결
사람/제어 요청, 편집 중·저장 중·IME 조합·충돌·불명확한 저장과 원문 초안을 다시 확인합니다.
확인 중에는 새 입력과 mutation을 막으며, 실제 native dialog에서 같은 ID의 취소 callback이
돌아오면 해당 종료 guard를 풉니다. 종료 응답 IPC가 만료되거나 실패한 오류 경계에서는 해당
시도를 진단과 함께 끝내고 그 시도의 guard를 해제해 계속 편집할 수 있게 합니다. QA의 일시적인
종료 준비 검사 자체는 guard를 반환합니다.

응답/실행 전송이 불명확하면 원래 payload A와 당시 runtime/vault pin을 보관합니다.
**원래 요청 확인·재시도**는 사용자가 명시적으로 눌렀을 때만 같은 범위의 최신 요청을 GET합니다.
일치하는 실제 접수 이력이 있으면 POST 없이 접수 확인만 합니다. 그렇지 않으면 원본이 fresh이고
수정되지 않았으며 writable이고, runtime 원본·revision과 vault revision이 원래 pin과 정확히
같을 때만 원래 payload A를 한 번 다시 보냅니다. poll이나 새 원문 B로 자동 재전송하지 않습니다.
B는 보존하며 실행은 원문을 지우지 않고, 응답은 현재 초안이 제출했던 A와 같을 때만 비웁니다.
이 과정은 승인·실행의 기존 backend 권한 검사나 물리 GUI 입력 검증을 대신하지 않습니다.
