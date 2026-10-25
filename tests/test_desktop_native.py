"""Portable Python discovery; actual macOS Rust checks require explicit prepared-run opt-in."""
from pathlib import Path
import os
import errno
import json
import signal
import threading
import time
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from scripts import verify_tauri_native as verify
from loop_work import desktop_install
from loop_work.storage import LoopError,read_json
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]

def run_prepared_native_check():
    # Cargo presence says nothing about GUI system dependencies or the offline crate cache.
    # The fixed development gate runs its separate Cargo check; Python discovery must stay portable.
    if sys.platform != 'darwin' or os.environ.get('LOOP_NATIVE_TESTS') != '1' or not shutil.which('cargo'):
        return None
    return subprocess.run(['cargo','test','--manifest-path',str(ROOT/'desktop/src-tauri/Cargo.toml'),'--locked','--offline'],cwd=ROOT,capture_output=True,text=True,timeout=180)

class DesktopNativeTests(unittest.TestCase):
    def test_actual_native_protocol_guards(self):
        result=run_prepared_native_check()
        if result is None:
            self.skipTest('Actual native check requires prepared macOS, cargo and LOOP_NATIVE_TESTS=1')
        self.assertEqual(result.returncode,0,result.stderr)

    def test_linux_with_cargo_and_empty_cache_never_invokes_native_toolchain(self):
        with tempfile.TemporaryDirectory() as cache:
            with patch.object(sys,'platform','linux'),patch.dict(os.environ,{'LOOP_NATIVE_TESTS':'1','CARGO_HOME':cache}),patch.object(shutil,'which',return_value='/fixture/cargo'),patch.object(subprocess,'run',side_effect=AssertionError('Linux Python suite must not build GUI')) as run:
                self.assertIsNone(run_prepared_native_check())
                run.assert_not_called();self.assertEqual(list(Path(cache).iterdir()),[])

    def test_macos_without_explicit_opt_in_does_not_invoke_cargo(self):
        with patch.object(sys,'platform','darwin'),patch.dict(os.environ,{'LOOP_NATIVE_TESTS':'0'}),patch.object(shutil,'which',return_value='/fixture/cargo'),patch.object(subprocess,'run',side_effect=AssertionError('No implicit GUI compile')) as run:
            self.assertIsNone(run_prepared_native_check());run.assert_not_called()

    def test_prepared_macos_preserves_locked_offline_check_and_reports_failure(self):
        result=subprocess.CompletedProcess(['cargo'],7,'','fixture compilation failure')
        with patch.object(sys,'platform','darwin'),patch.dict(os.environ,{'LOOP_NATIVE_TESTS':'1'}),patch.object(shutil,'which',return_value='/fixture/cargo'),patch.object(subprocess,'run',return_value=result) as run:
            self.assertIs(run_prepared_native_check(),result)
        self.assertEqual(run.call_args.args[0],['cargo','test','--manifest-path',str(ROOT/'desktop/src-tauri/Cargo.toml'),'--locked','--offline'])


class NativePreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name).resolve();self.source=self.base/'source';(self.source/'desktop').mkdir(parents=True)
        (self.source/'desktop/retained.ts').write_text('retained source')
        self.output=self.base/'output';self.output.mkdir();self.cache=self.base/'feature-cache';self.cache.mkdir()
        self.patch_root=patch.object(verify,'ROOT',self.source);self.patch_root.start();self.addCleanup(self.patch_root.stop)
        self.patch_source=patch.object(desktop_install,'SOURCE',self.source);self.patch_source.start();self.addCleanup(self.patch_source.stop)

    def test_default_output_is_external_and_default_cache_fixed_without_source_pollution(self):
        from loop_work.desktop_sources import paths
        before={str(p):p.read_bytes() for p in paths(self.source)}
        with patch.object(verify.tempfile,'gettempdir',return_value=str(self.base)),patch.dict(os.environ,{},clear=True):
            first=verify.prepare_output();second=verify.prepare_output()
            one=verify.preflight_native(first);two=verify.preflight_native(second)
        self.assertFalse(first.is_relative_to(self.source));self.assertNotEqual(first,second)
        self.assertEqual(one['feature_cache'],two['feature_cache'])
        self.assertEqual(one['feature_cache'],str(self.source/'desktop/src-tauri/target/native-qa'))
        self.assertEqual({str(p):p.read_bytes() for p in paths(self.source)},before)
        self.assertLess(one['evidence_order'].index('install_app'),one['evidence_order'].index('populate_task_evidence'))
        self.assertEqual(list(self.base.rglob('.loop-native-probe-*')),[])

    def test_actual_default_argv_preflights_before_dispatching_expensive_verification(self):
        seen=[]
        def verified(output,qa_only,progress,prepared):
            self.assertFalse(qa_only);self.assertFalse(output.is_relative_to(self.source))
            self.assertTrue((output/'preflight.json').is_file())
            self.assertEqual(read_json(output/'progress.json')['last_completed_stage'],'preflight')
            self.assertEqual(prepared['feature_cache'],str(self.source/'desktop/src-tauri/target/native-qa'))
            seen.append(output);return 0
        with patch.object(sys,'platform','darwin'),patch.dict(os.environ,{},clear=True),patch.object(verify.tempfile,'gettempdir',return_value=str(self.base)),patch.object(verify,'run_verification',side_effect=verified):
            self.assertEqual(verify.main([]),0)
        self.assertEqual(len(seen),1);progress=read_json(seen[0]/'progress.json')
        self.assertEqual(progress['status'],'completed');self.assertIsNotNone(progress['finished_at'])

    def test_default_temp_inside_source_and_explicit_source_output_fail_before_creating(self):
        before=set(self.source.rglob('*'))
        with patch.object(verify.tempfile,'gettempdir',return_value=str(self.source)):
            with self.assertRaisesRegex(RuntimeError,'outside'):verify.prepare_output()
        with self.assertRaisesRegex(RuntimeError,'outside'):verify.prepare_output(self.source/'new-output')
        self.assertEqual(set(self.source.rglob('*')),before)

    def test_invalid_cache_preflight_fails_before_any_build_and_preserves_files(self):
        marker=self.cache/'user-cache';marker.write_bytes(b'cache contents')
        wrong=self.base/'cache-file';wrong.write_bytes(b'user file')
        for selected in (wrong,self.source/'untracked-cache'):
            with self.subTest(selected=selected),patch.object(sys,'platform','darwin'),patch.dict(os.environ,{'LOOP_NATIVE_QA_TARGET_DIR':str(selected)},clear=True),patch.object(desktop_install,'build_app') as build:
                out=self.base/('run-'+selected.name)
                with self.assertRaises((RuntimeError,LoopError)):verify.main(['--output',str(out)])
                build.assert_not_called();failure=read_json(out/'run-failure.json')
                self.assertEqual(failure['last_stage'],'preflight');self.assertFalse(failure['passed'])
        link=self.base/'cache-link';link.symlink_to(self.cache,target_is_directory=True)
        with patch.dict(os.environ,{'LOOP_NATIVE_QA_TARGET_DIR':str(link)}):
            with self.assertRaises(LoopError):verify.preflight_native(self.output)
        self.assertEqual(marker.read_bytes(),b'cache contents');self.assertEqual(wrong.read_bytes(),b'user file')
        self.assertTrue(link.is_symlink())

    def test_capacity_is_observed_not_an_arbitrary_build_blocker_and_enospc_is_classified(self):
        usage=SimpleNamespace(total=100,free=1)
        with patch.dict(os.environ,{'LOOP_NATIVE_QA_TARGET_DIR':str(self.cache)}),patch.object(desktop_install.shutil,'disk_usage',return_value=usage):
            result=verify.preflight_native(self.output)
        self.assertEqual(result['storage']['feature_cache']['free_bytes'],1)
        with patch.dict(os.environ,{'LOOP_NATIVE_QA_TARGET_DIR':str(self.cache)}),patch.object(desktop_install.os,'write',side_effect=OSError(errno.ENOSPC,'no space')):
            with self.assertRaisesRegex(LoopError,'ENOSPC'):verify.preflight_native(self.output)
        self.assertEqual(list(self.base.rglob('.loop-native-probe-*')),[])

    def test_bounded_progress_retains_last_stage_and_native_marker_without_exception_payload(self):
        progress=verify.StageLog(self.output)
        for _ in range(40):progress.mark('bounded','start');progress.mark('bounded','done')
        secret='private-token-and-human-original'
        with self.assertRaises(subprocess.TimeoutExpired):
            with progress.stage('actual_wait'):
                progress.native('close_guard','start',123)
                raise subprocess.TimeoutExpired([secret],5,stderr=secret)
        saved=read_json(self.output/'progress.json')
        self.assertEqual(saved['status'],'failed');self.assertEqual(saved['failure_kind'],'timeout')
        self.assertEqual(saved['current_stage'],'actual_wait');self.assertEqual(saved['last_native_stage']['stage'],'close_guard')
        self.assertLessEqual(len(saved['events']),64);self.assertGreater(saved['dropped_events'],0)
        self.assertIsNotNone(saved['started_at']);self.assertIsNotNone(saved['finished_at'])
        other=self.base/'space-run';other.mkdir();space=verify.StageLog(other);space.mark('native_qa_build','start')
        space.fail(desktop_install.build_failure('native_qa_build',subprocess.CalledProcessError(1,['fixture'],stderr='No space left on device')))
        self.assertEqual(read_json(other/'progress.json')['failure_kind'],'storage_enospc')
        self.assertNotIn(secret,(self.output/'progress.json').read_text())
        self.assertTrue(all('at' in e and 'elapsed_seconds' in e for e in saved['events']))

    def test_dynamic_native_stages_persist_before_eof_and_reject_unknown_or_partial_names(self):
        driver=self.source/'desktop/src-tauri/src/native_qa_driver.js'
        driver.parent.mkdir(parents=True)
        driver.write_text((ROOT/'desktop/src-tauri/src/native_qa_driver.js').read_text())
        stages=['native_empty_draft_execute_delay_ack_quit_cancel_and_reconciliation',
                'native_empty_draft_execute_drop_ack_quit_cancel_and_reconciliation',
                'native_empty_response_ime_before_quit_preserved_until_compositionend',
                'native_empty_control_ime_before_quit_preserved_until_compositionend']
        progress=verify.StageLog(self.output)
        read_fd,write_fd=os.pipe();reader=os.fdopen(read_fd,'rb');writer=os.fdopen(write_fd,'wb')
        captured=verify.BoundedStderr(reader,progress.native)
        try:
            for index,stage in enumerate(stages):
                writer.write(('native_qa_progress progress:'+stage+':done at_ms='+str(index)+'\n').encode())
            writer.write(b'native_qa_progress progress:unknown_stage:start at_ms=4\n')
            writer.write(b'native_qa_progress progress:native_empty_:start at_ms=5\n')
            writer.write(b'native_qa_progress progress:native_empty_draft_execute_:start at_ms=6\n')
            # Exact marker retained by the failed actual native run, not a synthetic alias.
            writer.write(b'native_qa_progress progress:native_empty_control_ime_before_quit_preserved_until_compositionend:start at_ms=1792859366710\n')
            writer.flush()
            deadline=time.monotonic()+2
            saved=None
            while time.monotonic()<deadline:
                try:
                    candidate=read_json(self.output/'progress.json')
                    if (candidate.get('last_native_stage') or {}).get('at_ms')==1792859366710:
                        saved=candidate
                        break
                except (LoopError,FileNotFoundError):pass
                time.sleep(.01)
            self.assertIsNotNone(saved,'Native marker was not persisted before stderr EOF')
            self.assertIsNotNone(progress.value['last_native_stage'])
            self.assertEqual(progress.value['last_native_stage']['stage'],stages[-1])
            self.assertEqual(saved['last_native_stage'],{'stage':stages[-1],'event':'start','at_ms':1792859366710})
            seen={event['stage'] for event in saved['events']}
            self.assertTrue({'native_qa.'+stage for stage in stages}<=seen)
            self.assertFalse({'native_qa.unknown_stage','native_qa.native_empty_',
                              'native_qa.native_empty_draft_execute_'}&seen)
            self.assertNotIn('native_empty_',verify.native_stage_names())
            self.assertNotIn('native_empty_draft_execute_',verify.native_stage_names())
            self.assertTrue(captured.thread.is_alive())
        finally:
            writer.close();captured.thread.join(timeout=2);reader.close()
        self.assertFalse(captured.thread.is_alive())

    def test_native_marker_is_persisted_before_stderr_eof(self):
        read_fd,write_fd=os.pipe();reader=os.fdopen(read_fd,'rb');writer=os.fdopen(write_fd,'wb')
        self.addCleanup(reader.close);self.addCleanup(writer.close)
        progress=verify.StageLog(self.output)
        with patch.object(verify,'native_stage_names',return_value={'close_guard'}):
            captured=verify.BoundedStderr(reader,progress.native)
            writer.write(b'native_qa_progress progress:close_guard:start at_ms=123\n');writer.flush()
            deadline=time.monotonic()+2
            while not (self.output/'progress.json').exists() and time.monotonic()<deadline:time.sleep(.01)
            saved=read_json(self.output/'progress.json')
            self.assertEqual(saved['last_native_stage'],{'stage':'close_guard','event':'start','at_ms':123})
            self.assertTrue(captured.thread.is_alive())
            writer.close();captured.thread.join(timeout=2)
            self.assertFalse(captured.thread.is_alive())

    def test_sigterm_retains_last_actual_stage_and_partial_evidence(self):
        out=self.base/'stopped-run'
        code="""import sys,time
from pathlib import Path
from scripts import verify_tauri_native as v
v.sys.platform='darwin'
v.preflight_native=lambda output:{}
def run(output,qa_only,progress,prepared):
 (output/'partial.json').write_text('{\"passed\":false}')
 with progress.stage('deliberate_wait'):time.sleep(120)
v.run_verification=run
v.main(['--output',sys.argv[1]])
"""
        child=subprocess.Popen([sys.executable,'-B','-c',code,str(out)],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            deadline=time.monotonic()+5
            while time.monotonic()<deadline:
                try:
                    if read_json(out/'progress.json')['current_stage']=='deliberate_wait':break
                except LoopError:pass
                time.sleep(.02)
            else:self.fail('Controlled wait stage did not start')
            child.send_signal(signal.SIGTERM);child.communicate(timeout=5)
            self.assertNotEqual(child.returncode,0)
            self.assertEqual(read_json(out/'progress.json')['failure_kind'],'interrupted')
            self.assertEqual(read_json(out/'run-failure.json')['last_stage'],'deliberate_wait')
            self.assertEqual(read_json(out/'partial.json'),{'passed':False})
            self.assertFalse((out/'summary.json').exists())
        finally:
            if child.poll() is None:child.kill();child.communicate(timeout=5)

    def test_installed_observation_precedes_task_evidence_generation(self):
        import types
        events=[];cache_binary=self.cache/'release/loop-work-desktop';cache_binary.parent.mkdir();cache_binary.write_bytes(b'audit')
        kb=types.SimpleNamespace(home=self.base/'fake-kb',vault_home=self.base/'fake-vault',list=lambda kind:[],observe=lambda locations:events.append('observe') or {})
        def fixture(base):
            base.mkdir();target=base/'target';target.mkdir();events.append('fixture')
            return kb,{'target':str(target)}
        def build(app,*args,**kwargs):
            binary=Path(app)/'Contents/MacOS/LoopWork';binary.parent.mkdir(parents=True);binary.write_bytes(b'shipping');events.append('build');return Path(app)
        def installed(*args,**kwargs):events.append('install')
        def populated(*args):events.append('populate');raise RuntimeError('deliberate stop before native launch')
        with patch.object(verify,'populated_fixture',side_effect=fixture),patch.object(desktop_install,'build_app',side_effect=build),patch.object(verify.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'','')),patch.object(verify,'install_links',side_effect=installed),patch.object(desktop_install,'build_inputs',return_value={}),patch.object(verify,'populate_records',side_effect=populated):
            with self.assertRaisesRegex(RuntimeError,'deliberate stop'):
                verify.verify_populated_native(self.output,verify.StageLog(self.output),{'feature_cache':str(self.cache)})
        self.assertEqual(events,['fixture','build','observe','install','observe','populate'])
        self.assertTrue((self.output/'populated-native-qa/installation-observation.json').is_file())
        self.assertEqual(cache_binary.read_bytes(),b'audit')
