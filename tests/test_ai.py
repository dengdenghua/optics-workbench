import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from optics_workbench.core import Workbench
from optics_workbench import ai


def call(name,args,ident='c1'):
    return {'type':'function_call','name':name,'arguments':json.dumps(args),'call_id':ident}


def answer(text):
    return {'status':'completed','output':[{'type':'message','role':'assistant','content':[{'type':'output_text','text':text}]}]}


class AITests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.w=Workbench(data_dir=self.tmp.name)
        self.p=self.w.project(self.w.projects()[0]['id'])
        self.env=patch.dict('os.environ',{'OPENAI_API_KEY':'synthetic-test-key'},clear=False);self.env.start()
    def tearDown(self):self.env.stop();self.tmp.cleanup()

    def test_staged_edits_commit_once_and_context_excludes_private_notes(self):
        self.p['notes']='private-note-not-sent';self.p=self.w.save_project(self.p)
        responses=[{'status':'completed','output':[call('set_element',{'element_id':'collimator','updates':{'focal_mm':20}})]},
                   {'status':'completed','output':[call('update_parameters',{'updates':{'reference_efl_mm':20}},'c2')]},answer('已调整为20mm。')]
        requests=[]
        def transport(payload,key):
            requests.append(copy.deepcopy(payload))
            self.assertEqual(self.w.project(self.p['id'])['version'],self.p['version'])
            self.assertFalse(payload['store']);self.assertFalse(payload['parallel_tool_calls'])
            self.assertNotIn('private-note-not-sent',json.dumps(payload))
            return responses.pop(0)
        result=ai.chat(self.w,self.p['id'],self.p['version'],'调整焦距',transport=transport)
        self.assertEqual(result['project']['version'],self.p['version']+1)
        self.assertEqual(result['project']['parameters']['reference_efl_mm'],20)
        self.assertEqual(next(e['focal_mm'] for e in result['project']['scene']['elements'] if e['id']=='collimator'),20)
        self.assertEqual(len(result['actions']),2)
        self.assertTrue(any(x.get('type')=='function_call_output' for x in requests[-1]['input']))

    def test_provider_failure_discards_prior_tool_edits(self):
        responses=[{'status':'completed','output':[call('update_parameters',{'updates':{'source_lumens':123}})]}]
        def transport(payload,key):
            if responses:return responses.pop()
            raise ai.AIError('synthetic provider failure')
        with self.assertRaises(ai.AIError):ai.chat(self.w,self.p['id'],1,'改亮度',transport=transport)
        self.assertEqual(self.w.project(self.p['id']),self.p)

    def test_concurrent_edit_not_overwritten(self):
        calls=0
        def transport(payload,key):
            nonlocal calls
            calls+=1
            if calls==1:return {'status':'completed','output':[call('update_parameters',{'updates':{'source_lumens':123}})]}
            newer=copy.deepcopy(self.p);newer['parameters']['source_lumens']=999
            self.w.save_project(newer)
            return answer('Done')
        with self.assertRaisesRegex(ai.AIError,'处理期间'):ai.chat(self.w,self.p['id'],1,'change',transport=transport)
        self.assertEqual(self.w.project(self.p['id'])['parameters']['source_lumens'],999)

    def test_unknown_tool_and_invalid_history(self):
        sequence=[{'status':'completed','output':[call('run_shell',{'cmd':'no'},'bad')]},answer('无法执行该工具。')]
        r=ai.chat(self.w,self.p['id'],1,'演示',transport=lambda p,k:sequence.pop(0))
        self.assertFalse(r['actions'][0]['success'])
        self.assertEqual(self.w.project(self.p['id']),self.p)
        with self.assertRaises(ai.AIError):ai.chat(self.w,self.p['id'],1,'test',history=[{'role':'system','content':'x'}])

    def test_missing_key_does_not_invent_reply(self):
        with patch.dict('os.environ',{'OPENAI_API_KEY':''}):
            self.assertFalse(ai.status(self.w)['configured'])
            with self.assertRaisesRegex(ai.AIError,'尚未配置'):ai.chat(self.w,self.p['id'],1,'test')
        self.assertEqual(self.w.project(self.p['id']),self.p)

    def test_incomplete_output_and_invalid_updates_are_not_saved(self):
        for response in ({'status':'incomplete','output':[]},{'output':[]},{'status':'in_progress','output':answer('not complete')['output']}):
            with self.assertRaises(ai.AIError):ai.chat(self.w,self.p['id'],1,'test',transport=lambda p,k:response)
        responses=[{'status':'completed','output':[call('update_parameters',{'updates':{'source_lumens':-2}})]},answer('输入不合法。')]
        r=ai.chat(self.w,self.p['id'],1,'test',transport=lambda p,k:responses.pop(0))
        self.assertFalse(r['actions'][0]['success'])
        self.assertEqual(self.w.project(self.p['id']),self.p)


if __name__=='__main__':unittest.main()

