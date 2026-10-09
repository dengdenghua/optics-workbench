import json
import tempfile
import threading
import unittest
from unittest.mock import patch
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

    def test_scene_routes_atomic_edit_conflict_and_static_assets(self):
        boot=json.loads(self.request('/api/bootstrap')[2]);token={'X-Workbench-Token':boot['csrf_token'],'Origin':self.base}
        p=json.loads(self.request('/api/projects/new',{'template':'dlp','name':'Scene routes'},token)[2])
        view=json.loads(self.request('/api/projects/'+p['id']+'/scene')[2]);scene=view['scene']
        scene['elements'][1]['focal_mm']=20
        self.assertEqual(self.request('/api/scene/trace',{'scene':scene})[0],403)
        self.assertEqual(self.request('/api/scene/trace',{'scene':scene},token)[0],200)
        body={'project_id':p['id'],'version':p['version'],'scene':scene,'parameter_updates':{'reference_efl_mm':20}}
        status,_,raw=self.request('/api/design/apply',body,token);saved=json.loads(raw)
        self.assertEqual(status,200);self.assertEqual(saved['version'],p['version']+1)
        self.assertEqual(saved['scene']['elements'][1]['focal_mm'],20)
        self.assertEqual(self.request('/api/design/apply',body,token)[0],400)
        self.assertEqual(self.w.project(p['id'])['version'],saved['version'])
        for path in ['/optical-view.js','/optical-view.css']:
            status,_,raw=self.request(path);self.assertEqual(status,200);self.assertTrue(raw)

    def test_ai_unconfigured_is_explicit_and_mutations_protected(self):
        boot=json.loads(self.request('/api/bootstrap')[2]);token={'X-Workbench-Token':boot['csrf_token'],'Origin':self.base}
        p=json.loads(self.request('/api/projects/new',{'template':'dlp'},token)[2])
        with patch.dict('os.environ',{'OPENAI_API_KEY':''}):
            status,_,raw=self.request('/api/ai/status');self.assertEqual(status,200);self.assertFalse(json.loads(raw)['configured'])
            body={'project_id':p['id'],'version':p['version'],'message':'修改焦距'}
            self.assertEqual(self.request('/api/ai/chat',body)[0],403)
            status,_,raw=self.request('/api/ai/chat',body,token);self.assertEqual(status,503);self.assertIn('密钥',json.loads(raw)['error'])
        self.assertEqual(self.w.project(p['id'])['version'],p['version'])

    def test_color_cases_preview_save_and_conflict(self):
        boot=json.loads(self.request('/api/bootstrap')[2]);token={'X-Workbench-Token':boot['csrf_token'],'Origin':self.base}
        p=self.w.project(boot['projects'][0]['id'])
        self.assertEqual(json.loads(self.request('/api/color/cases')[2])[0]['id'],'synthetic-rgb')
        case=json.loads(self.request('/api/color/cases/synthetic-rgb')[2]);b=case['budget']
        self.assertFalse(json.loads(self.request('/api/projects/'+p['id']+'/color')[2])['saved'])
        self.assertEqual(self.request('/api/color/calculate',{'budget':b})[0],403)
        self.assertEqual(self.request('/api/color/calculate',{'budget':b},token)[0],200)
        body={'project_id':p['id'],'version':p['version'],'budget':b}
        status,_,raw=self.request('/api/color/save',body,token);saved=json.loads(raw)
        self.assertEqual(status,200);self.assertEqual(saved['color_budget'],b)
        self.assertEqual(self.request('/api/color/save',body,token)[0],400)
        for asset in ('/color-view.js','/color-view.css'):self.assertEqual(self.request(asset)[0],200)

if __name__=='__main__':unittest.main()
