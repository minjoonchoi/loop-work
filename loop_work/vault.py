"""Optional human-readable Obsidian views; SQLite remains authoritative."""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import stat

from .storage import LoopError, digest, now, write_json
from .vault_layout import (slug, display_title, id_suffix, ROLE_FOLDERS, HISTORY_FOLDERS,
                           validate_relative, validate_metadata, validate_document_path, validate_mapping)


MAX_EXPORT_FILE = 8 * 1024 * 1024
MAX_EXPORT_JSON = 2 * 1024 * 1024


def _read_regular(path, limit=MAX_EXPORT_FILE):
    """Bound optional export reads before opening any nonregular candidate."""
    path=Path(path).absolute()
    flags=os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    with ExitStack() as opened:
        fd=os.open(path.anchor,flags); opened.callback(os.close,fd)
        for part in path.parts[1:-1]:
            fd=os.open(part,flags,dir_fd=fd); opened.callback(os.close,fd)
        source=os.open(path.name,os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,dir_fd=fd)
        opened.callback(os.close,source)
        info=os.fstat(source)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size>limit:
            raise LoopError('Unsafe or oversized optional vault export file preserved: '+str(path))
        raw=bytearray()
        while True:
            block=os.read(source,min(65536,limit+1-len(raw)))
            if not block:
                break
            raw.extend(block)
            if len(raw)>limit:
                raise LoopError('Optional vault export file exceeds size limit: '+str(path))
        return bytes(raw),digest({'content':hashlib.sha256(raw).hexdigest(),'executable':bool(info.st_mode & 0o111)})


def read_export_json(path, default=None, *, limit=MAX_EXPORT_JSON):
    """Missing is optional; links, FIFOs, malformed and oversized files are not."""
    try:
        raw,_=_read_regular(path,limit)
    except FileNotFoundError:
        return default
    try:
        value=json.loads(raw)
    except (ValueError,UnicodeError,RecursionError) as exc:
        raise LoopError('Malformed optional vault export metadata: '+str(path)) from exc
    if not isinstance(value,dict):
        raise LoopError('Optional vault export metadata must be an object: '+str(path))
    return value


def _export_pin(path):
    try:
        return _read_regular(path)[1]
    except FileNotFoundError:
        return None


def _safe(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', value):
        raise LoopError('Unsafe vault record identifier')
    return value


def _directory(path):
    for item in [*reversed(path.parents), path]:
        if item.is_symlink():
            raise LoopError('Vault path cannot traverse symlinks: ' + str(item))
        if item.exists() and not item.is_dir():
            raise LoopError('Vault parent is not a directory: ' + str(item))
    path.mkdir(parents=True, exist_ok=True)


@contextmanager
def locked(root):
    """The optional export lock must reject unsafe files without waiting."""
    path=root/'.loop/state/lock'
    _directory(path.parent)
    fd=os.open(path,os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK,0o600)
    try:
        info=os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
            raise LoopError('Unsafe optional vault export lock preserved: '+str(path))
        try:
            fcntl.flock(fd,fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise LoopError('Another loop command is running in this repository') from exc
        try:
            yield
        finally:
            fcntl.flock(fd,fcntl.LOCK_UN)
    finally:
        os.close(fd)


# Explicit alias for the knowledge exporter diagnostics callgraph.
export_locked = locked

def _write(path, content, expected):
    _directory(path.parent)
    if path.is_symlink():
        raise LoopError('Vault target is a symlink: ' + str(path))
    if path.exists():
        if expected is None or _export_pin(path) != expected:
            raise LoopError('User-edited or unowned vault file preserved: ' + str(path))
        if _read_regular(path)[0].decode('utf-8') == content:
            return expected
    elif expected is not None:
        raise LoopError('Previously generated vault file was removed; preserved absence: ' + str(path))
    fd, temporary = tempfile.mkstemp(prefix='.loop-vault-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as output:
            output.write(content); output.flush(); os.fsync(output.fileno())
        if expected is None:
            os.link(temporary, path)  # Never clobber a concurrently created note.
            os.unlink(temporary)  # Drop our private link before validating the published note.
        else:
            if path.is_symlink() or _export_pin(path) != expected:
                raise LoopError('Vault file changed during export; preserved: ' + str(path))
            os.replace(temporary, path)
        return _export_pin(path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _local_view(text, knowledge, kind, key):
    uri = (knowledge.home / 'views' / kind / (key + '.json')).as_uri()
    return text.replace('[Full record](' + key + '.json)', '[현재 파생 JSON 기록](<' + uri + '>)').replace('[전체 기록](' + key + '.json)', '[현재 파생 JSON 기록](<' + uri + '>)')


class VaultExporter:
    def __init__(self, knowledge, root):
        self.knowledge = knowledge
        self.root = Path(root).expanduser().absolute()
        # Guard identity is lexical only: filesystem operations retain the original
        # spelling so _directory still rejects every symlink component before '..'.
        self.target_identity = os.path.normpath(str(self.root))
        self.manifest = knowledge.home / 'vault-owned.json'
        self.marker = knowledge.home / ('vault-export-initialized-' + digest(self.target_identity)[:32] + '.json')

    def _path(self, logical, proposed):
        paths = self.inventory['paths']
        selected = validate_mapping(logical, paths.setdefault(logical, proposed))
        if any(other != logical and target == selected for other, target in paths.items()):
            raise LoopError('Vault logical documents cannot share a frozen path')
        return selected

    def _project(self, project_id):
        project = self.knowledge.get('project', project_id, required=False) or {'name':'프로젝트'}
        mapped = self._path('project:' + project_id, '프로젝트/' + slug(display_title(project), project_id))
        return mapped.split('/')[1]

    def _base(self, project_id, task):
        logical = 'task:' + project_id + ':' + task['id']
        primary = self._path(logical, '프로젝트/' + self._project(project_id) + '/작업/' + slug(display_title(task), task['id']) + '/진행 현황.md')
        return primary.rsplit('/', 1)[0] + '/', primary

    def _topic_path(self, value):
        project_id = value.get('project_id') if value.get('scope') != 'global' else None
        prefix = '프로젝트/' + self._project(project_id) + '/지식/' if project_id else '공통 지식/'
        return self._path('topic:' + value['id'], prefix + slug(display_title(value), value['id']) + '.md')

    def _add(self, documents, path, kind, record, body, role, project_id=None, task_id=None):
        descriptor = dict(kind=kind, id=record['id'], role=role, project_id=project_id, task_id=task_id)
        envelope = dict(version=3, knowledge_home=str(self.knowledge.home.resolve()), record=record, **descriptor)
        validate_document_path(path, envelope)
        documents[path] = '---\nloop_work: ' + json.dumps(envelope, ensure_ascii=False, separators=(',', ':')) + '\n---\n' + body
        self.inventory['documents'][path] = descriptor

    def _index(self, documents, path, record, links, project_id=None, task_id=None, kind=None):
        self.indexes.append((path, record, links, project_id, task_id, kind))

    def _index_content(self, path, record, links, project_id, task_id, kind, verified):
        from urllib.parse import quote
        from .writing import plain
        body = '# ' + plain(record.get('title') or record.get('summary') or record.get('name') or record['id']) + '\n\n이 색인은 탐색용입니다. 승인·완료·품질 판정 권한을 만들지 않습니다.\n\n'
        for label, target in links:
            absolute = Path(os.path.normpath((self.root / path).parent / target))
            try:
                relative = str(absolute.relative_to(Path(self.target_identity)))
                expected = self.inventory['files'].get(relative)
                valid = relative not in self.inventory['reservations'] and expected is not None and _export_pin(absolute) == expected
                descriptor = self.inventory['documents'].get(relative)
                if valid and relative not in verified:
                    # A previous export is navigable only while its raw record is current.
                    raw, _ = _read_regular(absolute)
                    match = re.match(rb'^---\nloop_work: ([^\n]+)\n---\n', raw)
                    metadata = json.loads(match[1]) if match else None
                    valid = bool(metadata and descriptor and metadata.get('record') == self.knowledge.get(descriptor['kind'], descriptor['id'], required=False))
                if valid:
                    body += '- [' + plain(label) + '](<' + quote(target, safe='/') + '>)\n'
                else:
                    body += '- ' + plain(label) + ' — 확인 불가: 현재 생성 문서가 없거나 최신성·소유권을 확인할 수 없습니다.\n'
            except (LoopError, OSError, ValueError, KeyError, TypeError):
                body += '- ' + plain(label) + ' — 확인 불가: 현재 생성 문서를 검증할 수 없습니다.\n'
        documents = {}
        self._add(documents,path,kind or ('task' if task_id else ('project' if project_id else 'topic')),record,body,'index',project_id,task_id)
        return documents[path]

    def _project_index(self, project_id):
        project = self.knowledge.get('project',project_id,required=False) or {'id':project_id,'name':'프로젝트'}
        path = '프로젝트/' + self._project(project_id) + '/목록.md'
        links = []
        for task in self.knowledge.list('task'):
            if project_id in (task.get('project_ids') or ['unassigned']):
                _, target = self._base(project_id,task)
                links.append(('작업 · ' + display_title(task),os.path.relpath(self.root/target,(self.root/path).parent).replace(os.sep,'/')))
        for topic in self.knowledge.list('topic'):
            if topic.get('scope') != 'global' and topic.get('project_id') == project_id:
                target = self._topic_path(topic)
                links.append(('지식 · ' + display_title(topic),os.path.relpath(self.root/target,(self.root/path).parent).replace(os.sep,'/')))
        self._index({},path,project,links,project_id,kind='project')

    @staticmethod
    def _record_date(record):
        value = str(record.get('updated_at') or record.get('created_at') or '')
        return value[:10] if re.match(r'^[0-9]{4}-[0-9]{2}-[0-9]{2}(?:T|$)',value) else '날짜미상'

    def _task(self, task_id, documents):
        from .writing import task_document
        task = self.knowledge.get('task', task_id)
        value = {**task, 'delegations': self.knowledge.delegations(task_id)}
        snapshot = digest(value)
        cutoff = task.get('updated_at') or task.get('created_at') or snapshot
        body = _local_view(task_document(value, language='ko'), self.knowledge, 'task', task_id)
        body += ('\n<details>\n<summary>내보내기 정보</summary>\n\n기준 시점: ' + str(cutoff)
                 + '\n\nSQLite/JSON이 실행·권한·검증의 원본입니다. 이 문서는 승인이나 품질 검증 통과를 부여하지 않습니다.\n'
                 + '로컬 근거에는 원래 산출물이 필요합니다.\n\n원본 데이터베이스: ' + str(self.knowledge.path)
                 + '\n\n기록 해시: ' + snapshot + '\n\n</details>\n')
        for project_id in task.get('project_ids') or ['unassigned']:
            self.index_projects.add(project_id)
            base, primary = self._base(project_id, task)
            self._add(documents, primary, 'task', task, body, 'current', project_id, task_id)
            complete = task.get('phase') == 'completed' and (task.get('result') or {}).get('evidence_current') is not False
            role = 'final' if complete else 'interim'
            name = self._path('snapshot:' + project_id + ':' + task_id + ':' + snapshot,
                              base + '기록/' + HISTORY_FOLDERS[role] + '/' + self._record_date(task) + '-' + HISTORY_FOLDERS[role] + '-' + snapshot[:20] + '.md')
            notice = '과거 완료 시점의 기록입니다. 현재 문서의 최신성과 품질 검증을 별도로 확인하세요.\n\n' if complete else ''
            if name in self.inventory['files']:
                self.immutable_paths.add(name)
            else:
                self._add(documents, name, 'task', task, notice + body, role, project_id, task_id)
            for index, historical in enumerate(self.knowledge.history('task', task_id), 1):
                hr = 'final' if historical.get('phase') == 'completed' and (historical.get('result') or {}).get('evidence_current') is not False else 'interim'
                hd = digest(historical)[:20]
                name = self._path('history:' + project_id + ':' + task_id + ':' + str(index) + ':' + hd,
                                  base + '기록/' + HISTORY_FOLDERS[hr] + '/' + self._record_date(historical) + '-이력-' + str(index).zfill(3) + '-' + hd + '.md')
                if name in self.inventory['files']:
                    self.immutable_paths.add(name)
                else:
                    previous = '과거 작업 기록입니다. 당시 위임 상태를현재 기록으로 재구성하지 않습니다. 현재 완료 판정은 별도 확인이 필요합니다.\n\n' + _local_view(task_document(historical, language='ko'), self.knowledge, 'task', task_id)
                    self._add(documents,name,'task',historical,previous,hr,project_id,task_id)
        return value

    def export(self, kind, key):
        from .writing import delegation_document, topic_document
        _safe(kind); _safe(key)
        # Read committed records only after serialization: a delayed older
        # exporter must not overwrite a newer current view with stale rendering.
        with locked(self.knowledge.home / 'vault-export'):
            source_revision = self.knowledge.vault_revision()
            _directory(self.root)
            if self.manifest.is_symlink():
                raise LoopError('Vault ownership manifest cannot be a symlink')
            if not self.manifest.exists():
                prior = read_export_json(self.knowledge.home / 'vault-export-status.json', {})
                entries = prior.get('records', {})
                if not isinstance(entries, dict):
                    raise LoopError('Vault prior-export diagnostics are malformed; ownership uncertainty preserved')
                prior_export = any(isinstance(item, dict) and isinstance(item.get('vault'), str) and os.path.normpath(item['vault']) == self.target_identity and (item.get('status') in ('ok','conflict') or item.get('changed')) for item in entries.values())
                if os.path.lexists(self.marker) or prior_export:
                    raise LoopError('Vault ownership inventory is missing after prior export; existing files and absence preserved')
            manifest = read_export_json(self.manifest, {'version': 1, 'layout_version':3, 'vault': str(self.root), 'files': {}})
            if manifest.get('version') != 1 or manifest.get('vault') != str(self.root) or not isinstance(manifest.get('files'), dict):
                raise LoopError('Vault ownership manifest changed; existing notes preserved')
            if manifest.get('layout_version') != 3:
                raise LoopError('Vault layout requires explicit reorganization; run scripts/reorganize_vault.py --plan first. Existing notes preserved')
            original_manifest = digest(manifest)
            for field in ('paths','documents','reservations'):
                if not isinstance(manifest.setdefault(field, {}), dict):
                    raise LoopError('Invalid vault layout inventory')
            for path in list(manifest['files']) + list(manifest['paths'].values()) + list(manifest['documents']) + list(manifest['reservations']):
                validate_relative(path)
            for logical, path in manifest['paths'].items():
                validate_mapping(logical, path)
            if len(set(manifest['paths'].values())) != len(manifest['paths']):
                raise LoopError('Vault logical documents cannot share a frozen path')
            manifest['layout_version'] = 3
            self.inventory = manifest
            self.immutable_paths = set()
            self.indexes = []
            self.index_projects = set()
            documents = {}
            value = self.knowledge.get(kind, key)
            if kind == 'task':
                self._task(key, documents)
            elif kind == 'topic':
                project_id = value.get('project_id') if value.get('scope') != 'global' else None
                note = self._topic_path(value)
                if project_id:
                    self.index_projects.add(project_id)
                body = _local_view(topic_document(value, language='ko'), self.knowledge, 'topic', key)
                body += '\n파생 지식 문서입니다. 로컬 근거에는 원래 산출물이 필요하며 승인 권한을 부여하지 않습니다.\n'
                self._add(documents,note,'topic',value,body,'topic',project_id,value.get('task_id'))
            elif value.get('task_id'):
                from .writing import record_document
                task = self._task(value['task_id'], documents)
                for project_id in task.get('project_ids') or ['unassigned']:
                    base, primary = self._base(project_id, task)
                    if kind not in ROLE_FOLDERS:
                        continue
                    note = self._path(kind + ':' + project_id + ':' + key,
                                      base + '기록/' + ROLE_FOLDERS[kind] + '/' + slug(display_title(value),key) + '.md')
                    rendered = delegation_document(value,language='ko') if kind == 'delegation' else record_document(value,kind,language='ko')
                    body = _local_view(rendered,self.knowledge,kind,key)
                    self._add(documents,note,kind,value,body,kind,project_id,value['task_id'])
            for project_id in sorted(self.index_projects):
                self._project_index(project_id)
            if not documents:
                return {'enabled': True, 'status': 'unchanged', 'vault': str(self.root), 'errors': []}
            manifest['source_revision'] = source_revision
            for name, descriptor in manifest['documents'].items():
                if name in documents and descriptor.get('role') == 'current':
                    documents[name] += ('\n<details>\n<summary>출력 최신성 정보</summary>\n\n최종 내보내기 기준: '
                                        + json.dumps(source_revision,sort_keys=True)
                                        + '\n\n이 문서는 저장된 데이터보다 늦을 수 있습니다. 최신성은 내보내기 상태와 함께 확인하세요.\n\n</details>\n')
            errors, changed = [], []
            for name in sorted(self.immutable_paths):
                try:
                    if _export_pin(self.root / name) != manifest['files'][name]:
                        raise LoopError('Historical vault snapshot was edited or removed; preserved: ' + str(self.root / name))
                except (LoopError, OSError) as exc:
                    errors.append(str(exc))
            # Human-owned notes and Obsidian settings are outside this inventory.
            _directory(self.root / '개인 메모')
            marker = {'version':1, 'vault':self.target_identity}
            retained_marker = read_export_json(self.marker)
            if retained_marker is not None and retained_marker != marker:
                raise LoopError('Vault prior-export marker changed; existing files preserved')
            if retained_marker is None:
                _write(self.marker, json.dumps(marker,sort_keys=True) + '\n', None)
            verified = set()
            def publish(name, content):
                try:
                    target = self.root / name
                    previous = manifest['files'].get(name)
                    if name in manifest['reservations']:
                        raise LoopError('Previously unowned or conflicting vault path remains reserved; file and absence preserved: ' + str(target))
                    if previous is None and os.path.lexists(target):
                        manifest['reservations'][name] = 'unowned conflict; preserve file and later absence'
                        raise LoopError('User-edited or unowned vault file preserved: ' + str(target))
                    before = _export_pin(target)
                    pin = _write(target, content, previous)
                    manifest['files'][name] = pin
                    verified.add(name)
                    if before != pin:
                        changed.append(name)
                except (LoopError, OSError, UnicodeError) as exc:
                    if manifest['files'].get(name) is None and os.path.lexists(self.root / name):
                        manifest['reservations'][name] = 'unowned conflict; preserve file and later absence'
                    errors.append(str(exc))
            for name, content in documents.items():
                publish(name, content)
            for args in self.indexes:
                try:
                    path = args[0]
                    content = self._index_content(*args, verified)
                    publish(path, content)
                except (LoopError, OSError, ValueError, TypeError) as exc:
                    errors.append(str(exc))
            # Wiki notes are human-owned prose. Create once only after a current
            # execution document was actually verified; never shadow a conflict.
            from .wiki import ensure as ensure_wiki
            for name in sorted(verified):
                descriptor=manifest['documents'].get(name,{})
                if descriptor.get('role')=='index' and descriptor.get('kind')=='project':
                    try:
                        project_id=descriptor['project_id']
                        project=self.knowledge.get('project',project_id,required=False) or {'id':project_id,'name':'프로젝트'}
                        project_base=manifest['paths']['project:'+project_id]+'/'
                        ensure_wiki(self.knowledge,self.root,manifest,'project',project,project_id,project_base,name)
                    except (LoopError,OSError,UnicodeError,KeyError) as exc:
                        errors.append(str(exc))
                    continue
                if descriptor.get('role')!='current':
                    continue
                try:
                    task=self.knowledge.get('task',descriptor['id'])
                    project_id=descriptor['project_id']
                    project=self.knowledge.get('project',project_id,required=False) or {'id':project_id,'name':project_id}
                    project_base=manifest['paths']['project:'+project_id]+'/'
                    ensure_wiki(self.knowledge,self.root,manifest,'project',project,project_id,project_base,project_base+'목록.md' if project_base+'목록.md' in verified else name)
                    ensure_wiki(self.knowledge,self.root,manifest,'task',task,project_id,name.rsplit('/',1)[0]+'/',name)
                except (LoopError,OSError,UnicodeError,KeyError) as exc:
                    errors.append(str(exc))
            if not self.manifest.exists() or digest(manifest) != original_manifest:
                # Revalidate the retained inventory immediately before publication.
                retained=read_export_json(self.manifest)
                if retained is not None and digest(retained)!=original_manifest:
                    raise LoopError('Vault ownership manifest changed during export; preserved')
                write_json(self.manifest, manifest)
        return {'enabled': True, 'status': 'conflict' if errors else 'ok', 'vault': str(self.root), 'changed': changed, 'errors': errors, 'source_revision': source_revision, 'at': now()}
