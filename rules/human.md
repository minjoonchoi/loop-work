# Human desk mode

Read this rule only for `$loop-work human` / `/loop-work human` or an explicit
human-desk subcommand. Process this mode before `harness on`; never create a goal or
change activation merely to inspect or answer a request. Assigned workers/reviewers
retain their existing prohibitions and cannot record a human response.

Handle human-owned inputs without inventing answers or bypassing the task workflow.
The `human` argument does not activate or disable loop-work. Preserve the current conversation's
absolute entrypoint, knowledge home, session ID and task ID. When loop-work is active,
restore `orchestration context SESSION_ID` and retain only its existing task-scoped binding; never activate unrelated inputs.
Do not create a replacement session, switch tasks by recency, or reset budgets.

## Locate and inspect

Use the retained absolute entrypoint. Without a binding, the invoked loop-work skill's sibling
`loop.py` enters the installed or source runtime; do not search for another runtime
if it is unavailable. In a source checkout read this rule at `SKILL_DIR/../../rules/human.md`;
a copied project's rule is `.loop/rules/human.md`, while linked adapters expose their
`rules` link. These locate the same selected runtime, not a fallback installation.
Preserve the chosen knowledge home on every command.

```sh
python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" human list --session "$SESSION_ID"
python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" human show "$REQUEST_ID"
```

Use `--task TASK_ID` to narrow a list, or `--include-closed` when explicitly needed.
Inspect the exact question, options, action, evidence and current revision before
responding. Never claim an unanswered request is resolved. If the request/session is
ambiguous, ask one short question rather than selecting someone else's decision.

## Record the person's response

Record only the user's explicit response to the identified request. Preserve their
original text in a UTF-8 JSON file; do not paraphrase it into wider authorization.
Use the decision appropriate to the request: `answer` for a decision, `approve` or
`reject` for approval, and `resolved` for a completed manual action. For example:

```json
{"decision":"approve","text":"THE USER'S EXACT RESPONSE"}
```

```sh
python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" human respond "$REQUEST_ID" --input "$RESPONSE_JSON" --expected-revision "$REVISION"
```

The example text is a placeholder, never a real approval. A worker draft, inferred
preference, silence, available credentials or permission to inspect is not a human
response. On revision conflict, inspect the updated request before doing anything
else. Do not automatically resubmit or overwrite another response.

## Manual continuation and local UI

An approved/resolved request is a record, not automatic execution. Only when the
person explicitly asks to run its recorded `resume_task` action, inspect the current
revision and execute it once:

```sh
python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" human execute "$REQUEST_ID" --expected-revision "$REVISION"
```

For the native Board, use `board open` on macOS. Responses must come from the person; never click
approval controls on their behalf without their explicit answer. The desk cannot run
arbitrary CLI/shell commands. `resume_task` does not dispatch workers, reset attempts,
complete QA gates, merge code, commit/push, publish, or grant external permissions.
Unresolved task integrity, pause controls and finite budgets still apply.

To create a new genuinely human-owned request, use `human request TASK_ID --input
REQUEST_JSON` with exact fields `id`, `kind`, `title`, `question`, `options`, `action`
and optional pinned `evidence` and `supersedes: [REQUEST_ID, ...]`. Read `human request --help` and the current task
before composing it. Use `action: null` unless the existing task supports a scoped
`resume_task`; decision requests always use null. Do not turn technical work that
can proceed within scope into a human blocker. Report what was recorded, what remains
blocked and one concrete next action; never report task completion from an answer alone.

If an earlier request is stale, do not edit its pins or carry its answer forward.
Inspect the current task/evidence and create a new request with fresh evidence and
explicit `supersedes` IDs belonging to the same task. Only pending, stale or declined
requests can be replaced; their history remains available. The new request starts
pending and needs its own human response. Supersession is not renewed approval.
