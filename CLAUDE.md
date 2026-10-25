# Claude Code entry point

Read and follow `AGENTS.md` for repository development instructions.
`/loop-work <prompt>` binds only that task. Related corrections/status retain it;
completion or abort releases routing. Unrelated ordinary requests do not activate
the harness. A bare invocation asks for a task without state changes.
The shared entry is `rules/work.md`; readable status and knowledge follow
`rules/writing.md`. Development uses `rules/workflow.md`, `rules/context.md` and
`rules/quality.md` with the same contract and gates as Codex. Independent development review uses the opposite CLI when installed; otherwise it
uses a fresh invocation of the worker provider. The first preflight selection stays
pinned for the goal; selected CLI failures do not trigger a provider switch. Other work has
one content/completion check without a mandatory development loop.

The same default installation contract applies to both providers: `make install`
checks/installs Obsidian through existing Homebrew and prepares `~/.loop-work/vault`.
Python backend execution remains standard library. macOS installation also builds
Loop Work.app with Tauri 2/Rust and React, using shadcn, Motion, ECharts, ReactFlow
and Rive. Project-local npm/cargo dependencies and builds are authorized for this GUI;
global toolchain/package installation, system settings changes, login and real
user-HOME installation retain their explicit approval requirements. Missing toolchains
fail clearly without automatic installation. `/loop-work board` or `board open` opens the native
vault-backed window without changing activation. `board start` prepares a backend without opening a window. Linux retains the non-GUI CLI; native opening requires macOS. Vault Markdown supplies display/document data, while
SQLite/development JSON retain execution, permission and verification authority.
Preserve human notes and app settings; document edits never bypass runtime checks.

Relevant ordinary-input knowledge may be remembered as project topics without a task
or new session under `rules/context.md`. Do not collect every prompt, invent IDs or
promote remembered text into approval. Only actual explicit skill task creation uses
`--explicit-skill`; low-level/legacy task origins are preserved and hidden from the Board.
