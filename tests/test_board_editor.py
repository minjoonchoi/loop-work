"""API isolation regressions. Rich editing semantics now belong to the React desktop QA,
not the retired vanilla-JS serializer. This module does not certify editor parity.
"""
import http.client
import json
import threading
import unittest
from loop_work.board_ui import make_server, MAX_WIKI_BODY

class BoardApiIsolationTests(unittest.TestCase):
    def setUp(self):
        class Desk:
            def __getattr__(self,name):
                raise AssertionError('Rejected request must not reach Board: '+name)
        self.server=make_server(None,desk=Desk())
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.addCleanup(self.stop)
        self.host='127.0.0.1:'+str(self.server.server_port)
    def stop(self):
        self.server.shutdown();self.server.server_close();self.thread.join(2)
    def request(self,method,path,headers=None):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=3)
        actual={'Host':self.host,'Origin':'http://'+self.host,'X-Loop-Capability':self.server.capability_token,'Content-Type':'application/json'}
        actual.update(headers or {})
        connection.request(method,path,headers=actual)
        response=connection.getresponse();result=(response.status,response.read());connection.close();return result
    def test_static_routes_never_publish_renderer_or_capability(self):
        for path in ('/','/index.html','/app.js','/style.css','/editor.js','/markdown.js','/../README.md'):
            status,body=self.request('GET',path)
            self.assertEqual(status,404);self.assertNotIn(self.server.capability_token.encode(),body)
    def test_transport_denies_foreign_origin_and_missing_capability_before_dispatch(self):
        for headers in ({'Host':'foreign.invalid'},{'Origin':'https://foreign.invalid'},{'X-Loop-Capability':''},{'Sec-Fetch-Site':'cross-site'}):
            self.assertEqual(self.request('POST','/api/requests/x/respond',headers)[0],403)
    def test_body_bounds_reject_without_backend_side_effect(self):
        self.assertEqual(self.request('POST','/api/requests/x/respond',{'Content-Length':'65537'})[0],413)
        self.assertEqual(self.request('POST','/api/projects/p/wiki',{'Content-Length':str(MAX_WIKI_BODY+1)})[0],413)
