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
Runtime execution remains Python standard library. `/loop-work board serve` opens
the vault-backed board and default browser without changing activation; `--no-open`
keeps the server only. Vault Markdown supplies display/document data, while
SQLite/development JSON retain execution, permission and verification authority.
Preserve human notes and app settings; document edits never bypass runtime checks.
