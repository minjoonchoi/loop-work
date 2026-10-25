"""Vault-backed board using the human desk's loopback capability boundary."""
from __future__ import annotations
import json
import secrets
import threading
from urllib.parse import parse_qs, unquote, urlsplit

from .board import Board
from .human_ui import MAX_BODY, make_server as human_server
from .storage import LoopError

MAX_WIKI_BODY = 1024 * 1024


def make_server(knowledge, port=0, session_id=None, task_id=None, *, vault_home=None, desk=None, project_id=None, management=None):
    board = desk if desk is not None else Board(knowledge,vault_home)
    def selected(row):
        if ((session_id and row['record'].get('session_id') != session_id)
                or (task_id and (row['record'].get('task_id') if row['kind']=='human-request' else row['id']) != task_id)):
            raise LoopError('Document outside board scope')
        return row
    def dispatch_api(handler):
        parts = urlsplit(handler.path); query = parse_qs(parts.query)
        if any(key not in ('status','include_closed','session_id','task_id','project_id','path','query','sort') for key in query) or any(len(values)!=1 for values in query.values()):
            raise LoopError('Invalid board query fields')
        session = query.get('session_id',[session_id])[0]; task = query.get('task_id',[task_id])[0]
        project = query.get('project_id',[project_id])[0] or None
        if project_id is not None and project != project_id:
            raise LoopError('고정된 프로젝트 범위를 넓힐 수 없습니다')
        scoped = {'project_id':project} if project is not None else {}
        if (session_id and session!=session_id) or (task_id and task!=task_id):
            raise LoopError('Board scope cannot be expanded')
        if parts.path == '/api/_service':
            if management is None or parts.query:
                raise LoopError('This board is not a managed instance')
            if handler.command == 'GET':
                handler.send_value(200, management); return
            length = handler.headers.get('Content-Length','')
            if handler.headers.get('Transfer-Encoding') or not length.isdecimal() or int(length)>1024 or handler.headers.get_content_type()!='application/json':
                raise LoopError('Exact managed shutdown JSON required')
            try:
                payload=json.loads(handler.rfile.read(int(length)))
            except (ValueError,UnicodeError):
                raise LoopError('Invalid managed shutdown request')
            if not isinstance(payload,dict) or set(payload)!={'instance_nonce'} or not isinstance(payload['instance_nonce'],str) or not secrets.compare_digest(payload['instance_nonce'],management['instance_nonce']):
                raise LoopError('Managed instance identity mismatch')
            handler.send_value(200, {'stopping':True, **management})
            threading.Thread(target=handler.server.shutdown,daemon=True).start(); return
        segments=parts.path.split('/')
        wiki = len(segments)==5 and segments[1]=='api' and segments[2] in ('projects','tasks') and segments[4]=='wiki'
        if wiki:
            wiki_kind='project' if segments[2]=='projects' else 'task'; identifier=unquote(segments[3])
            if wiki_kind=='task':
                selected(board.show(identifier,'task',**scoped))
            elif session_id is not None or task_id is not None:
                raise LoopError('작업·세션 범위의 보드에서는 프로젝트 위키를 열 수 없습니다')
            if wiki_kind=='project' and project is not None and identifier!=project:
                raise LoopError('보드 범위 밖의 프로젝트 위키입니다')
            if handler.command=='GET':
                handler.send_value(200,board.wiki(wiki_kind,identifier,**scoped)); return
        if handler.command=='GET':
            if parts.path == '/api/projects':
                value=board.projects(query.get('query',[''])[0],query.get('sort',['name'])[0],session,task,**scoped)
            elif parts.path in ('/api/board','/api/requests'):
                value = board.list(session,task,query.get('include_closed',['1' if query.get('status',['all'])[0]=='all' else '0'])[0]=='1',**scoped)
            elif parts.path=='/api/document' and 'path' in query:
                value = selected(board.document(query['path'][0],**scoped))
            elif parts.path.startswith('/api/tasks/') and '/' not in parts.path[len('/api/tasks/'):]:
                value = selected(board.show(unquote(parts.path[len('/api/tasks/'):]),'task',**scoped))
            elif parts.path.startswith('/api/requests/') and '/' not in parts.path[len('/api/requests/'):]:
                value = selected(board.show(unquote(parts.path[len('/api/requests/'):]),**scoped) )
            else:
                handler.send_value(404,{'error':'Unknown board path'}); return
            handler.send_value(200,value); return
        if handler.headers.get('Transfer-Encoding'):
            raise LoopError('Chunked board requests unsupported')
        length=handler.headers.get('Content-Length','')
        if not length.isdecimal() or int(length)>(MAX_WIKI_BODY if wiki else MAX_BODY):
            handler.send_value(413,{'error':'위키 JSON 본문이 1MiB를 초과했거나 길이가 없습니다' if wiki else 'Board body too large or missing length'}); return
        if handler.headers.get_content_type()!='application/json':
            handler.send_value(415,{'error':'JSON body required'}); return
        try:
            payload=json.loads(handler.rfile.read(int(length)))
        except (ValueError,UnicodeError):
            raise LoopError('Invalid board JSON')
        if wiki:
            if not isinstance(payload,dict) or set(payload)!={'operation_id','expected_revision','title','body_markdown'}:
                raise LoopError('위키 저장에는 operation_id, expected_revision, title, body_markdown만 필요합니다')
            try:
                value=board.save_wiki(wiki_kind,identifier,payload,**scoped)
            except LoopError as exc:
                if getattr(exc,'status_code',None)==409:
                    handler.send_value(409,{'error':str(exc)}); return
                raise
            handler.send_value(200,value); return
        if len(segments)==5 and segments[1:3]==['api','tasks'] and segments[4]=='control':
            key=unquote(segments[3]); selected(board.show(key,'task',**scoped))
            value=board.control(key,payload,**scoped)
            if session_id is not None or task_id is not None or project_id is not None:
                value['vault_status']=board.sync_status(True)
            handler.send_value(200,value); return
        if len(segments)!=5 or segments[1:3]!=['api','requests'] or segments[4] not in ('respond','execute'):
            handler.send_value(404,{'error':'Unknown board operation'}); return
        key,operation=unquote(segments[3]),segments[4]
        selected(board.show(key,**scoped))
        required={'expected_revision','expected_vault_revision'} | ({'response'} if operation=='respond' else set())
        if (not isinstance(payload,dict) or set(payload)!=required or type(payload['expected_revision']) is not int
                or not isinstance(payload['expected_vault_revision'],str)):
            raise LoopError('Exact operation fields with runtime and vault revisions required')
        if operation=='respond':
            value=board.respond(key,payload['response'],payload['expected_revision'],payload['expected_vault_revision'],**scoped)
        else:
            value=board.execute(key,payload['expected_revision'],payload['expected_vault_revision'],**scoped)
        if session_id is not None or task_id is not None or project_id is not None:
            value['vault_status']=board.sync_status(True)
        handler.send_value(200,value)
    def api(handler):
        try:
            return dispatch_api(handler)
        except LoopError as exc:
            # Typed Korean diagnostics must retain their HTTP semantics without
            # relying on English words in the message or changing human_ui.
            if getattr(exc,'status_code',None)==409:
                handler.send_value(409,{'error':str(exc)})
                return
            raise
    return human_server(knowledge,port,session_id,task_id,desk=board,api_handler=api)
