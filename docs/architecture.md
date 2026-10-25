# Architecture

## Core decision

The user's entry point is a Claude Code or Codex conversation. This main session owns
goals, user feedback, scoped assignments, evidence checks and reporting.
Actual analysis, planning, implementation and writing are delegated to bounded workers.
The main session receives compact role results and artifact references; source analysis,
full worker output and peer exchanges stay in worker contexts and durable records.
Portable scripts select explicit economical profiles, stage worker candidates,
apply only assessed proposals, run deterministic
gates and persist state. An independent fresh invocation reviews
development. Other work has an evidence-backed content/completion check by the
orchestrator without a mandatory loop. There is no SDK, API-key requirement or daemon.
Worker CLIs can use either provider. Existing vendor/host restrictions on nested calls
are preserved: preflight must establish a usable worker, not bypass such restrictions.

This division makes the same workflow available in both environments while keeping
the user's responsibility to the goal and genuinely human-owned decisions. Calling
the CLI is an internal agent action, not a sequence of prompts the user must provide.

Harness benchmarking also has a standalone terminal entry point: `scripts/benchmark.py`.
It manages its own provider conversations; users do not need to open a chat or activate
the harness skill before running a benchmark.

An explicit `$loop-work <prompt>` or `/loop-work <prompt>` starts one task.
Only related corrections/status and compaction continue its binding. Completion or
abort releases routing; unrelated ordinary requests never create harness work.
A bare invocation asks for the missing prompt without state changes. A new explicit
prompt cannot silently replace an unfinished task. Board/human commands branch
before activation and preserve the existing binding.

The shared skill has Claude and Codex discovery files with implicit invocation off.
This is host-agent routing plus persisted state, not a keyword parser or message hook.

| Responsibility | Implementation |
| --- | --- |
| Shared behavioral policy | `rules/workflow.md`, `delegation.md`, `context.md`, `quality.md` |
| Bounded delegated work | `delegation.py`: explicit assignment, read-only worker, validated patch application |
| Work decomposition and profile selection | `routing.py`, `rules/routing.md`: goal-linked units, evidenced demand and bounded escalation |
| Worker teams | `team.py`: fixed roles, addressed peer messages, bounded turns and serialized application |
| Main-session recovery and steering | `orchestration.py`: compact capsules and versioned user feedback |
| Common goal setting and work | `work.py`, `rules/work.md`; development delegates to existing gates |
| Cross-project knowledge | `knowledge.py`; local SQLite, scoped records and dependency checks |
| Readable records and derived views | `writing.py`, `rules/writing.md`; deterministic Markdown, concise authored fields |
| Provider entry | `skills/loop-work/`, installed discovery files, managed AGENTS.md/CLAUDE.md blocks |
| Task binding | `harness.py`; explicit on with task ID, terminal release, shared SQLite session record |
| Harness outcome benchmarks | `benchmark.py`, `bench_transport.py`, `bench_report.py`; isolated paired runs, external grading, comparison gates |
| Goal completeness | `contract.py` validates structural traceability and decisions |
| Context reconstruction | `context.py` derives repository inventory, runtime evidence and next action |
| Reusable conversation analysis | `session.py` stores topics, decisions, dependency fingerprints and goal history |
| State/gates/recovery | `engine.py` |
| Independent review | `providers.py` selects the installed opposite CLI or a fresh same-provider call and validates structured output |
| Bounded subprocesses | `process.py`, argv arrays, stdin EOF, process-group timeout |
| Freshness/concurrency | `storage.py`, hashes, atomic JSON, POSIX flock |

## Installation adapters

The user-requested default `make install` also performs explicit workspace setup:
check for Obsidian, use existing Homebrew to install the app if absent, and prepare
`~/.loop-work/vault` plus its `.obsidian` directory without replacing existing files.
This is an installation-stage exception, not a Python runtime dependency. Low-level
link/copy installers and benchmarks do not run package setup unless explicitly passed
the workspace setup flag. App-wide vault registration, synchronization and plugin
configuration are unchanged. Existing selected knowledge records are backfilled during
setup; an empty database/session/goal is not created just for backfill. Export conflicts
are warnings with partial/failed view status, preserving notes without preventing skill
installation. App-install and unsafe-path errors still fail setup explicitly. Uninstall
retains the app, vault and knowledge data.

`make install` registers user discovery symlinks under `~/.agents/skills` and
`~/.claude/skills`, backed by owned adapters in `~/.local/share/loop-work/install`.
`make TARGET=/absolute/project install` instead uses project discovery paths and
`.loop/install`. Adapters share the canonical skill body; Claude-only metadata is
added during generation. Their `loop.py` enters the owned wrapper and rules/runtime
reference the source checkout. After moving the source, rerun install from its new
location to relink; the former path is unavailable until then.
Reinstall refreshes skill text/metadata; runtime/rule changes remain subject to existing
freshness seals. `make uninstall` removes the same scope's owned installation while
preserving unrelated instructions/settings/files. The legacy `--target` copy installer
remains available for sealed benchmarks and independent copies; linked uninstall/
migration intentionally does not remove legacy copied installations. Install/uninstall
are idempotent and reject conflicts before mutation. Project installs manage a
`.gitignore` block for host-specific links, runtime and state. Uninstall retains goals,
state and knowledge; if state remains, it retains the `/.loop/state/` ignore.

`harness_digest` fingerprints package code, built-in rules and canonical skill metadata
independently of target paths. Source changes invalidate frozen development evidence
and dependent caches, including legacy caches without a stamp. Pathless user decisions
retain their scope and remain reusable.

Hosts may retain already-loaded skill text after install changes: use a new conversation
or host reload. An active conversation whose entrypoint disappears stops routing;
it never selects another runtime or silently reactivates.

Legacy loop-dev links require explicit `scripts/install.py --uninstall-legacy` before
installing loop-work; ownership checks and preservation apply unchanged. Old linked
entrypoints fail closed with migration guidance. The previous knowledge home remains
in use when its database exists; two existing databases require an explicit home.
No records or artifact paths are moved, and `.loop/` state paths remain stable.
For a fresh knowledge home with no existing database, the default is
`~/.loop-work/data`; explicit knowledge-home/environment selection takes priority.
Existing `~/.local/share/loop-work` or legacy `loop-dev` databases retain their paths.
The single `~/.loop-work/vault` is an additional document view, not a data migration.

## Task binding

Create the identified task with `work open --explicit-skill` or development `init --explicit-skill` first, then run
`harness on --provider PROVIDER --session SESSION_ID --task TASK_ID`.
The task must belong to that provider/session. `harness status ID` reads only that
owned session; `harness off ID` releases routing without resetting tasks or budgets.
The raw binding records `scope=task`, `inputs=related` and `task_id`. Legacy
conversation-wide enabled flags are inactive under this protocol. Completion/abort
stores release metadata with the task transition. A blocker/pause retains the task,
not permission to route unrelated requests, and consumes no reset budget.

Related input, worker results and compaction restore
`orchestration context SESSION --task TASK_ID`. Carry `{session_id, task_id,
knowledge_home, rules_home, entrypoint}`. Directory changes preserve that task.
No latest-session pointer or project knowledge establishes new invocation authority.
A second explicit task uses a separate session while another task remains active.

Low-level engine and work commands remain usable independently; `harness on` is an
explicit agent action, not cryptographic evidence that a vendor skill was invoked.
The cooperative host must honor routing and off requests. The scripts cannot intercept
all messages, recover an erased binding without ownership evidence, or override host
permissions. An off input stops further automatic dispatch when the host handles it;
it does not retroactively cancel a synchronous subprocess. Rule fingerprints include
the installed harness skill and metadata, including ignored files, so edits invalidate
frozen development evidence and dependent knowledge. Workers cannot edit `.agents/`.

## Assignment boundary

`delegate GOAL` and `work delegate TASK` run one explicit assignment from a JSON input.
The same protocol is used for both providers: instruction, read paths, exact write
paths, prohibitions, named deliverables, completion criteria, selected knowledge IDs
and prerequisite assignment IDs. Its `planning` records parent criterion IDs, boundary
rationale, verification and complexity/risk/uncertainty with supporting evidence.
`rules/routing.md` owns this schema. A common task with multiple roots must select one
root per invocation. Worker status is distinct from parent goal status.

Both `delegate GOAL` and `work delegate TASK` accept `--check`. The read-only
preflight shares dispatch validation and reads the existing knowledge database
without registration, derived views, attempts, budgets or provider calls. It reports
structured diagnostics/remediation, or whether the actual command would dispatch
or reuse existing evidence. Success is current setup readiness only, not completion
or model correctness. Actual dispatch repeats validation, including stale candidate
recovery, runtime/parent/feedback/source seals and routing/budget constraints.
Existing read inputs must be visible. Absent declared paths produce structured
warnings rather than blocking existing absence-inspection behavior; the coordinator
determines whether an absent input is required. Existing directory scope also supports
absence checks. Compiler logs outside visible source need supplied exact diagnostic notes.

Workers receive only selected current knowledge and fresh prerequisite outputs, plus
the parent goal, decisions, initial diagnosis, notes, latest gate and prior failure as
context. Source files are indexed inside explicit read scopes; applicable rules are
added to that list. Context is evidence, never additional delegated authority. Workers
cannot recursively invoke the harness, ask users, redelegate or change rules/state.
Missing scope or information returns a precise blocker to the orchestrator.
Handoffs preserve original input/output types, return values, errors and data
preservation requirements. Clear bounded work can combine necessary inspection and
implementation in one worker unit, while retaining tests and independent gates.
Required preflight units must be resolved before start; `goal_setting` units cannot
be rerun afterward. A blocker preserves activation and is not a request to disable.

Worker packets describe their file-pin format: regular files use the SHA-256 of
canonical JSON containing raw-content SHA-256 and the executable flag, rather than
raw-content SHA-256 alone. The packet supplies a recomputation recipe. Claimed drift
must be checked with that algorithm; source and executable-mode changes remain
subject to the same freshness checks. Process execution defaults Python bytecode
writes off to avoid incidental cache files invalidating snapshots, preserving explicit
host environment values and per-call overrides. Source changes still invalidate gates.

Both CLI transports are read-only. Proposed edits are complete UTF-8 file contents
or deletions with original hashes; schema v2 also permits exact-base UTF-8 byte patches
with a pinned result hash (see operations). A result first becomes a `candidate`; it cannot
edit source, become prerequisite output, promote findings or relay peer messages.
The main session reads the candidate and current goal/criterion evidence, then calls
`assess GOAL` or `work assess TASK`. This is an internal decision, without a user
approval checkpoint or a compulsory second model judge. Each accepted check needs
hash-pinned evidence outside the candidate attempt directory; self-report is insufficient.
The runtime checks identity, digests and freshness; the main session judges meaning.

Acceptance rechecks all proposals before the first edit:
exact allowed paths, no wildcards/traversal/symlinks, no instruction/provider/state
edits, no ignored write targets, matching hashes and unchanged parent/source state.
The applier records originals, preserves modes and uses atomic replacement per file.
After apply it checks for unexpected source, branch, rule or parent changes. File
operations are not a multi-file transaction: a filesystem error can leave partial
edits, which remain recorded with originals. Nothing resets or cleans user changes.
Rejection quarantines the whole candidate and preserves audit evidence. Legacy v1
quality rejection selects a stronger allowed profile. V2 records rejection origin and
strategy: worker-output failures escalate; contract/fixture repairs retain the profile
and require a linked standalone request revision. Transport and stale-evidence failures
do not establish model-quality failure. Every retry remains within shared budgets and
receives a bounded failure reason, without adopting rejected content as facts. Repeating a pending candidate
returns its references without spending another worker call.

Assignment IDs are immutable and bound to a working location. Repeating a completed
request reuses it only with the same parent, source and selected handoff evidence.
Dependencies must have a successful result that still matches their own location,
including handoffs across directories in one task. Read sets support scoped context selection; they are not per-file
OS access controls. Provider permissions and host policy still govern actual reads,
external tools and hooks. Semantic compliance remains an orchestrator/reviewer check.

Task and location locks serialize workers; call budgets are shared across all IDs
in a task. At most three attempts per ID, default 40 calls per task, and per-call
(default 600 seconds) and working-time budgets apply. Retry/resume retains counts;
preflight clarification does not consume working elapsed time. Recovery of an
interrupted call requires inspection and an explicit recovery reason.

Every attempt retains its profile, prompt, schema, process logs and available result/originals.
SQLite records current assignments and prior versions; context includes a compact
index and Markdown is derived from the same records. Findings become task-scoped
drafts only after acceptance, never automatic facts. The orchestrator reconciles evidence before promotion.
`done` never changes a parent goal to completed; development gates and common content
checks retain that responsibility.

## Economical profile selection

Goal setting freezes `execution.routing`; an optional `LOOP_ROUTING_PROFILE` imports
the policy before the seal. Profiles declare provider, concrete model, explicit effort,
relative capability and cost ranks. Dispatch never falls back to CLI defaults or
rereads a changed environment. Missing support or configuration blocks honestly.

The highest requirement from assignment complexity, risk and uncertainty sets the
capability floor. The runtime selects the least costly eligible profile within the
task's worker provider, using capability rank and profile ID as deterministic ties.
Higher initial demand needs factual evidence. A cohesive small task stays one unit;
teams require distinct verifiable contributions, acyclic dependencies and one writer
per file. Schema checks do not establish that a split is useful; the main session does.

A recorded quality rejection permits a strictly higher capability and different
model/effort on the same provider, retaining all budgets. Authentication, permission,
timeouts, stale input and ambiguous scope are blockers, not escalation evidence.
Development review pins the installed opposite provider, or the worker provider when
the opposite CLI is absent, during plan-review. Calls are fresh and read-only; a failed
selected CLI never causes a provider switch. Selection mode and availability are retained
in gate routing provenance. Use a least-cost suitable explicit profile:
medium by default, high for evidenced high complexity, risk or uncertainty. Missing eligibility
does not lower the review requirement. Ranks are configuration, not measured cost or
capability; requested settings are recorded without claiming a host honored uncapped effort.

## Cooperative worker teams

`team GOAL --input FILE [--recover REASON]` and
`work team TASK --input FILE [--path ROOT] [--recover REASON]` run an orchestrator-owned
plan through `Team(knowledge, task_id, root).run(plan, recover=None)`. The plan assigns
2–12 distinct contributions using the assignment schema; `rules/delegation.md` owns its wire
contract. Each role gets an isolated, ephemeral CLI context on each turn, restored
from its assignment, selected current context and addressed messages. Roles and scopes
stay fixed across turns. A worker cannot create roles, redelegate or change the goal.

Workers can return bounded questions, answers and findings to named peers. The
coordinator validates recipients, scope, answer links and source evidence. It returns
`awaiting_assessment` with the current candidate. Only accepted messages enter the
peer inbox. After internal assessment, the main session repeats the same team command
to continue; no user prompt or recovery flag is needed for this normal boundary.
The coordinator routes the exchange to the addressed worker's next call.
Messages are draft data, never user instructions or permission to widen a read/write
scope. Unsupported requests become a blocker rather than implicit reassignment.
The main session receives compact member results and references to full artifacts,
so it need not relay or reload every exchange.

The portable implementation serializes worker execution and file application. It
does not depend on vendor-native real-time chat or concurrent writers. Task-wide call
and elapsed budgets, per-assignment attempt limits and a finite team turn limit all
remain in force; recovery cannot reset them. Existing `delegate` remains appropriate
for a single bounded unit. Team completion does not replace development checkpoints,
fresh independent final review or common content/completion checks.

## Compact orchestration and user feedback

`orchestration context SESSION [--task TASK] [--limit 1..5]` produces a recovery capsule
of at most 16 KiB. It exposes current control state, task/worker summaries, selected
profiles and candidate/assessment references, counts and
artifact references without source, transcript, log or output bodies. Full evidence
remains on disk and is loaded only to answer a concrete question. The main session
keeps its binding and the latest capsule; it does not maintain competing handoff files
or replay the full history after each input. Older detailed context commands remain
available for targeted investigation, especially inside worker assignments.

User steering is persisted with `orchestration feedback` and an expected control
version. Immutable feedback IDs make identical retries idempotent; new records reject
stale versions. The record keeps the original input reference, scope and any explicitly
superseded feedback. Affected workers receive the current feedback revision and that
revision is checked before applying their proposals. `rules/context.md` defines the
feedback fields and recovery steps.

Pause/resume controls apply to the identified task; a progress question is not a
resume. A scope change blocks the old task and requires a new goal, without editing
its frozen goal or acceptance. Peer messages and historical summaries cannot create
user authority. Durable capsules reduce the material loaded by the main session;
they do not guarantee a host compaction frequency or improved live-model outcomes.

## Goal versus current code

`contract.json` describes the desired outcome. `discovery.json` describes code and
rule evidence at preflight, including a gap for every requirement. A new repository,
prototype or nearly complete product can share the same target. The amount of work
changes; acceptance does not. The plan reviewer checks that the target is actionable,
not that it has already been implemented.

The preflight decision areas are scope, architecture, data, interface, dependencies,
security, verification, operations, delivery and autonomy. The model may resolve
technical facts through investigation and choices within existing delegated authority.
It asks the user only about material decisions that cannot be established this way.

Artifact discovery follows the requested result: requirements may lead to a PRD,
a PRD to a detailed plan/mockup, those artifacts to frontend or backend code, and
backend API evidence to frontend integration. Backend specs and whole-system
architecture can also be independent creation/refresh goals. These are selectable
work shapes, not an obligatory seven-stage pipeline. `rules/context.md` defines the
input/consumer checks. The main session uses scoped knowledge and delegated source
inspection to recover existing context, reconcile contradictions and carry user
feedback into the needed outputs. It asks only unresolved human-owned choices before
execution instead of asking the user to narrate discoverable context again.

Cross-project handoffs retain project/location identity and source evidence. Derived
knowledge lists its actual source dependencies so changes can mark it stale. The
orchestrator identifies and refreshes affected documents/code within authorized scope;
the runtime does not infer a semantic artifact graph or silently rewrite consumers.
Current code evidence measures implementation gaps and does not replace the desired
product outcome or override an applicable user decision.
Detailed knowledge/development contexts provide a bounded `sources` index from observed
paths and fingerprints, ranked with task title/goal hints. It reads no artifact bodies
and covers only selected locations. Hints are navigation, not validated artifact roles
or an exhaustive search; the assigned worker must inspect their meaning and currentness.

## Common work and knowledge

Non-development work moves from `goal_setting` to `working` to `completed`, with
explicit `blocked` and `aborted` outcomes. A goal records outcome, deliverable,
criteria and scoped decisions. Unresolved questions block start; the goal is sealed
on start. Finish requires evidence for each criterion. It invokes no provider or
test process and does not attest independently that a referenced output is correct.
The active agent inspects the deliverable and records that assessment. Failed criteria
remain working; there is no prescribed review/repair cycle or iteration count.

SQLite records projects, checkouts, sessions, tasks and knowledge topics. Origin
normalization groups Git clones without storing URL credentials; checkout identity
and observations keep their sources separate. Non-Git directories are supported.
Same-conversation IDs can cross roots. Scoped decisions retain original authority;
global/project knowledge can be reused across conversations without adopting a
different conversation's session binding. Drafts/hypotheses never become facts on finish.

Knowledge updates compare the read observation before and after preparation. SQLite
transactions and optimistic task version tokens protect concurrent writers; result
and new knowledge commit together. Identical topic content/dependencies do not create
another historical revision. Development remains authoritative in its repository
state: the shared task record mirrors progress, and common finish rejects it.
Common development context refreshes repository state before reporting freshness.

Markdown views are derived from committed data. Rendering never asks a second
model to invent a parallel explanation. Topics have a bounded one-line conclusion,
optional implication/details/uncertainty, scope/status and exact evidence references.
Full JSON retains all references; context is paged with counts and retrieval commands.
Documents are replaced only when content changes. A view export failure leaves
committed data intact; `knowledge get`/`work context` regenerates it. Confirmed labels
alone do not establish freshness; applicability is computed on context reads.
These checks constrain shape and duplication, not factual or semantic writing quality.

The [completion-use retrospective](../rules/writing.md#작업-완료-후-하네스-사용-회고) is an agent
instruction, not a new runtime hook or gate. The coordinator reuses existing task/session
provenance and knowledge context/remember/get to retain concise Korean observations and
separate hypotheses; existing derived-view ownership and export diagnostics still apply.

## Development state machine

| State | Entry condition | Allowed progress |
| --- | --- | --- |
| draft | init | Investigate, clarify, edit contract/discovery, repeat plan review |
| ready | valid contract + current passing independent plan review | start on the reviewed snapshot |
| running | frozen inputs and code unchanged since preflight | Implement, note discoveries, checkpoint, finish |
| blocked | External/protocol failure, mutation, exhausted budget, explicit blocker | Resume if retryable; otherwise abort/new preflight |
| completed | All milestones + fresh all-checks pass + full review pass | Report while evidence remains current |
| aborted | Explicit abort with reason | Report retained evidence; new goal can own the tree |

Only one running/blocked goal owns a working tree. A repository-level file lock also
prevents concurrent CLI mutations. It does not stop external editors or another
agent from editing files; snapshot comparisons reject evidence if inputs change
during checks/review.

## Frozen inputs and freshness

Freeze records canonical hashes of the target, diagnosis, decisions, declared rules,
discovered repository instruction files and gate-engine modules. New nested AGENTS
or CLAUDE files invalidate the seal too. Existing project-local provider settings are
hashed without copying their content into prompts. Global and managed provider
configuration remains outside the seal; the host remains responsible for its policy.

The work snapshot includes Git HEAD and hashes of tracked, deleted and untracked
nonignored files, including executable bits and symlink targets. Runtime artifacts
under `.loop/state/` are excluded. Ignored build caches/output are not verification
inputs. Declare critical ignored rules explicitly; do not keep implementation source
or acceptance fixtures ignored. Submodules are rejected rather than silently omitted;
run separate goals inside them.

Contracts optionally freeze `execution.check_failure_policy`: new templates use
`fail_fast`, explicit `diagnostic_continue` and field-absent legacy contracts continue.
Actual `checks` and `not_run_checks` are separate; no skipped suffix can pass. The
[workflow rule](../rules/workflow.md#4-execute-the-entire-loop-without-further-user-questions)
owns scheduling and scoped GUI planning, not a new runtime gate or reviewer role.

After successful checkpoints, subsequent implementation may change earlier files.
Final finish always re-runs every check and obtains a new review of every acceptance
criterion on the final snapshot. An edit or commit after completion makes `status`
report `evidence_current: false` and instructs the agent not to claim current completion.
The old completed record is retained as historical evidence.

## Detailed context behind the capsule

For targeted investigation, `context` reconstructs target, original gap analysis,
rule paths, source inventory, build manifest excerpts, test paths, milestone progress,
latest gate and accumulated
discoveries. Its `next` action routes the active conversation to clarification,
implementation, final verification, recovery or reporting.

The main session starts from the compact orchestration capsule, then uses a specific
reference when an assignment or evidence check needs more detail. It
inspects returned evidence, adjusts tactics within the frozen target, and passes the accumulated
notes to the next independent review. Review failures become repair instructions, and
test failures retain exact commands and log paths. This replaces the user's serial
context-feeding with an evidence-driven agent loop.

Notes are append-only through the CLI and can change tactics, not the frozen scope,
commands, business rules or authority. A discovery that truly requires a new business
decision becomes a blocker and a separate preflight goal rather than a mid-run question.

## Analysis reused within a conversation

A session retains knowledge history, but only an explicitly invoked task is bound.
Create the task before binding it; related commands pass
`--session`. Low-level `init` or `session open` without an ID creates an inactive
session. The agent carries the ID, absolute entrypoint, rules home and knowledge home in handoffs.
New conversations use new IDs; the engine never selects the latest cache as a proxy
for session ownership. Identified tasks recover bindings only for their own resumed
conversation. Providers must match the binding.
There is no undocumented host-session lookup, global pointer or vendor-specific hook.

`session.json` contains indexed topic summaries and original evidence, scope/basis
of decisions, linked goals and the last observation. `context.json` separates reusable
entries, stale entries with changed dependencies, other-goal entries and historical
goal records. Goal `context` embeds this detailed view for targeted reads; it is not a
default main-session prompt. Decisions and execution notes are archived automatically;
passing preflight/review evidence updates one broad fallback summary per goal. Fresh
implementation evidence replaces its preflight summary. The agent also persists focused
topics while investigating, answering decisions and editing to preserve granular reuse.

Dependencies are explicit file paths or directory prefixes. Prefixes detect additions,
deletions and renames; exact missing paths can record absence. Fingerprints include
working-tree changes and rule hashes, not just HEAD. All topics are reconciled after a
branch or rule change. A content-preserving commit retains code analysis, while the
existing completion gate still rejects changed HEAD. Creating `.loop/goals/` metadata
does not invalidate root-wide source summaries; an explicitly named goal file can still
be a dependency. Cached manifest excerpts are read again only if their hashes change.

`remember --observed` rejects a repository revision changed since the analysis context
was read. Updates preserve previous entries in history. Refresh only classifies freshness;
it cannot re-stamp a stale summary. The agent re-investigates relevant changed dependencies
and writes a new summary. Unaffected topics retain their evidence/time. It does not
re-investigate unrelated historical topics merely because they are stale.

Decisions preserve `user`, `repository-rule` or `delegated` basis and an `applies_to`
boundary. Session-wide preferences can survive unrelated code edits; goal-scoped answers
are presented separately and never promoted automatically. Earlier applicable answers
are carried into new contracts instead of being asked again. Whether a new product scope
fits an answer remains a semantic judgment for the agent and preflight reviewer.

Memory is derived context, not an authority source or verification pass. Final tests and
independent reviews remain fresh; reviewers receive reusable summaries as navigation
hints and must inspect actual behavior. Correct invalidation depends on complete declared
dependencies. Ignored application source and external runtime/service changes are outside
that model; explicitly declared ignored rules are hashed, and external facts require fresh
checks. Rules instruct agents to record the complete read set and directory-level absence.

Development session caches remain under ignored `.loop/state/`, protected by the
repository lock and atomic writes. Entries are imported into shared knowledge with
their original dependency stamps; import cannot renew stale evidence. Shared knowledge
uses an explicit `--knowledge-home`/`LOOP_KB_HOME` or reuses existing loop-work/loop-dev
databases; only a fresh default uses `~/.loop-work/data/`, outside source trees. Neither
store changes frozen contracts. Older goal state acquires a stable session binding on
first context read. Reconciliation is request-driven, not a background watcher.

## Obsidian workspace views

The workspace helper keeps the single vault at `~/.loop-work/vault`; it does not
move an existing database, change app-wide registration, or configure synchronization.
The runtime reads and writes a single Korean layout 3. Start at `안내.md`, then
`프로젝트/<short name--8-character hash>/목록.md`. Project notes are `프로젝트 안내.md`;
reusable conclusions live under `지식/`. Work folders use
`작업/<short name--8-character hash>/진행 현황.md` and human-owned `작업 문서.md`.
`기록/중간/` and `기록/완료/` retain cutoff snapshots; scoped records use the Korean
`위임`, `협업`, `사용자 검토`, `피드백` and `종료` folders. Global knowledge is in
`공통 지식/`; new personal notes belong in `개인 메모/`. Existing README/notes/settings
are preserved. One project list replaces duplicate topic/task index files.

The suffix disambiguates paths; metadata retains complete identities. Frozen mappings
prevent path churn after title changes. The outer ownership manifest stays version 1
with layout_version=3 and document envelope version 3. A separate preserving conversion
tool handles old exports; current reader/writer code has no legacy-format branch or
alias. Edited, missing or unowned files cannot regain authority through a fresh copy.
Conversion retains original managed documents, human wiki text and ownership evidence
in a vault-external backup, then removes the old managed layout from the vault tree.
Only generated source links in wiki bodies change; unowned notes and settings stay
in place. Conflicted, missing or reserved paths reject the entire conversion.

Optional topic `title` is a one-line bounded presentation field, preserved by knowledge
recording. New authoring requires a concise Korean noun phrase of at most 60 characters.
Historical records need no statement rewrite; `display_title` shows a marked short
excerpt, while the complete `summary` appears under `결론`. Documents present purpose,
observations, scope/uncertainty and evidence in reading order. Long identifiers and raw
JSON belong in folded original/verification details. Human request questions, every
choice and response remain readable with literal line boundaries; their full JSON is
also retained. Rendering does not change execution or approval authority.

Cutoff/source information remains part of each view. An authoritative completed record
can produce a completion snapshot; that historical file never establishes current source
freshness or grants QA authority. Topics and scoped worker/control records are separate
derived views; human notes remain outside generated-file ownership.

Selected task/topic/delegation/team/human-request/feedback/retirement writes enqueue
export only after their DB transaction commits. Standard shared knowledge homes use
the single vault automatically; arbitrary custom/temp homes default to disabled, with
explicit `vault_home` API opt-in. `sync_vault()` rebuilds existing records and task
history without model calls. `vault_status()` and `vault-export-status.json` expose
view-delivery diagnostics independently of task completion. A stale completed current
record is shown as interim while earlier final snapshots retain their historical boundary.

The exporter uses a knowledge-home ownership manifest to update only its pinned
files, preserving edited/unowned notes and Obsidian settings. Export failures leave
committed DB/JSON state intact and do not prevent authorized work. Local evidence
references are labeled as such; copying the vault does not copy `.loop` audit logs
or the source checkout. Vault Markdown is the board's display/document data source. The runtime DB/JSON
retain execution, permission and verification authority. Markdown editing is not an
approval channel or a gate override. No vendor SDK, Python package or running
Obsidian app is required in the harness execution path.

## Review protocol

| Implementation worker | Read-only reviewer |
| --- | --- |
| Claude Code | `codex --ask-for-approval never --sandbox read-only exec ...` |
| Codex | `claude -p --permission-mode dontAsk --tools Read,Glob,Grep ...` |

Each review is a new invocation with no resumed conversation. Its prompt identifies
the reviewer role, frozen criteria, original gaps, rules, changed paths, verification
logs and execution notes. Reviewer instructions explicitly prohibit recursively
starting the workflow from AGENTS/CLAUDE instructions. Claude's tool list is restricted
to reads and MCP tools are excluded for this invocation. Codex uses its read-only
sandbox and existing host configuration; external tools remain subject to host policy.
The engine detects working-tree mutations, but is not an isolation mechanism for
arbitrary externally configured tools or hooks.

Both adapters request the same JSON schema. Runtime validation rejects missing
coverage, duplicate/unknown IDs, blank evidence, malformed findings, execution-time
questions, and pass verdicts with findings. Every criterion needs a coverage record.
All finding severities block. A denied Claude permission or failed process blocks the
review. The model cannot set the persisted completed state through a review result.

## Failure and durability

- Finite attempt and wall-time budgets apply across resume; they cannot be reset by
  ordinary retry. Gate attempts are saved before subprocess invocation.
- Each command closes interactive stdin, inherits configured credentials, captures
  stdout/stderr and has a timeout. Timeout/interruption terminates its process group.
- State JSON is atomically replaced and each event has its own atomic file. An
  unfinished `inflight` gate is detected and requires inspecting logs before resume.
- Source, logs and user edits are retained on failure. There is no reset/clean/force
  push/automatic deletion of the working tree.
- The runtime directory is local and Git-ignored. Cross-machine or clean-clone resume
  requires transferring state intentionally; a goal definition alone is not evidence.

## Harness outcome evaluation

Benchmarking is separate from the harness's own completion gates. `scripts/benchmark.py`
invokes `bench check`: freeze configuration, run, judge, gate and produce improvements.
`bench_check.py` owns this sequence and records an inconclusive result when a phase fails;
an unjudged run does not stop the sequence. `bench plan/run`
freezes a suite and current harness file snapshot; every case/provider/
repetition runs plain and candidate in seeded random order. No baseline commit is selected
or read. The source snapshot includes uncommitted changes and is hashed automatically. Inputs, model
profiles and budgets match. Trial-local CLI wrappers enforce model IDs and efforts and reserve
a shared call budget for the conversation and its nested workers/reviewers. Existing
host policy and authentication remain in effect. No SDK or global hook is installed.
By default each provider has one pinned model/effort pair. Optional `--routing-profile`
freezes the same allowed pool for both arms, including all pinned root pairs; nested
calls may select only an allowed pair. The independently fixed judge is unchanged.
Both arms receive the policy before goal sealing. Mode/policy changes start a separate
temporal baseline. Per-pair call/failure counts are observable; rejection/escalation
needs linked attempt/assessment evidence, and configured ranks do not establish billing.
The suite must contain at least two distinct goal types. Session reuse is a scenario
dimension; the starter session case counts as explanation, alongside development and document.

Each trial gets fresh repositories, knowledge and an explicitly identified provider
conversation. Later turns resume that conversation, including directory transitions.
The first task turn invokes its installed skill; related later turns continue that task.
Completion releases routing; a new task requires another explicit invocation.
New manifests identify `activation_protocol=task-scoped-v1`; this setting enters
the temporal comparison profile, so conversation-wide legacy baselines cannot be
compared as unchanged experiments. The current single-task benchmark verifies raw
task scope/identity, actual task phase and terminal release metadata; extra tasks,
missing bindings and a contaminated plain control are rejected. The final turn
requires actual completed phase plus matching disabled/release metadata; blocked
or aborted results are honest noncompletion, not suite success. This scenario
constraint does not prohibit a conceptual user task from spanning multiple roots. Installation
and graders live outside the timed scenario. Timeout cleanup targets the launched
process group and observed descendants, including nested groups; it is not an OS sandbox.

After execution, an external checker runs on a separate artifact copy. A random-ID
packet contains only requests, answers, declared fixture source context/changes, deliverables and anchored rubric
criteria. A fixed read-only judge independently assesses each packet at least twice.
The full check freezes judge provider/model/effort/repetitions before running any trial;
later assessments must match that profile. Both vendors' results use the same judge.
Disagreements use the lower score. Human assessments use the same packet-bound schema.
Treatment inference from prose and model judging errors remain possible.

Reports compare each candidate to its plain counterpart and retain separate quality, user
intervention, duration and available usage evidence. Mandatory outcomes, a quality
floor, paired losses and excess overhead block promotion regardless of average gain.
Incomplete execution/evidence, failed controls and fake-CLI runs cannot establish an
improvement. `bench gate` rechecks hashes of artifacts, logs, candidate and suite.
Bootstrap intervals describe the selected paired observations, not unseen tasks.
`bench_improvements.py` deterministically groups repeated failures, reports each goal
type's coverage and comparison, and ranks setup/evidence, quality/intervention and
duration issues. Observations, causal hypotheses, related rules, bounded next changes
and revalidation remain distinct JSON fields. The human view shows at most five items;
the full JSON preserves evidence without additional model calls. No rule change is
invented for equal valid results, and a failed final gate cannot leave a passing check summary.

`bench_evolution.py` keeps automatic before/after baselines outside the source and suite.
Before changing the harness, the orchestrator establishes a passing live measurement
of the starting source if one is unavailable. Each full check selects the last passing
run with identical suite hash, models/efforts, judge settings, providers, repeats,
seed, budgets, host configuration and CLI versions. A new profile starts a separate
series and cannot establish improvement over a different profile.
The after run still executes only plain/candidate; the before run's sealed evidence
is reused, without another arm or Git revision lookup. Reports pair case/provider/
repeat outcomes across runs and show quality, elapsed time, calls, extra questions
and the change in on/off benefit. Any criterion loss, additional questions or duration
limit violation blocks advancement. Improvement requires positive descriptive intervals
for both candidate quality and the change in on/off benefit, with a changed source.
Ties are non-regressing, never improved. Same-source reruns do not replace a baseline.

`evolution.json` freezes the predecessor and its manifest, index, judgments, final check
and comparison seals. `bench gate` revalidates that evidence as well as the current
source/suite; removing a temporal comparison cannot restore an on/off-only pass.
`baselines.json` stores one accepted pointer per profile. A short file lock and comparison
with the pointer observed before execution prevent concurrent runs from silently replacing
each other. All reports and final checks are written before advancing the pointer.
Regression, missing evidence and simulations retain the old pointer. Old run directories
remain required evidence. The deterministic improvement report includes both comparisons;
no extra model calls, rule rewriting, merge or deployment follow from history updates.

`bench proposal` stores a bounded rule hypothesis with affected cases, their scores,
regressions and frozen source/suite hashes. It does not edit rules automatically.
The orchestrator delegates a scoped change and reruns both conditions, calibration
and holdout cases under unchanged criteria. Public starter holdouts are regression
examples; broader claims need representative independently held tasks. Unit CI does
not run paid providers or substitute for this live quality gate. See `rules/benchmark.md`.

Version 2 manifests explicitly fix `arms` to `plain` and `candidate`. Historical
version 1 reports keep their original three conditions when read; a missing historical
reference cannot be silently treated as a complete two-condition experiment.

## Explicit limits

Scripts enforce structure, transition ordering, bounded execution and evidence
freshness. Models judge completeness and investigate sources. Neither proves that
arbitrary software is bug-free or that unavailable services can be made available.
The workflow is cooperative, not tamper-proof: a process that can modify the repo
can also edit state or bypass the scripts. Existing host permissions remain essential.

The implementation deliberately keeps commit/PR/deployment outside automatic engine
side effects. The active conversation delegates pre-authorized delivery actions to explicit host
tool calls and reports their actual outcome. Read-only workers cannot publish. Core `completed` means verified development;
it does not itself assert that a remote deployment or merge occurred.

Benchmark managed provider resolution uses the trial wrapper's absolute path when
`LOOP_BENCH_PROFILE` is present, independently of tool-shell PATH reconstruction.
Conversation, development state and common-work knowledge/runs process receipts
and prompt hashes are reconciled with the call ledger;
missing or duplicate managed entries invalidate accounting. Legitimate ledger-only
nested/structured calls remain counted with separate coverage diagnostics. This covers managed runtime calls,
not arbitrary external execution. Per-turn configuration fingerprints include full resolved contents, link identity and
non-atime filesystem metadata to retain ordinary change-and-restore evidence. This
cooperative boundary guard tracks nearest-existing-directory metadata and ancestor
symlink identities for absent files; unrelated sibling creation/deletion can therefore
conservatively invalidate a run. Unstable observations fail closed. It does not promise continuous OS-event or adversarial
metadata-restoration detection. It retains observed host drift as failed evidence without copying or rewriting host configuration.


## Evidence-bearing lifecycle and assignment v2

Public `block GOAL --input FILE` and `work block TASK --input FILE` require a
version-1 typed decision with kind, reason, task scope, retryability and evidence.
Reason-only public blocking is rejected. External blockers require current file pins;
a user pause requires recorded explicit pause feedback; budget exhaustion checks actual
remaining calls/time and unfinished gate attempts. Three failures of one assignment do
not exhaust the task. Proven internal gate failures use a separate engine path. This
validates classification, freshness and counters, not the semantic truth of arbitrary
prose, and promises no host hook, daemon or automatic resumption.

V2 fixes criterion execution ownership (`worker` or `orchestrator`) and verification
mode. Root-owned checks remain pending (`satisfied: null`) in worker output; acceptance
still needs every check true with external pinned evidence. Read-only portable workers
cannot execute `candidate_test`; choose source inspection or an orchestrator receipt.
Standalone revisions preserve work-unit identity, exact previous-request hash, finite
attempts and immutable history; teams currently support revision 1 only. Repairs cannot
weaken criteria, parent contribution, prohibitions or demand. A cumulative correction
ledger retains prior rows and appends explicit superseding corrections. Its references
grant no read authority or reuse authority for rejected content.

`retire GOAL --input FILE` / `work retire TASK --input FILE` records an accepted
replacement graph for rejected, blocked or failed obligations without changing their
original status. Complete criterion coverage, immutable result/assessment receipts and
current contribution/evidence pins are checked; self-links, cycles, unaccepted or stale
replacements fail. Independent consumer edits need not preserve a producer's obsolete
whole-checkout digest. Stale proof restores the completion barrier. Repeating retirement
with valid new proof appends a receipt and preserves earlier receipt hashes. Retirement
does not bypass latest substantive feedback consumption, acceptance criteria or fresh
final gates. Context exposes original status and valid/stale retirement separately.

Routing retry observations distinguish assignment attempt caps, task calls/time, profile
ceilings and recovery requirements; an exhausted assignment is not a global stop. Review
demand retains high complexity, risk or uncertainty from relevant work; scope counts and
languages are descriptive metadata, not an experimentally established cost model.

## Human-owned requests

`human.py` stores task-bound decisions, approvals and manual-action requests in the
same knowledge home. The first `human` argument of `skills/loop-work/` routes to
`rules/human.md` before activation. It exposes the desk to either provider without
changing activation, session ownership or task identity, and creates no goal. Only
this mode reads its detailed human instructions; the skill remains explicit-only.
Responses preserve the person's original text and use optimistic revision checks;
an answer does not run an action. Only the allowlisted `resume_task` action can be
manually executed, with existing pause, integrity and finite-budget checks preserved.
It cannot run arbitrary commands or confer external authorization, QA completion or
merge authority. The desk does not dispatch worker/model calls.

The text `human list|show|request|respond|execute` CLI uses the same desk operations as the native Board. Linked/copied installations retain the single loop-work skill, human rule and backend; no standalone human UI assets, separate skill, global hooks or login changes are required.

## Vault-backed board

The first `board` skill argument routes to `rules/board.md` before activation; bare
board selects open. On macOS, `board open` shows the Tauri 2/React desktop window over the authenticated internal API. `board start` prepares only a managed backend, without app/browser launch. Linux retains the non-GUI CLI. It preserves the existing
entrypoint, knowledge home and session/task binding and never turns the harness on
or off, selects a recent session, or creates a goal. The legacy human CLI remains
compatible for request management.

Task cards, details, tracking text and request documents come from vault Markdown,
not an alternate DB dashboard. Task current/human-request documents carry single-line
JSON `loop_work` frontmatter with version/kind/id/knowledge_home/record; the document
body remains the reading/editing surface. That metadata associates a document with
its original runtime request and does not transfer DB authority to Markdown. Missing/stale/unrecognized documents produce visible
diagnostics; edited notes remain intact. Runtime actions still validate the original
request, its revision, the displayed vault revision and execution authority. The real
person supplies original response text; approval recording and explicit resume execution
are distinct. A committed action followed by export failure is reported separately
and must never trigger an automatic action replay. Bounded no-symlink discovery also
shows uninventoried task current documents read-only only when a matching current
runtime task has explicit-loop-work provenance. Documents without an eligible runtime
task remain hidden; an absent ownership pin grants no action authority. History failures are isolated per file.
All Board views and mutation receipts, including unscoped views, omit per-record
export identifiers, titles, paths and errors, retaining only identifier-free aggregate
diagnostics. Detailed CLI/KB export diagnostics remain available independently. Only the existing allowlisted
resume action is executable; the board grants no shell, model dispatch or QA authority.

## Direct board steering for the bound task

`POST /api/tasks/:id/control` records the person's original pause/resume/correction/
constraint without requiring a pending human request. Exact operation ID, task,
control and vault revisions bind it to the current task. Resume clears feedback
pause only, not a blocked phase or execution caps. Runtime cancellation probes and
managed subprocess polling observe pause/off; no OS-wide cancellation or rollback
is claimed. The UI polls visible state without overlapping reads and preserves
in-progress drafts. These controls do not activate unrelated conversation inputs.

## Vault language and preserved literals

Vault-only fixed labels/status explanations and boundaries render in Korean.
Authored task titles and knowledge/tracking conclusions follow `rules/writing.md`;
shared worker RESULT instructions carry the same policy. Explicit foreign-language
artifacts retain their requested language with separate Korean tracking. Original
user text, quotations, code, commands, refs, hashes, JSON keys/enums and proper names
remain unchanged; rendering does not translate old stored conclusions or infer facts.
No Hangul validator or new QA/eligibility/budget rule is introduced. Later normal
exports or an explicitly run install backfill may refresh generated views under
existing ownership guards; this change does not sync actual user vault contents.

## Project board and human-owned wiki documents

`Board.projects(query, sort, session_id, task_id, project_id)` derives the displayed
project inventory from actual scoped vault documents. Project selection applies in
`_discover`, `_scan`, `_history`, document lookup and action guards before replicas
are merged. A task shared by multiple projects therefore returns only the selected
project's current/history/request paths. Runtime task membership also prevents a
forged vault envelope from relabeling another runtime task into the selected project.
Names and task bodies are never synthesized from a hidden runtime dashboard.

Rows expose `display_title`, `board_state`, `state_label` and `review_reasons`.
Pending human work, feedback pause and stale completion take precedence over a
historical completed phase. Otherwise positively verified current completion, working/ready states and
technical stop/abort are distinct. Superseded requests do not keep the review queue
open. Common-work completion observations and recorded feedback stamps are checked
without mutating task state. A display classification does not grant QA authority.

`wiki.py` owns first-created, separately registered human prose. Its files use
`loop_work_wiki` frontmatter rather than the execution `loop_work` envelope. The
registry binds project/task IDs and frozen paths; it is not an alternative completion
record. Export creates a wiki only after verifying a current document and thereafter
preserves it, including external edits and deletion. `Board.wiki` and `save_wiki`
return actual Markdown content independently of the execution document's ownership
pin. The body API excludes the top display H1; serialization writes the display title
and H1 together without changing the runtime title, project identity or path.

Wiki saves use immutable operation receipts, an expected content/mode revision,
no-follow bounded reads and exclusive publication. The displaced inode is retained
as a recoverable revision. Detected concurrent replacements return `WikiConflict`
with status 409; a fresh read and explicit merge can then save. This is not a claim
of filesystem-wide CAS against noncooperating editors or of cross-file transactions.
Neither wiki text, title, a successful save nor a restored display file can bypass
original current/request pins, source freshness, finite budgets or human authority.

개발 완료의 Board 표시는 저장된 `result.evidence_current`만으로 결정하지 않는다.
작업의 실제 location root와 goal 범위에 있는 final `gate.json`을 크기 제한·심링크 비추종으로 읽어
통과·final 단계·현재 소스 snapshot·현재 피드백 revision을 읽기 전용으로 대조한다.
근거가 없거나 변경·안전성 검증 실패가 있으면 과거 완료 표시는 보존하되 사용자 확인 열에 둔다.
이 조회는 Engine 상태 갱신이나 DB·vault 쓰기를 수행하지 않는다.

위키 저장은 제출한 직렬화 문서를 독립된 revision 파일로 먼저 보존하고 게시 후
관측 fingerprint와 대조한 뒤에만 성공 receipt를 작성합니다. 게시 직후 외부 수정이
관측되면 충돌로 처리하여 외부 원문과 제출 초안이 서로 덮이지 않게 남깁니다.
사람 위키의 최초 스냅샷은 시점·한계를 표시하며, 이후 실행 지식은 연결된 generated
current/history 문서가 담당합니다. 목표와 실제 완료 결과를 사람 본문에 자동 덮어쓰지 않습니다.

## Explicit task origin and memory-only inputs

`Work.open` and `Engine.initialize` default to `explicit_skill=False`. Only the
actual explicit skill branch passes true (`--explicit-skill` in the CLI), recording
immutable `provenance={"version":1,"source":"explicit_loop_work"}`. This is
cooperative invocation provenance, not cryptographic proof of a vendor UI action.
Board task reads/actions require that runtime origin; Markdown cannot grant it.
Absent/unknown legacy and low-level tasks remain stored without retrospective promotion.

Relevant ordinary input can use existing `knowledge remember` as a project topic,
without creating a task/session/binding or execution call through the memory write.
Related ordinary-worded steering still follows the existing explicit task feedback
and controls with its consumed budgets preserved. Evidence and scoped user
basis remain original; known session IDs are optional and unknown IDs are omitted.
There is no automatic all-prompt capture or transcript dump. A later explicit task
selects the topic ID/revision and original sources as context without changing topic
ownership or treating memory as execution, scope-change, approval or completion authority.

Information-only projects can expose a zero-task project wiki only when an actual
project-index Markdown document exists. Topic-only memory may remain in Obsidian
without a Board project entry; the Board never substitutes a runtime DB project
record for a missing vault index.


## macOS desktop front end

The default macOS installation builds a local Tauri 2/Rust application with React,
shadcn, Motion, ECharts, ReactFlow and Rive using project-local npm/cargo dependencies. The user bundle is `~/Applications/Loop Work.app`;
a TARGET install places it in `<project>/.loop/Loop Work.app`. Python backend code
remains standard-library-only on macOS/Linux. Missing required build tools are reported without
automatic global toolchain installation. No Dock pinning, login item or app-wide settings change
is required. Linux retains the non-GUI CLI without claiming a native application install.

The bundled React frontend reads the same vault-backed Board through the authenticated
API-only loopback backend; Python serves no HTML or static frontend assets, and
there is no new execution/approval authority, alternate project list or model provider.
Runtime/KB/vault/project selection stays exact. Capability material remains in the private native launch/IPC channel, not bundle
configuration or ordinary logs.
Window close hides the app and reopen restores the window. Quit protects unsaved,
composing, conflicted or uncertain drafts before exiting. App/window lifecycle is
independent of task pause/resume, goals, feedback, approvals, caps and QA.

The app helper starts a backend when needed and stops only its own newly created
instance on quit/input EOF using matching identity. An app attached to an existing
CLI-managed backend leaves it running. `board start` starts/reuses that managed
backend without opening an app or browser; `status` and `stop` remain backend operations.
Public browser/foreground serve modes are removed. The private authenticated API and bundled React renderer remain required; public lifecycle output never exposes a capability URL.


### Native verification boundaries

Keep shipping-binary evidence separate from the opt-in `native-qa` build, whose
feature is off by default. The shipping startup/quit checks establish real bundled
application launch and owned/reused/replacement backend lifetime; they do not alone
establish populated-task editing, approval, control, visualization or physical input.
The separate audit binary exercises an actual Tauri WebView through the existing
Rust `board_request` bridge and Python API against an isolated populated vault. Its
programmatic DOM, composition and media-query probes must be labelled
`physical_gui_input_verified=false`; they are not physical keyboard or OS IME verification.
Audit-only instrumentation must not become a normal frontend command or new approval
path. The Python engine, authority checks, finite budgets and QA gates remain unchanged.
Native/renderer checks do not establish model-quality or speed improvement; the retained
benchmark comparison remains inconclusive unless its own gates establish otherwise.


Close preparation holds a request-ID-scoped guard through awaited editor saves and
native finish/cancel handling. After the await it rechecks all pending human/control
operations, editor saving/dirty/composition/conflict/uncertainty and unsent drafts;
late input invalidates a safe result. The actual native cancel callback releases only
the matching request guard on the normal cancellation path. An expired or failed
finish IPC ends that frontend attempt with a diagnostic and releases its own guard
so editing remains available. A transient QA preparation probe releases its own guard
without leaving the UI permanently locked.

An uncertain human response or execution retains its original payload and runtime/vault
pins. Only an explicit user retry first GETs the scoped current request: an authoritative
matching receipt reconciles without POST; otherwise a fresh, unmodified, writable and
exact prior record plus matching vault revision permits one resend of the original
payload. Polling never resubmits. A newer draft is preserved; execute does not clear it,
and respond clears only a draft still equal to the submitted original text.
