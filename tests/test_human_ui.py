from __future__ import annotations

import http.client
import json
import threading
import unittest

from loop_work.human_ui import MAX_BODY, make_server
from loop_work.storage import LoopError


class Desk:
    def __init__(self):
        self.rows = {'request-1': {'id': 'request-1', 'task_id': 'task-1', 'kind': 'approval', 'title': '<script>alert(1)</script>', 'question': 'Resume?', 'status': 'pending', 'revision': 1}}
        self.calls = []

    def list(self, session_id=None, task_id=None, include_closed=False):
        return {'requests': [r for r in self.rows.values() if (not task_id or r['task_id'] == task_id) and (include_closed or r['status'] == 'pending')], 'tasks': [{'id': 'task-1', 'phase': 'blocked'}]}

    def show(self, identifier):
        if identifier not in self.rows:
            raise LoopError('Unknown human request')
        return self.rows[identifier]

    def create(self, task, payload):
        self.calls.append(('create', task))
        self.rows[payload['id']] = {**payload, 'task_id': task, 'status': 'pending', 'revision': 1}
        return self.rows[payload['id']]

    def respond(self, identifier, response, expected_revision):
        row = self.show(identifier)
        if row['revision'] != expected_revision:
            raise LoopError('Human request revision changed')
        self.calls.append(('respond', identifier))
        row.update(response=response, status='answered', revision=expected_revision + 1)
        return row

    def execute(self, identifier, expected_revision):
        row = self.show(identifier)
        if row['revision'] != expected_revision:
            raise LoopError('Human request revision changed')
        self.calls.append(('execute', identifier))
        row.update(status='executed', revision=expected_revision + 1)
        return row


class HumanUiTests(unittest.TestCase):
    def setUp(self):
        self.desk = Desk()
        self.server = make_server(None, desk=self.desk)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)
        self.host = '127.0.0.1:' + str(self.server.server_port)

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)

    def request(self, method, path, value=None, *, headers=None, capability=True):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        actual = {'Host': self.host, 'Origin': 'http://' + self.host}
        if capability:
            actual['X-Loop-Capability'] = self.server.capability_token
        if value is not None:
            actual['Content-Type'] = 'application/json'
        actual.update(headers or {})
        body = json.dumps(value).encode() if value is not None else None
        connection.request(method, path, body, actual)
        response = connection.getresponse()
        result = response.status, dict(response.getheaders()), response.read()
        connection.close()
        return result

    def test_loopback_static_csp_and_no_arbitrary_file_read(self):
        self.assertEqual(self.server.server_address[0], '127.0.0.1')
        self.assertIn('/#' + self.server.capability_token, self.server.url)
        code, headers, body = self.request('GET', '/', capability=False)
        self.assertEqual(code, 200)
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertNotIn(self.server.capability_token.encode(), body)
        for path in ('/../README.md', '/api/file?path=/etc/passwd', '/style.css?token=secret'):
            self.assertIn(self.request('GET', path)[0], (400, 404))
        script = self.request('GET', '/app.js', capability=False)[2]
        self.assertIn(b'textContent', script)
        self.assertNotIn(b'innerHTML', script)

    def test_host_origin_and_capability_rejected_before_backend_calls(self):
        for headers, capability in (({'Host': 'evil.invalid'}, True), ({'Origin': 'https://evil.invalid'}, True), ({}, False), ({'Sec-Fetch-Site': 'cross-site'}, True)):
            self.assertEqual(self.request('GET', '/api/requests', headers=headers, capability=capability)[0], 403)
        self.assertEqual(self.desk.calls, [])
        code = self.request('POST', '/api/requests', {}, headers={'Origin': ''})[0]
        self.assertEqual(code, 403)

    def test_list_show_and_create(self):
        code, _, body = self.request('GET', '/api/requests?status=all')
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)['requests'][0]['id'], 'request-1')
        self.assertEqual(self.request('GET', '/api/requests/request-1')[0], 200)
        request = {'id': 'request-2', 'kind': 'decision', 'title': 'Choose', 'question': 'Which?', 'options': ['A', 'B'], 'action': None}
        code, _, body = self.request('POST', '/api/requests', {'task_id': 'task-1', 'request': request})
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(body)['status'], 'pending')

    def test_optimistic_revision_prevents_duplicate_response_and_execution(self):
        path = '/api/requests/request-1'
        response = {'expected_revision': 1, 'response': {'decision': 'approve', 'text': 'Explicit approval'}}
        self.assertEqual(self.request('POST', path + '/respond', response)[0], 200)
        self.assertEqual(self.request('POST', path + '/respond', response)[0], 409)
        execution = {'expected_revision': 2}
        self.assertEqual(self.request('POST', path + '/execute', execution)[0], 200)
        self.assertEqual(self.request('POST', path + '/execute', execution)[0], 409)
        self.assertEqual(self.desk.calls, [('respond', 'request-1'), ('execute', 'request-1')])

    def test_invalid_body_limits_and_exact_fields_have_no_side_effects(self):
        self.assertEqual(self.request('POST', '/api/requests', {'x': 'a' * MAX_BODY})[0], 413)
        self.assertEqual(self.request('POST', '/api/requests/request-1/execute', {'expected_revision': True})[0], 400)
        self.assertEqual(self.request('POST', '/api/requests/request-1/execute', {'expected_revision': 1, 'shell': 'anything'})[0], 400)
        self.assertEqual(self.desk.calls, [])

    def test_scoped_server_cannot_show_or_create_another_tasks_request(self):
        self.desk.rows['other'] = {'id': 'other', 'task_id': 'task-2', 'status': 'pending', 'revision': 1}
        self.server.shutdown(); self.thread.join(2)
        self.server.server_close()
        self.server = make_server(None, task_id='task-1', desk=self.desk)
        self.host = '127.0.0.1:' + str(self.server.server_port)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True); self.thread.start()
        self.assertEqual(self.request('GET', '/api/requests/other')[0], 400)
        self.assertEqual(self.request('GET', '/api/requests?task_id=task-2')[0], 400)
        self.assertEqual(self.request('POST', '/api/requests', {'task_id': 'task-2', 'request': {}})[0], 400)
        self.assertEqual(self.desk.calls, [])

    def test_isolated_real_backend_response_is_saved_without_task_execution(self):
        import tempfile
        from pathlib import Path
        from loop_work.human import HumanDesk
        from loop_work.knowledge import KnowledgeBase
        from loop_work.work import Work
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve(); root = base / 'project'; root.mkdir()
            kb = KnowledgeBase(base / 'knowledge')
            task = Work(kb).open('document', 'Explain current behavior', 'codex', [root])['task']
            backend = HumanDesk(kb)
            backend.create(task['id'], {'id': 'real-request', 'kind': 'decision', 'title': 'Choose scope', 'question': 'Which scope?', 'options': ['A', 'B'], 'action': None})
            # A separate real server keeps its capability and backend isolated.
            server = make_server(kb)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            try:
                connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                response = {'expected_revision': 1, 'response': {'decision': 'answer', 'text': 'A'}}
                connection.request('POST', '/api/requests/real-request/respond', json.dumps(response), {'Origin': 'http://127.0.0.1:' + str(server.server_port), 'X-Loop-Capability': server.capability_token, 'Content-Type': 'application/json'})
                reply = connection.getresponse(); body = json.loads(reply.read()); connection.close()
                self.assertEqual(reply.status, 200, body)
                self.assertEqual(backend.show('real-request')['response']['text'], 'A')
                self.assertEqual(kb.get('task', task['id'])['phase'], 'goal_setting')
                self.assertIsNone(body['execution'])
            finally:
                server.shutdown(); server.server_close(); thread.join(2)

    def test_factory_has_no_external_bind_parameter_and_tokens_are_independent(self):
        other = make_server(None, desk=Desk())
        self.addCleanup(other.server_close)
        self.assertNotEqual(other.capability_token, self.server.capability_token)
        with self.assertRaises(TypeError):
            make_server(None, host='0.0.0.0', desk=Desk())
        with self.assertRaises(LoopError):
            make_server(None, port=True, desk=Desk())
