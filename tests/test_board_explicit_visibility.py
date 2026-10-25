"""Same-session ordinary records never become Board tasks by association."""
import http.client
import json
import threading
import unittest
from unittest.mock import patch
import test_board
from loop_work.board_ui import make_server
from loop_work.storage import LoopError, digest, now, read_json


class ExplicitVisibilityTests(unittest.TestCase):
    def setUp(self):
        self.fixture=test_board.BoardTests();self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        self.kb=self.fixture.kb;self.board=self.fixture.board;self.visible=self.fixture.task
        self.hidden=self.fixture.work.open('document','일반 요청 참고 작업','codex',[self.fixture.project],session_id=self.visible['session_id'])['task']
        self.request=self.fixture.desk.create(self.hidden['id'],{'id':'ordinary-request','kind':'decision','title':'일반 참고 질문','question':'보존할 원문','options':[],'action':None})
        self.kb.sync_vault()
        manifest=read_json(self.kb.home/'vault-owned.json')
        self.paths=[p for p,d in manifest['documents'].items() if d.get('task_id')==self.hidden['id'] or d.get('id')==self.hidden['id']]
        self.bytes={p:(self.fixture.vault/p).read_bytes() for p in self.paths}
    def test_mixed_session_filters_cards_requests_counts_and_all_direct_reads(self):
        for listing in (self.board.list(include_closed=True),self.board.list(session_id=self.visible['session_id'],include_closed=True)):
            self.assertEqual([x['id'] for x in listing['tasks']],[self.visible['id']])
            self.assertEqual([x['id'] for x in listing['requests']],[self.fixture.request['id']])
        self.assertEqual(self.board.projects()['projects'][0]['task_count'],1)
        for action in (lambda:self.board.show(self.hidden['id'],'task'),lambda:self.board.show(self.request['id']),lambda:self.board.wiki('task',self.hidden['id']),lambda:self.board.save_wiki('task',self.hidden['id'],{})):
            with self.assertRaises(LoopError):action()
        for path in self.paths:
            with self.assertRaises(LoopError):self.board.document(path)
            self.assertEqual((self.fixture.vault/path).read_bytes(),self.bytes[path])
        self.assertEqual(self.board._history(self.hidden['id']),[])
        self.assertIsNotNone(self.kb.get('task',self.hidden['id']))
    def test_forged_vault_provenance_does_not_authorize_hidden_request_or_control_receipt(self):
        for path in self.paths:
            if path.endswith('.md'):
                self.fixture.metadata(self.fixture.vault/path,lambda m:m['record'].update(provenance={'version':1,'source':'explicit_loop_work'}))
        payload={'operation_id':'old-receipt','kind':'pause','text':'원문','expected_task_revision':digest(self.hidden),'expected_control_version':0,'expected_vault_revision':'old'}
        key='board-control-'+digest([self.hidden['id'],payload['operation_id']])[:24]
        self.kb.put('board-control',{'id':key,'task_id':self.hidden['id'],'session_id':self.hidden['session_id'],'input':payload,'original_text':'원문','created_at':now()})
        with self.assertRaises(LoopError):self.board.control(self.hidden['id'],payload)
        with self.assertRaises(LoopError):self.board.respond(self.request['id'],{'decision':'answer','text':'불허'},1,'old')
        with self.assertRaises(LoopError):self.board.execute(self.request['id'],1,'old')
        self.assertEqual(self.kb.get('human-request',self.request['id'])['status'],'pending')
        self.assertNotIn(self.hidden['id'],[x['id'] for x in self.board.list(include_closed=True)['tasks']])
    def test_real_http_hidden_ids_and_scope_expansion_are_rejected(self):
        server=make_server(self.kb,session_id=self.visible['session_id']);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join(2)))
        def request(method,path,data=None):
            con=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3);host='127.0.0.1:'+str(server.server_port)
            con.request(method,path,json.dumps(data) if data is not None else None,{'Host':host,'Origin':'http://'+host,'X-Loop-Capability':server.capability_token,'Content-Type':'application/json'})
            response=con.getresponse();body=json.loads(response.read());con.close();return response.status,body
        status,body=request('GET','/api/board?include_closed=1');self.assertEqual(status,200)
        self.assertNotIn(self.hidden['id'],[x['id'] for x in body['tasks']])
        for path in ('/api/tasks/'+self.hidden['id'],'/api/tasks/'+self.hidden['id']+'/wiki','/api/requests/'+self.request['id']):self.assertNotEqual(request('GET',path)[0],200)
        for path,data in (('/api/tasks/'+self.hidden['id']+'/wiki',{}),('/api/tasks/'+self.hidden['id']+'/control',{}),('/api/requests/'+self.request['id']+'/respond',{'expected_revision':1,'expected_vault_revision':'old','response':{'decision':'answer','text':'원문'}}),('/api/requests/'+self.request['id']+'/execute',{'expected_revision':1,'expected_vault_revision':'old'})):
            self.assertNotEqual(request('POST',path,data)[0],200)
        self.assertNotEqual(request('GET','/api/board?session_id=other')[0],200)

    def test_information_only_project_keeps_wiki_with_zero_tasks(self):
        project=self.fixture.base/'information';project.mkdir();(project/'README.md').write_text('참고 사실 원문\n')
        locations=[self.kb.attach(project)]
        self.kb.remember({'id':'information-fact','scope':'project','kind':'fact','status':'confirmed','summary':'일반 요청 참고 사실','evidence':['README.md:1'],'paths':['README.md']},locations,digest(self.kb.observe(locations)))
        pid=locations[0]['project_id'];rows=self.board.projects()['projects']
        self.assertNotIn(pid,[x['id'] for x in rows])
        manifest=read_json(self.kb.home/'vault-owned.json')
        topics=[name for name,item in manifest['documents'].items() if item.get('id')=='information-fact' and item.get('role')=='topic']
        self.assertTrue(topics);self.assertTrue(all((self.fixture.vault/name).is_file() for name in topics))
        self.fixture.work.open('document','일반 참고 작업','codex',[project])
        row=next(x for x in self.board.projects()['projects'] if x['id']==pid)
        self.assertEqual(row['task_count'],0)
        self.assertEqual(self.board.wiki('project',pid)['project_id'],pid)
        self.assertNotIn(pid,[x['id'] for x in self.board.projects(session_id=self.visible['session_id'])['projects']])

    def test_unscoped_diagnostic_redacts_ordinary_export_conflict(self):
        note=self.fixture.vault/self.paths[0];note.write_text(note.read_text()+'\nORDINARY-PRIVATE-EXPORT-SENTINEL\n')
        status=self.kb.export_vault('task',self.hidden['id']);self.assertTrue(status['errors'])
        value=json.dumps(self.board.list(include_closed=True),ensure_ascii=False)
        for secret in (self.hidden['id'],self.request['id'],self.paths[0],'ORDINARY-PRIVATE-EXPORT-SENTINEL'):
            self.assertNotIn(secret,value)
        self.assertTrue(self.board.sync_status()['errors'])

    def test_unscoped_http_control_fresh_replay_and_postcommit_error_redact_hidden_export_diagnostics(self):
        from loop_work.orchestration import Orchestration
        # Both tasks and their original questions stay in the real database.
        manifest=read_json(self.kb.home/'vault-owned.json')
        current_path=next(name for name,item in manifest['documents'].items() if item.get('id')==self.hidden['id'] and item.get('role')=='current')
        note=self.fixture.vault/current_path
        note.write_text(note.read_text()+'\nORDINARY-CONTROL-EXPORT-SECRET\n')
        export=self.kb.export_vault('task',self.hidden['id']);self.assertTrue(export['errors'])
        secrets=(self.hidden['id'],self.hidden['title'],self.request['id'],current_path,'ORDINARY-CONTROL-EXPORT-SECRET',*export['errors'])
        original_status=json.dumps(self.kb.vault_status(),ensure_ascii=False)
        self.assertIn(self.hidden['id'],original_status)
        server=make_server(self.kb);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join(2)))
        def post(payload):
            con=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=3);host='127.0.0.1:'+str(server.server_port)
            con.request('POST','/api/tasks/'+self.visible['id']+'/control',json.dumps(payload),{'Host':host,'Origin':'http://'+host,'X-Loop-Capability':server.capability_token,'Content-Type':'application/json'})
            response=con.getresponse();raw=response.read().decode();con.close();self.assertEqual(response.status,200,raw)
            value=json.loads(raw);self.assertTrue(value['action_committed'],value)
            for secret in secrets:self.assertNotIn(secret,raw)
            self.assertEqual(value['vault_status']['status'],'withheld')
            self.assertTrue(value['vault_status']['errors'])
            return value
        original_feedback=Orchestration.feedback
        def committed_then_error(instance,*args,**kwargs):
            original_feedback(instance,*args,**kwargs)
            raise RuntimeError('ORDINARY-CONTROL-EXPORT-SECRET '+self.hidden['id'])
        for late_error in (False,True):
            with self.subTest(postcommit_error=late_error):
                row=self.board.show(self.visible['id'],'task')
                payload={'operation_id':'private-control-'+str(late_error),'kind':'pause','text':'일시정지 원문\n그대로 보존',
                         'expected_task_revision':row['control']['task_revision'],'expected_control_version':row['control']['control_version'],'expected_vault_revision':row['vault_revision']}
                before=len(self.kb.list('feedback'))
                if late_error:
                    with patch.object(Orchestration,'feedback',committed_then_error):first=post(payload)
                else:first=post(payload)
                self.assertFalse(first['reused']);after=self.kb.list('feedback')
                self.assertEqual(len(after),before+1)
                replay=post(payload);self.assertTrue(replay['reused'])
                self.assertEqual(self.kb.list('feedback'),after)
                self.assertEqual(replay['control']['original_text'],payload['text'])
        self.assertEqual(self.kb.get('human-request',self.request['id'])['status'],'pending')
        self.assertIn(self.hidden['id'],json.dumps(self.kb.vault_status(),ensure_ascii=False))
