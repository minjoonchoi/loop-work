"""Real helper subprocess/loopback lifetime without native UI or user records."""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
from loop_work import board_service as service
from loop_work.knowledge import KnowledgeBase
from loop_work.storage import LoopError

class DesktopLifecycleTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.base=Path(temp.name).resolve()
        self.kb=KnowledgeBase(self.base/'kb',vault_home=self.base/'vault')
        self.addCleanup(self.stop)
    def stop(self):
        try:service.stop(self.kb)
        except LoopError:pass
    def helper(self,*extra):
        root=Path(__file__).resolve().parents[1]
        env={**os.environ,'HOME':str(self.base/'home'),'LOOP_KB_HOME':str(self.kb.home),'PYTHONDONTWRITEBYTECODE':'1'}
        command=[sys.executable,'-B',str(root/'scripts/loop.py'),'--knowledge-home',str(self.kb.home),'board','_desktop','--vault',str(self.kb.vault_home),*extra]
        child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env=env)
        self.addCleanup(lambda:child.poll() is None and self.finish(child))
        self.assertTrue(select.select([child.stdout],[],[],18)[0],'helper readiness timeout')
        line=child.stdout.readline()
        if not line:
            code=child.wait(timeout=5);errors=child.stderr.read().decode(errors='replace')
            self.fail('helper exited before descriptor: exit='+str(code)+' stderr='+errors)
        return child,json.loads(line)
    def finish(self,child):
        child.stdin.close();child.stdin=None
        output,errors=child.communicate(timeout=12)
        return child.returncode,output,errors
    def test_created_backend_is_stopped_by_pipe_eof_without_tasks(self):
        child,value=self.helper();self.assertTrue(value['owned']);self.assertEqual(self.kb.list('task'),[])
        self.assertNotIn(value['url'],str(child.args));self.assertNotIn(value['instance_nonce'],str(child.args))
        self.assertEqual(service.status(self.kb)['instance_nonce'],value['instance_nonce'])
        code,_,_=self.finish(child);self.assertEqual(code,0);self.assertEqual(service.status(self.kb)['status'],'stopped')
    def test_reused_cli_backend_survives_app_helper_eof(self):
        original=service.start(self.kb);child,value=self.helper();self.assertFalse(value['owned'])
        self.assertEqual(self.finish(child)[0],0);self.assertEqual(service.status(self.kb)['instance_nonce'],original['instance_nonce'])
        self.assertEqual(service.status(self.kb)['status'],'running')
    def test_replacement_instance_cannot_be_stopped_by_old_helper(self):
        child,value=self.helper();service.stop(self.kb,expected_instance_nonce=value['instance_nonce'])
        replacement=service.start(self.kb)
        self.assertNotEqual(replacement['instance_nonce'],value['instance_nonce'])
        code,_,_=self.finish(child);self.assertNotEqual(code,0)
        self.assertEqual(service.status(self.kb)['instance_nonce'],replacement['instance_nonce'])
        with self.assertRaises(LoopError):service.stop(self.kb,expected_instance_nonce=value['instance_nonce'])
        self.assertEqual(service.status(self.kb)['status'],'running')
    def test_target_root_uses_existing_custom_project_without_task_creation(self):
        project=self.base/'target';project.mkdir();self.kb.attach(project,project_id=None)
        original=self.kb.attach(project)['project_id']
        child,value=self.helper('--target-root',str(project))
        self.assertEqual(self.kb.list('task'),[])
        self.assertEqual(service.status(self.kb,project_id=original)['instance_nonce'],value['instance_nonce'])
        self.assertEqual(self.finish(child)[0],0)
    def test_owned_startup_timeout_reaps_actual_child_and_does_not_stop_reused_backend(self):
        from unittest.mock import patch
        spawned=[];original=subprocess.Popen
        def capture(*args,**kwargs):
            child=original(*args,**kwargs);spawned.append(child);return child
        with patch.object(service.subprocess,'Popen',side_effect=capture):
            with self.assertRaises(LoopError):service.start(self.kb,readiness_timeout=0,cleanup_on_failure=True)
        self.assertEqual(len(spawned),1);self.assertIsNotNone(spawned[0].poll())
        self.assertEqual(service.status(self.kb)['status'],'failed')
        active=service.start(self.kb)
        reused=service.start(self.kb,readiness_timeout=0,cleanup_on_failure=True)
        self.assertTrue(reused['reused']);self.assertEqual(reused['instance_nonce'],active['instance_nonce'])
