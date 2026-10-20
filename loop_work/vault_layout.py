"""Deterministic readable names; paths never grant record authority."""
from __future__ import annotations
import re
import unicodedata
from pathlib import PurePosixPath
from .storage import LoopError


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', value):
        raise LoopError('Unsafe vault record identifier')
    return value


def slug(title, identifier):
    identifier = safe_id(identifier)
    title = unicodedata.normalize('NFC', str(title or '문서'))
    title = ''.join(' ' if unicodedata.category(c).startswith('C') or c in '/\\:*?"<>|[]#^' else c for c in title)
    title = ' '.join(title.split()).strip(' .') or '문서'
    # Reserve space for the immutable ID and extensions/prefixes used by callers.
    limit = 180 - len(identifier.encode('utf-8'))
    title = title.encode('utf-8')[:max(12, limit)].decode('utf-8', errors='ignore').rstrip(' .') or '문서'
    return title + '--' + identifier


def validate_relative(value):
    if not isinstance(value, str) or not value or '\\' in value or any(unicodedata.category(c).startswith('C') for c in value):
        raise LoopError('Unsafe vault document path')
    path = PurePosixPath(value)
    if path.is_absolute() or any(x in ('', '.', '..') for x in value.split('/')) or str(path) != value:
        raise LoopError('Unsafe vault document path')
    if any(len(x.encode('utf-8')) > 255 for x in path.parts):
        raise LoopError('Vault document path component is too long')
    return value


def validate_metadata(value):
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


def _topic_directory(parts, metadata):
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


def validate_document_path(path, metadata):
    validate_relative(path); validate_metadata(metadata)
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
            valid = valid and _topic_directory(parts, metadata)
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
        if not _topic_directory(parts, metadata):
            raise LoopError('Vault topic scope directory mismatch')
    if not path.endswith('.md'):
        raise LoopError('Vault document must be Markdown')
    return path


def validate_mapping(logical, path):
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
