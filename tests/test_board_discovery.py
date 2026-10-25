"""Vault-only discovery and partial history failures stay readable, never authoritative."""
from pathlib import Path
import hashlib
import json
import unittest
from unittest.mock import patch

import test_board
from loop_work.vault_layout import slug
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
        envelope = {'version': 3, 'kind': 'task', 'id': identifier, 'role':'current',
                    'task_id':identifier, 'project_id':'vault-only-project',
                    'knowledge_home': str(self.kb.home), 'record': record}
        path = self.vault / '프로젝트' / slug('알 수 없는 프로젝트','vault-only-project') / '작업' / slug(record['title'],identifier) / '진행 현황.md'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('---\nloop_work: ' + json.dumps(envelope) + '\n---\n' + body)
        return path, record

    def test_unowned_vault_only_task_with_forged_marker_is_hidden_but_preserved(self):
        path, record = self.note('vault-only-one')
        record['provenance']={'version':1,'source':'explicit_loop_work'}
        test_board.BoardTests.metadata(self,path,lambda meta:meta.update(record=record))
        before=path.read_bytes()
        self.assertNotIn(record['id'],{row['id'] for row in self.board.list(include_closed=True)['tasks']})
        with self.assertRaises(LoopError):self.board.show(record['id'],'task')
        with self.assertRaises(LoopError):self.board.document(path.relative_to(self.vault).as_posix())
        self.assertEqual(path.read_bytes(),before)
        self.assertIsNone(self.kb.get('task',record['id'],required=False))

    def test_no_manifest_does_not_promote_vault_only_tasks(self):
        path,record=self.note('vault-only-complete',phase='completed',body='# Personal note')
        before=path.read_bytes();manifest=self.kb.home/'vault-owned.json';manifest.unlink()
        listing=self.board.list(include_closed=True)
        self.assertNotIn(record['id'],{row['id'] for row in listing['tasks']})
        self.assertTrue(all(not row['writable'] for row in listing['tasks']+listing['requests']))
        with self.assertRaises(LoopError):self.board.show(record['id'],'task')
        self.assertEqual(path.read_bytes(),before);self.assertFalse(manifest.exists())
        self.assertIsNone(self.kb.get('task',record['id'],required=False))
        original=self.kb.get('human-request',self.request['id'])
        with self.assertRaises(LoopError):self.board.respond(self.request['id'],{'decision':'approve','text':'Not authority'},original['revision'],'no-vault-authority')
        self.assertEqual(self.kb.get('human-request',self.request['id']),original)

    def test_missing_history_does_not_hide_healthy_interim_or_final_documents(self):
        task = self.board.show(self.task['id'], 'task')
        parent = Path(task['path']).parent
        manifest_path = self.kb.home / 'vault-owned.json'; manifest = read_json(manifest_path)
        paths = {}
        for kind, name, body in (('interim', 'missing-early', 'Lost historical note'),
                                 ('interim', 'healthy-interim', '# Observed partial result'),
                                 ('final', 'healthy-final', '# Historical completion claim only')):
            relative = (parent / '기록' / {'interim':'중간','final':'완료'}[kind] / ('날짜미상-' + {'interim':'중간','final':'완료'}[kind] + '-' + hashlib.sha256(name.encode()).hexdigest()[:20] + '.md')).as_posix()
            path = self.vault / relative; path.parent.mkdir(parents=True, exist_ok=True)
            record=self.kb.get('task',self.task['id'])
            descriptor={'kind':'task','id':record['id'],'role':kind,'task_id':record['id'],'project_id':record['project_ids'][0]}
            envelope={'version':3,'knowledge_home':str(self.kb.home),'record':record,**descriptor}
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
        self.assertTrue(any(paths['missing-early'] in warning for warning in warnings), warnings)
        shown = self.board.show(self.task['id'], 'task')
        self.assertIn(paths['healthy-final'], {item['path'] for item in shown['documents']})
        for name in ('healthy-interim', 'healthy-final'):
            document = self.board.document(paths[name])
            self.assertFalse(document['writable']); self.assertFalse(document['fresh'])
        self.assertEqual(self.kb.get('human-request', self.request['id'])['status'], 'pending')
        self.assertEqual(self.kb.get('task', self.task['id'])['phase'], 'blocked')

    def test_bad_or_oversized_discovery_does_not_promote_unknown_or_hide_eligible_task(self):
        _,unknown=self.note('unknown-task')
        bad=self.work.open('document','Explicit malformed document','codex',[self.project],explicit_skill=True)['task']
        row=self.board.show(bad['id'],'task');oversized=self.vault/row['path']
        oversized.write_text('x'*(board_module.MAX_NOTE+1))
        listing=self.board.list(include_closed=True)
        self.assertIn(self.task['id'],{row['id'] for row in listing['tasks']})
        self.assertNotIn(unknown['id'],{row['id'] for row in listing['tasks']})
        self.assertTrue(listing['warnings'])
        with self.assertRaises(LoopError):self.board.document(row['path'])

    def test_discovery_never_follows_linked_file_or_parent_and_rejects_traversal(self):
        outside = self.base / 'outside'; outside.mkdir()
        seed, record = self.note('outside-seed')
        external = outside / 'current.md'; external.write_bytes(seed.read_bytes()); seed.unlink()
        seed.symlink_to(external)
        linked = seed.parent.parent / slug('링크된 부모','linked-parent')
        linked.symlink_to(outside, target_is_directory=True)
        before = external.read_bytes()
        listing = self.board.list(include_closed=True)
        ids = {item['id'] for item in listing['tasks']}
        self.assertNotIn(record['id'], ids); self.assertNotIn('linked-parent', ids)
        for path in (seed.relative_to(self.vault).as_posix(), linked.relative_to(self.vault).as_posix() + '/진행 현황.md', '../outside/current.md'):
            with self.assertRaises(LoopError):
                self.board.document(path)
        self.assertEqual(external.read_bytes(), before)

    def test_discovery_document_budget_is_bounded_and_visible(self):
        for index in range(6):
            self.work.open('document','Bounded '+str(index),'codex',[self.project],explicit_skill=True)
        with patch.object(board_module, 'MAX_DOCUMENTS', 2):
            listing = self.board.list(include_closed=True)
        self.assertLessEqual(len(listing['tasks']) + len(listing['requests']), 2)
        self.assertEqual(listing['warnings'], ['일부 문서를 읽을 수 없거나 확인할 수 없습니다.'])
