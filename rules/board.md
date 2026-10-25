# Vault task board

Use this mode for `$loop-work board [subcommand]` / `/loop-work board [subcommand]`
before activation. A bare `board` means `board open`; an explicit `list` or `show`
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
python3 "$ENTRYPOINT" --knowledge-home "$KNOWLEDGE_HOME" board open --session "$SESSION_ID" --port 0
```

Add `--task TASK_ID` when selected. Omit absent scope flags rather than inventing IDs.
With no binding, `python3 "SKILL_DIR/loop.py" board open` uses the shared default.
An arbitrary custom knowledge home requires its explicitly selected `--vault PATH`;
do not substitute another knowledge home's vault or enable automatic export to find one.
On macOS, `open` shows the Tauri 2 desktop app (Rust with React, shadcn, Motion, ECharts, ReactFlow and Rive) over its authenticated internal loopback service. `start` prepares a backend only, without opening an app or browser. Linux retains the non-GUI CLI and reports native opening unavailable.
Do not ask again to open the explicitly requested local app. Report actual startup
failure; do not label a missing window as opened or silently switch to a browser.
Closing the window hides it; Dock reopen restores it. Quit must protect unsaved,
composing, conflicting or uncertain drafts with the Korean confirmation flow.
The app helper stops only its newly owned backend with matching identity on quit/EOF;
a server already started/reused by CLI remains for `board status|stop`. Window/app
lifecycle never pauses/resumes work, changes a task binding or records approval.

## Read the documents shown

The board's display and document data come from vault Markdown: task cards, details,
tracking text and recorded human requests. SQLite/development JSON retain execution,
authority and verification state; they do not replace missing vault text with a
parallel hidden DB dashboard. Preserve the user's notes and document edits.

Missing, edited, stale or unrecognized request metadata must show its diagnostic
and disable unsafe actions. A Markdown label or edited frontmatter cannot grant
approval, finish a task, reset budgets, satisfy QA or bypass runtime integrity checks.
Uninventoried task documents may be shown read-only only when their matching current
runtime task has explicit-loop-work provenance. Without an eligible runtime task they
remain hidden. An absent ownership pin never grants action authority. Every Board view, including an unscoped view, uses identifier-free aggregate export
diagnostics; it omits per-record task IDs, titles, paths and errors. Detailed CLI/KB
export diagnostics remain separate. Do not interpret withheld details as an error-free
export or expand scope silently to retrieve them.
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

## 독립 명령과 서버 수명

`loop-work board start`는 같은 설치 runtime과 선택 KB를 사용해 readiness가 확인된 관리 서버를
재사용하거나 시작하며 앱이나 브라우저를 열지 않는다. `open`만 macOS 네이티브 앱을 연다.
`status`는 인증된 현재 상태 조회, `stop`은 instance
인증 shutdown이다. 상태 파일 PID만으로 signal을 보내거나 미관리 서버를 종료하지 않는다.
앱 시작 실패와 backend 실패를 구분하며 CLI가 시작한 서버를 앱 실패만으로 중단하지 않는다. unknown/readiness 실패를 성공으로 보고하지 않는다.

고정 `--project ID`는 목록뿐 아니라 상세·문서·위키·질문·제어·저장에도 적용한다.
프로젝트/작업 위키의 표시 이름과 Markdown 편집은 원래 실행 목표·ID·고정 경로·품질 판정·예산·
승인 guard를 바꾸지 않는다. 외부 변경의 revision 충돌은 초안을 보존하고 명시적으로 보고한다.

Only tasks with the immutable explicit-loop-work origin are listed as Board tasks.
Low-level/legacy tasks with absent or unknown origin remain in KB/vault unchanged;
recovery does not retrofit origin. Relevant ordinary prompts may create project topics
without any task. Information-only projects expose a zero-task project wiki only when an actual
project-index Markdown document exists. Topic-only memory may remain in Obsidian
without a Board project entry; never fall back to runtime-only project metadata. Directory names, Markdown edits and remembered text cannot grant origin.
