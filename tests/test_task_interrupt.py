from __future__ import annotations
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import test_work_knowledge
from test_delegation import assignment
from loop_work.delegation import Delegation
from loop_work.harness import Harness, cancellation_probe
from loop_work.orchestration import Orchestration
from loop_work.process import execute
from loop_work.storage import LoopError


class TaskInterruptTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_work_knowledge.KnowledgeTests(); self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.kb=self.fixture.kb; self.root=self.fixture.root.resolve()
        self.task=self.fixture.started(); self.harness=Harness(self.kb)
        self.harness.on('codex',task_id=self.task['id'])

    def feedback(self,task,kind,key):
        current=self.kb.get('orchestration',task['session_id'],required=False) or {'control_version':0}
        return Orchestration(self.kb).feedback(task['session_id'],{'id':key,'task_id':task['id'],'kind':kind,
            'summary':'User '+kind+' this exact task.','original_input_ref':'conversation:'+key,
            'applies_to':'This task','supersedes':[]},current['control_version'])

    def test_cancellation_is_task_scoped_and_off_is_not_inherited_from_legacy(self):
        probe=cancellation_probe(self.kb,self.task['id'])
        other=self.fixture.open_task(session=self.task['session_id'])
        self.feedback(other,'pause','pause-other')
        self.assertFalse(probe())
        self.feedback(other,'resume','resume-other')
        self.feedback(self.task,'pause','pause-current'); self.assertTrue(probe())
        self.feedback(self.task,'resume','resume-current'); self.assertTrue(probe())
        probe=cancellation_probe(self.kb,self.task['id']); self.assertFalse(probe())
        self.harness.off(self.task['session_id']); self.assertTrue(probe())
        self.assertFalse(cancellation_probe(self.kb,other['id'])())

    def test_running_worker_cancels_with_logs_and_consumed_budget_but_no_quality_rejection(self):
        marker=self.root/'worker-started'; outcome={}; errors=[]
        request=assignment('pause-worker',goal_criteria=('C1',)); request['read_paths']=['guide.md']
        command=[sys.executable,'-c',"import pathlib,time; pathlib.Path('worker-started').write_text('started'); print('started',flush=True); time.sleep(30)"]
        worker=Delegation(self.kb,self.task['id'],self.root)
        def run():
            try: outcome.update(worker.run(request))
            except BaseException as exc: errors.append(exc)
        with patch('loop_work.providers.executable_for',return_value=sys.executable),patch('loop_work.providers.command',return_value=command):
            thread=threading.Thread(target=run,daemon=True); thread.start()
            try:
                deadline=time.monotonic()+4
                while not marker.exists() and time.monotonic()<deadline: time.sleep(0.02)
                self.assertTrue(marker.exists(),errors)
                started=time.monotonic(); self.feedback(self.task,'pause','pause-live')
                thread.join(4)
                self.assertFalse(thread.is_alive(),'Task cancellation did not stop worker')
                self.assertLess(time.monotonic()-started,4)
            finally:
                if thread.is_alive():
                    self.harness.off(self.task['session_id']); thread.join(4)
        self.assertEqual(errors,[])
        value=outcome['assignment']; self.assertEqual(value['status'],'interrupted')
        self.assertTrue(value['user_cancelled']); self.assertEqual(value['attempts'],1)
        self.assertFalse(value['retry']['can_retry_same_profile']); self.assertFalse(value['retry']['can_escalate'])
        self.assertEqual(self.kb.get('worker-budget',self.task['id'])['calls'],1)
        record=self.kb.get('delegation',value['id']); self.assertNotIn('quality_failure',record)
        process=json.loads((Path(value['directory'])/'process.json').read_text())
        self.assertTrue(process['cancelled']); self.assertFalse(process['timed_out'])
        self.assertIn('started',(Path(value['directory'])/'stdout.log').read_text())
        self.feedback(self.task,'resume','resume-live')
        with self.assertRaisesRegex(LoopError,'interrupted|Recover|recover'):
            worker.run(request)
        self.assertEqual(self.kb.get('worker-budget',self.task['id'])['calls'],1)
        with self.assertRaisesRegex(LoopError,'unresolved'):
            self.fixture.work.finish(self.task['id'],self.fixture.result())
        self.assertEqual(self.kb.get('task',self.task['id'])['phase'],'working')

    def test_process_cancellation_does_not_kill_an_unrelated_process_group(self):
        import subprocess
        unrelated=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],start_new_session=True)
        self.addCleanup(lambda: (unrelated.kill(),unrelated.wait()) if unrelated.poll() is None else None)
        result=execute([sys.executable,'-c','import time; time.sleep(30)'],self.root,self.root/'logs',10,cancel=lambda:'User paused')
        self.assertTrue(result['cancelled']); self.assertFalse(result['timed_out'])
        self.assertIsNone(unrelated.poll())

    def test_rapid_pause_resume_and_off_on_cannot_revive_an_existing_call(self):
        probe=cancellation_probe(self.kb,self.task['id'])
        self.feedback(self.task,'pause','rapid-pause')
        self.feedback(self.task,'resume','rapid-resume')
        self.assertTrue(probe())
        fresh=cancellation_probe(self.kb,self.task['id']); self.assertFalse(fresh())
        self.harness.off(self.task['session_id'])
        self.harness.on('codex',task_id=self.task['id'])
        self.assertTrue(fresh())
        self.assertFalse(cancellation_probe(self.kb,self.task['id'])())

    def test_existing_cancellation_is_checked_before_a_process_is_forked(self):
        self.feedback(self.task,'pause','pause-before-fork')
        with patch('loop_work.process.subprocess.Popen',side_effect=AssertionError('must not fork')):
            result=execute([sys.executable,'-c','raise SystemExit(0)'],self.root,self.root/'prefork',5,
                           cancel=cancellation_probe(self.kb,self.task['id']))
        self.assertTrue(result['cancelled']); self.assertIsNone(result['exit_code'])

    def test_control_interrupt_arriving_on_process_exit_is_still_observed(self):
        child=MagicMock(); child.returncode=0
        with patch('loop_work.process.subprocess.Popen',return_value=child), patch('loop_work.process.terminate') as terminate:
            values=iter((None,None,'Interrupted on exit'))
            result=execute([sys.executable,'-c','pass'],self.root,self.root/'exit-race',5,cancel=lambda:next(values))
        self.assertTrue(result['cancelled']); terminate.assert_called_once_with(child,True)

    def test_generation_comparison_is_readonly_in_the_actual_accept_transaction(self):
        worker=Delegation(self.kb,self.task['id'],self.root)
        control=worker.control()
        self.harness.off(self.task['session_id']); self.harness.on('codex',task_id=self.task['id'])
        with self.kb.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            with self.assertRaisesRegex(LoopError,'generation changed'):
                worker.control(control,db=db)

    def test_common_finish_rechecks_generation_inside_its_writer_transaction(self):
        original_save=self.fixture.work.save
        def interleave(task,*args,**kwargs):
            self.harness.off(task['session_id']); self.harness.on('codex',task_id=task['id'])
            return original_save(task,*args,**kwargs)
        with patch.object(self.fixture.work,'save',side_effect=interleave):
            with self.assertRaisesRegex(LoopError,'binding was interrupted'):
                self.fixture.work.finish(self.task['id'],self.fixture.result())
        self.assertEqual(self.kb.get('task',self.task['id'])['phase'],'working')
        self.assertIsNone(self.kb.get('worker-budget',self.task['id'],required=False))

    def test_accepted_preflight_survives_off_on_and_finishes_without_reexecution(self):
        self.harness.off(self.task['session_id'])
        task=self.fixture.open_task('review')
        harness=Harness(self.kb); harness.on('codex',task_id=task['id'])
        worker=Delegation(self.kb,task['id'],self.root)
        request=assignment('accepted-preflight',goal_criteria=('goal_setting',))
        request['read_paths']=['guide.md']
        value={'status':'done','summary':'The preflight comparison has source evidence.',
            'outputs':[{'id':'explanation','content':'The guide documents cache dependencies.','evidence':['guide.md:1']}],
            'coverage':[{'criterion_id':'C1','satisfied':True,'evidence':'guide.md:1'}],
            'changes':[],'findings':[],'blockers':[]}
        with patch('loop_work.providers.executable_for',return_value=sys.executable),patch('loop_work.providers.structured_call',return_value=value) as provider:
            staged=worker.run(request)
            accepted=worker.assess(support.fixture_assessment(self.kb,staged))
            self.assertTrue(accepted['passed'])
            original=self.kb.get('delegation',accepted['assignment']['id'])
            budget=self.kb.get('worker-budget',task['id'])
            harness.off(task['session_id']); harness.on('codex',task_id=task['id'])
            self.fixture.work.define(task['id'],self.fixture.goal())
            self.fixture.work.start(task['id'])
            result=self.fixture.work.finish(task['id'],self.fixture.result())
            self.assertTrue(result['passed'])
            self.assertEqual(provider.call_count,1)
        self.assertEqual(self.kb.get('delegation',original['id']),original)
        self.assertEqual(self.kb.get('worker-budget',task['id']),budget)
        self.assertFalse(harness.status(task['session_id'])['enabled'])
        self.assertEqual(harness.status(task['session_id'])['release_reason'],'completed')


import support

class GateInterruptBoundaryTests(support.ProjectTest):
    def test_development_gate_rechecks_generation_after_review_before_commit(self):
        import loop_work.providers as providers
        self.running()
        task_id=self.engine.refresh()['work_id']; kb=self.engine.knowledge
        harness=Harness(kb); harness.on('claude',task_id=task_id)
        original=providers.review
        def interleave(*args,**kwargs):
            result=original(*args,**kwargs)
            harness.off(self.state()['session_id']); harness.on('claude',task_id=task_id)
            return result
        with patch.object(providers,'review',side_effect=interleave):
            report=self.engine.gate('M1')
        self.assertFalse(report['passed']); self.assertTrue(report['cancelled'])
        self.assertEqual(self.state()['attempts']['milestone-M1'],1)
        self.assertEqual(self.state()['milestones'],[])
        self.assertEqual(self.state()['phase'],'blocked')

    def test_plan_review_rechecks_generation_in_writer_and_cannot_grant_freeze(self):
        import loop_work.providers as providers
        task_id=self.engine.refresh()['work_id']; kb=self.engine.knowledge
        harness=Harness(kb); harness.on('claude',task_id=task_id)
        original=providers.review
        attempts_before=dict(self.state()['attempts'])
        def interleave(*args,**kwargs):
            result=original(*args,**kwargs)
            harness.off(self.state()['session_id']); harness.on('claude',task_id=task_id)
            return result
        with patch.object(providers,'review',side_effect=interleave):
            report=self.engine.plan_review()
        self.assertFalse(report['passed']); self.assertTrue(report['cancelled'])
        self.assertTrue(report['review']['passed'])
        self.assertNotIn('plan_review',self.state())
        self.assertEqual(self.state()['attempts'],attempts_before)
        path=Path(self.state()['latest_gate'])
        self.assertFalse(json.loads(path.read_text())['passed'])
        self.assertTrue((Path(report['review']['artifact']).parent/'process.json').is_file())
        with self.assertRaisesRegex(LoopError,'plan-review before freeze'):
            self.engine.freeze()


class TeamInterruptBoundaryTests(unittest.TestCase):
    def test_peer_delivery_generation_is_rechecked_in_the_team_writer_transaction(self):
        import test_team
        fixture=test_team.TeamTests(); fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.running()
        harness=Harness(fixture.kb); task=fixture.kb.get('task',fixture.task_id)
        harness.on('claude',task_id=fixture.task_id)
        plan=test_team.plan('alpha','beta')
        staged=fixture.team.run(plan)
        self.assertEqual(staged['status'],'awaiting_assessment')
        worker=fixture.team.assignment('alpha')
        fixture.team.worker.assess(support.fixture_assessment(fixture.kb,fixture.team.worker.response(worker)))
        accepted=fixture.team.assignment('alpha'); record=fixture.ledger()
        before=fixture.kb.get('team',record['id'])
        budget=fixture.kb.get('worker-budget',fixture.task_id)
        original_save=fixture.team.save
        def interleave(value):
            harness.off(task['session_id']); harness.on('claude',task_id=fixture.task_id)
            return original_save(value)
        with patch.object(fixture.team,'save',side_effect=interleave):
            with self.assertRaisesRegex(LoopError,'generation changed'):
                fixture.team.accept(record,'alpha',accepted)
        self.assertEqual(fixture.kb.get('team',record['id']),before)
        self.assertEqual(fixture.kb.get('worker-budget',fixture.task_id),budget)
