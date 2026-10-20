"""Read managed vault Markdown; runtime records remain action authority."""
from __future__ import annotations

from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat

from .human import HumanDesk
from .storage import LoopError, digest, now
from .contract import identifier
from .vault_layout import validate_relative, validate_metadata, validate_document_path, validate_mapping

MAX_NOTE = 512 * 1024
MAX_MANIFEST = 2 * 1024 * 1024
MAX_DOCUMENTS = 500
MAX_TOTAL = 8 * 1024 * 1024
SAFE = r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}'
TASK = re.compile(r'^projects/(' + SAFE + r')/tasks/(' + SAFE + r')/current\.md$')
HISTORY = re.compile(r'^projects/(' + SAFE + r')/tasks/(' + SAFE + r')/(interim|final)/([A-Za-z0-9_-]{1,160})\.md$')
REQUEST = re.compile(r'^projects/(' + SAFE + r')/tasks/(' + SAFE + r')/records/human-request/(' + SAFE + r')\.md$')


def _read(root, name, limit):
    """Open each directory without following links, then read a bounded file."""
    relative = PurePosixPath(name)
    if relative.is_absolute() or str(relative) != name or '..' in relative.parts or '\\' in name:
        raise LoopError('Unsafe board document path')
    root = Path(root).absolute()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    try:
        with ExitStack() as opened:
            fd = os.open(root.anchor, flags); opened.callback(os.close, fd)
            for part in (*root.parts[1:], *relative.parts[:-1]):
                fd = os.open(part, flags, dir_fd=fd); opened.callback(os.close, fd)
            source = os.open(relative.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            opened.callback(os.close, source)
            info = os.fstat(source)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
                raise LoopError('Board document must be a bounded regular file without hard links')
            pieces = []; count = 0
            while True:
                block = os.read(source, min(65536, limit + 1 - count))
                if not block:
                    break
                pieces.append(block); count += len(block)
                if count > limit:
                    raise LoopError('Board document exceeds size limit')
            raw = b''.join(pieces)
            modepin = digest({'content': hashlib.sha256(raw).hexdigest(), 'executable': bool(info.st_mode & 0o111)})
            return raw.decode('utf-8'), modepin
    except (OSError, UnicodeError, ValueError) as exc:
        raise LoopError('Board document unavailable or unsafe: ' + name) from exc


def _metadata(body):
    lines=body.split('\n',3)
    if len(lines)==4 and lines[0]=='---' and lines[1].startswith('loop_work: ') and lines[2]=='---':
        try:
            return json.loads(lines[1][len('loop_work: '):]),lines[3]
        except (ValueError,RecursionError):
            pass
    return None,body


def _descriptor(name, meta=None):
    if meta is not None:
        validate_metadata(meta)
        validate_document_path(name,meta)
        return {key:meta[key] for key in ('kind','id','role','task_id','project_id')}
    task=TASK.fullmatch(name); request=REQUEST.fullmatch(name); history=HISTORY.fullmatch(name)
    if task:
        return {'kind':'task','id':task[2],'role':'current','task_id':task[2],'project_id':task[1]}
    if request:
        return {'kind':'human-request','id':request[3],'role':'human-request','task_id':request[2],'project_id':request[1]}
    if history:
        return {'kind':'task','id':history[2],'role':history[3],'task_id':history[2],'project_id':history[1]}
    return None


def _actionable(record):
    return (not record.get('superseded_by') and (record.get('status') in ('pending', 'declined', 'failed') or
            record.get('status') == 'answered' and record.get('action') == 'resume_task' and
            record.get('execution') is None and (record.get('response') if isinstance(record.get('response'),dict) else {}).get('decision') in ('approve', 'resolved')))


class Board:
    def __init__(self, knowledge, vault_home=None):
        self.knowledge = knowledge
        selected = vault_home if vault_home is not None else knowledge.vault_home
        if selected is None:
            raise LoopError('Board requires an enabled knowledge vault or explicit --vault path')
        self.root = Path(selected).expanduser().absolute()

    def _runtime(self, kind, key, db=None):
        if db is None:
            return self.knowledge.get(kind, key, required=False)
        row = db.execute('SELECT body FROM records WHERE kind=? AND id=?', (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    def _manifest(self):
        text, _ = _read(self.knowledge.home, 'vault-owned.json', MAX_MANIFEST)
        try:
            manifest = json.loads(text)
        except (ValueError, RecursionError) as exc:
            raise LoopError('Malformed board vault ownership manifest') from exc
        if (not isinstance(manifest, dict) or manifest.get('version') != 1 or manifest.get('vault') != str(self.root)
                or not isinstance(manifest.get('files'), dict) or not all(isinstance(name,str) for name in manifest['files'])):
            raise LoopError('Board vault ownership manifest does not match this vault')
        for name in manifest['files']:
            validate_relative(name)
        if 'layout_version' in manifest and manifest['layout_version']!=2:
            raise LoopError('Unsupported vault layout version')
        if not isinstance(manifest.get('paths',{}),dict) or not isinstance(manifest.get('documents',{}),dict):
            raise LoopError('Malformed vault layout inventory')
        for key,name in manifest.get('paths',{}).items():
            if not isinstance(key,str):
                raise LoopError('Malformed vault logical document key')
            validate_mapping(key,name)
        if len(set(manifest.get('paths',{}).values()))!=len(manifest.get('paths',{})):
            raise LoopError('Vault logical document paths must be distinct')
        for name,entry in manifest.get('documents',{}).items():
            validate_relative(name)
            if not isinstance(entry,dict) or set(entry)!={'kind','id','role','task_id','project_id'}:
                raise LoopError('Malformed vault document descriptor')
            validate_metadata({'version':2,'knowledge_home':str(self.knowledge.home),'record':{'id':entry['id']},**entry})
        return manifest

    def _discover(self):
        """Traverse only the fixed task layout, with no followed directory links."""
        found=[]; visited=0
        flags=os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        def descend(fd, parts):
            nonlocal visited
            if len(parts)==4:
                with os.scandir(fd) as entries:
                    for entry in entries:
                        visited+=1
                        if visited>MAX_DOCUMENTS*20:
                            raise LoopError('Board discovery entry limit reached')
                        if entry.name=='current.md' or entry.name.startswith('현재-') and entry.name.endswith('.md'):
                            found.append('/'.join(parts+[entry.name]))
                return
            expected='projects' if not parts else 'tasks' if len(parts)==2 else None
            with os.scandir(fd) as entries:
                for entry in entries:
                    visited+=1
                    if visited>MAX_DOCUMENTS*20:
                        raise LoopError('Board discovery entry limit reached')
                    if expected is not None and entry.name!=expected:
                        continue
                    if expected is None and re.fullmatch(SAFE,entry.name) is None:
                        if '--' not in entry.name:
                            continue
                        try:
                            validate_relative(entry.name)
                        except LoopError:
                            continue
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    try:
                        child=os.open(entry.name,flags,dir_fd=fd)
                    except OSError:
                        continue
                    try:
                        descend(child,parts+[entry.name])
                    finally:
                        os.close(child)
        with ExitStack() as opened:
            fd=os.open(self.root.anchor,flags); opened.callback(os.close,fd)
            for part in self.root.parts[1:]:
                fd=os.open(part,flags,dir_fd=fd); opened.callback(os.close,fd)
            descend(fd,[])
        return found

    def _history(self, task_id, body_path=None, warnings=None):
        documents=[]; total=0; count=0
        try:
            manifest=self._manifest(); files=manifest['files']
        except LoopError as exc:
            if warnings is not None:
                warnings.append(str(exc))
            return documents
        for name, owned in sorted(files.items()):
            entry=manifest.get('documents',{}).get(name) or _descriptor(name)
            if not entry or entry['role'] not in ('interim','final') or entry['task_id']!=task_id or body_path is not None and name!=body_path:
                continue
            count+=1
            if count>MAX_DOCUMENTS:
                break
            try:
                body,pin=_read(self.root,name,MAX_NOTE)
                meta,display=_metadata(body)
                if meta is not None and isinstance(meta,dict) and meta.get('version')==2:
                    actual=_descriptor(name,meta)
                    if actual!=entry or meta['knowledge_home']!=str(self.knowledge.home.resolve()):
                        raise LoopError('Historical vault metadata does not match its scoped inventory')
                    body=display
                elif not HISTORY.fullmatch(name):
                    raise LoopError('Missing historical vault metadata')
            except LoopError as exc:
                if warnings is not None:
                    warnings.append(str(exc))
                continue
            total+=len(body.encode('utf-8'))
            if total>MAX_TOTAL:
                break
            documents.append({'path':name,'revision':pin,'modified':pin!=owned,'kind':entry['role'],'role':entry['role'],
                              'body':body,'writable':False})
        return documents

    def sync_status(self, scoped=False):
        if not scoped:
            try:
                return self.knowledge.vault_status()
            except Exception:
                # Optional diagnostics must never erase a committed receipt.
                return {'status':'error','errors':['Optional vault diagnostics unavailable; committed actions must not be replayed']}
        # Export diagnostics are global and may contain unrelated private paths.
        return {'status':'withheld', 'diagnostics':'Global export diagnostics omitted for scoped board'}

    def _scan(self, db=None):
        warnings=[]; rows={}; total=0; count=0; unavailable=set()
        try:
            manifest=self._manifest(); files=dict(manifest['files']); descriptions=manifest.get('documents',{})
        except LoopError:
            files={}; descriptions={}
            warnings.append('Vault ownership inventory unavailable; discovered documents are read-only')
        try:
            discovered=self._discover()
        except (LoopError,OSError):
            discovered=[]
            warnings.append('Some vault discovery entries were unavailable or exceeded limits')
        for name in discovered:
            files.setdefault(name,None)
        for name,owned_pin in sorted(files.items()):
            entry=descriptions.get(name) or _descriptor(name)
            if entry and (entry['kind'],entry['role']) not in (('task','current'),('human-request','human-request')):
                continue
            if not entry and name not in discovered:
                continue
            if count>=MAX_DOCUMENTS:
                warnings.append('Board document limit reached'); break
            count+=1
            try:
                raw,pin=_read(self.root,name,MAX_NOTE)
                total+=len(raw.encode('utf-8'))
                if total>MAX_TOTAL:
                    warnings.append('Board total document limit reached'); break
            except LoopError as exc:
                warnings.append(str(exc))
                if entry:
                    unavailable.add((entry['kind'],entry['id']))
                continue
            meta,body=_metadata(raw); record={}; errors=[]; valid=False
            try:
                if isinstance(meta,dict) and meta.get('version')==2:
                    actual=_descriptor(name,meta)
                    if entry is not None and entry!=actual:
                        raise LoopError('Vault document descriptor disagrees with its metadata')
                    entry=actual
                    if (entry['kind'],entry['role']) not in (('task','current'),('human-request','human-request')):
                        continue
                    record=meta['record']
                    valid=meta['knowledge_home']==str(self.knowledge.home.resolve())
                    if owned_pin is not None and descriptions.get(name)!=actual:
                        valid=False
                elif entry is not None and isinstance(meta,dict):
                    record=meta.get('record')
                    valid=(set(meta)=={'version','kind','id','knowledge_home','record'} and type(meta['version']) is int
                           and meta['version']==1 and meta['kind']==entry['kind'] and meta['id']==entry['id']
                           and meta['knowledge_home']==str(self.knowledge.home.resolve()) and isinstance(record,dict))
                if entry is None:
                    raise LoopError('Missing or invalid vault task metadata')
                if not isinstance(record,dict):
                    record={}
                valid=valid and record.get('id')==entry['id']
                if entry['kind']=='task':
                    valid=valid and entry['task_id']==entry['id'] and entry['project_id'] in record.get('project_ids',[])
                else:
                    valid=valid and record.get('task_id')==entry['task_id']
            except (LoopError,TypeError,ValueError) as exc:
                valid=False
                if entry is None:
                    warnings.append('Malformed discovered vault document: '+name); continue
            kind,key=entry['kind'],entry['id']
            if not isinstance(record,dict):
                record={}
            if not valid:
                errors.append('Malformed or foreign vault metadata; document is read-only')
            current=self._runtime(kind,key,db)
            fresh=valid and current is not None and current==record
            if not fresh:
                errors.append('Vault record does not match current runtime authority')
            modified=owned_pin!=pin
            if modified:
                errors.append('User-edited vault document differs from its managed pin')
            row={'kind':kind,'id':key,'role':entry['role'],'record':record,'path':name,'body':body,'revision':pin,'vault_revision':pin,
                 'modified':modified,'fresh':fresh,'writable':valid and fresh and owned_pin is not None and not modified,
                 'warnings':errors,'documents':[{'path':name,'revision':pin,'role':entry['role']}],
                 '_task':entry['task_id'],'_projects':{entry['project_id']}}
            group=(kind,key)
            if group in rows:
                first=rows[group]; first['documents'].extend(row['documents']); first['_projects'].update(row['_projects'])
                if first['record']!=record or first['body']!=body or not row['writable']:
                    first['writable']=False
                    first['warnings'].append('Conflicting or modified per-project document copies')
                first['modified']=first['modified'] or modified; first['fresh']=first['fresh'] and fresh
            else:
                rows[group]=row
        for key in unavailable:
            if key in rows:
                rows[key]['writable']=False
                rows[key]['warnings'].append('Another retained document copy is unavailable')
        for row in rows.values():
            row['revision'] = row['vault_revision'] = digest(row['documents'])
        for row in rows.values():
            if row['kind'] != 'human-request':
                continue
            parent = rows.get(('task',row['_task']))
            if parent is None or not parent['writable'] or not row['_projects'].issubset(parent['_projects']):
                row['writable'] = False
                row['warnings'].append('Current task vault metadata is missing, stale or modified')
            row['revision'] = row['vault_revision'] = digest([row['documents'], parent['documents'] if parent else None])
        return rows, warnings

    @staticmethod
    def _public(row):
        return {key:value for key,value in row.items() if not key.startswith('_')}

    def list(self, session_id=None, task_id=None, include_closed=False):
        try:
            rows, warnings = self._scan()
        except LoopError as exc:
            return {'tasks':[],'requests':[],'notes':[],'warnings':['Vault documents unavailable'] if session_id is not None or task_id is not None else [str(exc)],
                    'status':{'vault':str(self.root),'status':'unavailable'},'vault_status':self.sync_status(session_id is not None or task_id is not None)}
        if session_id is not None or task_id is not None:
            warnings = ['Some vault documents were unavailable'] if warnings else []
        selected = lambda row: ((session_id is None or row['record'].get('session_id') == session_id)
                                and (task_id is None or row['_task'] == task_id))
        tasks = [self._public(row) for row in rows.values() if row['kind']=='task' and selected(row)]
        requests = [self._public(row) for row in rows.values() if row['kind']=='human-request' and selected(row)
                    and (include_closed or _actionable(row['record']))]
        for task in tasks:
            try:
                task['documents'] = task['documents'] + [{key:value for key,value in item.items() if key!='body'} for item in self._history(task['id'], warnings=task['warnings'])]
            except LoopError as exc:
                warnings.append(str(exc))
            task['control'] = self._control_view(task)
            task['requests'] = [row for row in requests if row['record'].get('task_id') == task['id']]
        return {'tasks':tasks,'requests':requests,'notes':[],'warnings':warnings,
                'status':{'vault':str(self.root),'status':'partial' if warnings else 'ready'},'vault_status':self.sync_status(session_id is not None or task_id is not None)}

    def show(self, identifier, kind='human-request'):
        rows, _ = self._scan()
        row = rows.get((kind,identifier))
        if row is None:
            raise LoopError('Unknown managed vault document')
        result=self._public(row)
        if kind=='task':
            result['control']=self._control_view(row)
            try:
                result['documents']=result['documents'] + [{key:value for key,value in item.items() if key!='body'} for item in self._history(identifier, warnings=result['warnings'])]
            except LoopError as exc:
                result['warnings']=result['warnings'] + [str(exc)]
        return result

    def document(self, name):
        rows, _ = self._scan()
        for row in rows.values():
            if name == row['path']:
                return self._public(row)
        try:
            entry=self._manifest().get('documents',{}).get(name) or (_descriptor(name) if isinstance(name,str) else None)
        except LoopError:
            entry=None
        if entry and entry['role'] in ('interim','final'):
            parent=rows.get(('task',entry['task_id']))
            history=self._history(entry['task_id'],name)
            if parent is not None and history:
                item=history[0]
                return {'kind':item['kind'],'role':item['role'],'id':entry['task_id'],'record':parent['record'],'path':name,'body':item['body'],
                        'revision':item['revision'],'vault_revision':item['revision'],'modified':item['modified'],
                        'fresh':False,'writable':False,'warnings':['Historical document; not current execution or QA authority'],
                        'documents':[]}
        raise LoopError('Unknown managed vault document path')

    def _control_view(self, row, db=None):
        from .orchestration import _control, _worker_view
        task = self._runtime('task', row['id'], db)
        if task is None:
            return {'available':False}
        if db is None:
            with self.knowledge.connection() as connection:
                return self._control_view(row, connection)
        control = _control(db, task['session_id'])
        history=[json.loads(item[0]) for item in db.execute("SELECT body FROM records WHERE kind='board-control'")]
        history=sorted((item for item in history if item.get('task_id')==task['id']),key=lambda item:item.get('created_at',''))[-5:]
        if self._runtime('session',task['session_id'],db) is None:
            return {'available':False,'block_reason':'Unknown session: '+task['session_id']}
        records=[json.loads(item[0]) for item in db.execute("SELECT body FROM records WHERE kind='feedback'")]
        human=[json.loads(item[0]) for item in db.execute("SELECT body FROM records WHERE kind='human-request'")]
        # This is a control-state projection, not a worker dispatch packet.
        # A full packet may be too large while pause/resume must remain usable;
        # execution continues to enforce worker_context's unchanged size limit.
        feedback = _worker_view(self.knowledge,task,records,enforce=False,human_records=human)
        workers=[json.loads(item[0]) for item in db.execute("SELECT body FROM records WHERE kind='delegation'")]
        workers=[{'id':item['id'],'status':item.get('status'),'user_cancelled':item.get('user_cancelled',False)}
                 for item in workers if item.get('task_id')==task['id']]
        return {'available':bool(row['writable']), 'task_revision':digest(task),
                'history':history, 'workers':workers, 'control_version':control['control_version'], 'paused':feedback['paused'],
                'blocked':feedback['blocked'], 'block_reason':feedback['block_reason'],
                'cancellation':'일시정지는 저장되며 실행 중 소유 worker가 이를 확인합니다. 이 표시는 프로세스 종료 확인을 뜻하지 않습니다.'}

    def control(self, task_id, payload):
        from .orchestration import Orchestration
        required={'operation_id','kind','text','expected_task_revision','expected_control_version','expected_vault_revision'}
        if (not isinstance(payload,dict) or set(payload)!=required or not identifier(payload.get('operation_id'))
                or payload.get('kind') not in ('pause','resume','correction','constraint')
                or not isinstance(payload.get('text'),str) or not payload['text'].strip() or len(payload['text'])>8000
                or type(payload.get('expected_control_version')) is not int
                or not all(isinstance(payload.get(k),str) for k in ('expected_task_revision','expected_vault_revision'))):
            raise LoopError('Exact task control fields, original text and revisions required')
        key='board-control-'+digest([task_id,payload['operation_id']])[:24]
        stored=self.knowledge.get('board-control',key,required=False)
        if stored:
            if stored['task_id']!=task_id or stored['input']!=payload:
                raise LoopError('Control operation ID is immutable; use a new operation ID')
            return {'action_committed':True,'reused':True,'control':stored,'vault_status':self._safe_status()}
        task=self.knowledge.get('task',task_id)
        # Keep exact original text in an immutable server-owned DB receipt. The
        # reference is explicitly a record, never an arbitrary client file path.
        receipt={'id':key,'task_id':task_id,'session_id':task['session_id'],'input':payload,
                 'original_text':payload['text'],'created_at':now()}
        def guard(db):
            nonlocal receipt
            current=self._runtime('task',task_id,db)
            if current is None or digest(current)!=payload['expected_task_revision']:
                raise LoopError('Task changed; refresh before control')
            rows,_=self._scan(db); row=rows.get(('task',task_id))
            if row is None or not row['writable'] or row['vault_revision']!=payload['expected_vault_revision']:
                raise LoopError('Task vault document is stale, modified or read-only')
            previous=self._runtime('board-control',key,db)
            if previous is not None and (previous.get('input')!=payload or previous.get('task_id')!=task_id):
                raise LoopError('Control operation ID is immutable')
            if previous is None:
                self.knowledge.put('board-control',receipt,db)
            else:
                receipt=previous
        summary=' '.join(payload['text'].split())[:280]
        feedback={'id':payload['operation_id'],'task_id':task_id,'kind':payload['kind'],
                  'summary':summary,'original_input_ref':'board-control:'+key,
                  'applies_to':'Task '+task_id,'supersedes':[]}
        try:
            result=Orchestration(self.knowledge).feedback(task['session_id'],feedback,payload['expected_control_version'],guard=guard)
        except Exception:
            # A diagnostic/export exception after commit must not hide success.
            committed=self.knowledge.get('board-control',key,required=False)
            if committed!=receipt:
                raise
            result={'saved':True,'diagnostics':'Control committed; inspect export diagnostics'}
        return {'action_committed':True,'reused':False,'control':receipt,'feedback':result,'vault_status':self._safe_status()}

    def _safe_status(self):
        try:
            return self.knowledge.vault_status()
        except Exception as exc:
            return {'status':'unavailable','errors':[str(exc)]}

    def _guard(self, identifier, expected, db=None):
        if not isinstance(expected,str):
            raise LoopError('Expected vault revision is required')
        rows, _ = self._scan(db)
        row = rows.get(('human-request',identifier))
        if row is None or row['revision'] != expected or not row['writable']:
            raise LoopError('Vault document is stale, modified or outside current runtime authority')
        return row

    def _mutate(self, identifier, expected_revision, expected_vault_revision, response=None, execute=False):
        board = self
        class GuardedDesk(HumanDesk):
            def _checked(self, request_id, revision, db=None):
                record = super()._checked(request_id, revision, db)
                # The first atomic claim is the vault-bound commit point. Its
                # own authorized export may change MD before resume completes;
                # later phase transitions retain HumanDesk's runtime guard.
                if record.get('execution') is None:
                    board._guard(request_id, expected_vault_revision, db)
                return record
        self._guard(identifier,expected_vault_revision)
        desk = GuardedDesk(self.knowledge)
        receipt = desk.execute(identifier,expected_revision) if execute else desk.respond(identifier,response,expected_revision)
        return {'request':receipt,'action_committed':True,'vault_status':self.sync_status()}

    def respond(self, identifier, response, expected_revision, expected_vault_revision):
        return self._mutate(identifier,expected_revision,expected_vault_revision,response)

    def execute(self, identifier, expected_revision, expected_vault_revision):
        return self._mutate(identifier,expected_revision,expected_vault_revision,execute=True)
