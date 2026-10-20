from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

from loop_work.delegation import Delegation, dispatch_preflight
from loop_work.storage import LoopError, digest, read_json, write_json
from loop_work.work import Work
from support import FAKE_CLI, ProjectTest, fixture_assessment
from test_delegation import WORKER_BRANCH, assignment


class DispatchPreflightTests(ProjectTest):
    def setUp(self):
        super().setUp()
        for name in ("claude", "codex"):
            (self.bin / name).write_text(FAKE_CLI.replace(
                'data = json.loads(prompt.split(', WORKER_BRANCH + 'data = json.loads(prompt.split(', 1))
        self.kb = self.engine.knowledge
        self.task_id = self.engine.refresh()["work_id"]

    def check(self, request=None, recover=None):
        return dispatch_preflight(self.kb, self.task_id, request or assignment(), self.root, recover)

    def frozen_bytes(self):
        return {str(path): (path.read_bytes(), path.stat().st_mode) for base in (self.root, self.kb.home)
                for path in base.rglob("*") if path.is_file()}

    def assert_setup_state_unchanged(self, before):
        # Actual dispatch historically acquires locks and renders context views.
        # They are not attempt/budget/task/candidate records or source changes.
        def substantive(values):
            return {name: value for name, value in values.items()
                    if not Path(name).is_relative_to(self.kb.home / "views/context")
                    and not name.endswith("/.loop/state/lock")}
        self.assertEqual(substantive(self.frozen_bytes()), substantive(before))

    def test_valid_check_is_read_only_then_actual_dispatch_calls_once(self):
        self.running()
        before = self.frozen_bytes()
        with patch("loop_work.providers.structured_call", side_effect=AssertionError("check must not call")):
            checked = self.check()
        self.assertTrue(checked["passed"], checked)
        self.assertEqual(checked["action"], "dispatch")
        self.assertEqual(self.frozen_bytes(), before)
        result = Delegation(self.kb, self.task_id, self.root).run(assignment())
        self.assertEqual(result["assignment"]["attempts"], 1)
        self.assertEqual(self.kb.get("worker-budget", self.task_id)["calls"], 1)

    def test_missing_cli_blocks_new_check_and_dispatch_without_consuming_budget(self):
        worker = Delegation(self.kb, self.task_id, self.root)
        before = self.frozen_bytes()
        with patch("loop_work.providers.shutil.which", return_value=None), \
                patch("loop_work.providers.structured_call", side_effect=AssertionError("must not call")):
            checked = self.check()
            self.assertFalse(checked["passed"], checked)
            self.assertEqual(checked["diagnostics"][0]["code"], "provider_setup")
            self.assertIn("not installed", checked["diagnostics"][0]["message"])
            self.assertEqual(self.frozen_bytes(), before)
            with self.assertRaisesRegex(LoopError, "not installed"):
                worker.run(assignment())
        self.assert_setup_state_unchanged(before)
        self.assertIsNone(self.kb.get("worker-budget", self.task_id, required=False))
        self.assertIsNone(self.kb.get("delegation", "delegate-" + digest([self.task_id, assignment()["id"]])[:24], required=False))

    def test_missing_frozen_wrapper_and_catalog_mismatch_are_provider_setup_errors(self):
        transport = Path(self.temp.name) / "empty-transport"
        transport.mkdir()
        profile_path = transport / "profile.json"
        self.assertFalse((transport / "bin").exists(), "Dedicated transport must have no benchmark wrappers")
        self.assertTrue((self.bin / "claude").is_file(), "Ordinary CLI fixture remains separate from missing wrappers")
        worker = Delegation(self.kb, self.task_id, self.root)
        for models, message in (({"codex": "fixture", "claude": "fixture"}, "wrapper is unavailable"), ({}, "outside the frozen benchmark catalog")):
            with self.subTest(models=models):
                write_json(profile_path, {"models": models})
                before = self.frozen_bytes()
                with patch.dict(os.environ, {"LOOP_BENCH_PROFILE": str(profile_path)}), \
                        patch("loop_work.providers.structured_call", side_effect=AssertionError("must not call")):
                    checked = self.check()
                    self.assertFalse(checked["passed"])
                    self.assertEqual(checked["diagnostics"][0]["code"], "provider_setup")
                    self.assertIn(message, checked["diagnostics"][0]["message"])
                    self.assertEqual(self.frozen_bytes(), before)
                    with self.assertRaisesRegex(LoopError, message):
                        worker.run(assignment())
                self.assert_setup_state_unchanged(before)
                self.assertIsNone(self.kb.get("worker-budget", self.task_id, required=False))

    def test_missing_cli_keeps_pending_and_completed_reuse_available(self):
        worker = Delegation(self.kb, self.task_id, self.root)
        response = worker.run(assignment())
        for accepted in (False, True):
            with self.subTest(accepted=accepted):
                if accepted:
                    response = worker.assess(fixture_assessment(self.kb, response))
                before = self.frozen_bytes()
                with patch("loop_work.providers.executable_for", side_effect=AssertionError("reuse needs no executable")), \
                        patch("loop_work.providers.structured_call", side_effect=AssertionError("must not call")):
                    checked = self.check()
                    self.assertTrue(checked["passed"], checked)
                    self.assertEqual(checked["action"], "reuse")
                    self.assertTrue(worker.run(assignment())["reused"])
                self.assertEqual(self.frozen_bytes(), before)

    def test_missing_cli_preserves_stale_pending_candidate_even_with_recover(self):
        worker = Delegation(self.kb, self.task_id, self.root)
        worker.run(assignment())
        (self.root / "value.py").write_text("VALUE = 2\n")
        before = self.frozen_bytes()
        with patch("loop_work.providers.shutil.which", return_value=None):
            checked = self.check(recover="Inspected stale candidate")
            self.assertFalse(checked["passed"])
            self.assertEqual(checked["diagnostics"][0]["code"], "provider_setup")
            self.assertEqual(self.frozen_bytes(), before)
            with self.assertRaisesRegex(LoopError, "not installed"):
                worker.run(assignment(), "Inspected stale candidate")
        self.assert_setup_state_unchanged(before)

    def test_missing_reads_warn_without_changing_absence_semantics_and_ignored_reads_block(self):
        for name in ("public-api.py", "compiler.log"):
            with self.subTest(name=name):
                request = assignment(); request["read_paths"].append(name)
                before = self.frozen_bytes()
                checked = self.check(request)
                self.assertTrue(checked["passed"], checked)
                self.assertEqual(checked["warnings"][0]["path"], name)
                self.assertEqual(checked["warnings"][0]["code"], "missing_read")
                self.assertEqual(self.frozen_bytes(), before)
        (self.root / ".gitignore").write_text("compiler.log\n")
        (self.root / "compiler.log").write_text("actual compiler diagnostic\n")
        request = assignment(); request["read_paths"].append("compiler.log")
        checked = self.check(request)
        self.assertFalse(checked["passed"])
        self.assertIn("ignored/unobserved", checked["diagnostics"][0]["message"])
        self.assertIsNone(self.kb.get("worker-budget", self.task_id, required=False))

    def test_actual_dispatch_still_allows_intentional_missing_read(self):
        request = assignment(); request["read_paths"].append("absent-test.py")
        response = Delegation(self.kb, self.task_id, self.root).run(request)
        self.assertEqual(response["assignment"]["status"], "candidate")
        self.assertEqual(response["assignment"]["attempts"], 1)

    def test_assessment_blocks_absent_read_becoming_ignored_file_or_symlink_without_reading_it(self):
        worker = Delegation(self.kb, self.task_id, self.root)
        for kind in ("file", "symlink"):
            with self.subTest(kind=kind):
                name = "ignored-input-" + kind + ".py"
                with (self.root / ".gitignore").open("a") as stream:
                    stream.write("\n" + name + "\n")
                request = assignment("assessment-" + kind)
                request["read_paths"].append(name)
                result = worker.run(request)
                before_digest = worker.observation()["digest"]
                denied = self.root / name
                if kind == "file":
                    denied.write_text("DO_NOT_READ = True\n")
                    target = denied
                else:
                    target = Path(self.temp.name) / "unassigned-target.py"
                    target.write_text("DO_NOT_READ = True\n")
                    denied.symlink_to(target)
                self.assertEqual(worker.observation()["digest"], before_digest)
                payload = fixture_assessment(self.kb, result)
                original_record = copy.deepcopy(self.kb.get("delegation", result["assignment"]["id"]))
                budget = self.kb.get("worker-budget", self.task_id)
                real_open = Path.open
                def refuse_denied_open(path, *args, **kwargs):
                    if Path(path) == denied or Path(path) == target:
                        raise AssertionError("Runtime must not read ignored or unassigned contents")
                    return real_open(path, *args, **kwargs)
                with patch.object(Path, "open", refuse_denied_open):
                    with self.assertRaises(LoopError):
                        worker.assess(payload)
                self.assertEqual(self.kb.get("delegation", result["assignment"]["id"]), original_record)
                self.assertEqual(self.kb.get("worker-budget", self.task_id), budget)
                self.assertFalse((Path(result["assignment"]["directory"]) / "assessment.json").exists())
                self.assertEqual(worker.observation()["digest"], before_digest)

    def test_unchanged_missing_read_and_empty_directory_remain_acceptable(self):
        (self.root / "empty-inputs").mkdir()
        request = assignment("unchanged-absence")
        request["read_paths"].extend(["still-missing.py", "empty-inputs/"])
        worker = Delegation(self.kb, self.task_id, self.root)
        result = worker.run(request)
        dispatch = read_json(Path(result["assignment"]["directory"]) / "dispatch.json")
        self.assertEqual(dispatch["read_scope"]["still-missing.py"], "absent")
        self.assertEqual(dispatch["read_scope"]["empty-inputs/"], "directory")
        self.assertTrue(worker.assess(fixture_assessment(self.kb, result))["passed"])

    def test_declared_absent_directory_becoming_empty_is_stale_with_new_presence_pin(self):
        request = assignment("changed-absence")
        request["read_paths"].append("previously-absent/")
        worker = Delegation(self.kb, self.task_id, self.root)
        result = worker.run(request)
        original_digest = worker.observation()["digest"]
        (self.root / "previously-absent").mkdir()
        current = worker.observation()
        self.assertEqual(current["digest"], original_digest)
        # An older dispatch without presence metadata cannot infer absence from
        # missing source entries; it still validates the current safe directory.
        self.assertEqual(worker._read_scope(request, current)["previously-absent/"], "directory")
        with self.assertRaisesRegex(LoopError, "existence changed"):
            worker.assess(fixture_assessment(self.kb, result))

    def test_authorized_creation_of_an_absent_read_write_path_still_applies_and_reuses(self):
        self.running()
        request = assignment("own-created-input", "implementation", ["created-output.py"])
        request["read_paths"].append("created-output.py")
        worker = Delegation(self.kb, self.task_id, self.root)
        with patch.dict(os.environ, {"LOOP_WORKER_EDITS": json.dumps({"created-output.py": "VALUE = 1\n"})}):
            result = worker.run(request)
        payload = fixture_assessment(self.kb, result)
        accepted = worker.assess(payload)
        self.assertTrue(accepted["passed"], accepted)
        self.assertEqual((self.root / "created-output.py").read_text(), "VALUE = 1\n")
        self.assertTrue(worker.assess(payload)["reused"])
        self.assertTrue(worker.run(request)["reused"])

    def test_existing_directory_scope_can_observe_absence(self):
        (self.root / "tests").mkdir()
        request = assignment(); request["read_paths"].append("tests/")
        self.assertTrue(self.check(request)["passed"])

    def test_pending_candidate_reuses_without_budget_check_or_changes(self):
        result = Delegation(self.kb, self.task_id, self.root).run(assignment())
        self.kb.put("worker-budget", {"id": self.task_id, "calls": 40})
        before = self.frozen_bytes()
        checked = self.check()
        self.assertTrue(checked["passed"], checked)
        self.assertEqual(checked["action"], "reuse")
        self.assertEqual(checked["assignment_status"], "candidate")
        self.assertEqual(self.frozen_bytes(), before)
        self.assertEqual(result["assignment"]["attempts"], 1)

    def test_expired_development_time_still_reuses_candidate_and_done_without_calls(self):
        self.running()
        worker = Delegation(self.kb, self.task_id, self.root)
        result = worker.run(assignment())
        future = datetime.now(timezone.utc) + timedelta(days=2)
        for accepted in (False, True):
            with self.subTest(accepted=accepted):
                if accepted:
                    result = worker.assess(fixture_assessment(self.kb, result))
                before_calls = self.kb.get("worker-budget", self.task_id)["calls"]
                with patch("loop_work.delegation.datetime", wraps=datetime) as clock, \
                        patch("loop_work.providers.structured_call", side_effect=AssertionError("expired work must not call")):
                    clock.now.return_value = future
                    checked = self.check()
                    self.assertTrue(checked["passed"], checked)
                    self.assertEqual(checked["action"], "reuse")
                    self.assertTrue(worker.run(assignment())["reused"])
                    with self.assertRaisesRegex(LoopError, "budget exhausted"):
                        worker.run(assignment("new-expired-call"))
                self.assertEqual(self.kb.get("worker-budget", self.task_id)["calls"], before_calls)

    def test_apply_checks_all_ignored_targets_before_any_source_write(self):
        self.running()
        request = assignment("new-output-files", "implementation", ["first-new.py", "second-new.py"])
        worker = Delegation(self.kb, self.task_id, self.root)
        with patch.dict(os.environ, {"LOOP_WORKER_EDITS": json.dumps({"first-new.py": "ONE = 1\n", "second-new.py": "TWO = 2\n"})}):
            result = worker.run(request)
        digest_before = worker.observation()["digest"]
        with (self.root / ".git/info/exclude").open("a") as stream:
            stream.write("\nsecond-new.py\n")
        self.assertEqual(worker.observation()["digest"], digest_before)
        assessed = worker.assess(fixture_assessment(self.kb, result))
        self.assertFalse(assessed["passed"])
        self.assertIn("ignored", assessed["assignment"]["error"])
        self.assertFalse((self.root / "first-new.py").exists())
        self.assertFalse((self.root / "second-new.py").exists())
        self.assertEqual(assessed["assignment"]["applied_count"], 0)

    def test_apply_rechecks_each_file_fence_after_earlier_write(self):
        from loop_work.storage import write_text
        self.running()
        request = assignment("fenced-output-files", "implementation", ["first-new.py", "second-new.py"])
        worker = Delegation(self.kb, self.task_id, self.root)
        with patch.dict(os.environ, {"LOOP_WORKER_EDITS": json.dumps({"first-new.py": "ONE = 1\n", "second-new.py": "TWO = 2\n"})}):
            result = worker.run(request)
        def change_exclude_after_first(path, content):
            write_text(path, content)
            if Path(path).resolve() == (self.root / "first-new.py").resolve():
                with (self.root / ".git/info/exclude").open("a") as stream:
                    stream.write("\nsecond-new.py\n")
        with patch("loop_work.delegation.write_text", side_effect=change_exclude_after_first):
            assessed = worker.assess(fixture_assessment(self.kb, result))
        self.assertFalse(assessed["passed"])
        self.assertIn("ignored", assessed["assignment"]["error"])
        self.assertTrue((self.root / "first-new.py").exists())
        self.assertFalse((self.root / "second-new.py").exists())
        self.assertEqual(assessed["assignment"]["applied"], ["first-new.py"])

    def ignored_read_transition(self, accepted):
        (self.root / ".gitignore").write_text("compiler.log\n")
        request = assignment(); request["read_paths"].append("compiler.log")
        worker = Delegation(self.kb, self.task_id, self.root)
        response = worker.run(request)
        if accepted:
            response = worker.assess(fixture_assessment(self.kb, response))
            self.assertEqual(response["assignment"]["status"], "done")
        else:
            self.assertEqual(response["assignment"]["status"], "candidate")
        observation = worker.observation()["digest"]
        (self.root / "compiler.log").write_text("actual ignored compiler output\n")
        self.assertEqual(worker.observation()["digest"], observation)
        before = self.frozen_bytes()
        budget = self.kb.get("worker-budget", self.task_id)
        record = copy.deepcopy(self.kb.get("delegation", response["assignment"]["id"]))
        with patch("loop_work.providers.structured_call", side_effect=AssertionError("must not call")):
            checked = self.check(request)
            self.assertFalse(checked["passed"], checked)
            self.assertEqual(checked["diagnostics"][0]["code"], "request_scope")
            self.assertIn("ignored/unobserved", checked["diagnostics"][0]["message"])
            self.assertEqual(self.frozen_bytes(), before)
            with self.assertRaisesRegex(LoopError, "ignored/unobserved"):
                worker.run(request)
        self.assertEqual(self.kb.get("worker-budget", self.task_id), budget)
        self.assertEqual(self.kb.get("delegation", response["assignment"]["id"]), record)
        self.assertEqual(self.frozen_bytes(), before)

    def test_empty_directory_presence_drift_blocks_candidate_reuse_and_refreshes_rejection(self):
        request = assignment()
        request["read_paths"].append("new-empty/")
        worker = Delegation(self.kb, self.task_id, self.root)
        response = worker.run(request)
        record = self.kb.get("delegation", response["assignment"]["id"])
        before = worker.observation()
        (self.root / "new-empty").mkdir()
        current = worker.observation()
        self.assertEqual(before["digest"], current["digest"])
        frozen = self.frozen_bytes()
        checked = self.check(request)
        self.assertFalse(checked["passed"], checked)
        self.assertIn("Pending candidate evidence changed", checked["diagnostics"][0]["message"])
        self.assertEqual(self.frozen_bytes(), frozen)
        self.assertTrue(worker._rejection_changed(record, current, record["parent_seal"],
                                                  {"revision": record["feedback_revision"]}))
        record["status"] = "done"
        self.assertTrue(worker._read_scope_changed(record, current))
        recovered = self.check(request, recover="Inspected empty-directory drift")
        self.assertTrue(recovered["passed"], recovered)
        self.assertEqual(recovered["action"], "dispatch")

    def test_dispatch_tamper_with_source_drift_cannot_be_recovered(self):
        worker = Delegation(self.kb, self.task_id, self.root)
        result = worker.run(assignment())
        record = self.kb.get("delegation", result["assignment"]["id"])
        dispatch = Path(record["directory"]) / "dispatch.json"
        value = read_json(dispatch)
        value["before"]["digest"] = "tampered"
        write_json(dispatch, value)
        (self.root / "unrelated.py").write_text("DRIFT = 1\n")
        budget = self.kb.get("worker-budget", self.task_id)
        with patch("loop_work.providers.structured_call", side_effect=AssertionError("must not call")):
            checked = self.check(recover="Inspected source drift")
            self.assertFalse(checked["passed"], checked)
            self.assertIn("dispatch evidence changed", checked["diagnostics"][0]["message"])
            with self.assertRaisesRegex(LoopError, "dispatch evidence changed"):
                worker.run(assignment(), recover="Inspected source drift")
        self.assertEqual(self.kb.get("worker-budget", self.task_id), budget)
        self.assertEqual(self.kb.get("delegation", record["id"]), record)

    def test_done_tampered_pins_block_new_call_even_after_unrelated_source_drift(self):
        worker = Delegation(self.kb, self.task_id, self.root)
        response = worker.run(assignment())
        response = worker.assess(fixture_assessment(self.kb, response))
        record = self.kb.get("delegation", response["assignment"]["id"])
        (self.root / "unrelated.py").write_text("NEW = 1\n")
        budget = self.kb.get("worker-budget", self.task_id)
        for field in ("result", "assessment_ref"):
            target = Path(record[field])
            original = target.read_bytes()
            target.write_bytes(original + b" ")
            with patch("loop_work.providers.structured_call", side_effect=AssertionError("must not call")):
                self.assertFalse(self.check()["passed"])
                with self.assertRaises(LoopError):
                    worker.run(assignment())
            self.assertEqual(self.kb.get("worker-budget", self.task_id), budget)
            self.assertEqual(self.kb.get("delegation", record["id"]), record)
            target.write_bytes(original)

    def test_blocked_retained_result_tamper_cannot_be_archived_by_recovery(self):
        from test_assignment_v2 import request_v2, worker_result
        request = request_v2("blocked-pinned-output")
        worker = Delegation(self.kb, self.task_id, self.root)
        def provider(*args, **kwargs):
            (self.root / "during-call.py").write_text("DRIFT = 1\n")
            return worker_result(request)
        with patch("loop_work.providers.structured_call", side_effect=provider):
            response = worker.run(request)
        self.assertEqual(response["assignment"]["status"], "blocked")
        record = self.kb.get("delegation", response["assignment"]["id"])
        Path(record["result"]).write_bytes(Path(record["result"]).read_bytes() + b" ")
        budget = self.kb.get("worker-budget", self.task_id)
        with patch("loop_work.providers.structured_call", side_effect=AssertionError("must not call")):
            checked = self.check(request, recover="Inspected source drift")
            self.assertFalse(checked["passed"], checked)
            with self.assertRaisesRegex(LoopError, "Candidate result artifact changed"):
                worker.run(request, recover="Inspected source drift")
        self.assertEqual(self.kb.get("worker-budget", self.task_id), budget)
        self.assertEqual(self.kb.get("delegation", record["id"]), record)

    def test_handoff_blocks_dependency_absent_read_becoming_ignored(self):
        (self.root / ".gitignore").write_text("compiler.log\n")
        worker = Delegation(self.kb, self.task_id, self.root)
        request = assignment("producer")
        request["read_paths"].append("compiler.log")
        result = worker.run(request)
        worker.assess(fixture_assessment(self.kb, result))
        (self.root / "compiler.log").write_text("hidden diagnostic\n")
        consumer = assignment("consumer")
        consumer["depends_on"] = ["producer"]
        budget = self.kb.get("worker-budget", self.task_id)
        with patch("loop_work.providers.structured_call", side_effect=AssertionError("must not call")):
            checked = self.check(consumer)
            self.assertFalse(checked["passed"], checked)
            with self.assertRaises(LoopError):
                worker.run(consumer)
        self.assertEqual(self.kb.get("worker-budget", self.task_id), budget)

    def test_patch_base_becoming_ignored_during_call_is_never_read(self):
        from test_assignment_v2 import request_v2, worker_result
        from loop_work.storage import file_hash
        self.running()
        target = self.root / "patch-base.py"
        target.write_text("BASE = 1\n")
        request = request_v2("hidden-patch-base", "implementation", [target.name])
        value = worker_result(request, [{"path": target.name, "operation": "patch",
            "base_hash": file_hash(target), "result_hash": "0" * 64,
            "edits": [{"start": 0, "end": 0, "content": "# new\n"}]}])
        original_read = Path.read_bytes
        hidden = False
        def deny_hidden(path):
            if hidden and Path(path).resolve() == target.resolve():
                raise AssertionError("ignored patch base must never be read")
            return original_read(path)
        def provider(*args, **kwargs):
            nonlocal hidden
            with (self.root / ".git/info/exclude").open("a") as stream:
                stream.write("\n" + target.name + "\n")
            hidden = True
            return value
        with patch("loop_work.providers.structured_call", side_effect=provider), patch.object(Path, "read_bytes", deny_hidden):
            response = Delegation(self.kb, self.task_id, self.root).run(request)
        self.assertEqual(response["assignment"]["status"], "blocked")
        self.assertNotIn("candidate_id", self.kb.get("delegation", response["assignment"]["id"]))

    def test_write_only_deleted_output_cannot_reappear_at_done_reuse_boundaries(self):
        self.running()
        worker = Delegation(self.kb, self.task_id, self.root)
        for kind in ("directory", "ignored-file", "symlink"):
            with self.subTest(kind=kind):
                name = "deleted-" + kind + ".py"
                target = self.root / name
                target.write_text("OLD = 1\n")
                request = assignment("write-only-" + kind, "implementation", [name])
                self.assertNotIn(name, request["read_paths"])
                with patch.dict(os.environ, {"LOOP_WORKER_EDITS": json.dumps({name: None})}):
                    response = worker.run(request)
                assessment = fixture_assessment(self.kb, response)
                response = worker.assess(assessment)
                self.assertTrue(response["passed"], response)
                self.assertTrue(worker.assess(assessment)["reused"])
                self.assertTrue(worker.run(request)["reused"])
                before = worker.observation()["digest"]
                with (self.root / ".git/info/exclude").open("a") as stream:
                    stream.write("\n" + name + "\n")
                if kind == "directory":
                    target.mkdir()
                elif kind == "symlink":
                    target.symlink_to(self.root / "value.py")
                else:
                    target.write_text("IGNORED = 1\n")
                self.assertEqual(worker.observation()["digest"], before)
                record_before = copy.deepcopy(self.kb.get("delegation", response["assignment"]["id"]))
                budget_before = self.kb.get("worker-budget", self.task_id)
                with patch("loop_work.providers.structured_call", side_effect=AssertionError("must not call")):
                    with self.assertRaises(LoopError):
                        worker.assess(assessment)
                    self.assertFalse(self.check(request)["passed"])
                    with self.assertRaises(LoopError):
                        worker.run(request)
                self.assertEqual(self.kb.get("delegation", response["assignment"]["id"]), record_before)
                self.assertEqual(self.kb.get("worker-budget", self.task_id), budget_before)
                if target.is_dir():
                    target.rmdir()
                else:
                    target.unlink()

    def test_accepted_delete_kind_is_absent_and_cannot_become_directory(self):
        self.running()
        request = assignment("deleted-output", "implementation", ["value.py"])
        worker = Delegation(self.kb, self.task_id, self.root)
        with patch.dict(os.environ, {"LOOP_WORKER_EDITS": json.dumps({"value.py": None})}):
            response = worker.run(request)
        response = worker.assess(fixture_assessment(self.kb, response))
        record = self.kb.get("delegation", response["assignment"]["id"])
        self.assertFalse((self.root / "value.py").exists())
        current = worker.observation()
        self.assertFalse(worker._read_scope_changed(record, current))
        kinds = worker._read_scope(request, current)
        kinds["value.py"] = "directory"
        with patch.object(worker, "_read_scope", return_value=kinds):
            self.assertTrue(worker._read_scope_changed(record, current))

    def test_done_kind_exception_requires_actual_candidate_change(self):
        self.running()
        request = assignment("unchanged-writable", "implementation", ["unused-output.py"])
        request["read_paths"].append("unused-output.py")
        worker = Delegation(self.kb, self.task_id, self.root)
        response = worker.run(request)
        record = self.kb.get("delegation", response["assignment"]["id"])
        self.assertEqual(worker.candidate(record)["changes"], [])
        response = worker.assess(fixture_assessment(self.kb, response))
        record = self.kb.get("delegation", response["assignment"]["id"])
        current = worker.observation()
        kinds = worker._read_scope(request, current)
        kinds["unused-output.py"] = "directory"
        # Isolate the done exception from source_path's independent prohibition
        # on a directory spelled as a file: declared permission alone is not
        # an accepted contribution and cannot erase a presence difference.
        with patch.object(worker, "_read_scope", return_value=kinds):
            self.assertTrue(worker._read_scope_changed(record, current))

    def test_candidate_reuse_blocks_absent_read_becoming_ignored_file(self):
        self.ignored_read_transition(accepted=False)

    def test_completed_reuse_blocks_absent_read_becoming_ignored_file(self):
        self.ignored_read_transition(accepted=True)

    def test_stale_pending_candidate_requires_recovery_and_never_mutates_during_check(self):
        Delegation(self.kb, self.task_id, self.root).run(assignment())
        (self.root / "value.py").write_text("VALUE = 3\n")
        before = self.frozen_bytes()
        self.assertFalse(self.check()["passed"])
        recovered = self.check(recover="Inspected source drift and candidate logs")
        self.assertTrue(recovered["passed"], recovered)
        self.assertEqual(recovered["action"], "dispatch")
        self.assertEqual(self.frozen_bytes(), before)

    def test_frozen_runtime_drift_fails_check_and_actual_dispatch(self):
        self.running()
        state, _, _ = self.engine.load()
        state["frozen_inputs"]["engine"] = "different-runtime"
        write_json(self.engine.state_path, state)
        before = self.frozen_bytes()
        checked = self.check()
        self.assertFalse(checked["passed"])
        self.assertEqual(checked["diagnostics"][0]["code"], "runtime_drift")
        with self.assertRaisesRegex(LoopError, "engine changed"):
            Delegation(self.kb, self.task_id, self.root).run(assignment())
        # Actual dispatch takes locks; only the read-only check is byte-exact.
        self.assertEqual({k: v for k, v in self.frozen_bytes().items() if not k.endswith("lock")},
                         {k: v for k, v in before.items() if not k.endswith("lock")})

    def test_draft_implementation_and_exhausted_budget_are_setup_failures(self):
        request = assignment(kind="implementation", writes=["value.py"])
        self.assertFalse(self.check(request)["passed"])
        self.kb.put("worker-budget", {"id": self.task_id, "calls": 40})
        before = self.frozen_bytes()
        checked = self.check()
        self.assertFalse(checked["passed"])
        self.assertEqual(checked["diagnostics"][0]["code"], "budget")
        self.assertEqual(self.frozen_bytes(), before)

    def test_cli_development_and_common_work_check_are_read_only(self):
        source = Path(__file__).resolve().parents[1] / "scripts/loop.py"
        request_path = Path(self.temp.name) / "request.json"
        write_json(request_path, assignment(goal_criteria=("goal_setting",)))
        argv = [sys.executable, str(source), "--knowledge-home", str(self.kb.home), "--root", str(self.root)]
        before = self.frozen_bytes()
        result = subprocess.run([*argv, "delegate", self.engine.id, "--input", str(request_path), "--check"],
                                capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(json.loads(result.stdout)["check_only"])
        self.assertEqual(self.frozen_bytes(), before)
        work = Work(self.kb)
        task = work.open("document", "Describe a value", "codex", [self.root])["task"]["id"]
        before = self.frozen_bytes()
        result = subprocess.run([*argv, "work", "delegate", task, "--input", str(request_path), "--check"],
                                capture_output=True, text=True, env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        self.assertTrue(json.loads(result.stdout)["passed"])
        self.assertEqual(self.frozen_bytes(), before)
