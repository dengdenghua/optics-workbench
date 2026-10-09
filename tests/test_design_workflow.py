import copy
import json
import tempfile
import unittest
from unittest.mock import patch
from optics_workbench import ai
from optics_workbench.color import calculate, default_budget
from optics_workbench.core import Workbench
from optics_workbench.design import chain_template
from optics_workbench.calculations import template_parameters


class ChainMathTests(unittest.TestCase):
    def setUp(self):
        self.b=default_budget();self.p=template_parameters('dlp')

    def chain(self,rates):
        self.b['downstream_chain']=dict(schema_version=1,stages=[dict(id='lens',name='test optical stage',from_plane=self.b['receiving_plane'],to_plane='屏幕',
            efficiencies=rates,basis='optical_only',status='assumed',reference='synthetic fixture')])

    def test_common_loss_scales_output_once_and_keeps_timing(self):
        before=calculate(self.b);self.chain(dict(R=.5,G=.5,B=.5));r=calculate(self.b)
        self.assertAlmostEqual(r['screen_lumens'],before['screen_lumens']*.5)
        self.assertAlmostEqual(r['output']['lumens'],before['output']['lumens'])
        for a,b in zip(r['rgb'],before['rgb']):self.assertAlmostEqual(a['weight'],b['weight'])
        self.b['downstream_efficiency']=.5
        with self.assertRaisesRegex(ValueError,'重复'):calculate(self.b)

    def test_selective_loss_is_solved_at_screen_not_input_plane(self):
        before=calculate(self.b);self.chain(dict(R=.4,G=.9,B=.8));r=calculate(self.b)
        self.assertAlmostEqual(r['screen_output']['x'],self.b['target_x'],12)
        self.assertAlmostEqual(r['screen_output']['y'],self.b['target_y'],12)
        self.assertGreater(r['rgb'][0]['weight'],before['rgb'][0]['weight'])
        self.assertNotAlmostEqual(r['output']['x'],self.b['target_x'])
        self.assertAlmostEqual(sum(v['angle_deg'] for v in r['rgb']),360)
        self.assertAlmostEqual(r['downstream']['stages'][-1]['lumens'],r['screen_lumens'])
        self.b['allocation']='manual';self.b['angles_deg']={v['group']:v['angle_deg'] for v in before['rgb']}
        manual=calculate(self.b);self.assertGreater(manual['target_delta_uv_prime'],.001)

    def test_linked_stage_resolves_current_parameters_not_snapshot(self):
        self.b['downstream_chain']=chain_template(self.p,self.b['receiving_plane'],'lens')
        before=calculate(self.b,self.p);self.p['lens_transmission']/=2
        after=calculate(self.b,self.p)
        self.assertAlmostEqual(after['screen_lumens'],before['screen_lumens']/2)
        self.assertEqual(after['downstream']['stages'][0]['efficiencies']['R'],self.p['lens_transmission'])
        self.assertNotEqual(before['input_hash'],after['input_hash'])
        with self.assertRaisesRegex(ValueError,'快照'):calculate(self.b)

    def test_contiguous_plane_scope_and_no_collection_or_timing_stage(self):
        chain=chain_template(self.p,self.b['receiving_plane'],'prism')
        self.assertEqual([s['id'] for s in chain['stages']],['prism','imager','lens'])
        self.assertTrue(all(s['basis']=='optical_only' for s in chain['stages']))
        self.b['downstream_chain']=chain
        calculate(self.b,self.p)
        mutations=[lambda c:c['stages'][1].update(from_plane='unrelated'),lambda c:c['stages'][0].update(basis='timing'),
                   lambda c:c['stages'][0].update(parameter_key='custom_collection_fraction'),lambda c:c['stages'][0]['efficiencies'].update(R=True),
                   lambda c:c['stages'][-1].update(to_plane='not screen')]
        for fn in mutations:
            bad=copy.deepcopy(self.b);fn(bad['downstream_chain'])
            with self.assertRaises(ValueError):calculate(bad,self.p)

    def test_zero_channel_solve_fails_and_legacy_zero_efficiency_is_valid(self):
        self.b['downstream_efficiency']=0
        self.assertEqual(calculate(self.b)['screen_lumens'],0)
        self.b['downstream_efficiency']=1;self.chain(dict(R=0,G=1,B=1))
        with self.assertRaisesRegex(ValueError,'输出为零'):calculate(self.b)

    def test_simultaneous_screen_solution_respects_channel_limit(self):
        self.b['timing']='simultaneous';self.chain(dict(R=.4,G=.9,B=.8));r=calculate(self.b)
        self.assertAlmostEqual(max(v['weight'] for v in r['rgb']),1)
        self.assertAlmostEqual(r['screen_output']['x'],self.b['target_x'],12)


class DesignWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.w=Workbench(data_dir=self.tmp.name);self.p=self.w.project(self.w.projects()[0]['id'])
    def tearDown(self):self.tmp.cleanup()

    def test_source_case_changes_and_fingerprint_survive_export_import(self):
        case=self.w.color_case('synthetic-rgb');b=case['budget']
        self.assertEqual(self.w.calculate_color(b)['source_context']['status'],'case_unchanged')
        b['sources'][0]['input_value']*=.9
        r=self.w.calculate_color(b);self.assertEqual(r['source_context']['status'],'case_modified')
        self.assertTrue(any(v['path']=='sources[0].input_value' for v in r['source_context']['changes']['items']))
        p=self.w.save_color(self.p['id'],1,b);q=self.w.import_project(self.w.export_project(p['id']))
        self.assertEqual(q['color_budget']['provenance'],b['provenance'])
        self.assertEqual(q['color_calculation']['source_context']['status'],'case_modified')

    def test_preview_and_linked_budget_are_atomic_and_not_saved(self):
        b=default_budget();b['downstream_chain']=self.w.chain_template(self.p['parameters'],b['receiving_plane'],'imager')
        preview=self.w.preview_design(self.p['id'],1,color_budget=b,parameter_updates={'lens_transmission':.5})
        self.assertEqual(self.w.project(self.p['id']),self.p)
        self.assertEqual(preview['draft']['color_calculation']['downstream']['stages'][-1]['efficiencies']['R'],.5)
        saved=self.w.apply_design(self.p['id'],1,color_budget=b,parameter_updates={'lens_transmission':.5})
        self.assertEqual(saved['color_calculation'],preview['draft']['color_calculation'])
        with self.assertRaises(ValueError):self.w.preview_design(self.p['id'],1,color_budget=b)

    def test_evidence_selection_is_exact_bounded_and_content_versioned(self):
        body='# fixture\n'+'\n'.join('private synthetic line '+str(i) for i in range(20))+'\nneedle target'
        with self.w.connect() as db:db.execute('INSERT INTO knowledge VALUES(?,?,?)',('fixture.md','fixture',body))
        r=self.w.search_evidence('needle')['items'][0]
        selected=self.w.selected_evidence([r['id']])[0]
        self.assertEqual(selected['excerpt'],r['excerpt'])
        self.assertNotIn('private synthetic line 1',selected['excerpt'])
        with self.w.connect() as db:db.execute('UPDATE knowledge SET body=? WHERE slug=?',(body+' changed','fixture.md'))
        with self.assertRaisesRegex(ValueError,'更新'):self.w.selected_evidence([r['id']])
        for ids in ([{}],['unknown'],['same','same']):
            with self.assertRaises(ValueError):self.w.selected_evidence(ids)

    def test_ai_preview_apply_once_and_concurrent_edit_is_not_overwritten(self):
        tool={'type':'function_call','name':'update_parameters','arguments':json.dumps({'updates':{'source_lumens':123}}),'call_id':'c1'}
        answer={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'草案已准备'}]}]}
        with patch.dict('os.environ',{'OPENAI_API_KEY':'synthetic-test-key'}):
            turns=[dict(status='completed',output=[tool]),answer]
            result=ai.chat(self.w,self.p['id'],1,'准备草案',preview=True,transport=lambda p,k:turns.pop(0))
        self.assertEqual(self.w.project(self.p['id']),self.p)
        self.assertEqual(result['draft']['parameters']['source_lumens'],123)
        saved=ai.apply_proposal(self.w,self.p['id'],1,result['proposal_id']);self.assertEqual(saved['version'],2)
        with self.assertRaises(ai.AIError):ai.apply_proposal(self.w,self.p['id'],1,result['proposal_id'])
        with patch.dict('os.environ',{'OPENAI_API_KEY':'synthetic-test-key'}):
            turns=[dict(status='completed',output=[tool]),answer]
            proposal=ai.chat(self.w,self.p['id'],2,'准备草案',preview=True,transport=lambda p,k:turns.pop(0))
        newer=copy.deepcopy(saved);newer['parameters']['source_lumens']=777;newer=self.w.save_project(newer)
        with self.assertRaises(ValueError):ai.apply_proposal(self.w,self.p['id'],2,proposal['proposal_id'])
        self.assertEqual(self.w.project(self.p['id']),newer)

    def test_ai_cannot_read_unselected_private_evidence(self):
        with self.w.connect() as db:db.execute('INSERT INTO knowledge VALUES(?,?,?)',('fixture.md','fixture','UNSELECTED_PRIVATE_SYNTHETIC_MARKER'))
        requests=[]
        outputs=[dict(status='completed',output=[dict(type='function_call',name='read_evidence',arguments=json.dumps({'evidence_id':'reference:fixture.md'}),call_id='c1')]),
                 dict(status='completed',output=[dict(type='message',content=[dict(type='output_text',text='未选择依据')])])]
        def transport(payload,key):requests.append(copy.deepcopy(payload));return outputs.pop(0)
        with patch.dict('os.environ',{'OPENAI_API_KEY':'synthetic-test-key'}):r=ai.chat(self.w,self.p['id'],1,'检查',transport=transport,preview=True)
        self.assertFalse(r['actions'][0]['success']);self.assertNotIn('UNSELECTED_PRIVATE_SYNTHETIC_MARKER',json.dumps(requests))
        self.assertEqual(self.w.project(self.p['id']),self.p)

    def test_ai_calculation_does_not_transmit_unselected_case_baseline(self):
        case=self.w.color_case('synthetic-rgb')
        p=self.w.save_color(self.p['id'],1,case['budget'])
        historical=copy.deepcopy(case)
        marker='UNSELECTED_HISTORICAL_BASELINE_ONLY'
        historical['budget']['sources'][0]['reference']=marker
        requests=[]
        outputs=[dict(status='completed',output=[dict(type='function_call',name='calculate_color_budget',arguments='{}',call_id='c1')]),
                 dict(status='completed',output=[dict(type='function_call',name='trace_design',arguments='{}',call_id='c2')]),
                 dict(status='completed',output=[dict(type='message',content=[dict(type='output_text',text='预算检查完成')])])]
        def transport(payload,key):requests.append(copy.deepcopy(payload));return outputs.pop(0)
        with patch.object(self.w,'color_case',return_value=historical),patch.dict('os.environ',{'OPENAI_API_KEY':'synthetic-test-key'}):
            self.assertIn(marker,json.dumps(self.w.calculate_color(p['color_budget'])))
            result=ai.chat(self.w,p['id'],2,'检查预算',preview=True,transport=transport)
        self.assertTrue(all(a['success'] for a in result['actions']))
        self.assertNotIn(marker,json.dumps(requests))
        self.assertEqual(self.w.project(p['id']),p)


if __name__=='__main__':unittest.main()
