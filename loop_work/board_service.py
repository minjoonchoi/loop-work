"""Bounded local board lifecycle; never signal a PID found in a state file."""
from __future__ import annotations
from contextlib import contextmanager
import fcntl
import http.client
import json
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
import threading
import time

from .storage import LoopError, digest


def _directory(path):
    for parent in [*reversed(path.parents),path]:
        if parent.is_symlink() or parent.exists() and not parent.is_dir():
            raise LoopError('Unsafe board service directory: ' + str(parent))
    path.mkdir(parents=True,exist_ok=True,mode=0o700)


@contextmanager
def _parent(path):
    path=Path(path).absolute();opened=[]
    try:
        fd=os.open(path.anchor,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW);opened.append(fd)
        for part in path.parts[1:-1]:
            fd=os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd);opened.append(fd)
        yield fd
    finally:
        for fd in reversed(opened): os.close(fd)


def _open(path,flags,mode=0o600):
    with _parent(path) as parent:
        for attempt in range(3):
            try:
                return os.open(path.name,flags|os.O_NOFOLLOW|os.O_NONBLOCK,mode,dir_fd=parent)
            except FileNotFoundError:
                if not flags & os.O_CREAT or attempt==2:
                    raise
                # Concurrent first creation can expose transient leaf absence.
                # Retain the same no-follow directory descriptor on every retry.
                time.sleep(0.01)


def _read(path):
    try:
        fd=_open(path,os.O_RDONLY)
    except FileNotFoundError:
        return None
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or info.st_size>32768 or stat.S_IMODE(info.st_mode)!=0o600:
            raise LoopError('Unsafe board service state; preserved')
        data=os.read(fd,32769)
        if len(data)>32768:
            raise LoopError('Board service state too large')
        value=json.loads(data)
        if not isinstance(value,dict):
            raise LoopError('Invalid board service state')
        return value
    except (ValueError,UnicodeError) as exc:
        raise LoopError('Invalid board service JSON; preserved') from exc
    finally:
        os.close(fd)


def _write(path,value):
    _directory(path.parent)
    _read(path)
    with _parent(path) as parent:
        temporary='.board-state-'+secrets.token_hex(16)
        fd=os.open(temporary,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as stream:
                json.dump(value,stream,ensure_ascii=False,sort_keys=True);stream.write('\n');stream.flush();os.fsync(stream.fileno())
            _read(path)
            os.replace(temporary,path.name,src_dir_fd=parent,dst_dir_fd=parent)
            os.fsync(parent)
        finally:
            try: os.unlink(temporary,dir_fd=parent)
            except FileNotFoundError: pass


@contextmanager
def _lock(directory):
    _directory(directory)
    fd=_open(directory/'lock',os.O_WRONLY|os.O_CREAT)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600:
            raise LoopError('Unsafe board service lock; preserved')
        deadline=time.monotonic()+15
        while True:
            try:
                fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB);break
            except BlockingIOError:
                if time.monotonic()>=deadline: raise LoopError('Board lifecycle command is busy; retry status')
                time.sleep(0.05)
        yield
    finally:
        os.close(fd)


def configuration(knowledge,session_id=None,task_id=None,project_id=None):
    return dict(knowledge_home=str(knowledge.home),vault_home=str(knowledge.vault_home) if knowledge.vault_home is not None else None,
                session_id=session_id,task_id=task_id,project_id=project_id,
                runtime=str(Path(__file__).resolve().parent.parent))


def _paths(knowledge,config):
    key=digest(config)
    directory=knowledge.home/'board-service'
    return key,directory,directory/(key+'.json')


def _validate(record,key,config):
    if (not isinstance(record,dict) or type(record.get('version')) is not int or record.get('version')!=1 or record.get('config_id')!=key or record.get('config')!=config
            or record.get('status') not in ('starting','running','stopped','failed')
            or not isinstance(record.get('instance_nonce'),str) or len(record['instance_nonce'])<32
            or type(record.get('pid')) is not int or record['pid']<0):
        raise LoopError('Board service identity changed; state preserved')
    if record['status']=='running' and (record['pid']<1 or type(record.get('port')) is not int or not 1<=record['port']<=65535 or not isinstance(record.get('capability'),str)):
        raise LoopError('Invalid running board service identity')
    return record


def _request(record,stop=False):
    """Only an authenticated live instance may confirm or stop itself."""
    connection=http.client.HTTPConnection('127.0.0.1',record['port'],timeout=2)
    origin='http://127.0.0.1:'+str(record['port'])
    headers={'Host':'127.0.0.1:'+str(record['port']),'Origin':origin,'X-Loop-Capability':record['capability']}
    body=None
    if stop:
        body=json.dumps({'instance_nonce':record['instance_nonce']});headers['Content-Type']='application/json'
    try:
        connection.request('POST' if stop else 'GET','/api/_service',body,headers)
        response=connection.getresponse();raw=response.read(4097)
        if response.status!=200 or len(raw)>4096:
            raise LoopError('Board did not authenticate this managed instance')
        value=json.loads(raw)
        if not isinstance(value,dict):
            raise LoopError('Invalid managed board response; no process was signalled')
        expected={k:record[k] for k in ('instance_nonce','pid','config_id')}
        if any(value.get(k)!=v for k,v in expected.items()) or (stop and value.get('stopping') is not True):
            raise LoopError('Board service identity mismatch; no process was signalled')
        return value
    except (OSError,http.client.HTTPException,ValueError,TypeError) as exc:
        raise LoopError('Board instance cannot be authenticated; no process was signalled') from exc
    finally:
        connection.close()


def _public(record,status=None,**extra):
    result={k:record[k] for k in ('pid','config_id','instance_nonce')}
    result['status']=status or record['status']
    if record.get('port'):
        result.update(port=record['port'],url='http://127.0.0.1:'+str(record['port'])+'/#'+record['capability'])
    result.update(extra)
    return result


def status(knowledge,session_id=None,task_id=None,project_id=None):
    config=configuration(knowledge,session_id,task_id,project_id);key,directory,path=_paths(knowledge,config)
    # Absence queries create no directories or lifecycle files.
    if not directory.exists(): return {'status':'stopped','config_id':key}
    _directory(directory);record=_read(path)
    if record is None: return {'status':'stopped','config_id':key}
    _validate(record,key,config)
    if record['status']=='running':
        try: _request(record)
        except LoopError as exc: return _public(record,'unknown',error=str(exc))
    return _public(record)


def start(knowledge,port=0,session_id=None,task_id=None,project_id=None,*,readiness_timeout=12,cleanup_on_failure=False):
    if type(port) is not int or not 0<=port<=65535: raise LoopError('Board port must be between 0 and 65535')
    if knowledge.vault_home is None: raise LoopError('Board requires an explicit vault for a custom knowledge store')
    config=configuration(knowledge,session_id,task_id,project_id);key,directory,path=_paths(knowledge,config)
    with _lock(directory):
        old=_read(path)
        if old is not None:
            _validate(old,key,config)
            if old['status']=='running':
                _request(old)
                if port and port!=old['port']: raise LoopError('A managed board already runs on a different port')
                result=_public(old,reused=True)
                return result
            if old['status']=='starting': raise LoopError('Earlier board startup is unresolved; inspect status before retrying')
        nonce=secrets.token_urlsafe(32)
        claim=dict(version=1,status='starting',config_id=key,config=config,instance_nonce=nonce,pid=0,requested_port=port)
        argv=[sys.executable,'-B','-m','loop_work.board_service','--child',str(path),nonce]
        env={**os.environ,'PYTHONPATH':config['runtime'],'PYTHONDONTWRITEBYTECODE':'1'}
        log=directory/(key+'.log')
        fd=_open(log,os.O_WRONLY|os.O_APPEND|os.O_CREAT)
        try:
            info=os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1 or stat.S_IMODE(info.st_mode)!=0o600:
                raise LoopError('Unsafe board service log; preserved')
            _write(path,claim)
            try:
                child=subprocess.Popen(argv,cwd=config['runtime'],env=env,stdin=subprocess.DEVNULL,stdout=fd,stderr=fd,start_new_session=True,close_fds=True)
            except OSError:
                _write(path,{**claim,'status':'failed','error':'launch failed'})
                raise
        finally:
            os.close(fd)
        # Reap only the Popen handle created here; no PID-file process signalling.
        threading.Thread(target=child.wait,daemon=True).start()
        try:
            deadline=time.monotonic()+readiness_timeout
            while time.monotonic()<deadline:
                current=_read(path)
                if current is None or current.get('instance_nonce')!=nonce: raise LoopError('Board readiness identity changed')
                _validate(current,key,config)
                if current['status']=='running':
                    _request(current);result=_public(current,reused=False)
                    return result
                if current['status']=='failed' or child.poll() is not None:
                    if current == claim:
                        _write(path,{**claim,'status':'failed','pid':child.pid,'error':'child exited before readiness'})
                    raise LoopError('Board startup failed; inspect '+str(log))
                time.sleep(0.05)
            raise LoopError('Board readiness timed out; owned startup cleanup required' if cleanup_on_failure else 'Board readiness timed out; inspect status; no process was signalled')
        except BaseException:
            if not cleanup_on_failure:
                raise
            # Only this newly-created Popen handle is signalled, never a PID
            # loaded from a state file. No late-ready orphan survives failure.
            if child.poll() is None:
                child.terminate()
                try: child.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    child.kill(); child.wait(timeout=2)
            current=_read(path)
            if current is not None and current.get('instance_nonce')==nonce:
                _write(path,{**current,'status':'failed','error':'owned startup did not complete'})
            raise


def stop(knowledge,session_id=None,task_id=None,project_id=None,*,expected_instance_nonce=None):
    config=configuration(knowledge,session_id,task_id,project_id);key,directory,path=_paths(knowledge,config)
    with _lock(directory):
        record=_read(path)
        if record is None: return {'status':'stopped','config_id':key,'reused':True}
        _validate(record,key,config)
        if expected_instance_nonce is not None and record['instance_nonce']!=expected_instance_nonce:
            raise LoopError('Board instance was replaced; replacement was not stopped')
        if record['status'] in ('stopped','failed'): return _public(record,'stopped',reused=True)
        if record['status']!='running': raise LoopError('Board startup is unresolved; no process was signalled')
        _request(record);_request(record,stop=True)
        deadline=time.monotonic()+4
        while time.monotonic()<deadline:
            current=_read(path)
            if current is None or current.get('instance_nonce')!=record['instance_nonce']:
                raise LoopError('Board shutdown state changed; no process was signalled')
            _validate(current,key,config)
            if current['status']=='stopped':
                return _public(current,reused=False)
            time.sleep(0.05)
        raise LoopError('Board accepted shutdown but completion is unconfirmed; inspect status')


def _child(path,nonce):
    from .knowledge import KnowledgeBase
    from .board_ui import make_server
    path=Path(path);_directory(path.parent)
    claim=_read(path)
    if claim is None or claim.get('instance_nonce')!=nonce or claim.get('status')!='starting':
        raise LoopError('Board startup claim changed')
    config=claim['config'];_validate(claim,claim['config_id'],config)
    knowledge=KnowledgeBase(config['knowledge_home'],vault_home=config['vault_home'])
    try:
        try: knowledge.sync_vault()
        except Exception: pass  # Optional export diagnostics never prevent serving existing notes.
        identity=dict(instance_nonce=nonce,pid=os.getpid(),config_id=claim['config_id'])
        server=make_server(knowledge,claim['requested_port'],config['session_id'],config['task_id'],vault_home=config['vault_home'],project_id=config['project_id'],management=identity)
        current=_read(path)
        if current!=claim: server.server_close();raise LoopError('Board startup claim changed')
        running={**claim,**identity,'status':'running','port':server.server_port,'capability':server.capability_token}
        _write(path,running)
        try: server.serve_forever(poll_interval=0.1)
        finally:
            server.server_close()
            # Never erase a replacement instance's state.
            current=_read(path)
            if current==running: _write(path,{**running,'status':'stopped'})
    except Exception as exc:
        current=_read(path)
        if current==claim: _write(path,{**claim,'status':'failed','error':type(exc).__name__})
        raise


if __name__=='__main__':
    if len(sys.argv)!=4 or sys.argv[1]!='--child': raise SystemExit(2)
    _child(sys.argv[2],sys.argv[3])
