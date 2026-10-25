---
name: loop-work
description: Explicitly run one requested task through the goal-setting and work harness in Claude Code or Codex, or use board to open the vault-backed task board without changing activation. The human argument remains available for request management. Ordinary task wording never activates it.
---

# Loop Work

Orchestrate goals, feedback, delegation, evidence checks and reporting. Delegate
investigation, planning, implementation and writing.
An assigned worker/reviewer executes only its assignment: never activate, orchestrate,
write task/knowledge state, ask users or delegate further.

## Select the argument first

If the first argument is `board` (`$loop-work board` / `/loop-work board`), read
[board mode](rules/board.md) before activation. Use retained `rules_home` or the
adapter's `rules` link; unbound source uses `SKILL_DIR/../../rules/board.md` and a
copied project uses `.loop/rules/board.md`. A bare `board` means `board open`.
Use the retained absolute entrypoint/knowledge home/session/task; without a retained
entrypoint use this skill's sibling `loop.py`. Never run `harness on` or `off`,
create a goal/session, or guess the latest binding to open the board. `board open` opens the native desktop window on macOS. `board start` prepares only the backend; Linux retains the non-GUI CLI. The explicit request
authorizes that local app/server action; do not ask for repeated permission.
Stop this mode after handling the board command; do not continue into activation.

If the first argument is `human` (`$loop-work human` / `/loop-work human`), read
[human mode](rules/human.md) from retained `rules_home` or the adapter's `rules`
link. For an unbound source checkout use `SKILL_DIR/../../rules/human.md`; a copied
project uses its `.loop/rules/human.md`. Do not run `on` to locate it. Route remaining arguments to
`human list|show|request|respond|execute` using the same runtime and retained
knowledge/session/task. A bare `human` inspects the scoped list; it never runs
`harness on` or `off`, creates a goal, or changes the binding. Without a retained
entrypoint use this skill's `SKILL_DIR/loop.py`; never choose a session by recency.
Otherwise follow the explicit task/off procedure below. Worker assignment restrictions apply first.

## Run one explicit task

`$loop-work <prompt>` or `/loop-work <prompt>` authorizes one task, not a session toggle.
A bare skill invocation asks once for the missing task prompt; create no session,
goal or activation. An explicit `off` cancels routing only for the owned binding
without creating a session or changing retained tasks, files, knowledge or budgets.
Never infer a task from the latest session, provider, cwd or legacy enabled flag.

Use [work](rules/work.md) to classify the explicit prompt and establish its goal/task
with `work open --explicit-skill` or development `init --explicit-skill`, retaining the returned session/task IDs.
For development use the returned `work.id` task record, not the local goal name.
Then bind the existing task:

```sh
python3 "ENTRYPOINT" --knowledge-home "KNOWLEDGE_HOME" harness on --provider PROVIDER --session SESSION_ID --task TASK_ID
```

Use `claude` inside Claude Code and `codex` inside Codex. Before binding, use this
skill's sibling `loop.py` if there is no retained absolute entrypoint. Preserve its
returned `entrypoint`, `rules_home`, `knowledge_home`, `session_id` and `task_id`.
A second explicit prompt must not silently replace a still-running task: keep it
separate with an independent task/session or clarify a consequential conflict.

## Continue only this task

Related corrections, status questions, worker results and compaction retain the same
task, including directory changes. Restore only its capsule:

```sh
python3 "ENTRYPOINT" --knowledge-home "KNOWLEDGE_HOME" orchestration context SESSION_ID --task TASK_ID
```

Read only needed references; never replay full histories or duplicate recovery logs.
Unrelated ordinary requests run normally outside the harness: do not auto-create,
resume or replace a task. Relevant ordinary-input information may be retained as
project knowledge without a task under [memory boundaries](rules/context.md#ordinary-input-memory-without-a-task).
Do not dump all prompts or fabricate session IDs. Completion or abort releases automatic task routing;
never carry activation into a new request. A blocker or pause is not completion:
preserve its task and consumed budgets, dispatch no paused work, and resume only
on explicit continuation. A status question never resumes work.

After actual task completion, follow the [한국어 하네스 사용 회고](rules/writing.md#작업-완료-후-하네스-사용-회고)
using the retained task/session and knowledge context. This adds no new task or review;
worker restrictions still apply.

Load only the applicable rule:

- [entry](rules/entry.md): task binding, legacy/off handling and pause recovery.
- [routing](rules/routing.md) and [delegation](rules/delegation.md): bounded workers,
  eligible frozen profiles, assessment before effects and finite retries.
- [context](rules/context.md) and [writing](rules/writing.md): scoped steering and Korean
  authored tracking/knowledge; preserve original input, code/evidence and explicitly
  requested foreign-language deliverables.
- [workflow](rules/workflow.md): development tests, fresh available-provider review,
  repair and final evidence; other work uses completion checks.
  For affected GUI async changes, use its scoped state-combination plan and frozen
  check policy; reuse delegation handoff evidence and writing's bounded stage updates.
- [benchmark](rules/benchmark.md): harness changes/evaluation only.

If the entrypoint is unavailable, stop this task's routing and report it; never
fall back or silently reactivate. These are host instructions, not message hooks.
Honor user recording restrictions and provider permissions.

### 독립 보드 명령

설치된 `loop-work board start`는 관리형 localhost 서버를 시작하거나 같은 instance를 재사용하고,
`loop-work board status`로 확인하며 `loop-work board stop`으로 인증된 instance만 종료합니다.
`loop-work board open`은 macOS 데스크톱 앱을 엽니다. `board start`는 창 없이 backend만 준비합니다. 앱을 닫아도 작업을 중단·재개하지 않습니다. `--project ID`는 해당 프로젝트로 보드를 제한합니다.
이 관리 명령으로 작업을 활성화하거나 목표·QA·예산을 바꾸지 마세요. PATH에 없으면 설치가 출력한
절대 실행 경로를 사용하고 PATH/전역 설정을 임의로 변경하지 마세요. 기존 스킬의 절대 진입점도 계속 유효합니다.
