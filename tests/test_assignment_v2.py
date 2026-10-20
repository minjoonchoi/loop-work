from __future__ import annotations
import copy
import json
from pathlib import Path
from unittest.mock import patch

from loop_work.assignment_contract import validate_revision
from loop_work.delegation import Delegation, validate_request
from loop_work.storage import LoopError, digest, file_hash, read_json
from support import ProjectTest, fixture_assessment
from test_delegation import assignment


def request_v2(name="owned-unit", kind="analysis", writes=()):
    request = assignment(name, kind, writes)
    request.update(schema_version=2, work_unit_id=name, request_revision=1,
                   previous_request_hash=None, correction_ledger=[])
    request["criteria"][0].update(execution_owner="worker", verification_mode="source_inspection")
    request["criteria"].append({"id": "root-proof", "description": "Root verifies the exact contribution after inspection.",
                                "execution_owner": "orchestrator", "verification_mode": "orchestrator_receipt"})
    return request


def worker_result(request, changes=None):
    return {"schema_version": 2, "status": "done", "summary": "The assigned draft is ready; root verification remains pending.",
            "outputs": [{"id": row["id"], "content": "VALUE = 1, supported by value.py.", "evidence": ["value.py:1"]}
                        for row in request["deliverables"]],
            "coverage": [{"criterion_id": row["id"], "satisfied": True if row["execution_owner"] == "worker" else None,
                          "evidence": "value.py:1" if row["execution_owner"] == "worker" else "Pending root-owned verification."}
                         for row in request["criteria"]],
            "changes": changes or [], "findings": [], "blockers": []}


class AssignmentV2Tests(ProjectTest):
    def setUp(self):
        super().setUp()
        self.kb = self.engine.knowledge
        self.task_id = self.engine.refresh()["work_id"]
        self.worker = Delegation(self.kb, self.task_id, self.root)

    def dispatch(self, request, value=None):
        with patch("loop_work.providers.structured_call", return_value=value or worker_result(request)):
            return self.worker.run(request)

    def assessment(self, result, origin=None):
        payload = fixture_assessment(self.kb, result)
        payload.update(schema_version=2, rejection=None)
        if origin:
            payload.update(verdict="reject", reason="incorrect", summary="Pinned evidence identifies a defective assignment input.",
                           rejection={"origin": origin, "strategy": "repair_contract_same_profile" if origin != "worker_output" else "escalate"})
            payload["checks"][0]["satisfied"] = False
        return payload

    def revised(self, request):
        value = copy.deepcopy(request)
        value.update(request_revision=request["request_revision"] + 1, previous_request_hash=digest(request))
        value["instruction"] += " Use the supplied public API contract exactly."
        return value

    def test_root_pending_is_candidate_ready_but_accept_still_needs_all_true(self):
        request = request_v2()
        result = self.dispatch(request)
        self.assertEqual(result["assignment"]["validation_errors"], [])
        self.assertEqual(read_json(Path(result["assignment"]["result"]))["coverage"][1]["satisfied"], None)
        payload = self.assessment(result)
        payload["checks"][1]["satisfied"] = False
        with self.assertRaisesRegex(LoopError, "unmet"):
            self.worker.assess(payload)
        payload["checks"][1]["satisfied"] = True
        self.assertTrue(self.worker.assess(payload)["passed"])

    def test_worker_cannot_attest_root_receipt_or_claim_done_with_worker_failure(self):
        for name, index, satisfied in (("false-root", 1, True), ("false-worker", 0, False)):
            request = request_v2(name)
            request["criteria"][0]["description"] += " Distinct ownership validation scenario: " + name
            value = worker_result(request); value["coverage"][index]["satisfied"] = satisfied
            result = self.dispatch(request, value)
            self.assertTrue(result["assignment"]["validation_errors"])

    def test_earlier_attempt_pins_block_next_revision_without_calls_or_budget_changes(self):
        request = request_v2('historical-immutable')
        first = self.dispatch(request)
        self.worker.assess(self.assessment(first, 'assignment_input'))
        original = self.kb.get('delegation', first['assignment']['id'])
        raw = Path(original['directory']) / 'retained-raw.txt'; raw.write_text('Harness-authored raw execution evidence')
        original['raw_result'] = {'ref': str(raw), 'sha256': file_hash(raw)}
        self.worker.save_attempt(original)
        second_request = self.revised(request)
        second = self.dispatch(second_request)
        self.assertEqual(second['assignment']['status'], 'candidate', second)
        self.worker.assess(self.assessment(second, 'assignment_input'))
        third_request = self.revised(second_request)
        record_before = self.kb.get('delegation', second['assignment']['id'])
        budget_before = self.kb.get('worker-budget', self.task_id)
        files = [Path(original['result']), Path(original['assessment_ref']),
                 Path(original['directory']) / 'dispatch.json', Path(original['directory']) / 'attempt.json', raw]
        for path in files:
            with self.subTest(artifact=path.name):
                previous = path.read_bytes(); path.write_text('{}')
                try:
                    with patch('loop_work.providers.structured_call', side_effect=AssertionError('Historical tamper must not call')):
                        with self.assertRaises(LoopError):
                            self.worker.run(third_request)
                    self.assertEqual(self.kb.get('delegation', second['assignment']['id']), record_before)
                    self.assertEqual(self.kb.get('worker-budget', self.task_id), budget_before)
                finally:
                    path.write_bytes(previous)
        # Valid history still authorizes the legitimate linked input repair.
        third = self.dispatch(third_request)
        self.assertEqual(third['assignment']['attempts'], 3)

    def test_prerequisite_all_retained_pins_precede_consumer_calls(self):
        producer_request = request_v2('pinned-producer')
        first = self.dispatch(producer_request)
        self.worker.assess(self.assessment(first, 'assignment_input'))
        original = self.kb.get('delegation', first['assignment']['id'])
        raw = Path(original['directory']) / 'raw-evidence.txt'; raw.write_text('Original raw evidence')
        original['raw_result'] = {'ref': str(raw), 'sha256': file_hash(raw)}
        self.worker.save_attempt(original)
        producer_request = self.revised(producer_request)
        second = self.dispatch(producer_request)
        self.worker.assess(self.assessment(second))
        producer = self.kb.get('delegation', second['assignment']['id'])
        consumer = request_v2('consumer-of-pinned-producer')
        consumer.update(read_paths=['check.py'], depends_on=[producer_request['id']])
        consumer['criteria'][0]['description'] = 'Explain the independently verifiable consumer assertion.'
        consumer['deliverables'][0]['description'] = 'Consumer behavior and producer handoff evidence.'
        budget = self.kb.get('worker-budget', self.task_id)
        artifacts = [Path(producer['directory']) / 'dispatch.json', Path(producer['directory']) / 'attempt.json',
                     Path(original['result']), Path(original['assessment_ref']),
                     Path(original['directory']) / 'dispatch.json', Path(original['directory']) / 'attempt.json', raw]
        for path in artifacts:
            with self.subTest(artifact=str(path)):
                content = path.read_bytes(); path.write_text('{}')
                try:
                    with patch('loop_work.providers.structured_call', side_effect=AssertionError('Invalid prerequisite must not call')):
                        with self.assertRaises(LoopError):
                            self.worker.run(consumer)
                    self.assertEqual(self.kb.get('worker-budget', self.task_id), budget)
                    self.assertEqual(self.kb.get('delegation', producer['id']), producer)
                    key = 'delegate-' + digest([self.task_id, consumer['id']])[:24]
                    self.assertIsNone(self.kb.get('delegation', key, required=False))
                finally:
                    path.write_bytes(content)
        self.assertEqual(self.dispatch(consumer)['assignment']['attempts'], 1)

    def test_earlier_attempt_tamper_blocks_current_completed_reuse(self):
        request = request_v2('historical-reuse')
        first = self.dispatch(request)
        self.worker.assess(self.assessment(first, 'assignment_input'))
        old = self.kb.get('delegation', first['assignment']['id'])
        revised = self.revised(request)
        second = self.dispatch(revised)
        self.worker.assess(self.assessment(second))
        budget = self.kb.get('worker-budget', self.task_id)
        Path(old['result']).write_text('{}')
        with patch('loop_work.providers.structured_call', side_effect=AssertionError('Reuse must not call')):
            with self.assertRaises(LoopError):
                self.worker.run(revised)
        self.assertEqual(self.kb.get('worker-budget', self.task_id), budget)

    def test_input_repairs_retain_profile_attempts_history_and_cap(self):
        request = request_v2()
        original_profile = None
        for attempt in range(1, 4):
            result = self.dispatch(request)
            self.assertEqual(result["assignment"]["attempts"], attempt)
            profile = result["assignment"]["profile"]
            original_profile = original_profile or profile
            self.assertEqual(profile, original_profile)
            rejected = self.worker.assess(self.assessment(result, "assignment_input"))
            self.assertEqual(rejected["assignment"]["rejection_origin"], "assignment_input")
            request = self.revised(request)
        with patch("loop_work.providers.structured_call", side_effect=AssertionError("cap must not call")):
            with self.assertRaisesRegex(LoopError, "budget exhausted"):
                self.worker.run(request)
        record = self.kb.get("delegation", result["assignment"]["id"])
        self.assertEqual(len(record["history"]), 2)
        self.assertEqual([item["request"]["request_revision"] for item in record["history"]], [1, 2])
        self.assertEqual(self.kb.get("worker-budget", self.task_id)["calls"], 3)
        self.assertEqual(record["request_revision"], 3)

    def test_fresh_worker_quality_rejection_escalates_and_cannot_revise_input(self):
        request = request_v2()
        first = self.dispatch(request)
        self.worker.assess(self.assessment(first, "worker_output"))
        with self.assertRaisesRegex(LoopError, "Only an assessed input"):
            self.worker.run(self.revised(request))
        second = self.dispatch(request)
        self.assertGreater(second["assignment"]["profile"]["capability_rank"], first["assignment"]["profile"]["capability_rank"])

    def test_lineage_hash_owner_and_origin_strategy_guards(self):
        request = request_v2()
        first = self.dispatch(request)
        payload = self.assessment(first, "assignment_input")
        payload["rejection"]["strategy"] = "escalate"
        with self.assertRaisesRegex(LoopError, "combination"):
            self.worker.assess(payload)
        self.worker.assess(self.assessment(first, "orchestrator_fixture"))
        bad = self.revised(request); bad["previous_request_hash"] = "0" * 64
        with self.assertRaisesRegex(LoopError, "immediately previous"):
            self.worker.run(bad)
        bad = self.revised(request); bad["id"] = "renamed"
        with self.assertRaisesRegex(LoopError, "stable work_unit_id"):
            self.worker.run(bad)
        bad = request_v2("wrong-owner"); bad["criteria"][1]["execution_owner"] = "worker"
        with self.assertRaisesRegex(LoopError, "exclusively"):
            self.worker.run(bad)

    def test_v2_patch_is_pinned_and_applied_after_full_assessment(self):
        self.running()
        request = request_v2("patch-unit", "implementation", ["value.py"])
        original = (self.root / "value.py").read_bytes()
        position = original.index(b"1")
        changed = original[:position] + b"2" + original[position + 1:]
        import hashlib
        pin = digest({"content": hashlib.sha256(changed).hexdigest(), "executable": bool((self.root / "value.py").stat().st_mode & 0o111)})
        change = {"path": "value.py", "operation": "patch", "base_hash": file_hash(self.root / "value.py"),
                  "result_hash": pin, "edits": [{"start": position, "end": position + 1, "content": "2"}]}
        result = self.dispatch(request, worker_result(request, [change]))
        self.assertEqual((self.root / "value.py").read_bytes(), original)
        self.assertEqual(result["assignment"]["validation_errors"], [])
        self.assertTrue(self.worker.assess(self.assessment(result))["passed"])
        self.assertEqual((self.root / "value.py").read_bytes(), changed)

    def test_three_revisions_keep_exact_corrections_and_explicit_supersession(self):
        request = request_v2("ledger-unit")
        original = {"id": "api-correction", "criterion_id": "C1", "origin": "assignment_input",
                    "expected": "exact-public-api.py; digest " + "a" * 64, "observed": "Missing API scope in the original assignment.",
                    "source_ref": "supplied typed setup facts", "source_hash": "b" * 64,
                    "validation_owner": "orchestrator", "resolution_status": "unresolved", "supersedes": []}
        request["correction_ledger"] = [original]
        for revision in range(1, 4):
            result = self.dispatch(request)
            packet = self.kb.get("delegation", result["assignment"]["id"])["request"]
            self.assertEqual(packet["correction_ledger"][0], original)
            if revision == 3:
                self.assertTrue(self.worker.assess(self.assessment(result))["passed"])
                break
            self.worker.assess(self.assessment(result, "assignment_input"))
            next_request = self.revised(request)
            if revision == 1:
                next_request["correction_ledger"].append({**original, "id": "api-resolved",
                    "observed": "The exact typed API and digest are now supplied.", "resolution_status": "resolved",
                    "supersedes": ["api-correction"]})
            removed = copy.deepcopy(next_request); removed["correction_ledger"] = []
            with self.assertRaises(LoopError):
                self.worker.run(removed)
            mutated = copy.deepcopy(next_request); mutated["correction_ledger"][0]["expected"] = "shortened"
            with self.assertRaisesRegex(LoopError, "exact append-only prefix"):
                self.worker.run(mutated)
            request = next_request

    def test_read_only_worker_cannot_own_compile_and_v1_rejects_v2_fields(self):
        for kind in ("analysis", "planning", "writing", "implementation"):
            request = request_v2("invalid-compile-" + kind, kind)
            request["criteria"][0]["verification_mode"] = "candidate_test"
            with self.subTest(kind=kind), patch("loop_work.providers.structured_call", side_effect=AssertionError("must not call")):
                with self.assertRaisesRegex(LoopError, "cannot own candidate execution"):
                    self.worker.run(request)
        legacy = assignment("legacy-unknown-field"); legacy["work_unit_id"] = "legacy-unknown-field"
        with self.assertRaisesRegex(LoopError, "exactly"):
            self.worker.run(legacy)

    def test_bad_patch_result_pin_never_writes(self):
        self.running()
        request = request_v2("bad-patch", "implementation", ["value.py"])
        original = (self.root / "value.py").read_bytes()
        change = {"path": "value.py", "operation": "patch", "base_hash": file_hash(self.root / "value.py"),
                  "result_hash": "0" * 64, "edits": [{"start": 0, "end": 0, "content": "# prefix\n"}]}
        result = self.dispatch(request, worker_result(request, [change]))
        self.assertTrue(result["assignment"]["validation_errors"])
        self.assertEqual((self.root / "value.py").read_bytes(), original)

    def test_patch_against_dispatch_absent_base_is_assessable_worker_output(self):
        self.running()
        request = request_v2("absent-patch", "implementation", ["new-module.py"])
        change = {"path": "new-module.py", "operation": "patch", "base_hash": "deleted",
                  "result_hash": "0" * 64, "edits": [{"start": 0, "end": 0, "content": "VALUE = 1\n"}]}
        result = self.dispatch(request, worker_result(request, [change]))
        self.assertEqual(result["assignment"]["status"], "candidate")
        self.assertTrue(result["assignment"]["candidate_id"])
        self.assertIn("dispatch-pinned base", result["assignment"]["validation_errors"][0])
        path = Path(result["assignment"]["result"])
        refs = [{"ref": str(path), "sha256": file_hash(path)}]
        payload = {"schema_version": 2, "assignment_id": request["id"],
                   "candidate_id": result["assignment"]["candidate_id"], "result_digest": result["assignment"]["result_digest"],
                   "verdict": "reject", "reason": "invalid_result", "summary": "A patch cannot edit a nonexistent dispatch base.",
                   "rejection": {"origin": "worker_output", "strategy": "escalate"},
                   "checks": [{"scope": scope, "criterion_id": key, "satisfied": False, "evidence": refs}
                              for scope, key in [("assignment", "C1"), ("assignment", "root-proof"), ("goal", "A1")]]}
        rejected = self.worker.assess(payload)
        self.assertEqual(rejected["assignment"]["status"], "rejected")
        self.assertEqual(rejected["assignment"]["rejection_origin"], "worker_output")
        self.assertFalse((self.root / "new-module.py").exists())

    def test_existing_patch_base_disappearing_is_source_failure_not_worker_candidate(self):
        self.running()
        request = request_v2("vanished-patch", "implementation", ["value.py"])
        change = {"path": "value.py", "operation": "patch", "base_hash": file_hash(self.root / "value.py"),
                  "result_hash": "0" * 64, "edits": [{"start": 0, "end": 0, "content": "# prefix\n"}]}
        def disappear(*args, **kwargs):
            (self.root / "value.py").unlink()
            return worker_result(request, [change])
        with patch("loop_work.providers.structured_call", side_effect=disappear):
            result = self.worker.run(request)
        self.assertEqual(result["assignment"]["status"], "blocked")
        self.assertNotIn("candidate_id", result["assignment"])
        self.assertFalse(result["assignment"]["retry"]["can_escalate"])

    def test_v2_team_revision_is_explicitly_unsupported_before_calls(self):
        from loop_work.team import Team
        request = request_v2("team-unit")
        request.update(request_revision=2, previous_request_hash="a" * 64)
        other = request_v2("other-team-unit")
        with patch("loop_work.providers.structured_call", side_effect=AssertionError("must not call")):
            with self.assertRaisesRegex(LoopError, "revision 1 only"):
                Team(self.kb, self.task_id, self.root).run({"id": "fixed-team", "max_turns": 3,
                    "members": [{"assignment": request}, {"assignment": other}]})

    def test_v2_team_revision_one_transports_pending_ownership_and_assesses(self):
        from loop_work.team import Team
        first, second = request_v2("team-source"), request_v2("team-consumer")
        first["read_paths"], second["read_paths"] = ["value.py"], ["value.py", "check.py"]
        second["deliverables"][0]["description"] = "Trace the separately observable consumer assertion."
        plan = {"id": "v2-team", "max_turns": 4, "members": [{"assignment": first}, {"assignment": second}]}
        team = Team(self.kb, self.task_id, self.root)
        def result_for_call(*args, **kwargs):
            packet = json.loads(args[3].split("WORKER DATA:\n", 1)[1])
            return {**worker_result(packet["assignment"]), "messages": []}
        with patch("loop_work.providers.structured_call", side_effect=result_for_call):
            result = team.run(plan)
            for _ in range(2):
                self.assertEqual(result["status"], "awaiting_assessment", result)
                ledger = team.load(plan["id"])
                record = team.assignment(ledger["inflight"]["member"])
                candidate = team.worker.response(record)
                self.assertEqual(candidate["assignment"]["validation_errors"], [])
                self.assertTrue(team.worker.assess(self.assessment(candidate))["passed"])
                result = team.run(plan)
        self.assertEqual(result["status"], "done", result)

    def test_invalid_worker_result_cannot_be_reclassified_as_provider_failure(self):
        request = request_v2("invalid-origin")
        value = worker_result(request); value["coverage"][0]["satisfied"] = False
        result = self.dispatch(request, value)
        record = self.kb.get("delegation", result["assignment"]["id"])
        evidence = [{"ref": str(Path(result["assignment"]["result"])),
                     "sha256": file_hash(Path(result["assignment"]["result"]))}]
        payload = {"schema_version": 2, "assignment_id": request["id"],
                   "candidate_id": result["assignment"]["candidate_id"], "result_digest": result["assignment"]["result_digest"],
                   "verdict": "reject", "reason": "invalid_result", "summary": "The worker claimed done with a false owned criterion.",
                   "checks": [{"scope": scope, "criterion_id": key, "satisfied": False, "evidence": evidence}
                              for scope, key in [("assignment", "C1"), ("assignment", "root-proof"), ("goal", "A1")]]}
        for origin, strategy in (("provider_execution", "retry_same_profile"), ("evidence_staleness", "retry_same_profile"),
                                 ("assignment_input", "repair_contract_same_profile")):
            with self.subTest(origin=origin):
                payload["rejection"] = {"origin": origin, "strategy": strategy}
                with self.assertRaises(LoopError):
                    self.worker.assess(payload)
                self.assertEqual(self.kb.get("delegation", result["assignment"]["id"]), record)
        payload["rejection"] = {"origin": "worker_output", "strategy": "escalate"}
        rejected = self.worker.assess(payload)
        next_result = self.dispatch(request)
        self.assertGreater(next_result["assignment"]["profile"]["capability_rank"], rejected["assignment"]["profile"]["capability_rank"])

    def test_renaming_both_unit_and_assignment_cannot_reset_exact_contribution_cap(self):
        request = request_v2("capped-unit")
        original = copy.deepcopy(request)
        for _ in range(3):
            result = self.dispatch(request)
            self.worker.assess(self.assessment(result, "assignment_input"))
            request = self.revised(request)
            request["read_paths"] = ["value.py"]
        renamed = copy.deepcopy(original)
        renamed.update(id="renamed-unit", work_unit_id="renamed-unit")
        before_calls = self.kb.get("worker-budget", self.task_id)["calls"]
        with patch("loop_work.providers.structured_call", side_effect=AssertionError("must not call")):
            with self.assertRaisesRegex(LoopError, "Exact contribution already belongs"):
                self.worker.run(renamed)
        self.assertEqual(self.kb.get("worker-budget", self.task_id)["calls"], before_calls)

    def test_contract_repair_preserves_demand_and_prohibitions(self):
        request = request_v2("high-risk-input")
        request["planning"].update(complexity="high", risk="high", uncertainty="high", evidence=["value.py:1"])
        first = self.dispatch(request)
        self.worker.assess(self.assessment(first, "assignment_input"))
        for dimension in ("complexity", "risk", "uncertainty"):
            with self.subTest(dimension=dimension):
                revised = self.revised(request); revised["planning"][dimension] = "low"
                with self.assertRaisesRegex(LoopError, "cannot lower"):
                    self.worker.run(revised)
        revised = self.revised(request); revised["prohibited"] = ["Do not publish."]
        with self.assertRaisesRegex(LoopError, "original prohibitions"):
            self.worker.run(revised)
        revised = self.revised(request); revised["criteria"][0]["description"] = "Any output is sufficient."
        with self.assertRaisesRegex(LoopError, "criterion descriptions"):
            self.worker.run(revised)
        revised = self.revised(request); revised["prohibited"].append("Do not change unrelated tests.")
        second = self.dispatch(revised)
        self.assertEqual(second["assignment"]["profile"], first["assignment"]["profile"])

    def test_higher_demand_repair_blocks_when_retained_profile_is_ineligible(self):
        from loop_work.delegation import dispatch_preflight
        request = request_v2("raised-demand")
        first = self.dispatch(request)
        self.worker.assess(self.assessment(first, "assignment_input"))
        original_record = copy.deepcopy(self.kb.get("delegation", first["assignment"]["id"]))
        calls = self.kb.get("worker-budget", self.task_id)["calls"]
        for key in ("complexity", "risk", "uncertainty"):
            with self.subTest(key=key):
                revised = self.revised(request)
                revised["planning"].update({key: "high", "evidence": ["value.py:1"]})
                with patch("loop_work.providers.structured_call", side_effect=AssertionError("must not call")):
                    checked = dispatch_preflight(self.kb, self.task_id, revised, self.root)
                    self.assertFalse(checked["passed"])
                    self.assertIn("does not meet revised demand", checked["diagnostics"][0]["message"])
                    with self.assertRaisesRegex(LoopError, "does not meet revised demand"):
                        self.worker.run(revised)
                self.assertEqual(self.kb.get("worker-budget", self.task_id)["calls"], calls)
                self.assertEqual(self.kb.get("delegation", first["assignment"]["id"]), original_record)

    def test_stale_rejection_at_ceiling_reports_recovery_and_retains_profile(self):
        request = request_v2("ceiling-recovery")
        request["planning"].update(complexity="high", evidence=["value.py:1"])
        first = self.dispatch(request)
        rejected = self.worker.assess(self.assessment(first, "worker_output"))
        previous = self.kb.get("delegation", first["assignment"]["id"])
        attempt_path = Path(previous["directory"]) / "attempt.json"
        prior_attempt_bytes = attempt_path.read_bytes()
        self.assertFalse(rejected["assignment"]["retry"]["can_escalate"])
        (self.root / "value.py").write_text("VALUE = 2\n")
        record = self.kb.get("delegation", first["assignment"]["id"])
        response = self.worker.response(record)
        self.assertTrue(response["assignment"]["retry"]["requires_recovery"])
        self.assertTrue(response["assignment"]["retry"]["can_retry_same_profile"])
        self.assertFalse(response["assignment"]["retry"]["can_escalate"])
        self.assertIn("--recover", response["next"])
        with patch("loop_work.providers.structured_call", return_value=worker_result(request)):
            recovered = self.worker.run(request, "Inspected source change and retained rejected candidate")
        self.assertEqual(recovered["assignment"]["profile"], first["assignment"]["profile"])
        self.assertEqual(attempt_path.read_bytes(), prior_attempt_bytes)
        current = self.kb.get("delegation", first["assignment"]["id"])
        self.assertEqual(current["history"][-1]["status"], "rejected")
        self.assertEqual(current["history"][-1]["error"], previous["error"])
        self.assertEqual(current["history"][-1]["attempt_file_hash"], file_hash(attempt_path))
        self.assertEqual(current["recovery"]["previous_attempt_hash"], file_hash(attempt_path))
        self.assertEqual(current["recovery"]["previous_status"], "rejected")
        self.assertFalse(current["escalated"])

    def test_tampered_rejection_pin_is_not_recovery_authority(self):
        request = request_v2("tampered-rejection")
        result = self.dispatch(request)
        self.worker.assess(self.assessment(result, "worker_output"))
        Path(result["assignment"]["result"]).write_text("changed invalid result artifact\n")
        record = self.kb.get("delegation", result["assignment"]["id"])
        response = self.worker.response(record)
        self.assertFalse(response["assignment"]["retry"]["can_retry_same_profile"])
        self.assertFalse(response["assignment"]["retry"]["can_escalate"])
        self.assertFalse(response["assignment"]["retry"]["requires_recovery"])
