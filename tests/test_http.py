import json
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request,urlopen
from optics_workbench.core import Workbench
from optics_workbench.server import Server

class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.w=Workbench(data_dir=self.tmp.name)
        self.server=Server(self.w,port=0);self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
    def tearDown(self):
        self.server.shutdown();self.thread.join();self.server.server_close();self.tmp.cleanup()
    def request(self,path,body=None,headers=None):
        h=headers or {}
        if body is not None:h={'Content-Type':'application/json',**h}
        req=Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,headers=h)
        try:
            with urlopen(req,timeout=5) as r:return r.status,r.headers,r.read()
        except HTTPError as e:return e.code,e.headers,e.read()

    def test_browser_save_and_export(self):
        status,_,raw=self.request('/api/bootstrap');boot=json.loads(raw);self.assertEqual(status,200)
        token={'X-Workbench-Token':boot['csrf_token'],'Origin':self.base}
        status,_,raw=self.request('/api/projects/new',{'template':'compact','name':'Browser test'},token)
        p=json.loads(raw);self.assertEqual(status,200)
        p['parameters']['source_lumens']=4000
        status,_,raw=self.request('/api/projects',p,token);saved=json.loads(raw);self.assertEqual(status,200);self.assertEqual(saved['version'],2)
        status,headers,raw=self.request('/api/projects/'+p['id']+'/export');self.assertIn('attachment',headers['Content-Disposition']);self.assertEqual(json.loads(raw)['schema_version'],1)

    def test_reject_cross_site_host_and_missing_token(self):
        for path,body,headers in [('/api/projects/new',{},{}),('/api/bootstrap',None,{'Origin':'https://outside.example'}),('/api/bootstrap',None,{'Host':'outside.example'}),('/api/bootstrap',None,{'Sec-Fetch-Site':'cross-site'})]:
            with self.subTest(headers=headers):self.assertEqual(self.request(path,body,headers)[0],403)

    def test_static_whitelist_and_errors(self):
        self.assertEqual(self.request('/config.local.json')[0],404)
        self.assertEqual(self.request('/../optics_workbench/core.py')[0],404)
        self.assertEqual(self.request('/api/library?page=invalid')[0],400)
        status,headers,raw=self.request('/');self.assertEqual(status,200);self.assertIn(b'<!',raw);self.assertIn("frame-ancestors 'none'",headers['Content-Security-Policy'])

if __name__=='__main__':unittest.main()
