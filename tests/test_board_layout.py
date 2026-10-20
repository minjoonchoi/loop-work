"""Readable vault paths retain metadata identity and legacy document authority."""
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
        self.task=self.work.open('document','승인할 작업 이름','codex',[self.project])['task']
        self.work._stop_internal(self.task['id'],'사람 확인이 필요합니다.')
        self.task=self.kb.get('task',self.task['id']); self.board=Board(self.kb)

    def manifest(self):
        return read_json(self.kb.home/'vault-owned.json')

    def legacy(self, identifier=None, record=None, owned=True):
        record=record or self.task; identifier=identifier or record['id']
        project=record['project_ids'][0]
        name='projects/'+project+'/tasks/'+identifier+'/current.md'
        path=self.vault/name; path.parent.mkdir(parents=True,exist_ok=True)
        meta={'version':1,'kind':'task','id':identifier,'knowledge_home':str(self.kb.home),'record':record}
        path.write_text('---\nloop_work: '+json.dumps(meta,ensure_ascii=False)+'\n---\n기존 문서 본문\n')
        if owned:
            manifest=self.manifest(); manifest['files'][name]=file_hash(path); write_json(self.kb.home/'vault-owned.json',manifest)
        return name

    def test_new_unicode_paths_approval_and_historical_navigation(self):
        row=self.board.show(self.task['id'],'task')
        self.assertIn('승인할 작업 이름--',row['path']); self.assertIn('/현재-',row['path'])
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

    def test_legacy_and_new_unrelated_tasks_visible_but_same_task_unowned_replica_blocks(self):
        other=copy.deepcopy(self.task); other['id']='legacy-only-task'; other['title']='기존 작업'
        self.kb.put('task',other)
        manifest=self.manifest()
        for name,entry in list(manifest.get('documents',{}).items()):
            if entry['id']==other['id']:
                (self.vault/name).unlink(missing_ok=True); manifest['files'].pop(name,None); manifest['documents'].pop(name)
        write_json(self.kb.home/'vault-owned.json',manifest)
        self.legacy(record=other)
        tasks={row['id']:row for row in self.board.list(include_closed=True)['tasks']}
        self.assertTrue(tasks[self.task['id']]['writable']); self.assertTrue(tasks[other['id']]['writable'])
        old=self.legacy(owned=False)
        (self.vault/old).write_text((self.vault/old).read_text()+'사람의 변경\n')
        self.assertFalse(self.board.show(self.task['id'],'task')['writable'])

    def test_optional_layout_inventory_traversal_and_role_forgery_do_not_grant_authority(self):
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
        with self.assertRaisesRegex(LoopError,'Unknown managed'):
            self.board.show(task['id'],'task')
        self.assertFalse((self.vault/first).exists())
        self.assertTrue(self.kb.vault_status()['errors'])
        canonical=[name for name,entry in self.manifest()['documents'].items() if entry['role']=='current' and entry['id']==task['id']]
        self.assertEqual(canonical,[first])

    def test_existing_v1_canonical_and_edited_note_cannot_be_migrated_or_shadowed(self):
        kb=KnowledgeBase(self.base/'legacy-data')
        work=Work(kb); task=work.open('document','기존 문서','codex',[self.project])['task']
        vault=self.base/'legacy-vault'; kb.vault_home=vault
        name='projects/'+task['project_ids'][0]+'/tasks/'+task['id']+'/current.md'
        path=vault/name; path.parent.mkdir(parents=True)
        meta={'version':1,'kind':'task','id':task['id'],'knowledge_home':str(kb.home),'record':task}
        path.write_text('---\nloop_work: '+json.dumps(meta,ensure_ascii=False)+'\n---\n기존 본문\n')
        write_json(kb.home/'vault-owned.json',{'version':1,'vault':str(vault),'files':{name:file_hash(path)}})
        kb.sync_vault(); board=Board(kb)
        self.assertEqual(board.show(task['id'],'task')['path'],name)
        self.assertEqual(json.loads(path.read_text().splitlines()[1][len('loop_work: '):])['version'],1)
        path.write_text(path.read_text()+'사람이 수정한 지식\n'); edited=path.read_bytes()
        (kb.home/'vault-owned.json').unlink()
        task['title']='가독 이름으로 변경'; kb.put('task',task)
        self.assertEqual(path.read_bytes(),edited)
        rows=board.list(include_closed=True)['tasks']
        self.assertTrue(rows); self.assertFalse(any(row['writable'] for row in rows))
        self.assertFalse((kb.home/'vault-owned.json').exists())
        self.assertFalse(list(vault.rglob('현재-*.md')))
        self.assertTrue(kb.vault_status()['errors'])

    def test_frozen_mapping_foreign_task_identity_cannot_preserve_writable_view(self):
        row=self.board.show(self.task['id'],'task')
        manifest=self.manifest()
        manifest['paths']['task:'+self.task['project_ids'][0]+':foreign-task']=row['path']
        write_json(self.kb.home/'vault-owned.json',manifest)
        current=self.board.show(self.task['id'],'task')
        self.assertFalse(current['writable'])
        self.assertTrue(current['modified'])
