from __future__ import annotations
import json
import errno
import subprocess
import os
from pathlib import Path
import plistlib
import sys
import tempfile
import unittest
from unittest.mock import patch

from loop_work import desktop_install as desktop
from loop_work.storage import LoopError, file_hash, read_json
from scripts import install


class DesktopInstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve();self.home=self.base/'home';self.home.mkdir()
        self.target=self.base/'project';self.target.mkdir();(self.target/'README.md').write_text('프로젝트 원문')
        self.builds=[]

    def fake_build(self, path, entrypoint, knowledge_home=None,vault_home=None,project_id=None,*,target_root=None):
        path=Path(path);self.builds.append(path)
        for name in desktop.BUNDLE_DIRS:(path/name).mkdir(parents=True,exist_ok=True)
        (path/'Contents/Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'LoopWork','CFBundleIdentifier':'org.loop-work.desktop'}))
        (path/'Contents/MacOS/LoopWork').write_bytes(b'owned-native-test-binary');(path/'Contents/MacOS/LoopWork').chmod(0o755)
        (path/'Contents/Resources/desktop-config.json').write_text(json.dumps(desktop.configuration(entrypoint,knowledge_home,vault_home,project_id,target_root)))
        return path

    def run_install(self,target=None,*,failure=False,explicit_home=True):
        args=['--link','--workspace']
        if explicit_home:args+=['--home',str(self.home)]
        if target:args+=['--target',str(target)]
        with patch.object(sys,'platform','darwin'),patch.object(desktop,'build_inputs',side_effect=lambda config:{'config':config,'compiler':'test-fixed-toolchain'}),patch.object(desktop,'build_app',side_effect=LoopError('compile failure') if failure else self.fake_build),patch('scripts.setup_workspace.bootstrap',return_value={'root':str(self.home/'.loop-work'),'obsidian':'existing','next':'열기'}) as bootstrap:
            result=install.main(args)
        return result,bootstrap

    def test_user_and_target_install_cache_recreate_and_uninstall_preserve_data(self):
        for target in (None,self.target):
            with self.subTest(target=target):
                root=target or self.home;app=root/('.loop/Loop Work.app' if target else 'Applications/Loop Work.app')
                self.assertEqual(self.run_install(target)[0],0)
                config=read_json(app/'Contents/Resources/desktop-config.json')
                self.assertEqual(config['python'],str(Path(sys.executable).resolve()))
                self.assertTrue(Path(config['entrypoint']).is_absolute());self.assertEqual(config['target_root'],str(target) if target else None)
                self.assertIsNone(config['project_id']);self.assertEqual(config['knowledge_home'],str(self.home/'.loop-work/data'));self.assertEqual(config['vault_home'],str(self.home/'.loop-work/vault'))
                self.assertTrue(os.access(app/'Contents/MacOS/LoopWork',os.X_OK))
                manifest=root/('.loop/install/manifest.json' if target else '.local/share/loop-work/install/manifest.json')
                original=manifest.read_bytes();builds=len(self.builds);pins=desktop.inspect_bundle(app)
                self.assertEqual(self.run_install(target)[0],0);self.assertEqual(len(self.builds),builds)
                self.assertEqual(manifest.read_bytes(),original);self.assertEqual(desktop.inspect_bundle(app),pins)
                (app/'Contents/MacOS/LoopWork').unlink()
                self.assertEqual(self.run_install(target)[0],0);self.assertGreater(len(self.builds),builds)
                self.assertTrue(os.access(app/'Contents/MacOS/LoopWork',os.X_OK))
                note=root/'vault-user.md';note.write_text('사용자 원문 유지')
                install.uninstall_links(self.home,target)
                self.assertFalse(app.exists());self.assertEqual(note.read_text(),'사용자 원문 유지')

    def test_unowned_modified_added_and_symlink_app_conflicts_preserve_skills(self):
        app=self.home/'Applications/Loop Work.app';app.mkdir(parents=True);(app/'user-note').write_text('원문')
        self.assertEqual(self.run_install()[0],2);self.assertEqual((app/'user-note').read_text(),'원문')
        self.assertFalse((self.home/'.agents').exists());self.assertEqual(self.builds,[])
        (app/'user-note').unlink();app.rmdir()
        self.assertEqual(self.run_install()[0],0)
        manifest=self.home/'.local/share/loop-work/install/manifest.json';before=manifest.read_bytes()
        binary=app/'Contents/MacOS/LoopWork';binary.write_bytes(b'user modified')
        self.assertEqual(self.run_install()[0],2);self.assertEqual(binary.read_bytes(),b'user modified');self.assertEqual(manifest.read_bytes(),before)
        with self.assertRaises(LoopError):install.uninstall_links(self.home)
        binary.write_bytes(b'owned-native-test-binary');binary.chmod(0o755)
        extra=app/'user-extra';extra.write_text('보존')
        with self.assertRaises(LoopError):install.uninstall_links(self.home)
        self.assertEqual(extra.read_text(),'보존');extra.unlink()
        config=app/'Contents/Resources/desktop-config.json';original=config.read_bytes();config.unlink();outside=self.base/'outside';outside.write_bytes(original);config.symlink_to(outside)
        self.assertEqual(self.run_install()[0],2);self.assertTrue(config.is_symlink());self.assertEqual(outside.read_bytes(),original)

    def test_compile_failure_happens_before_workspace_or_skill_mutation(self):
        result,bootstrap=self.run_install(failure=True)
        self.assertEqual(result,2);bootstrap.assert_not_called()
        self.assertFalse((self.home/'.agents').exists());self.assertFalse((self.home/'Applications').exists())

    def test_legacy_link_upgrade_and_lowlevel_install_do_not_compile(self):
        with patch.object(desktop,'build_app',side_effect=AssertionError('lowlevel must not compile')):
            install.install_links(self.home)
        manifest=self.home/'.local/share/loop-work/install/manifest.json';self.assertNotIn('desktop',read_json(manifest))
        self.assertEqual(self.run_install()[0],0);self.assertIn('desktop',read_json(manifest))
        before=read_json(manifest)['desktop']
        install.install_links(self.home);self.assertEqual(read_json(manifest)['desktop'],before)

    def test_installer_pins_custom_store_for_finder_and_explicit_home_ignores_environment(self):
        custom=self.base/'custom-knowledge'
        with patch.dict(os.environ,{'LOOP_KB_HOME':str(custom)}),patch.object(Path,'home',return_value=self.home):
            self.assertEqual(self.run_install(explicit_home=False)[0],0)
        app=self.home/'Applications/Loop Work.app';config=read_json(app/'Contents/Resources/desktop-config.json')
        self.assertEqual(config['knowledge_home'],str(custom));self.assertIsNone(config['vault_home'])
        self.assertFalse(custom.exists())
        # Finder need not inherit LOOP_KB_HOME: the selected absolute store is saved.
        with patch.dict(os.environ,{},clear=True):self.assertEqual(read_json(app/'Contents/Resources/desktop-config.json'),config)
        other=self.base/'isolated-home';other.mkdir();self.home=other
        with patch.dict(os.environ,{'LOOP_KB_HOME':str(custom)}):self.assertEqual(self.run_install()[0],0)
        config=read_json(other/'Applications/Loop Work.app/Contents/Resources/desktop-config.json')
        self.assertEqual(config['knowledge_home'],str(other/'.loop-work/data'));self.assertEqual(config['vault_home'],str(other/'.loop-work/vault'))
        self.assertFalse(custom.exists())

    def test_project_generated_bundle_and_launcher_are_exactly_ignored_preserving_user_rules(self):
        import subprocess
        subprocess.run(['git','init','-q',str(self.target)],check=True,capture_output=True)
        ignore=self.target/'.gitignore';ignore.write_text('# 사용자 원문 보존\nprivate-note.md\n')
        self.assertEqual(self.run_install(self.target)[0],0)
        self.assertTrue(ignore.read_text().startswith('# 사용자 원문 보존\nprivate-note.md\n'))
        for name,pattern in (('.loop/Loop Work.app/Contents/MacOS/LoopWork','/.loop/Loop Work.app/'),
                             ('.loop/Loop Work.app/Contents/Resources/desktop-config.json','/.loop/Loop Work.app/'),
                             ('.loop/bin/loop-work','/.loop/bin/loop-work')):
            result=subprocess.run(['git','-C',str(self.target),'check-ignore','-v','--',name],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('.gitignore:',result.stdout);self.assertIn(pattern,result.stdout)
        unowned=self.target/'.loop/bin/user-command';unowned.write_text('사용자 파일')
        result=subprocess.run(['git','-C',str(self.target),'check-ignore','--',str(unowned)],capture_output=True)
        self.assertEqual(result.returncode,1)
        install.uninstall_links(self.home,self.target)
        self.assertEqual(unowned.read_text(),'사용자 파일')
        self.assertEqual(ignore.read_text(),'# 사용자 원문 보존\nprivate-note.md\n')

    def test_cached_owned_binary_without_current_user_execute_is_rejected_unchanged(self):
        for target in (None,self.target):
            with self.subTest(target=target):
                self.assertEqual(self.run_install(target)[0],0)
                root=target or self.home;app=root/('.loop/Loop Work.app' if target else 'Applications/Loop Work.app')
                binary=app/'Contents/MacOS/LoopWork';manifest=root/('.loop/install/manifest.json' if target else '.local/share/loop-work/install/manifest.json')
                contents=binary.read_bytes();saved=manifest.read_bytes();builds=len(self.builds)
                # Non-root owners cannot execute mode0655 although group/other
                # execute bits keep storage.file_hash's boolean execute pin true.
                original_pin=file_hash(binary)
                mode=0o655 if os.geteuid()!=0 else 0o644;binary.chmod(mode)
                if os.geteuid()!=0:self.assertEqual(file_hash(binary),original_pin)
                self.assertFalse(os.access(binary,os.X_OK))
                self.assertEqual(self.run_install(target)[0],2)
                self.assertEqual(len(self.builds),builds)
                self.assertEqual(binary.stat().st_mode&0o777,mode)
                self.assertEqual(binary.read_bytes(),contents);self.assertEqual(manifest.read_bytes(),saved)

    def test_toolchain_absence_is_clear_and_does_not_create_bundle(self):
        with patch.object(desktop.shutil,'which',return_value=None):
            with self.assertRaisesRegex(LoopError,'cargo'):desktop.build_inputs(desktop.configuration(self.base/'loop.py'))
        self.assertFalse((self.base/'app.app').exists())

    def test_storage_preflight_refuses_unwritable_build_before_commands(self):
        source=self.base/'build-source';(source/'desktop').mkdir(parents=True)
        marker=source/'desktop/user.ts';marker.write_text('preserved')
        with patch.object(sys,'platform','darwin'),patch.object(desktop,'SOURCE',source),patch.object(desktop.os,'access',return_value=False),patch.object(desktop.subprocess,'run') as run:
            with self.assertRaisesRegex(LoopError,'not writable'):
                desktop.build_app(self.base/'staged.app',self.base/'loop.py')
            run.assert_not_called()
        self.assertEqual(marker.read_text(),'preserved');self.assertFalse((self.base/'staged.app').exists())

    def test_actual_enospc_and_timeout_report_exact_build_stage_preserving_existing_files(self):
        source=self.base/'build-source';(source/'desktop').mkdir(parents=True)
        marker=source/'desktop/user.ts';marker.write_text('preserved')
        for error,label in ((OSError(errno.ENOSPC,'full'),'ENOSPC'),(subprocess.CalledProcessError(1,['fixture'],stderr='No space left on device (os error 28)'),'ENOSPC'),(subprocess.TimeoutExpired(['/fixed/npm'],1,stderr=b'bounded diagnostic'),'timed out')):
            events=[]
            with self.subTest(label=label),patch.object(sys,'platform','darwin'),patch.object(desktop,'SOURCE',source),patch.object(desktop,'build_inputs',return_value={'tools':{'npm':'/fixed/npm'}}),patch.object(desktop.subprocess,'run',side_effect=error):
                with self.assertRaisesRegex(LoopError,label+'.*npm_ci'):
                    desktop.build_app(self.base/'staged.app',self.base/'loop.py',progress=lambda stage,event:events.append((stage,event)))
                self.assertEqual(events,[('npm_ci','start'),('npm_ci','failed')])
                self.assertFalse((self.base/'staged.app').exists())
        self.assertEqual(marker.read_text(),'preserved');self.assertEqual(list(self.base.rglob('.loop-native-probe-*')),[])

    def test_build_phase_callbacks_cover_success_without_putting_capacity_in_build_identity(self):
        source=self.base/'build-source';binary=source/'desktop/src-tauri/target/release/loop-work-desktop';binary.parent.mkdir(parents=True);binary.write_bytes(b'fixture executable')
        events=[]
        with patch.object(sys,'platform','darwin'),patch.object(desktop,'SOURCE',source),patch.object(desktop,'build_inputs',return_value={'tools':{'npm':'/fixed/npm'}}),patch.object(desktop.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','')) as run:
            app=desktop.build_app(self.base/'staged.app',self.base/'loop.py',progress=lambda stage,event:events.append((stage,event)))
        self.assertEqual(events,[(stage,event) for stage in ('npm_ci','frontend_build','shipping_tauri_build','bundle_packaging') for event in ('start','done')])
        self.assertEqual(run.call_count,3);self.assertEqual((app/'Contents/MacOS/LoopWork').read_bytes(),b'fixture executable')
        self.assertEqual(set(desktop.inspect_bundle(app)),set(desktop.BUNDLE_FILES))

    def test_enospc_build_failure_keeps_original_path_and_message_with_bounded_diagnostic(self):
        source=self.base/'enospc-source';(source/'desktop').mkdir(parents=True)
        marker=source/'desktop/user.ts';marker.write_text('unchanged')
        failure_path='/fixture/native-output/unique-failed-object.o'
        errors=(OSError(errno.ENOSPC,'native original write failure',failure_path),
                subprocess.CalledProcessError(1,['fixture'],stderr='native original linker failure '+failure_path+' No space left on device\n'+'x'*9000+'\noriginal terminal error'))
        for error in errors:
            with self.subTest(error=type(error).__name__),patch.object(sys,'platform','darwin'),patch.object(desktop,'SOURCE',source),patch.object(desktop,'build_inputs',return_value={'tools':{'npm':'/fixed/npm'}}),patch.object(desktop.subprocess,'run',side_effect=error):
                with self.assertRaises(LoopError) as caught:
                    desktop.build_app(self.base/'failure.app',self.base/'loop.py')
                message=str(caught.exception)
                self.assertIn(failure_path,message);self.assertIn('native original',message)
                self.assertIn('npm_ci',message);self.assertIn('ENOSPC',message)
                self.assertEqual(caught.exception.failure_kind,'storage_enospc')
                self.assertLessEqual(len(message),4200)
                if isinstance(error,subprocess.CalledProcessError):
                    self.assertIn('[diagnostic truncated]',message);self.assertIn('original terminal error',message)
                self.assertFalse((self.base/'failure.app').exists())
        self.assertEqual(marker.read_text(),'unchanged')

    @unittest.skipUnless(sys.platform=='darwin','Native bundle compilation requires macOS')
    def test_real_compiled_app_cache_rejects_removed_owner_execute_permission(self):
        args=['--link','--workspace','--home',str(self.home)]
        with patch('scripts.setup_workspace.bootstrap',return_value={'root':str(self.home/'.loop-work'),'obsidian':'existing','next':'열기'}):
            self.assertEqual(install.main(args),0)
            app=self.home/'Applications/Loop Work.app';binary=app/'Contents/MacOS/LoopWork'
            manifest=self.home/'.local/share/loop-work/install/manifest.json';saved=manifest.read_bytes();contents=binary.read_bytes()
            original_pin=file_hash(binary)
            mode=0o655 if os.geteuid()!=0 else 0o644;binary.chmod(mode)
            if os.geteuid()!=0:self.assertEqual(file_hash(binary),original_pin)
            self.assertFalse(os.access(binary,os.X_OK))
            with patch.object(desktop,'build_app',side_effect=AssertionError('changed permissions must not trigger repair')):
                self.assertEqual(install.main(args),2)
            self.assertEqual(binary.read_bytes(),contents);self.assertEqual(binary.stat().st_mode&0o777,mode)
            self.assertEqual(manifest.read_bytes(),saved)

    @unittest.skipUnless(sys.platform=='darwin','Native bundle compilation requires macOS')
    def test_real_tauri_compilation_has_native_executable_and_sparse_path_config(self):
        entrypoint=self.base/'loop.py';entrypoint.write_text('raise SystemExit(0)\n')
        app=desktop.build_app(self.base/'real.app',entrypoint,knowledge_home=self.base/'kb',vault_home=self.base/'vault')
        pins=desktop.inspect_bundle(app);self.assertEqual(set(pins),set(desktop.BUNDLE_FILES))
        self.assertTrue(os.access(app/'Contents/MacOS/LoopWork',os.X_OK))
        with (app/'Contents/Info.plist').open('rb') as stream:self.assertEqual(plistlib.load(stream)['CFBundleIdentifier'],'org.loop-work.desktop')
        self.assertTrue(read_json(app/'Contents/Resources/desktop-config.json')['python'].startswith('/'))
