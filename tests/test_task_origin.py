from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

from loop_work.engine import Engine
from loop_work.harness import Harness, explicit_skill_task
from loop_work.storage import LoopError, read_json, write_json
from loop_work.work import Work
from support import ProjectTest


SOURCE = Path(__file__).resolve().parents[1]
MARKER = {'version': 1, 'source': 'explicit_loop_work'}


class TaskOriginTests(ProjectTest):
    def test_strict_marker_rejects_malformed_and_legacy_inference(self):
        self.assertTrue(explicit_skill_task({'provenance':MARKER}))
        invalid = [None, [], 'explicit_loop_work', {}, {'version':True,'source':'explicit_loop_work'},
                   {'version':1.0,'source':'explicit_loop_work'}, {'version':2,'source':'explicit_loop_work'},
                   {'version':1,'source':'ordinary_prompt'}, {**MARKER,'extra':'not allowed'}]
        for marker in invalid:
            with self.subTest(marker=marker):
                self.assertFalse(explicit_skill_task({'provenance':marker}))
        for value in [None, [], {'harness':{'enabled':True}}, {'explicit_skill':True}]:
            self.assertFalse(explicit_skill_task(value))

    def test_same_session_mixed_common_work_binding_never_promotes(self):
        kb=self.engine.knowledge;work=Work(kb);harness=Harness(kb)
        marked=work.open('document','명시 작업','claude',[self.root],explicit_skill=True)['task']
        harness.on('claude',task_id=marked['id'])
        ordinary=work.open('document','일반 요청의 저수준 작업','claude',[self.root],marked['session_id'])['task']
        self.assertEqual(marked['session_id'],ordinary['session_id'])
        self.assertEqual(kb.get('task',marked['id'])['provenance'],MARKER)
        self.assertNotIn('provenance',ordinary)
        harness.off(marked['session_id']);harness.on('claude',task_id=ordinary['id'])
        work.context(ordinary['id']);harness.off(ordinary['session_id'])
        self.assertNotIn('provenance',kb.get('task',ordinary['id']))
        self.assertTrue(explicit_skill_task(kb.get('task',marked['id'])))

    def test_development_creation_refresh_and_terminal_preserve_origin(self):
        kb=self.engine.knowledge
        self.engine=Engine(self.root,'explicit-development',kb)
        self.engine.initialize('명시 개발 작업','claude',explicit_skill=True)
        self.fill_contract();self.running()
        task_id=self.engine.work_id()
        state=read_json(self.engine.state_path);state.pop('provenance');write_json(self.engine.state_path,state)
        self.assertEqual(self.engine.refresh()['work_id'],task_id)
        self.assertEqual(kb.get('task',task_id)['provenance'],MARKER)
        self.assertTrue(self.engine.gate('M1')['passed']);self.assertTrue(self.engine.gate()['passed'])
        self.assertEqual(kb.get('task',task_id)['provenance'],MARKER)
        self.assertEqual(kb.get('task',task_id)['phase'],'completed')

    def test_late_state_marker_and_binding_cannot_promote_existing_development(self):
        kb=self.engine.knowledge;task_id=self.engine.work_id()
        self.assertNotIn('provenance',kb.get('task',task_id))
        state=read_json(self.engine.state_path);state['provenance']=MARKER;write_json(self.engine.state_path,state)
        self.engine.refresh();Harness(kb).on('claude',task_id=task_id);self.engine.refresh()
        self.assertNotIn('provenance',kb.get('task',task_id))

    def test_invalid_creation_option_fails_before_mutation(self):
        kb=self.engine.knowledge;before=kb.list('task')
        with self.assertRaises(LoopError):Work(kb).open('document','오류 입력','claude',[self.root],explicit_skill=1)
        with self.assertRaises(LoopError):Engine(self.root,'invalid-origin',kb).initialize('오류 개발','claude',explicit_skill='true')
        self.assertEqual(kb.list('task'),before)
        self.assertFalse((self.root/'.loop/goals/invalid-origin').exists())

    def test_cli_explicit_flag_common_development_and_direct_init(self):
        kb=self.engine.knowledge
        commands=[['work','open','--kind','document','--title','일반 저수준','--provider','claude'],
                  ['work','open','--kind','document','--title','명시 일반작업','--provider','claude','--explicit-skill'],
                  ['work','open','--kind','development','--title','일반 개발','--provider','claude'],
                  ['work','open','--kind','development','--title','명시 개발','--provider','claude','--explicit-skill'],
                  ['init','cli-plain','--title','저수준 init','--implementer','claude'],
                  ['init','cli-explicit','--title','명시 init','--implementer','claude','--explicit-skill']]
        for args in commands:
            with self.subTest(command=args):
                before={row['id'] for row in kb.list('task')}
                result=subprocess.run([sys.executable,str(SOURCE/'scripts/loop.py'),'--root',str(self.root),
                    '--knowledge-home',str(kb.home),*args],capture_output=True,text=True,timeout=20)
                self.assertEqual(result.returncode,0,result.stderr)
                json.loads(result.stdout)
                created=[row for row in kb.list('task') if row['id'] not in before]
                self.assertEqual(len(created),1)
                self.assertEqual(explicit_skill_task(created[0]),'--explicit-skill' in args)
