"""Readable v3 vault paths preserve source identity and human edit boundaries."""
from __future__ import annotations
import copy
import json
from pathlib import Path
import tempfile
import unittest

from loop_work.board import Board
from loop_work.human import HumanDesk
from loop_work.knowledge import KnowledgeBase
from loop_work.storage import LoopError, file_hash, read_json, write_json
from loop_work.vault_layout import slug
from loop_work.work import Work


class BoardLayoutTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(); self.addCleanup(temporary.cleanup)
        self.base=Path(temporary.name).resolve(); self.project=self.base/'한글 프로젝트'; self.project.mkdir()
        (self.project/'입력.txt').write_text('원본 입력\n')
        self.vault=self.base/'vault'; self.kb=KnowledgeBase(self.base/'data',vault_home=self.vault)
        self.work=Work(self.kb)
        self.task=self.work.open('document','승인할 작업 이름','codex',[self.project],explicit_skill=True)['task']
        self.work._stop_internal(self.task['id'],'사람 확인이 필요합니다.')
        self.task=self.kb.get('task',self.task['id']); self.board=Board(self.kb)

    def manifest(self):
        return read_json(self.kb.home/'vault-owned.json')

    def test_new_unicode_paths_approval_and_historical_navigation(self):
        row=self.board.show(self.task['id'],'task')
        self.assertIn('승인할 작업 이름--',row['path']); self.assertTrue(row['path'].endswith('/진행 현황.md'))
        self.assertTrue(row['writable'],row)
        snapshots=[item for item in row['documents'] if item.get('role')=='interim']
        self.assertTrue(snapshots,row)
        historical=self.board.document(snapshots[0]['path'])
        self.assertEqual(historical['role'],'interim'); self.assertFalse(historical['writable'])
        request=HumanDesk(self.kb).create(self.task['id'],{'id':'request-one','kind':'approval','title':'원래 승인 질문',
            'question':'이 작업만 재개할까요?','options':[],'action':'resume_task'})
        wrapper=self.board.show(request['id']); self.assertTrue(wrapper['writable'],wrapper)
        receipt=self.board.respond(request['id'],{'decision':'approve','text':'이 작업만 승인합니다.'},1,wrapper['vault_revision'])
        self.assertTrue(receipt['action_committed'])
        answered=self.board.show(request['id'])
        result=self.board.execute(request['id'],answered['record']['revision'],answered['vault_revision'])
        self.assertEqual(result['request']['status'],'executed')

    def test_unmanaged_unicode_discovery_is_readonly_and_foreign_metadata_rejected(self):
        row=self.board.show(self.task['id'],'task'); path=self.vault/row['path']
        (self.kb.home/'vault-owned.json').unlink()
        found=self.board.show(self.task['id'],'task')
        self.assertEqual(found['body'],row['body']); self.assertFalse(found['writable'])
        lines=path.read_text().split('\n',3); meta=json.loads(lines[1][len('loop_work: '):]); meta['task_id']='foreign-task'
        path.write_text('---\nloop_work: '+json.dumps(meta,ensure_ascii=False)+'\n---\n'+lines[3])
        listing=self.board.list(include_closed=True)
        self.assertFalse(listing['tasks']); self.assertTrue(listing['warnings'])

    def test_old_paths_are_ignored_and_preserved_without_alias_support(self):
        row=self.board.show(self.task['id'],'task')
        old=self.vault/'projects'/self.task['project_ids'][0]/'tasks'/self.task['id']/'current.md'
        old.parent.mkdir(parents=True)
        meta={'version':1,'kind':'task','id':self.task['id'],'knowledge_home':str(self.kb.home),'record':self.task}
        old.write_text('---\nloop_work: '+json.dumps(meta,ensure_ascii=False)+'\n---\n사람이 보존할 기존 원문\n')
        before=old.read_bytes()
        self.assertTrue(self.board.show(self.task['id'],'task')['writable'])
        with self.assertRaises(LoopError): self.board.document(old.relative_to(self.vault).as_posix())
        self.assertEqual(old.read_bytes(),before)
        (self.vault/row['path']).unlink()
        self.assertEqual(self.board.list(include_closed=True)['tasks'],[])
        self.assertEqual(old.read_bytes(),before)

    def test_required_layout_inventory_traversal_and_role_forgery_do_not_grant_authority(self):
        original=self.manifest(); row=self.board.show(self.task['id'],'task')
        for bad in ('../outside.md','/absolute.md'):
            with self.subTest(path=bad):
                manifest=copy.deepcopy(original); manifest.setdefault('paths',{})['bad-key']=bad
                write_json(self.kb.home/'vault-owned.json',manifest)
                current=self.board.show(self.task['id'],'task')
                self.assertFalse(current['writable'])
        manifest=copy.deepcopy(original); manifest['documents'][row['path']]['role']='human-request'
        write_json(self.kb.home/'vault-owned.json',manifest)
        listed=self.board.list(include_closed=True)
        self.assertFalse(any(item['writable'] for item in listed['tasks']))

    def test_title_changes_keep_path_and_missing_current_preserves_absence(self):
        first=self.board.show(self.task['id'],'task')['path']
        task=self.kb.get('task',self.task['id']); task['title']='달라진 작업 제목'
        self.kb.put('task',task)
        changed=self.board.show(task['id'],'task')
        self.assertEqual(changed['path'],first); self.assertTrue(changed['writable'])
        (self.vault/first).unlink()
        task['title']='복구할 작업 제목'; self.kb.put('task',task)
        with self.assertRaisesRegex(LoopError,'등록된 문서'):
            self.board.show(task['id'],'task')
        self.assertFalse((self.vault/first).exists())
        self.assertTrue(self.kb.vault_status()['errors'])
        canonical=[name for name,entry in self.manifest()['documents'].items() if entry['role']=='current' and entry['id']==task['id']]
        self.assertEqual(canonical,[first])

    def test_only_layout3_and_envelope3_can_authorize_current_document(self):
        original=self.manifest(); row=self.board.show(self.task['id'],'task')
        path=self.vault/row['path']; original_text=path.read_text()
        for version in (None,1,2):
            with self.subTest(layout_version=version):
                manifest=copy.deepcopy(original)
                if version is None: manifest.pop('layout_version')
                else: manifest['layout_version']=version
                write_json(self.kb.home/'vault-owned.json',manifest)
                self.assertFalse(self.board.show(self.task['id'],'task')['writable'])
        write_json(self.kb.home/'vault-owned.json',original)
        for version in (1,2):
            with self.subTest(envelope_version=version):
                lines=original_text.split('\n',3)
                meta=json.loads(lines[1][len('loop_work: '):]); meta['version']=version
                path.write_text('---\nloop_work: '+json.dumps(meta,ensure_ascii=False)+'\n---\n'+lines[3])
                self.assertFalse(self.board.show(self.task['id'],'task')['writable'])
        path.write_text(original_text)
        self.assertTrue(self.board.show(self.task['id'],'task')['writable'])

    def test_frozen_mapping_foreign_task_identity_cannot_preserve_writable_view(self):
        row=self.board.show(self.task['id'],'task')
        manifest=self.manifest()
        manifest['paths']['task:'+self.task['project_ids'][0]+':foreign-task']=row['path']
        write_json(self.kb.home/'vault-owned.json',manifest)
        current=self.board.show(self.task['id'],'task')
        self.assertFalse(current['writable'])
        self.assertTrue(current['modified'])
