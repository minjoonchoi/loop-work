import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from loop_work import desktop
from loop_work.knowledge import KnowledgeBase
from loop_work.storage import LoopError,file_hash

class DesktopTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.base=Path(temp.name).resolve();self.kb=KnowledgeBase(self.base/'kb',vault_home=self.base/'vault')
    def app(self,target=False):
        home=self.base/'home';home.mkdir(exist_ok=True);root=self.base/'project' if target else home;root.mkdir(exist_ok=True)
        entry=root/('.loop/install/loop.py' if target else '.local/share/loop-work/install/loop.py');entry.parent.mkdir(parents=True);entry.write_text('# wrapper')
        runtime=Path(desktop.__file__).resolve().parent.parent;(entry.parent/'runtime').symlink_to(runtime,target_is_directory=True)
        (entry.parent/'manifest.json').write_text(json.dumps({'version':2,'kind':'links','scope':'project' if target else 'user','root':str(root),'source':str(runtime),'files':{str(entry.relative_to(root)):file_hash(entry)}}))
        app=root/'.loop/Loop Work.app' if target else home/'Applications/Loop Work.app'
        resource=app/'Contents/Resources';resource.mkdir(parents=True);binary=app/'Contents/MacOS/LoopWork';binary.parent.mkdir();binary.write_text('binary');binary.chmod(0o755)
        (app/'Contents/Info.plist').write_text('plist')
        config={'version':1,'python':'/usr/bin/python3','entrypoint':str(entry),'knowledge_home':None,'vault_home':None,'project_id':None,'target_root':str(root) if target else None};(resource/desktop.CONFIG_NAME).write_text(json.dumps(config))
        from loop_work.desktop_install import inspect_bundle
        manifest=json.loads((entry.parent/'manifest.json').read_text());manifest['desktop']={'path':str(app.relative_to(root)),'files':inspect_bundle(app)};(entry.parent/'manifest.json').write_text(json.dumps(manifest))
        return home,entry,app,config
    def test_descriptor_rejects_remote_malformed_and_nonloopback_urls(self):
        valid={'version':1,'url':'http://127.0.0.1:1234/#private','instance_nonce':'n'*40,'owned':True};self.assertEqual(desktop.descriptor(valid),valid)
        for changed in ({'url':'https://example.com/#private'},{'url':'http://localhost:1234/#private'},{'url':'http://127.0.0.1:1234/?x=1#private'},{'url':3},{'version':True},{'owned':1},{'extra':'x'}):
            with self.subTest(changed=changed),self.assertRaises(LoopError):desktop.descriptor({**valid,**changed})
    def test_target_entry_does_not_fallback_and_source_requires_matching_owned_manifest(self):
        home,entry,app,_=self.app(target=True)
        with patch.object(Path,'home',return_value=home):
            self.assertEqual(desktop.resolve_app(entry),app)
            (app/'Contents/Resources'/desktop.CONFIG_NAME).unlink()
            with self.assertRaises(LoopError):desktop.resolve_app(entry)
        home,entry,app,_=self.app()
        with patch.object(Path,'home',return_value=home):
            self.assertEqual(desktop.resolve_app(entry),app)
            self.assertEqual(desktop.resolve_app(Path(desktop.__file__).parents[1]/'scripts/loop.py'),app)
            entry.write_text('modified')
            with self.assertRaises(LoopError):desktop.resolve_app(entry)
    def test_custom_scope_handoff_contains_no_token_and_uses_frozen_installed_entry(self):
        home,entry,app,config=self.app(target=True);captured={}
        self.kb.put('project',{'id':'p','name':'명시 프로젝트','identity':'fixture-custom-project'})
        self.kb.attach(Path(config['target_root']),project_id='p')
        original_run=desktop.subprocess.run
        def launch(argv,**kwargs):
            if argv[0] != '/usr/bin/open':
                return original_run(argv,**kwargs)
            captured['argv']=argv;path=Path(argv[-1]);captured['config']=json.loads(path.read_text());self.assertEqual(path.stat().st_mode&0o777,0o600);path.unlink();return SimpleNamespace(returncode=0)
        with patch.object(Path,'home',return_value=home),patch.object(desktop.sys,'platform','darwin'),patch.object(desktop.subprocess,'run',side_effect=launch):desktop.open_app(self.kb,session_id='s',task_id='t',project_id='p',entrypoint=entry)
        self.assertEqual(captured['config']['entrypoint'],config['entrypoint']);self.assertEqual(captured['config']['target_root'],config['target_root'])
        self.assertEqual(captured['config']['session_id'],'s');self.assertIn('-n',captured['argv'])
        self.assertNotIn('url',captured['config']);self.assertNotIn('capability',json.dumps(captured))
    def test_default_scope_starts_exact_frozen_context_without_guessing_existing_instance(self):
        home,entry,app,config=self.app();resource=app/'Contents/Resources'/desktop.CONFIG_NAME;config['knowledge_home']=str(self.kb.home);config['vault_home']=str(self.kb.vault_home);resource.write_text(json.dumps(config))
        from loop_work.desktop_install import inspect_bundle
        manifest=json.loads((entry.parent/'manifest.json').read_text());manifest['desktop']['files']=inspect_bundle(app);(entry.parent/'manifest.json').write_text(json.dumps(manifest))
        with patch.object(Path,'home',return_value=home),patch.dict('os.environ',{},clear=True),patch.object(desktop.sys,'platform','darwin'),patch.object(desktop.subprocess,'run',return_value=SimpleNamespace(returncode=0)) as launch:
            desktop.open_app(self.kb,entrypoint=entry)
        self.assertEqual(launch.call_args.args[0],['/usr/bin/open','-n',str(app)])

    def test_nonexecutable_owned_binary_is_never_resolved_or_launched(self):
        home,entry,app,_=self.app();binary=app/'Contents/MacOS/LoopWork'
        mode=0o655 if __import__('os').geteuid()!=0 else 0o644;binary.chmod(mode);before=binary.read_bytes();manifest=entry.parent/'manifest.json';saved=manifest.read_bytes()
        with patch.object(Path,'home',return_value=home),patch.object(desktop.sys,'platform','darwin'),patch.object(desktop.subprocess,'run') as launch:
            with self.assertRaises(LoopError):desktop.resolve_app(entry)
            with self.assertRaises(LoopError):desktop.open_app(self.kb,entrypoint=entry)
        launch.assert_not_called();self.assertEqual(binary.stat().st_mode&0o777,mode)
        self.assertEqual(binary.read_bytes(),before);self.assertEqual(manifest.read_bytes(),saved)

    def test_unowned_modified_or_special_app_config_is_never_launched(self):
        import os
        home,entry,app,_=self.app();config=app/'Contents/Resources'/desktop.CONFIG_NAME
        with patch.object(Path,'home',return_value=home):
            original=config.read_bytes();config.write_bytes(original+b' ')
            with self.assertRaises(LoopError):desktop.resolve_app(entry)
            config.unlink();config.symlink_to(self.base/'unrelated')
            with self.assertRaises(LoopError):desktop.resolve_app(entry)
            config.unlink()
            if hasattr(os,'mkfifo'):
                os.mkfifo(config)
                with self.assertRaises(LoopError):desktop.resolve_app(entry)

    def test_malformed_regular_config_and_manifest_are_clean_install_errors(self):
        home,entry,app,_=self.app();config=app/'Contents/Resources'/desktop.CONFIG_NAME;manifest=entry.parent/'manifest.json'
        originals={config:config.read_bytes(),manifest:manifest.read_bytes()}
        with patch.object(Path,'home',return_value=home):
            for target in (config,manifest):
                for invalid in (b'[]',b'null',b'x'*(1024*1024+1)):
                    with self.subTest(target=target.name,invalid_size=len(invalid)):
                        for path,data in originals.items():path.write_bytes(data)
                        target.write_bytes(invalid)
                        with self.assertRaises(LoopError):desktop.resolve_app(entry)
