from __future__ import annotations

import json
import os
from unittest.mock import patch
from pathlib import Path

from loop_work.contract import validate
from loop_work.engine import Engine
from loop_work.storage import LoopError, read_json, snapshot, write_json
from support import ProjectTest


class LifecycleTests(ProjectTest):
    def test_gate_checks_accepted_worker_pins_before_checks_review_or_attempt_spending(self):
        from loop_work.delegation import Delegation
        from loop_work.human import HumanDesk
        from support import fixture_assessment
        from test_delegation import assignment
        self.running()
        kb = self.engine.knowledge
        task_id = self.engine.refresh()["work_id"]
        worker = Delegation(kb, task_id, self.root)
        for human in (False, True):
            with self.subTest(substantive_human=human):
                if human:
                    desk = HumanDesk(kb)
                    asked = desk.create(task_id, {"id": "gate-choice", "kind": "decision", "title": "Confirm contract",
                        "question": "Keep the same behavior?", "options": [], "action": None})
                    desk.respond(asked["id"], {"decision": "answer", "text": "Keep the frozen target."}, 1)
                request = assignment("gate-unit-" + str(human))
                value = {"status": "done", "summary": "VALUE is defined in value.py.",
                    "outputs": [{"id": row["id"], "content": "VALUE equals one.", "evidence": ["value.py:1"]} for row in request["deliverables"]],
                    "coverage": [{"criterion_id": row["id"], "satisfied": True, "evidence": "value.py:1"} for row in request["criteria"]],
                    "changes": [], "findings": [], "blockers": []}
                # Preserve one work unit across the two passes; new input is
                # consumed on its current source-bound turn after human feedback.
                request["id"] = "gate-pinned-unit"
                with patch("loop_work.providers.structured_call", return_value=value):
                    result = worker.run(request, recover="Consume current human feedback" if human else None)
                    worker.assess(fixture_assessment(kb, result))
                record = kb.get("delegation", result["assignment"]["id"])
                for target in (Path(record["assessment_ref"]), Path(record["directory"]) / "dispatch.json"):
                    original = target.read_bytes()
                    if target.name == "dispatch.json":
                        dispatch = read_json(target)
                        dispatch["before"]["digest"] = "tampered"
                        write_json(target, dispatch)
                    else:
                        target.write_bytes(original + b" ")
                    state_before = self.engine.state_path.read_bytes()
                    budget = kb.get("worker-budget", task_id)
                    with patch("loop_work.engine.execute", side_effect=AssertionError("must not run checks")), patch("loop_work.providers.review", side_effect=AssertionError("must not review")):
                        with self.assertRaises(LoopError):
                            self.engine.gate("M1")
                    self.assertEqual(self.engine.state_path.read_bytes(), state_before)
                    self.assertEqual(kb.get("worker-budget", task_id), budget)
                    target.write_bytes(original)
        self.assertTrue(self.engine.gate("M1")["passed"])

    def test_full_loop_both_directions_and_fresh_final_verification(self):
        for implementer in ("claude", "codex"):
            with self.subTest(implementer=implementer):
                if implementer == "codex":
                    self.engine = Engine(self.root, "second")
                    self.engine.initialize("Second implementation", implementer)
                    self.fill_contract()
                self.running()
                checkpoint = self.engine.gate("M1")
                self.assertTrue(checkpoint["passed"])
                expected = "codex" if implementer == "claude" else "claude"
                self.assertEqual(checkpoint["review"]["provider"], expected)
                final = self.engine.gate()
                self.assertTrue(final["passed"])
                self.assertEqual(self.state()["phase"], "completed")
                self.assertNotEqual(checkpoint["review"]["artifact"], final["review"]["artifact"])
                self.assertTrue(self.engine.refresh()["evidence_current"])
                self.assertFalse(self.engine.active_path.exists())

    def test_failed_behavior_is_repaired_without_new_user_input(self):
        self.running()
        (self.root / "value.py").write_text("VALUE = 2\n")
        failed = self.engine.gate("M1")
        self.assertFalse(failed["passed"])
        self.assertIsNone(failed["review"])
        self.assertEqual(self.state()["phase"], "running")
        context = read_json(self.engine.state_dir / "context.json")
        self.assertEqual(context["next"]["action"], "implement")
        self.assertEqual(context["latest_gate"]["checks"][0]["process"]["exit_code"], 1)
        self.engine.note("discovery", "The consumer exposed a wrong value", "check.py assertion")
        (self.root / "value.py").write_text("VALUE = 1\n")
        self.assertTrue(self.engine.gate("M1")["passed"])
        self.assertTrue(self.engine.gate()["passed"])
        self.assertEqual(self.state()["attempts"]["milestone-M1"], 2)

    def test_review_findings_drive_repair_and_context_survives_new_engine(self):
        self.running()
        with patch.dict(os.environ, {"LOOP_TEST_VERDICT": "revise"}):
            self.assertFalse(self.engine.gate("M1")["passed"])
        recovered = Engine(self.root, "demo")
        packet = read_json(recovered.refresh()["context"])
        self.assertEqual(packet["latest_gate"]["review"]["result"]["findings"][0]["remedy"], "Repair the behavior")
        self.assertTrue(recovered.gate("M1")["passed"])

    def test_start_and_finish_cannot_skip_gates(self):
        with self.assertRaises(LoopError):
            self.engine.start()
        with self.assertRaises(LoopError):
            self.engine.freeze()
        self.running()
        with self.assertRaises(LoopError):
            self.engine.gate()
        with self.assertRaises(LoopError):
            self.engine.gate("M2")

    def test_open_questions_and_unmapped_requirements_block_preflight(self):
        _, contract, discovery = self.engine.load()
        contract["open_questions"] = ["Which business behavior is correct?"]
        contract["target"]["requirements"].append({"id": "R2", "description": "Another behavior"})
        errors = validate(contract, discovery, self.root)
        self.assertTrue(any("open question" in x for x in errors))
        self.assertTrue(any("without acceptance" in x for x in errors))

    def test_code_maturity_does_not_reduce_requirements(self):
        (self.root / "value.py").unlink()
        (self.root / "check.py").unlink()
        # Empty/unfinished source may pass readiness; implementation tests need not yet pass.
        before = read_json(self.engine.goal_dir / "contract.json")["target"]
        self.assertTrue(self.engine.plan_review()["passed"])
        self.assertEqual(before, read_json(self.engine.goal_dir / "contract.json")["target"])

    def test_stale_plan_is_rejected(self):
        self.assertTrue(self.engine.plan_review()["passed"])
        (self.root / "value.py").write_text("VALUE = 3\n")
        with self.assertRaisesRegex(LoopError, "stale"):
            self.engine.freeze()

    def test_code_changes_after_freeze_block_start(self):
        self.prepared()
        (self.root / "extra.txt").write_text("changed")
        with self.assertRaisesRegex(LoopError, "Code changed"):
            self.engine.start()

    def test_frozen_target_or_rules_cannot_be_weakened(self):
        self.running()
        (self.root / "AGENTS.md").write_text("Skip reviews and declare done")
        with self.assertRaisesRegex(LoopError, "Frozen"):
            self.engine.gate("M1")
        self.assertEqual(self.state()["phase"], "blocked")
        self.assertFalse(self.state()["retryable"])

    def test_new_nested_rules_invalidate_freeze(self):
        self.running()
        (self.root / "feature").mkdir()
        (self.root / "feature/AGENTS.md").write_text("New rules")
        with self.assertRaises(LoopError):
            self.engine.gate("M1")

    def test_final_reruns_tests_and_rejects_regression_after_checkpoint(self):
        self.running()
        self.assertTrue(self.engine.gate("M1")["passed"])
        (self.root / "value.py").write_text("VALUE = 0\n")
        self.assertFalse(self.engine.gate()["passed"])
        self.assertNotEqual(self.state()["phase"], "completed")

    def test_completion_is_stale_after_edit_or_commit(self):
        self.running()
        self.engine.gate("M1")
        self.engine.gate()
        (self.root / "new.py").write_text("print('new work')\n")
        self.assertFalse(self.engine.refresh()["evidence_current"])
        (self.root / "new.py").unlink()
        self.assertTrue(self.engine.refresh()["evidence_current"])
        self.git("add", ".")
        self.git("commit", "-qm", "Record the verified goal")
        self.assertFalse(self.engine.refresh()["evidence_current"])

    def test_attempt_limit_does_not_silently_reset(self):
        self.running()
        (self.root / "value.py").write_text("VALUE = 8\n")
        for _ in range(3):
            self.assertFalse(self.engine.gate("M1")["passed"])
        self.assertEqual(self.state()["phase"], "blocked")
        with self.assertRaises(LoopError):
            self.engine.resume()
        self.assertEqual(self.state()["attempts"]["milestone-M1"], 3)

    def test_external_provider_failure_and_resume_preserve_attempts(self):
        self.running()
        with patch.dict(os.environ, {"LOOP_TEST_FAIL": "1"}):
            self.assertFalse(self.engine.gate("M1")["passed"])
        self.assertTrue(self.state()["retryable"])
        self.engine.resume()
        self.assertTrue(self.engine.gate("M1")["passed"])
        self.assertEqual(self.state()["attempts"]["milestone-M1"], 2)

    def test_second_active_goal_is_rejected_and_abort_preserves_code(self):
        self.running()
        other = Engine(self.root, "other")
        other.initialize("Second goal", "codex")
        with self.assertRaisesRegex(LoopError, "Another goal"):
            other.active(claim=True)
        self.engine.abort("Superseded by a separately clarified goal")
        self.assertTrue((self.root / "value.py").exists())
        other.active(claim=True)

    def test_interrupted_gate_consumes_attempt_and_can_resume(self):
        self.running()
        state = self.state()
        state["inflight"] = "interrupted-gate"
        state["attempts"]["milestone-M1"] = 1
        write_json(self.engine.state_path, state)
        with self.assertRaisesRegex(LoopError, "Interrupted gate"):
            self.engine.gate("M1")
        self.engine.resume()
        self.assertTrue(self.engine.gate("M1")["passed"])
        self.assertEqual(self.state()["attempts"]["milestone-M1"], 2)

    def test_changed_sources_are_in_reviewer_context(self):
        self.running()
        (self.root / "value.py").write_text("# Actual implementation\nVALUE = 1\n")
        self.engine.note("decision", "Keep the existing consumer API", "value.py and check.py")
        result = self.engine.gate("M1")
        from pathlib import Path
        prompt = (Path(result["review"]["artifact"]).parent / "prompt.txt").read_text()
        payload = json.loads(prompt.split("REVIEW DATA:\n", 1)[1])
        self.assertIn("value.py", payload["changed_paths"])
        self.assertEqual(payload["execution_notes"][0]["text"], "Keep the existing consumer API")

    def test_snapshot_covers_dirty_deleted_and_untracked_files(self):
        before = snapshot(self.root)["digest"]
        (self.root / "untracked.txt").write_text("one")
        self.assertNotEqual(before, snapshot(self.root)["digest"])
        (self.root / "untracked.txt").unlink()
        (self.root / "value.py").unlink()
        self.assertNotEqual(before, snapshot(self.root)["digest"])

    def test_all_regression_checks_run_at_each_ordered_milestone(self):
        _, contract, _ = self.engine.load()
        regression = dict(contract["checks"][0], id="regression", kind="regression")
        contract["checks"].append(regression)
        contract["milestones"].append({"id": "M2", "title": "Verify integration", "acceptance_ids": ["A1"]})
        write_json(self.engine.goal_dir / "contract.json", contract)
        self.running()
        for milestone in ("M1", "M2"):
            result = self.engine.gate(milestone)
            self.assertTrue(result["passed"])
            self.assertEqual({x["id"] for x in result["checks"]}, {"behavior", "regression"})
        self.assertTrue(self.engine.gate()["passed"])

    def test_wall_time_budget_blocks_execution_and_resume(self):
        self.running()
        state = self.state()
        state["started_at"] = "2000-01-01T00:00:00+00:00"
        write_json(self.engine.state_path, state)
        with self.assertRaisesRegex(LoopError, "budget exhausted"):
            self.engine.gate("M1")
        self.assertEqual(self.state()["phase"], "blocked")
        with self.assertRaises(LoopError):
            self.engine.resume()

    def test_acceptance_commands_cannot_be_weakened_after_start(self):
        self.running()
        _, contract, _ = self.engine.load()
        contract["checks"][0]["argv"] = ["true"]
        write_json(self.engine.goal_dir / "contract.json", contract)
        with self.assertRaisesRegex(LoopError, "Frozen"):
            self.engine.gate("M1")
        self.assertFalse(self.state()["retryable"])


class RejectionTests(ProjectTest):
    def test_malformed_missing_and_question_responses_fail_closed(self):
        self.running()
        for env in ("LOOP_TEST_BAD_JSON", "LOOP_TEST_MISSING_COVERAGE", "LOOP_TEST_QUESTION"):
            with self.subTest(env=env), patch.dict(os.environ, {env: "1"}):
                result = self.engine.gate("M1")
                self.assertFalse(result["passed"])
                self.assertTrue(result["error"])
            if self.state().get("retryable"):
                self.engine.resume()
        self.assertEqual(self.state()["phase"], "blocked")

    def test_read_only_reviewer_mutation_is_not_accepted(self):
        self.running()
        with patch.dict(os.environ, {"LOOP_TEST_MUTATE": "1"}):
            result = self.engine.gate("M1")
        self.assertFalse(result["passed"])
        self.assertIn("reviewer changed", result["error"])

    def test_test_command_that_rewrites_source_is_not_accepted(self):
        (self.root / "check.py").write_text("from pathlib import Path\nPath('value.py').write_text('VALUE = 8\\n')\n")
        self.running()
        result = self.engine.gate("M1")
        self.assertFalse(result["passed"])
        self.assertIn("Checks changed", result["error"])

    def test_invalid_ids_and_escape_paths_rejected(self):
        with self.assertRaises(LoopError):
            Engine(self.root, "../outside")
        _, contract, discovery = self.engine.load()
        contract["checks"][0]["cwd"] = "../outside"
        self.assertTrue(any("escapes" in x for x in validate(contract, discovery, self.root)))

    def test_codex_only_reviews_are_fresh_and_selection_is_pinned(self):
        availability = patch("loop_work.providers.shutil.which", side_effect=lambda p:
                             str(self.bin / p) if (self.bin / p).is_file() else None)
        availability.start()
        self.addCleanup(availability.stop)
        (self.bin / "claude").unlink()
        self.engine = Engine(self.root, "codex-only")
        self.engine.initialize("Codex-only verification", "codex")
        self.fill_contract()
        _, contract, _ = self.engine.load()
        contract["execution"]["routing"]["profiles"] = [
            p for p in contract["execution"]["routing"]["profiles"] if p["provider"] == "codex"]
        # An opposite CLI appearing after preflight must not alter the selected
        # provider or demand a newly configured opposite profile at freeze/start.
        write_json(self.engine.goal_dir / "contract.json", contract)
        self.assertTrue(self.engine.plan_review()["passed"])
        (self.bin / "claude").write_text((self.bin / "codex").read_text())
        (self.bin / "claude").chmod(0o700)
        self.engine.freeze()
        self.engine.start()
        selection = self.state()["review_selection"]
        self.assertEqual(selection["mode"], "same_provider_fresh")
        first = self.engine.gate("M1")
        self.assertTrue(first["passed"])
        self.assertEqual(first["review"]["provider"], "codex")
        final = self.engine.gate()
        self.assertTrue(final["passed"])
        self.assertNotEqual(first["review"]["artifact"], final["review"]["artifact"])
        self.assertEqual(final["routing"]["review_selection"], selection)

    def test_repeated_preflight_preserves_selection_and_invalidates_prior_approval(self):
        availability = patch("loop_work.providers.shutil.which", side_effect=lambda p:
                             str(self.bin / p) if (self.bin / p).is_file() else None)
        availability.start()
        self.addCleanup(availability.stop)
        (self.bin / "codex").unlink()
        first = self.engine.plan_review()
        self.assertTrue(first["passed"])
        selection = self.state()["review_selection"]
        approval = self.state()["plan_review"]
        self.assertEqual(selection["mode"], "same_provider_fresh")
        (self.bin / "codex").write_text((self.bin / "claude").read_text())
        (self.bin / "codex").chmod(0o700)
        _, contract, _ = self.engine.load()
        original = json.loads(json.dumps(contract))
        contract["target"]["acceptance"] = []
        write_json(self.engine.goal_dir / "contract.json", contract)
        with self.assertRaises(LoopError):
            self.engine.plan_review()
        self.assertEqual(self.state()["review_selection"], selection)
        self.assertNotIn("plan_review", self.state())
        self.assertTrue(read_json(Path(approval))["passed"])
        write_json(self.engine.goal_dir / "contract.json", original)
        with self.assertRaisesRegex(LoopError, "Run the live independent"):
            self.engine.freeze()
        second = self.engine.plan_review()
        self.assertTrue(second["passed"])
        self.assertEqual(second["routing"]["review_selection"], selection)
        self.assertNotEqual(self.state()["plan_review"], approval)
        self.engine.freeze()

    def test_freeze_rejects_review_selection_mismatch(self):
        self.assertTrue(self.engine.plan_review()["passed"])
        state = self.state()
        state["review_selection"]["reason"] = "A different selection record"
        write_json(self.engine.state_path, state)
        with self.assertRaisesRegex(LoopError, "selection differs"):
            self.engine.freeze()

    def test_selected_opposite_failure_does_not_fallback(self):
        self.running()
        opposite = self.state()["review_selection"]["provider"]
        (self.bin / opposite).unlink()
        import shutil
        original_which = shutil.which
        with patch("loop_work.providers.shutil.which",
                   side_effect=lambda p: None if p == opposite else original_which(p)):
            result = self.engine.gate("M1")
        self.assertFalse(result["passed"])
        self.assertIn("Required CLI is not installed", result["error"])
        self.assertEqual(self.state()["review_selection"]["mode"], "cross_provider")

    def test_missing_provider_blocks_plan(self):
        (self.bin / "codex").unlink()
        with patch("loop_work.providers.shutil.which", return_value=None):
            with self.assertRaisesRegex(LoopError, "Required CLIs"):
                self.engine.plan_review()

    def test_claude_permission_denial_rejected(self):
        self.engine = Engine(self.root, "codex-denial")
        self.engine.initialize("Check Claude denial from Codex", "codex")
        self.fill_contract()
        self.running()
        with patch.dict(os.environ, {"LOOP_TEST_DENIED": "1"}):
            result = self.engine.gate("M1")
        self.assertFalse(result["passed"])
        self.assertIn("denied", result["error"])


class CheckFailurePolicyTests(ProjectTest):
    def configure(self, policy='fail_fast', first_passes=False, first_argv=None, first_timeout=5):
        import sys
        self.marker = Path(self.temp.name) / 'later-checks.txt'
        path = self.engine.goal_dir / 'contract.json'
        contract = read_json(path)
        if policy is None:
            contract['execution'].pop('check_failure_policy', None)
        else:
            contract['execution']['check_failure_policy'] = policy
        contract['checks'][0]['argv'] = [sys.executable, '-B', '-c', 'raise SystemExit('+('0' if first_passes else '3')+')']
        if first_argv is not None:
            contract['checks'][0]['argv'] = first_argv
            contract['checks'][0]['timeout_seconds'] = first_timeout
        contract['checks'].append({'id':'later','kind':'regression','cwd':'.','timeout_seconds':5,
            'argv':[sys.executable,'-B','-c',"from pathlib import Path;p=Path("+repr(str(self.marker))+");p.write_text((p.read_text() if p.exists() else '')+'ran\\n')"]})
        write_json(path,contract)
        self.running()

    def test_new_default_stops_after_failure_without_later_side_effect_or_review(self):
        self.configure()
        with patch('loop_work.providers.review',side_effect=AssertionError('Failed checks must not review')):
            result=self.engine.gate('M1')
        self.assertFalse(result['passed']);self.assertFalse(self.marker.exists())
        self.assertEqual([x['id'] for x in result['checks']],['behavior'])
        self.assertEqual(result['not_run_checks'],[{'id':'later','reason':'known_check_failure','after_check':'behavior'}])
        self.assertEqual(result['checks'][0]['process']['exit_code'],3)

    def test_explicit_diagnostic_continue_runs_later_checks_without_promoting_failure(self):
        self.configure('diagnostic_continue')
        result=self.engine.gate('M1')
        self.assertFalse(result['passed']);self.assertEqual(self.marker.read_text(),'ran\n')
        self.assertEqual(len(result['checks']),2);self.assertEqual(result['not_run_checks'],[])
        self.assertIsNone(result['review'])

    def test_legacy_absence_keeps_continuation_and_frozen_contract_bytes(self):
        self.configure(None)
        path=self.engine.goal_dir/'contract.json';before=path.read_bytes()
        result=self.engine.gate('M1')
        self.assertFalse(result['passed']);self.assertTrue(self.marker.exists())
        self.assertEqual(result['check_failure_policy'],'diagnostic_continue')
        self.assertEqual(path.read_bytes(),before)

    def test_successful_final_runs_every_check_again_and_obtains_fresh_review(self):
        self.configure(first_passes=True)
        first=self.engine.gate('M1');final=self.engine.gate()
        self.assertTrue(first['passed']);self.assertTrue(final['passed'])
        self.assertEqual(self.marker.read_text(),'ran\nran\n')
        self.assertEqual([x['id'] for x in final['checks']],['behavior','later'])
        self.assertEqual(final['not_run_checks'],[])
        self.assertNotEqual(first['review']['artifact'],final['review']['artifact'])

    def test_cancelled_check_retains_cause_and_does_not_run_later_check(self):
        self.configure('diagnostic_continue')
        value={'exit_code':-15,'timed_out':False,'cancelled':True,'cancel_reason':'Explicit task pause'}
        with patch('loop_work.engine.execute',return_value=value) as execute:
            result=self.engine.gate('M1')
        self.assertEqual(execute.call_count,1);self.assertTrue(result['cancelled'])
        self.assertEqual(result['error'],'Explicit task pause');self.assertFalse(self.marker.exists())
        self.assertEqual(result['not_run_checks'],[{'id':'later','reason':'cancelled'}])
        self.assertFalse(result['passed'])

    def test_real_timeout_is_retained_and_following_check_is_not_run(self):
        import sys
        self.configure(first_argv=[sys.executable,'-B','-c','import time;time.sleep(2)'],first_timeout=1)
        result=self.engine.gate('M1')
        self.assertFalse(result['passed']);self.assertTrue(result['checks'][0]['process']['timed_out'])
        self.assertFalse(self.marker.exists());self.assertEqual(result['not_run_checks'][0]['reason'],'known_check_failure')

    def test_mid_gate_budget_exhaustion_keeps_cause_and_unexecuted_check(self):
        self.configure('diagnostic_continue')
        with patch.object(self.engine,'remaining',side_effect=[100,100,0,0]):
            result=self.engine.gate('M1')
        self.assertFalse(result['passed']);self.assertEqual(result['error'],'Execution budget exhausted')
        self.assertFalse(self.marker.exists())
        self.assertEqual(result['not_run_checks'],[{'id':'later','reason':'execution_budget_exhausted'}])
        self.assertFalse(self.state()['retryable'])

    def test_frozen_policy_cannot_change_before_next_attempt(self):
        self.configure();path=self.engine.goal_dir/'contract.json';contract=read_json(path)
        contract['execution']['check_failure_policy']='diagnostic_continue';write_json(path,contract)
        before=self.state()['attempts'].copy()
        with self.assertRaises(LoopError):self.engine.gate('M1')
        self.assertEqual(self.state()['attempts'],before);self.assertFalse(self.marker.exists())
