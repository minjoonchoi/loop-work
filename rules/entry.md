# Binding recovery and task controls

First select explicit `board` or `human` arguments under SKILL.md; they bypass activation
without changing the binding. Otherwise only explicit `loop-work <prompt>` starts
one task. Bare invocation asks once for the prompt without state changes. Related
correction/status inputs continue that task; unrelated ordinary inputs do not route
through it. Completion/abort releases routing. Legacy conversation-wide enabled
flags alone never authorize routing or selection. Use the task/continuation/off
contract in SKILL.md. Preserve its binding in
compaction handoffs; a distinct conversation never inherits activation from project
knowledge or old goals. Recover a lost binding only from this conversation's identified
task/goal. Without ownership evidence report the missing binding; never select by
recency/provider/cwd. If its entrypoint is unavailable, stop routing without fallback
or reactivation. An off request while already inactive/unbound acknowledges without
creating a session. No daemon or vendor hook intercepts messages.

## Pause and resume

Task pause/stop preserves only that task binding, not conversation-wide routing. Stop dispatching and save `pause` feedback with the
original input reference/current control version using `context.md`. Keep draft/ready
phase; do not start it. Only the user's later continuation request permits `resume`
feedback. Status questions and skill reactivation do not resume paused work.

Feedback controls dispatch, not goal/task phase. Resolve a separate phase blocker
with `work resume`/`resume` only when its condition is resolved; resume feedback alone
does not clear it. Abandonment uses `work abort`/`abort`; a pause remains resumable and
does not release development working-tree ownership.

For in-flight work, use available host cancellation. A synchronous call may finish
before the host handles stop: inspect logs/applied paths, preserve actual edits and
consumed attempts, then record pause. Dispatch no further calls, apply no pending
candidates, silently roll back nothing and claim no unobserved cancellation.

A task blocker does not request or authorize disabling activation. Report its
evidence, remaining work and recovery condition; do not suggest `loop-work off`
as a way around the blocker. Run off only on the user's explicit disable request.

## Human desk binding

Select the `human` first argument before activation. Invoking `loop-work human`
does not activate or disable loop-work and does not replace its
session/task. In an active conversation restore the same orchestration context and
continue the binding. A human response is scoped to its identified request; it does
not silently resume work. Only the user's explicit request permits execution of an
eligible recorded `resume_task`, with existing pause and integrity controls intact.

Read [human mode](human.md) only when handling that argument or an explicit human-desk
command. Human-only use creates no goal or session and preserves the existing binding.
