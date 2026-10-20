#!/usr/bin/env python3
"""Explicit installer-only Obsidian check and loop-work workspace bootstrap."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys

SOURCE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SOURCE))
from loop_work import workspace
from loop_work.storage import LoopError


def find_obsidian(home=None):
    base = Path(home).expanduser().resolve() if home is not None else Path.home().resolve()
    for path in (Path("/Applications/Obsidian.app"), base / "Applications/Obsidian.app"):
        if path.is_dir():
            return str(path)
    executable = shutil.which("obsidian")
    appimages = sorted((base / "Applications").glob("Obsidian*.AppImage")) + sorted((base / "Applications").glob("obsidian*.AppImage"))
    for path in ([Path(executable)] if executable else []) + [Path("/opt/homebrew/bin/obsidian"), Path("/usr/local/bin/obsidian"), base / ".local/bin/obsidian", *appimages]:
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
    return None


def bootstrap(home=None):
    # Conflicts must fail before invoking a package manager or creating data.
    workspace.preflight(home)
    from loop_work.knowledge import KnowledgeBase, default_home, is_shared_home
    # An explicit --home scopes setup independently of inherited process
    # settings. For normal installation, use the runtime's environment-first
    # selection without enrolling custom/benchmark stores in the shared vault.
    configured = os.environ.get("LOOP_KB_HOME") if home is None else None
    selected_knowledge = Path(configured).expanduser().resolve() if configured else default_home(home)
    shared_selected = is_shared_home(selected_knowledge, home=home)
    existing_knowledge = shared_selected and (selected_knowledge / "knowledge.sqlite3").is_file()
    obsidian = find_obsidian(home)
    installed = False
    if obsidian is None:
        executable = shutil.which("brew")
        if not executable:
            raise LoopError("Obsidian is missing and Homebrew was not found. Homebrew itself is not installed automatically; no workspace was created.")
        brew = Path(executable).resolve()
        if not brew.is_absolute() or not brew.is_file() or not os.access(brew, os.X_OK):
            raise LoopError("Homebrew must resolve to an existing absolute executable; no installation was attempted")
        try:
            process = subprocess.run([str(brew), "install", "--cask", "obsidian"],
                                     stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise LoopError("Obsidian cask installation did not complete; existing notes preserved: " + str(exc)) from exc
        if process.returncode:
            raise LoopError("Obsidian cask installation failed (exit " + str(process.returncode) + "): " + (process.stderr or process.stdout)[-1000:])
        obsidian = find_obsidian(home)
        if obsidian is None:
            raise LoopError("Homebrew returned success but Obsidian is still unavailable; workspace setup was not marked successful")
        installed = True
    result = workspace.ensure(home)
    sync = ({"status": "not_needed", "records_considered": 0} if shared_selected else
            {"enabled": False, "status": "disabled", "records_considered": 0,
             "reason": "Explicit LOOP_KB_HOME selects custom storage; automatic shared-vault export is disabled."})
    if existing_knowledge:
        # An explicit fake home never selects the real user's knowledge store.
        # Do not create a new empty DB just to bootstrap an empty vault.
        try:
            sync = KnowledgeBase(selected_knowledge, vault_home=workspace.vault(home)).sync_vault()
        except (sqlite3.Error, OSError, LoopError) as exc:
            sync = {"enabled": True, "status": "failed", "vault": str(workspace.vault(home)),
                    "records_considered": None, "errors": ["Initial vault backfill unavailable: " + str(exc)]}
        if sync.get("errors"):
            sync = {**sync, "status": "partial" if sync.get("changed") else "failed"}
    return {**result, "vault_sync": sync, "obsidian": obsidian, "obsidian_installed": installed,
            "next": "Open " + result["vault"] + " in Obsidian using Open folder as vault; no global registration was changed."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path)
    args = parser.parse_args(argv)
    try:
        print(json.dumps(bootstrap(args.home), ensure_ascii=False, indent=2))
        return 0
    except LoopError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
