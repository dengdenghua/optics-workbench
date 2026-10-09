import copy
import math
import tempfile
import unittest
from optics_workbench import ai
from optics_workbench.color import calculate, default_budget, source, xyz, mixed, area, intersection
from optics_workbench.color_cases import all_cases
from optics_workbench.core import Workbench
from unittest.mock import patch


class ColorMathTests(unittest.TestCase):
    def setUp(self): self.b=default_budget()

    def test_xyz_addition_is_not_lumen_weighted_xy(self):
        m=mixed([xyz(.6,.3,100),xyz(.15,.05,100)])
        self.assertAlmostEqual(m['x'],3/14);self.assertAlmostEqual(m['y'],3/35)
        self.assertNotAlmostEqual(m['x'],(.6+.15)/2)

    def test_white_point_and_angle_constraint(self):
        r=calculate(self.b)
        self.assertAlmostEqual(r['output']['x'],self.b['target_x'],12)
        self.assertAlmostEqual(r['output']['y'],self.b['target_y'],12)
        self.assertAlmostEqual(sum(v['angle_deg'] for v in r['rgb']),360)
        for v in r['rgb']:self.assertGreaterEqual(v['weight'],0)

    def test_spoke_loss_scales_white_flux_once(self):
        r=calculate(self.b);self.b['available_angle_deg']=348;s=calculate(self.b)
        self.assertAlmostEqual(s['output']['lumens']/r['output']['lumens'],348/360)
        self.assertAlmostEqual(sum(v['angle_deg'] for v in s['rgb']),348)

    def test_split_source_same_group_does_not_add_segments(self):
        r=calculate(self.b);s=copy.deepcopy(self.b['sources'][0]);s['input_value']/=2
        self.b['sources'][0]['input_value']/=2;s['name']='R two';self.b['sources'].append(s)
        q=calculate(self.b);self.assertAlmostEqual(r['output']['lumens'],q['output']['lumens'])
        self.assertEqual(len(q['rgb']),3);self.assertEqual(q['sources'][0]['weight'],q['sources'][3]['weight'])

    def test_average_input_is_not_timed_twice(self):
        self.b['allocation']='manual';self.b['angles_deg']=dict(R=60,G=180,B=120)
        cw=calculate(self.b)
        for s,r in zip(self.b['sources'],cw['sources']):s['input_value']=r['average_lumens'];s['time_basis']='average'
        q=calculate(self.b);self.assertAlmostEqual(q['output']['lumens'],cw['output']['lumens'])
        self.assertAlmostEqual(q['output']['x'],cw['output']['x'])
        self.b['allocation']='solve'
        with self.assertRaisesRegex(ValueError,'已平均'):calculate(self.b)

    def test_simultaneous_solution_respects_channel_limits(self):
        self.b['timing']='simultaneous';r=calculate(self.b)
        self.assertAlmostEqual(max(v['weight'] for v in r['rgb']),1)
        self.assertTrue(all(v['weight']<=1+1e-12 for v in r['rgb']))
        self.assertAlmostEqual(r['output']['x'],self.b['target_x'],12)

    def test_infeasible_white_is_rejected_not_clipped(self):
        self.b['target_x']=.8;self.b['target_y']=.1
        with self.assertRaisesRegex(ValueError,'负通道'):calculate(self.b)
        self.b['allocation']='manual';self.assertFalse(calculate(self.b)['target_feasible'])

    def test_singular_primaries_rejected(self):
        for s in self.b['sources']:s['x']=.3;s['y']=.3
        with self.assertRaisesRegex(ValueError,'共线'):calculate(self.b)

    def test_photometry_and_source_heat_use_output_optical_w(self):
        for s in self.b['sources']:s.update(input_kind='optical_w',input_value=2,efficacy_lm_per_w=200,electrical_w=10)
        self.b.update(allocation='manual',angles_deg=dict(R=120,G=120,B=120),downstream_efficiency=.5,screen_area_m2=2,screen_gain=1.2)
        r=calculate(self.b)
        self.assertAlmostEqual(r['output']['lumens'],400);self.assertAlmostEqual(r['screen_lumens'],200)
        self.assertAlmostEqual(r['mean_illuminance_lx'],100);self.assertAlmostEqual(r['estimated_luminance_cd_m2'],120/math.pi)
        self.assertAlmostEqual(r['average_electrical_w'],10);self.assertAlmostEqual(r['source_heat_w'],8)

    def test_inconsistent_electricity_and_pump_w_do_not_create_fake_heat(self):
        for s in self.b['sources']:s.update(input_kind='optical_w',input_value=2,electrical_w=1)
        r=calculate(self.b);self.assertIsNone(r['average_electrical_w']);self.assertIsNone(r['source_heat_w'])
        for s in self.b['sources']:s.update(input_kind='pump_w',electrical_w=10,efficacy_lm_per_w=1000)
        r=calculate(self.b);self.assertIsNone(r['source_heat_w'])
        self.assertTrue(all(s['optical_w'] is None for s in r['sources']))

    def test_polygon_coverage_and_area_ratio_are_distinct(self):
        small=[(0,0),(1,0),(0,1)];large=[(0,0),(2,0),(0,2)]
        self.assertEqual(area(intersection(large,small)),area(small))
        self.assertEqual(area(intersection(small,large)),area(small))
        self.assertEqual(area(large)/area(small),4)
        r=calculate(self.b)
        self.assertAlmostEqual(r['gamut']['BT.709']['xy']['intersection_coverage'],1)
        self.assertAlmostEqual(r['gamut']['BT.709']['uv_prime']['area_ratio'],1)

    def test_invalid_inputs_rejected(self):
        mutations=[lambda b:b.update(target_x=float('nan')),lambda b:b['sources'][0].update(quantity=True),lambda b:b['sources'][0].update(y=0),lambda b:b['sources'][0].update(input_kind='optical_w',efficacy_lm_per_w=1000),lambda b:b.update(extra=1),lambda b:b.update(allocation='manual',available_angle_deg=300)]
        for change in mutations:
            b=copy.deepcopy(self.b);change(b)
            with self.assertRaises(ValueError):calculate(b)


class ColorStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.w=Workbench(data_dir=self.tmp.name);self.p=self.w.project(self.w.projects()[0]['id'])
    def tearDown(self):self.tmp.cleanup()

    def test_old_project_default_is_unsaved_and_legacy_write_preserves_color(self):
        self.assertFalse(self.w.color_budget(self.p['id'])['saved']);self.assertEqual(self.w.project(self.p['id']),self.p)
        saved=self.w.save_color(self.p['id'],self.p['version'],default_budget())
        legacy=copy.deepcopy(saved);legacy.pop('color_budget');legacy.pop('color_calculation');legacy['name']='Legacy edit'
        newer=self.w.save_project(legacy);self.assertEqual(newer['color_budget'],saved['color_budget'])

    def test_import_recalculates_not_cached_result_and_preserves_scene(self):
        p=self.w.apply_design(self.p['id'],1,color_budget=default_budget(),scene=self.w.scene(self.p['id'])['scene'])
        exported=self.w.export_project(p['id']);exported['project']['color_calculation']={'fake':True}
        q=self.w.import_project(exported);self.assertEqual(q['color_calculation'],p['color_calculation']);self.assertEqual(q['scene'],p['scene'])
        self.assertNotEqual(p['id'],q['id'])

    def test_conflict_and_invalid_budget_are_atomic(self):
        p=self.w.save_color(self.p['id'],1,default_budget())
        with self.assertRaises(ValueError):self.w.apply_design(p['id'],1,color_budget=default_budget(),parameter_updates={'source_lumens':123})
        bad=default_budget();bad['target_y']=0
        with self.assertRaises(ValueError):self.w.apply_design(p['id'],2,color_budget=bad,parameter_updates={'source_lumens':123})
        self.assertEqual(self.w.project(p['id']),p)

    def test_public_cases_are_synthetic_and_unknown_case_is_error(self):
        self.assertEqual([c['id'] for c in all_cases()],['synthetic-rgb'])
        with self.assertRaises(ValueError):self.w.color_case('private-not-configured')

    def test_ai_color_edit_commits_once_or_discards_on_provider_failure(self):
        budget=default_budget();budget['available_angle_deg']=330
        call={'type':'function_call','name':'set_color_budget','arguments':__import__('json').dumps({'budget':budget}),'call_id':'color1'}
        answer={'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':'已复算'}]}]}
        with patch.dict('os.environ',{'OPENAI_API_KEY':'synthetic-test-key'}):
            turns=[{'status':'completed','output':[call]},answer]
            r=ai.chat(self.w,self.p['id'],1,'配色',transport=lambda p,k:turns.pop(0))
            self.assertEqual(r['project']['version'],2);self.assertEqual(r['project']['color_budget'],budget)
            count=0
            def fail(p,k):
                nonlocal count
                count+=1
                if count==1:return {'status':'completed','output':[call]}
                raise ai.AIError('synthetic failure')
            with self.assertRaises(ai.AIError):ai.chat(self.w,self.p['id'],2,'配色',transport=fail)
            self.assertEqual(self.w.project(self.p['id']),r['project'])
