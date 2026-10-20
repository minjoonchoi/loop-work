"""Ownership-loss sequences must not regain Board control or approval authority."""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest

from loop_work.board import Board
from loop_work.human import HumanDesk
from loop_work.knowledge import KnowledgeBase
from loop_work.storage import LoopError
from loop_work.work import Work


class BoardReadableOwnershipTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.base=Path(temp.name).resolve(); self.project=self.base/'보존할 프로젝트'; self.project.mkdir()
        (self.project/'README.md').write_text('실제 입력 원문\n')
        self.vault=self.base/'vault'; self.kb=KnowledgeBase(self.base/'knowledge')
        self.work=Work(self.kb)
        self.task=self.work.open('document','삭제를 존중할 작업','codex',[self.project])['task']
        self.kb.vault_home=self.vault; self.board=Board(self.kb)

    def request(self):
        return HumanDesk(self.kb).create(self.task['id'],{'id':'must-not-regain-approval','kind':'approval',
            'title':'원래 승인 질문','question':'보존된 근거만 사용합니까?','options':[],'action':None})

    def assert_no_regained_authority(self, request, absent):
        tasks=[row for row in self.board.list(include_closed=True)['tasks'] if row['id']==self.task['id']]
        try:
            approval=self.board.show(request['id'])
        except LoopError:
            approval=None
        observed={'removed_note_exists':absent.exists(),
                  'writable_current':any(row['writable'] for row in tasks),
                  'available_control':any(row.get('control',{}).get('available',False) for row in tasks),
                  'writable_approval':bool(approval and approval['writable']),
                  'friendly_current_files':[str(path.relative_to(self.vault)) for path in self.vault.rglob('현재-*.md')]}
        self.assertEqual(observed,{'removed_note_exists':False,'writable_current':False,'available_control':False,
                                   'writable_approval':False,'friendly_current_files':[]},observed)
        if approval is not None:
            with self.assertRaises(LoopError):
                self.board.respond(request['id'],{'decision':'approve','text':'권한을 복원하지 않습니다.'},request['revision'],approval['vault_revision'])
        self.assertEqual(self.kb.get('human-request',request['id']),request)
        self.assertEqual(self.kb.list('feedback'),[])

    def test_unowned_legacy_conflict_then_user_delete_cannot_become_owned(self):
        name='projects/'+self.task['project_ids'][0]+'/tasks/'+self.task['id']+'/current.md'
        legacy=self.vault/name; legacy.parent.mkdir(parents=True)
        envelope={'version':1,'kind':'task','id':self.task['id'],'knowledge_home':str(self.kb.home),'record':self.task}
        legacy.write_text('---\nloop_work: '+json.dumps(envelope,ensure_ascii=False)+'\n---\n사람이 소유한 기존 문서\n')
        first=self.kb.export_vault('task',self.task['id'])
        self.assertTrue(first['errors']); self.assertIn('사람이 소유한 기존 문서',legacy.read_text())
        request=self.request(); task_before=self.kb.get('task',self.task['id'])
        self.assertFalse(self.board.show(self.task['id'],'task')['writable'])
        legacy.unlink()
        self.kb.sync_vault()
        self.assertEqual(self.kb.get('task',self.task['id']),task_before)
        self.assert_no_regained_authority(request,legacy)

    def test_lost_manifest_deleted_current_and_new_title_cannot_create_fresh_authority(self):
        self.kb.sync_vault(); request=self.request()
        first=self.board.show(self.task['id'],'task')
        self.assertTrue(first['writable']); original=self.vault/first['path']
        (self.kb.home/'vault-owned.json').unlink(); original.unlink()
        changed=self.kb.get('task',self.task['id']); changed['title']='이름만 바꾼 같은 작업'
        self.kb.put('task',changed)
        self.kb.sync_vault()
        self.assertEqual(self.kb.get('task',self.task['id']),changed)
        self.assert_no_regained_authority(request,original)
