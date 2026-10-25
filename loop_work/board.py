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
from .vault_layout import validate_relative, validate_metadata, validate_document_path, validate_mapping, id_suffix

class BoardConflict(LoopError):
    status_code=409


MAX_NOTE = 512 * 1024
MAX_MANIFEST = 2 * 1024 * 1024
MAX_DOCUMENTS = 500
MAX_TOTAL = 8 * 1024 * 1024


def _read(root, name, limit):
    """Open each directory without following links, then read a bounded file."""
    relative = PurePosixPath(name)
    if relative.is_absolute() or str(relative) != name or '..' in relative.parts or '\\' in name:
        raise LoopError('허용되지 않은 보드 문서 경로입니다.')
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
                raise LoopError('문서는 크기 제한을 지키는 일반 파일이어야 하며 하드 링크는 허용하지 않습니다.')
            pieces = []; count = 0
            while True:
                block = os.read(source, min(65536, limit + 1 - count))
                if not block:
                    break
                pieces.append(block); count += len(block)
                if count > limit:
                    raise LoopError('문서 크기 제한을 초과했습니다.')
            raw = b''.join(pieces)
            modepin = digest({'content': hashlib.sha256(raw).hexdigest(), 'executable': bool(info.st_mode & 0o111)})
            return raw.decode('utf-8'), modepin
    except (OSError, UnicodeError, ValueError) as exc:
        raise LoopError('문서를 안전하게 읽을 수 없습니다: ' + name) from exc


def _metadata(body):
    lines=body.split('\n',3)
    if len(lines)==4 and lines[0]=='---' and lines[1].startswith('loop_work: ') and lines[2]=='---':
        try:
            return json.loads(lines[1][len('loop_work: '):]),lines[3]
        except (ValueError,RecursionError):
            pass
    return None,body


def _descriptor(name, meta):
    validate_metadata(meta)
    validate_document_path(name,meta)
    return {key:meta[key] for key in ('kind','id','role','task_id','project_id')}


def _actionable(record):
    return (not record.get('superseded_by') and (record.get('status') in ('pending', 'declined', 'failed') or
            record.get('status') == 'answered' and record.get('action') == 'resume_task' and
            record.get('execution') is None and (record.get('response') if isinstance(record.get('response'),dict) else {}).get('decision') in ('approve', 'resolved')))


class Board:
    def __init__(self, knowledge, vault_home=None):
        self.knowledge = knowledge
        selected = vault_home if vault_home is not None else knowledge.vault_home
        if selected is None:
            raise LoopError('활성화된 지식 vault 또는 명시적인 --vault 경로가 필요합니다.')
        self.root = Path(selected).expanduser().absolute()

    def _runtime(self, kind, key, db=None):
        if db is None:
            return self.knowledge.get(kind, key, required=False)
        row = db.execute('SELECT body FROM records WHERE kind=? AND id=?', (kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    def _explicit_task(self, task_id, db=None):
        from .harness import explicit_skill_task
        task = self._runtime('task', task_id, db) if isinstance(task_id, str) else None
        return task if explicit_skill_task(task) else None

    def _visible_entry(self, entry, db=None):
        if entry['kind'] == 'task':
            return self._explicit_task(entry['id'], db) is not None
        request = self._runtime('human-request', entry['id'], db)
        return (request is not None and request.get('task_id') == entry['task_id']
                and self._explicit_task(request.get('task_id'), db) is not None)

    def _manifest(self):
        text, _ = _read(self.knowledge.home, 'vault-owned.json', MAX_MANIFEST)
        try:
            manifest = json.loads(text)
        except (ValueError, RecursionError) as exc:
            raise LoopError('문서 소유 기록의 형식이 올바르지 않습니다.') from exc
        if (not isinstance(manifest, dict) or type(manifest.get('version')) is not int or manifest.get('version') != 1 or manifest.get('vault') != str(self.root)
                or not isinstance(manifest.get('files'), dict) or not all(isinstance(name,str) for name in manifest['files'])):
            raise LoopError('문서 소유 기록이 현재 vault와 일치하지 않습니다.')
        for name in manifest['files']:
            validate_relative(name)
        if manifest.get('layout_version')!=3:
            raise LoopError('지원하지 않는 문서 배치 버전입니다.')
        if not isinstance(manifest.get('paths'),dict) or not isinstance(manifest.get('documents'),dict):
            raise LoopError('문서 배치 기록이 올바르지 않습니다.')
        for key,name in manifest.get('paths',{}).items():
            if not isinstance(key,str):
                raise LoopError('문서 연결 ID가 올바르지 않습니다.')
            validate_mapping(key,name)
        if len(set(manifest.get('paths',{}).values()))!=len(manifest.get('paths',{})):
            raise LoopError('서로 다른 문서가 같은 고정 경로를 사용할 수 없습니다.')
        for name,entry in manifest.get('documents',{}).items():
            validate_relative(name)
            if not isinstance(entry,dict) or set(entry)!={'kind','id','role','task_id','project_id'}:
                raise LoopError('문서 연결 정보의 형식이 올바르지 않습니다.')
            descriptor={'version':3,'knowledge_home':str(self.knowledge.home),'record':{'id':entry['id']},**entry}
            validate_metadata(descriptor)
            validate_document_path(name,descriptor)
        return manifest

    def _discover(self, project_id=None):
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
                            raise LoopError('문서 탐색 항목 제한에 도달했습니다.')
                        if entry.name=='진행 현황.md':
                            found.append('/'.join(parts+[entry.name]))
                return
            expected='프로젝트' if not parts else '작업' if len(parts)==2 else None
            with os.scandir(fd) as entries:
                for entry in entries:
                    visited+=1
                    if visited>MAX_DOCUMENTS*20:
                        raise LoopError('문서 탐색 항목 제한에 도달했습니다.')
                    if len(parts)==1 and project_id is not None and not entry.name.endswith('--'+id_suffix(project_id)):
                        continue
                    if expected is not None and entry.name!=expected:
                        continue
                    if expected is None:
                        if not re.fullmatch(r'.+--[0-9a-f]{8}',entry.name):
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

    def _history(self, task_id, body_path=None, warnings=None, project_id=None):
        if self._explicit_task(task_id) is None:
            return []
        documents=[]; total=0; count=0
        try:
            manifest=self._manifest(); files=manifest['files']
        except LoopError as exc:
            if warnings is not None:
                warnings.append(str(exc) if any('가'<=c<='힣' for c in str(exc)) else '문서의 소유 기록 또는 연결 정보를 확인할 수 없습니다.')
            return documents
        for name, owned in sorted(files.items()):
            entry=manifest.get('documents',{}).get(name)
            if entry and project_id is not None and entry['project_id']!=project_id:
                continue
            if not entry or entry['role'] not in ('interim','final') or entry['task_id']!=task_id or body_path is not None and name!=body_path:
                continue
            count+=1
            if count>MAX_DOCUMENTS:
                break
            try:
                body,pin=_read(self.root,name,MAX_NOTE)
                meta,display=_metadata(body)
                if meta is not None and isinstance(meta,dict) and meta.get('version')==3:
                    actual=_descriptor(name,meta)
                    if actual!=entry or meta['knowledge_home']!=str(self.knowledge.home.resolve()):
                        raise LoopError('과거 문서의 연결 정보가 선택 범위의 기록과 일치하지 않습니다.')
                    body=display
                else:
                    raise LoopError('과거 문서의 연결 정보가 없습니다.')
            except LoopError as exc:
                if warnings is not None:
                    warnings.append(str(exc) if any('가'<=c<='힣' for c in str(exc)) else '문서의 소유 기록 또는 연결 정보를 확인할 수 없습니다.')
                continue
            total+=len(body.encode('utf-8'))
            if total>MAX_TOTAL:
                break
            documents.append({'path':name,'revision':pin,'modified':pin!=owned,'kind':entry['role'],'role':entry['role'],
                              'body':body,'writable':False})
        return documents

    def sync_status(self, scoped=False):
        # Board diagnostics never disclose records outside the visible task set.
        # Full exporter details remain available through KnowledgeBase/CLI.
        errors=[]
        try:
            value=self.knowledge.vault_status()
            if not isinstance(value,dict) or value.get('errors'):
                errors=['문서 출력 진단에 확인이 필요합니다. 이미 저장된 동작을 반복하지 마세요.']
        except Exception:
            errors=['문서 출력 진단을 읽을 수 없습니다. 이미 저장된 동작을 반복하지 마세요.']
        return {'status':'withheld','diagnostics':'보드에서는 개별 문서 출력 진단을 표시하지 않습니다.','errors':errors}

    def _scan(self, db=None, project_id=None):
        if project_id is not None and not identifier(project_id):
            raise LoopError('프로젝트 ID가 올바르지 않습니다.')
        warnings=[]; rows={}; total=0; count=0; unavailable=set()
        try:
            manifest=self._manifest(); files=dict(manifest['files']); descriptions=manifest.get('documents',{})
        except LoopError:
            files={}; descriptions={}
            warnings.append('문서 소유 기록을 읽을 수 없어 발견한 문서를 읽기 전용으로 표시합니다.')
        try:
            discovered=self._discover(project_id)
        except (LoopError,OSError):
            discovered=[]
            warnings.append('일부 문서를 읽을 수 없거나 탐색 제한을 초과했습니다.')
        for name in discovered:
            files.setdefault(name,None)
        for name,owned_pin in sorted(files.items()):
            entry=descriptions.get(name)
            if entry and project_id is not None and entry['project_id']!=project_id:
                continue
            if entry and (entry['kind'],entry['role']) not in (('task','current'),('human-request','human-request')):
                continue
            if not entry and name not in discovered:
                continue
            if entry and not self._visible_entry(entry, db):
                continue
            if count>=MAX_DOCUMENTS:
                warnings.append('문서 개수 제한에 도달했습니다.'); break
            count+=1
            try:
                raw,pin=_read(self.root,name,MAX_NOTE)
                total+=len(raw.encode('utf-8'))
                if total>MAX_TOTAL:
                    warnings.append('전체 문서 크기 제한에 도달했습니다.'); break
            except LoopError as exc:
                warnings.append(str(exc) if any('가'<=c<='힣' for c in str(exc)) else '문서의 소유 기록 또는 연결 정보를 확인할 수 없습니다.')
                if entry:
                    unavailable.add((entry['kind'],entry['id']))
                continue
            meta,body=_metadata(raw); record={}; errors=[]; valid=False
            try:
                if isinstance(meta,dict) and meta.get('version')==3:
                    actual=_descriptor(name,meta)
                    if entry is not None and entry!=actual:
                        raise LoopError('문서 연결 기록과 실제 문서 정보가 일치하지 않습니다.')
                    entry=actual
                    if project_id is not None and entry['project_id']!=project_id:
                        continue
                    if (entry['kind'],entry['role']) not in (('task','current'),('human-request','human-request')):
                        continue
                    record=meta['record']
                    valid=meta['knowledge_home']==str(self.knowledge.home.resolve())
                    if owned_pin is not None and descriptions.get(name)!=actual:
                        valid=False
                if entry is None:
                    raise LoopError('작업 문서의 연결 정보가 없거나 올바르지 않습니다.')
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
                    warnings.append('연결 정보를 확인할 수 없는 문서: '+name); continue
            kind,key=entry['kind'],entry['id']
            if not isinstance(record,dict):
                record={}
            if not valid:
                errors.append('문서 연결 정보가 올바르지 않거나 다른 지식 홈의 문서이므로 읽기 전용입니다.')
            current=self._runtime(kind,key,db)
            authority_task=current if kind=='task' else (self._runtime('task',current.get('task_id'),db) if current else None)
            if project_id is not None and authority_task is not None and project_id not in authority_task.get('project_ids',[]):
                continue
            if self._explicit_task(authority_task.get('id') if authority_task else None, db) is None:
                continue
            fresh=valid and current is not None and current==record
            if not fresh:
                errors.append('문서 기록이 현재 실행 원본과 일치하지 않습니다.')
            modified=owned_pin!=pin
            if modified:
                errors.append('사용자가 수정한 문서가 관리 중인 원본 해시와 다릅니다.')
            row={'kind':kind,'id':key,'role':entry['role'],'record':record,'path':name,'body':body,'revision':pin,'vault_revision':pin,
                 'modified':modified,'fresh':fresh,'writable':valid and fresh and owned_pin is not None and not modified,
                 'warnings':errors,'documents':[{'path':name,'revision':pin,'role':entry['role']}],
                 '_task':entry['task_id'],'_projects':{entry['project_id']},
                 '_session':(authority_task or record).get('session_id')}
            group=(kind,key)
            if group in rows:
                first=rows[group]; first['documents'].extend(row['documents']); first['_projects'].update(row['_projects'])
                if first['record']!=record or first['body']!=body or not row['writable']:
                    first['writable']=False
                    first['warnings'].append('프로젝트별 문서 사본이 서로 다르거나 수정되었습니다.')
                first['modified']=first['modified'] or modified; first['fresh']=first['fresh'] and fresh
            else:
                rows[group]=row
        for key in unavailable:
            if key in rows:
                rows[key]['writable']=False
                rows[key]['warnings'].append('보존된 다른 문서 사본을 읽을 수 없습니다.')
        for row in rows.values():
            row['revision'] = row['vault_revision'] = digest(row['documents'])
        for row in rows.values():
            if row['kind'] != 'human-request':
                continue
            parent = rows.get(('task',row['_task']))
            if parent is None or not parent['writable'] or not row['_projects'].issubset(parent['_projects']):
                row['writable'] = False
                row['warnings'].append('현재 작업 문서의 연결 정보가 없거나 오래되었거나 수정되었습니다.')
            row['revision'] = row['vault_revision'] = digest([row['documents'], parent['documents'] if parent else None])
        return rows, warnings

    @staticmethod
    def _public(row):
        return {key:value for key,value in row.items() if not key.startswith('_')}

    def list(self, session_id=None, task_id=None, include_closed=False, project_id=None):
        try:
            rows, warnings = self._scan(project_id=project_id)
        except LoopError as exc:
            return {'tasks':[],'requests':[],'notes':[],'warnings':['문서를 읽을 수 없습니다.'],
                    'status':{'vault':str(self.root),'status':'unavailable'},'vault_status':self.sync_status(session_id is not None or task_id is not None or project_id is not None)}
        warnings = ['일부 문서를 읽을 수 없거나 확인할 수 없습니다.'] if warnings else []
        selected = lambda row: ((session_id is None or row.get('_session',row['record'].get('session_id')) == session_id)
                                and (task_id is None or row['_task'] == task_id))
        tasks = [self._public(row) for row in rows.values() if row['kind']=='task' and selected(row)]
        requests = [self._public(row) for row in rows.values() if row['kind']=='human-request' and selected(row)
                    and (include_closed or _actionable(row['record']))]
        for task in tasks:
            try:
                task['documents'] = task['documents'] + [{key:value for key,value in item.items() if key!='body'} for item in self._history(task['id'], warnings=task['warnings'],project_id=project_id)]
            except LoopError as exc:
                warnings.append(str(exc) if any('가'<=c<='힣' for c in str(exc)) else '문서의 소유 기록 또는 연결 정보를 확인할 수 없습니다.')
            task['control'] = self._control_view(task)
            task['requests'] = [row for row in requests if row['record'].get('task_id') == task['id']]
            self._decorate(task,project_id)
        return {'tasks':tasks,'requests':requests,'notes':[],'warnings':warnings,
                'status':{'vault':str(self.root),'status':'partial' if warnings else 'ready'},'vault_status':self.sync_status(session_id is not None or task_id is not None or project_id is not None)}

    def show(self, identifier, kind='human-request', project_id=None):
        rows, _ = self._scan(project_id=project_id)
        row = rows.get((kind,identifier))
        if row is None:
            raise LoopError('등록된 문서를 찾을 수 없습니다.')
        result=self._public(row)
        if kind=='task':
            result['control']=self._control_view(row)
            try:
                result['documents']=result['documents'] + [{key:value for key,value in item.items() if key!='body'} for item in self._history(identifier, warnings=result['warnings'],project_id=project_id)]
            except LoopError as exc:
                result['warnings']=result['warnings'] + [str(exc)]
            result['requests']=[self._public(item) for item in rows.values() if item['kind']=='human-request' and item['_task']==identifier]
            self._decorate(result,project_id)
        return result

    def document(self, name, project_id=None):
        rows, _ = self._scan(project_id=project_id)
        for row in rows.values():
            if name == row['path']:
                return self._public(row)
        try:
            entry=self._manifest().get('documents',{}).get(name)
        except LoopError:
            entry=None
        if entry and entry['role'] in ('interim','final') and (project_id is None or entry['project_id']==project_id):
            parent=rows.get(('task',entry['task_id']))
            history=self._history(entry['task_id'],name,project_id=project_id)
            if parent is not None and history:
                item=history[0]
                return {'kind':item['kind'],'role':item['role'],'id':entry['task_id'],'record':parent['record'],'path':name,'body':item['body'],
                        'revision':item['revision'],'vault_revision':item['revision'],'modified':item['modified'],
                        'fresh':False,'writable':False,'warnings':['과거 문서입니다. 현재 실행이나 품질 검증 권한을 부여하지 않습니다.'],
                        'documents':[]}
        raise LoopError('등록된 문서 경로를 찾을 수 없습니다.')

    def _project_record(self, project_id):
        manifest=self._manifest()
        for name,entry in manifest.get('documents',{}).items():
            if entry.get('kind')!='project' or entry.get('role')!='index' or entry.get('project_id')!=project_id:
                continue
            raw,_=_read(self.root,name,MAX_NOTE); meta,_body=_metadata(raw)
            actual=_descriptor(name,meta)
            if actual!=entry or meta['knowledge_home']!=str(self.knowledge.home.resolve()):
                raise LoopError('프로젝트 문서의 연결 정보를 확인할 수 없습니다.')
            return meta['record']
        return None

    def projects(self, query='', sort='name', session_id=None, task_id=None, project_id=None):
        if not isinstance(query,str) or len(query)>200 or sort not in ('name','updated'):
            raise LoopError('프로젝트 검색·정렬 값이 올바르지 않습니다.')
        rows,_=self._scan(project_id=project_id)
        tasks=[row for row in rows.values() if row['kind']=='task'
               and (session_id is None or row.get('_session',row['record'].get('session_id'))==session_id)
               and (task_id is None or row['id']==task_id)]
        identities={project for row in tasks for project in row['_projects']}
        if session_id is None and task_id is None:
            try:
                entries=self._manifest()['documents'].values()
                task_projects={entry['project_id'] for entry in entries if entry['kind']=='task' and entry['role']=='current'}
                identities.update(entry['project_id'] for entry in entries
                                  if entry['kind']=='project' and entry['role']=='index' and entry['project_id'] in task_projects
                                  and (project_id is None or entry['project_id']==project_id))
            except LoopError:
                pass
        result=[]
        from .wiki import Wiki
        for project in sorted(identities):
            if project_id is not None and project!=project_id:
                continue
            try:
                record=self._project_record(project)
            except LoopError:
                record=None
            name=str((record or {}).get('name') or project)
            title=name; warnings=[]; updated=max((row['record'].get('updated_at','') for row in tasks if project in row['_projects'] and isinstance(row['record'].get('updated_at',''),str)),default='')
            try:
                wiki=Wiki(self.knowledge,self.root).get('project',project,project)
                title=wiki['title']; updated=max(updated,wiki.get('updated_at',''))
            except (LoopError,OSError,UnicodeError) as exc:
                warnings.append('프로젝트 위키를 읽을 수 없습니다. '+str(exc))
            # Only already scoped task rows participate; Wiki.get observes safe
            # vault file mtime, including external Obsidian edits, without a new scan.
            for task in tasks:
                if project not in task['_projects']:
                    continue
                try:
                    task_wiki=Wiki(self.knowledge,self.root).get('task',task['id'],project)
                    updated=max(updated,task_wiki.get('updated_at',''))
                except (LoopError,OSError,UnicodeError):
                    warnings.append('작업 위키의 최근 변경 시각을 확인할 수 없습니다.')
            if query.casefold() not in (name+' '+title).casefold():
                continue
            result.append({'id':project,'name':name,'display_name':title,'task_count':sum(project in row['_projects'] for row in tasks),
                           'updated_at':updated,'warnings':warnings})
        result.sort(key=lambda row:(row['display_name'].casefold(),row['id']))
        if sort=='updated':
            result.sort(key=lambda row:row['updated_at'],reverse=True)
        return {'projects':result}

    def _wiki_scope(self, kind, identifier, project_id):
        from .wiki import key
        if kind=='project':
            if project_id is not None and project_id!=identifier:
                raise LoopError('선택한 프로젝트 밖의 위키입니다.')
            project_id=identifier
            if self._project_record(project_id) is None:
                raise LoopError('원본 프로젝트 문서가 없습니다.')
        elif kind=='task':
            rows,_=self._scan(project_id=project_id); row=rows.get(('task',identifier))
            if row is None:
                raise LoopError('선택한 프로젝트의 작업 문서가 없습니다.')
            if project_id is None:
                if len(row['_projects'])!=1:
                    raise LoopError('위키를 편집할 프로젝트를 선택하세요.')
                project_id=next(iter(row['_projects']))
        else:
            raise LoopError('위키 종류가 올바르지 않습니다.')
        key(kind,identifier,project_id)
        return project_id

    def wiki(self, kind, identifier, project_id=None):
        from .wiki import Wiki
        selected=self._wiki_scope(kind,identifier,project_id)
        try:
            return Wiki(self.knowledge,self.root).get(kind,identifier,selected)
        except LoopError as exc:
            if any('가'<=character<='힣' for character in str(exc)):
                raise
            raise LoopError('위키의 소유 기록과 문서 연결 정보를 확인할 수 없습니다.') from exc

    def save_wiki(self, kind, identifier, payload, project_id=None):
        from .wiki import Wiki
        selected=self._wiki_scope(kind,identifier,project_id)
        return Wiki(self.knowledge,self.root).save(kind,identifier,payload,selected)

    def _decorate(self, row, project_id):
        record=row['record']; row['display_title']=str(record.get('title') or row['id'])
        candidates=record.get('project_ids',[])
        if not isinstance(candidates,list):
            candidates=[]
        selected=project_id or (candidates[0] if len(candidates)==1 else None)
        if selected:
            try:
                from .wiki import Wiki
                row['display_title']=Wiki(self.knowledge,self.root).get('task',row['id'],selected)['title']
            except (LoopError,OSError,UnicodeError):
                pass
        reasons=[]; control=row.get('control',{})
        if control.get('needs_human') or any(_actionable(request['record']) for request in row.get('requests',[])):
            reasons.append('응답·확인 또는 후속 조치가 필요한 사람 요청이 있습니다.')
        if control.get('paused'):
            reasons.append('사용자가 일시정지를 요청했습니다. 프로세스 종료 기록은 별도로 확인하세요.')
        if not row['fresh'] or not row['writable']:
            reasons.append('현재 문서의 원본 일치·소유 근거를 확인해야 합니다.')
        phase=record.get('phase')
        if phase=='completed' and control.get('completion_current') is not True:
            reasons.append('현재 유효한 완료 근거가 없거나 확인되지 않았습니다. 과거 완료 기록을 검토하세요.')
        if reasons:
            state='review'
        elif phase=='completed':
            state='completed'
        elif phase in ('working','running'):
            state='working'
        elif phase in ('goal_setting','draft','ready'):
            state='ready'
        else:
            state='stopped'
        label={'ready':'준비','working':'진행 중','review':'사용자 확인 필요','completed':'완료','stopped':'중단·차단'}[state]
        if state=='stopped':
            label={'aborted':'중단·폐기','blocked':'기술적 차단'}.get(phase,label)
        row.update(board_state=state,state_label=label,state_reason=record.get('reason'),
                   review_reasons=reasons,historical_completed=phase=='completed',project_id=selected)

    def _development_completion_current(self, task, feedback, db):
        """Read final evidence without refreshing or mutating runtime records."""
        from .storage import snapshot
        try:
            goal_id=task.get('goal_id')
            if not identifier(goal_id) or len(task.get('locations',[]))!=1:
                return False
            location=self._runtime('location',task['locations'][0],db)
            if not location or location.get('project_id') not in task.get('project_ids',[]):
                return False
            root=Path(location['root'])
            if not root.is_absolute():
                return False
            gate=Path(task.get('result',{}).get('gate') or '')
            if not gate.is_absolute() or '..' in gate.parts or len(gate.parents)<6:
                return False
            # Older goals may retain /var while locations canonicalize /private/var.
            # Resolve only the repository prefix; no gate component is followed.
            gate_root=gate.parents[5]
            if gate_root.resolve()!=root.resolve():
                return False
            relative=gate.relative_to(gate_root).as_posix()
            parts=PurePosixPath(relative).parts
            if (len(parts)!=6 or parts[:4]!=('.loop','state',goal_id,'gates')
                    or not parts[4].startswith('final-') or parts[5]!='gate.json'):
                return False
            report=json.loads(_read(root,relative,MAX_MANIFEST)[0])
            state=json.loads(_read(root,'.loop/state/'+goal_id+'/state.json',MAX_MANIFEST)[0])
            contract=json.loads(_read(root,'.loop/goals/'+goal_id+'/contract.json',MAX_MANIFEST)[0])
            discovery=json.loads(_read(root,'.loop/goals/'+goal_id+'/discovery.json',MAX_MANIFEST)[0])
            if (not all(isinstance(value,dict) for value in (state,contract,discovery))
                    or state.get('id')!=goal_id or contract.get('id')!=goal_id
                    or state.get('phase')!='completed' or state.get('latest_gate')!=str(gate)
                    or not isinstance(report,dict) or state.get('completion_snapshot')!=report.get('snapshot')
                    or state.get('completion_feedback_revision')!=report.get('feedback_revision')):
                return False
            # Reuse the exact pure Engine input semantics (including managed
            # rule links and current engine digest); never load/refresh/save.
            from .engine import Engine
            observer=Engine(root,goal_id,knowledge=self.knowledge)
            observer.integrity(state,contract,discovery)
            return (isinstance(report,dict) and report.get('passed') is True and report.get('phase')=='final'
                    and report.get('snapshot')==snapshot(root)['digest']
                    and report.get('feedback_revision')==feedback['revision']
                    and not feedback.get('blocked'))
        except (LoopError,OSError,ValueError,KeyError,TypeError,UnicodeError,RecursionError):
            return False

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
            return {'available':False,'block_reason':'세션을 찾을 수 없습니다: '+task['session_id']}
        records=[json.loads(item[0]) for item in db.execute("SELECT body FROM records WHERE kind='feedback'")]
        human=[json.loads(item[0]) for item in db.execute("SELECT body FROM records WHERE kind='human-request'")]
        # This is a control-state projection, not a worker dispatch packet.
        # A full packet may be too large while pause/resume must remain usable;
        # execution continues to enforce worker_context's unchanged size limit.
        feedback = _worker_view(self.knowledge,task,records,enforce=False,human_records=human)
        # Authority contributes only a classification bit. Unavailable vault
        # request text is never reconstructed from SQLite for Board display.
        needs_human=any(item.get('task_id')==task['id'] and item.get('session_id')==task['session_id']
                        and _actionable(item) for item in human)
        completion_current=None
        if task.get('phase')=='completed':
            result=task.get('result') if isinstance(task.get('result'),dict) else {}
            marker=result.get('evidence_current')
            completion_current=marker if type(marker) is bool else None
            feedback_matches=result.get('feedback_revision')==feedback['revision']
            if result.get('feedback_revision') is not None and not feedback_matches:
                completion_current=False
            if task.get('kind')=='development':
                completion_current=(marker is not False and self._development_completion_current(task,feedback,db))
            elif task.get('completion_observation'):
                try:
                    locations=[self._runtime('location',location,db) for location in task['locations']]
                    source_matches=bool(all(locations) and digest(self.knowledge.observe(locations))==task['completion_observation'])
                    if not source_matches:
                        completion_current=False
                    elif feedback_matches and completion_current is not False:
                        completion_current=True
                except (LoopError,OSError,KeyError):
                    completion_current=False
        workers=[json.loads(item[0]) for item in db.execute("SELECT body FROM records WHERE kind='delegation'")]
        workers=[{'id':item['id'],'status':item.get('status'),'user_cancelled':item.get('user_cancelled',False)}
                 for item in workers if item.get('task_id')==task['id']]
        return {'available':bool(row['writable']), 'task_revision':digest(task),
                'history':history, 'workers':workers, 'control_version':control['control_version'], 'paused':feedback['paused'],
                'needs_human':needs_human, 'blocked':feedback['blocked'] or needs_human, 'block_reason':('작업 범위가 변경되어 새 목표가 필요합니다.' if feedback.get('scope_changed') else '사용자가 이 작업을 일시정지했습니다.' if feedback.get('paused') else '사람의 응답 또는 후속 확인을 기다립니다.' if needs_human else '원본 피드백이 변경되었거나 확인할 수 없습니다.' if feedback.get('blocked') else None),'completion_current':completion_current,
                'cancellation':'일시정지는 저장되며 실행 중 소유 worker가 이를 확인합니다. 이 표시는 프로세스 종료 확인을 뜻하지 않습니다.'}

    def control(self, task_id, payload, project_id=None):
        from .orchestration import Orchestration
        required={'operation_id','kind','text','expected_task_revision','expected_control_version','expected_vault_revision'}
        if (not isinstance(payload,dict) or set(payload)!=required or not identifier(payload.get('operation_id'))
                or payload.get('kind') not in ('pause','resume','correction','constraint')
                or not isinstance(payload.get('text'),str) or not payload['text'].strip() or len(payload['text'])>8000
                or type(payload.get('expected_control_version')) is not int
                or not all(isinstance(payload.get(k),str) for k in ('expected_task_revision','expected_vault_revision'))):
            raise LoopError('정확한 작업 제어 필드·원문·현재 버전이 필요합니다.')
        if project_id is not None:
            self.show(task_id,'task',project_id=project_id)
        if self._explicit_task(task_id) is None:
            raise LoopError('명시적으로 loop-work를 요청한 작업만 보드에서 제어할 수 있습니다.')
        key='board-control-'+digest([task_id,payload['operation_id']])[:24]
        stored=self.knowledge.get('board-control',key,required=False)
        if stored:
            if stored['task_id']!=task_id or stored['input']!=payload:
                raise LoopError('같은 제어 작업 ID의 원문은 바꿀 수 없습니다. 새 ID를 사용하세요.')
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
                raise BoardConflict('작업이 변경되었습니다. 다시 읽은 뒤 제어하세요.')
            rows,_=self._scan(db,project_id=project_id); row=rows.get(('task',task_id))
            if row is None or not row['writable'] or row['vault_revision']!=payload['expected_vault_revision']:
                raise BoardConflict('작업 문서가 오래되었거나 수정되었거나 읽기 전용입니다.')
            self._retained_action_pins(task_id,db=db)
            previous=self._runtime('board-control',key,db)
            if previous is not None and (previous.get('input')!=payload or previous.get('task_id')!=task_id):
                raise LoopError('같은 제어 작업 ID의 원문은 바꿀 수 없습니다.')
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
            result={'saved':True,'diagnostics':'제어 원문은 저장되었습니다. 문서 출력 진단을 확인하세요.'}
        return {'action_committed':True,'reused':False,'control':receipt,'feedback':result,'vault_status':self._safe_status()}

    def _safe_status(self):
        # Fresh, replayed and recovered control receipts share the Board's
        # identifier-free diagnostics; detailed errors remain in the KB/CLI.
        return self.sync_status()

    def _retained_action_pins(self, task_id, request_id=None, db=None):
        """Check all retained replicas privately, independently of display scope."""
        try:
            manifest=self._manifest()
            task=self._runtime('task',task_id,db)
            if self._explicit_task(task_id, db) is None:
                raise LoopError('Missing explicit action task')
            projects=set(task.get('project_ids',[]))
            if not projects:
                raise LoopError('Missing task projects')
            required={('task',task_id):task}
            if request_id is not None:
                request=self._runtime('human-request',request_id,db)
                if (request is None or request.get('task_id')!=task_id
                        or request.get('session_id')!=task.get('session_id')):
                    raise LoopError('Request task mismatch')
                required[('human-request',request_id)]=request
            found={key:set() for key in required}
            count=0;total=0
            for name in sorted(set(manifest['files']) | set(manifest.get('documents',{}))):
                entry=manifest.get('documents',{}).get(name)
                if entry is None or (entry['kind'],entry['id']) not in required:
                    continue
                key=(entry['kind'],entry['id'])
                role='current' if entry['kind']=='task' else 'human-request'
                if entry['role']!=role:
                    continue
                if entry['task_id']!=task_id or entry['project_id'] not in projects:
                    raise LoopError('Replica scope mismatch')
                count+=1
                if count>MAX_DOCUMENTS:
                    raise LoopError('Replica count limit')
                text,pin=_read(self.root,name,MAX_NOTE)
                total+=len(text.encode('utf-8'))
                if total>MAX_TOTAL or manifest['files'].get(name)!=pin:
                    raise LoopError('Replica ownership changed')
                meta,_=_metadata(text)
                if not isinstance(meta,dict):
                    raise LoopError('Replica metadata missing')
                if _descriptor(name,meta)!=entry or manifest.get('documents',{}).get(name)!=entry:
                    raise LoopError('Replica descriptor mismatch')
                if meta.get('knowledge_home')!=str(self.knowledge.home.resolve()) or meta.get('record')!=required[key]:
                    raise LoopError('Replica runtime changed')
                found[key].add(entry['project_id'])
            if any(seen!=projects for seen in found.values()):
                raise LoopError('Required retained replica unavailable')
        except (LoopError,OSError,ValueError,KeyError,TypeError,UnicodeError,RecursionError) as exc:
            # Neither paths nor content from another project leave this guard.
            raise BoardConflict('공유 작업 또는 요청의 보존된 문서가 없거나 수정되어 실행할 수 없습니다.') from exc

    def _guard(self, identifier, expected, db=None, project_id=None):
        if not isinstance(expected,str):
            raise LoopError('문서의 현재 버전이 필요합니다.')
        rows, _ = self._scan(db,project_id=project_id)
        row = rows.get(('human-request',identifier))
        if row is None or row['revision'] != expected or not row['writable']:
            raise BoardConflict('문서가 오래되었거나 수정되었거나 현재 실행 권한 밖에 있습니다.')
        self._retained_action_pins(row['_task'],identifier,db)
        return row

    def _mutate(self, identifier, expected_revision, expected_vault_revision, response=None, execute=False, project_id=None):
        board = self
        class GuardedDesk(HumanDesk):
            def _checked(self, request_id, revision, db=None):
                record = super()._checked(request_id, revision, db)
                # The first atomic claim is the vault-bound commit point. Its
                # own authorized export may change MD before resume completes;
                # later phase transitions retain HumanDesk's runtime guard.
                if record.get('execution') is None:
                    board._guard(request_id, expected_vault_revision, db,project_id=project_id)
                return record
        self._guard(identifier,expected_vault_revision,project_id=project_id)
        desk = GuardedDesk(self.knowledge)
        receipt = desk.execute(identifier,expected_revision) if execute else desk.respond(identifier,response,expected_revision)
        return {'request':receipt,'action_committed':True,'vault_status':self.sync_status(project_id is not None)}

    def respond(self, identifier, response, expected_revision, expected_vault_revision, project_id=None):
        return self._mutate(identifier,expected_revision,expected_vault_revision,response,project_id=project_id)

    def execute(self, identifier, expected_revision, expected_vault_revision, project_id=None):
        return self._mutate(identifier,expected_revision,expected_vault_revision,execute=True,project_id=project_id)
