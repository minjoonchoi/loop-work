#!/usr/bin/env python3
"""Real release app/helper/service verification in fresh isolated stores.

No OS input automation, no test bridge in the shipped application. A renderer_ready
ack establishes actual bundled React startup, not physical keyboard/IME verification.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime,timezone
import errno
import re
import threading
import ctypes
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from loop_work import board_service,desktop_install
from loop_work.knowledge import KnowledgeBase
from loop_work.storage import engine_digest,file_hash,write_json
from scripts.install import install_links

class StageLog:
    """Bounded, payload-free progress, including the last actual native QA marker."""
    def __init__(self,output):
        self.path=Path(output)/'progress.json';self.lock=threading.Lock();self.started=time.monotonic()
        self.value={'version':1,'started_at':datetime.now(timezone.utc).isoformat(),'finished_at':None,'status':'running','current_stage':None,'last_completed_stage':None,
                    'last_native_stage':None,'events':[],'dropped_events':0}
    def _event(self,stage,event):
        self.value['events'].append({'stage':stage,'event':event,'at':datetime.now(timezone.utc).isoformat(),
                                     'elapsed_seconds':round(time.monotonic()-self.started,3)})
        if len(self.value['events'])>64:
            self.value['events']=self.value['events'][-64:];self.value['dropped_events']+=1
        write_json(self.path,self.value)
    def mark(self,stage,event):
        if not re.fullmatch(r'[a-z0-9_.:-]{1,120}',stage) or event not in ('start','done','failed'):
            raise ValueError('Invalid diagnostic stage')
        with self.lock:
            if self.value['status']=='failed':return
            self.value['current_stage']=stage
            if event=='done':self.value['last_completed_stage']=stage
            self._event(stage,event)
    def native(self,stage,event,at_ms):
        if not re.fullmatch(r'[a-z0-9_]{1,100}',stage) or event not in ('start','done') or type(at_ms) is not int:raise ValueError('Invalid native diagnostic marker')
        with self.lock:
            self.value['last_native_stage']={'stage':stage,'event':event,'at_ms':at_ms}
            self._event('native_qa.'+stage,event)
    def fail(self,error):
        with self.lock:
            if self.value['status']=='failed':return
            category='failed';cause=error
            for _ in range(6):
                if getattr(cause,'failure_kind',None) in ('storage_enospc','timeout'):
                    category=cause.failure_kind;break
                if isinstance(cause,(KeyboardInterrupt,SystemExit)):category='interrupted';break
                if isinstance(cause,(subprocess.TimeoutExpired,TimeoutError)):category='timeout';break
                if isinstance(cause,OSError) and cause.errno==errno.ENOSPC:category='storage_enospc';break
                cause=getattr(cause,'__cause__',None)
                if cause is None:break
            self.value.update(status='failed',failure_kind=category,error_type=type(error).__name__,finished_at=datetime.now(timezone.utc).isoformat())
            self._event(self.value['current_stage'] or 'initialization','failed')
    @contextmanager
    def stage(self,name):
        self.mark(name,'start')
        try:yield
        except BaseException as error:self.fail(error);raise
        else:self.mark(name,'done')
    def finish(self):
        with self.lock:
            self.value['status']='completed';self.value['finished_at']=datetime.now(timezone.utc).isoformat();self._event('verification','done')


def prepare_output(selected=None):
    if selected is not None:
        output=Path(selected).expanduser().resolve()
        if output.is_relative_to(ROOT):raise RuntimeError('Native fixtures must be outside the source repository')
        output.mkdir(parents=True,exist_ok=False)
        return output
    temporary=Path(tempfile.gettempdir()).resolve()
    if temporary.is_relative_to(ROOT):raise RuntimeError('Native temporary fixtures must be outside the source repository')
    return Path(tempfile.mkdtemp(prefix='loop-work-native-verification-',dir=temporary)).resolve()


def preflight_native(output):
    raw=Path(os.environ.get('LOOP_NATIVE_QA_TARGET_DIR',str(ROOT/'desktop/src-tauri/target/native-qa'))).expanduser()
    if not raw.is_absolute() or '..' in raw.parts:raise RuntimeError('Native QA cache must be an absolute non-symlink directory')
    cache=desktop_install._safe(raw)
    shipping=ROOT/'desktop/src-tauri/target'
    if cache==shipping or cache.is_relative_to(ROOT) and not cache.is_relative_to(shipping):
        raise RuntimeError('Native QA cache must be separate from shipping output and source files')
    if cache.exists() and not cache.is_dir():raise RuntimeError('Native QA cache is not a directory')
    try:cache.mkdir(parents=True,exist_ok=True)
    except OSError as exc:
        if exc.errno==errno.ENOSPC:raise RuntimeError('Native QA cache has no space (ENOSPC)') from exc
        raise RuntimeError('Native QA cache cannot be prepared') from exc
    result={'fixture_output':str(output),'feature_cache':str(cache),'feature':'native-qa',
            'storage':{'fixture':desktop_install.storage_observation(output,probe=True),
                       'feature_cache':desktop_install.storage_observation(cache,probe=True),
                       'frontend':desktop_install.storage_observation(ROOT/'desktop')},
            'storage_policy':'capacity observed; no arbitrary free-byte threshold; no cache cleanup',
            'evidence_order':['prepare_fixture','build_shipping','build_native_qa','install_app',
                              'observe_installed_inputs','populate_task_evidence','launch_actual_webview']}
    write_json(Path(output)/'preflight.json',result)
    return result


def native_stage_names():
    text=(ROOT/'desktop/src-tauri/src/native_qa_driver.js').read_text()
    # Only complete literal calls: dynamic concatenation prefixes are not stages.
    fixed=set(re.findall(r"check\(['\"]([a-z0-9_]+)['\"]\s*,",text))
    return fixed|{'driver_start','driver_listen_ready',
                  'native_empty_draft_execute_delay_ack_quit_cancel_and_reconciliation',
                  'native_empty_draft_execute_drop_ack_quit_cancel_and_reconciliation',
                  'native_empty_response_ime_before_quit_preserved_until_compositionend',
                  'native_empty_control_ime_before_quit_preserved_until_compositionend'}


def terminate(pid):
    # Public NSRunningApplication API; normal quit, never a force-kill fallback.
    ctypes.CDLL('/System/Library/Frameworks/AppKit.framework/AppKit')
    objc=ctypes.CDLL('/usr/lib/libobjc.A.dylib')
    objc.objc_getClass.argtypes=[ctypes.c_char_p];objc.objc_getClass.restype=ctypes.c_void_p
    objc.sel_registerName.argtypes=[ctypes.c_char_p];objc.sel_registerName.restype=ctypes.c_void_p
    address=ctypes.cast(objc.objc_msgSend,ctypes.c_void_p).value
    get=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_int)(address)
    app=get(objc.objc_getClass(b'NSRunningApplication'),objc.sel_registerName(b'runningApplicationWithProcessIdentifier:'),pid)
    if not app:raise RuntimeError('Owned native application is unavailable')
    call=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(address)
    if not call(app,objc.sel_registerName(b'terminate')):raise RuntimeError('Normal native quit request was rejected')

def wait_ready(child,deadline):
    while time.monotonic()<deadline:
        if child.poll() is not None:raise RuntimeError('Native application exited before renderer_ready')
        if select.select([child.stdout],[],[],0.2)[0]:
            line=child.stdout.readline()
            if line.strip()==b'{"event":"desktop_ready"}':return
    raise TimeoutError('Actual React renderer readiness deadline exceeded')

class BoundedStderr:
    """Drain immediately; retain only bounded private native-process diagnostics."""
    def __init__(self,stream,progress=None):
        self.data=bytearray();self.received=0;self.last_stage=None
        allowed=native_stage_names() if progress else set();pending=bytearray()
        def drain():
            read=getattr(stream,'read1',stream.read)
            while True:
                chunk=read(4096)
                if not chunk:break
                self.received+=len(chunk);self.data.extend(chunk)
                pending.extend(chunk)
                while b'\n' in pending:
                    line,_,rest=pending.partition(b'\n');pending[:]=rest
                    match=re.fullmatch(rb'native_qa_progress progress:([a-z0-9_]+):(start|done) at_ms=([0-9]{1,20})',line)
                    if match and match[1].decode() in allowed:
                        self.last_stage={'stage':match[1].decode(),'event':match[2].decode(),'at_ms':int(match[3])}
                        progress(self.last_stage['stage'],self.last_stage['event'],self.last_stage['at_ms'])
                if len(pending)>4096:pending.clear()
                if len(self.data)>32768:del self.data[:-32768]
        self.thread=threading.Thread(target=drain,daemon=True);self.thread.start()
    def snapshot(self):
        self.thread.join(timeout=.5)
        text=bytes(self.data).decode('utf-8',errors='replace')
        if self.received>32768:text=text.partition('\n')[2]
        # The Rust launcher already redacts helper diagnostics. Fail closed on a
        # raw capability URL accidentally emitted by another native dependency.
        import re
        text=re.sub(r'http://127\.0\.0\.1:[0-9]+/#[^\s"\']+','[비공개 연결 주소]',text)
        return {'stderr':text,'bytes_received':self.received,'truncated':self.received>32768,'reader_done':not self.thread.is_alive(),'last_native_stage':self.last_stage}

def populated_fixture(base):
    from loop_work.work import Work
    from loop_work.human import HumanDesk
    from loop_work.storage import file_hash
    base.mkdir();home=base/'home';home.mkdir();target=base/'인증서비스';target.mkdir()
    install_links(home,target)  # Freeze managed project instructions before task evidence.
    proof=target/'README.md';proof.write_text('실제 native 통합 검증용 합성 입력입니다. 제품 작업 완료 기록이 아닙니다.\n')
    kb=KnowledgeBase(base/'kb',vault_home=base/'vault');project=kb.attach(target)['project_id']
    return kb,{'project_id':project,'target':str(target),'proof':str(proof)}

def populate_records(kb, prepared):
    from loop_work.work import Work
    from loop_work.human import HumanDesk
    target=Path(prepared['target']);proof=Path(prepared['proof']);project=prepared['project_id'];work=Work(kb);tasks={}
    policy={'version':1,'profiles':[{'id':'fixture-codex','provider':'codex','model':'gpt-6.1-sol','effort':'low','capability_rank':100,'cost_rank':1}],'requirements':{'low':100,'medium':100,'high':100}}
    titles={'ready':'준비','working':'진행','review':'사용자 확인','completed':'완료','completed_pending':'완료 후 확인','stopped':'중단','blocked':'기술 차단','execute_delay':'빈 응답 실행 지연','execute_lost':'빈 응답 실행 유실','execute_race':'종료 준비 중 실행 확인'}
    for state,title in titles.items():
        t=work.open('document','네이티브 '+title+' 문서','codex',[target],explicit_skill=True)['task'];tid=t['id'];tasks[state]=tid
        if state!='ready':
            work.define(tid,{'outcome':'합성 native 통합 상태 확인','deliverable':'README.md','criteria':[{'id':'C1','description':'합성 README가 존재한다'}],'decisions':[],'open_questions':[],'execution':{'routing':policy}});work.start(tid)
        if state in ('completed','completed_pending'):
            work.finish(tid,{'summary':'합성 fixture 상태 전이','outputs':[str(proof)],'checks':[{'criterion_id':'C1','satisfied':True,'evidence':str(proof)}]})
        if state in ('review','completed_pending'):
            HumanDesk(kb).create(tid,{'id':'native-question-'+tid,'kind':'decision','title':'합성 네이티브 질문','question':'원문을 그대로 기록합니까?','options':[],'action':None})
        elif state=='stopped':work.stop(tid,'명시적 합성 중단',abort=True)
        elif state in ('blocked','execute_delay','execute_lost','execute_race'):work.stop(tid,{'version':1,'kind':'external','reason':'합성 환경 확인 대기','scope':'task','retryable':True,'evidence':[{'ref':str(proof),'sha256':file_hash(proof)}]})
    ordinary=work.open('document','일반 대화의 숨긴 참고 정보','codex',[target],session_id=kb.get('task',tasks['working'])['session_id'])['task']
    HumanDesk(kb).create(ordinary['id'],{'id':'native-hidden-question','kind':'decision','title':'숨긴 일반 질문','question':'목록 제외','options':[],'action':None})
    respond='native-visible-question';HumanDesk(kb).create(tasks['review'],{'id':respond,'kind':'decision','title':'네이티브 실제 응답','question':'응답 원문 보존','options':[],'action':None})
    execute='native-manual-resume';HumanDesk(kb).create(tasks['blocked'],{'id':execute,'kind':'manual_action','title':'네이티브 명시 재개','question':'수동 해소 후 명시 실행','options':[],'action':'resume_task'})
    execute_cases=[]
    for mode,key in (('delay','execute_delay'),('drop','execute_lost')):
        rid='native-empty-execute-'+mode
        HumanDesk(kb).create(tasks[key],{'id':rid,'kind':'manual_action','title':'빈 입력 실행 접수 '+mode,'question':'합성 수동 해소 후 명시 실행 확인','options':[],'action':'resume_task'})
        execute_cases.append({'id':rid,'task_id':tasks[key],'mode':mode,'expected_phase':kb.get('task',tasks[key])['previous_phase']})
    race_id='native-close-race-execute'
    HumanDesk(kb).create(tasks['execute_race'],{'id':race_id,'kind':'manual_action','title':'종료 준비 경합의 명시 실행','question':'합성 종료 준비 중 실행 차단과 취소 후 수동 재시도','options':[],'action':'resume_task'})
    race_case={'id':race_id,'task_id':tasks['execute_race'],'expected_phase':kb.get('task',tasks['execute_race'])['previous_phase']}
    kb.sync_vault()
    manifest=json.loads((kb.home/'vault-owned.json').read_text());hidden_paths=[name for name,v in manifest['documents'].items() if v.get('task_id')==ordinary['id'] or v.get('id')==ordinary['id']]
    fixture={'project_id':project,'edit_task':tasks['working'],'hidden_task':ordinary['id'],'expected_task_ids':list(tasks.values()),'respond_id':respond,'respond_task':tasks['review'],'execute_id':execute,'blocked_task':tasks['blocked'],'resume_phase':kb.get('task',tasks['blocked'])['previous_phase'],'execute_cases':execute_cases,'close_race_case':race_case,'marker':str(time.time_ns()),'target':str(target),'hidden_paths':hidden_paths,'proof_sha256':file_hash(proof),'proof':str(proof)}
    return kb,fixture

def verify_populated_native(output,progress=None,preflight=None):
    import shutil
    if progress:progress.mark('populated.prepare_fixture','start')
    base=output/'populated-native-qa';kb,fixture=populated_fixture(base)
    if progress:progress.mark('populated.prepare_fixture','done')
    target=Path(fixture['target']);entry=target/'.loop/install/loop.py'
    app=desktop_install.build_app(base/'audit.app',entry,kb.home,kb.vault_home,target_root=target,progress=(lambda stage,event:progress.mark('populated.'+stage,event)) if progress else None)
    shipping=app/'Contents/MacOS/LoopWork';shipping_pin=file_hash(shipping)
    build_target=Path((preflight or preflight_native(output))['feature_cache'])
    command=[str(ROOT/'desktop/node_modules/.bin/tauri'),'build','--no-bundle','--ci','--features','native-qa','--','--locked','--target-dir',str(build_target)]
    if progress:progress.mark('populated.native_qa_build','start')
    built=subprocess.run(command,cwd=ROOT/'desktop',capture_output=True,text=True,timeout=600)
    (base/'audit-build.log').write_text(built.stdout+built.stderr)
    if built.returncode:
        error=subprocess.CalledProcessError(built.returncode,command,stderr=built.stderr)
        raise desktop_install.build_failure('native_qa_build',error) from error
    if progress:progress.mark('populated.native_qa_build','done')
    audit_binary=build_target/'release/loop-work-desktop';audit_pin=file_hash(audit_binary)
    preserved_binary=base/'audit-binary';shutil.copy2(audit_binary,preserved_binary)
    shutil.copyfile(audit_binary,shipping);shipping.chmod(0o755)
    from loop_work.desktop_install import configuration,build_inputs
    from loop_work.storage import digest
    locations=[kb.get('location',x['id']) for x in kb.list('location')]
    observation_before=kb.observe(locations)
    if progress:progress.mark('populated.install_app','start')
    install_links(base/'home',target,desktop_app=app,desktop_build=digest(build_inputs(configuration(entry,kb.home,kb.vault_home,target_root=target))))
    if progress:progress.mark('populated.install_app','done')
    if progress:progress.mark('populated.observe_installed_inputs','start')
    observation_after=kb.observe(locations)
    changed={key:sorted(name for name in set(observation_before[key]['files'])|set(observation_after[key]['files']) if observation_before[key]['files'].get(name)!=observation_after[key]['files'].get(name)) for key in observation_before}
    (base/'installation-observation.json').write_text(json.dumps({'before':digest(observation_before),'after':digest(observation_after),'changed_paths':changed},ensure_ascii=False,indent=2))
    if progress:progress.mark('populated.observe_installed_inputs','done')
    if progress:progress.mark('populated.populate_task_evidence','start')
    kb,fixture=populate_records(kb,fixture)
    if progress:progress.mark('populated.populate_task_evidence','done')
    before={t['id']:{k:t.get(k) for k in ('goal','execution','budget','calls','attempts','title')} for t in kb.list('task')}
    before_counts={'tasks':len(kb.list('task')),'sessions':len(kb.list('session'))}
    from loop_work.board import Board
    initial=Board(kb).list(project_id=fixture['project_id'],include_closed=True)
    (base/'initial-board-state.json').write_text(json.dumps({'tasks':[{'id':r['record']['id'],'phase':r['record']['phase'],'board_state':r['board_state'],'completion_current':r.get('control',{}).get('completion_current')} for r in initial['tasks']]},ensure_ascii=False,indent=2))
    script=base/'native-driver.js';script.write_text('const fixture='+json.dumps(fixture,ensure_ascii=False)+';\n'+(ROOT/'desktop/src-tauri/src/native_qa_driver.js').read_text())
    report=base/'native-webview-report.json';plan=base/'plan.json';plan.write_text(json.dumps({'script_path':str(script),'report_path':str(report)}))
    binary=target/'.loop/Loop Work.app/Contents/MacOS/LoopWork';child=None;capture=None
    try:
        if progress:progress.mark('populated.launch_actual_webview','start')
        child=subprocess.Popen([str(binary)],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={**os.environ,'HOME':str(base/'home'),'LOOP_KB_HOME':str(kb.home),'LOOP_NATIVE_QA_PLAN':str(plan)})
        capture=BoundedStderr(child.stderr,progress.native if progress else None);wait_ready(child,time.monotonic()+60)
        if progress:progress.mark('populated.actual_webview_audit','start')
        deadline=time.monotonic()+150
        while child.poll() is None and time.monotonic()<deadline:time.sleep(.2)
        if child.poll() is None:raise TimeoutError('Populated actual WebView audit deadline exceeded')
        if not report.is_file():raise RuntimeError('Actual WebView audit exited without report')
        result=json.loads(report.read_text());result['native_exit']=child.returncode;result['shipping_binary_pin']=shipping_pin;result['audit_binary_pin']=audit_pin;result['feature']='native-qa';result['separate_target_dir']=str(build_target);result['evidence_kind']='test_only_native_webview_actual_api';result['input_evidence']={'composition':'synthetic_events','physical_gui_input_verified':False}
        if child.returncode!=0 or not result['report']['passed']:
            (base/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2));raise RuntimeError('Actual WebView QA failed: '+str(result['report'].get('error')))
        after={t['id']:{k:t.get(k) for k in ('goal','execution','budget','calls','attempts','title')} for t in kb.list('task')}
        after_counts={'tasks':len(kb.list('task')),'sessions':len(kb.list('session'))}
        for _ in range(80):
            if board_service.status(kb,project_id=fixture['project_id'])['status']=='stopped':break
            time.sleep(.1)
        result.update({'source_tasks_unchanged':before_counts==after_counts,'goals_budgets_titles_unchanged':before==after,'source_proof_unchanged':file_hash(Path(fixture['proof']))==fixture['proof_sha256'],'hidden_documents_preserved':all((kb.vault_home/name).is_file() for name in fixture['hidden_paths']),'wiki_marker_persisted':any(fixture['marker'] in p.read_text() for p in kb.vault_home.rglob('*.md')),'backend_stopped':board_service.status(kb,project_id=fixture['project_id'])['status']=='stopped','native_stderr':capture.snapshot(),'fixture_only':True,'model_calls':0})
        result['passed']=all(result[k] for k in ('source_tasks_unchanged','goals_budgets_titles_unchanged','source_proof_unchanged','hidden_documents_preserved','wiki_marker_persisted','backend_stopped'))
        (base/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        if progress:progress.mark('populated.actual_webview_audit','done')
        return result
    except Exception as exc:
        if child and child.poll() is None:child.terminate();child.wait(timeout=10)
        (base/'failure.json').write_text(json.dumps({'error':str(exc),'native_exit':child.poll() if child else None,'native_stderr':capture.snapshot() if capture else None,'feature':'native-qa'},ensure_ascii=False,indent=2)+'\n');raise
    finally:
        if child and child.poll() is None:child.terminate();child.wait(timeout=10)
        try:board_service.stop(kb,project_id=fixture['project_id'])
        except Exception:pass

def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path);parser.add_argument('--qa-only',action='store_true',help='Development diagnostic only; the default gate retains all shipping cases');args=parser.parse_args(argv)
    if sys.platform!='darwin':raise SystemExit('Native verification requires macOS; no browser fallback')
    selected=args.output or os.environ.get('LOOP_NATIVE_VERIFY_OUTPUT')
    output=prepare_output(selected)
    progress=StageLog(output)
    previous_signal=None
    if threading.current_thread() is threading.main_thread():
        previous_signal=signal.getsignal(signal.SIGTERM)
        def interrupted(_number,_frame):raise KeyboardInterrupt('Native verification interrupted')
        signal.signal(signal.SIGTERM,interrupted)
    try:
        with progress.stage('preflight'):
            prepared=preflight_native(output)
        with progress.stage('verification'):
            code=run_verification(output,args.qa_only,progress,prepared)
        if code==0:progress.finish()
        else:progress.fail(RuntimeError('Verification did not pass'))
        return code
    except BaseException as exc:
        progress.fail(exc)
        write_json(output/'run-failure.json',{'passed':False,'error_type':type(exc).__name__,
                   'failure_kind':progress.value.get('failure_kind'),'last_stage':progress.value['current_stage'],
                   'last_completed_stage':progress.value['last_completed_stage'],
                   'last_native_stage':progress.value['last_native_stage'],'fixture_only':True,
                   'physical_gui_input_verified':False})
        raise
    finally:
        if previous_signal is not None:signal.signal(signal.SIGTERM,previous_signal)


def run_verification(output,qa_only,progress,prepared):
    before=engine_digest();results=[]
    for mode in (() if qa_only else ('owned-auto','owned-fixed','reused-fixed','replacement')):
        progress.mark('shipping.'+mode+'.prepare_fixture','start')
        base=output/mode;base.mkdir();home=base/'home';home.mkdir();target=base/'target';target.mkdir()
        kb=KnowledgeBase(base/'kb',vault_home=base/'vault');location=kb.attach(target);project=location['project_id']
        progress.mark('shipping.'+mode+'.prepare_fixture','done')
        entry=target/'.loop/install/loop.py';app=desktop_install.build_app(base/'staged.app',entry,kb.home,kb.vault_home,target_root=target,progress=lambda stage,event:progress.mark('shipping.'+mode+'.'+stage,event))
        from loop_work.desktop_install import build_inputs,configuration
        from loop_work.storage import digest
        progress.mark('shipping.'+mode+'.install_app','start')
        install_links(home,target,desktop_app=app,desktop_build=digest(build_inputs(configuration(entry,kb.home,kb.vault_home,target_root=target))))
        progress.mark('shipping.'+mode+'.install_app','done')
        binary=target/'.loop/Loop Work.app/Contents/MacOS/LoopWork'
        original=None;child=None;nonce=None;capture=None
        try:
            if mode!='owned-auto':
                with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
                config_path=binary.parent.parent/'Resources/desktop-config.json'
                # Startup port is an explicit per-run override, never a secret.
                config=json.loads(config_path.read_text());config['port']=port
                fd,override=tempfile.mkstemp(prefix='loop-work-desktop-',suffix='.json')
                with os.fdopen(fd,'w') as stream:json.dump(config,stream)
                os.chmod(override,0o600);launch=[str(binary),'--config',override]
            else:port=0;launch=[str(binary)]
            if mode=='reused-fixed':original=board_service.start(kb,port,project_id=project)
            progress.mark('shipping.'+mode+'.launch','start')
            child=subprocess.Popen(launch,stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,env={**os.environ,'HOME':str(home),'LOOP_KB_HOME':str(kb.home)})
            capture=BoundedStderr(child.stderr)
            wait_ready(child,time.monotonic()+60)
            progress.mark('shipping.'+mode+'.renderer_ready','done')
            active=board_service.status(kb,project_id=project)
            if active['status']!='running':raise AssertionError('Native helper did not create/adopt scoped backend')
            nonce=active['instance_nonce']
            if original and nonce!=original['instance_nonce']:raise AssertionError('Existing backend was not reused')
            if mode=='replacement':
                board_service.stop(kb,project_id=project,expected_instance_nonce=nonce)
                original=board_service.start(kb,project_id=project)
            progress.mark('shipping.'+mode+'.normal_quit','start')
            terminate(child.pid);child.wait(timeout=20)
            if child.returncode!=0:raise AssertionError('Normal native quit failed')
            for _ in range(50):
                status=board_service.status(kb,project_id=project)
                if original or status['status']=='stopped':break
                time.sleep(.1)
            if original:
                if status['status']!='running' or status['instance_nonce']!=original['instance_nonce']:raise AssertionError('Reused/replacement backend was stopped')
            elif status['status']!='stopped':raise AssertionError('Owned helper backend remained running')
            if kb.list('task') or kb.list('session'):raise AssertionError('GUI created a task or session')
            progress.mark('shipping.'+mode+'.normal_quit','done')
            results.append({'case':mode,'evidence_kind':'shipping_native_lifecycle','physical_gui_input_verified':False,'passed':True,'renderer_ready':True,'native_exit':child.returncode,'backend_after_quit':status['status'],'nonce_before':nonce,'nonce_after':status.get('instance_nonce'),'app_pid':child.pid,'app_exited':child.poll() is not None,'tasks':0,'sessions':0,'binary_pin':file_hash(binary),'native_stderr':capture.snapshot()})
        except Exception as exc:
            (output/'failure.json').write_text(json.dumps({'passed':False,'case':mode,'error_type':type(exc).__name__,'error':str(exc),'completed_cases':results,'native_exit':child.poll() if child else None,'native_stderr':capture.snapshot() if capture else None,'source_before':before,'source_after':engine_digest()},ensure_ascii=False,indent=2)+'\n')
            raise
        finally:
            if child and child.poll() is None:
                # Cleanup exact test child only; never claim forced cleanup normal quit.
                child.terminate()
                try:child.wait(timeout=10)
                except subprocess.TimeoutExpired:child.kill();child.wait()
            try:board_service.stop(kb,project_id=project)
            except Exception:pass
    populated=verify_populated_native(output,progress,prepared)
    after=engine_digest();result={'passed':(qa_only or len(results)==4) and before==after and populated['passed'],'shipping_cases_verified':not qa_only,'populated_native_qa':{'passed':populated['passed'],'report':str(output/'populated-native-qa/result.json'),'feature':'native-qa','shipping_binary':False},'cases':results,'source_before':before,'source_after':after,'pins_unchanged':before==after,'physical_gui_input_verified':False,'evidence_types':{'shipping_lifecycle':not qa_only,'test_only_native_webview_actual_api':True,'composition':'synthetic_events','physical_input':False}}
    (output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'passed':result['passed'],'summary':str(output/'summary.json')}));return 0 if result['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
