from pathlib import Path
import os
import unittest
from unittest.mock import patch

import test_board_wiki
from loop_work.storage import LoopError
from loop_work.wiki import WikiConflict


class WikiDocumentTests(unittest.TestCase):
    def setUp(self): test_board_wiki.setup(self)

    def test_initial_korean_sections_real_content_source_and_no_export_overwrite(self):
        wiki=self.board.wiki('task',self.task['id'],self.pid)
        for text in ('## 개요','권한 검사 정리','## 관련 문서','진행 현황'):
            self.assertIn(text,wiki['body_markdown'])
        path=self.vault/wiki['path']; original=path.read_bytes()
        task=self.kb.get('task',self.task['id']); task['title']='나중 목표 제목'; self.kb.put('task',task)
        self.assertEqual(path.read_bytes(),original)
        self.assertEqual(self.board.wiki('task',self.task['id'],self.pid)['path'],wiki['path'])

    def test_wiki_heading_escapes_markup_and_retains_original_display_title(self):
        from loop_work.writing import plain
        for index,title in enumerate(('[원문](https://example.invalid) <tag> #제목','*'*200)):
            wiki=self.board.wiki('task',self.task['id'],self.pid)
            result=self.board.save_wiki('task',self.task['id'],test_board_wiki.payload(wiki,'safe-heading-'+str(index),title=title),self.pid)
            self.assertIn('\n# '+plain(title)+'\n',(self.vault/result['path']).read_text())
            self.assertEqual(self.board.wiki('task',self.task['id'],self.pid)['title'],title)

    def test_new_task_wiki_summarizes_real_goal_result_and_blocker_once(self):
        from loop_work.writing import plain
        self.kb.vault_home=None
        task=self.work.open('document','목표와 결과가 있는 작업','codex',[self.project],explicit_skill=True)['task']
        task.update(phase='blocked',reason='현재 차단: <원본> *오류*',
                    goal={'outcome':'사용자가 [실제 목표]를 이해한다'},
                    result={'summary':'관찰된 결과 #1을 정리했다'})
        self.kb.put('task',task); self.kb.vault_home=self.vault; self.kb.sync_vault()
        wiki=self.board.wiki('task',task['id'],self.pid)
        for label,value in [('목표',task['goal']['outcome']),('결과',task['result']['summary']),('남은 장애',task['reason'])]:
            self.assertIn('**'+label+':** '+plain(value),wiki['body_markdown'])
        self.assertIn('작성 당시의 기록',wiki['body_markdown'])
        self.assertIn('[진행 현황]',wiki['body_markdown'])
        self.assertNotIn('> #',wiki['body_markdown'])
        path=self.vault/wiki['path']; path.write_text(path.read_text()+'\n사용자가 남긴 별도 분석\n'); edited=path.read_bytes()
        task['goal']['outcome']='새로 합의한 목표'; task['result']['summary']='이후 결과'; self.kb.put('task',task)
        self.assertEqual(path.read_bytes(),edited)
        self.assertIn('사용자가 남긴 별도 분석',self.board.wiki('task',task['id'],self.pid)['body_markdown'])

    def test_symlink_fifo_and_tampered_identity_are_not_editable(self):
        wiki=self.board.wiki('task',self.task['id'],self.pid); path=self.vault/wiki['path']; original=path.read_bytes()
        external=self.base/'outside.md'; external.write_text('외부 파일 보존')
        path.unlink(); path.symlink_to(external)
        with self.assertRaises(LoopError): self.board.wiki('task',self.task['id'],self.pid)
        self.assertEqual(external.read_text(),'외부 파일 보존')
        path.unlink(); os.mkfifo(path)
        with self.assertRaises(LoopError): self.board.wiki('task',self.task['id'],self.pid)
        path.unlink(); path.write_bytes(original.replace(self.task['id'].encode(),b'foreign-task'))
        with self.assertRaises(LoopError): self.board.wiki('task',self.task['id'],self.pid)

    def test_external_write_between_read_and_publish_is_restored_with_revision_evidence(self):
        wiki=self.board.wiki('task',self.task['id'],self.pid); path=self.vault/wiki['path']; original=path.read_text()
        rename=os.rename
        def external_before_rename(*args,**kwargs):
            path.write_text(original+'\n경쟁한 외부 문장\n')
            return rename(*args,**kwargs)
        with patch('loop_work.wiki.os.rename',side_effect=external_before_rename):
            with self.assertRaises(WikiConflict):
                self.board.save_wiki('task',self.task['id'],test_board_wiki.payload(wiki),self.pid)
        self.assertIn('경쟁한 외부 문장',path.read_text())
        backups=list((path.parent/'.loop-work-revisions').glob('*.md'))
        self.assertTrue(backups); self.assertTrue(any('경쟁한 외부 문장' in p.read_text() for p in backups))
        latest=self.board.wiki('task',self.task['id'],self.pid)
        saved=self.board.save_wiki('task',self.task['id'],test_board_wiki.payload(latest,'merge-explicit',body=latest['body_markdown']+'\n명시적 병합'),self.pid)
        self.assertTrue(saved['saved']); self.assertIn('경쟁한 외부 문장',saved['body_markdown'])

    def test_external_recreation_during_publication_is_not_overwritten(self):
        wiki=self.board.wiki('task',self.task['id'],self.pid); path=self.vault/wiki['path']; original=path.read_text()
        rename=os.rename
        def external_after_rename(*args,**kwargs):
            result=rename(*args,**kwargs); path.write_text(original+'\n외부 재생성 파일\n'); return result
        with patch('loop_work.wiki.os.rename',side_effect=external_after_rename):
            with self.assertRaises(WikiConflict):
                self.board.save_wiki('task',self.task['id'],test_board_wiki.payload(wiki),self.pid)
        self.assertIn('외부 재생성 파일',path.read_text())
        self.assertTrue(any(p.read_text()==original for p in (path.parent/'.loop-work-revisions').glob('*.md')))

    def test_external_edit_after_publication_is_conflict_with_independent_draft(self):
        wiki=self.board.wiki('task',self.task['id'],self.pid); path=self.vault/wiki['path']
        submitted='제출한 독립 초안 원문'; external='게시 직후 Obsidian 외부 원문'
        link=os.link
        def edit_after_publish(*args,**kwargs):
            result=link(*args,**kwargs)
            if args[1]==path.name:
                path.write_text(path.read_text()+'\n'+external)
            return result
        with patch('loop_work.wiki.os.link',side_effect=edit_after_publish):
            with self.assertRaises(WikiConflict):
                self.board.save_wiki('task',self.task['id'],test_board_wiki.payload(wiki,body=submitted),self.pid)
        self.assertIn(external,path.read_text())
        revisions=list((path.parent/'.loop-work-revisions').glob('*.md'))
        self.assertTrue(any(submitted in p.read_text() and external not in p.read_text() for p in revisions))
        self.assertEqual(list((self.kb.home/'wiki-operations').glob('*.json')),[])

    def test_short_wiki_links_live_source_without_copying_execution_snapshot(self):
        from urllib.parse import unquote
        import re
        wiki=self.board.wiki('task',self.task['id'],self.pid); path=self.vault/wiki['path']; initial=path.read_bytes()
        self.assertIn('처음 작성한 시각',wiki['body_markdown'])
        self.assertNotIn('- [ ]',wiki['body_markdown'])
        self.assertNotIn('**상태:**',wiki['body_markdown'])
        self.assertNotIn('> # ',wiki['body_markdown'])
        self.assertLess(len(wiki['body_markdown']),600)
        self.assertNotIn('## 결과와 참고 사항',wiki['body_markdown'])
        self.assertNotIn('## 작업 기록',wiki['body_markdown'])
        link=re.search(r'\[진행 현황\]\(<([^>]+)>\)',wiki['body_markdown']).group(1)
        current=(path.parent/unquote(link)).resolve()
        from support import use_fake_routing
        use_fake_routing(self,self.base)
        self.work.define(self.task['id'],{'outcome':'실제 권한 검사 지식을 설명한다','deliverable':'근거가 있는 권한 문서',
            'criteria':[{'id':'C1','description':'허용과 거절을 구분한다'}],'open_questions':[],'decisions':[]})
        self.assertIn('실제 권한 검사 지식을 설명한다',current.read_text())
        self.assertIn('허용과 거절을 구분한다',current.read_text())
        self.assertEqual(path.read_bytes(),initial)
        self.work.start(self.task['id'])
        finished=self.work.finish(self.task['id'],{'summary':'허용·거절의 실제 차이를 문서로 확인했다',
            'outputs':['conversation:권한결과'], 'checks':[{'criterion_id':'C1','satisfied':True,'evidence':'README.md 실제 내용 대조'}]})
        self.assertTrue(finished['passed'])
        self.assertIn('허용·거절의 실제 차이를 문서로 확인했다',current.read_text())
        self.assertIn('README.md 실제 내용 대조',current.read_text())
        self.assertIn('conversation:권한결과',current.read_text())
        self.assertEqual(path.read_bytes(),initial)
        path.write_text(path.read_text()+'\n사용자 별도 기록')
        edited=path.read_bytes(); self.kb.sync_vault(); self.assertEqual(path.read_bytes(),edited)
        path.unlink(); self.kb.sync_vault(); self.assertFalse(path.exists())

    def test_large_unicode_and_worst_escaped_bodies_retry_without_mutation(self):
        from loop_work.wiki import MAX_WIKI
        for operation,body in [('emoji-large','😀'*100000),('control-limit','\x01'*(MAX_WIKI-4096))]:
            with self.subTest(operation=operation):
                wiki=self.board.wiki('task',self.task['id'],self.pid)
                payload=test_board_wiki.payload(wiki,operation,body=body)
                first=self.board.save_wiki('task',self.task['id'],payload,self.pid)
                def versions():
                    return {str(p.relative_to(self.base)):(p.read_bytes(),p.stat().st_mtime_ns) for parent in (self.vault,self.kb.home/'wiki-operations') for p in parent.rglob('*') if p.is_file()}
                before=versions()
                retry=self.board.save_wiki('task',self.task['id'],payload,self.pid)
                self.assertTrue(retry['reused']);self.assertEqual(retry['body_markdown'],body)
                self.assertEqual(retry['revision'],first['revision']);self.assertEqual(versions(),before)

    def test_json_unicode_escaping_does_not_change_valid_receipt_identity(self):
        import json
        from loop_work.vault import read_export_json
        wiki=self.board.wiki('task',self.task['id'],self.pid)
        payload=test_board_wiki.payload(wiki,'escaped-emoji',body='😀'*100000)
        first=self.board.save_wiki('task',self.task['id'],payload,self.pid)
        receipt=next((self.kb.home/'wiki-operations').glob('*.json'))
        receipt.write_text(json.dumps(json.loads(receipt.read_text()),ensure_ascii=True))
        self.assertGreater(receipt.stat().st_size,2*1024*1024)
        with self.assertRaises(LoopError):read_export_json(receipt)
        before=receipt.read_bytes();mtime=receipt.stat().st_mtime_ns
        retry=self.board.save_wiki('task',self.task['id'],payload,self.pid)
        self.assertTrue(retry['reused']);self.assertEqual(retry['revision'],first['revision'])
        self.assertEqual(receipt.read_bytes(),before);self.assertEqual(receipt.stat().st_mtime_ns,mtime)

    def test_encoded_receipt_capacity_is_checked_before_publication(self):
        wiki=self.board.wiki('task',self.task['id'],self.pid);path=self.vault/wiki['path']
        before=path.read_bytes();mtime=path.stat().st_mtime_ns
        with patch('loop_work.wiki.MAX_WIKI_RECEIPT',1):
            with self.assertRaises(LoopError):self.board.save_wiki('task',self.task['id'],test_board_wiki.payload(wiki),self.pid)
        self.assertEqual(path.read_bytes(),before);self.assertEqual(path.stat().st_mtime_ns,mtime)
        self.assertEqual(list((self.kb.home/'wiki-operations').glob('*.json')),[])
