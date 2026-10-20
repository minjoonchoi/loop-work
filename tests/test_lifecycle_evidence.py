from __future__ import annotations

import copy
from pathlib import Path
import tempfile
import unittest

from loop_work.blocking import validate_block
from loop_work.knowledge import KnowledgeBase
from loop_work.orchestration import Orchestration, worker_context
from loop_work.retirement import retire, is_retired
from loop_work.storage import LoopError, digest, file_hash, write_json
from loop_work.work import Work, completion_feedback
from support import use_fake_routing


class LifecycleEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        use_fake_routing(self, self.base)
        self.root = self.base / 'project'
        self.root.mkdir()
        (self.root / 'producer.txt').write_text('accepted producer\n')
        self.kb = KnowledgeBase(self.base / 'knowledge')
        self.work = Work(self.kb)
        self.task = self.work.open('document', 'Retain failed history and accepted replacement', 'codex', [self.root])['task']
        self.work.define(self.task['id'], {'outcome': 'Deliver a supported explanation.', 'deliverable': 'Explanation',
            'criteria': [{'id': 'C1', 'description': 'Preserve exact supported facts.'}], 'decisions': [], 'open_questions': []})
        self.task = self.work.start(self.task['id'])['task']
        self.feedback = worker_context(self.kb, self.task['id'])

    def record(self, name, status='done', goals=('C1',), changes=False):
        directory = self.base / name
        directory.mkdir()
        request = {'id': name, 'kind': 'writing', 'instruction': 'Deliver the scoped contribution.', 'prohibited': [], 'deliverables': [], 'criteria': [{'id': 'D1', 'description': 'Contribution'}],
                   'planning': {'goal_criteria': list(goals)}, 'read_paths': ['producer.txt'] if name != 'consumer' else [], 'write_paths': ['producer.txt'] if changes else []}
        value = {'status': 'done', 'changes': [{'path': 'producer.txt', 'operation': 'write', 'base_hash': 'old',
                                              'content': 'accepted producer\n'}] if changes else [], 'outputs': []}
        path, assessment = directory / 'result.json', directory / 'assessment.json'
        write_json(path, value)
        decision = {'verdict': 'accept', 'checks': [{'satisfied': True}]}
        write_json(assessment, {**decision, 'assessed_at': 'fixture'})
        if changes:
            write_json(directory / 'originals.json', [{'path': 'producer.txt', 'mode': 0o644}])
        record = {'id': 'delegate-' + digest([self.task['id'], name])[:24], 'task_id': self.task['id'],
                  'location_id': self.task['locations'][0], 'root': str(self.root), 'request': request,
                  'summary': 'Scoped contribution retained.', 'provider': 'codex', 'applied': [], 'started_at': '2026-10-19T00:00:00+00:00', 'status': status, 'attempts': 3 if status == 'rejected' else 1, 'history': [],
                  'directory': str(directory), 'result': str(path), 'result_digest': digest(value),
                  'result_file_hash': file_hash(path), 'assessment': decision, 'assessment_ref': str(assessment),
                  'assessment_file_hash': file_hash(assessment), 'feedback_substantive_revision': self.feedback['substantive_revision'],
                  'finished_at': '2026-10-19T00:00:00+00:00'}
        from loop_work.delegation import Delegation, PreflightKnowledge
        observed = Delegation(PreflightKnowledge(self.kb.home), self.task['id'], self.root).observation()
        dispatch = {'before': observed}
        write_json(directory / 'dispatch.json', dispatch)
        record['dispatch_digest'] = digest(dispatch)
        self.kb.put('delegation', record)
        return record

    def payload(self):
        path = self.root / 'producer.txt'
        return {'version': 1, 'assignment_id': 'failed-unit', 'reason': 'Accepted producer and consumer replace the failed combined work.',
                'replacements': ['producer', 'consumer'],
                'coverage': {'assignment:D1': ['producer', 'consumer'], 'goal:C1': ['producer', 'consumer']},
                'evidence': [{'ref': str(path), 'sha256': file_hash(path)}]}

    def setup_replacement(self):
        old = self.record('failed-unit', 'rejected')
        self.record('producer', changes=True)
        self.record('consumer')
        return old

    def test_capsule_retry_uses_shared_response_and_suppresses_retired_obligation(self):
        from unittest.mock import patch
        old = self.setup_replacement()
        response = {'assignment': {'retry': {'requires_recovery': True, 'can_escalate': False}},
                    'next': 'Inspect changed evidence and use --recover; preserve budgets.'}
        coordinator = Orchestration(self.kb)
        with patch('loop_work.delegation.Delegation.response', return_value=response) as shared:
            view = coordinator._worker_preview(old)
            self.assertEqual(view['next'], response['next'])
            self.assertEqual(view['retry'], response['assignment']['retry'])
            self.assertEqual(shared.call_count, 1)
            retired = coordinator._worker_preview(old, {'valid': True})
            self.assertNotIn('retry', retired)
            self.assertIn('valid retirement', retired['next'])
            self.assertEqual(shared.call_count, 1)

    def test_absent_exact_read_becoming_ignored_file_restores_retirement_barrier(self):
        import subprocess
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        (self.root / '.gitignore').write_text('missing-input.txt\n')
        location = self.kb.get('location', self.task['locations'][0])
        location['git'] = True; self.kb.put('location', location)
        self.setup_replacement()
        key = 'delegate-' + digest([self.task['id'], 'consumer'])[:24]
        consumer = self.kb.get('delegation', key)
        consumer['request']['read_paths'] = ['missing-input.txt']
        from loop_work.delegation import Delegation, PreflightKnowledge
        dispatch = {'before': Delegation(PreflightKnowledge(self.kb.home), self.task['id'], self.root).observation()}
        write_json(Path(consumer['directory']) / 'dispatch.json', dispatch)
        consumer['dispatch_digest'] = digest(dispatch); self.kb.put('delegation', consumer)
        retire(self.kb, self.task['id'], self.payload())
        missing = self.root / 'missing-input.txt'; missing.write_text('New ignored data')
        with self.assertRaisesRegex(LoopError, 'ignored/unobserved'):
            completion_feedback(self.kb, self.task['id'], require_worker=True)
        missing.unlink(); missing.symlink_to(self.root / 'producer.txt')
        with self.assertRaisesRegex(LoopError, 'cannot traverse symlinks'):
            completion_feedback(self.kb, self.task['id'], require_worker=True)

    def test_managed_skill_directory_link_uses_rule_manifest_and_remains_pinned(self):
        runtime = self.root / '.loop/runtime/skills/loop-work'
        (runtime / 'agents').mkdir(parents=True)
        (runtime / 'SKILL.md').write_text('Managed skill instructions')
        (runtime / 'agents/openai.yaml').write_text('interface: managed')
        link = self.root / '.agents/skills/loop-work'
        link.parent.mkdir(parents=True)
        link.symlink_to(runtime, target_is_directory=True)
        self.setup_replacement()
        retire(self.kb, self.task['id'], self.payload())
        completion_feedback(self.kb, self.task['id'], require_worker=True)
        # Ordinary worker source scope still cannot follow the managed rule link.
        from loop_work.delegation import source_path
        with self.assertRaisesRegex(LoopError, 'cannot traverse symlinks'):
            source_path(self.root, '.agents/skills/loop-work/SKILL.md')
        (runtime / 'agents/openai.yaml').write_text('interface: changed')
        with self.assertRaisesRegex(LoopError, 'source rule dependency changed'):
            completion_feedback(self.kb, self.task['id'], require_worker=True)

    def _read_directory_kind_transition(self, initially_exists):
        self.setup_replacement()
        folder = self.root / 'empty-input'
        if initially_exists:
            folder.mkdir()
        key = 'delegate-' + digest([self.task['id'], 'consumer'])[:24]
        consumer = self.kb.get('delegation', key)
        consumer['request']['read_paths'] = ['empty-input/']
        from loop_work.delegation import Delegation, PreflightKnowledge
        runner = Delegation(PreflightKnowledge(self.kb.home), self.task['id'], self.root)
        observed = runner.observation()
        dispatch = {'before': observed, 'read_scope': runner._read_scope(consumer['request'], observed)}
        write_json(Path(consumer['directory']) / 'dispatch.json', dispatch)
        consumer['dispatch_digest'] = digest(dispatch); self.kb.put('delegation', consumer)
        retire(self.kb, self.task['id'], self.payload())
        if initially_exists:
            folder.rmdir()
        else:
            folder.mkdir()
        with self.assertRaisesRegex(LoopError, 'read path existence changed'):
            completion_feedback(self.kb, self.task['id'], require_worker=True)

    def test_pinned_empty_read_directory_removal_is_stale(self):
        self._read_directory_kind_transition(True)

    def test_pinned_absent_read_directory_creation_is_stale(self):
        self._read_directory_kind_transition(False)

    def test_read_directory_membership_changes_invalidate_replacement(self):
        self.setup_replacement()
        folder = self.root / 'inputs'; folder.mkdir()
        (folder / 'one.txt').write_text('Original scoped input')
        key = 'delegate-' + digest([self.task['id'], 'consumer'])[:24]
        consumer = self.kb.get('delegation', key)
        consumer['request']['read_paths'] = ['inputs/']
        from loop_work.delegation import Delegation, PreflightKnowledge
        dispatch = {'before': Delegation(PreflightKnowledge(self.kb.home), self.task['id'], self.root).observation()}
        write_json(Path(consumer['directory']) / 'dispatch.json', dispatch)
        consumer['dispatch_digest'] = digest(dispatch)
        self.kb.put('delegation', consumer)
        retire(self.kb, self.task['id'], self.payload())
        (self.root / 'unrelated-consumer.txt').write_text('Allowed outside scope')
        completion_feedback(self.kb, self.task['id'], require_worker=True)
        (folder / 'two.txt').write_text('New scoped input')
        with self.assertRaisesRegex(LoopError, 'scoped source dependency changed'):
            completion_feedback(self.kb, self.task['id'], require_worker=True)

    def test_read_only_replacement_source_dependency_is_checked_with_external_receipt(self):
        self.setup_replacement()
        proof = self.base / 'outside-receipt.txt'; proof.write_text('Approved external receipt')
        payload = self.payload(); payload['evidence'] = [{'ref': str(proof), 'sha256': file_hash(proof)}]
        # Both replacement results have no edits and their assessment cites only a receipt.
        producer = self.kb.get('delegation', 'delegate-' + digest([self.task['id'], 'producer'])[:24])
        result = {'status': 'done', 'changes': [], 'outputs': []}
        write_json(Path(producer['result']), result)
        producer.update(result_digest=digest(result), result_file_hash=file_hash(Path(producer['result'])))
        self.kb.put('delegation', producer)
        retire(self.kb, self.task['id'], payload)
        (self.root / 'producer.txt').write_text('Changed input despite unchanged external receipt')
        with self.assertRaisesRegex(LoopError, 'scoped source dependency changed'):
            completion_feedback(self.kb, self.task['id'], require_worker=True)

    def test_retirement_preserves_failed_history_and_allows_current_producer_after_consumer_edits(self):
        old = self.setup_replacement()
        with self.assertRaisesRegex(LoopError, 'unresolved'):
            completion_feedback(self.kb, self.task['id'], require_worker=True)
        (self.root / 'consumer.txt').write_text('Later consumer contribution\n')
        result = retire(self.kb, self.task['id'], self.payload())
        self.assertTrue(result['retired'])
        self.assertEqual(self.kb.get('delegation', old['id']), old)
        completion_feedback(self.kb, self.task['id'], require_worker=True)
        self.assertTrue(retire(self.kb, self.task['id'], self.payload())['reused'])

    def test_stale_contribution_restores_completion_barrier(self):
        self.setup_replacement()
        retire(self.kb, self.task['id'], self.payload())
        (self.root / 'producer.txt').write_text('unexpected mutation\n')
        with self.assertRaisesRegex(LoopError, 'contribution is stale'):
            completion_feedback(self.kb, self.task['id'], require_worker=True)

    def test_unaccepted_missing_coverage_self_reference_and_receipt_tamper_rejected(self):
        self.setup_replacement()
        for mutate in (lambda p: p.update(replacements=['failed-unit']),
                       lambda p: p['coverage'].pop('goal:C1'),
                       lambda p: p.update(replacements=['unknown'])):
            payload = self.payload(); mutate(payload)
            with self.assertRaises(LoopError):
                retire(self.kb, self.task['id'], payload)
        result = retire(self.kb, self.task['id'], self.payload())
        Path(result['retirement']['receipt_ref']).write_text('{}')
        with self.assertRaises(LoopError):
            completion_feedback(self.kb, self.task['id'], require_worker=True)

    def test_replacement_decision_tamper_and_feedback_do_not_bypass_barrier(self):
        self.setup_replacement()
        retire(self.kb, self.task['id'], self.payload())
        decision = self.base / 'producer/assessment.json'
        original = decision.read_bytes()
        decision.write_text('{}')
        with self.assertRaisesRegex(LoopError, 'assessment receipt changed'):
            completion_feedback(self.kb, self.task['id'], require_worker=True)
        decision.write_bytes(original)
        Orchestration(self.kb).feedback(self.task['session_id'], {'id': 'new-correction', 'task_id': self.task['id'],
            'kind': 'correction', 'summary': 'Preserve a newly clarified requirement.', 'original_input_ref': 'conversation:correction',
            'applies_to': 'This task', 'supersedes': []}, 0)
        with self.assertRaisesRegex(LoopError, 'feedback authority changed'):
            completion_feedback(self.kb, self.task['id'], require_worker=True)

    def test_retirement_proof_refresh_appends_receipt_and_capsule_explains_barrier(self):
        old = self.setup_replacement()
        proof = self.base / 'current-proof.txt'; proof.write_text('Original independent proof')
        payload = self.payload(); payload['evidence'] = [{'ref': str(proof), 'sha256': file_hash(proof)}]
        first = retire(self.kb, self.task['id'], payload)
        first_path = Path(first['retirement']['receipt_ref']); first_bytes = first_path.read_bytes()
        capsule = Orchestration(self.kb).context(self.task['session_id'], self.task['id'])
        failed = next(x for x in capsule['workers'] if x['assignment_id'] == 'failed-unit')
        self.assertEqual(failed['status'], 'rejected')
        self.assertTrue(failed['retirement']['valid'])
        self.assertNotIn('Retry the rejected', capsule['next'])
        proof.write_text('Refreshed current independent proof')
        with self.assertRaisesRegex(LoopError, 'contribution evidence changed'):
            completion_feedback(self.kb, self.task['id'], require_worker=True)
        payload['evidence'][0]['sha256'] = file_hash(proof)
        second = retire(self.kb, self.task['id'], payload)
        self.assertEqual(second['retirement']['sequence'], 2)
        self.assertEqual(first_path.read_bytes(), first_bytes)
        self.assertEqual(len(second['retirement']['history']), 1)
        self.assertEqual(self.kb.get('delegation', old['id']), old)
        completion_feedback(self.kb, self.task['id'], require_worker=True)

    def test_original_failed_artifact_and_replacement_identity_are_pinned(self):
        old = self.setup_replacement()
        retire(self.kb, self.task['id'], self.payload())
        path = Path(old['result']); original = path.read_bytes(); path.write_text('{}')
        with self.assertRaisesRegex(LoopError, 'result artifact changed'):
            completion_feedback(self.kb, self.task['id'], require_worker=True)
        path.write_bytes(original)
        replacement = self.kb.get('delegation', 'delegate-' + digest([self.task['id'], 'producer'])[:24])
        replacement['candidate_id'] = 'different-candidate'
        self.kb.put('delegation', replacement)
        with self.assertRaisesRegex(LoopError, 'identity changed'):
            completion_feedback(self.kb, self.task['id'], require_worker=True)

    def test_retirement_preserves_original_dispatch_and_attempt_record_pins(self):
        old = self.setup_replacement()
        from loop_work.delegation import Delegation
        runner = Delegation.__new__(Delegation); runner.knowledge = self.kb
        runner.save_attempt(old)
        retire(self.kb, self.task['id'], self.payload())
        for name in ('dispatch.json', 'attempt.json'):
            with self.subTest(artifact=name):
                path = Path(old['directory']) / name
                previous = path.read_bytes(); path.write_text('{}')
                try:
                    with self.assertRaises(LoopError):
                        completion_feedback(self.kb, self.task['id'], require_worker=True)
                finally:
                    path.write_bytes(previous)
        completion_feedback(self.kb, self.task['id'], require_worker=True)

    def test_public_cli_typed_block_and_retirement(self):
        import subprocess, sys
        payload = self.block()
        path = self.base / 'block.json'; write_json(path, payload)
        entry = Path(__file__).resolve().parents[1] / 'scripts/loop.py'
        argv = [sys.executable, str(entry), '--knowledge-home', str(self.kb.home), 'work']
        legacy = subprocess.run([*argv, 'block', self.task['id'], '--reason', 'three failures'], capture_output=True, text=True)
        self.assertNotEqual(legacy.returncode, 0)
        invalid = subprocess.run([*argv, 'block', self.task['id'], '--input', str(path)], capture_output=True, text=True)
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn('Overall execution budget remains', invalid.stderr)
        self.setup_replacement(); write_json(path, self.payload())
        result = subprocess.run([*argv, 'retire', self.task['id'], '--input', str(path)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(__import__('json').loads(result.stdout)['retired'])

    def test_read_only_replacement_cannot_launder_stale_assessment_evidence(self):
        self.setup_replacement()
        key = 'delegate-' + digest([self.task['id'], 'consumer'])[:24]
        record = self.kb.get('delegation', key)
        evidence = self.root / 'read-only-input.txt'; evidence.write_text('value = 1')
        record['assessment']['checks'][0]['evidence'] = [{'ref': str(evidence), 'sha256': file_hash(evidence)}]
        write_json(Path(record['assessment_ref']), {**record['assessment'], 'assessed_at': 'fixture'})
        record['assessment_file_hash'] = file_hash(Path(record['assessment_ref']))
        self.kb.put('delegation', record)
        retire(self.kb, self.task['id'], self.payload())
        evidence.write_text('value = 999')
        with self.assertRaisesRegex(LoopError, 'contribution evidence changed'):
            completion_feedback(self.kb, self.task['id'], require_worker=True)
        with self.assertRaisesRegex(LoopError, 'contribution evidence changed'):
            retire(self.kb, self.task['id'], self.payload())

    def _accepted_own_transition(self, operation, *, absent=False, hide_output=False, write_only=False):
        self.setup_replacement()
        key = 'delegate-' + digest([self.task['id'], 'producer'])[:24]
        record = self.kb.get('delegation', key)
        if write_only:
            record['request']['read_paths'] = []
        path = self.root / 'producer.txt'
        if absent:
            path.unlink()
        else:
            path.write_text('Original input before authorized edit')
        base_pin = file_hash(path)
        from loop_work.delegation import Delegation, PreflightKnowledge
        runner = Delegation(PreflightKnowledge(self.kb.home), self.task['id'], self.root)
        observed = runner.observation()
        dispatch = {'before': observed, 'read_scope': runner._read_scope(record['request'], observed)}
        change = {'path': 'producer.txt', 'operation': operation, 'base_hash': base_pin}
        if operation == 'delete':
            path.unlink()
        else:
            path.write_text('Accepted final output')
            if operation == 'patch':
                change.update(result_hash=file_hash(path), edits=[{'start': 0, 'end': 37, 'content': 'Accepted final output'}])
            else:
                change['content'] = 'Accepted final output'
        value = {'status': 'done', 'changes': [change], 'outputs': []}
        write_json(Path(record['result']), value)
        record.update(result_digest=digest(value), result_file_hash=file_hash(Path(record['result'])), dispatch_digest=digest(dispatch))
        write_json(Path(record['directory']) / 'dispatch.json', dispatch)
        self.kb.put('delegation', record)
        proof = self.base / 'transition-proof.txt'; proof.write_text('Independent verification')
        payload = self.payload(); payload['evidence'] = [{'ref': str(proof), 'sha256': file_hash(proof)}]
        retire(self.kb, self.task['id'], payload)
        (self.root / 'independent-consumer.txt').write_text('Unrelated consumer output')
        completion_feedback(self.kb, self.task['id'], require_worker=True)
        if hide_output:
            (self.root / '.gitignore').write_text('producer.txt\n')
            with self.assertRaisesRegex(LoopError, 'ignored/unobserved'):
                completion_feedback(self.kb, self.task['id'], require_worker=True)
            return
        path.write_text('Stale or resurrected output')
        with self.assertRaisesRegex(LoopError, 'contribution is stale'):
            completion_feedback(self.kb, self.task['id'], require_worker=True)

    def test_absent_read_created_by_exact_accepted_own_write_is_output(self):
        self._accepted_own_transition('write', absent=True)

    def test_write_only_output_hidden_by_git_info_exclude_is_not_retirement_authority(self):
        import subprocess
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        location = self.kb.get('location', self.task['locations'][0])
        location['git'] = True; self.kb.put('location', location)
        self.setup_replacement()
        key = 'delegate-' + digest([self.task['id'], 'producer'])[:24]
        record = self.kb.get('delegation', key)
        record['request']['read_paths'] = []
        self.kb.put('delegation', record)
        retire(self.kb, self.task['id'], self.payload())
        completion_feedback(self.kb, self.task['id'], require_worker=True)
        pin = file_hash(self.root / 'producer.txt')
        (self.root / '.git/info/exclude').write_text('producer.txt\n')
        self.assertEqual(file_hash(self.root / 'producer.txt'), pin)
        with self.assertRaisesRegex(LoopError, 'write contribution is now ignored/unobserved'):
            completion_feedback(self.kb, self.task['id'], require_worker=True)

    def test_accepted_own_create_becoming_ignored_remains_blocked(self):
        import subprocess
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        location = self.kb.get('location', self.task['locations'][0])
        location['git'] = True; self.kb.put('location', location)
        self._accepted_own_transition('write', absent=True, hide_output=True)

    def test_normal_write_only_output_is_valid(self):
        self._accepted_own_transition('write', write_only=True)

    def test_normal_write_only_deletion_is_valid(self):
        self._accepted_own_transition('delete', write_only=True)

    def test_existing_read_replaced_by_exact_accepted_write_is_output(self):
        self._accepted_own_transition('write')

    def test_existing_read_replaced_by_exact_accepted_patch_is_output(self):
        self._accepted_own_transition('patch')

    def test_existing_read_removed_by_exact_accepted_delete_is_output(self):
        self._accepted_own_transition('delete')

    def test_own_preapply_base_evidence_remains_valid_for_accepted_output(self):
        self.setup_replacement()
        key = 'delegate-' + digest([self.task['id'], 'producer'])[:24]
        record = self.kb.get('delegation', key)
        record['assessment']['checks'][0]['evidence'] = [{'ref': str(self.root / 'producer.txt'), 'sha256': 'old'}]
        write_json(Path(record['assessment_ref']), {**record['assessment'], 'assessed_at': 'fixture'})
        record['assessment_file_hash'] = file_hash(Path(record['assessment_ref']))
        self.kb.put('delegation', record)
        retire(self.kb, self.task['id'], self.payload())
        (self.root / 'consumer.txt').write_text('Independent consumer change')
        completion_feedback(self.kb, self.task['id'], require_worker=True)

    def block(self, **overrides):
        return {'version': 1, 'kind': 'budget_exhausted', 'reason': 'Execution budget exhausted.',
                'scope': 'task', 'retryable': False, 'evidence': [], **overrides}

    def test_unit_attempt_exhaustion_does_not_justify_global_stop(self):
        self.record('failed-unit', 'rejected')
        before = self.work.load(self.task['id'])
        with self.assertRaisesRegex(LoopError, 'Overall execution budget remains'):
            self.work.stop(self.task['id'], self.block())
        self.assertEqual(self.work.load(self.task['id']), before)
        with self.assertRaisesRegex(LoopError, 'structured input'):
            self.work.stop(self.task['id'], 'three attempts failed')

    def test_exhausted_task_budget_is_recorded_and_cannot_resume(self):
        self.kb.put('worker-budget', {'id': self.task['id'], 'calls': 40})
        self.work.stop(self.task['id'], self.block())
        blocked = self.work.load(self.task['id'])
        self.assertEqual(blocked['block_proof']['budget']['calls_remaining'], 0)
        with self.assertRaisesRegex(LoopError, 'not retryable'):
            self.work.resume(self.task['id'])

    def test_external_evidence_and_explicit_user_pause(self):
        proof = self.root / 'failure.log'; proof.write_text('service unavailable')
        payload = self.block(kind='external', reason='Required service is unavailable.', retryable=True,
                             evidence=[{'ref': str(proof), 'sha256': file_hash(proof)}])
        self.work.stop(self.task['id'], payload)
        self.work.resume(self.task['id'])
        with self.assertRaisesRegex(LoopError, 'explicit pause'):
            self.work.stop(self.task['id'], self.block(kind='user_pause', retryable=True))
        Orchestration(self.kb).feedback(self.task['session_id'], {'id': 'pause', 'task_id': self.task['id'],
            'kind': 'pause', 'summary': 'Stop this task.', 'original_input_ref': 'conversation:user-stop',
            'applies_to': 'This task', 'supersedes': []}, 0)
        self.work.stop(self.task['id'], self.block(kind='user_pause', reason='User paused this task.', retryable=True))
        with self.assertRaisesRegex(LoopError, 'paused'):
            self.work.resume(self.task['id'])
