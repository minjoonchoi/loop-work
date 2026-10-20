# Vault task board

Use this mode for `$loop-work board [subcommand]` / `/loop-work board [subcommand]`
before activation. A bare `board` means `board serve`; an explicit `list` or `show`
keeps that subcommand and its arguments rather than opening a server. Assigned workers/reviewers keep their
existing prohibitions; they cannot open a user decision UI or submit human responses.

## Open with the existing binding

Keep the absolute entrypoint, knowledge home, session and selected task. If unbound,
use the invoked skill's sibling `loop.py` to locate this runtime. Do not activate,
disable, create a goal/session, or select by recency/provider/cwd. Ask one short
question only if the intended existing scope is genuinely ambiguous. For an active
conversation restore only its existing task context; off remains off. Completion
releases task routing; opening the board never creates or reactivates a task.

```sh
python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" board serve --session "$SESSION_ID" --port 0
```

Add `--task TASK_ID` when selected. Omit absent scope flags rather than inventing IDs.
With no binding, `python3 "SKILL_DIR/loop.py" board serve` uses the shared default.
An arbitrary custom knowledge home requires its explicitly selected `--vault PATH`;
do not substitute another knowledge home's vault or enable automatic export to find one.
The command starts a localhost server and opens its actual URL in the default browser.
Use `--no-open` when requested. Do not ask again for permission to open the browser
for this explicit board request. Report the actual URL if browser opening fails; never
report an unopened tab as opened. Keep the server available during use and stop it
when finished. Do not open a second server merely because the page is still loading.

## Read the documents shown

The board's display and document data come from vault Markdown: task cards, details,
tracking text and recorded human requests. SQLite/development JSON retain execution,
authority and verification state; they do not replace missing vault text with a
parallel hidden DB dashboard. Preserve the user's notes and document edits.

Missing, edited, stale or unrecognized request metadata must show its diagnostic
and disable unsafe actions. A Markdown label or edited frontmatter cannot grant
approval, finish a task, reset budgets, satisfy QA or bypass runtime integrity checks.
Vault-only task documents may be shown read-only without a runtime record or an
ownership pin. They confer no action authority. A scoped board intentionally omits
global export error details that could expose other tasks; do not interpret withheld
diagnostics as an error-free export or expand scope silently to retrieve them.
For current execution evidence, follow the scoped original references and normal
orchestration context. Local audit links are not automatically portable artifacts.

## Human responses and execution

Only the actual person supplies an answer, approval, rejection or manual-action result.
Never invent response text or use approval controls without the person's explicit
answer to that exact request. Inspect the identified request, displayed revision and vault revision before submitting. On a
conflict reload the actual document/request and preserve existing responses; do not
blindly retry or reinterpret the original answer as broader authorization.

An approved/resolved request does not execute itself. Only an explicit request to run
its allowed `resume_task` permits the manual execute action. Keep the same task,
goal, pause controls, histories and remaining attempts/calls/deadline. This does not
dispatch models, run arbitrary shell, complete QA, merge, commit/push or publish.

If an action committed but vault export failed, report the committed action and the
separate document error. Never execute again to refresh the page. Existing `human`
CLI/rules remain compatible for creating or replacing requests; the board is the
primary viewing/responding UI, not a new source of user authorization.

## Direct task controls

The actual person may submit pause, resume, correction or constraint text directly
for the identified task without a pending human request. Preserve their original
text; bind the operation ID and expected task/control/vault revisions. A conflict
requires rereading current state, not silently replaying text against a new task.
Resume clears feedback pause only: it does not repair a phase blocker, reset caps,
run models, satisfy QA or grant permission for an unrelated task. Pause/cancellation
is observed at runtime boundaries and managed subprocess polling; report the actual
interruption/remaining work rather than promise rollback or immediate cancellation
of arbitrary external processes. Polling must preserve typed drafts and disable
unsafe controls when current state cannot be loaded.
