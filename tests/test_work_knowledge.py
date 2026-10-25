from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from loop_work.knowledge import KnowledgeBase
from loop_work.storage import LoopError, digest, file_hash
from loop_work.work import Work
from scripts.install import install
from support import use_fake_routing


class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        use_fake_routing(self, self.base)
        self.root = self.base / "docs"
        self.root.mkdir()
        (self.root / "guide.md").write_text("The cache stores file dependencies.\n")
        self.kb = KnowledgeBase(self.base / "knowledge")
        self.location = self.kb.attach(self.root)
        self.locations = [self.location]
        self.work = Work(self.kb)

    def entry(self, **overrides):
        return {"id": "docs-cache", "scope": "project", "kind": "fact", "status": "confirmed",
                "summary": "The cache records file dependencies.", "evidence": ["guide.md:1"],
                "paths": ["guide.md"], **overrides}

    def remember(self, entry=None, locations=None, **kwargs):
        locations = locations or self.locations
        return self.kb.remember(entry or self.entry(), locations, digest(self.kb.observe(locations)), **kwargs)

    def open_task(self, kind="explanation", paths=None, session=None):
        return self.work.open(kind, "Explain cached knowledge", "codex", paths or [self.root], session)["task"]

    def goal(self, **overrides):
        return {"outcome": "Explain how stored analysis is reused.", "deliverable": "An inline explanation with source references.",
                "criteria": [{"id": "C1", "description": "Describe the dependency check with a source reference."}],
                "decisions": [], "open_questions": [], **overrides}

    def result(self, **overrides):
        return {"summary": "The explanation identifies dependency checks and when reinspection is needed.",
                "outputs": ["conversation:answer-cache"], "checks": [{"criterion_id": "C1", "satisfied": True,
                "evidence": "guide.md:1 is cited in the delivered answer."}], "knowledge": [], **overrides}

    def started(self, kind="explanation"):
        task = self.open_task(kind)
        self.work.define(task["id"], self.goal())
        return self.work.start(task["id"])["task"]

    def test_topic_title_is_presentation_only_and_searchable_without_promoting_evidence(self):
        original = self.entry(title="메모 저장 설계", status="hypothesis", evidence=[])
        saved = self.remember(original)
        self.assertEqual(saved["title"], "메모 저장 설계")
        self.assertEqual(saved["summary"], original["summary"])
        self.assertEqual(saved["status"], "hypothesis")
        self.assertIsNone(saved["source_task_id"])
        context = self.kb.context(self.locations, query="메모 저장")
        self.assertEqual([x["id"] for x in context["unconfirmed"]], [saved["id"]])
        self.assertEqual(context["reusable"], [])
        before = {k: v for k, v in saved.items() if k != "title"}
        renamed = self.remember({**original, "title": "메모 저장의 검증 한계"})
        self.assertEqual({k: v for k, v in renamed.items() if k != "title"}, before)
        self.assertEqual(self.kb.history("topic", saved["id"]), [saved])
        for invalid in ("", "줄바꿈\n제목", "x" * 61, "TODO"):
            with self.subTest(title=invalid), self.assertRaises(LoopError):
                self.remember({**original, "title": invalid})
        self.assertEqual(self.kb.get("topic", saved["id"]), renamed)

    def test_title_add_change_and_remove_preserve_stale_evidence_and_all_provenance(self):
        subprocess.run(["git", "init", "-q", str(self.root)], check=True)
        subprocess.run(["git", "-C", str(self.root), "symbolic-ref", "HEAD", "refs/heads/original"], check=True)
        first = self.open_task()
        second = self.open_task()
        entry = self.entry()
        with patch("loop_work.knowledge.now", return_value="2020-01-01T00:00:00+00:00"), \
             patch("loop_work.knowledge.harness_digest", return_value="original-harness"):
            saved = self.remember(entry, session_id=first["session_id"], task_id=first["id"])
        (self.root / "guide.md").write_text("The source now contradicts the stored conclusion.\n")
        (self.root / "AGENTS.md").write_text("Changed source rules.\n")
        subprocess.run(["git", "-C", str(self.root), "symbolic-ref", "HEAD", "refs/heads/changed"], check=True)
        previous = saved
        for title in ("메모 저장 원리", "메모 근거의 한계", None):
            with self.subTest(title=title), \
                 patch("loop_work.knowledge.now", return_value="2030-01-01T00:00:00+00:00"), \
                 patch("loop_work.knowledge.harness_digest", return_value="changed-harness"):
                submitted = {**entry, **({"title": title} if title is not None else {})}
                renamed = self.remember(submitted, session_id=second["session_id"], task_id=second["id"])
                self.assertEqual({k: v for k, v in renamed.items() if k != "title"},
                                 {k: v for k, v in saved.items() if k != "title"})
                self.assertEqual(renamed.get("title"), title)
                self.assertEqual("title" in renamed, title is not None)
                self.assertEqual(self.kb.history("topic", saved["id"])[-1], previous)
                context = self.kb.context(self.locations)
                self.assertEqual(context["reusable"], [])
                self.assertEqual([x["id"] for x in context["stale"]], [saved["id"]])
                self.assertIn("changed: guide.md", context["stale"][0]["stale_reasons"])
                self.assertIn("rules_or_branch_changed", context["stale"][0]["stale_reasons"])
                self.assertEqual(self.kb.get("topic", saved["id"]), renamed)
                previous = renamed
        self.assertEqual(len(self.kb.history("topic", saved["id"])), 3)

    def test_title_with_semantic_change_still_records_current_evidence_and_provenance(self):
        first = self.open_task()
        second = self.open_task()
        updates = ({"summary": "The changed guide describes a different cache."},
                   {"evidence": ["guide.md:changed"]}, {"status": "draft"}, {"paths": ["."]})
        for index, semantic in enumerate(updates):
            with self.subTest(semantic=semantic):
                entry = self.entry(id="semantic-" + str(index), title="원래 메모")
                with patch("loop_work.knowledge.now", return_value="2020-01-01T00:00:00+00:00"), \
                     patch("loop_work.knowledge.harness_digest", return_value="original-harness"):
                    saved = self.remember(entry, session_id=first["session_id"], task_id=first["id"])
                (self.root / "guide.md").write_text("Changed evidence for semantic update " + str(index))
                with patch("loop_work.knowledge.now", return_value="2030-01-01T00:00:00+00:00"), \
                     patch("loop_work.knowledge.harness_digest", return_value="changed-harness"):
                    updated = self.remember({**entry, **semantic, "title": "수정한 메모"},
                                            session_id=second["session_id"], task_id=second["id"])
                    current = self.kb.observe(self.locations)[self.location["id"]]
                    self.assertEqual(updated["fingerprints"],
                                     {p: self.kb.fingerprint(current, p) for p in updated["paths"]})
                    self.assertEqual(updated["harness"], "changed-harness")
                    self.assertEqual(updated["recorded_at"], "2030-01-01T00:00:00+00:00")
                    self.assertEqual(updated["source_task_id"], second["id"])
                    self.assertEqual(updated["source_session_id"], second["session_id"])
                    for key, value in semantic.items():
                        self.assertEqual(updated[key], value)
                    self.assertNotEqual(updated["fingerprints"], saved["fingerprints"])
                    self.assertEqual(self.kb.history("topic", saved["id"]), [saved])

    def test_title_only_remember_preserves_additional_stored_metadata(self):
        entry = self.entry(title="원래 지식 제목")
        saved = self.remember(entry)
        extended = self.kb.put_topic({**saved, "custom_metadata": {
            "original_note": "Preserve additional source information.", "nested": [1, {"keep": True}]}})
        history = self.kb.history("topic", saved["id"])
        (self.root / "guide.md").write_text("The stored conclusion now needs new evidence.\n")
        renamed = self.remember({**entry, "title": "지식 근거의 한계"})
        self.assertEqual({k: v for k, v in renamed.items() if k != "title"},
                         {k: v for k, v in extended.items() if k != "title"})
        self.assertEqual(self.kb.get("topic", saved["id"]), renamed)
        self.assertEqual(self.kb.history("topic", saved["id"]), [*history, extended])
        context = self.kb.context(self.locations)
        self.assertEqual(context["reusable"], [])
        self.assertEqual([x["id"] for x in context["stale"]], [saved["id"]])
        self.assertEqual(json.loads((self.kb.home / "views/topic/docs-cache.json").read_text()), renamed)

    def test_freshness_updates_without_restamping_or_history_noise(self):
        saved = self.remember()
        doc = self.kb.home / "views/topic/docs-cache.md"
        before = doc.stat().st_mtime_ns
        self.assertEqual(self.remember(), saved)
        self.assertEqual(self.kb.history("topic", saved["id"]), [])
        self.assertEqual(doc.stat().st_mtime_ns, before)
        (self.root / "guide.md").write_text("Changed cache design.\n")
        context = self.kb.context(self.locations)
        self.assertEqual(context["reusable"], [])
        self.assertEqual(context["stale"][0]["stale_reasons"], ["changed: guide.md"])
        self.assertEqual(self.kb.get("topic", saved["id"])["recorded_at"], saved["recorded_at"])
        self.assertIn("changed: guide.md", Path(context["document"]).read_text())
        self.remember(self.entry(summary="The guide now describes a different cache design."))
        self.assertEqual(self.kb.history("topic", saved["id"]), [saved])

    def test_revision_check_rejects_changes_during_analysis(self):
        revision = self.kb.context(self.locations)["revision"]
        (self.root / "guide.md").write_text("Changed\n")
        with self.assertRaisesRegex(LoopError, "changed"):
            self.kb.remember(self.entry(), self.locations, revision)
        self.assertEqual(self.kb.list("topic"), [])

    def test_directory_fingerprints_track_additions_deletions_and_rules(self):
        self.remember(self.entry(paths=["."]))
        added = self.root / "more.md"
        added.write_text("new")
        self.assertTrue(self.kb.context(self.locations)["stale"])
        added.unlink()
        self.assertTrue(self.kb.context(self.locations)["reusable"])
        self.remember(self.entry(paths=["guide.md"]))
        (self.root / "AGENTS.md").write_text("New rules\n")
        self.assertIn("rules_or_branch_changed", self.kb.context(self.locations)["stale"][0]["stale_reasons"])

    def test_drafts_hypotheses_and_expiry_are_not_current_facts(self):
        for status in ("draft", "hypothesis", "superseded"):
            self.remember(self.entry(id=status, status=status, evidence=[]))
        self.remember(self.entry(id="expired", expires_at="2001-01-01T00:00:00+00:00"))
        context = self.kb.context(self.locations)
        self.assertEqual(context["reusable"], [])
        self.assertEqual(len(context["unconfirmed"]), 3)
        self.assertEqual(context["stale"][0]["stale_reasons"], ["expired"])
        with self.assertRaisesRegex(LoopError, "evidence"):
            self.remember(self.entry(evidence=[]))

    def test_other_projects_are_not_reusable_or_injected_as_summaries(self):
        self.remember()
        other = self.base / "other"
        other.mkdir()
        (other / "guide.md").write_text("Different project")
        context = self.kb.context([self.kb.attach(other)])
        self.assertEqual(context["reusable"], [])
        self.assertEqual(context["counts"]["other_contexts"], 1)
        self.assertNotIn("summary", context["other_contexts"][0])
        with self.assertRaisesRegex(LoopError, "owner"):
            self.remember(locations=[self.kb.attach(other)])

    def test_global_preference_retains_scope_and_can_be_updated_from_another_project(self):
        preference = self.entry(id="writing-language", scope="global", kind="decision", paths=[],
                                summary="Use Korean for user-facing explanations.", basis="user",
                                applies_to="Explanations in every project", evidence=["conversation:user-preference"])
        self.remember(preference)
        other = self.base / "another"
        other.mkdir()
        locations = [self.kb.attach(other)]
        self.assertEqual(self.kb.context(locations)["reusable"][0]["id"], preference["id"])
        self.remember(preference, locations)
        self.assertEqual(self.kb.history("topic", preference["id"]), [])
        self.remember({**preference, "summary": "Use Korean and preserve technical identifiers."}, locations)
        self.assertEqual(len(self.kb.history("topic", preference["id"])), 1)
        with self.assertRaisesRegex(LoopError, "scope/owner"):
            self.remember({**preference, "scope": "project"}, locations)

    def test_session_and_task_answers_do_not_widen_to_a_new_request(self):
        first = self.open_task()
        self.remember(self.entry(scope="task", kind="decision", paths=[], basis="user", applies_to="This explanation"),
                      session_id=first["session_id"], task_id=first["id"])
        second = self.open_task(session=first["session_id"])
        self.assertEqual(self.kb.context(self.locations, second["session_id"], second["id"])["reusable"], [])
        self.assertTrue(self.kb.context(self.locations, first["session_id"], first["id"])["reusable"])
        with self.assertRaisesRegex(LoopError, "one provider"):
            self.kb.session("claude", first["session_id"])

    def test_renamed_directory_keeps_knowledge_and_task_links(self):
        task = self.open_task()
        self.remember()
        moved = self.base / "renamed"
        self.root.rename(moved)
        location = self.kb.attach(moved)
        self.assertEqual(location["id"], self.location["id"])
        context = self.work.context(task["id"])
        self.assertEqual(context["knowledge"]["locations"][0]["root"], str(moved.resolve()))
        self.assertTrue(context["knowledge"]["reusable"])

    def test_remote_identity_groups_clones_but_checks_every_working_tree(self):
        locations = []
        for name, remote in (("one", "https://user:secret@github.com/team/repo.git"),
                             ("two", "git@github.com:team/repo.git")):
            root = self.base / name
            root.mkdir()
            subprocess.run(["git", "init", "-q", str(root)], check=True)
            subprocess.run(["git", "-C", str(root), "remote", "add", "origin", remote], check=True)
            (root / "guide.md").write_text("Same content")
            locations.append(self.kb.attach(root))
        self.assertNotEqual(locations[0]["id"], locations[1]["id"])
        self.assertEqual(locations[0]["project_id"], locations[1]["project_id"])
        self.assertNotIn("secret", json.dumps(self.kb.list("project")))
        self.remember(locations=locations[:1])
        self.assertTrue(self.kb.context(locations[1:])["reusable"])
        (Path(locations[1]["root"]) / "guide.md").write_text("Different implementation")
        self.assertEqual(self.kb.context(locations)["reusable"], [])
        self.assertTrue(self.kb.context(locations)["stale"])

    def test_non_git_copy_can_be_explicitly_attached_to_existing_project(self):
        other = self.base / "copy"
        other.mkdir()
        attached = self.kb.attach(other, self.location["project_id"])
        self.assertEqual(attached["project_id"], self.location["project_id"])
        self.assertNotEqual(attached["id"], self.location["id"])

    def test_context_is_paged_without_losing_records(self):
        for index in range(7):
            self.remember(self.entry(id=f"topic-{index}"))
        first = self.kb.context(self.locations, limit=3)
        second = self.kb.context(self.locations, limit=3, offset=3)
        self.assertEqual(first["counts"]["reusable"], 7)
        self.assertEqual(len(first["reusable"]), 3)
        self.assertFalse({x["id"] for x in first["reusable"]} & {x["id"] for x in second["reusable"]})
        self.assertEqual(len(self.kb.list("topic")), 7)
        self.assertEqual(self.kb.context(self.locations, query="topic-6")["counts"]["reusable"], 1)
        self.assertIn("Nothing is deleted", Path(first["document"]).read_text())

    def test_finish_checks_all_retained_pins_before_completion_or_knowledge_promotion(self):
        from loop_work.delegation import Delegation
        from loop_work.human import HumanDesk
        from loop_work.storage import read_json
        from support import fixture_assessment
        from test_delegation import assignment
        for human in (False, True):
            with self.subTest(substantive_human=human):
                task = self.started()
                if human:
                    desk = HumanDesk(self.kb)
                    asked = desk.create(task["id"], {"id": "finish-choice-" + str(human), "kind": "decision", "title": "Confirm format",
                        "question": "Keep this format?", "options": [], "action": None})
                    desk.respond(asked["id"], {"decision": "answer", "text": "Keep the current goal and format."}, 1)
                request = assignment("finished-unit", goal_criteria=("C1",))
                request["read_paths"] = ["guide.md"]
                value = {"status": "done", "summary": "The guide describes cached dependency behavior.",
                    "outputs": [{"id": row["id"], "content": "The guide records dependencies.", "evidence": ["guide.md:1"]}
                                for row in request["deliverables"]],
                    "coverage": [{"criterion_id": row["id"], "satisfied": True, "evidence": "guide.md:1"} for row in request["criteria"]],
                    "changes": [], "findings": [], "blockers": []}
                worker = Delegation(self.kb, task["id"], self.root)
                with patch("loop_work.providers.executable_for", return_value="test-provider"), patch("loop_work.providers.structured_call", return_value=value):
                    first = worker.run(request)
                    rejected = fixture_assessment(self.kb, first)
                    rejected.update(verdict="reject", reason="incorrect", summary="The explanation needs a corrected source interpretation.")
                    rejected["checks"][0]["satisfied"] = False
                    worker.assess(rejected)
                    second = worker.run(request)
                    worker.assess(fixture_assessment(self.kb, second))
                record = self.kb.get("delegation", second["assignment"]["id"])
                targets = [Path(record["assessment_ref"]), Path(record["directory"]) / "dispatch.json",
                           Path(record["history"][0]["assessment_ref"])]
                task_before = copy.deepcopy(self.kb.get("task", task["id"]))
                budget = self.kb.get("worker-budget", task["id"])
                for target in targets:
                    with self.subTest(pin=target.name):
                        original = target.read_bytes()
                        # Whitespace changes preserve JSON meaning but break its immutable artifact pin.
                        target.write_bytes(original + b" ")
                        if target.name == "dispatch.json":
                            dispatch = read_json(target)
                            dispatch["before"]["digest"] = "tampered"
                            target.write_text(json.dumps(dispatch))
                        revision = digest(self.kb.observe(self.locations))
                        result = self.result(knowledge=[self.entry(id="must-not-promote-" + str(human))], observed_revision=revision)
                        with patch("loop_work.providers.structured_call", side_effect=AssertionError("must not call")):
                            with self.assertRaises(LoopError):
                                self.work.finish(task["id"], result)
                        self.assertEqual(self.kb.get("task", task["id"]), task_before)
                        self.assertEqual(self.kb.get("worker-budget", task["id"]), budget)
                        self.assertEqual(self.kb.list("topic"), [])
                        target.write_bytes(original)
                # The same real accepted artifacts remain usable when intact.
                self.assertTrue(self.work.finish(task["id"], self.result())["passed"])

    def test_non_development_kinds_complete_without_provider_calls_or_project_writes(self):
        original = {p.name: p.read_bytes() for p in self.root.iterdir()}
        with patch("loop_work.providers.review", side_effect=AssertionError("Unexpected review")), \
             patch("loop_work.providers.doctor", side_effect=AssertionError("Unexpected provider requirement")):
            for kind in ("document", "explanation", "research", "review", "planning"):
                with self.subTest(kind=kind):
                    task = self.started(kind)
                    completed = self.work.finish(task["id"], self.result())
                    self.assertTrue(completed["passed"])
                    self.assertEqual(completed["task"]["phase"], "completed")
                    self.assertNotIn("attempts", completed["task"])
        self.assertEqual({p.name: p.read_bytes() for p in self.root.iterdir()}, original)

    def test_questions_must_be_resolved_before_start_and_work_goal_is_fixed(self):
        task = self.open_task()
        self.work.define(task["id"], self.goal(open_questions=["Who is the audience?"]))
        with self.assertRaisesRegex(LoopError, "questions"):
            self.work.start(task["id"])
        self.work.define(task["id"], self.goal())
        self.work.start(task["id"])
        with self.assertRaisesRegex(LoopError, "fixed"):
            self.work.define(task["id"], self.goal(outcome="A weaker target"))

    def test_missing_or_failed_criterion_does_not_complete_work(self):
        task = self.started()
        with self.assertRaisesRegex(LoopError, "each completion criterion"):
            self.work.finish(task["id"], self.result(checks=[]))
        failed = self.result()
        failed["checks"][0]["satisfied"] = False
        self.assertFalse(self.work.finish(task["id"], failed)["passed"])
        self.assertEqual(self.work.load(task["id"])["phase"], "working")
        self.assertTrue(self.work.finish(task["id"], self.result())["passed"])

    def test_completion_and_knowledge_are_atomic_and_reused_by_next_work(self):
        task = self.started()
        revision = self.kb.context(self.locations)["revision"]
        result = self.result(knowledge=[self.entry()], observed_revision=revision)
        self.work.finish(task["id"], result)
        next_task = self.open_task(session=task["session_id"])
        self.assertTrue(self.work.context(next_task["id"])["knowledge"]["reusable"])
        (self.root / "guide.md").write_text("A later change\n")
        self.assertTrue(self.work.context(next_task["id"])["knowledge"]["stale"])
        self.assertTrue(self.work.load(task["id"])["result"]["historical"])
        task2 = self.started()
        revision = self.kb.context(self.locations)["revision"]
        with self.assertRaisesRegex(LoopError, "scope/owner"):
            self.work.finish(task2["id"], self.result(knowledge=[self.entry(id="another-fact"), self.entry(scope="global")], observed_revision=revision))
        self.assertIsNone(self.kb.get("topic", "another-fact", required=False))
        self.assertEqual(self.work.load(task2["id"])["phase"], "working")

    def test_block_resume_and_concurrent_update_preserve_state(self):
        task = self.started()
        stale = copy.deepcopy(task)
        evidence = self.base / "source-blocker.txt"
        evidence.write_text("The required source is unavailable.")
        payload = {"version": 1, "kind": "external", "reason": "A source is unavailable.",
                   "scope": "task", "retryable": True,
                   "evidence": [{"ref": str(evidence.resolve()), "sha256": file_hash(evidence)}]}
        self.work.stop(task["id"], payload)
        self.work.stop(task["id"], {**payload, "reason": "The source is still unavailable."})
        self.assertEqual(self.work.resume(task["id"])["task"]["phase"], "working")
        with self.assertRaisesRegex(LoopError, "concurrently"):
            self.work.save(stale)

    def test_multi_directory_task_uses_same_session_and_keeps_project_boundaries(self):
        first = self.open_task()
        other = self.base / "second"
        other.mkdir()
        task = self.open_task(paths=[self.root, other], session=first["session_id"])
        self.assertEqual(len(task["project_ids"]), 2)
        self.assertEqual(task["session_id"], first["session_id"])
        self.remember()
        self.assertTrue(self.work.context(task["id"])["knowledge"]["reusable"])

    def test_readable_records_reject_bloat_duplicates_and_placeholders(self):
        for fields in ({"summary": "x" * 281}, {"summary": "a\nb"}, {"summary": "TODO"}, {"summary": "Replace with actual findings"},
                       {"details": [self.entry()["summary"]]}, {"details": [str(i) for i in range(6)]},
                       {"evidence": ["guide.md:1", "guide.md:1"]}):
            with self.subTest(fields=fields), self.assertRaises(LoopError):
                self.remember(self.entry(**fields))
        self.assertEqual(self.kb.list("topic"), [])

    def test_document_is_derived_and_preserves_evidence_and_uncertainty(self):
        self.remember(self.entry(summary="A <script> label appears in the guide.", why="Readers need its literal meaning.",
                                 uncertainty="Runtime performance has not been measured.", details=["The guide names file dependencies."]))
        path = self.kb.home / "views/topic/docs-cache.md"
        content = path.read_text()
        self.assertIn("&lt;script&gt;", content)
        self.assertIn("Runtime performance has not been measured.", content)
        self.assertIn("guide.md:1", content)
        self.assertNotIn("Next", content)
        path.write_text("An unsupported manual claim")
        self.kb.document("topic", "docs-cache")
        self.assertEqual(path.read_text(), content)
        task = self.started()
        finished = self.work.finish(task["id"], self.result())
        self.assertNotIn("Next (agent)", Path(finished["document"]).read_text())

    def test_duplicate_notes_do_not_accumulate(self):
        task = self.started()
        for _ in range(2):
            self.work.note(task["id"], "The guide records file dependencies.", "guide.md:1")
        self.assertEqual(len(self.work.load(task["id"])["notes"]), 1)

    def test_installed_non_git_cli_lifecycle_and_generated_documents(self):
        install(self.root)
        script = self.root / ".loop/loop.py"
        def run(*args):
            result = subprocess.run([sys.executable, str(script), "--root", str(self.root), "--knowledge-home", str(self.kb.home), *args],
                                    check=True, capture_output=True, text=True)
            return json.loads(result.stdout)
        opened = run("work", "open", "--kind", "explanation", "--title", "Explain cache", "--provider", "claude")
        task_id = opened["task"]["id"]
        goal_path, result_path = self.base / "goal.json", self.base / "result.json"
        goal_path.write_text(json.dumps(self.goal()))
        result_path.write_text(json.dumps(self.result()))
        run("work", "goal", task_id, "--input", str(goal_path))
        run("work", "start", task_id)
        finished = run("work", "finish", task_id, "--input", str(result_path))
        self.assertTrue(finished["passed"])
        self.assertTrue(Path(finished["document"]).is_file())
        self.assertTrue(Path(run("knowledge", "get", "task", task_id)["document"]).is_file())


if __name__ == "__main__":
    unittest.main()
