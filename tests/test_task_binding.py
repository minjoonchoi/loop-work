from __future__ import annotations
import json
import unittest
import test_harness
from loop_work.harness import Harness
from loop_work.orchestration import Orchestration, worker_context
from loop_work.storage import LoopError, digest


class TaskBindingTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_harness.ConversationTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.kb=self.fixture.kb; self.work=self.fixture.work; self.harness=Harness(self.kb)
        self.task=self.fixture.opened()

    def test_terminal_task_and_binding_release_commit_or_rollback_together(self):
        self.harness.on('codex',task_id=self.task['id'])
        with self.assertRaisesRegex(RuntimeError,'rollback'):
            with self.kb.connection() as db:
                db.execute('BEGIN IMMEDIATE')
                self.kb.put('task',{**self.task,'phase':'aborted'},db)
                session=json.loads(db.execute("SELECT body FROM records WHERE kind='session' AND id=?",(self.task['session_id'],)).fetchone()[0])
                self.assertFalse(session['harness']['enabled'])
                raise RuntimeError('rollback terminal transition')
        self.assertEqual(self.kb.get('task',self.task['id']),self.task)
        self.assertTrue(self.harness.status(self.task['session_id'])['enabled'])
        self.kb.put('task',{**self.task,'phase':'aborted'})
        current=self.harness.status(self.task['session_id'])
        self.assertFalse(current['enabled']); self.assertEqual(current['release_reason'],'aborted')
        with self.assertRaisesRegex(LoopError,'Terminal'):
            self.harness.on('codex',task_id=self.task['id'])

    def test_context_follows_only_explicit_binding_and_does_not_adopt_another_task(self):
        self.harness.on('codex',task_id=self.task['id'])
        other=self.fixture.opened(session_id=self.task['session_id'])
        orchestration=Orchestration(self.kb)
        current=orchestration.context(self.task['session_id'])
        self.assertEqual(current['task_id'],self.task['id'])
        self.assertEqual(current['current']['id'],self.task['id'])
        foreign=orchestration.context(self.task['session_id'],other['id'])
        self.assertFalse(foreign['enabled'])
        self.assertFalse(foreign['binding']['enabled'])
        self.assertEqual(foreign['current']['id'],other['id'])
        self.assertIn('not actively bound',foreign['next'])
        self.kb.put('task',{**self.task,'phase':'completed'})
        current=orchestration.context(self.task['session_id'])
        self.assertFalse(current['enabled']); self.assertEqual(current['task_id'],self.task['id'])
        self.assertNotEqual(current['task_id'],other['id'])

    def test_feedback_guard_and_full_board_original_share_one_transaction(self):
        text='Keep this exact interface. '+('Preserve the original user constraint. '*20)
        original={'id':'control-record','task_id':self.task['id'],'session_id':self.task['session_id'],
                  'original_text':text,'input':{'text':text}}
        payload={'id':'board-input','task_id':self.task['id'],'kind':'constraint','summary':'Preserve the exact user constraint.',
                 'original_input_ref':'board-control:control-record','applies_to':'This task','supersedes':[]}
        seen=[]
        def guard(db):
            seen.append(db.in_transaction)
            self.kb.put('board-control',original,db)
        Orchestration(self.kb).feedback(self.task['session_id'],payload,0,guard=guard)
        self.assertEqual(seen,[True])
        evidence=worker_context(self.kb,self.task['id'])['feedback'][0]['evidence']
        self.assertEqual(evidence['original_text'],text)
        self.assertEqual(evidence['sha256'],digest(original))
        before=self.kb.list('feedback')
        def reject(db): raise LoopError('guard rejected stale authority')
        with self.assertRaisesRegex(LoopError,'guard rejected'):
            Orchestration(self.kb).feedback(self.task['session_id'],{**payload,'id':'new-input'},1,guard=reject)
        self.assertEqual(self.kb.list('feedback'),before)
