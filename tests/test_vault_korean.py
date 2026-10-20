from __future__ import annotations
import copy
import json
from pathlib import Path
import tempfile
import unittest
import unicodedata
from loop_work.knowledge import KnowledgeBase
from loop_work.storage import LoopError, file_hash, write_json
from loop_work.vault_layout import slug, validate_relative, validate_document_path
from loop_work.writing import task_document


class KoreanVaultTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.base = Path(temp.name).resolve(); self.vault = self.base / 'vault'
        self.kb = KnowledgeBase(self.base/'kb',vault_home=self.vault)
        self.task = dict(id='task-a',title='로그인 오류 원인 조사',kind='document',phase='working',session_id='s',project_ids=['project-a'],goal={'outcome':'Keep literal API /login English'},result=None)
        self.kb.put('project',dict(id='project-a',name='인증 서비스'))

    def manifest(self):
        return json.loads((self.kb.home/'vault-owned.json').read_text())

    def primary(self):
        return self.vault/self.manifest()['paths']['task:project-a:task-a']

    def test_korean_labels_unicode_frozen_names_and_literal_source(self):
        self.kb.put('task',self.task)
        path=self.primary(); text=path.read_text()
        self.assertIn('인증 서비스--project-a/tasks/로그인 오류 원인 조사--task-a/현재-',str(path))
        self.assertIn('**상태:** 진행 중',text); self.assertIn('Keep literal API /login English',text)
        self.assertIn('## 내보내기 범위',text)
        self.assertIn('**State:** In progress',task_document(self.task))
        metadata=json.loads(text.splitlines()[1][11:]); self.assertEqual(metadata['record'],self.task)
        self.assertEqual(metadata['role'],'current'); self.assertEqual(metadata['version'],2)
        self.kb.put('task',{**self.task,'title':'새 제목'})
        self.kb.put('project',dict(id='project-a',name='변경된 프로젝트'))
        self.kb.sync_vault()
        self.assertEqual(self.primary(),path); self.assertIn('# 새 제목',path.read_text())
        indexes=[self.vault/p for p,d in self.manifest()['documents'].items() if d['role']=='index']
        self.assertTrue(any('로그인 오류 원인 조사' in p.name for p in indexes))
        self.assertTrue(all('탐색용' in p.read_text() for p in indexes))

    def test_slug_normalization_bounds_collisions_and_path_rejection(self):
        self.assertEqual(slug('한글','a'),slug(unicodedata.normalize('NFD','한글'),'a'))
        self.assertNotEqual(slug('동일','a'),slug('동일','b'))
        name=slug('../\\😀'*300,'a'); self.assertLessEqual(len(name.encode()),184)
        self.assertNotIn('/',name); self.assertNotIn('\\',name)
        for value in ('../outside.md','/absolute.md','x//a.md','x/./a.md','x/../a.md','x\\a.md'):
            with self.subTest(value=value), self.assertRaises(LoopError): validate_relative(value)

    def seed_legacy(self, owned=True):
        path=self.vault/'projects/project-a/tasks/task-a/current.md'; path.parent.mkdir(parents=True)
        path.write_text('Existing legacy document')
        if owned:
            write_json(self.kb.home/'vault-owned.json',dict(version=1,vault=str(self.vault),files={str(path.relative_to(self.vault)):file_hash(path)}))
        return path

    def test_legacy_managed_path_and_v1_envelope_preserved_with_readable_index(self):
        path=self.seed_legacy(); self.kb.put('task',self.task)
        self.assertEqual(self.primary(),path)
        self.assertEqual(json.loads(path.read_text().splitlines()[1][11:])['version'],1)
        path.write_text('Human correction'); self.kb.put('task',{**self.task,'title':'새 제목'})
        self.assertEqual(path.read_text(),'Human correction')
        self.assertFalse(list(self.vault.rglob('현재-*.md')))
        self.assertTrue(list(self.vault.rglob('*--task-a.md')))
        path.unlink(); self.kb.sync_vault(); self.assertFalse(path.exists())
        self.assertFalse(list(self.vault.rglob('현재-*.md')))
        self.assertTrue(self.kb.vault_status()['errors'])

    def test_manifest_missing_legacy_user_file_cannot_be_bypassed(self):
        path=self.seed_legacy(False); self.kb.put('task',self.task)
        self.assertEqual(path.read_text(),'Existing legacy document'); self.assertEqual(self.primary(),path)
        self.assertFalse(list(self.vault.rglob('현재-*.md')))
        self.assertNotIn(str(path.relative_to(self.vault)),self.manifest()['files'])
        self.assertTrue(self.kb.vault_status()['errors'])

    def test_topics_follow_actual_scope_and_frozen_summary_path(self):
        for key,scope in [('topic-a','project'),('topic-g','global'),('topic-s','session')]:
            topic=dict(id=key,summary='참조 경계 보존',scope=scope,project_id='project-a',kind='finding',status='confirmed',recorded_at='2026-10-21',evidence=[])
            self.kb.put('topic',topic)
            path=self.manifest()['paths']['topic:'+key]
            if scope=='global': self.assertTrue(path.startswith('topics/global/'))
            elif scope=='project': self.assertTrue(path.startswith('projects/인증 서비스--project-a/topics/'))
            else: self.assertIn('/topics/session/',path)
            self.assertIn('참조 경계 보존--'+key,path)
            self.kb.put('topic',{**topic,'summary':'수정된 요약'})
            self.assertEqual(self.manifest()['paths']['topic:'+key],path)
            self.assertIn('# 수정된 요약',(self.vault/path).read_text())

    def test_corrupt_frozen_path_cannot_write_outside_or_other_identity(self):
        self.kb.put('task',self.task)
        original=self.primary().read_bytes()
        for bad in ('../outside.md','projects/인증 서비스--other/tasks/다른작업--other/현재-다른작업--other.md'):
            manifest=self.manifest(); manifest['paths']['task:project-a:task-a']=bad
            write_json(self.kb.home/'vault-owned.json',manifest)
            self.kb.export_vault('task','task-a')
            self.assertTrue(self.kb.vault_status()['errors']); self.assertFalse((self.base/'outside.md').exists())
        self.assertEqual(next(self.vault.rglob('현재-*.md')).read_bytes(),original)

    def test_exact_metadata_types_and_path_identity(self):
        self.kb.put('task',self.task); path=self.primary()
        meta=json.loads(path.read_text().splitlines()[1][11:]); relative=str(path.relative_to(self.vault))
        self.assertEqual(validate_document_path(relative,meta),relative)
        for field,value in [('version',2.0),('task_id','other'),('kind','topic'),('project_id','other')]:
            bad=copy.deepcopy(meta); bad[field]=value
            with self.subTest(field=field), self.assertRaises(LoopError): validate_document_path(relative,bad)

    def test_localized_views_preserve_useful_fields_and_neutral_interrupt(self):
        from loop_work.writing import delegation_document, topic_document
        task={**self.task,'kind':'development','execution_phase':'running','progress':'4/5','goal':{'target':{'outcome':'literal goal'}},'notes':[{'text':'literal finding','evidence':'literal source'}],'last_result':{'checks':[{'criterion_id':'c','satisfied':True,'evidence':'literal check'}]}}
        text=task_document(task,language='ko')
        for literal in ('literal goal','4/5','literal finding','literal source','literal check','실행 중','개발'):
            self.assertIn(literal,text)
        record=dict(id='d',status='interrupted',provider='codex',attempts=2,root='/literal/root',directory='/literal/evidence',summary='literal summary',error='literal error',applied=['literal change'],request=dict(id='a',instruction='literal instruction',read_paths=['literal read'],write_paths=[],prohibited=['literal prohibition'],deliverables=[dict(id='out',description='literal output')],criteria=[dict(id='c',description='literal criterion')]))
        text=delegation_document(record,language='ko')
        for literal in ('codex','2','/literal/root','/literal/evidence','literal summary','literal error','literal change','literal instruction','literal read','literal prohibition','literal output','literal criterion','중단됨'):
            self.assertIn(literal,text)
        self.assertNotIn('사용자 중단',text)
        self.assertIn('사용자 중단',delegation_document({**record,'user_cancelled':True},language='ko'))
        topic=dict(id='topic',summary='literal summary',status='confirmed',scope='global',kind='finding',recorded_at='literal time',details=[str(i) for i in range(7)])
        text=topic_document(topic,language='ko'); self.assertIn('literal time',text); self.assertIn('2개 항목이 더 있습니다',text)
        self.assertNotIn('more in the linked',text)

    def test_old_topic_unowned_and_removed_files_stay_canonical(self):
        path=self.vault/'topics/topic-a.md'; path.parent.mkdir(parents=True); path.write_text('User topic note')
        topic=dict(id='topic-a',summary='의미 있는 주제',scope='project',project_id='project-a',kind='finding',status='confirmed',recorded_at='today')
        self.kb.put('topic',topic)
        self.assertEqual(path.read_text(),'User topic note')
        self.assertEqual(self.manifest()['paths']['topic:topic-a'],'topics/topic-a.md')
        self.assertFalse([p for p in self.vault.rglob('*--topic-a.md') if not p.name.startswith('색인-')])
        self.assertTrue(self.kb.vault_status()['errors'])

    def test_changed_or_deleted_snapshot_is_not_rewritten_or_silently_cleared(self):
        self.kb.put('task',self.task)
        manifest=self.manifest(); histories=[p for p,d in manifest['documents'].items() if d['role']=='interim']
        snapshot=self.vault/histories[0]; snapshot.write_text('Human historical annotation')
        self.kb.sync_vault(); self.assertEqual(snapshot.read_text(),'Human historical annotation'); self.assertTrue(self.kb.vault_status()['errors'])
        snapshot.unlink(); self.kb.sync_vault(); self.assertFalse(snapshot.exists()); self.assertTrue(self.kb.vault_status()['errors'])

    def test_mapping_cannot_alias_another_logical_document(self):
        self.kb.put('task',self.task)
        self.kb.put('task',{**self.task,'id':'task-b','title':'다른 작업'})
        manifest=self.manifest(); a=manifest['paths']['task:project-a:task-a']; b=manifest['paths']['task:project-a:task-b']; original=(self.vault/b).read_bytes()
        manifest['paths']['task:project-a:task-a']=b
        write_json(self.kb.home/'vault-owned.json',manifest)
        self.kb.export_vault('task','task-a')
        self.assertTrue(self.kb.vault_status()['errors']); self.assertEqual((self.vault/b).read_bytes(),original); self.assertTrue((self.vault/a).is_file())

    def test_unowned_legacy_conflict_then_delete_cannot_acquire_ownership(self):
        path=self.seed_legacy(False); self.kb.put('task',self.task)
        self.assertTrue(self.kb.vault_status()['errors']); path.unlink()
        self.kb.export_vault('task',self.task['id'])
        self.assertFalse(path.exists()); self.assertFalse(list(self.vault.rglob('현재-*.md')))
        self.assertNotIn(str(path.relative_to(self.vault)),self.manifest()['files'])
        self.assertTrue(self.kb.vault_status()['errors'])

    def test_lost_inventory_and_removed_current_does_not_create_replacement(self):
        self.kb.put('task',self.task); old=self.primary(); old.unlink()
        (self.kb.home/'vault-owned.json').unlink()
        self.kb.put('task',{**self.task,'title':'삭제 후 변경된 제목'})
        self.assertFalse(old.exists()); self.assertFalse(list(self.vault.rglob('현재-*.md')))
        self.assertTrue(self.kb.vault_status()['errors'])

    def test_index_prefixed_topic_summary_is_valid_and_roles_remain_distinct(self):
        for scope in ('project','global'):
            topic=dict(id='topic-'+scope,summary='색인-갱신 규칙',scope=scope,project_id='project-a',kind='finding',status='confirmed',recorded_at='today')
            self.kb.put('topic',topic)
            self.assertEqual(self.kb.vault_status()['errors'],[])
            manifest=self.manifest(); canonical=manifest['paths']['topic:'+topic['id']]; index=manifest['paths']['index:topic:'+topic['id']]
            self.assertNotEqual(canonical,index)
            self.assertEqual(manifest['documents'][canonical]['role'],'topic'); self.assertEqual(manifest['documents'][index]['role'],'index')

    def test_indexes_do_not_link_missing_conflicted_or_unexported_current(self):
        self.kb.put('task',self.task); path=self.primary(); path.unlink()
        # A committed task not yet exported cannot acquire an active index link.
        with self.kb.connection() as db:
            other={**self.task,'id':'task-unexported','title':'아직 내보내지 않은 작업'}
            encoded=json.dumps(other,ensure_ascii=False)
            db.execute('INSERT INTO records(kind,id,body) VALUES(?,?,?)',('task',other['id'],encoded))
        self.kb.export_vault('task',self.task['id'])
        for name,meta in self.manifest()['documents'].items():
            if meta['role']=='index':
                body=(self.vault/name).read_text().split('\n---\n',1)[1]
                self.assertNotIn('](<',body)
                self.assertIn('확인 불가',body)

    def test_topic_index_scope_matches_record_and_rejects_foreign_project(self):
        topic=dict(id='topic-scoped',summary='범위 검증',scope='project',project_id='project-a',kind='finding',status='confirmed',recorded_at='today')
        self.kb.put('topic',topic); manifest=self.manifest(); index=manifest['paths']['index:topic:'+topic['id']]
        meta=json.loads((self.vault/index).read_text().splitlines()[1][11:])
        self.assertEqual(meta['kind'],'topic'); self.assertEqual(meta['project_id'],'project-a')
        foreign=index.replace('인증 서비스--project-a','다른 프로젝트--foreign')
        manifest['paths']['index:topic:'+topic['id']]=foreign
        write_json(self.kb.home/'vault-owned.json',manifest)
        self.kb.export_vault('topic',topic['id'])
        self.assertTrue(self.kb.vault_status()['errors']); self.assertFalse((self.vault/foreign).exists())

    def test_empty_sync_or_other_fresh_vault_does_not_claim_lost_inventory(self):
        self.assertEqual(self.kb.sync_vault()['records_considered'],0)
        self.kb.put('task',self.task); old=self.primary(); old_bytes=old.read_bytes()
        (self.kb.home/'vault-owned.json').unlink()
        fresh=self.base/'explicit-new-vault'
        other=KnowledgeBase(self.kb.home,vault_home=fresh)
        result=other.sync_vault()
        self.assertEqual(result['errors'],[])
        self.assertTrue(list(fresh.rglob('현재-*.md')))
        self.assertEqual(old.read_bytes(),old_bytes)

    def test_same_target_dotdot_alias_cannot_replace_lost_inventory(self):
        self.kb.put('task',self.task); original=self.primary(); original.unlink()
        (self.kb.home/'vault-owned.json').unlink()
        offline=KnowledgeBase(self.kb.home,vault_home=False)
        offline.put('task',{**self.task,'title':'별칭으로 변경한 제목'})
        other=self.base/'other'; other.mkdir()
        alias=other/'..'/'vault'
        replay=KnowledgeBase(self.kb.home,vault_home=alias)
        result=replay.sync_vault()
        self.assertTrue(result['errors']); self.assertFalse(original.exists())
        self.assertFalse(list(self.vault.rglob('현재-*.md')))
        self.assertFalse((self.kb.home/'vault-owned.json').exists())

    def test_guard_normalization_does_not_hide_symlink_components(self):
        self.kb.put('task',self.task)
        other=self.base/'other'; outside=self.base/'outside'; outside.mkdir()
        other.symlink_to(outside,target_is_directory=True)
        alias=other/'..'/'vault'
        replay=KnowledgeBase(self.kb.home,vault_home=alias)
        result=replay.sync_vault()
        self.assertTrue(result['errors']); self.assertIn('symlink',' '.join(result['errors']).lower())
        self.assertEqual(list(outside.iterdir()),[])

    def test_fresh_dotdot_alias_indexes_link_owned_task_and_topic(self):
        other=self.base/'other'; other.mkdir()
        alias=other/'..'/'fresh-vault'
        kb=KnowledgeBase(self.base/'fresh-kb',vault_home=alias)
        kb.put('project',{'id':'project-a','name':'한국어 프로젝트'})
        kb.put('task',self.task)
        for scope in ('project','global'):
            kb.put('topic',dict(id='alias-'+scope,summary='한국어 지식 경로',scope=scope,project_id='project-a',kind='finding',status='confirmed',recorded_at='today'))
        self.assertEqual(kb.vault_status()['errors'],[])
        manifest=json.loads((kb.home/'vault-owned.json').read_text())
        for name,meta in manifest['documents'].items():
            if meta['role']=='index':
                body=(alias/name).read_text().split('\n---\n',1)[1]
                self.assertIn('](<',body); self.assertNotIn('확인 불가',body)

    def test_topic_mapping_scope_directory_and_depth_are_exact(self):
        for scope in ('global','project','checkout','session','task'):
            key='scope-'+scope
            topic=dict(id=key,summary='지식 범위 '+scope,scope=scope,project_id='project-a',kind='finding',status='confirmed',recorded_at='today')
            self.kb.put('topic',topic); self.assertEqual(self.kb.vault_status()['errors'],[])
            manifest=self.manifest(); canonical=manifest['paths']['topic:'+key]; index=manifest['paths']['index:topic:'+key]
            for name in (canonical,index):
                meta=json.loads((self.vault/name).read_text().splitlines()[1][11:])
                self.assertEqual(validate_document_path(name,meta),name)
                parts=name.split('/')
                if scope=='global':
                    wrong='/'.join(['topics','task',parts[-1]])
                elif scope=='project':
                    wrong='/'.join(parts[:-1]+['session',parts[-1]])
                else:
                    wrong='/'.join(parts[:-2]+['project',parts[-1]])
                with self.subTest(scope=scope,path=wrong), self.assertRaises(LoopError):
                    validate_document_path(wrong,meta)
            # Exercise the actual exporter with a corrupted persisted canonical or index mapping.
            logical=('topic:'+key) if scope=='global' else ('index:topic:'+key)
            original=manifest['paths'][logical]; parts=original.split('/')
            wrong='/'.join(['topics','task',parts[-1]]) if scope=='global' else '/'.join(parts[:-1]+['session',parts[-1]])
            manifest['paths'][logical]=wrong; write_json(self.kb.home/'vault-owned.json',manifest)
            self.kb.export_vault('topic',key)
            self.assertTrue(self.kb.vault_status()['errors']); self.assertFalse((self.vault/wrong).exists())
            manifest['paths'][logical]=original; write_json(self.kb.home/'vault-owned.json',manifest)
            self.kb.sync_vault(); self.assertEqual(self.kb.vault_status()['errors'],[])
