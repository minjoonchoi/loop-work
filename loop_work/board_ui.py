"""Vault-backed board using the human desk's loopback capability boundary."""
from __future__ import annotations
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, unquote, urlsplit
import webbrowser

from .board import Board
from .human_ui import MAX_BODY, make_server as human_server
from .storage import LoopError

ASSETS = Path(__file__).with_name('board_ui_assets')


def make_server(knowledge, port=0, session_id=None, task_id=None, *, vault_home=None, desk=None):
    board = desk if desk is not None else Board(knowledge,vault_home)
    def selected(row):
        if ((session_id and row['record'].get('session_id') != session_id)
                or (task_id and (row['record'].get('task_id') if row['kind']=='human-request' else row['id']) != task_id)):
            raise LoopError('Document outside board scope')
        return row
    def api(handler):
        parts = urlsplit(handler.path); query = parse_qs(parts.query)
        if any(key not in ('status','include_closed','session_id','task_id','path') for key in query) or any(len(values)!=1 for values in query.values()):
            raise LoopError('Invalid board query fields')
        session = query.get('session_id',[session_id])[0]; task = query.get('task_id',[task_id])[0]
        if (session_id and session!=session_id) or (task_id and task!=task_id):
            raise LoopError('Board scope cannot be expanded')
        if handler.command=='GET':
            if parts.path in ('/api/board','/api/requests'):
                value = board.list(session,task,query.get('include_closed',['1' if query.get('status',['all'])[0]=='all' else '0'])[0]=='1')
            elif parts.path=='/api/document' and 'path' in query:
                value = selected(board.document(query['path'][0]))
            elif parts.path.startswith('/api/tasks/') and '/' not in parts.path[len('/api/tasks/'):]:
                value = selected(board.show(unquote(parts.path[len('/api/tasks/'):]),'task'))
            elif parts.path.startswith('/api/requests/') and '/' not in parts.path[len('/api/requests/'):]:
                value = selected(board.show(unquote(parts.path[len('/api/requests/'):])) )
            else:
                handler.send_value(404,{'error':'Unknown board path'}); return
            handler.send_value(200,value); return
        if handler.headers.get('Transfer-Encoding'):
            raise LoopError('Chunked board requests unsupported')
        length=handler.headers.get('Content-Length','')
        if not length.isdecimal() or int(length)>MAX_BODY:
            handler.send_value(413,{'error':'Board body too large or missing length'}); return
        if handler.headers.get_content_type()!='application/json':
            handler.send_value(415,{'error':'JSON body required'}); return
        try:
            payload=json.loads(handler.rfile.read(int(length)))
        except (ValueError,UnicodeError):
            raise LoopError('Invalid board JSON')
        segments=parts.path.split('/')
        if len(segments)==5 and segments[1:3]==['api','tasks'] and segments[4]=='control':
            key=unquote(segments[3]); selected(board.show(key,'task'))
            value=board.control(key,payload)
            if session_id is not None or task_id is not None:
                value['vault_status']=board.sync_status(True)
            handler.send_value(200,value); return
        if len(segments)!=5 or segments[1:3]!=['api','requests'] or segments[4] not in ('respond','execute'):
            handler.send_value(404,{'error':'Unknown board operation'}); return
        key,operation=unquote(segments[3]),segments[4]
        selected(board.show(key))
        required={'expected_revision','expected_vault_revision'} | ({'response'} if operation=='respond' else set())
        if (not isinstance(payload,dict) or set(payload)!=required or type(payload['expected_revision']) is not int
                or not isinstance(payload['expected_vault_revision'],str)):
            raise LoopError('Exact operation fields with runtime and vault revisions required')
        if operation=='respond':
            value=board.respond(key,payload['response'],payload['expected_revision'],payload['expected_vault_revision'])
        else:
            value=board.execute(key,payload['expected_revision'],payload['expected_vault_revision'])
        if session_id is not None or task_id is not None:
            value['vault_status']=board.sync_status(True)
        handler.send_value(200,value)
    return human_server(knowledge,port,session_id,task_id,desk=board,assets=ASSETS,api_handler=api)


def serve(knowledge, port=0, session_id=None, task_id=None, *, vault_home=None, open_browser=True):
    # Sync once at startup; refreshes read notes and never erase user edits.
    startup=None
    try:
        startup=knowledge.sync_vault()
    except Exception as exc:
        startup={'status':'failed','errors':[str(exc)]}
    if session_id is not None or task_id is not None:
        startup={'status':'withheld','diagnostics':'Global export diagnostics omitted for scoped board'}
    server=make_server(knowledge,port,session_id,task_id,vault_home=vault_home)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    print(json.dumps({'url':server.url,'host':'127.0.0.1','port':server.server_port,'vault_sync':startup}),flush=True)
    if open_browser:
        try:
            opened=webbrowser.open(server.url)
            warning=None if opened else 'Browser did not open; use the printed URL. Server remains available.'
        except Exception:
            warning='Browser could not open; use the printed URL. Server remains available.'
        if warning:
            print(json.dumps({'warning':warning}),flush=True)
    try:
        while thread.is_alive():
            thread.join(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown(); server.server_close(); thread.join(2)
