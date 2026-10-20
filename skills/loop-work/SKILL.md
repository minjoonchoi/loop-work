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
copied project uses `.loop/rules/board.md`. A bare `board` means `board serve`.
Use the retained absolute entrypoint/knowledge home/session/task; without a retained
entrypoint use this skill's sibling `loop.py`. Never run `harness on` or `off`,
create a goal/session, or guess the latest binding to open the board. `board serve`
opens the default browser unless `--no-open` was requested. The explicit request
authorizes that local server/browser action; do not ask for repeated permission.
Stop this mode after handling the board command; do not continue into activation.

If the first argument is `human` (`$loop-work human` / `/loop-work human`), read
[human mode](rules/human.md) from retained `rules_home` or the adapter's `rules`
link. For an unbound source checkout use `SKILL_DIR/../../rules/human.md`; a copied
project uses its `.loop/rules/human.md`. Do not run `on` to locate it. Route remaining arguments to
`human list|show|request|respond|execute|serve` using the same runtime and retained
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
with `work open` or development `init`, retaining the returned session/task IDs.
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
resume or replace a task. Completion or abort releases automatic task routing;
never carry activation into a new request. A blocker or pause is not completion:
preserve its task and consumed budgets, dispatch no paused work, and resume only
on explicit continuation. A status question never resumes work.

Load only the applicable rule:

- [entry](rules/entry.md): task binding, legacy/off handling and pause recovery.
- [routing](rules/routing.md) and [delegation](rules/delegation.md): bounded workers,
  eligible frozen profiles, assessment before effects and finite retries.
- [context](rules/context.md) and [writing](rules/writing.md): scoped steering and Korean
  authored tracking/knowledge; preserve original input, code/evidence and explicitly
  requested foreign-language deliverables.
- [workflow](rules/workflow.md): development tests, fresh available-provider review,
  repair and final evidence; other work uses completion checks.
- [benchmark](rules/benchmark.md): harness changes/evaluation only.

If the entrypoint is unavailable, stop this task's routing and report it; never
fall back or silently reactivate. These are host instructions, not message hooks.
Honor user recording restrictions and provider permissions.
