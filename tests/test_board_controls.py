from __future__ import annotations

import copy
import unittest
from unittest.mock import patch

import test_board
from loop_work.orchestration import Orchestration, worker_context
from loop_work.storage import LoopError, digest


class BoardControlTests(unittest.TestCase):
    def setUp(self):
        test_board.BoardTests.setUp(self)
        # Direct controls do not depend on a human request.
        with self.kb.connection() as db:
            db.execute("DELETE FROM records WHERE kind='human-request'")
        self.kb.sync_vault()

    def payload(self, operation='pause-one', kind='pause', text='Stop this task now.\nKeep the existing goal.'):
        row=self.board.show(self.task['id'],'task')
        return {'operation_id':operation,'kind':kind,'text':text,
                'expected_task_revision':row['control']['task_revision'],
                'expected_control_version':row['control']['control_version'],
                'expected_vault_revision':row['vault_revision']}

    def test_direct_pause_original_text_and_explicit_feedback_resume_without_phase_resume(self):
        first=self.board.control(self.task['id'],self.payload())
        self.assertTrue(first['action_committed'])
        self.assertTrue(worker_context(self.kb,self.task['id'])['paused'])
        self.assertIn('\n',first['control']['original_text'])
        phase=self.kb.get('task',self.task['id'])['phase']
        self.board.control(self.task['id'],self.payload('resume-one','resume','Resume feedback control only.'))
        self.assertFalse(worker_context(self.kb,self.task['id'])['paused'])
        self.assertEqual(self.kb.get('task',self.task['id'])['phase'],phase)
        self.assertEqual(self.kb.list('human-request'),[])

    def test_exact_replay_no_extra_feedback_and_changed_operation_rejected(self):
        payload=self.payload(); self.board.control(self.task['id'],payload)
        before=copy.deepcopy(self.kb.list('feedback'))
        replay=self.board.control(self.task['id'],payload)
        self.assertTrue(replay['reused'])
        self.assertEqual(self.kb.list('feedback'),before)
        changed={**payload,'text':'Different original input.'}
        with self.assertRaisesRegex(LoopError,'immutable'):
            self.board.control(self.task['id'],changed)
        self.assertEqual(self.kb.list('feedback'),before)

    def test_stale_task_control_and_vault_all_reject_without_receipt(self):
        for field in ('expected_task_revision','expected_control_version','expected_vault_revision'):
            with self.subTest(field=field):
                payload=self.payload('stale-'+field)
                payload[field]=999 if field=='expected_control_version' else 'stale'
                with self.assertRaises(LoopError):
                    self.board.control(self.task['id'],payload)
        self.assertEqual(self.kb.list('board-control'),[])
        self.assertEqual(self.kb.list('feedback'),[])

    def test_edited_vault_cannot_gain_control_even_with_latest_token(self):
        row=self.board.show(self.task['id'],'task')
        path=self.vault/row['path']; path.write_text(path.read_text()+'\nUser-edited intent.\n')
        payload=self.payload()
        with self.assertRaisesRegex(LoopError,'read-only|modified'):
            self.board.control(self.task['id'],payload)
        self.assertEqual(self.kb.list('feedback'),[])

    def test_atomic_guard_rechecks_task_after_preflight(self):
        payload=self.payload()
        original=Orchestration.feedback
        def race(instance,*args,**kwargs):
            task=self.kb.get('task',self.task['id']); task['title']='Changed concurrently'
            self.kb.put('task',task)
            return original(instance,*args,**kwargs)
        with patch.object(Orchestration,'feedback',race):
            with self.assertRaisesRegex(LoopError,'Task changed'):
                self.board.control(self.task['id'],payload)
        self.assertEqual(self.kb.list('board-control'),[])
        self.assertEqual(self.kb.list('feedback'),[])

    def test_correction_and_constraint_keep_full_input_and_require_worker(self):
        for kind in ('correction','constraint'):
            self.board.control(self.task['id'],self.payload(kind,kind,'Preserve every requirement.\nInspect the exact evidence.'))
        view=worker_context(self.kb,self.task['id'])
        self.assertTrue(view['requires_worker'])
        self.assertTrue(all(item['evidence']['original_text']=='Preserve every requirement.\nInspect the exact evidence.' for item in view['feedback']))
        self.assertEqual(len(self.kb.list('board-control')),2)
        self.assertEqual(self.kb.get('task',self.task['id'])['phase'],'blocked')

    def test_postcommit_diagnostic_error_does_not_hide_receipt(self):
        original=Orchestration.feedback
        def late_failure(instance,*args,**kwargs):
            original(instance,*args,**kwargs)
            raise OSError('diagnostic publication failed after commit')
        with patch.object(Orchestration,'feedback',late_failure), patch.object(self.kb,'vault_status',side_effect=OSError('status unavailable')):
            result=self.board.control(self.task['id'],self.payload())
        self.assertTrue(result['action_committed'])
        self.assertEqual(result['vault_status']['status'],'unavailable')
        self.assertTrue(worker_context(self.kb,self.task['id'])['paused'])

    def test_http_controls_require_capability_scope_and_all_revisions(self):
        import json
        import test_board_ui
        fixture=test_board_ui.BoardUiTests(); fixture.setUp()
        try:
            row=fixture.board.show(fixture.task['id'],'task')
            payload={'operation_id':'http-pause','kind':'pause','text':'Interrupt this exact task.',
                     'expected_task_revision':row['control']['task_revision'],
                     'expected_control_version':row['control']['control_version'],
                     'expected_vault_revision':row['vault_revision']}
            endpoint='/api/tasks/'+fixture.task['id']+'/control'
            self.assertEqual(fixture.http('POST',endpoint,payload,{'X-Loop-Capability':'wrong'})[0],403)
            bad={**payload}; del bad['expected_task_revision']
            self.assertEqual(fixture.http('POST',endpoint,bad)[0],400)
            other=fixture.work.open('document','Other task','codex',[fixture.project])['task']
            self.assertNotEqual(fixture.http('POST','/api/tasks/'+other['id']+'/control',payload)[0],200)
            code,body=fixture.http('POST',endpoint,payload)
            self.assertEqual(code,200,body)
            result=json.loads(body); self.assertTrue(result['action_committed'])
            self.assertEqual(result['vault_status']['status'],'withheld')
            self.assertTrue(worker_context(fixture.kb,fixture.task['id'])['paused'])
            self.assertFalse(worker_context(fixture.kb,other['id'])['paused'])
        finally:
            fixture.doCleanups()

    def test_same_pause_text_can_be_saved_again_after_explicit_resume(self):
        self.board.control(self.task['id'],self.payload('first-pause','pause','잠시 멈춤'))
        self.board.control(self.task['id'],self.payload('explicit-resume','resume','다시 진행'))
        self.board.control(self.task['id'],self.payload('second-pause','pause','잠시 멈춤'))
        self.assertTrue(worker_context(self.kb,self.task['id'])['paused'])
        self.assertEqual(len(self.kb.list('feedback')),3)

    def test_missing_runtime_session_disables_control_without_hiding_vault_task(self):
        with self.kb.connection() as db:
            db.execute("DELETE FROM records WHERE kind='session'")
        row=self.board.list(include_closed=True)['tasks'][0]
        self.assertEqual(row['record']['id'],self.task['id'])
        self.assertFalse(row['control']['available'])
        self.assertIn('Unknown session',row['control']['block_reason'])

    def test_long_pause_remains_observable_and_explicitly_resumable(self):
        original='가'*6000
        result=self.board.control(self.task['id'],self.payload('long-pause','pause',original))
        self.assertTrue(result['action_committed'])
        self.assertEqual(result['control']['original_text'],original)
        with self.assertRaisesRegex(LoopError,'16 KiB'):
            worker_context(self.kb,self.task['id'])
        row=self.board.show(self.task['id'],'task')
        self.assertTrue(row['control']['available'],row['control'])
        self.assertTrue(row['control']['paused'])
        self.board.control(self.task['id'],self.payload('long-pause-resume','resume','원문을 보존하고 명시적으로 해제합니다.'))
        self.assertFalse(self.board.show(self.task['id'],'task')['control']['paused'])
        self.assertFalse(worker_context(self.kb,self.task['id'])['paused'])
        self.assertEqual(self.kb.get('task',self.task['id'])['phase'],'blocked')

    def test_accumulated_worker_packet_overflow_does_not_disable_manual_controls(self):
        for index in range(2):
            self.board.control(self.task['id'],self.payload('large-correction-'+str(index),'correction','나'*3000))
        with self.assertRaisesRegex(LoopError,'16 KiB'):
            worker_context(self.kb,self.task['id'])
        self.assertTrue(self.board.show(self.task['id'],'task')['control']['available'])
        self.board.control(self.task['id'],self.payload('overflow-pause','pause','패킷 한도를 유지하며 일시정지합니다.'))
        self.assertTrue(self.board.show(self.task['id'],'task')['control']['paused'])
        self.board.control(self.task['id'],self.payload('overflow-resume','resume','명시적 해제만 기록합니다.'))
        self.assertFalse(self.board.show(self.task['id'],'task')['control']['paused'])
        with self.assertRaisesRegex(LoopError,'16 KiB'):
            worker_context(self.kb,self.task['id'])
        self.assertEqual(len(self.kb.list('feedback')),4)
