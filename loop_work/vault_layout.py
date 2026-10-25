"""One readable Korean vault layout; paths never grant record authority."""
from __future__ import annotations
import hashlib
import re
import unicodedata
from pathlib import PurePosixPath
from .storage import LoopError


ROLE_FOLDERS = {'delegation':'위임', 'team':'협업', 'human-request':'사용자 검토',
                'feedback':'피드백', 'retirement':'종료'}
HISTORY_FOLDERS = {'interim':'중간', 'final':'완료'}


def safe_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', value):
        raise LoopError('Unsafe vault record identifier')
    return value


def id_suffix(identifier):
    return hashlib.sha256(safe_id(identifier).encode('utf-8')).hexdigest()[:8]


def display_title(record):
    """A short display excerpt, never a replacement for the source statement."""
    value = (record.get('title') or record.get('name') or record.get('summary')
             or (record.get('request') or {}).get('instruction') or '문서')
    value = unicodedata.normalize('NFC', ' '.join(str(value).split())).strip()
    if len(value) <= 48:
        return value or '문서'
    excerpt = value[:47]
    boundary = excerpt.rfind(' ')
    if boundary >= 24:
        excerpt = excerpt[:boundary]
    return excerpt.rstrip(' .') + '…'


def slug(title, identifier):
    title = display_title({'title':title})
    title = ''.join(' ' if unicodedata.category(c).startswith('C') or c in '/\\:*?"<>|[]#^' else c for c in title)
    title = ' '.join(title.split()).strip(' .') or '문서'
    return title + '--' + id_suffix(identifier)


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
    if not isinstance(value, dict) or set(value) != fields or type(value.get('version')) is not int or value.get('version') != 3:
        raise LoopError('Invalid vault document metadata')
    safe_id(value['kind']); safe_id(value['id'])
    if value['role'] in ('current','interim','final') and (value['kind'] != 'task' or value['task_id'] != value['id']):
        raise LoopError('Vault task role identity mismatch')
    if value['role'] in ('topic',*ROLE_FOLDERS) and value['kind'] != value['role']:
        raise LoopError('Vault request role identity mismatch')
    for key in ('project_id','task_id'):
        if value[key] is not None:
            safe_id(value[key])
    if value['role'] not in ('current','interim','final','topic',*ROLE_FOLDERS,'index'):
        raise LoopError('Invalid vault document role')
    if not isinstance(value['knowledge_home'], str) or not isinstance(value['record'], dict) or value['record'].get('id') != value['id']:
        raise LoopError('Invalid vault document identity')
    return value


def _named(component, identifier):
    suffix = '--' + id_suffix(identifier)
    return len(component) > len(suffix) and component.endswith(suffix)


def _task_prefix(parts, project, task):
    return (len(parts) >= 5 and parts[0] == '프로젝트' and _named(parts[1], project)
            and parts[2] == '작업' and _named(parts[3], task))


def _topic_directory(parts, metadata):
    project = metadata['project_id']
    record = metadata['record']
    scope = record.get('scope')
    if scope is not None and scope not in ('global','project','checkout','session','task'):
        return False
    if 'scope' in record:
        if project != (record.get('project_id') if scope != 'global' else None) or metadata['task_id'] != record.get('task_id'):
            return False
    if project is None:
        return len(parts) == 2 and parts[0] == '공통 지식' and scope in (None,'global')
    return len(parts) == 4 and parts[0] == '프로젝트' and _named(parts[1], project) and parts[2] == '지식'


def validate_document_path(path, metadata):
    validate_relative(path); validate_metadata(metadata)
    parts = path.split('/'); role = metadata['role']
    project, task = metadata['project_id'], metadata['task_id']
    if role in ('current','interim','final',*ROLE_FOLDERS):
        if project is None or task is None or not _task_prefix(parts, project, task):
            raise LoopError('Vault document is outside its declared task')
        if role == 'current':
            valid = len(parts) == 5 and parts[-1] == '진행 현황.md'
        elif role in HISTORY_FOLDERS:
            valid = (len(parts) == 7 and parts[4:6] == ['기록',HISTORY_FOLDERS[role]]
                     and re.fullmatch(r'(?:[0-9]{4}-[0-9]{2}-[0-9]{2}|날짜미상)-(?:중간|완료|이력-[0-9]{3,})-[0-9a-f]{20}\.md',parts[-1]) is not None)
        else:
            valid = len(parts) == 7 and parts[4:6] == ['기록',ROLE_FOLDERS[role]] and _named(parts[-1][:-3], metadata['id'])
        if not valid:
            raise LoopError('Invalid vault task document path')
    elif role == 'topic':
        if not _topic_directory(parts, metadata) or not _named(parts[-1][:-3], metadata['id']):
            raise LoopError('Vault topic scope directory mismatch')
    elif role == 'index':
        if not (metadata['kind'] == 'project' and metadata['id'] == project and task is None
                and len(parts) == 3 and parts[0] == '프로젝트' and _named(parts[1],project) and parts[-1] == '목록.md'):
            raise LoopError('Invalid vault index path')
    if not path.endswith('.md'):
        raise LoopError('Vault document must be Markdown')
    return path


def validate_mapping(logical, path):
    """Validate one current layout against immutable logical identities."""
    validate_relative(path)
    if not isinstance(logical, str):
        raise LoopError('Invalid vault logical document key')
    key = logical.split(':'); category = key[0]; parts = path.split('/')
    if category == 'project' and len(key) == 2:
        project = safe_id(key[1]); valid = len(parts) == 2 and parts[0] == '프로젝트' and _named(parts[1],project)
    elif category == 'task' and len(key) == 3:
        project, task = map(safe_id,key[1:]); valid = _task_prefix(parts,project,task) and len(parts) == 5 and parts[-1] == '진행 현황.md'
    elif category in ('snapshot','history') and len(key) == (4 if category == 'snapshot' else 5):
        project, task = map(safe_id,key[1:3]); token = key[-1]
        if category == 'snapshot':
            valid_token = re.fullmatch('[0-9a-f]{64}',token) is not None
            filename = token[:20] + '.md'
        else:
            valid_token = re.fullmatch('[0-9a-f]{20}',token) is not None and re.fullmatch('[1-9][0-9]*',key[3]) is not None
            filename = '-이력-' + key[3].zfill(3) + '-' + token + '.md'
        valid = valid_token and _task_prefix(parts,project,task) and len(parts) == 7 and parts[4] == '기록' and parts[5] in HISTORY_FOLDERS.values() and parts[-1].endswith(filename) and re.fullmatch(r'(?:[0-9]{4}-[0-9]{2}-[0-9]{2}|날짜미상)-(?:중간|완료|이력-[0-9]{3,})-[0-9a-f]{20}\.md',parts[-1]) is not None
    elif category == 'topic' and len(key) == 2:
        identifier = safe_id(key[1]); valid = (_named(parts[-1][:-3],identifier) and path.endswith('.md')
            and ((len(parts) == 2 and parts[0] == '공통 지식') or (len(parts) == 4 and parts[0] == '프로젝트' and parts[2] == '지식' and re.search(r'--[0-9a-f]{8}$',parts[1]) is not None)))
    elif category in ROLE_FOLDERS and len(key) == 3:
        project, identifier = map(safe_id,key[1:]); valid = (len(parts) == 7 and parts[0] == '프로젝트' and _named(parts[1],project)
            and parts[2] == '작업' and re.search(r'--[0-9a-f]{8}$',parts[3]) is not None and parts[4:6] == ['기록',ROLE_FOLDERS[category]]
            and path.endswith('.md') and _named(parts[-1][:-3],identifier))
    else:
        valid = False
    if not valid:
        raise LoopError('Vault frozen path does not match its logical identity')
    return path
