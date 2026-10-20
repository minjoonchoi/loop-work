"""Persisted task transitions and benchmark protocol isolation."""
import copy
import json
import sqlite3
from pathlib import Path
import tempfile
import unittest

from loop_work.benchmark import activation_records, task_activation, check_task_activation, ACTIVATION_PROTOCOL
from loop_work.bench_evolution import profile, PROFILE_FIELDS
from loop_work.storage import digest


class TaskBenchActivationTests(unittest.TestCase):
    def setUp(self):
        self.session = {'id': 'session-a', 'provider': 'codex', 'harness': {
            'enabled': True, 'scope': 'task', 'task_id': 'work-a', 'inputs': 'related',
            'activated_at': '2026-10-21T00:00:00Z'}}
        self.task = {'id': 'work-a', 'session_id': 'session-a', 'provider': 'codex', 'phase': 'working'}

    def check(self, session=None, task=None, **previous):
        return task_activation([session or self.session], [task or self.task], 'codex', **previous)[0]

    def test_terminal_release_matches_actual_record(self):
        self.assertTrue(self.check())
        for terminal in ('completed', 'aborted'):
            task = {**self.task, 'phase': terminal}
            session = copy.deepcopy(self.session)
            self.assertFalse(self.check(session, task))
            session['harness'].update(enabled=False, released_at='now', release_reason=terminal)
            self.assertTrue(self.check(session, task))
            session['harness']['release_reason'] = 'off'
            self.assertFalse(self.check(session, task))

    def test_disabled_legacy_foreign_or_extra_task_cannot_mask_missing_authority(self):
        for mutation in ({'enabled': False}, {'scope': 'conversation'}, {'inputs': 'all'},
                         {'task_id': 'work-other'}, {'activated_at': None}):
            session = copy.deepcopy(self.session)
            session['harness'].update(mutation)
            self.assertFalse(self.check(session))
        for mutation in ({'session_id': 'session-other'}, {'provider': 'claude'}, {'phase': 'invented'}):
            self.assertFalse(self.check(task={**self.task, **mutation}))
        self.assertFalse(task_activation([self.session], [self.task, {**self.task, 'id': 'extra'}], 'codex')[0])
        self.assertFalse(task_activation([self.session], [], 'codex')[0])
        self.assertFalse(self.check(previous_session='session-other'))
        self.assertFalse(self.check(previous_task='work-other'))

    def test_actual_database_records_are_read_without_creating_missing_database(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.assertEqual(activation_records(root), ([], []))
            self.assertFalse((root / 'knowledge').exists())
            (root / 'knowledge').mkdir()
            db = sqlite3.connect(root / 'knowledge/knowledge.sqlite3')
            self.addCleanup(db.close)
            db.execute('CREATE TABLE records (kind TEXT, body TEXT)')
            db.executemany('INSERT INTO records VALUES (?,?)', [('session', json.dumps(self.session)),
                                                               ('task', json.dumps(self.task))])
            db.commit()
            sessions, tasks = activation_records(root)
            self.assertTrue(task_activation(sessions, tasks, 'codex')[0])
            db.execute('INSERT INTO records VALUES (?,?)', ('task', json.dumps({**self.task, 'id': 'unrequested-task'})))
            db.commit()
            sessions, tasks = activation_records(root)
            self.assertFalse(task_activation(sessions, tasks, 'codex')[0])

    def test_new_protocol_cannot_compare_equal_to_legacy_profile(self):
        spec = {field: 'fixture' for field in PROFILE_FIELDS}
        legacy = profile(spec)
        spec['activation_protocol'] = ACTIVATION_PROTOCOL
        current = profile(spec)
        self.assertNotEqual(digest(legacy), digest(current))
        self.assertNotIn('activation_protocol', legacy)
        self.assertEqual(current['activation_protocol'], 'task-scoped-v1')

    def test_plain_control_cannot_hide_task_creation_behind_disabled_marker(self):
        self.assertTrue(check_task_activation('plain', [], [], 'codex')[0])
        disabled = copy.deepcopy(self.session)
        disabled['harness']['enabled'] = False
        self.assertFalse(check_task_activation('plain', [disabled], [], 'codex')[0])
        self.assertFalse(check_task_activation('plain', [], [self.task], 'codex')[0])
        self.assertFalse(check_task_activation('unknown', [], [], 'codex')[0])

    def test_final_turn_requires_real_completed_phase_and_matching_release(self):
        self.assertTrue(self.check())
        self.assertFalse(self.check(require_completed=True))
        session = copy.deepcopy(self.session)
        session['harness'].update(enabled=False, released_at='now', release_reason='aborted')
        self.assertTrue(self.check(session, {**self.task, 'phase': 'aborted'}))
        self.assertFalse(self.check(session, {**self.task, 'phase': 'aborted'}, require_completed=True))
        session['harness']['release_reason'] = 'completed'
        self.assertTrue(self.check(session, {**self.task, 'phase': 'completed'}, require_completed=True))
        session['harness']['enabled'] = True
        self.assertFalse(self.check(session, {**self.task, 'phase': 'completed'}, require_completed=True))
