"""Human-owned vault prose, separate from generated execution evidence."""
from __future__ import annotations
from contextlib import ExitStack
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import uuid

from .storage import LoopError, digest, now
from .vault_layout import safe_id, validate_relative, validate_mapping, display_title

MAX_WIKI=512*1024
# Two accepted bodies (input/result), worst JSON escaping, bounded metadata.
MAX_WIKI_RECEIPT=2*MAX_WIKI*6+128*1024
class WikiConflict(LoopError):
    status_code=409


def _receipt_text(payload,result):
    text=json.dumps({'input':payload,'result':result,'at':now()},ensure_ascii=False,separators=(',',':'))+'\n'
    if len(text.encode('utf-8'))>MAX_WIKI_RECEIPT:
        raise LoopError('저장 접수 기록의 크기 제한을 초과했습니다. 원문은 게시하지 않았습니다.')
    return text


FIELDS={'version','kind','id','project_id','task_id','title'}


def key(kind, identifier, project_id):
    if kind not in ('project','task'):
        raise LoopError('위키 종류는 project 또는 task여야 합니다.')
    safe_id(identifier); safe_id(project_id)
    return kind+':'+project_id+':'+identifier


def encode(meta, body):
    from .writing import plain
    return '---\nloop_work_wiki: '+json.dumps(meta,ensure_ascii=True,separators=(',',':'))+'\n---\n# '+plain(meta['title'])+'\n\n'+body


def parse(text, entry):
    lines=text.split('\n',3)
    try:
        if len(lines)!=4 or lines[0]!='---' or lines[2]!='---' or not lines[1].startswith('loop_work_wiki: '):
            raise ValueError()
        meta=json.loads(lines[1][len('loop_work_wiki: '):])
        if (not isinstance(meta,dict) or set(meta)!=FIELDS or type(meta['version']) is not int or meta['version']!=1
                or any(meta[x]!=entry[x] for x in ('kind','id','project_id','task_id'))
                or not isinstance(meta['title'],str) or not meta['title'].strip() or len(meta['title'])>200):
            raise ValueError()
        meta['title'].encode('utf-8')
        body=lines[3]
        if body.startswith('# '):
            from .writing import plain
            heading,separator,rest=body.partition('\n')
            value=heading[2:].strip()
            if value!=plain(meta['title']):
                if len(value)>200:
                    raise ValueError()
                if value:
                    meta={**meta,'title':value}
            body=rest.removeprefix('\n') if separator else ''
        return meta,body
    except (ValueError,TypeError,KeyError,UnicodeError,RecursionError) as exc:
        raise LoopError('위키 연결 정보가 변경되었거나 올바르지 않습니다.') from exc


def initial_body(kind, record, source):
    """Start a short human document; execution details stay in their source."""
    from urllib.parse import quote
    from .writing import plain
    title=display_title(record)
    cutoff=record.get('updated_at') or record.get('created_at') or '원본 기록에 시각 없음'
    purpose=('작업의 배경·결정·활용할 지식을 정리합니다.' if kind=='task' else
             '프로젝트의 목적·구조·운영 지식을 정리합니다.')
    body='## 개요\n\n'+plain(title)+' — '+purpose+'\n\n처음 작성한 시각: '+plain(cutoff)+'\n'
    body+='\n아래 개요는 작성 당시의 기록입니다. 최신 상태와 근거는 연결 문서에서 확인합니다.\n'
    if kind=='task':
        for label,value in (('목표',(record.get('goal') or {}).get('outcome')),
                            ('결과',(record.get('result') or {}).get('summary')),
                            ('남은 장애',record.get('reason') if record.get('phase')=='blocked' else None)):
            if value:
                body+='\n**'+label+':** '+plain(value)+'\n'
    if source:
        label='진행 현황' if kind=='task' else '프로젝트 목록'
        body+='\n## 관련 문서\n\n- ['+label+'](<'+quote(source,safe='/')+'>): 목표·현재 상태·실제 근거를 확인합니다.\n'
    body+='\n> 문서의 표시 이름과 본문을 바꿔도 목표·완료·예산·승인은 변경되지 않습니다.\n'
    return body


def ensure(knowledge, root, manifest, kind, record, project_id, base, source=None):
    """Exporter-only first creation; retained entries are never regenerated."""
    from .vault import _write
    identity=key(kind,record['id'],project_id)
    entries=manifest.setdefault('wiki_documents',{})
    if not isinstance(entries,dict):
        raise LoopError('위키 소유 기록이 올바르지 않습니다.')
    if identity in entries:
        return
    name=base+('프로젝트 안내.md' if kind=='project' else '작업 문서.md')
    validate_relative(name)
    entry={'kind':kind,'id':record['id'],'project_id':project_id,'task_id':record['id'] if kind=='task' else None,'path':name,'owned':False}
    # Reserve the exact path even after an unowned conflict or later deletion.
    entries[identity]=entry
    title=display_title(record)
    meta={k:entry[k] for k in ('kind','id','project_id','task_id')}
    meta.update(version=1,title=title)
    relative=os.path.relpath(root/source,(root/name).parent).replace(os.sep,'/') if source else None
    _write(root/name,encode(meta,initial_body(kind,record,relative)),None)
    entry['owned']=True


class Wiki:
    def __init__(self, knowledge, root):
        self.knowledge=knowledge; self.root=Path(root).absolute()

    def _entry(self, kind, identifier, project_id):
        from .vault import read_export_json
        identity=key(kind,identifier,project_id)
        manifest=read_export_json(self.knowledge.home/'vault-owned.json')
        if (not manifest or manifest.get('version')!=1 or manifest.get('layout_version')!=3
                or manifest.get('vault')!=str(self.root)):
            raise LoopError('위키의 원본 소유 기록이 없습니다.')
        if not isinstance(manifest.get('wiki_documents',{}),dict) or not isinstance(manifest.get('paths',{}),dict):
            raise LoopError('위키 경로 기록이 올바르지 않습니다.')
        entry=manifest.get('wiki_documents',{}).get(identity)
        expected={'kind':kind,'id':identifier,'project_id':project_id,'task_id':identifier if kind=='task' else None}
        if not isinstance(entry,dict) or set(entry)!={*expected,'path','owned'} or entry.get('owned') is not True or any(entry[k]!=v for k,v in expected.items()):
            raise LoopError('위키가 없거나 연결 정보가 변경되었습니다.')
        name=validate_relative(entry['path']); parts=name.split('/')
        # Bind to the existing project/task canonical inventory, never a supplied path.
        project_name=manifest.get('paths',{}).get('project:'+project_id)
        if kind=='project':
            if project_name:
                validate_mapping('project:'+project_id,project_name)
            valid=project_name and name==project_name+'/프로젝트 안내.md'
        else:
            current=manifest.get('paths',{}).get('task:'+project_id+':'+identifier)
            if current:
                validate_mapping('task:'+project_id+':'+identifier,current)
            valid=current and name==current.rsplit('/',1)[0]+'/작업 문서.md'
        if not valid:
            raise LoopError('위키 경로가 선택한 프로젝트·작업과 다릅니다.')
        return entry

    def get(self, kind, identifier, project_id):
        from .vault import _read_regular
        entry=self._entry(kind,identifier,project_id)
        try:
            text,pin=_read_regular(self.root/entry['path'],MAX_WIKI)
            meta,body=parse(text.decode('utf-8'),entry)
        except (LoopError,OSError,UnicodeError) as exc:
            raise LoopError('위키 파일이 없거나 안전하게 읽을 수 없습니다. 원문을 보존했습니다.') from exc
        return {'id':identifier,'kind':kind,'project_id':project_id,'task_id':entry['task_id'],
                'title':meta['title'],'body_markdown':body,'revision':pin,'path':entry['path'],'editable':True,'warnings':[],
                'updated_at':datetime.fromtimestamp(os.lstat(self.root/entry['path']).st_mtime,timezone.utc).isoformat()}

    def save(self, kind, identifier, payload, project_id):
        from .vault import export_locked, _directory, _read_regular, _write, read_export_json
        fields={'operation_id','expected_revision','title','body_markdown'}
        try:
            if isinstance(payload,dict):
                for field in ('title','body_markdown'):
                    if isinstance(payload.get(field),str):
                        payload[field].encode('utf-8')
        except UnicodeError as exc:
            raise LoopError('위키에는 유효한 UTF-8 텍스트를 사용하세요.') from exc
        if (not isinstance(payload,dict) or set(payload)!=fields or not isinstance(payload.get('expected_revision'),str)
                or not isinstance(payload.get('title'),str) or not payload['title'].strip() or len(payload['title'])>200 or '\n' in payload['title'] or '\r' in payload['title']
                or not isinstance(payload.get('body_markdown'),str) or len(payload['body_markdown'].encode('utf-8'))>MAX_WIKI-4096):
            raise LoopError('저장에는 작업 ID·현재 버전·표시 이름·본문이 필요합니다.')
        safe_id(payload['operation_id'])
        operation=digest([kind,identifier,project_id,payload['operation_id']])
        folder=self.knowledge.home/'wiki-operations'; receipt_path=folder/(operation+'.json')
        with export_locked(self.knowledge.home/'vault-export'):
            previous=read_export_json(receipt_path,limit=MAX_WIKI_RECEIPT)
            if previous:
                if previous.get('input')!=payload:
                    raise WikiConflict('같은 저장 작업 ID에 다른 내용을 사용할 수 없습니다.')
                return {**previous['result'],'saved':True,'reused':True}
            current=self.get(kind,identifier,project_id)
            if current['revision']!=payload['expected_revision']:
                raise WikiConflict('위키가 다른 곳에서 변경되었습니다. 초안을 보존하고 다시 불러오세요.')
            entry=self._entry(kind,identifier,project_id)
            meta={k:entry[k] for k in ('kind','id','project_id','task_id')}; meta.update(version=1,title=payload['title'])
            content=encode(meta,payload['body_markdown'])
            target=self.root/entry['path']; _directory(target.parent)
            # A short rename/exclusive-publication protocol retains the displaced
            # inode. External editors do not participate in our advisory lock;
            # retain revisions even on success instead of claiming perfect FS CAS.
            revisions=target.parent/'.loop-work-revisions'; _directory(revisions)
            backup=revisions/(operation+'-'+uuid.uuid4().hex+'.md')
            intended=revisions/(operation+'-submitted-'+uuid.uuid4().hex+'.md')
            # Validate encoded receipt capacity before any target publication.
            _receipt_text(payload,{**current,'title':payload['title'],'body_markdown':payload['body_markdown'],
                'saved':True,'reused':False,'updated_at':now(),
                'previous_revision_path':str(backup.relative_to(self.root)),
                'submitted_revision_path':str(intended.relative_to(self.root))})
            _write(intended,content,None)
            intended_pin=_read_regular(intended,MAX_WIKI)[1]
            flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
            with ExitStack() as stack:
                fd=os.open(target.anchor,flags); stack.callback(os.close,fd)
                for part in target.parent.parts[1:]:
                    fd=os.open(part,flags,dir_fd=fd); stack.callback(os.close,fd)
                rfd=os.open('.loop-work-revisions',flags,dir_fd=fd); stack.callback(os.close,rfd)
                staged='.loop-wiki-'+uuid.uuid4().hex
                out=os.open(staged,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=fd)
                try:
                    with os.fdopen(out,'wb') as stream:
                        stream.write(content.encode('utf-8')); stream.flush(); os.fsync(stream.fileno())
                    # Check the inode after displacement, not only before rename.
                    os.rename(target.name,backup.name,src_dir_fd=fd,dst_dir_fd=rfd)
                    moved_raw=None
                    try:
                        moved_raw,moved_pin=_read_regular(backup,MAX_WIKI)
                        if moved_pin!=current['revision']:
                            raise WikiConflict('저장 중 외부 수정이 발견되었습니다. 원문과 초안을 보존했습니다.')
                        os.link(staged,target.name,src_dir_fd=fd,dst_dir_fd=fd,follow_symlinks=False)
                    except BaseException:
                        try:
                            if moved_raw is not None:
                                _write(target,moved_raw.decode('utf-8'),None)
                            else:
                                os.link(backup.name,target.name,src_dir_fd=rfd,dst_dir_fd=fd,follow_symlinks=False)
                        except (FileExistsError,LoopError):
                            pass
                        raise
                except OSError as exc:
                    raise WikiConflict('위키 저장 충돌: 다른 파일과 원문을 보존했습니다.') from exc
                finally:
                    os.unlink(staged,dir_fd=fd)
            try:
                published=self.get(kind,identifier,project_id)
                if published['revision']!=intended_pin:
                    raise WikiConflict('게시 후 외부 수정이 발견되었습니다.')
            except (LoopError,OSError,UnicodeError) as exc:
                raise WikiConflict('저장 확인 충돌: 외부 현재 원문·이전 원문·제출 초안을 보존했습니다. 제출본: '+str(intended.relative_to(self.root))) from exc
            result={**published,'saved':True,'reused':False,'previous_revision_path':str(backup.relative_to(self.root)),
                    'submitted_revision_path':str(intended.relative_to(self.root))}
            _directory(folder)
            _write(receipt_path,_receipt_text(payload,result),None)
            return result
