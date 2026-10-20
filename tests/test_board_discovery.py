"""Vault-only discovery and partial history failures stay readable, never authoritative."""
from pathlib import Path
import json
import unittest
from unittest.mock import patch

import test_board
from loop_work import board as board_module
from loop_work.storage import LoopError, file_hash, read_json, write_json


class BoardDiscoveryTests(unittest.TestCase):
    def setUp(self):
        # Reuse setup without importing/subclassing its TestCase (no duplicate tests).
        test_board.BoardTests.setUp(self)

    def note(self, identifier, *, phase='working', body='Written in Obsidian, not copied from the database.'):
        record = {'id': identifier, 'title': 'Vault-only ' + identifier, 'kind': 'document', 'phase': phase,
                  'session_id': 'vault-only-session', 'project_ids': ['vault-only-project'],
                  'goal': {'outcome': 'A local document'}, 'result': None}
        envelope = {'version': 1, 'kind': 'task', 'id': identifier,
                    'knowledge_home': str(self.kb.home), 'record': record}
        path = self.vault / 'projects/vault-only-project/tasks' / identifier / 'current.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('---\nloop_work: ' + json.dumps(envelope) + '\n---\n' + body)
        return path, record

    def test_unowned_vault_only_task_is_listed_and_read_from_markdown(self):
        path, record = self.note('vault-only-one')
        listing = self.board.list(include_closed=True)
        row = next(item for item in listing['tasks'] if item['id'] == record['id'])
        self.assertEqual(row['record'], record)
        self.assertFalse(row['writable']); self.assertFalse(row['fresh'])
        self.assertIn('Written in Obsidian', row['body'])
        self.assertEqual(self.board.show(record['id'], 'task')['body'], row['body'])
        self.assertEqual(self.board.document(path.relative_to(self.vault).as_posix())['body'], row['body'])
        self.assertIsNone(self.kb.get('task', record['id'], required=False))

    def test_no_manifest_discovers_readonly_tasks_without_creating_runtime_authority(self):
        path, record = self.note('vault-only-complete', phase='completed', body='# Completed in a personal note')
        manifest = self.kb.home / 'vault-owned.json'; manifest.unlink()
        listing = self.board.list(include_closed=True)
        row = next(item for item in listing['tasks'] if item['id'] == record['id'])
        self.assertEqual(row['record']['phase'], 'completed')
        self.assertIn('personal note', self.board.show(record['id'], 'task')['body'])
        self.assertTrue(all(not item['writable'] for item in listing['tasks'] + listing['requests']))
        self.assertFalse(manifest.exists())
        self.assertIsNone(self.kb.get('task', record['id'], required=False))
        original = self.kb.get('human-request', self.request['id'])
        with self.assertRaises(LoopError):
            self.board.respond(self.request['id'], {'decision': 'approve', 'text': 'A fake completed note is not authority'}, original['revision'], 'no-vault-authority')
        self.assertEqual(self.kb.get('human-request', self.request['id']), original)

    def test_missing_history_does_not_hide_healthy_interim_or_final_documents(self):
        task = self.board.show(self.task['id'], 'task')
        parent = Path(task['path']).parent
        manifest_path = self.kb.home / 'vault-owned.json'; manifest = read_json(manifest_path)
        paths = {}
        for kind, name, body in (('interim', 'missing-early', 'Lost historical note'),
                                 ('interim', 'healthy-interim', '# Observed partial result'),
                                 ('final', 'healthy-final', '# Historical completion claim only')):
            relative = (parent / kind / (name + '.md')).as_posix()
            path = self.vault / relative; path.parent.mkdir(parents=True, exist_ok=True)
            record=self.kb.get('task',self.task['id'])
            descriptor={'kind':'task','id':record['id'],'role':kind,'task_id':record['id'],'project_id':record['project_ids'][0]}
            envelope={'version':2,'knowledge_home':str(self.kb.home),'record':record,**descriptor}
            path.write_text('---\nloop_work: '+json.dumps(envelope)+'\n---\n'+body)
            manifest.setdefault('documents',{})[relative]=descriptor
            manifest['files'][relative] = file_hash(path); paths[name] = relative
        write_json(manifest_path, manifest)
        (self.vault / paths['missing-early']).unlink()
        listing = self.board.list(include_closed=True)
        current = next(item for item in listing['tasks'] if item['id'] == self.task['id'])
        names = {item['path'] for item in current['documents']}
        self.assertIn(paths['healthy-interim'], names)
        self.assertIn(paths['healthy-final'], names)
        warnings = listing['warnings'] + current.get('warnings', [])
        self.assertTrue(any('missing-early' in warning for warning in warnings), warnings)
        shown = self.board.show(self.task['id'], 'task')
        self.assertIn(paths['healthy-final'], {item['path'] for item in shown['documents']})
        for name in ('healthy-interim', 'healthy-final'):
            document = self.board.document(paths[name])
            self.assertFalse(document['writable']); self.assertFalse(document['fresh'])
        self.assertEqual(self.kb.get('human-request', self.request['id'])['status'], 'pending')
        self.assertEqual(self.kb.get('task', self.task['id'])['phase'], 'blocked')

    def test_bad_or_oversized_discovery_is_diagnostic_without_hiding_good_task(self):
        _, good = self.note('readable-task')
        invalid, _ = self.note('invalid-metadata')
        invalid.write_text('---\nloop_work: [broken JSON\n---\nA local note')
        oversized, _ = self.note('oversized-task')
        oversized.write_text('x' * (board_module.MAX_NOTE + 1))
        listing = self.board.list(include_closed=True)
        self.assertIn(good['id'], {item['id'] for item in listing['tasks']})
        warnings = listing['warnings'] + [warning for row in listing['tasks'] for warning in row.get('warnings', [])]
        self.assertTrue(warnings)
        bad = next((row for row in listing['tasks'] if row['id'] == 'invalid-metadata'), None)
        if bad is not None:
            self.assertFalse(bad['writable']); self.assertTrue(bad['warnings'])
        with self.assertRaises(LoopError):
            self.board.document(oversized.relative_to(self.vault).as_posix())

    def test_discovery_never_follows_linked_file_or_parent_and_rejects_traversal(self):
        outside = self.base / 'outside'; outside.mkdir()
        _, record = self.note('outside-seed')
        seed = self.vault / 'projects/vault-only-project/tasks/outside-seed/current.md'
        external = outside / 'current.md'; external.write_bytes(seed.read_bytes()); seed.unlink()
        seed.symlink_to(external)
        linked = self.vault / 'projects/vault-only-project/tasks/linked-parent'
        linked.symlink_to(outside, target_is_directory=True)
        before = external.read_bytes()
        listing = self.board.list(include_closed=True)
        ids = {item['id'] for item in listing['tasks']}
        self.assertNotIn(record['id'], ids); self.assertNotIn('linked-parent', ids)
        for path in (seed.relative_to(self.vault).as_posix(), linked.relative_to(self.vault).as_posix() + '/current.md', '../outside/current.md'):
            with self.assertRaises(LoopError):
                self.board.document(path)
        self.assertEqual(external.read_bytes(), before)

    def test_discovery_document_budget_is_bounded_and_visible(self):
        for index in range(6):
            self.note('bounded-' + str(index))
        with patch.object(board_module, 'MAX_DOCUMENTS', 2):
            listing = self.board.list(include_closed=True)
        self.assertLessEqual(len(listing['tasks']) + len(listing['requests']), 2)
        self.assertTrue(any('limit' in message.lower() for message in listing['warnings']), listing['warnings'])
