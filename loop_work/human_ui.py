"""Authenticated loopback API transport; native Board supplies its renderer."""
from __future__ import annotations

import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from socketserver import TCPServer
from urllib.parse import parse_qs, unquote, urlsplit

from .storage import LoopError

MAX_BODY = 65536


def make_server(knowledge, port=0, session_id=None, task_id=None, *, desk=None, api_handler=None):
    """Create an unstarted IPv4 loopback server; no settings or browser changes."""
    if type(port) is not int or not 0 <= port <= 65535:
        raise LoopError('Human UI port must be between 0 and 65535')
    if desk is None:
        from .human import HumanDesk
        desk = HumanDesk(knowledge)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Capability values and decision text never enter request logs.

        def send_value(self, code, value, content_type='application/json; charset=utf-8'):
            body = json.dumps(value, ensure_ascii=False).encode() if content_type.startswith('application/json') else value
            self.send_response(code)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def guard(self, api=False):
            expected = '127.0.0.1:' + str(self.server.server_port)
            if self.headers.get('Host') != expected:
                self.send_value(403, {'error': 'Invalid Host'}); return False
            origin = self.headers.get('Origin')
            if origin is not None and origin != 'http://' + expected:
                self.send_value(403, {'error': 'Invalid Origin'}); return False
            if api:
                if self.command == 'POST' and origin != 'http://' + expected:
                    self.send_value(403, {'error': 'Origin required'}); return False
                if self.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site'):
                    self.send_value(403, {'error': 'Cross-site request denied'}); return False
                token = self.headers.get('X-Loop-Capability', '')
                if not secrets.compare_digest(token, self.server.capability_token):
                    self.send_value(403, {'error': 'Capability required'}); return False
            return True

        def listing(self, query):
            selected_session = query.get('session_id', [session_id])[0]
            selected_task = query.get('task_id', [task_id])[0]
            if (session_id and selected_session != session_id) or (task_id and selected_task != task_id):
                raise LoopError('UI scope cannot be expanded')
            return desk.list(session_id=selected_session, task_id=selected_task, include_closed=query.get('status', ['pending'])[0] != 'pending')

        def selected(self, identifier):
            if session_id or task_id:
                allowed = desk.list(session_id=session_id, task_id=task_id, include_closed=True)['requests']
                if identifier not in {item['id'] for item in allowed}:
                    raise LoopError('Request outside UI scope')
            return desk.show(identifier)

        def handle_api(self):
            if api_handler is not None:
                return api_handler(self)
            parts = urlsplit(self.path)
            if parts.query and any(name not in ('status', 'session_id', 'task_id') for name in parse_qs(parts.query)):
                raise LoopError('Unknown query field')
            path = parts.path
            if self.command == 'GET':
                if path == '/api/requests':
                    self.send_value(200, self.listing(parse_qs(parts.query))); return
                if path.startswith('/api/requests/') and '/' not in path[len('/api/requests/'):]:
                    self.send_value(200, self.selected(unquote(path[len('/api/requests/'):]))); return
                self.send_value(404, {'error': 'Unknown API path'}); return
            if self.headers.get('Transfer-Encoding'):
                self.send_value(400, {'error': 'Chunked body unsupported'}); return
            length = self.headers.get('Content-Length', '')
            if not length.isdecimal() or int(length) > MAX_BODY:
                self.send_value(413, {'error': 'Request body too large or missing length'}); return
            if self.headers.get_content_type() != 'application/json':
                self.send_value(415, {'error': 'JSON body required'}); return
            try:
                value = json.loads(self.rfile.read(int(length)))
            except (ValueError, UnicodeError):
                self.send_value(400, {'error': 'Invalid JSON'}); return
            if not isinstance(value, dict):
                raise LoopError('JSON object required')
            if path == '/api/requests':
                if set(value) != {'task_id', 'request'} or (task_id and value['task_id'] != task_id):
                    raise LoopError('Create requires scoped task_id and request')
                if session_id:
                    tasks = desk.list(session_id=session_id, task_id=task_id, include_closed=True)['tasks']
                    if value['task_id'] not in {item['id'] for item in tasks}:
                        raise LoopError('Task outside UI scope')
                result = desk.create(value['task_id'], value['request'])
            else:
                segments = path.split('/')
                if len(segments) != 5 or segments[1:3] != ['api', 'requests'] or segments[4] not in ('respond', 'execute'):
                    self.send_value(404, {'error': 'Unknown API path'}); return
                identifier, operation = unquote(segments[3]), segments[4]
                self.selected(identifier)
                required = {'expected_revision', 'response'} if operation == 'respond' else {'expected_revision'}
                if set(value) != required or type(value['expected_revision']) is not int:
                    raise LoopError('Exact operation fields and integer expected_revision required')
                result = desk.respond(identifier, value['response'], value['expected_revision']) if operation == 'respond' else desk.execute(identifier, value['expected_revision'])
            self.send_value(200, result)

        def request(self):
            api = urlsplit(self.path).path.startswith('/api/')
            if not self.guard(api):
                return
            if api:
                try:
                    self.handle_api()
                except LoopError as exc:
                    message = str(exc)
                    self.send_value(409 if any(x in message.lower() for x in ('conflict', 'stale', 'changed')) else 400, {'error': message})
                except (KeyError, TypeError, ValueError):
                    self.send_value(400, {'error': 'Invalid request fields'})
                except Exception:
                    self.send_value(500, {'error': 'Local request failed; inspect task state before retrying'})
                return
            if self.command != 'GET':
                self.send_value(405, {'error': 'Method not allowed'}); return
            self.send_value(404, {'error': 'Not found'}); return

        do_GET = request
        do_POST = request

    class LocalServer(ThreadingHTTPServer):
        def server_bind(self):
            # HTTPServer's default reverse-DNS lookup is unnecessary on loopback
            # and can block local startup on hosts without working DNS.
            TCPServer.server_bind(self)
            self.server_name, self.server_port = self.server_address

    server = LocalServer(('127.0.0.1', port), Handler)
    server.daemon_threads = True
    server.capability_token = secrets.token_urlsafe(32)
    server.url = 'http://127.0.0.1:' + str(server.server_port) + '/#' + server.capability_token
    return server
