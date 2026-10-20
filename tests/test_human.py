from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from loop_work.human import HumanDesk, KIND
from loop_work.knowledge import KnowledgeBase
from loop_work.orchestration import Orchestration, worker_context
from loop_work.storage import LoopError, digest, file_hash, write_json
from loop_work.work import Work


class HumanTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "project"
        self.root.mkdir()
        (self.root / "input.txt").write_text("original\n")
        self.kb = KnowledgeBase(Path(self.temp.name) / "knowledge")
        self.work = Work(self.kb)
        self.task = self.work.open("document", "Write a description", "codex", [self.root])["task"]
        self.desk = HumanDesk(self.kb)

    def steer(self, task_id=None, kind="constraint"):
        task_id = task_id or self.task["id"]
        task = self.kb.get("task", task_id)
        control = self.kb.get("orchestration", task["session_id"], required=False) or {"control_version": 0}
        return Orchestration(self.kb).feedback(task["session_id"], {
            "id": "concurrent-" + str(control["control_version"]), "task_id": task_id, "kind": kind,
            "summary": "Preserve the explicitly requested output", "original_input_ref": "conversation:user-steering",
            "applies_to": "This task", "supersedes": []}, control["control_version"])

    def retained_fields(self):
        from test_delegation import assignment
        return {"request": assignment("retained"), "summary": "Retained original result", "provider": "codex",
                "attempts": 1, "root": str(self.root), "applied": [], "directory": str(self.kb.home),
                "started_at": "2026-01-01T00:00:00+00:00"}

    def request(self, name="human-choice", kind="decision", action=None):
        return {"id": name, "kind": kind, "title": "Choose the delivery", "question": "Which output do you want?",
                "options": ["A", "B"], "action": action}

    def blocked_request(self):
        self.work._stop_internal(self.task["id"], "Needs a human decision")
        return self.desk.create(self.task["id"], self.request(kind="approval", action="resume_task"))

    def test_raw_answer_is_scoped_visible_and_immutable_not_a_gate_pass(self):
        original_task = self.kb.get("task", self.task["id"])
        request = self.desk.create(self.task["id"], self.request())
        pending = worker_context(self.kb, self.task["id"])
        self.assertTrue(pending["blocked"])
        self.assertEqual(pending["needs_human"][0]["id"], request["id"])
        raw = {"decision": "answer", "text": "B — preserve my exact wording.\nNo commit."}
        answered = self.desk.respond(request["id"], raw, 1)
        self.assertEqual(answered["revision"], 2)
        self.assertEqual(answered["history"][0]["status"], "pending")
        view = worker_context(self.kb, self.task["id"])
        self.assertFalse(view["blocked"])
        self.assertTrue(view["requires_worker"])
        self.assertEqual(view["human_responses"][0]["response"], raw)
        self.assertNotEqual(view["substantive_revision"], pending["substantive_revision"])
        capsule = Orchestration(self.kb).context(self.task["session_id"], self.task["id"])
        self.assertEqual(capsule["human_requests"][0]["response"], raw)
        self.assertEqual(self.kb.get("task", self.task["id"]), original_task)
        with self.assertRaises(LoopError):
            self.desk.respond(request["id"], raw, 1)
        with self.assertRaises(LoopError):
            self.desk.execute(request["id"], 2)
        other = self.work.open("document", "Other task", "codex", [self.root], self.task["session_id"])["task"]
        self.assertEqual(worker_context(self.kb, other["id"])["human_requests"], [])

    def test_resume_uses_existing_work_once_and_preserves_budgets_and_goal(self):
        record = self.blocked_request()
        task_before = self.kb.get("task", self.task["id"])
        self.kb.put("worker-budget", {"id": self.task["id"], "calls": 2})
        # A budget change after creation invalidates the original request.
        with self.assertRaisesRegex(LoopError, "stale"):
            self.desk.respond(record["id"], {"decision": "approve", "text": "Resume this task."}, 1)
        replacement = self.request("current-resume", "approval", "resume_task")
        replacement["supersedes"] = [record["id"]]
        record = self.desk.create(self.task["id"], replacement)
        record = self.desk.respond(record["id"], {"decision": "approve", "text": "Resume this task."}, 1)
        budget = self.kb.get("worker-budget", self.task["id"])
        with patch.object(Work, "resume", autospec=True, wraps=Work.resume) as call:
            # Use the actual method; autospec/wraps does not call it automatically.
            call.side_effect = lambda instance, task_id, **kwargs: Work_resume(instance, task_id, **kwargs)
            result = self.desk.execute(record["id"], record["revision"])
            self.assertEqual(call.call_count, 1)
            with self.assertRaises(LoopError):
                self.desk.execute(record["id"], record["revision"])
            with self.assertRaises(LoopError):
                self.desk.execute(record["id"], result["revision"])
            self.assertEqual(call.call_count, 1)
        self.assertEqual(result["status"], "executed")
        task_after = self.kb.get("task", self.task["id"])
        self.assertEqual(task_after["phase"], "goal_setting")
        self.assertEqual(task_after["goal"], task_before["goal"])
        self.assertEqual(self.kb.get("worker-budget", self.task["id"]), budget)
        self.assertEqual([row["revision"] for row in result["history"]], [1, 2, 3])

    def test_source_or_task_drift_rejects_response_without_writing(self):
        record = self.desk.create(self.task["id"], self.request())
        (self.root / "input.txt").write_text("changed\n")
        with self.assertRaisesRegex(LoopError, "stale"):
            self.desk.respond(record["id"], {"decision": "answer", "text": "A"}, 1)
        self.assertEqual(self.desk.show(record["id"]), record)
        (self.root / "input.txt").write_text("original\n")
        changed = self.kb.get("task", self.task["id"])
        changed["title"] = "Different task intent"
        self.kb.put("task", changed)
        with self.assertRaisesRegex(LoopError, "stale"):
            self.desk.respond(record["id"], {"decision": "answer", "text": "A"}, 1)
        self.assertEqual(self.desk.show(record["id"]), record)

    def test_execution_drift_and_unverified_worker_foundation_do_not_resume(self):
        record = self.blocked_request()
        record = self.desk.respond(record["id"], {"decision": "approve", "text": "Resume."}, 1)
        (self.root / "input.txt").write_text("changed\n")
        with patch.object(Work, "resume", side_effect=AssertionError("must not resume")):
            with self.assertRaisesRegex(LoopError, "stale"):
                self.desk.execute(record["id"], 2)
        self.assertEqual(self.desk.show(record["id"]), record)
        (self.root / "input.txt").write_text("original\n")
        result = self.kb.home / "retained-result.json"
        write_json(result, {"summary": "Original retained evidence"})
        self.kb.put("delegation", {**self.retained_fields(), "id": "retained", "task_id": self.task["id"], "status": "done",
                    "location_id": self.task["locations"][0], "result": str(result),
                    "result_digest": "0" * 64, "result_file_hash": file_hash(result)})
        current = self.desk.create(self.task["id"], self.request("retained-resume", "approval", "resume_task"))
        current = self.desk.respond(current["id"], {"decision": "approve", "text": "Resume."}, 1)
        with patch.object(Work, "resume", side_effect=AssertionError("must not resume")):
            with self.assertRaisesRegex(LoopError, "artifact changed"):
                self.desk.execute(current["id"], current["revision"])
        self.assertEqual(self.desk.show(current["id"]), current)
        self.assertEqual(self.kb.get("task", self.task["id"])["phase"], "blocked")

    def test_valid_retained_pins_allow_resume_and_exhausted_budget_does_not(self):
        self.work._stop_internal(self.task["id"], "Needs confirmation")
        result = self.kb.home / "retained-result.json"
        value = {"summary": "Original retained evidence"}
        write_json(result, value)
        self.kb.put("delegation", {**self.retained_fields(), "id": "retained", "task_id": self.task["id"], "status": "done",
                    "location_id": self.task["locations"][0], "result": str(result),
                    "result_digest": digest(value), "result_file_hash": file_hash(result)})
        record = self.desk.create(self.task["id"], self.request("valid-retained", "approval", "resume_task"))
        record = self.desk.respond(record["id"], {"decision": "approve", "text": "Resume the existing task."}, 1)
        self.assertEqual(self.desk.execute(record["id"], record["revision"])["status"], "executed")
        self.work._stop_internal(self.task["id"], "Call budget is exhausted")
        self.kb.put("worker-budget", {"id": self.task["id"], "calls": 40})
        record = self.desk.create(self.task["id"], self.request("exhausted", "approval", "resume_task"))
        record = self.desk.respond(record["id"], {"decision": "approve", "text": "Resume."}, 1)
        with self.assertRaisesRegex(LoopError, "budget exhausted"):
            self.desk.execute(record["id"], record["revision"])
        self.assertEqual(self.kb.get("worker-budget", self.task["id"])["calls"], 40)
        self.assertEqual(self.kb.get("task", self.task["id"])["phase"], "blocked")

    def test_decline_no_action_and_kind_validation(self):
        record = self.desk.create(self.task["id"], self.request(kind="approval", action="resume_task"))
        with self.assertRaisesRegex(LoopError, "kind"):
            self.desk.respond(record["id"], {"decision": "answer", "text": "A"}, 1)
        declined = self.desk.respond(record["id"], {"decision": "reject", "text": "Do not resume."}, 1)
        self.assertEqual(declined["status"], "declined")
        self.assertTrue(worker_context(self.kb, self.task["id"])["blocked"])
        self.assertEqual([item["id"] for item in self.desk.list()["requests"]], [declined["id"]])
        self.assertEqual(len(self.desk.list(include_closed=True)["requests"]), 1)
        with self.assertRaises(LoopError):
            self.desk.execute(record["id"], 2)
        with self.assertRaises(LoopError):
            self.desk.create(self.task["id"], self.request("shell", "approval", "shell"))
        with self.assertRaises(LoopError):
            self.desk.create(self.task["id"], self.request("goal-change", "decision", "resume_task"))

    def test_default_list_is_actionable_queue_and_history_retains_seven_states(self):
        pending = self.desk.create(self.task["id"], self.request("queue-pending"))
        states = [
            ("queue-declined", "declined", None, {"decision": "reject", "text": "Need another decision"}, None, None),
            ("queue-failed", "failed", "resume_task", {"decision": "approve", "text": "Resume"}, {"state": "failed"}, None),
            ("queue-resume", "answered", "resume_task", {"decision": "approve", "text": "Resume"}, None, None),
            ("history-answer", "answered", None, {"decision": "answer", "text": "Keep the format"}, None, None),
            ("history-executed", "executed", "resume_task", {"decision": "approve", "text": "Resume"}, {"state": "executed"}, None),
            ("history-superseded", "pending", None, None, None, pending["id"])]
        # Persisted lifecycle-state fixtures isolate queue selection from action
        # execution: rejected/failed requests need attention, answered facts do not.
        for name, status, action, response, execution, superseded_by in states:
            self.kb.put(KIND, {**copy.deepcopy(pending), "id": name, "status": status, "action": action,
                              "kind": "approval" if action else "decision", "response": response, "execution": execution, "superseded_by": superseded_by})
        listed = self.desk.list(task_id=self.task["id"])
        self.assertEqual({item["id"] for item in listed["requests"]},
                         {"queue-pending", "queue-declined", "queue-failed", "queue-resume"})
        self.assertEqual(len(self.desk.list(include_closed=True)["requests"]), 7)
        resolved = self.desk.show("queue-resume")
        resolved["kind"] = "manual_action"
        resolved["response"] = {"decision": "resolved", "text": "Manual setup repaired"}
        self.kb.put(KIND, resolved)
        self.assertIn("queue-resume", {item["id"] for item in self.desk.list()["requests"]})

    def test_failed_execution_is_recorded_and_never_retried(self):
        record = self.blocked_request()
        record = self.desk.respond(record["id"], {"decision": "approve", "text": "Resume."}, 1)
        with patch.object(Work, "resume", side_effect=LoopError("Original blocker remains")) as call:
            failed = self.desk.execute(record["id"], record["revision"])
            self.assertEqual(failed["status"], "failed")
            self.assertIn("Original blocker", failed["execution"]["error"])
            with self.assertRaises(LoopError):
                self.desk.execute(record["id"], failed["revision"])
            self.assertEqual(call.call_count, 1)
        self.assertEqual(self.kb.get("task", self.task["id"])["phase"], "blocked")

    def test_explicit_supersession_preserves_history_and_never_inherits_approval(self):
        old = self.blocked_request()
        old = self.desk.respond(old["id"], {"decision": "reject", "text": "Do not resume yet."}, 1)
        self.assertTrue(worker_context(self.kb, self.task["id"])["blocked"])
        payload = self.request("replacement", "approval", "resume_task")
        payload["supersedes"] = [old["id"]]
        new = self.desk.create(self.task["id"], payload)
        self.assertEqual(new["status"], "pending")
        self.assertIsNone(new["response"])
        self.assertIsNone(new["execution"])
        replaced = self.desk.show(old["id"])
        self.assertEqual(replaced["response"], old["response"])
        self.assertEqual(replaced["superseded_by"], new["id"])
        view = worker_context(self.kb, self.task["id"])
        self.assertEqual([item["id"] for item in view["needs_human"]], [new["id"]])
        with self.assertRaisesRegex(LoopError, "superseded"):
            self.desk.respond(old["id"], {"decision": "approve", "text": "Old approval"}, replaced["revision"])
        with self.assertRaises(LoopError):
            self.desk.execute(new["id"], new["revision"])
        self.desk.respond(new["id"], {"decision": "approve", "text": "Resume now."}, 1)
        self.assertFalse(worker_context(self.kb, self.task["id"])["blocked"])
        for ids in (["missing"], [new["id"], new["id"]], ["cyclic"]):
            invalid = self.request("cyclic")
            invalid["supersedes"] = ids
            with self.assertRaises(LoopError):
                self.desk.create(self.task["id"], invalid)
        other = self.work.open("document", "Other", "codex", [self.root])["task"]
        invalid = self.request("other-task")
        invalid["supersedes"] = [new["id"]]
        with self.assertRaisesRegex(LoopError, "same task"):
            self.desk.create(other["id"], invalid)

    def test_response_rechecks_authority_after_current_before_atomic_write(self):
        for kind in ("constraint", "pause", "task", "budget", "source"):
            with self.subTest(kind=kind):
                record = self.desk.create(self.task["id"], self.request("race-response-" + kind))
                original = self.desk._current
                def interleave(*args):
                    current = original(*args)
                    if kind in ("constraint", "pause"):
                        self.steer(kind=kind)
                    elif kind == "task":
                        task = self.kb.get("task", self.task["id"])
                        task["title"] += " changed"
                        self.kb.put("task", task)
                    elif kind == "budget":
                        self.kb.put("worker-budget", {"id": self.task["id"], "calls": 3})
                    else:
                        (self.root / "input.txt").write_text("concurrent source\n")
                    return current
                with patch.object(self.desk, "_current", side_effect=interleave):
                    with self.assertRaisesRegex(LoopError, "stale"):
                        self.desk.respond(record["id"], {"decision": "answer", "text": "A"}, 1)
                self.assertEqual(self.desk.show(record["id"]), record)

    def test_execution_rechecks_authority_after_current_before_claim(self):
        record = self.blocked_request()
        record = self.desk.respond(record["id"], {"decision": "approve", "text": "Resume."}, 1)
        original = self.desk._current
        task_before = self.kb.get("task", self.task["id"])
        def interleave(*args):
            current = original(*args)
            self.steer()
            return current
        with patch.object(self.desk, "_current", side_effect=interleave), patch.object(Work, "resume", side_effect=AssertionError("must not resume")):
            with self.assertRaisesRegex(LoopError, "stale"):
                self.desk.execute(record["id"], record["revision"])
        self.assertEqual(self.desk.show(record["id"]), record)
        self.assertEqual(self.kb.get("task", self.task["id"]), task_before)

    def test_resume_transaction_rejects_feedback_committed_after_claim(self):
        record = self.blocked_request()
        record = self.desk.respond(record["id"], {"decision": "approve", "text": "Resume."}, 1)
        task_before = self.kb.get("task", self.task["id"])
        def interleave(instance, task_id, **kwargs):
            self.steer()
            return Work_resume(instance, task_id, **kwargs)
        with patch.object(Work, "resume", autospec=True, side_effect=interleave):
            result = self.desk.execute(record["id"], record["revision"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("stale", result["execution"]["error"])
        self.assertEqual(self.kb.get("task", self.task["id"]), task_before)

    def test_resume_transaction_rejects_task_budget_and_source_changes_after_claim(self):
        for kind in ("task", "budget", "source"):
            with self.subTest(kind=kind):
                task = self.work.open("document", "Blocked task " + kind, "codex", [self.root])["task"]
                self.work._stop_internal(task["id"], "Needs a human confirmation")
                record = self.desk.create(task["id"], self.request("late-change-" + kind, "approval", "resume_task"))
                response = {"decision": "approve", "text": "Resume only this unchanged task."}
                record = self.desk.respond(record["id"], response, 1)
                def interleave(instance, task_id, **kwargs):
                    if kind == "task":
                        changed = self.kb.get("task", task_id)
                        changed["title"] = "Changed after approval"
                        self.kb.put("task", changed)
                    elif kind == "budget":
                        self.kb.put("worker-budget", {"id": task_id, "calls": 3})
                    else:
                        (self.root / "input.txt").write_text("changed after claim\n")
                    return Work_resume(instance, task_id, **kwargs)
                with patch.object(Work, "resume", autospec=True, side_effect=interleave):
                    result = self.desk.execute(record["id"], record["revision"])
                self.assertEqual(result["status"], "failed")
                self.assertIn("stale", result["execution"]["error"])
                self.assertEqual(result["response"], response)
                self.assertEqual(self.kb.get("task", task["id"])["phase"], "blocked")

    def test_other_task_feedback_does_not_invalidate_response_or_execution(self):
        record = self.blocked_request()
        other = self.work.open("document", "Other task", "codex", [self.root], self.task["session_id"])["task"]
        self.steer(other["id"])
        record = self.desk.respond(record["id"], {"decision": "approve", "text": "Resume the original task."}, 1)
        self.steer(other["id"])
        result = self.desk.execute(record["id"], record["revision"])
        self.assertEqual(result["status"], "executed", result)
        self.assertEqual(self.kb.get("task", self.task["id"])["phase"], "goal_setting")

    def test_feedback_receipt_includes_pending_human_gate(self):
        request = self.desk.create(self.task["id"], self.request())
        receipt = Orchestration(self.kb).feedback(self.task["session_id"], {
            "id": "user-steering", "task_id": self.task["id"], "kind": "constraint",
            "summary": "Preserve the output contract", "original_input_ref": "conversation:user-message",
            "applies_to": "This task", "supersedes": []}, 0)
        view = worker_context(self.kb, self.task["id"])
        self.assertTrue(receipt["blocked"])
        self.assertEqual(receipt["feedback_revision"], view["revision"])
        self.assertIn("human response", receipt["block_reason"])
        self.assertEqual(view["needs_human"][0]["id"], request["id"])

    def test_time_budget_exhaustion_blocks_resume_without_attempt(self):
        self.work._stop_internal(self.task["id"], "Wait for the operator")
        task = self.kb.get("task", self.task["id"])
        task["started_at"] = "2000-01-01T00:00:00+00:00"
        self.kb.put("task", task)
        record = self.desk.create(self.task["id"], self.request("time-expired", "manual_action", "resume_task"))
        record = self.desk.respond(record["id"], {"decision": "resolved", "text": "Setup repaired."}, 1)
        with patch.object(Work, "resume", side_effect=AssertionError("must not resume")):
            with self.assertRaisesRegex(LoopError, "budget exhausted"):
                self.desk.execute(record["id"], record["revision"])
        self.assertEqual(self.desk.show(record["id"]), record)

    def test_evidence_pin_and_cli_round_trip(self):
        payload = self.request()
        evidence = self.root / "input.txt"
        payload["evidence"] = [{"ref": str(evidence), "modepin": file_hash(evidence)}]
        record = self.desk.create(self.task["id"], payload)
        source = Path(__file__).resolve().parents[1] / "scripts/loop.py"
        result = subprocess.run([sys.executable, str(source), "--knowledge-home", str(self.kb.home),
                                 "human", "show", record["id"]], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["id"], record["id"])
        evidence.chmod(0o700)
        with self.assertRaisesRegex(LoopError, "stale"):
            self.desk.respond(record["id"], {"decision": "answer", "text": "A"}, 1)


Work_resume = Work.resume


from support import ProjectTest


class HumanDevelopmentTests(ProjectTest):
    def setUp(self):
        super().setUp()
        self.kb = self.engine.knowledge
        self.task_id = self.engine.refresh()["work_id"]
        self.desk = HumanDesk(self.kb)

    @staticmethod
    def payload(name, kind="decision", action=None):
        return {"id": name, "kind": kind, "title": "Confirm delivery", "question": "Keep this delivery scope?",
                "options": ["Keep the existing scope"], "action": action}

    def test_real_refresh_context_response_and_blocked_resume_remain_valid(self):
        self.running()
        request = self.desk.create(self.task_id, self.payload("dev-decision"))
        fingerprint = request["fingerprint"]
        self.engine.refresh()
        Work(self.kb).context(self.task_id)
        Orchestration(self.kb).context(request["session_id"], self.task_id)
        self.assertEqual(self.desk._snapshot(self.task_id), fingerprint)
        answer = self.desk.respond(request["id"], {"decision": "answer", "text": "Keep the existing scope."}, 1)
        self.assertEqual(answer["status"], "answered")
        self.engine._block_internal("Operator repaired local setup", retryable=True)
        request = self.desk.create(self.task_id, self.payload("dev-resume", "approval", "resume_task"))
        before = self.engine.load()
        self.engine.refresh()
        Work(self.kb).context(self.task_id)
        request = self.desk.respond(request["id"], {"decision": "approve", "text": "Resume this same goal."}, 1)
        result = self.desk.execute(request["id"], request["revision"])
        self.assertEqual(result["status"], "executed", result)
        after = self.engine.load()
        self.assertEqual(after[0]["phase"], "running")
        self.assertEqual(after[1:], before[1:])
        self.assertEqual(after[0]["milestones"], before[0]["milestones"])
        self.assertEqual(after[0]["started_at"], before[0]["started_at"])

    def test_development_resume_transaction_rejects_feedback_after_claim(self):
        from loop_work.engine import Engine
        self.running()
        self.engine._block_internal("Setup requires human confirmation", retryable=True)
        request = self.desk.create(self.task_id, self.payload("dev-race-resume", "approval", "resume_task"))
        request = self.desk.respond(request["id"], {"decision": "approve", "text": "Resume."}, 1)
        before = self.engine.load()[0]
        original_resume = Engine.resume
        def interleave(instance, **kwargs):
            task = self.kb.get("task", self.task_id)
            Orchestration(self.kb).feedback(task["session_id"], {
                "id": "late-user-input", "task_id": self.task_id, "kind": "constraint",
                "summary": "Preserve the original accepted behavior", "original_input_ref": "conversation:user-input",
                "applies_to": "This goal", "supersedes": []}, 0)
            return original_resume(instance, **kwargs)
        with patch.object(Engine, "resume", autospec=True, side_effect=interleave):
            result = self.desk.execute(request["id"], request["revision"])
        self.assertEqual(result["status"], "failed")
        self.assertIn("stale", result["execution"]["error"])
        self.assertEqual(self.engine.load()[0], before)

    def test_real_development_phase_goal_budget_and_source_drift_stay_stale(self):
        original_state = self.engine.state_path.read_bytes()
        contract_path = self.engine.goal_dir / "contract.json"
        original_contract = contract_path.read_bytes()
        original_source = (self.root / "value.py").read_bytes()
        for kind in ("phase", "goal", "budget", "source"):
            with self.subTest(kind=kind):
                request = self.desk.create(self.task_id, self.payload("dev-drift-" + kind))
                if kind == "phase":
                    state = self.engine.load()[0]
                    state["phase"] = "blocked"
                    write_json(self.engine.state_path, state)
                elif kind == "goal":
                    contract = self.engine.load()[1]
                    contract["target"]["outcome"] = "A changed product goal"
                    write_json(contract_path, contract)
                elif kind == "budget":
                    self.kb.put("worker-budget", {"id": self.task_id, "calls": 1})
                else:
                    (self.root / "value.py").write_text("VALUE = 9\n")
                with self.assertRaisesRegex(LoopError, "stale"):
                    self.desk.respond(request["id"], {"decision": "answer", "text": "Keep it."}, 1)
                self.assertEqual(self.desk.show(request["id"]), request)
                self.engine.state_path.write_bytes(original_state)
                contract_path.write_bytes(original_contract)
                (self.root / "value.py").write_bytes(original_source)
                with self.kb.connection() as db:
                    db.execute("DELETE FROM records WHERE kind='worker-budget' AND id=?", (self.task_id,))
