import http.client
import json
import threading
import unittest
from loop_work.board_ui import make_server
from loop_work.storage import LoopError


class Desk:
    def __init__(self):self.calls=[]
    def _scope(self,project_id):
        if project_id!='p':raise AssertionError('Project scope was not forwarded')
    def projects(self,query,sort,session,task,project_id=None):
        self._scope(project_id);self.calls.append(('projects',query,sort,session,task,project_id));return {'projects':[{'id':'p'}]}
    def list(self,*args,project_id=None):self._scope(project_id);return {'tasks':[],'requests':[]}
    def show(self,key,kind='human-request',project_id=None):
        self._scope(project_id)
        return {'id':key,'kind':kind,'record':{'id':key,'task_id':'t','session_id':'s','project_ids':['p']}}
    def wiki(self,kind,key,project_id=None):
        self._scope(project_id);self.calls.append(('wiki',kind,key,project_id));return {'id':key,'project_id':'p','title':'위키','body_markdown':'본문','revision':'pin','editable':True}
    def save_wiki(self,kind,key,payload,project_id=None):
        if payload.get('title') == '충돌':
            class Conflict(LoopError): status_code=409
            raise Conflict('외부 문서와 충돌했습니다')
        self._scope(project_id);self.calls.append(('save',kind,key,project_id));return {'saved':True,'id':key,'project_id':'p'}
    def control(self,key,payload,project_id=None):self._scope(project_id);self.calls.append(('control',key,project_id));return {'action_committed':True}
    def respond(self,*args,project_id=None):self._scope(project_id);self.calls.append(('respond',project_id));return {'action_committed':True}
    def execute(self,*args,project_id=None):self._scope(project_id);self.calls.append(('execute',project_id));return {'action_committed':True}
    def sync_status(self,scoped):return {'withheld':scoped}


class ProjectRouteTests(unittest.TestCase):
    def setUp(self):
        self.desk=Desk();self.server=make_server(None,desk=self.desk,project_id='p')
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(lambda:(self.server.shutdown(),self.server.server_close(),self.thread.join(2)))
    def request(self,method,path,payload=None,declared_length=None):
        con=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        host='127.0.0.1:'+str(self.server.server_port)
        headers={'Host':host,'Origin':'http://'+host,'X-Loop-Capability':self.server.capability_token,'Content-Type':'application/json'}
        if declared_length is not None: headers['Content-Length']=str(declared_length)
        con.request(method,path,json.dumps(payload) if payload is not None else None,headers)
        res=con.getresponse();data=json.loads(res.read());con.close();return res.status,data
    def test_project_search_sort_scope_and_wiki_get_post(self):
        status,data=self.request('GET','/api/projects?query=test&sort=updated');self.assertEqual(status,200);self.assertEqual(data['projects'][0]['id'],'p')
        for route in ('/api/board?project_id=other','/api/tasks/t?project_id=other','/api/projects/other/wiki','/api/tasks/t/wiki?project_id=other'):
            self.assertEqual(self.request('GET',route)[0],400)
        for route in ('/api/projects/p/wiki','/api/tasks/t/wiki?project_id=p'):
            self.assertEqual(self.request('GET',route)[0],200)
            self.assertEqual(self.request('POST',route,{'operation_id':'op','expected_revision':'pin','title':'제목','body_markdown':'본문'})[0],200)
            self.assertEqual(self.request('POST',route,{'title':'extra'})[0],400)
            status,error=self.request('POST',route,{'operation_id':'op','expected_revision':'old','title':'충돌','body_markdown':'초안'})
            self.assertEqual(status,409);self.assertIn('충돌',error['error'])
    def test_project_scope_reaches_control_response_and_execute(self):
        for route,payload in [('/api/tasks/t/control',{'kind':'pause'}),('/api/requests/r/respond',{'expected_revision':1,'expected_vault_revision':'pin','response':{'decision':'approve','text':'확인'}}),('/api/requests/r/execute',{'expected_revision':1,'expected_vault_revision':'pin'})]:
            status,value=self.request('POST',route,payload);self.assertEqual(status,200,value);self.assertTrue(value['vault_status']['withheld'])
        self.assertIn(('control','t','p'),self.desk.calls);self.assertIn(('respond','p'),self.desk.calls);self.assertIn(('execute','p'),self.desk.calls)

    def test_wiki_transport_limit_is_separate_from_control_limit(self):
        payload={'operation_id':'large','expected_revision':'pin','title':'제목','body_markdown':'x'*70000}
        self.assertEqual(self.request('POST','/api/tasks/t/wiki',payload)[0],200)
        self.assertEqual(self.request('POST','/api/tasks/t/control',{'text':'x'*70000})[0],413)
        # Oversized length must be rejected before the server waits for body bytes.
        status,error=self.request('POST','/api/tasks/t/wiki',declared_length=1024*1024+1)
        self.assertEqual(status,413);self.assertIn('1MiB',error['error'])

    def test_typed_korean_conflicts_preserve_409_for_all_mutation_routes(self):
        class Conflict(LoopError): status_code=409
        def conflict(*args,**kwargs):raise Conflict('문서 또는 실행 근거가 변경되었습니다')
        routes=[('control','/api/tasks/t/control',{'kind':'pause'}),
                ('respond','/api/requests/r/respond',{'expected_revision':1,'expected_vault_revision':'pin','response':{'decision':'approve','text':'확인'}}),
                ('execute','/api/requests/r/execute',{'expected_revision':1,'expected_vault_revision':'pin'}),
                ('save_wiki','/api/tasks/t/wiki',{'operation_id':'op','expected_revision':'pin','title':'제목','body_markdown':'본문'})]
        for method,route,payload in routes:
            original=getattr(self.desk,method);setattr(self.desk,method,conflict)
            try:
                status,error=self.request('POST',route,payload)
                self.assertEqual(status,409,(route,error));self.assertEqual(error['error'],'문서 또는 실행 근거가 변경되었습니다')
            finally:setattr(self.desk,method,original)


class LargeUnicodeWikiHttpTests(unittest.TestCase):
    def setUp(self):
        import test_board_wiki
        test_board_wiki.setup(self)
        self.server=make_server(self.kb,project_id=self.pid)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(lambda:(self.server.shutdown(),self.server.server_close(),self.thread.join(2)))

    def post(self,payload,*,discard_response=False):
        con=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=10)
        host='127.0.0.1:'+str(self.server.server_port)
        headers={'Host':host,'Origin':'http://'+host,'X-Loop-Capability':self.server.capability_token,'Content-Type':'application/json'}
        encoded=json.dumps(payload,ensure_ascii=False).encode('utf-8')
        self.assertLess(len(encoded),1024*1024)
        con.request('POST','/api/tasks/'+self.task['id']+'/wiki?project_id='+self.pid,encoded,headers)
        response=con.getresponse();status=response.status;body=response.read();con.close()
        # Model a response lost by the client after HTTP delivery: the caller
        # never receives or adopts the save receipt, and retries identical input.
        return status,None if discard_response else json.loads(body)

    def test_large_unicode_lost_response_same_operation_retry_has_no_second_write(self):
        from loop_work.storage import file_hash
        wiki=self.board.wiki('task',self.task['id'],self.pid)
        body='😀'*100000
        self.assertEqual(len(body.encode('utf-8')),400000)
        payload={'operation_id':'large-emoji-http','expected_revision':wiki['revision'],'title':'큰 유니코드 문서','body_markdown':body}
        raw=self.kb.get('task',self.task['id'])
        status,lost=self.post(payload,discard_response=True)
        self.assertEqual(status,200);self.assertIsNone(lost)
        saved=self.board.wiki('task',self.task['id'],self.pid)
        self.assertEqual(saved['body_markdown'],body)
        def inventory():
            return {str(path.relative_to(self.base)):(file_hash(path),path.stat().st_mtime_ns,path.stat().st_ino)
                    for path in self.base.rglob('*') if path.is_file()}
        files=inventory()
        status,retry=self.post(payload)
        self.assertEqual(status,200,retry.get('error'))
        self.assertTrue(retry['saved']);self.assertTrue(retry['reused'])
        self.assertEqual(retry['revision'],saved['revision'])
        self.assertEqual(retry['body_markdown'],body)
        self.assertEqual(inventory(),files)
        self.assertEqual(self.kb.get('task',self.task['id']),raw)
