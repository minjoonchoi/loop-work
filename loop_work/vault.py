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
from .vault_layout import slug, validate_relative, validate_metadata, validate_document_path, validate_mapping


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


def read_export_json(path, default=None):
    """Missing is optional; links, FIFOs, malformed and oversized files are not."""
    try:
        raw,_=_read_regular(path,MAX_EXPORT_JSON)
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


def _board_frontmatter(knowledge, kind, record, body):
    """JSON is a single YAML-compatible flow value, never executable markup."""
    envelope = {'version': 1, 'kind': kind, 'id': record['id'],
                'knowledge_home': str(knowledge.home.resolve()), 'record': record}
    return '---\nloop_work: ' + json.dumps(envelope, ensure_ascii=True, separators=(',', ':')) + '\n---\n' + body


def _prefix_board_body(content, prefix):
    header, separator, body = content.partition('\n---\n')
    if content.startswith('---\nloop_work: ') and separator:
        return header + separator + prefix + body
    return prefix + content


class VaultExporter:
    def __init__(self, knowledge, root):
        self.knowledge = knowledge
        self.root = Path(root).expanduser().absolute()
        # Guard identity is lexical only: filesystem operations retain the original
        # spelling so _directory still rejects every symlink component before '..'.
        self.target_identity = os.path.normpath(str(self.root))
        self.manifest = knowledge.home / 'vault-owned.json'
        self.marker = knowledge.home / ('vault-export-initialized-' + digest(self.target_identity)[:32] + '.json')

    def _path(self, logical, proposed, legacy=None):
        paths = self.inventory['paths']
        if logical not in paths:
            paths[logical] = legacy if legacy and (legacy in self.inventory['files'] or os.path.lexists(self.root / legacy)) else proposed
        selected = validate_mapping(logical, paths[logical])
        if any(other != logical and target == selected for other, target in paths.items()):
            raise LoopError('Vault logical documents cannot share a frozen path')
        if logical.startswith('snapshot:') and not selected.endswith(logical.rsplit(':',1)[1][:20] + '.md'):
            raise LoopError('Vault snapshot path identity mismatch')
        if logical.startswith('history:') and not selected.endswith(logical.rsplit(':',1)[1] + '.md'):
            raise LoopError('Vault history path identity mismatch')
        return selected

    def _project(self, project_id):
        project = self.knowledge.get('project', project_id, required=False) or {}
        name = slug(project.get('name') or project_id, project_id)
        mapped = self.inventory['paths'].setdefault('project:' + project_id, 'projects/' + name)
        validate_relative(mapped)
        if not mapped.startswith('projects/') or len(mapped.split('/')) != 2 or not mapped.endswith('--' + project_id):
            raise LoopError('Vault project layout identity mismatch')
        return mapped.split('/')[1]

    def _base(self, project_id, task):
        legacy = 'projects/' + _safe(project_id) + '/tasks/' + _safe(task['id']) + '/'
        logical = 'task:' + project_id + ':' + task['id']
        primary = self._path(logical, 'projects/' + self._project(project_id) + '/tasks/' + slug(task['title'], task['id']) + '/현재-' + slug(task['title'], task['id']) + '.md', legacy + 'current.md')
        return primary.rsplit('/', 1)[0] + '/', primary, legacy

    def _add(self, documents, path, kind, record, body, role, project_id=None, task_id=None, legacy=False):
        descriptor = dict(kind=kind, id=record['id'], role=role, project_id=project_id, task_id=task_id)
        if legacy:
            content = _board_frontmatter(self.knowledge, kind, record, body) if role == 'current' or kind == 'human-request' else body
        else:
            envelope = dict(version=2, knowledge_home=str(self.knowledge.home.resolve()), record=record, **descriptor)
            validate_document_path(path, envelope)
            content = '---\nloop_work: ' + json.dumps(envelope, ensure_ascii=True, separators=(',', ':')) + '\n---\n' + body
        documents[path] = content
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

    def _task(self, task_id, documents):
        from .writing import task_document
        task = self.knowledge.get('task', task_id)
        value = {**task, 'delegations': self.knowledge.delegations(task_id)}
        snapshot = digest(value)
        cutoff = task.get('updated_at') or task.get('created_at') or snapshot
        body = _local_view(task_document(value, language='ko'), self.knowledge, 'task', task_id) + ('\n## 내보내기 범위\n\n기준 시점: ' + str(cutoff) + '\n\nSQLite/JSON이 원본 기록입니다. 이 문서는 승인이나 품질 검증 통과를 부여하지 않습니다.\n근거 경로는 원래 로컬 산출물 없이 이식 가능하지 않습니다.\n원본 데이터베이스: ' + str(self.knowledge.path) + '\n기록 해시: ' + snapshot + '\n')
        for project_id in task.get('project_ids') or ['unassigned']:
            base, primary, legacy = self._base(project_id, task)
            old = primary == legacy + 'current.md'
            self._add(documents, primary, 'task', task, body, 'current', project_id, task_id, old)
            complete = task.get('phase') == 'completed' and (task.get('result') or {}).get('evidence_current') is not False
            role = 'final' if complete else 'interim'
            name = self._path('snapshot:' + project_id + ':' + task_id + ':' + snapshot,
                (legacy + role + '/' + snapshot[:20] + '.md') if old else base + role + '/' + ('완료-' if complete else '중간-') + slug(task['title'],task_id) + '-' + snapshot[:20] + '.md',
                legacy + role + '/' + snapshot[:20] + '.md')
            notice = '과거 완료 시점의 기록입니다. 현재 문서의 최신성과 품질 검증을 별도로 확인하세요.\n\n' if complete else ''
            if name in self.inventory['files']:
                self.immutable_paths.add(name)
            else:
                self._add(documents, name, 'task', task, notice + body, role, project_id, task_id, old)
            for index, historical in enumerate(self.knowledge.history('task', task_id), 1):
                hr = 'final' if historical.get('phase') == 'completed' and (historical.get('result') or {}).get('evidence_current') is not False else 'interim'
                hd = digest(historical)[:20]
                name = self._path('history:' + project_id + ':' + task_id + ':' + str(index) + ':' + hd,
                    (legacy + hr + '/history-' + str(index) + '-' + hd + '.md') if old else base + hr + '/이력-' + slug(task['title'],task_id) + '-' + str(index) + '-' + hd + '.md', legacy + hr + '/history-' + str(index) + '-' + hd + '.md')
                if name in self.inventory['files']:
                    self.immutable_paths.add(name)
                else:
                    previous = '과거 작업 기록입니다. 당시 위임 상태를 현재 기록으로 재구성하지 않습니다. 현재 완료 판정은 별도 확인이 필요합니다.\n\n' + _local_view(task_document(historical, language='ko'), self.knowledge, 'task', task_id)
                    self._add(documents,name,'task',historical,previous,hr,project_id,task_id,old)
            # A readable index is a navigation-only compatibility view, never another current.
            index_path = self._path('index:task:' + project_id + ':' + task_id, 'projects/' + self._project(project_id) + '/작업색인/' + slug(task['title'],task_id) + '.md')
            relative = os.path.relpath(self.root / primary, (self.root / index_path).parent).replace(os.sep, '/')
            self._index(documents,index_path,task,[('현재 작업 기록',relative)],project_id,task_id)
            project = self.knowledge.get('project',project_id,required=False) or {'id':project_id,'name':project_id}
            project_index = 'projects/' + self._project(project_id) + '/프로젝트색인.md'
            # Read committed tasks, rather than discarding earlier index entries on each export.
            links=[]
            for other in self.knowledge.list('task'):
                if project_id in (other.get('project_ids') or ['unassigned']):
                    _, target, _ = self._base(project_id,other)
                    links.append((str(other.get('title') or other['id']).replace('[','').replace(']',''),os.path.relpath(self.root/target,(self.root/project_index).parent).replace(os.sep,'/')))
            self._index(documents,project_index,project,links,project_id)
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
            manifest = read_export_json(self.manifest, {'version': 1, 'vault': str(self.root), 'files': {}})
            if manifest.get('version') != 1 or manifest.get('vault') != str(self.root) or not isinstance(manifest.get('files'), dict):
                raise LoopError('Vault ownership manifest changed; existing notes preserved')
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
            manifest['layout_version'] = 2
            self.inventory = manifest
            self.immutable_paths = set()
            self.indexes = []
            documents = {}
            value = self.knowledge.get(kind, key)
            if kind == 'task':
                self._task(key, documents)
            elif kind == 'topic':
                project_id = value.get('project_id') if value.get('scope') != 'global' else None
                scope = value.get('scope', 'global')
                _safe(scope)
                prefix = ('projects/' + self._project(project_id) + '/topics/' + (scope + '/' if scope != 'project' else '')) if project_id else 'topics/' + scope + '/'
                proposed = prefix + slug(value['summary'],key) + '.md'
                note = self._path('topic:' + key, proposed, 'topics/' + key + '.md')
                body = _local_view(topic_document(value, language='ko'), self.knowledge, 'topic', key) + '\n파생 지식 문서입니다. 로컬 근거에는 원래 산출물이 필요하며 승인 권한을 부여하지 않습니다.\n'
                self._add(documents,note,'topic',value,body,'topic',project_id, value.get('task_id'),note == 'topics/' + key + '.md')
                index = self._path('index:topic:' + key,prefix + '색인-' + slug(value['summary'],key) + '.md')
                relative = os.path.relpath(self.root/note,(self.root/index).parent).replace(os.sep,'/')
                self._index(documents,index,value,[('지식 기록',relative)],project_id,value.get('task_id'),kind='topic')
            elif value.get('task_id'):
                task = self._task(value['task_id'], documents)
                for project_id in task.get('project_ids') or ['unassigned']:
                    base, primary, legacy = self._base(project_id, task)
                    folder = 'delegations/' if kind == 'delegation' else 'records/' + kind + '/'
                    title = value.get('title') or value.get('summary') or value.get('question') or (value.get('request') or {}).get('instruction') or task['title']
                    note = self._path(kind + ':' + project_id + ':' + key, (legacy + folder + key + '.md') if primary == legacy + 'current.md' else base + folder + slug(title,key) + '.md',legacy + folder + key + '.md')
                    if kind == 'delegation':
                        body = _local_view(delegation_document(value, language='ko'),self.knowledge,kind,key)
                    elif kind in ('team','human-request','feedback','retirement'):
                        body = '# ' + str(title).replace('\n',' ') + '\n\n## 원본 기록\n\n```json\n' + json.dumps(value,ensure_ascii=False,indent=2).replace('```','\\u0060\\u0060\\u0060') + '\n```\n\n파생 기록입니다. 승인·완료 권한을 부여하지 않습니다.\n'
                    else:
                        continue
                    self._add(documents,note,kind,value,body,kind,project_id,value['task_id'],note == legacy + folder + key + '.md')
            if not documents:
                return {'enabled': True, 'status': 'unchanged', 'vault': str(self.root), 'errors': []}
            manifest['source_revision'] = source_revision
            for name, descriptor in manifest['documents'].items():
                if name in documents and descriptor.get('role') == 'current':
                    documents[name] = _prefix_board_body(documents[name], '최종 내보내기 기준: ' + json.dumps(source_revision,sort_keys=True) + '\n이 문서는 저장된 데이터보다 늦을 수 있습니다. 최신성은 내보내기 상태와 함께 확인하세요.\n\n')
            errors, changed = [], []
            for name in sorted(self.immutable_paths):
                try:
                    if _export_pin(self.root / name) != manifest['files'][name]:
                        raise LoopError('Historical vault snapshot was edited or removed; preserved: ' + str(self.root / name))
                except (LoopError, OSError) as exc:
                    errors.append(str(exc))
            # Human-owned notes and Obsidian settings are outside this inventory.
            _directory(self.root / 'notes')
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
            if not self.manifest.exists() or digest(manifest) != original_manifest:
                # Revalidate the retained inventory immediately before publication.
                retained=read_export_json(self.manifest)
                if retained is not None and digest(retained)!=original_manifest:
                    raise LoopError('Vault ownership manifest changed during export; preserved')
                write_json(self.manifest, manifest)
        return {'enabled': True, 'status': 'conflict' if errors else 'ok', 'vault': str(self.root), 'changed': changed, 'errors': errors, 'source_revision': source_revision, 'at': now()}
