import os
import json
import sys
from unittest.mock import patch
from pathlib import Path
import subprocess
import tempfile
import unittest
from scripts import install
from loop_work.storage import LoopError


class LauncherTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        self.base=Path(temp.name).resolve();self.home=self.base/'home';self.home.mkdir();self.project=self.base/'target';self.project.mkdir()

    def test_user_launcher_runs_from_other_cwd_and_uninstall_preserves_data(self):
        install.install_links(self.home)
        launcher=self.home/'.local/bin/loop-work';self.assertTrue(os.access(launcher,os.X_OK))
        before=launcher.stat().st_mtime_ns;install.install_links(self.home);self.assertEqual(launcher.stat().st_mtime_ns,before)
        result=subprocess.run([str(launcher),'--knowledge-home',str(self.base/'kb'),'board','status','--vault',str(self.base/'vault')],cwd=self.project,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr);self.assertIn('stopped',result.stdout)
        user=self.base/'vault/keep.md';user.parent.mkdir(exist_ok=True);user.write_text('private note')
        install.uninstall_links(self.home)
        self.assertFalse(launcher.exists());self.assertEqual(user.read_text(),'private note');self.assertTrue((self.base/'kb/knowledge.sqlite3').is_file())

    def test_target_launcher_stays_local_and_foreign_launchers_are_preserved(self):
        install.install_links(self.home,self.project)
        launcher=self.project/'.loop/bin/loop-work';self.assertTrue(os.access(launcher,os.X_OK));self.assertFalse((self.home/'.local/bin').exists())
        launcher.write_text('user edit')
        with self.assertRaises(LoopError):install.install_links(self.home,self.project)
        with self.assertRaises(LoopError):install.uninstall_links(self.home,self.project)
        self.assertEqual(launcher.read_text(),'user edit')

    def test_unowned_and_symlink_cli_conflicts_precede_any_install_write(self):
        binary=self.home/'.local/bin/loop-work';binary.parent.mkdir(parents=True);binary.write_text('unowned')
        with self.assertRaises(LoopError):install.install_links(self.home)
        self.assertEqual(binary.read_text(),'unowned');self.assertFalse((self.home/'.agents').exists())
        binary.unlink();outside=self.base/'outside';outside.write_text('outside');binary.symlink_to(outside)
        with self.assertRaises(LoopError):install.install_links(self.home)
        self.assertEqual(outside.read_text(),'outside')

    def test_make_install_fake_home_and_generated_cli_real_lifecycle(self):
        source=Path(__file__).resolve().parents[1]
        binaries=self.base/'fake-bin';binaries.mkdir()
        wrapper=binaries/'python3'
        wrapper.write_text('#!'+sys.executable+'\n'+
            'import runpy,sys\nfrom pathlib import Path\nfrom unittest.mock import patch\n'+
            'sys.path.insert(0,'+repr(str(source))+')\nfrom scripts import setup_workspace\n'+
            'script=sys.argv.pop(1)\n'+
            'with patch.object(Path,"home",return_value=Path('+repr(str(self.home))+')), patch.object(setup_workspace,"find_obsidian",return_value="/fake/installed/Obsidian.app"):\n    runpy.run_path(script,run_name="__main__")\n')
        wrapper.chmod(0o755)
        env={**os.environ,'PATH':str(binaries)+os.pathsep+os.environ.get('PATH',''),'LOOP_KB_HOME':str(self.home/'.loop-work/data')}
        env.pop('LOOP_INSTALL_TARGET',None)
        install_run=subprocess.run(['make','install'],cwd=source,env=env,capture_output=True,text=True,timeout=180)
        self.assertEqual(install_run.returncode,0,install_run.stderr)
        if sys.platform == 'darwin':
            app=self.home/'Applications/Loop Work.app'
            self.assertTrue(os.access(app/'Contents/MacOS/LoopWork',os.X_OK))
            configuration=json.loads((app/'Contents/Resources/desktop-config.json').read_text())
            self.assertEqual(configuration['entrypoint'],str(self.home/'.local/share/loop-work/install/loop.py'))
            self.assertTrue(Path(configuration['python']).is_absolute())
        launcher=self.home/'.local/bin/loop-work';self.assertTrue(os.access(launcher,os.X_OK))
        self.assertIn('PATH is unchanged',install_run.stdout)
        argv=[str(launcher),'--knowledge-home',str(self.base/'cli-kb'),'board']
        def invoke(command):
            run=subprocess.run(argv+[command,'--vault',str(self.base/'cli-vault')],cwd=self.project,capture_output=True,text=True,timeout=180)
            self.assertEqual(run.returncode,0,run.stderr);return json.loads(run.stdout)
        first=invoke('start')
        try:
            self.assertEqual(invoke('status')['status'],'running')
            self.assertEqual(invoke('start')['instance_nonce'],first['instance_nonce'])
        finally:
            self.assertEqual(invoke('stop')['status'],'stopped')
        self.assertEqual(invoke('stop')['status'],'stopped')
        self.assertFalse((self.home/'.codex/config.toml').exists())

    def test_make_recreates_deleted_owned_launchers_executable_user_and_target(self):
        source=Path(__file__).resolve().parents[1]
        binaries=self.base/'fake-bin';binaries.mkdir()
        wrapper=binaries/'python3'
        wrapper.write_text('#!'+sys.executable+'\n'+
            'import runpy,sys\nfrom pathlib import Path\nfrom unittest.mock import patch\n'+
            'sys.path.insert(0,'+repr(str(source))+')\nfrom scripts import setup_workspace\n'+
            'script=sys.argv.pop(1)\n'+
            'with patch.object(Path,"home",return_value=Path('+repr(str(self.home))+')), patch.object(setup_workspace,"find_obsidian",return_value="/fake/installed/Obsidian.app"):\n    runpy.run_path(script,run_name="__main__")\n')
        wrapper.chmod(0o755)
        env={**os.environ,'PATH':str(binaries)+os.pathsep+os.environ.get('PATH',''),'LOOP_KB_HOME':str(self.home/'.loop-work/data')}
        env.pop('LOOP_INSTALL_TARGET',None)
        other=self.base/'other-cwd';other.mkdir()
        for target in (None,self.project):
            with self.subTest(target=target):
                command=['make','install']+(['TARGET='+str(target)] if target else [])
                def reinstall():
                    result=subprocess.run(command,cwd=source,env=env,capture_output=True,text=True,timeout=180)
                    self.assertEqual(result.returncode,0,result.stderr)
                reinstall()
                launcher=target/'.loop/bin/loop-work' if target else self.home/'.local/bin/loop-work'
                original=launcher.read_bytes();launcher.unlink();reinstall()
                self.assertEqual(launcher.read_bytes(),original)
                self.assertTrue(os.access(launcher,os.X_OK))
                result=subprocess.run([str(launcher),'--knowledge-home',str(self.base/'isolated-cli-kb'),'board','status','--vault',str(self.base/'isolated-vault')],cwd=other,env=env,capture_output=True,text=True,timeout=180)
                self.assertEqual(result.returncode,0,result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'],'stopped')
