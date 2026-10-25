"""Explicit, pinned, non-destructive reorganization outside the vault runtime."""
from __future__ import annotations
from copy import deepcopy
from contextlib import ExitStack
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile
from urllib.parse import quote

from .storage import LoopError, digest
from .board import MAX_MANIFEST, MAX_NOTE, MAX_DOCUMENTS, MAX_TOTAL
from .vault import (VaultExporter, _directory, _read_regular, _export_pin, _write,
                    export_locked, read_export_json)
from .vault_layout import validate_relative, safe_id

PROTOCOL = 'readable-vault-reorganization-v1'
MAX_FILES = 12000
MAX_BYTES = 256 * 1024 * 1024
KINDS = ('task','topic','delegation','team','human-request','feedback','retirement')
_NO_DESCRIPTOR = object()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _snapshot(home):
    path = home / 'knowledge.sqlite3'
    _read_regular(path, MAX_BYTES)
    # Read-only is deliberate: no schema, chmod, task, history or control writes.
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)
    try:
        db.execute('BEGIN')
        records = db.execute('SELECT kind,id,body FROM records ORDER BY kind,id').fetchall()
        history = db.execute('SELECT sequence,kind,id,body,at FROM history ORDER BY sequence').fetchall()
        if len(records) + len(history) > 100000:
            raise LoopError('Vault reorganization exceeds the bounded record limit')
        return {'records':records,'history':history}
    finally:
        db.close()


class _ReadOnlyKnowledge:
    def __init__(self, snapshot, home, source_home):
        self.home = home
        self.path = source_home / 'knowledge.sqlite3'
        self.records = {(kind,key):json.loads(body) for kind,key,body in snapshot['records']}
        self.previous = snapshot['history']

    def get(self, kind, key, required=True):
        value = self.records.get((kind,key))
        if value is None and required:
            raise LoopError('Missing source record for vault reorganization')
        return deepcopy(value)

    def list(self, kind):
        return [deepcopy(value) for (k,_),value in sorted(self.records.items()) if k == kind]

    def history(self, kind, key):
        return [json.loads(body) for _,k,i,body,_ in self.previous if k == kind and i == key]

    def delegations(self, task_id):
        values = sorted(self.list('delegation'), key=lambda value:value['started_at'], reverse=True)
        return [{**{k:x.get(k) for k in ('id','provider','status','summary','error','attempts','applied','result')},
                 'assignment_id':x['request']['id'],'kind':x['request']['kind']}
                for x in values if x.get('task_id') == task_id]

    def vault_revision(self):
        return {'records':len(self.records),'history':max((row[0] for row in self.previous),default=0)}


def _scan_previous_execution(vault, allowed):
    """Bounded rechecks include additions and unsafe execution directory links."""
    old_root=vault/'projects';visited=0
    if old_root.is_symlink():
        raise LoopError('Previous execution document root cannot be a symlink')
    if not old_root.exists():
        return
    for directory,dirs,names in os.walk(old_root,followlinks=False):
        visited += len(dirs)+len(names)
        if visited > MAX_FILES*4:
            raise LoopError('Previous document discovery exceeds the bounded entry limit')
        for name in dirs:
            if (Path(directory)/name).is_symlink():
                raise LoopError('Previous execution namespace contains an unsafe directory link')
        for name in names:
            relative=str((Path(directory)/name).relative_to(vault));parts=relative.split('/')
            current=name == 'current.md' or name.startswith('현재-') and name.endswith('.md')
            scoped=(len(parts)>=6 and parts[0]=='projects' and parts[2]=='tasks')
            record=scoped and (parts[4]=='delegations' or len(parts)>=7 and parts[4]=='records'
                               and parts[5] in ('team','human-request','feedback','retirement'))
            history=scoped and parts[4] in ('interim','final')
            if (current or (record or history) and name.endswith('.md')) and relative not in allowed:
                raise LoopError('Unowned previous execution document preserved; reorganization refused: '+relative)


# Converter-only copy of the previous layout's pure authority validators.
# These are never called by the current Board or runtime exporter.
def _old_validate_metadata(value):
    fields = {'version','kind','id','knowledge_home','record','role','project_id','task_id'}
    if not isinstance(value, dict) or set(value) != fields or (type(value.get('version')) is not int or value.get('version') != 2):
        raise LoopError('Invalid vault document metadata')
    safe_id(value['kind']); safe_id(value['id'])
    if value['role'] in ('current','interim','final') and (value['kind'] != 'task' or value['task_id'] != value['id']):
        raise LoopError('Vault task role identity mismatch')
    if value['role'] in ('topic','delegation','team','human-request','feedback','retirement') and value['kind'] != value['role']:
        raise LoopError('Vault request role identity mismatch')
    for key in ('project_id','task_id'):
        if value[key] is not None:
            safe_id(value[key])
    if value['role'] not in ('current','interim','final','topic','delegation','team','human-request','feedback','retirement','index'):
        raise LoopError('Invalid vault document role')
    if not isinstance(value['knowledge_home'], str) or not isinstance(value['record'], dict) or value['record'].get('id') != value['id']:
        raise LoopError('Invalid vault document identity')
    return value


def _old_topic_directory(parts, metadata):
    """Scope is an exact namespace, not a filename or optional path prefix."""
    project = metadata['project_id']
    scope = metadata['record'].get('scope')
    scopes = ('global','project','checkout','session','task')
    if scope is not None and scope not in scopes:
        return False
    if project is None:
        return (len(parts) == 3 and parts[0] == 'topics'
                and parts[1] in scopes and (scope is None or parts[1] == scope))
    if len(parts) < 4 or parts[0] != 'projects' or not parts[1].endswith('--' + project) or parts[2] != 'topics':
        return False
    if scope == 'project':
        return len(parts) == 4
    if scope is None:
        # Manifest descriptors have identity only; the full envelope is checked again.
        return len(parts) == 4 or (len(parts) == 5 and parts[3] in ('checkout','session','task'))
    return len(parts) == 5 and parts[3] == scope and scope in ('checkout','session','task')


def _old_validate_document_path(path, metadata):
    validate_relative(path); _old_validate_metadata(metadata)
    parts = path.split('/')
    if metadata['role'] in ('current','interim','final','delegation','team','human-request','feedback','retirement'):
        if metadata['project_id'] is None or metadata['task_id'] is None:
            raise LoopError('Vault task scope is missing')
        if len(parts) < 5 or parts[0] != 'projects' or parts[2] != 'tasks':
            raise LoopError('Vault document is outside its declared task')
        if not parts[1].endswith('--' + str(metadata['project_id'])) or not parts[3].endswith('--' + str(metadata['task_id'])):
            raise LoopError('Vault document path identity mismatch')
        role = metadata['role']
        if role == 'current' and (len(parts) != 5 or not parts[4].startswith('현재-') or not parts[4].endswith('--' + metadata['task_id'] + '.md')):
            raise LoopError('Invalid current vault document path')
        if role in ('interim','final') and (len(parts) != 6 or parts[4] != role):
            raise LoopError('Invalid history vault document path')
        if role == 'delegation' and (len(parts) != 6 or parts[4] != 'delegations' or not parts[-1].endswith('--' + metadata['id'] + '.md')):
            raise LoopError('Invalid delegation vault document path')
        if role in ('team','human-request','feedback','retirement') and (len(parts) != 7 or parts[4:6] != ['records',role] or not parts[-1].endswith('--' + metadata['id'] + '.md')):
            raise LoopError('Invalid record vault document path')
    if metadata['role'] == 'index':
        project, task = metadata['project_id'], metadata['task_id']
        if metadata['kind'] == 'topic':
            scope = metadata['record'].get('scope')
            expected_project = metadata['record'].get('project_id') if scope != 'global' else None
            if 'scope' in metadata['record'] and (project != expected_project or task != metadata['record'].get('task_id')):
                raise LoopError('Vault topic index scope mismatch')
            valid = parts[-1].startswith('색인-') and parts[-1].endswith('--' + metadata['id'] + '.md')
            valid = valid and _old_topic_directory(parts, metadata)
        elif task is not None:
            valid = (metadata['kind'] == 'task' and metadata['id'] == task and len(parts) == 4 and parts[0] == 'projects' and parts[1].endswith('--' + str(project)) and parts[2] == '작업색인' and parts[3].endswith('--' + task + '.md'))
        elif project is not None:
            valid = metadata['kind'] == 'project' and metadata['id'] == project and len(parts) == 3 and parts[0] == 'projects' and parts[1].endswith('--' + project) and parts[2] == '프로젝트색인.md'
        else:
            valid = metadata['kind'] == 'topic' and parts[-1].startswith('색인-') and parts[-1].endswith('--' + metadata['id'] + '.md') and ('topics' in parts)
        if not valid:
            raise LoopError('Invalid vault index path')
    if metadata['role'] == 'topic':
        if not path.endswith('--' + metadata['id'] + '.md') or 'topics' not in parts:
            raise LoopError('Invalid vault topic path')
        project = metadata['project_id']
        scope = metadata['record'].get('scope')
        if 'scope' in metadata['record'] and (project != (metadata['record'].get('project_id') if scope != 'global' else None) or metadata['task_id'] != metadata['record'].get('task_id')):
            raise LoopError('Vault topic record scope mismatch')
        if not _old_topic_directory(parts, metadata):
            raise LoopError('Vault topic scope directory mismatch')
    if not path.endswith('.md'):
        raise LoopError('Vault document must be Markdown')
    return path


def _old_validate_mapping(logical, path):
    """Check frozen names against their logical identity before any export writes."""
    validate_relative(path)
    if not isinstance(logical, str):
        raise LoopError('Invalid vault logical document key')
    key = logical.split(':'); category = key[0]; parts = path.split('/')
    if category == 'project' and len(key) == 2:
        safe_id(key[1])
        valid = len(parts) == 2 and parts[0] == 'projects' and parts[1].endswith('--' + key[1])
    elif category == 'task' and len(key) == 3:
        project, task = map(safe_id,key[1:])
        legacy = 'projects/' + project + '/tasks/' + task + '/current.md'
        valid = path == legacy or (len(parts) == 5 and parts[0] == 'projects' and parts[1].endswith('--' + project) and parts[2] == 'tasks' and parts[3].endswith('--' + task) and parts[4].startswith('현재-') and parts[4].endswith('--' + task + '.md'))
    elif category in ('snapshot','history') and len(key) == (4 if category == 'snapshot' else 5):
        project, task = map(safe_id,key[1:3]); token = key[-1]
        expected = token[:20] if category == 'snapshot' else token
        valid = bool(re.fullmatch('[0-9a-f]{64}' if category == 'snapshot' else '[0-9a-f]{20}',token)) and len(parts) == 6 and parts[0] == 'projects' and parts[2] == 'tasks' and parts[1].endswith('--' + project) and parts[3].endswith('--' + task) and parts[4] in ('interim','final') and parts[-1].endswith(expected + '.md')
        legacy = len(parts) == 6 and parts[:4] == ['projects',project,'tasks',task] and parts[4] in ('interim','final') and parts[-1].endswith(expected + '.md')
        valid = valid or legacy
    elif category == 'topic' and len(key) == 2:
        identifier = safe_id(key[1]); valid = path == 'topics/' + identifier + '.md' or ('topics' in parts and parts[-1].endswith('--' + identifier + '.md'))
    elif category == 'index' and len(key) in (3,4):
        if key[1] == 'task' and len(key) == 4:
            project, task = map(safe_id,key[2:]); valid = len(parts) == 4 and parts[0] == 'projects' and parts[1].endswith('--' + project) and parts[2] == '작업색인' and parts[-1].endswith('--' + task + '.md')
        elif key[1] == 'topic' and len(key) == 3:
            identifier=safe_id(key[2]); valid='topics' in parts and parts[-1].startswith('색인-') and parts[-1].endswith('--' + identifier + '.md')
        else:
            valid=False
    elif category in ('delegation','team','human-request','feedback','retirement') and len(key) == 3:
        project, identifier = map(safe_id,key[1:]); folder=['delegations'] if category == 'delegation' else ['records',category]
        valid = len(parts) == 5 + len(folder) and parts[0] == 'projects' and (parts[1] == project or parts[1].endswith('--' + project)) and parts[2] == 'tasks' and parts[4:-1] == folder and (parts[-1] == identifier + '.md' or parts[-1].endswith('--' + identifier + '.md'))
    else:
        valid=False
    if not valid:
        raise LoopError('Vault frozen path does not match its logical identity')
    return path


def _validate_previous_manifest(manifest, home, vault):
    """Preserve the complete old Board manifest predicate before conversion."""
    if (not isinstance(manifest,dict) or manifest.get('version')!=1 or manifest.get('vault')!=str(vault)
            or not isinstance(manifest.get('files'),dict) or not all(isinstance(name,str) for name in manifest['files'])):
        raise LoopError('Previous ownership manifest is invalid; replacement authority refused')
    for name in manifest['files']:
        validate_relative(name)
    if 'layout_version' in manifest and manifest['layout_version']!=2:
        raise LoopError('Previous layout version was not authoritative; replacement authority refused')
    if not isinstance(manifest.get('paths',{}),dict) or not isinstance(manifest.get('documents',{}),dict):
        raise LoopError('Previous layout inventory is invalid; replacement authority refused')
    for logical,name in manifest.get('paths',{}).items():
        if not isinstance(logical,str):
            raise LoopError('Previous mapping identity is invalid; replacement authority refused')
        validate_relative(name);_old_validate_mapping(logical,name)
    if len(set(manifest.get('paths',{}).values()))!=len(manifest.get('paths',{})):
        raise LoopError('Previous mappings share a document; replacement authority refused')
    for name,entry in manifest.get('documents',{}).items():
        validate_relative(name)
        if not isinstance(entry,dict) or set(entry)!={'kind','id','role','task_id','project_id'}:
            raise LoopError('Previous document descriptor is invalid; replacement authority refused')
        _old_validate_metadata({'version':2,'knowledge_home':str(home),'record':{'id':entry['id']},**entry})


def _previous_execution_identity(name, meta, home, descriptor=_NO_DESCRIPTOR):
    """The converter accepts old envelopes only inside their actual old scope."""
    if (not isinstance(meta,dict) or type(meta.get('version')) is not int or meta['version'] not in (1,2)
            or meta.get('knowledge_home')!=str(home.resolve()) or not isinstance(meta.get('record'),dict)):
        raise LoopError('Previous execution identity is unavailable; replacement authority refused')
    fields={'version','kind','id','knowledge_home','record'}
    if meta['version']==2:
        fields.update(('role','project_id','task_id'))
    if set(meta)!=fields:
        raise LoopError('Previous execution metadata fields differ from the supported envelope; replacement authority refused')
    if meta['version']==2:
        try:
            _old_validate_document_path(name,meta)
        except LoopError as exc:
            raise LoopError('Previous envelope was not authoritative; replacement authority refused: '+str(exc)) from exc
    kind=meta.get('kind');identifier=safe_id(meta.get('id'));record=meta['record'];parts=name.split('/')
    if kind not in ('task','human-request') or record.get('id')!=identifier or len(parts) not in (5,7):
        raise LoopError('Previous execution identity is unavailable; replacement authority refused')
    task_id=identifier if kind=='task' else safe_id(record.get('task_id'))
    if meta['version']==2:
        project=safe_id(meta.get('project_id'))
        task_name=parts[3].endswith('--'+task_id) and len(parts[3])>len(task_id)+2
        project_name=parts[1].endswith('--'+project) and len(parts[1])>len(project)+2
        current_name=parts[-1].startswith('현재-') and parts[-1].endswith('--'+task_id+'.md')
        request_name=parts[-1].endswith('--'+identifier+'.md') and len(parts[-1])>len(identifier)+5
        role='current' if kind=='task' else 'human-request'
        valid=meta.get('task_id')==task_id and meta.get('role')==role
    else:
        project=safe_id(parts[1]);project_name=True;task_name=parts[3]==task_id
        current_name=parts[-1]=='current.md';request_name=parts[-1]==identifier+'.md';valid=True
    valid=valid and parts[0]=='projects' and parts[2]=='tasks' and project_name and task_name
    valid=valid and ((kind=='task' and len(parts)==5 and current_name)
                     or (kind=='human-request' and len(parts)==7 and parts[4:6]==['records','human-request'] and request_name))
    if not valid:
        raise LoopError('Previous document physical scope differs from its identity; replacement authority refused: '+name)
    expected={'kind':kind,'id':identifier,'role':'current' if kind=='task' else 'human-request',
              'project_id':project,'task_id':task_id}
    if ((meta['version']==2 or descriptor is not _NO_DESCRIPTOR) and descriptor!=expected):
        raise LoopError('Previous owned document descriptor differs from its envelope; replacement authority refused: '+name)
    return kind,identifier,project,task_id,record


def _old_metadata(vault, name):
    raw,_=_read_regular(vault/name,MAX_NOTE);lines=raw.decode('utf-8').split('\n',3)
    try:
        if len(lines)!=4 or lines[0]!='---' or lines[2]!='---' or not lines[1].startswith('loop_work: '):
            raise ValueError()
        return json.loads(lines[1][len('loop_work: '):])
    except (ValueError,TypeError,UnicodeError,RecursionError) as exc:
        raise LoopError('Previous execution envelope is unavailable; replacement authority refused: '+name) from exc


def _verify_current_ownership(snapshot, manifest, vault, home):
    records={(kind,key):json.loads(body) for kind,key,body in snapshot['records']}
    tasks={key:value for (kind,key),value in records.items() if kind=='task'};owned=set()
    for name in manifest['files']:
        descriptor=manifest.get('documents',{}).get(name,{})
        filename=name.rsplit('/',1)[-1]
        if not (descriptor.get('kind')=='task' and descriptor.get('role')=='current' or filename=='current.md' or filename.startswith('현재-') and filename.endswith('.md')):
            continue
        kind,key,project,task_id,record=_previous_execution_identity(name,_old_metadata(vault,name),home,
            manifest.get('documents',{}).get(name,_NO_DESCRIPTOR))
        task=tasks.get(key)
        if (kind!='task' or task is None or task_id!=key or record.get('session_id')!=task.get('session_id')
                or project not in (task.get('project_ids') or ['unassigned'])
                or project not in (record.get('project_ids') or ['unassigned']) or record!=task):
            raise LoopError('Previous task current identity is unavailable; replacement authority refused: '+name)
        owned.add((key,project))
    for key,task in tasks.items():
        if any((key,project) not in owned for project in task.get('project_ids') or ['unassigned']):
            raise LoopError('Previous task current ownership is missing; replacement authority refused: '+key)


def _source_inventory(home, vault):
    manifest_raw, manifest_pin = _read_regular(home / 'vault-owned.json',MAX_MANIFEST)
    try:
        manifest = json.loads(manifest_raw)
    except (ValueError,UnicodeError,RecursionError) as exc:
        raise LoopError('Vault reorganization requires a valid ownership manifest') from exc
    try:
        _validate_previous_manifest(manifest,home,vault)
    except LoopError as exc:
        raise LoopError('Previous manifest was not authoritative; replacement authority refused: '+str(exc)) from exc
    if manifest.get('reservations'):
        raise LoopError('Reserved or conflicting vault paths must be resolved without creating replacement authority')
    files = manifest['files']
    if len(files) > MAX_FILES:
        raise LoopError('Vault reorganization exceeds the bounded file limit')
    paths=manifest.get('paths',{})
    if not isinstance(paths,dict):
        raise LoopError('Invalid previous path inventory')
    for logical,name in paths.items():
        validate_relative(name)
        if not isinstance(logical,str) or (not logical.startswith('project:') and name not in files):
            raise LoopError('Unowned or absent mapped document cannot acquire replacement authority')
    documents=manifest.get('documents',{})
    if not isinstance(documents,dict):
        raise LoopError('Invalid previous document inventory')
    for name,entry in documents.items():
        validate_relative(name)
        if name not in files:
            raise LoopError('Unowned or absent described document cannot acquire replacement authority: '+name)
    _scan_previous_execution(vault,set(files))
    source = {}; total = 0
    for name, pin in sorted(files.items()):
        validate_relative(name)
        raw, actual = _read_regular(vault/name)
        total += len(raw)
        if actual != pin:
            raise LoopError('Edited or unowned vault document preserved; reorganization refused: ' + name)
        source[name] = {'pin':actual,'sha256':_sha(raw),'size':len(raw),'kind':'generated'}
    wiki = manifest.get('wiki_documents',{})
    if not isinstance(wiki,dict):
        raise LoopError('Invalid previous wiki inventory')
    for identity, entry in sorted(wiki.items()):
        if not isinstance(entry,dict) or entry.get('owned') is not True:
            raise LoopError('Unowned or missing wiki cannot acquire authority through reorganization')
        name = validate_relative(entry.get('path'))
        raw, pin = _read_regular(vault/name)
        from .wiki import parse
        parse(raw.decode('utf-8'),entry)
        total += len(raw)
        source[name] = {'pin':pin,'sha256':_sha(raw),'size':len(raw),'kind':'wiki','identity':identity}
    if total > MAX_BYTES:
        raise LoopError('Vault reorganization exceeds the bounded byte limit')
    return manifest_raw, manifest_pin, manifest, source


def _verify_request_ownership(snapshot, manifest, vault, home):
    """Every regenerated decision must have all of its prior owned replicas."""
    records={(kind,key):json.loads(body) for kind,key,body in snapshot['records']}
    requests={key:value for (kind,key),value in records.items() if kind=='human-request'}
    if not requests:
        return
    owned=set()
    for name in manifest['files']:
        descriptor=manifest.get('documents',{}).get(name,{})
        if descriptor.get('kind')!='human-request' and '/records/human-request/' not in name:
            continue
        kind,key,project,task_id,record=_previous_execution_identity(name,_old_metadata(vault,name),home,
            manifest.get('documents',{}).get(name,_NO_DESCRIPTOR))
        request=requests.get(key);task=records.get(('task',task_id))
        if (kind!='human-request' or request is None or task is None or request.get('task_id')!=task_id
                or record.get('session_id')!=request.get('session_id')
                or project not in (task.get('project_ids') or ['unassigned']) or record!=request):
            raise LoopError('Previous user request identity is unavailable; replacement authority refused: '+name)
        owned.add((key,project))
    for key,request in requests.items():
        task=records.get(('task',request.get('task_id')))
        if not task or any((key,project) not in owned for project in task.get('project_ids') or ['unassigned']):
            raise LoopError('Previous user request ownership is missing; replacement authority refused: '+key)


def _verify_previous_action_evidence(snapshot, manifest, vault, home):
    """Retain existing action read bounds and do not merge divergent prose."""
    groups={}
    for name in manifest['files']:
        descriptor=manifest.get('documents',{}).get(name,{})
        filename=name.rsplit('/',1)[-1]
        current=(descriptor.get('kind')=='task' and descriptor.get('role')=='current'
                 or filename=='current.md' or filename.startswith('현재-') and filename.endswith('.md'))
        request=descriptor.get('kind')=='human-request' or '/records/human-request/' in name
        if not current and not request:
            continue
        raw,_=_read_regular(vault/name,MAX_NOTE)
        meta=_old_metadata(vault,name)
        kind,key,project,task_id,record=_previous_execution_identity(name,meta,home,
            manifest.get('documents',{}).get(name,_NO_DESCRIPTOR))
        groups.setdefault((kind,key),[]).append((len(raw),raw.decode('utf-8').split('\n',3)[3],task_id))
    def bounded(documents):
        if len(documents)>MAX_DOCUMENTS or sum(item[0] for item in documents)>MAX_TOTAL:
            raise LoopError('Previous action evidence exceeded its existing read limits; replacement authority refused')
    for (kind,key),documents in groups.items():
        if len({item[1] for item in documents})>1:
            raise LoopError('Previous document replica bodies differ; replacement authority refused')
        if kind=='task':
            bounded(documents)
        else:
            bounded(groups.get(('task',documents[0][2]),[])+documents)


def plan(home, vault, output):
    """Write a reviewable payload outside user data; leave source files untouched."""
    home = Path(home).expanduser().absolute(); vault = Path(vault).expanduser().absolute()
    output = Path(output).expanduser().absolute()
    if not home.is_dir() or not vault.is_dir():
        raise LoopError('Knowledge and vault must already exist for read-only planning')
    if output == home or output == vault or output.is_relative_to(home) or output.is_relative_to(vault):
        raise LoopError('Write the reorganization plan outside knowledge and vault directories')
    if os.path.lexists(output) or os.path.lexists(output.with_suffix(output.suffix+'.payload')):
        raise LoopError('Reorganization plan or payload already exists; preserve it and choose a new output')
    original, manifest_pin, old, source = _source_inventory(home,vault)
    snapshot = _snapshot(home)
    _verify_current_ownership(snapshot,old,vault,home)
    _verify_request_ownership(snapshot,old,vault,home)
    _verify_previous_action_evidence(snapshot,old,vault,home)
    output.parent.mkdir(parents=True,exist_ok=True)
    payload = output.with_suffix(output.suffix+'.payload')
    payload.mkdir(mode=0o700)
    with tempfile.TemporaryDirectory(prefix='loop-vault-stage-',dir=output.parent) as temporary:
        stage = Path(temporary); stage_home = stage/'knowledge'; stage_home.mkdir(); stage_vault = stage/'vault'
        knowledge = _ReadOnlyKnowledge(snapshot,stage_home,home)
        for (kind,key),record in sorted(knowledge.records.items()):
            if kind in KINDS:
                result = VaultExporter(knowledge,stage_vault).export(kind,key)
                if result.get('errors'):
                    raise LoopError('Staged reorganization failed: ' + '; '.join(result['errors'][:3]))
        fresh = read_export_json(stage_home/'vault-owned.json')
        if fresh is None:
            raise LoopError('No exportable records exist for reorganization')
        fresh['vault'] = str(vault)
        files = {}
        for name in sorted(fresh['files']):
            raw,_ = _read_regular(stage_vault/name)
            text = raw.decode('utf-8'); head,sep,body = text.partition('\n---\n')
            meta = json.loads(head.split('\n',1)[1][len('loop_work: '):])
            meta['knowledge_home'] = str(home.resolve())
            body = body.replace(stage_home.as_uri()+'/',home.as_uri()+'/')
            text = '---\nloop_work: ' + json.dumps(meta,ensure_ascii=False,separators=(',',':')) + '\n---\n' + body
            target = payload/name; _backup_bytes(payload,name,text.encode('utf-8'))
            files[name] = {'sha256':_sha(target.read_bytes()),'pin':_export_pin(target),'kind':'generated'}
            fresh['files'][name] = files[name]['pin']
        rebased = []
        for identity,entry in sorted(fresh.get('wiki_documents',{}).items()):
            name = entry['path']; previous = old.get('wiki_documents',{}).get(identity)
            if previous:
                raw,_ = _read_regular(vault/previous['path'])
                text = raw.decode('utf-8')
                # Only the exact system-generated source link is rebased. Other
                # human prose is retained; the exact original is archived outside the vault.
                if entry['kind'] == 'task':
                    old_source = old.get('paths',{}).get('task:'+entry['project_id']+':'+entry['id'])
                    if old_source is None:
                        old_source = 'projects/'+entry['project_id']+'/tasks/'+entry['id']+'/current.md'
                    new_source = fresh['paths']['task:'+entry['project_id']+':'+entry['id']]
                else:
                    project_base = old.get('paths',{}).get('project:'+entry['project_id'])
                    old_source = project_base+'/프로젝트색인.md' if project_base else None
                    new_source = fresh['paths']['project:'+entry['project_id']]+'/목록.md'
                if old_source:
                    before = '[실행 원본 기록](<' + quote(os.path.relpath(vault/old_source,(vault/previous['path']).parent).replace(os.sep,'/'),safe='/') + '>)'
                    after = '[실행 원본 기록](<' + quote(os.path.relpath(vault/new_source,(vault/name).parent).replace(os.sep,'/'),safe='/') + '>)'
                    if before in text:
                        text = text.replace(before,after)
                        rebased.append(identity)
            else:
                raw,_ = _read_regular(stage_vault/name); text = raw.decode('utf-8')
            target = payload/name; _backup_bytes(payload,name,text.encode('utf-8'))
            files[name] = {'sha256':_sha(target.read_bytes()),'pin':_export_pin(target),'kind':'wiki'}
        if len(files) > MAX_FILES or sum((payload/name).stat().st_size for name in files) > MAX_BYTES:
            raise LoopError('Reorganization payload exceeds the bounded file or byte limit')
        for name in files:
            if os.path.lexists(vault/name):
                raise LoopError('Existing destination preserved; reorganization cannot bypass it: '+name)
        fresh['migration'] = {'protocol':PROTOCOL,'source_manifest_sha256':_sha(original)}
        document = {'version':1,'protocol':PROTOCOL,'knowledge_home':str(home),'vault':str(vault),
                    'source_manifest_sha256':_sha(original),'source_manifest_pin':manifest_pin,
                    'source_records_sha256':digest(snapshot),'source_files':source,'target_files':files,
                    'target_manifest':fresh,'payload':str(payload),'rebased_generated_wiki_links':rebased,
                    'archived_original_files':len(source),'preserved_database':True,
                    'note':'Original document bytes and manifest are backed up outside the vault. After publishing current documents, pinned old managed files move to that backup. Unowned notes, settings, database and audit history remain unchanged.'}
        _write(output,json.dumps(document,ensure_ascii=False,indent=2,sort_keys=True)+'\n',None)
    raw,_ = _read_regular(output,MAX_BYTES)
    return {'status':'planned','plan':str(output),'sha256':_sha(raw),'source_files':len(source),'target_files':len(files),'rebased_generated_wiki_links':len(rebased),'source_not_written':True}


def _restore_captured(captured, destination):
    """Restore only to an unoccupied name; a racing human file always wins."""
    try:
        os.link(captured,destination,follow_symlinks=False)
    except FileExistsError:
        return False
    else:
        os.unlink(captured)
        return True


def _backup_bytes(root, name, content, executable=False):
    """Create backup bytes exclusively through no-follow directory descriptors."""
    validate_relative(name);flags=os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW
    with ExitStack() as opened:
        fd=os.open(root.anchor,flags);opened.callback(os.close,fd)
        for part in root.parts[1:]:
            fd=os.open(part,flags,dir_fd=fd);opened.callback(os.close,fd)
        parts=name.split('/')
        for part in parts[:-1]:
            try:
                os.mkdir(part,0o700,dir_fd=fd)
            except FileExistsError:
                pass
            fd=os.open(part,flags,dir_fd=fd);opened.callback(os.close,fd)
        output=os.open(parts[-1],os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o700 if executable else 0o600,dir_fd=fd)
        with os.fdopen(output,'wb') as stream:
            stream.write(content);stream.flush();os.fsync(stream.fileno())


def _move_exclusive(source, destination):
    """Atomic no-clobber archive; unsupported platforms fail closed."""
    libc=ctypes.CDLL(None,use_errno=True)
    if sys.platform=='darwin':
        function=getattr(libc,'renamex_np',None)
        if function is None:
            raise LoopError('Atomic exclusive rename is unavailable on this macOS')
        function.argtypes=(ctypes.c_char_p,ctypes.c_char_p,ctypes.c_uint);function.restype=ctypes.c_int
        result=function(os.fsencode(source),os.fsencode(destination),4)  # RENAME_EXCL
    elif sys.platform.startswith('linux'):
        function=getattr(libc,'renameat2',None)
        if function is None:
            raise LoopError('Atomic exclusive rename is unavailable on this Linux')
        function.argtypes=(ctypes.c_int,ctypes.c_char_p,ctypes.c_int,ctypes.c_char_p,ctypes.c_uint);function.restype=ctypes.c_int
        result=function(-100,os.fsencode(source),-100,os.fsencode(destination),1)  # AT_FDCWD, RENAME_NOREPLACE
    else:
        raise LoopError('Atomic exclusive archive supports macOS and Linux only')
    if result:
        code=ctypes.get_errno()
        raise OSError(code,os.strerror(code),str(destination))


def apply(plan_path, expected_sha256):
    path = Path(plan_path).expanduser().absolute()
    raw,_ = _read_regular(path,MAX_BYTES)
    if not isinstance(expected_sha256,str) or not re.fullmatch('[0-9a-f]{64}',expected_sha256) or _sha(raw) != expected_sha256:
        raise LoopError('Reorganization plan hash changed; apply refused')
    try:
        value = json.loads(raw)
    except (ValueError,UnicodeError,RecursionError) as exc:
        raise LoopError('Invalid reorganization plan') from exc
    if value.get('version') != 1 or value.get('protocol') != PROTOCOL:
        raise LoopError('Unsupported reorganization plan')
    home=Path(value['knowledge_home']); vault=Path(value['vault']); payload=Path(value['payload'])
    backup=path.with_suffix(path.suffix+'.backup')
    if any(path.is_relative_to(root) or payload.is_relative_to(root) or backup.is_relative_to(root) for root in (home,vault)):
        raise LoopError('Plan, payload and backup must remain outside knowledge and vault directories')
    if os.path.lexists(backup):
        raise LoopError('Reorganization backup already exists; inspect the previous attempt before retrying')
    with export_locked(home/'vault-export'):
        original,pin,old,source = _source_inventory(home,vault)
        if (_sha(original) != value['source_manifest_sha256'] or pin != value['source_manifest_pin']
                or source != value['source_files'] or digest(_snapshot(home)) != value['source_records_sha256']):
            raise LoopError('Source changed after reorganization planning; create a fresh plan')
        targets=value['target_files']
        if not isinstance(targets,dict) or len(targets)>MAX_FILES or value['target_manifest'].get('layout_version') != 3:
            raise LoopError('Invalid reorganization target inventory')
        verified={}; verified_bytes=0
        for name, entry in targets.items():
            validate_relative(name)
            content,actual = _read_regular(payload/name)
            verified_bytes += len(content)
            if verified_bytes > MAX_BYTES:
                raise LoopError('Reorganization payload exceeds the bounded byte limit')
            if _sha(content) != entry['sha256'] or actual != entry['pin']:
                raise LoopError('Reorganization payload changed; apply refused: '+name)
            if os.path.lexists(vault/name):
                raise LoopError('Existing destination preserved; reorganization refused: '+name)
            verified[name]=content
        if os.stat(vault).st_dev != os.stat(path.parent).st_dev:
            raise LoopError('Choose a plan/backup directory on the same filesystem as the vault')
        os.mkdir(backup,0o700)  # Exclusive ownership: a racing directory is never adopted.
        _backup_bytes(backup,'vault-owned.json',original)
        for name in source:
            content,_=_read_regular(vault/name)
            executable=bool(os.stat(vault/name,follow_symlinks=False).st_mode & 0o111)
            _backup_bytes(backup,'original-files/'+name,content,executable)
        receipt={'version':1,'protocol':PROTOCOL,'plan_sha256':expected_sha256,'backup':str(backup),'status':'publishing','published':[]}
        receipt_pin=None
        def publish_receipt():
            nonlocal receipt_pin
            text=json.dumps(receipt,ensure_ascii=False,sort_keys=True,indent=2)+'\n'
            receipt_pin=_write(backup/'receipt.json',text,receipt_pin)
        publish_receipt()
        try:
            for name,entry in sorted(targets.items()):
                actual=_write(vault/name,verified[name].decode('utf-8'),None)
                if actual != entry['pin'] or _export_pin(vault/name) != entry['pin']:
                    raise LoopError('Published document changed; ownership cutover refused: '+name)
                receipt['published'].append(name)
            # Do not let concurrent edits or new task state be hidden by cutover.
            after,pin_after,_,source_after = _source_inventory(home,vault)
            if after != original or pin_after != pin or source_after != source or digest(_snapshot(home)) != value['source_records_sha256']:
                raise LoopError('Source changed during reorganization; old ownership inventory preserved')
            receipt['manifest_committed']=False
            receipt['archived']=[]
            publish_receipt()
            if os.stat(vault).st_dev != os.stat(backup).st_dev:
                raise LoopError('Archiving original files requires a backup on the same filesystem')
            for name,entry in sorted(source.items()):
                # Renaming captures the complete source inode. A racing human
                # edit is retained separately and never silently overwritten.
                captured=backup/'captured-originals'/name; _directory(captured.parent)
                if os.path.lexists(captured):
                    raise LoopError('Unexpected archive destination preserved: '+name)
                _move_exclusive(vault/name,captured)
                moved,actual=_read_regular(captured)
                if actual != entry['pin'] or _sha(moved) != entry['sha256']:
                    _restore_captured(captured,vault/name)
                    raise LoopError('Original changed during archive; captured content preserved: '+name)
                saved=backup/'original-files'/name
                saved_raw,_=_read_regular(saved)
                if _sha(saved_raw) != entry['sha256']:
                    raise LoopError('Backup changed during archive; both copies preserved: '+name)
                # Keep the independently copied snapshot and captured inode.
                # Neither backup is replaced after publication.
                receipt['archived'].append(name)
                publish_receipt()
            # The new manifest grants no authority until every captured original
            # and every actual published document still matches the reviewed pin.
            for name,entry in source.items():
                saved=backup/'original-files'/name
                archived,actual=_read_regular(saved)
                captured=backup/'captured-originals'/name
                captured_raw,captured_pin=_read_regular(captured)
                if (actual != entry['pin'] or _sha(archived) != entry['sha256'] or captured_pin != entry['pin']
                        or _sha(captured_raw) != entry['sha256'] or os.path.lexists(vault/name)):
                    raise LoopError('Archived original changed or its old path was recreated; ownership cutover refused: '+name)
            for name,entry in targets.items():
                if _export_pin(vault/name) != entry['pin']:
                    raise LoopError('Published document changed before ownership cutover: '+name)
            if digest(_snapshot(home)) != value['source_records_sha256']:
                raise LoopError('Source records changed during archive; ownership cutover refused')
            _scan_previous_execution(vault,set())
            new=json.dumps(value['target_manifest'],ensure_ascii=False,indent=2,sort_keys=True)+'\n'
            _write(home/'vault-owned.json',new,pin)
            receipt['manifest_committed']=True
            publish_receipt()
            # Only directories emptied by our own managed-file moves are removed.
            parents=sorted({parent for name in source for parent in (vault/name).parents if parent != vault and parent.is_relative_to(vault)},key=lambda item:len(item.parts),reverse=True)
            for parent in parents:
                try:
                    parent.rmdir()
                except OSError:
                    pass
            receipt['status']='applied'; receipt['source_database_unchanged']=True
            receipt['original_files_preserved']=True
            publish_receipt()
            return {'status':'applied','backup':str(backup),'published_files':len(targets),'layout_version':3,'database_unchanged':True,'original_files_preserved':True,'archived_original_files':len(source)}
        except Exception as exc:
            receipt['status']='failed';receipt['error']=str(exc)
            publish_receipt()
            raise
