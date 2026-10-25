"""Readable paths remain an identity-bound projection, not control authority."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
import unicodedata
from loop_work.knowledge import KnowledgeBase
from loop_work.storage import LoopError
from loop_work.vault_layout import (display_title,id_suffix,slug,validate_mapping,
                                    validate_metadata,validate_document_path)


class ReadableVaultLayoutTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.base=Path(tmp.name).resolve();self.vault=self.base/'vault'
        self.kb=KnowledgeBase(self.base/'kb',vault_home=self.vault)
        self.project={'id':'project-one','name':'인증 서비스'};self.kb.put('project',self.project)
        self.task={'id':'task-one','title':'로그인 오류 수정','kind':'document','phase':'working','session_id':'s',
                   'project_ids':['project-one'],'goal':{'outcome':'원래 목표'},'result':None,'updated_at':'2026-10-25T00:00:00Z'}

    def inventory(self):
        return json.loads((self.kb.home/'vault-owned.json').read_text())

    def test_short_names_keep_full_summary_and_ids_only_in_metadata(self):
        summary='이것은 문서 제목에 전부 들어가면 읽기 어려운 긴 결론이며 실제 결론 전문과 근거는 본문에서 빠짐없이 보존해야 한다.'
        topic={'id':'long-record-id-that-should-not-appear-in-the-filename','summary':summary,'kind':'finding','scope':'project',
               'project_id':'project-one','status':'confirmed','recorded_at':'2026-10-25','evidence':[]}
        self.kb.put('topic',topic);manifest=self.inventory();name=manifest['paths']['topic:'+topic['id']]
        self.assertTrue(name.startswith('프로젝트/인증 서비스--'))
        self.assertIn('/지식/',name);self.assertNotIn(topic['id'],name)
        text=(self.vault/name).read_text();self.assertIn(summary,text)
        meta=json.loads(text.splitlines()[1][11:]);self.assertEqual(meta['record'],topic);self.assertEqual(meta['version'],3)
        self.assertEqual(manifest['layout_version'],3)
        self.assertFalse(any('색인-' in name or '작업색인' in name for name in manifest['files']))
        self.assertEqual(sum(name.endswith('/목록.md') for name in manifest['files']),1)

    def test_dates_history_single_current_and_frozen_short_name(self):
        self.kb.put('task',self.task);first=self.inventory()['paths']['task:project-one:task-one']
        self.assertTrue(first.endswith('/진행 현황.md'))
        self.assertIn('로그인 오류 수정--'+id_suffix('task-one'),first)
        self.kb.put('task',{**self.task,'title':'제목을 바꾼 같은 작업','phase':'completed'})
        manifest=self.inventory();self.assertEqual(manifest['paths']['task:project-one:task-one'],first)
        histories=[name for name in manifest['files'] if '/기록/' in name]
        self.assertTrue(any('/기록/완료/2026-10-25-완료-' in name for name in histories))
        self.assertTrue(any('/기록/중간/2026-10-25-이력-001-' in name for name in histories))
        self.assertNotIn('task-one',first)

    def test_unicode_and_same_name_identity_and_short_excerpt(self):
        self.assertEqual(slug('한글','one'),slug(unicodedata.normalize('NFD','한글'),'one'))
        self.assertNotEqual(slug('같은 이름','one'),slug('같은 이름','two'))
        excerpt=display_title({'summary':'글자와 단어를 이어 쓰는 아주 긴 결론입니다. '*15})
        self.assertLessEqual(len(excerpt),48);self.assertTrue(excerpt.endswith('…'))
        self.assertLess(len(slug('😀'*300,'one').encode()),255)
        self.assertNotIn('/',slug('../escape','one'))

    def test_old_layout_and_foreign_metadata_are_rejected_without_fallback(self):
        self.kb.put('task',self.task);name=self.inventory()['paths']['task:project-one:task-one']
        meta=json.loads((self.vault/name).read_text().splitlines()[1][11:])
        for version in (1,2,3.0):
            with self.subTest(version=version):
                with self.assertRaises(LoopError):validate_metadata({**meta,'version':version})
        for wrong in ('other-project','other-task'):
            with self.assertRaises(LoopError):validate_document_path(name,{**meta,'task_id':wrong})
        with self.assertRaises(LoopError):validate_mapping('task:project-one:task-one','projects/project-one/tasks/task-one/current.md')
        with self.assertRaises(LoopError):validate_mapping('task:project-one:other-task',name)

    def test_topic_only_project_has_readable_index_and_person_owned_wiki(self):
        self.kb.put('topic',{'id':'fact','title':'참조 기준','summary':'원래 긴 결론','scope':'project','project_id':'project-one',
                             'kind':'fact','status':'confirmed','recorded_at':'2026-10-25','evidence':[]})
        manifest=self.inventory();project=manifest['paths']['project:project-one']
        self.assertTrue((self.vault/project/'프로젝트 안내.md').is_file())
        self.assertIn('지식 · 참조 기준',(self.vault/project/'목록.md').read_text())
        self.assertEqual(self.kb.list('task'),[])
