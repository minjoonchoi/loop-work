"""Installed TARGET uses one project/config for native and CLI lifecycle."""
import contextlib
import io
import json
from pathlib import Path
import socket
import unittest
from unittest.mock import patch
import test_desktop_lifecycle
from loop_work import desktop,board_service as service
from loop_work.cli import main
from loop_work.desktop_install import inspect_bundle
from loop_work.storage import read_json,write_json
from scripts.install import install_links

class TargetScopeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_desktop_lifecycle.DesktopLifecycleTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.base=self.fixture.base;self.kb=self.fixture.kb;self.root=self.base/'target';self.root.mkdir();(self.root/'source.txt').write_text('fixture')
        install_links(target=self.root);self.entry=self.root/'.loop/install/loop.py'
    def app(self):
        app=self.root/'.loop/Loop Work.app';resources=app/'Contents/Resources';resources.mkdir(parents=True);binary=app/'Contents/MacOS/LoopWork';binary.parent.mkdir();binary.write_text('fixture binary');binary.chmod(0o755);(app/'Contents/Info.plist').write_text('plist')
        import sys
        config={'version':1,'python':sys.executable,'entrypoint':str(self.entry),'knowledge_home':str(self.kb.home),'vault_home':str(self.kb.vault_home),'project_id':None,'target_root':str(self.root)}
        (resources/'desktop-config.json').write_text(json.dumps(config));manifest=read_json(self.entry.parent/'manifest.json');manifest['desktop']={'path':str(app.relative_to(self.root)),'files':inspect_bundle(app)};write_json(self.entry.parent/'manifest.json',manifest)
    def cli(self,*args):
        output=io.StringIO();errors=io.StringIO()
        with contextlib.redirect_stdout(output),contextlib.redirect_stderr(errors):code=main(['--knowledge-home',str(self.kb.home),'board',*args,'--vault',str(self.kb.vault_home)],entrypoint=str(self.entry))
        self.last_cli_error=errors.getvalue()
        return code,json.loads(output.getvalue()) if output.getvalue().strip() else None
    def cleanup_project(self,pid):
        try:service.stop(self.kb,project_id=pid)
        except Exception:pass
    def test_real_fixed_and_ephemeral_port_start_helper_reuse_and_status_stop(self):
        self.app();self.kb.put('project',{'id':'custom-project','name':'원래 이름','identity':'existing'});self.kb.attach(self.root,project_id='custom-project');self.addCleanup(self.cleanup_project,'custom-project')
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));fixed=sock.getsockname()[1]
        for port in (fixed,0):
            with self.subTest(port=port),patch('loop_work.cli.sys.platform','darwin'),patch('loop_work.desktop.open_app',return_value={'status':'opening'}) as launch:
                code,first=self.cli('start','--port',str(port));self.assertEqual(code,0);launch.assert_not_called();self.assertNotIn('url',first);self.assertEqual(service.status(self.kb,project_id='custom-project')['instance_nonce'],first['instance_nonce'])
                child,descriptor=self.fixture.helper('--target-root',str(self.root),'--project','custom-project','--port',str(port))
                self.assertFalse(descriptor['owned']);self.assertEqual(descriptor['instance_nonce'],first['instance_nonce']);self.assertEqual(self.fixture.finish(child)[0],0)
                self.assertEqual(self.cli('status')[1]['instance_nonce'],first['instance_nonce'])
                self.assertEqual(service.status(self.kb)['status'],'stopped')
                self.assertEqual(self.cli('stop')[1]['status'],'stopped')
        self.assertEqual(self.kb.list('task'),[]);self.assertEqual(self.kb.list('session'),[])
    def test_unattached_readonly_status_stop_never_touch_foreign_global_backend(self):
        self.app();foreign=service.start(self.kb)
        with self.kb.connection() as db:before=list(db.execute('SELECT kind,id,body FROM records ORDER BY kind,id'))
        for cmd in ('status','stop'):
            code,result=self.cli(cmd);self.assertEqual(code,0);self.assertEqual(result,{'status':'stopped','project_scope':'unattached'})
        with self.kb.connection() as db:self.assertEqual(list(db.execute('SELECT kind,id,body FROM records ORDER BY kind,id')),before)
        self.assertEqual(service.status(self.kb)['instance_nonce'],foreign['instance_nonce'])
    def test_foreign_explicit_project_rejected_before_start_and_backend_uses_target_scope(self):
        self.app();pid=self.kb.attach(self.root)['project_id'];self.addCleanup(self.cleanup_project,pid)
        with patch('loop_work.cli.sys.platform','darwin'),patch('loop_work.board_service.start',wraps=service.start) as start:
            self.assertNotEqual(self.cli('start','--project','foreign')[0],0);start.assert_not_called()
        with patch('loop_work.cli.sys.platform','darwin'):
            code,started=self.cli('start');self.assertEqual(code,0);self.assertEqual(self.cli('status')[1]['instance_nonce'],started['instance_nonce']);self.assertEqual(self.cli('stop')[1]['status'],'stopped')
    def test_lowlevel_target_without_app_retains_server_only_scope(self):
        with patch('loop_work.cli.sys.platform','darwin'):
            code,first=self.cli('start');self.assertEqual(code,0,self.last_cli_error)
            self.assertEqual(service.status(self.kb)['instance_nonce'],first['instance_nonce'])
            code,status=self.cli('status');self.assertEqual(code,0,self.last_cli_error)
            self.assertEqual(status['instance_nonce'],first['instance_nonce'])
            code,stopped=self.cli('stop');self.assertEqual(code,0,self.last_cli_error)
            self.assertEqual(stopped['status'],'stopped')
        self.assertEqual(self.kb.list('location'),[])

    def test_foreign_unattached_and_modified_app_cannot_fallback_to_global(self):
        self.app();foreign=service.start(self.kb)
        with patch('loop_work.cli.sys.platform','darwin'),patch('loop_work.board_service.start',wraps=service.start) as start:
            self.assertNotEqual(self.cli('start','--project','foreign')[0],0);start.assert_not_called()
        self.assertEqual(self.kb.list('location'),[])
        config=self.root/'.loop/Loop Work.app/Contents/Resources/desktop-config.json';config.write_text('null')
        for cmd in ('status','stop'):
            self.assertNotEqual(self.cli(cmd)[0],0)
        self.assertEqual(service.status(self.kb)['instance_nonce'],foreign['instance_nonce'])
    def test_backend_only_start_uses_same_target_lifecycle_scope(self):
        self.app();pid=self.kb.attach(self.root)['project_id'];self.addCleanup(self.cleanup_project,pid)
        with patch('loop_work.desktop.open_app',side_effect=AssertionError('start must not open app')):
            code,first=self.cli('start');self.assertEqual(code,0);self.assertNotIn('url',first)
            self.assertEqual(self.cli('status')[1]['instance_nonce'],first['instance_nonce']);self.assertEqual(self.cli('stop')[1]['status'],'stopped')

    def test_missing_owned_app_is_not_lowlevel_fallback(self):
        import shutil
        self.app();shutil.rmtree(self.root/'.loop/Loop Work.app')
        foreign=service.start(self.kb)
        with patch('loop_work.board_service.start',wraps=service.start) as start:
            self.assertNotEqual(self.cli('start')[0],0);start.assert_not_called()
        self.assertNotEqual(self.cli('stop')[0],0)
        self.assertEqual(service.status(self.kb)['instance_nonce'],foreign['instance_nonce'])
