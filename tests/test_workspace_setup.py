"""Installer bootstrap uses only fake homes and mocked external app commands."""
from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from loop_work import workspace
from loop_work.storage import LoopError
from scripts import install as installer
from scripts import setup_workspace as setup


@contextlib.contextmanager
def allow_native_tools_but_forbid_brew():
    # setup and the native builder import the same subprocess module. Preserve
    # the no-Obsidian-install boundary without blocking the legitimate compiler.
    original_run = subprocess.run
    def checked_run(argv, *args, **kwargs):
        if Path(argv[0]).name == "brew":
            raise AssertionError("existing Obsidian must not invoke brew")
        return original_run(argv, *args, **kwargs)
    with patch.object(setup.subprocess, "run", side_effect=checked_run):
        yield


class WorkspaceSetupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve() / "home"
        self.home.mkdir()
        environment = patch.dict(os.environ, {"LOOP_INSTALL_TARGET": ""})
        environment.start()
        self.addCleanup(environment.stop)

    def fake_brew(self):
        brew = Path(self.temp.name) / "brew"
        brew.write_text("not executed by these tests\n")
        brew.chmod(0o700)
        return brew

    def test_paths_are_pure_and_ensure_is_idempotent_without_global_registration(self):
        self.assertEqual(workspace.root(self.home), self.home / ".loop-work")
        self.assertEqual(workspace.vault(self.home), self.home / ".loop-work/vault")
        self.assertEqual(workspace.data(self.home), self.home / ".loop-work/data")
        self.assertFalse(workspace.root(self.home).exists())
        first = workspace.ensure(self.home)
        note = workspace.vault(self.home) / "my-note.md"
        note.write_text("My original notes\n")
        settings = workspace.vault(self.home) / ".obsidian/app.json"
        settings.write_text('{"original":true}\n')
        settings.chmod(0o640)
        before = {p: (p.read_bytes(), p.stat().st_mode, p.stat().st_ino) for p in (note, settings, workspace.vault(self.home) / "안내.md")}
        second = workspace.ensure(self.home)
        self.assertTrue(first["created"])
        self.assertEqual(second["created"], [])
        self.assertFalse(second["registered"])
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_mode, p.stat().st_ino) for p in before})
        self.assertFalse((self.home / ".config").exists())
        self.assertFalse((self.home / "Library").exists())

    def test_korean_guide_and_personal_notes_preserve_existing_readme_and_user_files(self):
        vault = workspace.vault(self.home)
        vault.mkdir(parents=True)
        readme = vault / "README.md"
        readme.write_text("기존 사람이 정리한 README\n")
        notes = vault / "notes"
        notes.mkdir()
        original = notes / "원래 메모.md"
        original.write_text("원문 메모\n")
        before = {p: (p.read_bytes(), p.stat().st_ino) for p in (readme, original)}
        workspace.ensure(self.home)
        guide = vault / "안내.md"
        self.assertIn("프로젝트/", guide.read_text())
        self.assertIn("공통 지식/", guide.read_text())
        self.assertTrue((vault / "개인 메모").is_dir())
        guide.write_text("사용자가 바꾼 안내\n")
        workspace.ensure(self.home)
        self.assertEqual(guide.read_text(), "사용자가 바꾼 안내\n")
        self.assertEqual(before, {p: (p.read_bytes(), p.stat().st_ino) for p in before})

    def test_all_conflicts_fail_before_any_app_or_workspace_mutation(self):
        cases = ("root-file", "root-link", "data-file", "vault-link", "settings-file", "guide-link", "personal-notes-link")
        for name in cases:
            with self.subTest(name=name):
                home = self.home / name
                home.mkdir()
                root = workspace.root(home)
                outside = home / "keep"
                outside.mkdir()
                if name == "root-file":
                    root.write_text("original")
                elif name == "root-link":
                    root.symlink_to(outside, target_is_directory=True)
                else:
                    root.mkdir()
                    if name == "data-file":
                        workspace.data(home).write_text("original")
                    elif name == "vault-link":
                        workspace.vault(home).symlink_to(outside, target_is_directory=True)
                    else:
                        workspace.vault(home).mkdir()
                        if name == "settings-file":
                            (workspace.vault(home) / ".obsidian").write_text("original")
                        elif name == "personal-notes-link":
                            (workspace.vault(home) / "개인 메모").symlink_to(outside, target_is_directory=True)
                        else:
                            (workspace.vault(home) / "안내.md").symlink_to(outside / "missing")
                before = sorted(str(p.relative_to(home)) for p in home.rglob("*"))
                with patch.object(setup, "find_obsidian", side_effect=AssertionError("app checks must follow preflight")), patch.object(subprocess, "run", side_effect=AssertionError("must not install")):
                    with self.assertRaises(LoopError):
                        setup.bootstrap(home)
                self.assertEqual(sorted(str(p.relative_to(home)) for p in home.rglob("*")), before)
                self.assertEqual(list(outside.iterdir()), [])

    def test_existing_obsidian_skips_brew_and_preserves_user_notes(self):
        with patch.object(setup, "find_obsidian", return_value="/Applications/Obsidian.app"), patch.object(setup.shutil, "which", side_effect=AssertionError("must not search brew")), patch.object(setup.subprocess, "run", side_effect=AssertionError("must not install")):
            first = setup.bootstrap(self.home)
            second = setup.bootstrap(self.home)
        self.assertFalse(first["obsidian_installed"])
        self.assertEqual(second["created"], [])
        self.assertTrue(workspace.vault(self.home).is_dir())

    def test_missing_obsidian_uses_absolute_brew_argv_and_verifies_result(self):
        brew = self.fake_brew()
        with patch.object(setup, "find_obsidian", side_effect=[None, "/installed/obsidian"]), patch.object(setup.shutil, "which", return_value=str(brew)), patch.object(setup.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="installed", stderr="")) as command:
            result = setup.bootstrap(self.home)
        self.assertTrue(result["obsidian_installed"])
        self.assertEqual(command.call_args.args[0], [str(brew.resolve()), "install", "--cask", "obsidian"])
        self.assertNotIn("shell", command.call_args.kwargs)
        self.assertEqual(command.call_args.kwargs["stdin"], subprocess.DEVNULL)

    def test_no_brew_and_failed_or_unverified_install_never_create_workspace(self):
        brew = self.fake_brew()
        with patch.object(setup, "find_obsidian", return_value=None), patch.object(setup.shutil, "which", return_value=None), patch.object(setup.subprocess, "run", side_effect=AssertionError("must not install Homebrew")):
            with self.assertRaisesRegex(LoopError, "Homebrew itself is not installed"):
                setup.bootstrap(self.home)
        self.assertFalse(workspace.root(self.home).exists())
        for output, message in ((SimpleNamespace(returncode=8, stdout="", stderr="cask failed"), "exit 8"),
                                (SimpleNamespace(returncode=0, stdout="", stderr=""), "still unavailable")):
            with patch.object(setup, "find_obsidian", return_value=None), patch.object(setup.shutil, "which", return_value=str(brew)), patch.object(setup.subprocess, "run", return_value=output):
                with self.assertRaisesRegex(LoopError, message):
                    setup.bootstrap(self.home)
            self.assertFalse(workspace.root(self.home).exists())

    def test_obsidian_detection_supports_app_and_executable_without_launching(self):
        app = self.home / "Applications/Obsidian.app"
        with patch.object(Path, "is_dir", autospec=True, side_effect=lambda path: path == app), patch.object(setup.shutil, "which", side_effect=AssertionError("app is already present")):
            self.assertEqual(setup.find_obsidian(self.home), str(app))
        executable = self.home / "Applications/Obsidian-current.AppImage"
        executable.parent.mkdir()
        executable.write_text("not launched")
        executable.chmod(0o700)
        original_file = Path.is_file
        with patch.object(Path, "is_dir", return_value=False), patch.object(setup.shutil, "which", return_value=None), patch.object(Path, "is_file", autospec=True, side_effect=lambda path: path == executable and original_file(path)):
            self.assertEqual(setup.find_obsidian(self.home), str(executable))

    def test_bootstrap_backfills_only_existing_selected_fake_home_knowledge(self):
        from loop_work.knowledge import KnowledgeBase
        selected = self.home / ".local/share/loop-work"
        knowledge = KnowledgeBase(selected, vault_home=None)
        from loop_work.work import Work
        project = Path(self.temp.name) / "target"
        project.mkdir()
        task = Work(knowledge).open("document", "Existing task", "codex", [project])["task"]
        knowledge.put("human-request", {"id": "existing-human", "task_id": task["id"], "session_id": task["session_id"],
                                       "kind": "decision", "title": "Existing note", "status": "pending"})
        original = knowledge.get("human-request", "existing-human")
        with patch.object(setup, "find_obsidian", return_value="/Applications/Obsidian.app"), patch.object(setup.subprocess, "run", side_effect=AssertionError("must not install")):
            result = setup.bootstrap(self.home)
        self.assertEqual(result["vault_sync"]["records_considered"], 2)
        self.assertEqual(result["vault_sync"]["errors"], [])
        self.assertEqual(KnowledgeBase(selected, vault_home=None).get("human-request", "existing-human"), original)
        self.assertFalse((workspace.data(self.home) / "knowledge.sqlite3").exists())
        import json
        manifest = json.loads((selected / "vault-owned.json").read_text())
        name = next(name for name, entry in manifest["documents"].items() if entry["kind"] == "human-request" and entry["id"] == "existing-human")
        note = workspace.vault(self.home) / name
        self.assertTrue(note.is_file())
        note.write_text("User edited this generated view; preserve it.\n")
        with patch.object(setup, "find_obsidian", return_value="/Applications/Obsidian.app"), allow_native_tools_but_forbid_brew(), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as diagnostics:
            self.assertEqual(installer.main(["--link", "--workspace", "--home", str(self.home)]), 0)
        self.assertIn("Vault backfill warning", diagnostics.getvalue())
        self.assertEqual(note.read_text(), "User edited this generated view; preserve it.\n")
        self.assertTrue((self.home / ".agents/skills/loop-work").is_symlink())

    def test_locked_backfill_database_warns_without_blocking_install_or_touching_notes(self):
        import sqlite3
        from loop_work.knowledge import KnowledgeBase
        selected = workspace.data(self.home)
        knowledge = KnowledgeBase(selected, vault_home=None)
        database = knowledge.path.read_bytes()
        note = workspace.vault(self.home) / "my-original-note.md"
        note.parent.mkdir(parents=True)
        note.write_text("Preserve this existing note.\n")
        with patch("loop_work.knowledge.KnowledgeBase", side_effect=sqlite3.OperationalError("database is locked")), patch.object(setup, "find_obsidian", return_value="/Applications/Obsidian.app"), allow_native_tools_but_forbid_brew(), contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()) as diagnostics:
            self.assertEqual(installer.main(["--link", "--workspace", "--home", str(self.home)]), 0)
        self.assertIn("Vault backfill warning (failed)", diagnostics.getvalue())
        self.assertIn("database is locked", diagnostics.getvalue())
        self.assertEqual(note.read_text(), "Preserve this existing note.\n")
        self.assertEqual(knowledge.path.read_bytes(), database)
        self.assertTrue((self.home / ".agents/skills/loop-work").is_symlink())

    def test_normal_bootstrap_honors_known_shared_env_selection_with_multiple_legacy_databases(self):
        from loop_work.knowledge import KnowledgeBase
        first = self.home / ".local/share/loop-work"
        second = self.home / ".local/share/loop-dev"
        KnowledgeBase(first, vault_home=False)
        KnowledgeBase(second, vault_home=False)
        with patch.object(Path, "home", return_value=self.home), patch.dict(os.environ, {"LOOP_KB_HOME": str(second)}), patch.object(setup, "find_obsidian", return_value="/fixture/Obsidian.app"), patch.object(KnowledgeBase, "sync_vault", autospec=True, return_value={"status": "unchanged", "errors": [], "records_considered": 0}) as sync:
            result = setup.bootstrap()
        self.assertEqual(sync.call_count, 1)
        self.assertEqual(sync.call_args.args[0].home, second.resolve())
        self.assertEqual(sync.call_args.args[0].vault_home, workspace.vault(self.home))
        self.assertEqual(result["vault_sync"]["errors"], [])
        self.assertFalse((workspace.data(self.home) / "knowledge.sqlite3").exists())

    def test_custom_env_selection_never_falls_back_to_or_backfills_default_database(self):
        from loop_work.knowledge import KnowledgeBase
        default = KnowledgeBase(self.home / ".local/share/loop-work", vault_home=False)
        custom = KnowledgeBase(self.home / "benchmark/trial-kb", vault_home=False)
        original = {path: path.read_bytes() for path in (default.path, custom.path)}
        with patch.object(Path, "home", return_value=self.home), patch.dict(os.environ, {"LOOP_KB_HOME": str(custom.home)}), patch.object(setup, "find_obsidian", return_value="/fixture/Obsidian.app"), patch("loop_work.knowledge.KnowledgeBase", side_effect=AssertionError("custom selection must not open or export any store")):
            result = setup.bootstrap()
        self.assertEqual(result["vault_sync"]["status"], "disabled")
        self.assertFalse(result["vault_sync"]["enabled"])
        self.assertEqual({path: path.read_bytes() for path in original}, original)
        self.assertFalse((workspace.data(self.home) / "knowledge.sqlite3").exists())

    def test_explicit_fake_home_never_inherits_outside_knowledge_override(self):
        outside = Path(self.temp.name) / "outside-knowledge"
        outside.mkdir()
        database = outside / "knowledge.sqlite3"
        database.write_bytes(b"outside fake-home data must never be opened")
        with patch.dict(os.environ, {"LOOP_KB_HOME": str(outside)}), patch.object(setup, "find_obsidian", return_value="/fixture/Obsidian.app"), patch.object(Path, "home", side_effect=AssertionError("explicit fake home must not discover real home")), patch("loop_work.knowledge.KnowledgeBase", side_effect=AssertionError("must not open inherited outside store")):
            result = setup.bootstrap(self.home)
        self.assertEqual(result["vault_sync"]["status"], "not_needed")
        self.assertEqual(database.read_bytes(), b"outside fake-home data must never be opened")
        self.assertFalse((workspace.data(self.home) / "knowledge.sqlite3").exists())

    def test_lowlevel_install_and_uninstall_never_bootstrap_or_remove_workspace(self):
        result = workspace.ensure(self.home)
        note = workspace.vault(self.home) / "keep.md"
        note.write_text("keep notes")
        with patch.object(setup, "bootstrap", side_effect=AssertionError("lowlevel install must not bootstrap")):
            installer.install_links(self.home)
            installer.uninstall_links(self.home)
        self.assertEqual(note.read_text(), "keep notes")
        self.assertTrue(workspace.data(self.home).is_dir())
        self.assertFalse(result["registered"])

    def test_explicit_workspace_cli_preflights_install_conflicts_before_app_setup(self):
        conflict = self.home / ".agents/skills/loop-work"
        conflict.mkdir(parents=True)
        (conflict / "SKILL.md").write_text("unowned skill")
        with patch.object(setup, "bootstrap", side_effect=AssertionError("must preflight link paths first")), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(installer.main(["--link", "--workspace", "--home", str(self.home)]), 2)
        self.assertFalse(workspace.root(self.home).exists())
        self.assertEqual((conflict / "SKILL.md").read_text(), "unowned skill")

    def test_explicit_workspace_cli_and_make_install_share_opt_in_boundary(self):
        with patch.object(setup, "find_obsidian", return_value="/Applications/Obsidian.app"), allow_native_tools_but_forbid_brew(), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(installer.main(["--link", "--workspace", "--home", str(self.home)]), 0)
        self.assertTrue(workspace.vault(self.home).is_dir())
        self.assertTrue((self.home / ".agents/skills/loop-work").is_symlink())
        makefile = Path(installer.SOURCE / "Makefile").read_text()
        self.assertIn("python3 scripts/install.py --link --workspace", makefile)
        for arguments in (["--uninstall", "--workspace"], ["--workspace"]):
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(installer.main([*arguments, "--home", str(self.home)]), 2)
