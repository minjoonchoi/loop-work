from __future__ import annotations
import copy
import json
from pathlib import Path
import tempfile
import unittest

from loop_work.board import Board
from loop_work.human import HumanDesk
from loop_work.knowledge import KnowledgeBase
from loop_work.storage import LoopError, file_hash, read_json
from loop_work.work import Work
from loop_work.wiki import WikiConflict


def setup(fixture):
    temp=tempfile.TemporaryDirectory(); fixture.addCleanup(temp.cleanup)
    fixture.base=Path(temp.name).resolve(); fixture.project=fixture.base/'인증 서비스'; fixture.project.mkdir()
    (fixture.project/'README.md').write_text('원본 API_NAME / expired / print("hello")\n')
    fixture.vault=fixture.base/'vault'; fixture.kb=KnowledgeBase(fixture.base/'data',vault_home=fixture.vault)
    fixture.work=Work(fixture.kb); fixture.task=fixture.work.open('document','권한 검사 정리','codex',[fixture.project],explicit_skill=True)['task']
    fixture.pid=fixture.task['project_ids'][0]; fixture.board=Board(fixture.kb)


def payload(wiki, operation='save-one', title='새 표시 이름', body='## 개요\n\n사용자가 쓴 내용\n'):
    return {'operation_id':operation,'expected_revision':wiki['revision'],'title':title,'body_markdown':body}


class BoardWikiTests(unittest.TestCase):
    def setUp(self): setup(self)

    def test_title_body_save_exact_vault_h1_ids_paths_and_runtime_unchanged(self):
        before=self.board.show(self.task['id'],'task',self.pid)
        source=self.vault/before['path']; pin=file_hash(source); raw=self.kb.get('task',self.task['id'])
        old=self.board.wiki('task',self.task['id'],self.pid)
        result=self.board.save_wiki('task',self.task['id'],payload(old),self.pid)
        self.assertTrue(result['saved']); self.assertEqual(result['path'],old['path'])
        text=(self.vault/result['path']).read_text()
        self.assertIn('\n# 새 표시 이름\n',text); self.assertIn('사용자가 쓴 내용',text)
        self.assertEqual(self.kb.get('task',self.task['id']),raw); self.assertEqual(file_hash(source),pin)
        row=self.board.show(self.task['id'],'task',self.pid)
        self.assertEqual(row['display_title'],'새 표시 이름'); self.assertTrue(row['writable'])
        self.assertNotIn('# 새 표시 이름',result['body_markdown'])
        self.assertTrue((self.vault/result['previous_revision_path']).is_file())

    def test_project_display_rename_does_not_change_identity_or_runtime_name(self):
        raw=self.kb.get('project',self.pid); wiki=self.board.wiki('project',self.pid,self.pid)
        result=self.board.save_wiki('project',self.pid,payload(wiki,title='사용자 프로젝트 이름'),self.pid)
        self.assertEqual(self.kb.get('project',self.pid),raw)
        project=self.board.projects(query='사용자 프로젝트',project_id=self.pid)['projects'][0]
        self.assertEqual(project['name'],raw['name']); self.assertEqual(project['display_name'],'사용자 프로젝트 이름')
        self.assertEqual(project['id'],self.pid); self.assertEqual(result['path'],wiki['path'])
        self.assertIn('# 사용자 프로젝트 이름',(self.vault/result['path']).read_text())

    def test_external_obsidian_changes_stale_cas_and_export_preservation(self):
        wiki=self.board.wiki('task',self.task['id'],self.pid); path=self.vault/wiki['path']
        text=path.read_text().replace('# 권한 검사 정리','# Obsidian에서 바꾼 이름')+'\n외부에서 보존할 문장\n'
        path.write_text(text)
        with self.assertRaises(WikiConflict):
            self.board.save_wiki('task',self.task['id'],payload(wiki),self.pid)
        self.kb.sync_vault(); self.assertEqual(path.read_text(),text)
        read=self.board.wiki('task',self.task['id'],self.pid)
        self.assertEqual(read['title'],'Obsidian에서 바꾼 이름'); self.assertIn('외부에서 보존할 문장',read['body_markdown'])
        self.assertNotEqual(read['revision'],wiki['revision'])

    def test_same_operation_exact_retry_and_conflicting_operation_content(self):
        wiki=self.board.wiki('task',self.task['id'],self.pid); request=payload(wiki)
        first=self.board.save_wiki('task',self.task['id'],request,self.pid)
        again=self.board.save_wiki('task',self.task['id'],request,self.pid)
        self.assertTrue(again['reused']); self.assertEqual(first['revision'],again['revision'])
        with self.assertRaises(WikiConflict):
            self.board.save_wiki('task',self.task['id'],{**request,'body_markdown':'다른 원문'},self.pid)
        self.assertEqual(self.board.wiki('task',self.task['id'],self.pid)['body_markdown'],request['body_markdown'])

    def test_large_unicode_same_operation_retry_preserves_receipt_and_versions(self):
        wiki=self.board.wiki('task',self.task['id'],self.pid)
        request=payload(wiki,operation='large-emoji-direct',body='😀'*100000)
        first=self.board.save_wiki('task',self.task['id'],request,self.pid)
        files={str(path.relative_to(self.base)):(file_hash(path),path.stat().st_mtime_ns,path.stat().st_ino)
               for path in self.base.rglob('*') if path.is_file()}
        again=self.board.save_wiki('task',self.task['id'],request,self.pid)
        self.assertTrue(again['reused']);self.assertEqual(again['revision'],first['revision'])
        self.assertEqual(again['body_markdown'],request['body_markdown'])
        self.assertEqual({str(path.relative_to(self.base)):(file_hash(path),path.stat().st_mtime_ns,path.stat().st_ino)
                         for path in self.base.rglob('*') if path.is_file()},files)

    def test_wiki_delete_does_not_regenerate_or_shadow(self):
        wiki=self.board.wiki('task',self.task['id'],self.pid); path=self.vault/wiki['path']; path.unlink()
        self.kb.sync_vault(); self.assertFalse(path.exists())
        with self.assertRaises(LoopError): self.board.wiki('task',self.task['id'],self.pid)
        self.assertEqual(list(path.parent.glob('작업 문서.md')),[])

    def test_wiki_does_not_restore_modified_or_removed_execution_authority(self):
        wiki=self.board.wiki('task',self.task['id'],self.pid)
        row=self.board.show(self.task['id'],'task',self.pid); source=self.vault/row['path']
        source.write_text(source.read_text()+'사람이 수정한 실행 기록\n')
        self.board.save_wiki('task',self.task['id'],payload(wiki,body='완료·승인이라고 적어도 권한은 없습니다.'),self.pid)
        self.assertFalse(self.board.show(self.task['id'],'task',self.pid)['writable'])
        source.unlink(); self.kb.sync_vault(); self.assertFalse(source.exists())
        self.assertEqual(self.board.list(project_id=self.pid)['tasks'],[])

    def test_wiki_save_does_not_change_human_question_answer_or_fingerprint(self):
        request=HumanDesk(self.kb).create(self.task['id'],{'id':'actual-question','kind':'approval','title':'원래 질문',
            'question':'API_NAME과 expired 원문을 유지합니까?','options':[],'action':None})
        wiki=self.board.wiki('task',self.task['id'],self.pid)
        self.board.save_wiki('task',self.task['id'],payload(wiki,body='승인 완료라고 쓰는 위키 본문'),self.pid)
        self.assertEqual(self.kb.get('human-request',request['id']),request)
        self.assertEqual(self.kb.get('task',self.task['id'])['phase'],'goal_setting')
        self.assertTrue(self.board.show(request['id'],project_id=self.pid)['writable'])
