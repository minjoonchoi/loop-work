from __future__ import annotations
import contextlib
import http.client
import io
import json
import threading
import unittest
from urllib.parse import quote
from unittest.mock import patch

from loop_work import board_ui
import test_board


class BoardUiTests(unittest.TestCase):
    def setUp(self):
        test_board.BoardTests.setUp(self)
        self.server=board_ui.make_server(self.kb,task_id=self.task['id'])
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
        self.addCleanup(self.stop)
        self.host='127.0.0.1:'+str(self.server.server_port)

    def stop(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join(2)

    def http(self,method,path,value=None,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        actual={'Host':self.host,'Origin':'http://'+self.host,'X-Loop-Capability':self.server.capability_token}
        if value is not None:
            actual['Content-Type']='application/json'
        actual.update(headers or {})
        connection.request(method,path,json.dumps(value).encode() if value is not None else None,actual)
        response=connection.getresponse(); result=(response.status,response.read()); connection.close()
        return result

    def test_security_scope_and_vault_driven_task_detail(self):
        status,body=self.http('GET','/api/board?include_closed=1')
        self.assertEqual(status,200)
        listing=json.loads(body)
        self.assertEqual(listing['tasks'][0]['record']['id'],self.task['id'])
        self.assertEqual(self.http('GET','/api/board',headers={'X-Loop-Capability':'wrong'})[0],403)
        self.assertEqual(self.http('GET','/api/board',headers={'Host':'foreign.example'})[0],403)
        self.assertEqual(self.http('GET','/api/board',headers={'Origin':'https://foreign.example'})[0],403)
        self.assertNotEqual(self.http('GET','/api/board?task_id=other-task')[0],200)
        detail=json.loads(self.http('GET','/api/tasks/'+self.task['id'])[1])
        path=next(item['path'] for item in detail['documents'] if '/interim/' in item['path'])
        status,body=self.http('GET','/api/document?path='+quote(path,safe=''))
        self.assertEqual(status,200); self.assertFalse(json.loads(body)['writable'])
        self.assertNotEqual(self.http('GET','/api/document?path=../private')[0],200)

    def test_http_mutations_require_both_revisions_and_return_commit_receipt(self):
        row=self.board.show(self.request['id'])
        endpoint='/api/requests/'+row['id']+'/respond'
        self.assertEqual(self.http('POST',endpoint,{'expected_revision':1,'response':{'decision':'approve','text':'Approve'}})[0],400)
        value={'expected_revision':1,'expected_vault_revision':row['revision'],'response':{'decision':'approve','text':'Approve once'}}
        status,body=self.http('POST',endpoint,value)
        self.assertEqual(status,200,body); self.assertTrue(json.loads(body)['action_committed'])
        self.assertEqual(self.http('POST',endpoint,value)[0],409)
        self.assertEqual(self.http('POST','/api/requests',{'task_id':self.task['id'],'request':{}})[0],404)

    def test_browser_is_opened_after_serving_and_failure_keeps_url_available(self):
        extra=board_ui.make_server(self.kb)
        def opener(url):
            connection=http.client.HTTPConnection('127.0.0.1',extra.server_port,timeout=3)
            connection.request('GET','/',headers={'Host':'127.0.0.1:'+str(extra.server_port)})
            self.assertEqual(connection.getresponse().status,200)
            connection.close(); extra.shutdown()
            return False
        with patch.object(board_ui,'make_server',return_value=extra), patch.object(board_ui.webbrowser,'open',side_effect=opener) as opened, contextlib.redirect_stdout(io.StringIO()) as output:
            board_ui.serve(self.kb)
        self.assertEqual(opened.call_args.args[0],extra.url)
        self.assertIn('printed URL',output.getvalue())

    def test_headless_mode_never_opens_browser_and_startup_export_failure_is_nonfatal(self):
        class Server:
            server_port=12345; url='http://127.0.0.1:12345/#test'
            def serve_forever(self): pass
            def shutdown(self): pass
            def server_close(self): pass
        with patch.object(self.kb,'sync_vault',side_effect=OSError('export unavailable')), patch.object(board_ui,'make_server',return_value=Server()), patch.object(board_ui.webbrowser,'open',side_effect=AssertionError('headless mode must not open browser')), contextlib.redirect_stdout(io.StringIO()) as output:
            board_ui.serve(self.kb,open_browser=False)
        self.assertIn('export unavailable',output.getvalue())
