# Shared development loop

Enter through `work.md` to select the task type. Apply `writing.md` to status,
analysis and results; keep detailed evidence in linked records.

This is the single workflow for Claude Code and Codex. The main conversation handles
the goal, user feedback, orchestration, evidence checks and reporting. Explicitly
assigned CLI workers investigate, plan, draft and implement; an independent fresh
invocation reviews. Use the opposite provider when its CLI is installed; otherwise
use the worker provider. Record this availability choice during plan-review and keep
it fixed for the goal. Authentication, permission or execution failure never triggers
a same-provider retry. Follow `delegation.md` for every handoff. The user must
not have to feed source locations, missing dependencies, error explanations, or next
steps one prompt at a time. Run the commands below yourself; do not hand the user a
manual checklist to operate the loop.

## Development for one explicitly invoked task

An explicit `$loop-work <prompt>` or `/loop-work <prompt>` enters this workflow for
that task. Related corrections and continuation do not need another prefix. Ordinary
unrelated requests do not activate it, even in a conversation with prior tasks.
Completion or abort releases routing; preserve all QA gates and finite budgets.

| User intent | Agent action |
| --- | --- |
| Build, implement, improve, change or fix project behavior | Enter preflight automatically, then execute the full loop |
| Follow up on an existing goal or say "continue" | Restore its context and continue the appropriate phase |
| Ask a question, request explanation, or ask for read-only review | Answer/review within scope; do not create a development goal |
| Explicitly request planning only, a pause, or no code changes | Honor that boundary; do not start implementation |

When there is an existing goal, inspect the session's orchestration capsule before
creating anything. If there is no active goal, reuse the
matching draft/ready goal from the conversation and stored state when identifiable.
Otherwise choose a meaningful safe goal ID yourself. Do not ask the user to supply
IDs, JSON, file locations or script commands merely to operate the harness.

Keep the same local `session_id` and task ID throughout this task. Completion
releases routing; a later explicit task never inherits activation automatically. After every user input, worker result and compaction, load
`orchestration context SESSION_ID [--task TASK_ID]`. Follow specific references to
relevant facts, decisions or failed evidence. Reuse unchanged facts/answers; delegate
only missing topics and affected dependencies. Follow `context.md` for feedback and
durable updates; do not reload full context/history or create parallel recovery logs.
The last goal's state stores the session ID for recovery after context compaction.
Never guess session ownership from the newest file or a provider-wide global pointer.

A broad desired outcome starts discovery and preflight, not speculative code edits.
Derive the missing technical context and acceptance criteria. Ask only necessary
human-owned decisions before start, following the policy below. Do not expand the
product scope beyond the user's goal or wait for repeated "next" instructions.
For a clear bounded change, put necessary source inspection and the implementation
in one complete worker unit instead of adding a standalone analysis/plan deliverable.
Keep actual tests, preflight review, independent implementation review and final
fresh evidence. Before start, resolve every required preflight assignment; a blocked
`goal_setting` assignment cannot be rerun after entering implementation. A new task
or assignment ID must not be used to erase its history or reset budgets.

For a setup-sensitive handoff, run `delegate GOAL --input FILE --check` before the
actual delegate call. The check reports current setup failures without changes;
it does not approve implementation or guarantee later freshness. Resolve exact
scope/public API/settings/classpath/compiler-diagnostic gaps before spending a call.
Check every prerequisite command's exit status: if `note` or validation fails, do
not run its dependent delegate. Draft evidence belongs in discovery/contract, while
execution notes require running phase. Keep parent inputs unchanged during a call;
retain and recover stale results instead of silently resealing them.

## Roles and precedence

- Follow the user's goal and applicable repository instructions. Inspect nested
  `AGENTS.md`, `AGENTS.override.md`, `CLAUDE.md` and project rules before editing.
- Read this file, `delegation.md`, `routing.md`, `context.md`, and `quality.md`. Project-specific rules remain in
  their original files; reference them in the contract rather than duplicating them.
- An explicit worker/reviewer assignment is a bounded tool task. Return its schema
  only; never expand scope, redelegate, ask the user or start another loop.
- `orchestrator` identifies the actual conversation; `implementer` identifies its
  implementation worker. Both can be Claude or Codex. The session belongs to the
  orchestrator; the independent reviewer follows the recorded preflight selection. Do not switch
  either provider after freeze. Do not bypass vendor restrictions on nested CLI calls.
- Python 3.10+, Git and at least the selected worker CLI on macOS/Linux are required. Use
  existing CLI authentication and permissions. Do not bypass permission systems.

## 1. Capture the target and discover context

For a new explicitly invoked development task, run this command yourself:

```sh
python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" --root "$PROJECT_ROOT" init goal-id --explicit-skill --title "Desired result" --implementer codex --orchestrator codex --session SESSION_ID
```

Set `--orchestrator claude` inside Claude Code. The worker defaults to the same
provider in ordinary use; an authorized alternative may be set before freeze. Test
a read-only analysis assignment before start to verify the worker CLI.
For a continuing goal, restore its orchestration capsule instead of initializing again.
`init` creates the task/session before `harness on --task TASK_ID` binds it.
`session open` remains available for inactive low-level use; it does not activate work. Keep the ID, absolute CLI entrypoint and knowledge home
in handoffs. The agent performs these actions; the user supplies goals and unresolved
human decisions. A completed or aborted goal releases task routing.

1. Define observable target behavior, users, scope, exclusions, requirements and
   acceptance scenarios before judging the current implementation.
2. Reuse applicable current session analysis first. Delegate bounded analysis of
   missing/stale source, callers, tests, data and interfaces. Inspect the returned
   evidence and save supported summaries with `session remember`. Request official
   documentation through explicitly scoped lookup tools for uncertain integrations.
   Provide those references to the worker; do not ask the user to narrate technical facts.
3. Have planning workers return findings and per-requirement gaps for `discovery.json`,
   and desired behavior/acceptance for `contract.json`. Record validated content in
   those files. Empty, partial, mock-only or broken code means
   more work. It is never a reason to silently downgrade the target to an MVP.
4. Have planning workers decompose work into ordered vertical milestones. Every
   requirement maps to acceptance, every acceptance maps to executable checks and a milestone. Include
   existing regression checks and real integration/E2E checks where needed.
   Keep a complete small contribution together; team members need separate verifiable
   outputs, explicit dependencies and exclusive write ownership under `routing.md`.
5. Fill the ten decision areas in `"$TEMPLATES_HOME/contract.example.json"`'s format.
   Record basis accurately: `user`, `repository-rule`, or `delegated`.
6. Record explicit available profiles in `execution.routing`, or import them using
   `LOOP_ROUTING_PROFILE` during preflight. Configure suitable profiles for the worker
   and selected independent reviewer before freeze. Assignment demand chooses the cheapest eligible
   profile; higher initial demand needs evidence. No runtime model/effort fallback is used.

Before freeze, state the coordinator-selected gate-attempt, worker-call and working-time
budgets, their rationale and the exhaustion condition. Distinguish coordinator choices
from user limits; do not ask for another approval when the choice is already delegated.

## 2. Resolve only human-owned uncertainty

Distinguish information you can discover from decisions only the user can make.
Check prior answers and their original scope/basis first. Do not repeat an answered
question because a new prompt or goal began. Resolve technical cache staleness
yourself; a changed file alone is not a reason to ask the user again. Carry applicable
answers into the new contract with their provenance. A goal-specific answer is not
new session-wide authorization; a changed product boundary may need a new decision.
Resolve technical facts through scoped workers. Recommend a default for implementation choices
and record any already-delegated discretion. Ask a consolidated, focused round
about materially unresolved product behavior, business rules, allowed external
actions, infrastructure constraints or data ownership. Ask follow-ups only if the
answers expose another blocking decision. Do not invent user answers or mark an
unknown value as approved. Explain `not applicable` with a reason.

Before implementation, settle scope, architecture, data/migrations, UI/API contract,
dependencies/credentials, security, verification, runtime/operations, delivery and
autonomous decision boundaries. The delivery answer states whether completion means
a verified working tree, commit, PR, merge or deployment. Perform external actions
only within the user's existing authorization; plan them before freeze.

Record the permission/setup needed to avoid interactive prompts during execution.
Pre-existing hooks may still run. Inspect their behavior; do not disable managed
controls. Missing credentials or required infrastructure must be resolved now.

For asynchronous GUI editing, approval or close changes, include a short state-combination
table in the existing plan, selecting only affected boundaries. Link each row to its
criterion: input/saved/composing; before-dispatch/committed/lost-response; close/cancel/
reopen; preserved value/prohibited side effect; fixture/command and evidence scope
(renderer, actual native, synthetic event or physical input). Reuse current checks and
explicit limits. Simple work needs no separate PRD, new reviewer roles/count or gate.

## 3. Cross-review and freeze the executable contract

```sh
python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" --root "$PROJECT_ROOT" validate goal-id
python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" --root "$PROJECT_ROOT" plan-review goal-id
```

The live plan review selects the opposite installed CLI, or a fresh invocation of
the worker provider when it is absent, with the explicit review profile
selected under `routing.md`, which also checks that required
CLI flags/authentication work. Review must cover every acceptance criterion and
find no unresolved questions or findings. If it fails, read the artifact, investigate
and repair the plan. Only new human-owned choices return to the user, before start.

Once the goal is sufficiently specified under the user's authorization:

```sh
python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" --root "$PROJECT_ROOT" freeze goal-id
python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" --root "$PROJECT_ROOT" start goal-id
```

Do not add a redundant approval question. Freeze seals target, discovery, decisions,
rules and gate-engine hashes. Start refuses stale code/context. Do not implement
product code before start. Goal/discovery drafting is preflight work.

## 4. Execute the entire loop without further user questions

The contract freezes `execution.check_failure_policy` before start. New templates use
`fail_fast`: a failed check stops later invocations. `diagnostic_continue` explicitly
runs later diagnostics; absent fields preserve legacy continuation without rewriting
frozen inputs. Gate `checks` holds actual executions; `not_run_checks` records `id`,
`reason` and `after_check` for a known-failure stop. Skipped checks never pass. Preserve
cancellation, timeout and budget causes. The final fresh-check/review requirement below
is unchanged; partial/stale passes or budget resets cannot substitute.

Repeat until the goal is complete:

1. Run `orchestration context SESSION_ID --task TASK_ID`. Inspect current control
   state, unfinished acceptance, compact worker results and gate references.
   Open only the evidence needed for the next assignment or completion decision.
   Persist newly received user feedback before dispatch, using `context.md`.
2. Create explicit analysis/planning assignments for remaining gaps, using saved
   paths and dependencies. Pass only necessary current knowledge and prerequisite
   assignment IDs. Inspect each result before selecting the next scope.
3. Delegate complete implementation units with exact allowed file paths, exclusions,
   deliverables, criteria and goal-linked demand. Use `delegate goal-id --input ASSIGNMENT`
   for a small unit or `team goal-id --input PLAN` for cooperating roles. Follow `delegation.md`
   for fixed member scopes, accepted peer routing and finite turns; the main session
   reads compact role results rather than relaying each message.
   Include required integration, error handling, compatibility and documentation.
   The command stages a candidate. Inspect its goal contribution and concrete evidence,
   then call `assess goal-id --input ASSESSMENT` internally. Accept to apply/release it;
   reject an incorrect or harmful result and rerun the same assignment/team with a
   stronger allowed profile within the existing budgets for worker-output quality failure.
   For v2 contract/fixture failures, repair the same work unit with a linked standalone
   request revision on the same profile; teams support revision 1 only. Retain cumulative
   corrections and consumed attempts. Root-owned checks remain pending in worker output,
   then require accepted external evidence; do not assign execution to read-only workers. Do not ask the user to approve
   candidates or add an obligatory model judge. Continue accepted team turns with the
   same plan; worker `done` is not milestone success. Setup, permission and changed-input
   blockers do not justify model escalation.
   Refresh affected knowledge after changes. Do not restamp stale summaries or redo
   unaffected analysis. Do not accept stubs, fake success or weakened tests.
4. Record meaningful discoveries, decisions and adjusted implementation tactics:

   ```sh
   python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" --root "$PROJECT_ROOT" note goal-id --kind discovery \
     --text "What was learned and what it changes" --evidence "src/path.py:42 and check-id"
   ```

   Use `decision` or `replan` for choices/tactical replanning within the frozen
   target. Notes do not authorize scope, test-command, rule or business-rule changes.
5. Run the next checkpoint. The script runs real commands, then a fresh independent
   review using the recorded provider. Read the report; it supplies the next corrective work.

   ```sh
   python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" --root "$PROJECT_ROOT" checkpoint goal-id --milestone M1
   ```

6. When a check/review fails, delegate bounded diagnosis and repair with its evidence, refresh
   context and retry within the fixed budget. Do not ask the user how to debug it.
   If `blocked` is retryable, repair the external/setup problem within existing
   authority, run `resume`, and continue. Never widen authority to force progress.
7. After all milestones pass, run `finish goal-id`. It runs **all** checks and a
   new full-target review on the current files, not a collection of stale passes.
   Fix final regressions and run finish again if needed.

No extra questions after start. Use frozen decisions and delegated technical
discretion. If an unforeseen issue genuinely requires a new product decision,
credential or forbidden action, record a blocker rather than inventing an answer,
waiting on a prompt, or claiming completion. Report what prevented completion and
the exact recovery condition. New requirements start a new preflight goal.

## 5. Completion, interruption and delivery

After verified completion, follow the [한국어 하네스 사용 회고](writing.md#작업-완료-후-하네스-사용-회고)
without changing completed source, frozen criteria or delivery permissions.

- Only `finish` can create `completed`. A reviewer saying "done", a commit, or green
  unit tests alone cannot. Check `status` and require current evidence before reporting.
- Honor the frozen delivery boundary. If a commit changes HEAD after a gate, gate
  evidence becomes stale; make intended commits before the final finish. Treat
  authorized post-verification publishing as delivery and report its actual result.
- For context loss, reopen the same provider and run
  `orchestration context SESSION_ID --task TASK_ID`; continue
  from persisted milestones, findings and notes without asking the user to repeat them.
  Recover `session_id` too and retain it for this identified task; a later new
  task needs an explicit skill prompt and its own binding.
- For an interrupted gate, inspect logs, call `checkpoint`/`finish` to detect the
  interruption if necessary, then `resume`. Consumed attempts stay consumed.
- `block GOAL --input FILE` requires typed version-1 blocker evidence (operations.md).
  Reason-only public blocking is rejected. Check actual task calls/time and unfinished
  gate budgets: exhaustion of one assignment does not exhaust the task. Explicit user
  pause still requires recorded pause feedback. `abort --reason` preserves all
  files and evidence and releases the working tree for another goal. Neither is success.
- A user-requested pause follows `entry.md`'s pause recipe. Preserve the recorded
  boundary; a progress question, retry recommendation or skill reactivation is not
  authorization to resume paused work.
- Budget exhaustion is not a retryable interruption. If the user requests further
  repair, preserve the exhausted goal and create a new preflight goal under the same
  session. Link the predecessor ID, its last failed gate and unresolved acceptance;
  record the new budget and who selected it. Never reset consumed attempts, silently
  replace failed evidence, or interpret a status question as a new execution request.
- Give brief progress updates during execution. Finish with achieved behavior,
  verification evidence, delivery location and concrete remaining limitations.

## Trust boundary

Rules govern the conversation agent; CLI gates enforce recorded transitions and
evidence freshness. These are not an OS sandbox around the parent conversation and
cannot keep a hostile agent/user from editing state or bypassing the CLI. Use the
host tool's permissions for containment. Do not promise that every arbitrary goal
can always complete: denied permissions, unavailable services and finite budgets
must produce honest, recoverable failure.


Rejected obligations may be replaced through `retire GOAL --input FILE`, preserving
the failed status and audit history. Require accepted same-task replacements, complete
criterion coverage and current contribution/evidence pins. Stale retirement restores
the barrier; refresh by appending a new validated receipt. Never use retirement to skip
latest substantive feedback consumption, milestone criteria or fresh final gates.
No rule here guarantees host-hook or daemon-driven automatic resumption.

Use `--explicit-skill` only for an actual explicit skill task, not technical memory
capture. Ordinary prompts may contribute scoped project topics under `context.md`
without starting a goal/session or consuming a gate/worker budget. A later task
references original topic evidence and does not convert it into user approval.
