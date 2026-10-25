"""macOS window handoff; capability URLs stay in the helper's stdout pipe."""
from __future__ import annotations
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from .storage import LoopError, file_hash

CONFIG_NAME='desktop-config.json'

def _config_json(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size>1024*1024:
            raise LoopError('앱 설정 또는 소유 기록이 일반 파일이 아닙니다.')
        raw=os.read(fd,1024*1024+1)
        if len(raw)>1024*1024: raise LoopError('앱 설정 또는 소유 기록의 크기 제한을 초과했습니다.')
        value=json.loads(raw)
        if not isinstance(value,dict): raise LoopError('앱 설정 또는 소유 기록은 JSON 객체여야 합니다.')
        return value
    finally: os.close(fd)

def descriptor(value):
    if not isinstance(value,dict) or set(value)!={'version','url','instance_nonce','owned'} or type(value.get('version')) is not int or value['version']!=1 or type(value.get('owned')) is not bool:
        raise LoopError('앱 연결 정보가 올바르지 않습니다.')
    if not isinstance(value.get('url'),str): raise LoopError('앱 연결 주소가 올바르지 않습니다.')
    parts=urlsplit(value['url'])
    try: port=parts.port
    except ValueError: raise LoopError('앱 연결 주소가 올바르지 않습니다.')
    if parts.scheme!='http' or parts.hostname!='127.0.0.1' or not port or parts.username or parts.password or parts.path!='/' or parts.query or not parts.fragment or not isinstance(value.get('instance_nonce'),str) or len(value['instance_nonce'])<32:
        raise LoopError('앱 연결 주소 또는 인스턴스를 확인할 수 없습니다.')
    return value


def project_for_root(knowledge,target_root,project_id=None,*,create=False):
    """Use the KB's existing checkout key; never invent a second identity."""
    from .knowledge import project_root,disk_identity
    from .storage import digest
    root=project_root(target_root)
    location=knowledge.get('location','checkout-'+digest(disk_identity(root))[:24],required=False)
    if location is None:
        if project_id is not None:raise LoopError('아직 연결되지 않은 TARGET에 임의 프로젝트를 지정할 수 없습니다. 프로젝트 지정 없이 먼저 시작하세요.')
        if not create: return None,True
        location=knowledge.attach(root)
    attached=location.get('project_id')
    if not isinstance(attached,str):raise LoopError('설치된 프로젝트의 연결 기록을 확인할 수 없습니다.')
    if project_id is not None and project_id!=attached:
        raise LoopError('설치한 앱의 프로젝트 범위를 바꿀 수 없습니다.')
    return attached,False


def effective_project(knowledge,project_id=None,*,entrypoint=None,create=False):
    entry=Path(entrypoint or sys.argv[0]).expanduser().resolve()
    if entry.parent.name!='install' or entry.parent.parent.name!='.loop':return project_id,False
    app=entry.parent.parent/'Loop Work.app'
    # Server-only low-level installations keep their original CLI contract.
    if not os.path.lexists(app):
        manifest=_config_json(entry.parent/'manifest.json')
        if 'desktop' in manifest:raise LoopError('설치 기록에 있는 TARGET 앱이 없습니다. 다시 설치한 뒤 실행하세요.')
        return project_id,False
    installed=_config_json(resolve_app(entry)/'Contents/Resources'/CONFIG_NAME)
    if not isinstance(installed.get('target_root'),str):raise LoopError('설치한 앱의 프로젝트 경로를 확인할 수 없습니다.')
    return project_for_root(knowledge,installed['target_root'],project_id,create=create)


def helper(knowledge,port=0,session_id=None,task_id=None,project_id=None,*,target_root=None,input_stream=None,output_stream=None):
    from . import board_service
    incoming=input_stream if input_stream is not None else sys.stdin
    outgoing=output_stream if output_stream is not None else sys.stdout
    if target_root is not None:
        project_id,_=project_for_root(knowledge,target_root,project_id,create=True)
    result=board_service.start(knowledge,port,session_id,task_id,project_id,cleanup_on_failure=True)
    owned=not result['reused']
    try:
        value=descriptor({'version':1,'url':result['url'],'instance_nonce':result['instance_nonce'],'owned':owned})
        outgoing.write(json.dumps(value,ensure_ascii=False)+'\n');outgoing.flush()
        # Only this pipe's owner controls lifetime; no arbitrary PID signalling.
        while incoming.read(4096): pass
    finally:
        if owned:
            board_service.stop(knowledge,session_id,task_id,project_id,expected_instance_nonce=result['instance_nonce'])
    return 0


def resolve_app(entrypoint=None):
    entry=Path(entrypoint or sys.argv[0]).expanduser().resolve()
    runtime=Path(__file__).resolve().parent.parent
    user_entry=Path.home()/'.local/share/loop-work/install/loop.py'
    if entry.parent.name=='install' and entry.parent.parent.name=='.loop':
        candidates=[(entry.parent.parent/'Loop Work.app',entry,'project')]
    elif entry==user_entry or entry in (runtime/'scripts/loop.py',runtime/'skills/loop-work/loop.py'):
        candidates=[(Path.home()/'Applications/Loop Work.app',user_entry,'user')]
    else:
        candidates=[]
    for app,wrapper,scope in candidates:
        config=app/'Contents/Resources'/CONFIG_NAME
        try:
            installed=_config_json(config)
            manifest=_config_json(wrapper.parent/'manifest.json')
            root=wrapper.parents[2] if scope=='project' else Path.home()
            relative=str(wrapper.relative_to(root))
            from .desktop_install import inspect_bundle
            owned=manifest.get('desktop')
            if not isinstance(owned,dict) or owned.get('path')!=str(app.relative_to(root)) or owned.get('files')!=inspect_bundle(app): continue
            if (app/'Contents/MacOS/LoopWork').is_file() and manifest.get('kind')=='links' and manifest.get('scope')==scope and manifest.get('source')==str(runtime) and manifest.get('root')==str(root) and manifest.get('files',{}).get(relative)==file_hash(wrapper) and (wrapper.parent/'runtime').resolve()==runtime and installed.get('entrypoint')==str(wrapper):
                return app
        except (OSError,ValueError,TypeError,LoopError): pass
    raise LoopError('이 진입점의 Loop Work 앱이 없습니다. make install 설치를 확인하세요.')


def open_app(knowledge,port=0,session_id=None,task_id=None,project_id=None,*,entrypoint=None):
    if sys.platform!='darwin':
        raise LoopError('데스크톱 앱은 macOS에서만 지원합니다. 이 환경에서는 비 GUI 관리 명령을 사용할 수 있습니다.')
    app=resolve_app(entrypoint)
    installed=_config_json(app/'Contents/Resources'/CONFIG_NAME)
    if installed.get('target_root') is not None:
        project_id,_=project_for_root(knowledge,installed['target_root'],project_id,create=True)
    entry=Path(entrypoint or sys.argv[0]).expanduser().resolve()
    if not entry.is_file(): raise LoopError('설치된 Python 진입점을 확인할 수 없습니다.')
    config={'version':1,'python':installed['python'],'entrypoint':installed['entrypoint'],
            'knowledge_home':str(knowledge.home.resolve()),'vault_home':str(knowledge.vault_home) if knowledge.vault_home is not None else None,
            'project_id':project_id if project_id is not None else installed.get('project_id'),'target_root':installed.get('target_root'),'session_id':session_id,'task_id':task_id,'port':port}
    default_scope=not any((port,session_id,task_id,project_id,os.environ.get('LOOP_KB_HOME')))
    from .knowledge import default_home
    from .workspace import vault
    expected_kb=Path(installed['knowledge_home']) if installed.get('knowledge_home') else default_home()
    expected_vault=Path(installed['vault_home']) if installed.get('vault_home') else vault()
    same_kb=knowledge.home.resolve()==expected_kb.resolve()
    same_vault=knowledge.vault_home is not None and Path(knowledge.vault_home).resolve()==expected_vault.resolve()
    if default_scope and same_kb and same_vault:
        result=subprocess.run(['/usr/bin/open','-n',str(app)],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
        if result.returncode: raise LoopError('Loop Work 앱을 열지 못했습니다.')
        return {'status':'opening','application':'Loop Work','new_window':True}
    # No capability, source text or credentials enter this short-lived file.
    fd,name=tempfile.mkstemp(prefix='loop-work-desktop-',suffix='.json')
    try:
        os.fchmod(fd,stat.S_IRUSR|stat.S_IWUSR)
        with os.fdopen(fd,'w',encoding='utf-8') as stream:json.dump(config,stream)
        result=subprocess.run(['/usr/bin/open','-n',str(app),'--args','--config',name],stdin=subprocess.DEVNULL,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15)
        if result.returncode: raise LoopError('Loop Work 앱을 열지 못했습니다. 설치 상태를 확인하세요.')
    except Exception:
        Path(name).unlink(missing_ok=True)
        raise
    # The app consumes and removes the override after parsing; do not race it.
    return {'status':'opening','application':'Loop Work','scope':{'session_id':session_id,'task_id':task_id,'project_id':project_id}}
