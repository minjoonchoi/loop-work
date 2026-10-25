"""HTTP scope keeps unrelated vault diagnostics out of reads and receipts."""
from pathlib import Path
import http.client
import json
import tempfile
import threading
import unittest
from urllib.parse import quote

from loop_work import board_ui
from loop_work.board import Board
from loop_work.human import HumanDesk
from loop_work.knowledge import KnowledgeBase
from loop_work.storage import file_hash, read_json, write_json
from loop_work.work import Work


class BoardScopeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.vault = self.base / 'vault'
        self.kb = KnowledgeBase(self.base / 'kb', vault_home=self.vault)
        self.work = Work(self.kb)
        self.desk = HumanDesk(self.kb)
        self.tasks = []
        for index, title in enumerate(('In-scope task', 'OUTSIDE-TITLE-SENTINEL')):
            project = self.base / ('project-' + str(index))
            project.mkdir()
            (project / 'input.txt').write_text('Original input\n')
            task = self.work.open('document', title, 'codex', [project],explicit_skill=True)['task']
            self.work._stop_internal(task['id'], 'Operator confirmation required')
            self.tasks.append(self.kb.get('task', task['id']))
        self.task, self.other = self.tasks
        self.primary = self.desk.create(self.task['id'], self.payload('in-scope-approval', 'approval', 'resume_task'))
        secondary = self.desk.create(self.other['id'], self.payload('OUTSIDE-REQUEST-SENTINEL'))
        self.desk.respond(secondary['id'], {'decision': 'answer', 'text': 'OUTSIDE-RESPONSE-SENTINEL'}, 1)
        self.board = Board(self.kb)
        other_row = self.board.show(self.other['id'], 'task')
        self.other_path = other_row['path']
        note = self.vault / self.other_path
        note.write_text(note.read_text() + '\nOUTSIDE-EDIT-SENTINEL\n')
        status = self.kb.export_vault('task', self.other['id'])
        self.assertTrue(status['errors'], status)
        # An unsafe historical note must not disclose its path via global scan
        # warnings on a server scoped to the unrelated primary task/session.
        self.unsafe_name = str(Path(self.other_path).parent / '기록' / '중간' / ('날짜미상-중간-' + 'a'*20 + '.md'))
        unsafe = self.vault / self.unsafe_name
        unsafe.parent.mkdir(parents=True,exist_ok=True)
        external = self.base / 'OUTSIDE-EXTERNAL-SENTINEL.txt'
        external.write_text('OUTSIDE-FILE-CONTENT-SENTINEL')
        unsafe.symlink_to(external)
        manifest_path = self.kb.home / 'vault-owned.json'
        manifest = read_json(manifest_path)
        manifest['files'][self.unsafe_name] = file_hash(unsafe)
        manifest['documents'][self.unsafe_name] = {'kind':'task','id':self.other['id'],'role':'interim',
            'project_id':self.other['project_ids'][0],'task_id':self.other['id']}
        write_json(manifest_path, manifest)
        self.sentinels = (self.other['id'], self.other['session_id'], self.other_path, self.unsafe_name,
                          'OUTSIDE-TITLE-SENTINEL', 'OUTSIDE-REQUEST-SENTINEL',
                          'OUTSIDE-RESPONSE-SENTINEL', 'OUTSIDE-EDIT-SENTINEL',
                          'OUTSIDE-PATH-SENTINEL', 'OUTSIDE-EXTERNAL-SENTINEL',
                          'OUTSIDE-FILE-CONTENT-SENTINEL')

    @staticmethod
    def payload(identifier, kind='decision', action=None):
        return {'id': identifier, 'kind': kind, 'title': 'Confirm requested action',
                'question': 'Confirm this exact task?', 'options': [], 'action': action}

    def server(self, **scope):
        server = board_ui.make_server(self.kb, **scope)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        def close():
            server.shutdown()
            server.server_close()
            thread.join(2)
        self.addCleanup(close)
        return server

    def http(self, server, method, path, payload=None):
        host = '127.0.0.1:' + str(server.server_port)
        headers = {'Host': host, 'Origin': 'http://' + host,
                   'X-Loop-Capability': server.capability_token}
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=3)
        try:
            connection.request(method, path, json.dumps(payload).encode() if payload is not None else None, headers)
            response = connection.getresponse()
            return response.status, response.read().decode()
        finally:
            connection.close()

    def assert_private(self, serialized):
        for sentinel in self.sentinels:
            self.assertNotIn(sentinel, serialized)

    def test_scoped_lists_redact_unrelated_errors_and_cannot_expand(self):
        for scope in ({'task_id': self.task['id']}, {'session_id': self.task['session_id']}):
            with self.subTest(scope=scope):
                server = self.server(**scope)
                status, body = self.http(server, 'GET', '/api/board?include_closed=1')
                self.assertEqual(status, 200, body)
                self.assert_private(body)
                view = json.loads(body)
                self.assertEqual([row['id'] for row in view['tasks']], [self.task['id']])
                self.assertNotEqual(view['vault_status']['status'], 'ok')
                for query in ('task_id=' + self.other['id'], 'session_id=' + self.other['session_id']):
                    # Only the originally fixed dimension is a widening attempt.
                    if query.split('=')[0] not in scope:
                        continue
                    code, rejected = self.http(server, 'GET', '/api/board?' + query)
                    self.assertNotEqual(code, 200)
                    self.assert_private(rejected)
                code, rejected = self.http(server, 'GET', '/api/document?path=' + quote(self.unsafe_name, safe=''))
                self.assertNotEqual(code, 200)
                self.assert_private(rejected)
        server = self.server()
        code, body = self.http(server, 'GET', '/api/board?include_closed=1')
        self.assertEqual(code, 200, body)
        self.assertIn(self.other['id'], body)
        self.assertIn('OUTSIDE-RESPONSE-SENTINEL', body)
        self.assertTrue(json.loads(body)['vault_status']['errors'])

    def mutation_receipts(self, scope):
        server = self.server(**scope)
        for operation in ('respond', 'execute'):
            row = self.board.show(self.primary['id'])
            value = {'expected_revision': row['record']['revision'], 'expected_vault_revision': row['revision']}
            if operation == 'respond':
                value['response'] = {'decision': 'approve', 'text': 'Resume only this unchanged task.'}
            code, body = self.http(server, 'POST', '/api/requests/' + row['id'] + '/' + operation, value)
            self.assertEqual(code, 200, body)
            self.assert_private(body)
            receipt = json.loads(body)
            self.assertTrue(receipt['action_committed'])
            self.assertIn(receipt['request']['status'], ('answered', 'executed'))
        self.assertEqual(self.kb.get('task', self.task['id'])['phase'], 'goal_setting')
        self.assertEqual(self.kb.get('human-request', self.primary['id'])['status'], 'executed')

    def test_task_scoped_respond_and_execute_receipts_do_not_leak_global_diagnostics(self):
        self.mutation_receipts({'task_id': self.task['id']})

    def test_session_scoped_respond_and_execute_receipts_do_not_leak_global_diagnostics(self):
        self.mutation_receipts({'session_id': self.task['session_id']})


if __name__ == '__main__':
    unittest.main()
