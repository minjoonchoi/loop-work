from __future__ import annotations

import copy
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from loop_work.knowledge import KnowledgeBase, default_home
from loop_work.storage import LoopError


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name).resolve()
        self.fake_home = self.base / 'home'; self.fake_home.mkdir()
        self.kb = KnowledgeBase(self.base / 'knowledge', vault_home=self.base / 'vault')

    def task(self, name='task-one', project='project-one', phase='working'):
        return {'id': name, 'title': 'Explain the supported behavior', 'kind': 'document', 'phase': phase,
                'session_id': 'session-one', 'project_ids': [project], 'goal': {'outcome': 'Explain exact facts.'},
                'updated_at': '2026-10-20T00:00:00+00:00', 'result': None}

    def folder(self, project='project-one', task='task-one'):
        from loop_work.vault_layout import slug
        return self.base/'vault/프로젝트'/slug('프로젝트',project)/'작업'/slug(self.task()['title'],task)

    def current(self, project='project-one', task='task-one'):
        return self.folder(project,task)/'진행 현황.md'

    def test_new_default_and_readonly_preflight_share_data_home(self):
        from loop_work.delegation import PreflightKnowledge
        with patch('pathlib.Path.home', return_value=self.fake_home), patch.dict(os.environ, {}, clear=True):
            self.assertEqual(default_home(), self.fake_home / '.loop-work/data')
            kb = KnowledgeBase()
            self.assertEqual(PreflightKnowledge().home, kb.home)
            kb.put('task', self.task())
            self.assertTrue(list((self.fake_home / '.loop-work/vault/프로젝트').glob('*/작업/*/진행 현황.md')))

    def test_legacy_database_is_reused_without_moving_or_duplicate_creation(self):
        old = KnowledgeBase(self.fake_home / '.local/share/loop-dev', vault_home=False)
        old.put('task', self.task())
        with patch('pathlib.Path.home', return_value=self.fake_home), patch.dict(os.environ, {}, clear=True):
            selected = KnowledgeBase()
            self.assertEqual(selected.home, old.home)
            self.assertIsNotNone(selected.get('task', 'task-one'))
            self.assertFalse((self.fake_home / '.loop-work/data/knowledge.sqlite3').exists())
            newer = KnowledgeBase(self.fake_home / '.loop-work/data', vault_home=False)
            with self.assertRaisesRegex(LoopError, 'multiple knowledge'):
                KnowledgeBase()
            self.assertTrue(newer.path.exists()); self.assertTrue(old.path.exists())

    def test_explicit_and_environment_scopes_do_not_write_shared_vault(self):
        with patch('pathlib.Path.home', return_value=self.fake_home), patch.dict(os.environ, {'LOOP_KB_HOME': str(self.base / 'environment')}, clear=True):
            env = KnowledgeBase(); explicit = KnowledgeBase(self.base / 'explicit')
            for kb in (env, explicit):
                kb.put('task', self.task()); self.assertFalse(kb.vault_status()['enabled'])
            self.assertEqual(env.home, self.base / 'environment')
            self.assertEqual(explicit.home, self.base / 'explicit')
            self.assertFalse((self.fake_home / '.loop-work').exists())

    def test_current_interim_final_and_stale_completion_preserve_history(self):
        task = self.task(phase='blocked'); task['reason'] = 'Original blocked condition'
        self.kb.put('task', task)
        self.assertFalse((self.folder() / '기록/완료').exists())
        original = list((self.folder() / '기록/중간').glob('*.md'))[0].read_bytes()
        complete = {**task, 'phase': 'completed', 'result': {'summary': 'Verified explanation', 'checks': []}}
        self.kb.put('task', complete)
        final = list((self.folder() / '기록/완료').glob('*.md'))[0]
        final_text = final.read_bytes(); self.assertIn('과거 완료 시점'.encode(), final_text)
        stale = copy.deepcopy(complete); stale['result']['evidence_current'] = False
        self.kb.put('task', stale)
        self.assertIn('새 검증 전에는 현재 완료로 사용하지 마세요', self.current().read_text())
        self.assertEqual(final.read_bytes(), final_text)
        self.assertTrue(any(path.read_bytes() == original for path in (self.folder() / '기록/중간').glob('*.md')))

    def test_delayed_export_rereads_committed_record_after_lock_acquisition(self):
        from contextlib import contextmanager
        import threading
        import loop_work.vault as module
        from loop_work.vault import VaultExporter
        task = self.task(); self.kb.put('task', task)
        old_snapshot = next((self.folder() / '기록/중간').glob('*.md'))
        old_content = old_snapshot.read_bytes()
        waiting, release = threading.Event(), threading.Event()
        original_lock = module.locked
        errors = []
        @contextmanager
        def delayed_lock(*args, **kwargs):
            if threading.current_thread().name == 'delayed-vault-export':
                waiting.set()
                if not release.wait(5):
                    raise AssertionError('Newer export did not release delayed exporter')
            with original_lock(*args, **kwargs):
                yield
        def delayed_export():
            try:
                VaultExporter(self.kb, self.base / 'vault').export('task', task['id'])
            except Exception as exc:
                errors.append(exc)
        with patch.object(module, 'locked', delayed_lock):
            thread = threading.Thread(target=delayed_export, name='delayed-vault-export')
            thread.start()
            try:
                self.assertTrue(waiting.wait(3))
                newer = {**task, 'title': 'Newer committed task result'}
                self.kb.put('task', newer)
                self.assertIn(newer['title'], self.current().read_text())
            finally:
                release.set(); thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
        self.assertIn(newer['title'], self.current().read_text())
        self.assertEqual(old_snapshot.read_bytes(), old_content)
        self.assertTrue(list((self.folder() / '기록/중간').glob('*-이력-*.md')))

    def test_busy_newer_export_remains_observable_after_older_success(self):
        import threading
        from loop_work.vault import VaultExporter
        task = self.task(); self.kb.put('task', task)
        old_revision = self.kb.vault_revision()
        waiting, release = threading.Event(), threading.Event()
        original_render = VaultExporter._task
        errors = []
        def hold_old_render(exporter, *args):
            value = original_render(exporter, *args)
            if threading.current_thread().name == 'older-vault-render':
                waiting.set()
                if not release.wait(5):
                    raise AssertionError('New database writer did not finish')
            return value
        def old_export():
            try:
                self.kb.export_vault('task', task['id'])
            except Exception as exc:
                errors.append(exc)
        other = KnowledgeBase(self.kb.home, vault_home=self.base / 'vault')
        with patch.object(VaultExporter, '_task', hold_old_render):
            thread = threading.Thread(target=old_export, name='older-vault-render'); thread.start()
            try:
                self.assertTrue(waiting.wait(3))
                changed = {**task, 'title': 'New task committed while export is busy'}
                other.put('task', changed)
                during = other.vault_status()
                self.assertEqual(other.get('task', task['id'])['title'], changed['title'])
                self.assertTrue(during['errors'])
            finally:
                release.set(); thread.join(5)
        self.assertFalse(thread.is_alive()); self.assertEqual(errors, [])
        status = self.kb.vault_status()
        self.assertEqual(status['status'], 'deferred')
        self.assertEqual(status['exported_source_revision'], old_revision)
        self.assertNotEqual(status['exported_source_revision'], status['current_source_revision'])
        self.assertEqual(status['records']['task/task-one']['errors'], during['records']['task/task-one']['errors'])
        current = self.current().read_text()
        self.assertIn('최종 내보내기 기준', current)
        self.assertIn('저장된 데이터보다 늦을 수', current)
        # Success for another record cannot erase this record's pending failure.
        other.put('task', self.task('task-two', 'project-two'))
        self.assertTrue(self.kb.vault_status()['records']['task/task-one']['errors'])
        # Explicit bounded repair can clear the failure at the same newer revision.
        result = other.sync_vault()
        self.assertEqual(result['errors'], [])
        self.assertEqual(result['status'], 'ok')
        self.assertIn(changed['title'], self.current().read_text())

    def test_same_revision_older_publication_cannot_erase_newer_user_edit_conflict(self):
        import threading
        from loop_work.vault import VaultExporter
        task = self.task(); self.kb.put('task', task)
        revision = self.kb.vault_revision()
        current = self.current(); managed_text = current.read_bytes()
        waiting, release = threading.Event(), threading.Event()
        original_export = VaultExporter.export
        failures = []
        def delayed_publication(exporter, *args):
            result = original_export(exporter, *args)
            if threading.current_thread().name == 'older-status-publication':
                waiting.set()
                if not release.wait(5):
                    raise AssertionError('Newer conflict was not published')
            return result
        def older():
            try:
                self.kb.export_vault('task', task['id'])
            except Exception as exc:
                failures.append(exc)
        other = KnowledgeBase(self.kb.home, vault_home=self.base / 'vault')
        with patch.object(VaultExporter, 'export', delayed_publication):
            thread = threading.Thread(target=older, name='older-status-publication'); thread.start()
            try:
                self.assertTrue(waiting.wait(3))
                current.write_text('User correction at the same database revision')
                conflict = other.export_vault('task', task['id'])
                self.assertTrue(conflict['errors'])
                newer_attempt = conflict['records']['task/task-one']['export_attempt']
                self.assertEqual(other.vault_revision(), revision)
            finally:
                release.set(); thread.join(5)
        self.assertFalse(thread.is_alive()); self.assertEqual(failures, [])
        after = self.kb.vault_status()
        self.assertEqual(after['status'], 'conflict')
        self.assertEqual(after['records']['task/task-one']['export_attempt'], newer_attempt)
        self.assertEqual(after['errors'], conflict['errors'])
        self.assertEqual(current.read_text(), 'User correction at the same database revision')
        # Explicit fixture repair restores ownership; a genuinely newer attempt
        # can then clear the error without changing the database revision.
        current.write_bytes(managed_text)
        repaired = other.export_vault('task', task['id'])
        self.assertEqual(repaired['status'], 'ok')
        self.assertGreater(repaired['records']['task/task-one']['export_attempt'], newer_attempt)
        self.assertEqual(repaired['errors'], [])

    def test_legacy_store_ignores_unused_new_root_or_data_conflicts(self):
        from loop_work.delegation import PreflightKnowledge
        for conflict in ('root-file', 'root-link', 'root-loop', 'data-file', 'data-link'):
            with self.subTest(conflict=conflict):
                home = self.base / conflict; home.mkdir()
                old = KnowledgeBase(home / '.local/share/loop-work', vault_home=False)
                old.put('task', self.task())
                workspace = home / '.loop-work'
                outside = self.base / ('outside-' + conflict); outside.mkdir()
                if conflict == 'root-file':
                    workspace.write_text('Unrelated existing root file')
                elif conflict == 'root-link':
                    workspace.symlink_to(outside, target_is_directory=True)
                elif conflict == 'root-loop':
                    workspace.symlink_to(workspace, target_is_directory=True)
                else:
                    workspace.mkdir()
                    if conflict == 'data-file':
                        (workspace / 'data').write_text('Unrelated data file')
                    else:
                        (workspace / 'data').symlink_to(outside, target_is_directory=True)
                with patch('pathlib.Path.home', return_value=home), patch.dict(os.environ, {}, clear=True):
                    selected = KnowledgeBase()
                    self.assertEqual(selected.home, old.home)
                    self.assertEqual(PreflightKnowledge().home, old.home)
                    selected.put('task', {**self.task(), 'title': 'Legacy work continues'})
                    self.assertEqual(selected.get('task', 'task-one')['title'], 'Legacy work continues')
                    if conflict.startswith('root-'):
                        self.assertTrue(selected.vault_status()['errors'])
                    # Even explicit retained-home use must not resolve an unused
                    # new-root symlink loop while recognizing the shared store.
                    self.assertEqual(KnowledgeBase(old.home).get('task', 'task-one')['title'], 'Legacy work continues')
                self.assertEqual(list(outside.iterdir()), [])

    def test_no_op_does_not_rewrite_notes_or_ownership_manifest(self):
        task = self.task(); self.kb.put('task', task)
        current = self.current(); manifest = self.kb.home / 'vault-owned.json'
        before = (current.stat().st_mtime_ns, manifest.stat().st_mtime_ns)
        self.kb.put('task', task); self.kb.sync_vault()
        self.assertEqual((current.stat().st_mtime_ns, manifest.stat().st_mtime_ns), before)

    def test_user_edit_conflict_preserves_note_and_database_commit(self):
        task = self.task(); self.kb.put('task', task)
        current = self.current(); current.write_text('A human-owned correction')
        changed = {**task, 'title': 'New database result'}
        with self.kb.connection() as db:
            self.kb.put('task', changed, db)
        self.assertEqual(self.kb.get('task', task['id'])['title'], 'New database result')
        self.assertEqual(current.read_text(), 'A human-owned correction')
        self.assertEqual(self.kb.vault_status()['status'], 'conflict')
        self.assertIn('preserved', ' '.join(self.kb.vault_status()['errors']))
        self.assertTrue((self.kb.home / 'vault-export-status.json').is_file())

    def test_export_failure_after_commit_does_not_break_get_or_task_work(self):
        with patch('loop_work.vault.VaultExporter.export', side_effect=OSError('Read-only vault fixture')):
            self.kb.put('task', self.task())
        self.assertEqual(self.kb.get('task', 'task-one')['phase'], 'working')
        self.assertIn('Read-only vault fixture', ' '.join(self.kb.vault_status()['errors']))
        self.assertTrue((self.kb.home / 'views/task/task-one.md').is_file())

    def test_status_write_failure_is_observable_without_reverting_database(self):
        self.kb.put('task', self.task())
        changed = {**self.task(), 'title': 'Committed with diagnostic write failure'}
        with patch('loop_work.storage.write_json', side_effect=OSError('Status destination unavailable')):
            self.kb.put('task', changed)
        self.assertEqual(self.kb.get('task', 'task-one')['title'], changed['title'])
        self.assertEqual(self.kb.vault_status()['status'], 'error')
        self.assertIn('Status destination unavailable', ' '.join(self.kb.vault_status()['errors']))

    def test_backfill_existing_database_and_project_separation(self):
        kb = KnowledgeBase(self.base / 'backfill', vault_home=False)
        first = self.task(); kb.put('task', first)
        kb.put('task', {**first, 'phase': 'blocked', 'reason': 'Historical stop'})
        kb.put('task', self.task('task-two', 'project-two'))
        exporter = KnowledgeBase(kb.home, vault_home=self.base / 'vault')
        result = exporter.sync_vault()
        self.assertEqual(result['records_considered'], 2)
        self.assertTrue(self.current().is_file())
        self.assertTrue(self.current('project-two', 'task-two').is_file())
        historical = list((self.folder() / '기록/중간').glob('*-이력-*.md'))
        self.assertTrue(historical); self.assertIn('과거 작업 기록', historical[0].read_text())
        self.assertEqual(kb.get('task', 'task-one')['phase'], 'blocked')

    def test_symlink_and_traversal_targets_are_rejected_without_overwrite(self):
        outside = self.base / 'outside'; outside.mkdir()
        (self.base / 'vault').symlink_to(outside, target_is_directory=True)
        self.kb.put('task', self.task())
        self.assertEqual(list(outside.iterdir()), [])
        self.assertTrue(self.kb.vault_status()['errors'])
        (self.base / 'vault').unlink()
        task = self.task(project='../outside'); self.kb.put('task', task)
        self.assertEqual(list(outside.iterdir()), [])
        self.assertIn('Unsafe', ' '.join(self.kb.vault_status()['errors']))

    def test_unowned_existing_target_is_preserved_before_first_export(self):
        current = self.current(); current.parent.mkdir(parents=True)
        current.write_text('Existing user document')
        self.kb.put('task', self.task())
        self.assertEqual(current.read_text(), 'Existing user document')
        self.assertIn('unowned', ' '.join(self.kb.vault_status()['errors']))

    def test_transactional_human_record_updates_vault_after_commit(self):
        self.kb.put('task', self.task())
        with self.kb.connection() as db:
            self.kb.put('human-request', {'id': 'human-one', 'task_id': 'task-one', 'status': 'pending', 'question': 'Explicit decision'}, db)
        record = next((self.folder() / '기록/사용자 검토').glob('*.md'))
        self.assertIn('Explicit decision', record.read_text())
        self.assertIn('Explicit decision', record.read_text())

    def test_human_notes_and_obsidian_settings_are_preserved(self):
        notes = self.base / 'vault/notes'; notes.mkdir(parents=True)
        note = notes / 'my-note.md'; note.write_text('My private note')
        settings = self.base / 'vault/.obsidian'; settings.mkdir()
        config = settings / 'app.json'; config.write_text('{"user":true}')
        self.kb.put('task', self.task())
        self.assertEqual(note.read_text(), 'My private note')
        self.assertEqual(config.read_text(), '{"user":true}')
