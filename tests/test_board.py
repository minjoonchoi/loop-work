from __future__ import annotations

import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from loop_work.board import Board, MAX_NOTE
from loop_work.human import HumanDesk
from loop_work.knowledge import KnowledgeBase
from loop_work.storage import LoopError, file_hash, read_json, write_json
from loop_work.work import Work


class BoardTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve(); self.project=self.base/'project'; self.project.mkdir()
        (self.project/'source.txt').write_text('source\n')
        self.vault=self.base/'vault'; self.kb=KnowledgeBase(self.base/'kb',vault_home=self.vault)
        self.work=Work(self.kb)
        self.task=self.work.open('document','Vault-driven task','codex',[self.project],explicit_skill=True)['task']
        self.work._stop_internal(self.task['id'],'Operator confirmation required')
        self.desk=HumanDesk(self.kb)
        self.request=self.desk.create(self.task['id'],{'id':'approval-one','kind':'approval','title':'Resume task',
            'question':'Resume this exact task?','options':[],'action':'resume_task'})
        self.board=Board(self.kb)

    def metadata(self,path,change):
        lines=path.read_text().split('\n',3)
        value=json.loads(lines[1][len('loop_work: '):]); change(value)
        path.write_text('---\nloop_work: '+json.dumps(value,ensure_ascii=False)+'\n---\n'+lines[3])

    def test_actual_export_is_display_source_and_normal_approval_resume_remains_guarded(self):
        listing=self.board.list(include_closed=True)
        self.assertEqual(listing['tasks'][0]['record']['title'],'Vault-driven task')
        row=self.board.show(self.request['id'])
        self.assertTrue(row['writable'],row)
        self.assertTrue(row['fresh']); self.assertFalse(row['modified'])
        self.assertIn('Resume',row['body'])
        result=self.board.respond(row['id'],{'decision':'approve','text':'Resume the existing task.'},1,row['revision'])
        self.assertTrue(result['action_committed'])
        answered=self.board.show(row['id'])
        self.assertEqual(answered['record']['response']['text'],'Resume the existing task.')
        self.assertTrue(answered['writable'],answered)
        result=self.board.execute(row['id'],answered['record']['revision'],answered['revision'])
        self.assertTrue(result['action_committed'])
        self.assertEqual(result['request']['status'],'executed')
        self.assertEqual(self.kb.get('task',self.task['id'])['phase'],'goal_setting')
        with self.assertRaises(LoopError):
            self.board.execute(row['id'],answered['record']['revision'],answered['revision'])

    def test_obsidian_body_edits_are_rendered_but_never_authorize_mutation(self):
        row=self.board.show(self.request['id']); path=self.vault/row['path']
        path.write_text(path.read_text()+'\nUser edit from Obsidian.\n')
        current=self.board.show(row['id'])
        self.assertIn('User edit from Obsidian.',current['body'])
        self.assertTrue(current['modified']); self.assertFalse(current['writable'])
        with self.assertRaisesRegex(LoopError,'오래되었거나 수정'):
            self.board.respond(row['id'],{'decision':'approve','text':'Approve'},1,current['revision'])
        self.assertEqual(self.kb.get('human-request',row['id'])['status'],'pending')

    def test_forged_metadata_even_reowned_pin_cannot_override_runtime_identity_or_scope(self):
        row=self.board.show(self.request['id']); path=self.vault/row['path']; original=path.read_bytes()
        manifest_path=self.kb.home/'vault-owned.json'; original_manifest=manifest_path.read_bytes()
        changes=(lambda meta:meta['record'].update(title='Forged title'),
                 lambda meta:meta['record'].update(question='Different question'),
                 lambda meta:meta['record'].update(options=['Forged option']),
                 lambda meta:meta['record'].update(task_id='another-task'),
                 lambda meta:meta.update(knowledge_home=str(self.base/'foreign-kb')))
        for change in changes:
            with self.subTest(change=change):
                path.write_bytes(original); manifest_path.write_bytes(original_manifest)
                self.metadata(path,change)
                manifest=read_json(manifest_path); manifest['files'][row['path']]=file_hash(path); write_json(manifest_path,manifest)
                current=self.board.show(row['id'])
                self.assertFalse(current['writable'])
                with self.assertRaises(LoopError):
                    self.board.respond(row['id'],{'decision':'approve','text':'Approve'},1,current['revision'])
                self.assertEqual(self.kb.get('human-request',row['id'])['status'],'pending')

    def test_task_and_request_hashes_are_bound_and_atomic_prewrite_recheck_blocks_edits(self):
        row=self.board.show(self.request['id']); task=self.board.show(self.task['id'],'task')
        path=self.vault/task['path']; original=path.read_bytes()
        path.write_text(path.read_text()+'\nChanged task scope prose.\n')
        self.assertFalse(self.board.show(row['id'])['writable'])
        with self.assertRaises(LoopError):
            self.board.respond(row['id'],{'decision':'approve','text':'Approve'},1,row['revision'])
        path.write_bytes(original)
        original_current=HumanDesk._current
        def interleave(instance,*args):
            value=original_current(instance,*args)
            path.write_text(path.read_text()+'\nChanged between check and commit.\n')
            return value
        with patch.object(HumanDesk,'_current',autospec=True,side_effect=interleave):
            with self.assertRaises(LoopError):
                self.board.respond(row['id'],{'decision':'approve','text':'Approve'},1,row['revision'])
        self.assertEqual(self.kb.get('human-request',row['id'])['status'],'pending')

    def test_database_only_tasks_are_not_silently_substituted_for_vault_documents(self):
        task=self.board.show(self.task['id'],'task')
        manifest=read_json(self.kb.home/'vault-owned.json')
        for name in list(manifest['files']):
            if manifest.get('documents',{}).get(name,{}).get('role')=='current':
                del manifest['files'][name]
        write_json(self.kb.home/'vault-owned.json',manifest)
        # A DB record without any vault document remains invisible.
        (self.vault/task['path']).unlink()
        self.assertEqual(self.board.list(include_closed=True)['tasks'],[])
        self.assertFalse(self.board.show(self.request['id'])['writable'])
        foreign=KnowledgeBase(self.base/'foreign',vault_home=self.vault)
        self.assertEqual(Board(foreign).list()['requests'],[])

    def test_manifest_paths_symlinks_size_and_malformed_metadata_are_read_only(self):
        row=self.board.show(self.request['id']); path=self.vault/row['path']; original=path.read_bytes()
        outside=self.base/'private.txt'; outside.write_text('private')
        path.unlink(); path.symlink_to(outside)
        self.assertFalse(self.board.list(include_closed=True)['requests'])
        with self.assertRaises(LoopError):
            self.board.document('../private.txt')
        path.unlink(); path.write_bytes(b'x'*(MAX_NOTE+1))
        self.assertFalse(self.board.list(include_closed=True)['requests'])
        path.write_text('---\nloop_work: invalid json\n---\nA user edited note\n')
        self.assertFalse(self.board.show(row['id'])['writable'])
        self.assertIn('user edited',self.board.show(row['id'])['body'])
        path.write_bytes(original)

    def test_interim_final_documents_are_read_from_managed_vault_and_never_write_authority(self):
        task=self.board.show(self.task['id'],'task')
        interim=[item for item in task['documents'] if item.get('role')=='interim']
        self.assertTrue(interim)
        document=self.board.document(interim[0]['path'])
        self.assertIn('과거 문서',document['warnings'][0]); self.assertFalse(document['writable'])
        path=self.vault/interim[0]['path']; path.write_text(path.read_text()+'\nHistorical note edit.\n')
        current=self.board.document(interim[0]['path'])
        self.assertIn('Historical note edit.',current['body']); self.assertTrue(current['modified'])

    def test_identical_multi_project_replicas_do_not_remove_task_or_approval(self):
        second=self.base/'second-project'; second.mkdir()
        location=self.kb.attach(second)
        task=self.kb.get('task',self.task['id'])
        task['project_ids']=sorted(set(task['project_ids']+[location['project_id']]))
        task['locations']=sorted(set(task['locations']+[location['id']]))
        self.kb.put('task',task); self.kb.sync_vault()
        row=self.board.show(self.task['id'],'task')
        copies=[item for item in row['documents'] if item.get('role')=='current']
        self.assertEqual(len(copies),2)
        self.assertEqual(len(self.board.list()['tasks']),1)
        self.assertTrue(self.board.show(self.request['id'])['writable'])
        path=self.vault/copies[1]['path']
        path.write_text(path.read_text()+'\nConflicting copy.\n')
        self.assertFalse(self.board.show(self.request['id'])['writable'])

    def test_committed_response_reports_export_failure_without_replaying_action(self):
        row=self.board.show(self.request['id'])
        with patch('loop_work.vault.VaultExporter.export',side_effect=LoopError('User note export conflict')):
            result=self.board.respond(row['id'],{'decision':'approve','text':'Approve once'},1,row['revision'])
        self.assertTrue(result['action_committed'])
        self.assertTrue(result['vault_status']['errors'])
        self.assertEqual(self.kb.get('human-request',row['id'])['status'],'answered')
        with self.assertRaises(LoopError):
            self.board.respond(row['id'],{'decision':'approve','text':'Do not replay'},1,row['revision'])

    def test_unavailable_optional_history_does_not_hide_current_task(self):
        task=self.board.show(self.task['id'],'task')
        interim=next(item for item in task['documents'] if item.get('role')=='interim')
        (self.vault/interim['path']).unlink()
        current=self.board.show(self.task['id'],'task')
        self.assertEqual(current['record']['id'],self.task['id'])
        self.assertTrue(current['body'])
        self.assertTrue(current['warnings'])
