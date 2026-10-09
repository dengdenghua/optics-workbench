import copy
import json
import math
from pathlib import Path
import tempfile
import unittest
from optics_workbench.calculations import calculate,template_parameters
from optics_workbench.core import Workbench

class CalculationTests(unittest.TestCase):
    def setUp(self):self.p=template_parameters('dlp')

    def test_lambertian_and_power_accounting(self):
        self.p.update(collection_half_angle_deg=30,source_lumens=1000,collimator_transmission=1,flyeye_transmission=1,prism_transmission=1,imager_efficiency=1,lens_transmission=1)
        r=calculate(self.p)
        self.assertAlmostEqual(r['power']['collection_fraction'],.25)
        self.assertAlmostEqual(r['power']['output_lumens'],250)
        self.assertAlmostEqual(r['collimator']['normal_axis_source_G_mm2_sr'],math.pi*2.5*1.2*.25)

    def test_zero_flux_and_efficiency_valid(self):
        for key in ('source_lumens','collimator_transmission','custom_collection_fraction'):
            p={**self.p,key:0,'source_model':'custom'}
            self.assertEqual(calculate(p)['power']['output_lumens'],0)

    def test_custom_collection_independent_of_half_angle(self):
        self.p.update(source_model='custom',custom_collection_fraction=.3)
        r=calculate(self.p)
        self.p['collection_half_angle_deg']=30
        self.assertEqual(r['power'],calculate(self.p)['power'])

    def test_flyeye_exact_rectangle_and_shortfall(self):
        self.p.update(cell_clear_width_mm=1,cell_clear_height_mm=.6,cell_efl_mm=4,relay_efl_mm=40,target_width_mm=10,target_height_mm=6,margin_mm=0)
        r=calculate(self.p)['flyeye'];self.assertTrue(r['covers_target_rectangle']);self.assertEqual(r['minimum_ideal_relay_efl_mm'],40)
        self.p['margin_mm']=.01;self.assertFalse(calculate(self.p)['flyeye']['covers_target_rectangle'])

    def test_tir_boundary_strict_and_transmission_direction(self):
        critical=math.degrees(math.asin(1/1.5))
        self.p.update(incidence_min_deg=critical,incidence_max_deg=critical,required_margin_deg=0)
        r=calculate(self.p)['prism'];self.assertFalse(r['meets_requested_margin']);self.assertTrue(r['at_requested_margin_boundary'])
        self.p.update(prism_behavior='transmit',incidence_min_deg=critical-4,incidence_max_deg=critical-3,required_margin_deg=2)
        self.assertTrue(calculate(self.p)['prism']['meets_requested_margin'])

    def test_pbs_never_claims_tir_success(self):
        self.p.update(prism_behavior='pbs',n_high=1,n_low=1.5)
        r=calculate(self.p);self.assertFalse(r['prism']['supported']);self.assertEqual(r['checks'][1]['status'],'unknown')

    def test_invalid_inputs_fail(self):
        for key,value in [('source_width_mm',0),('source_width_mm',True),('source_lumens',float('nan')),('collection_half_angle_deg',90),('n_high',1),('collimator_transmission',1.01),('columns',1.5),('cell_clear_width_mm',2),('incidence_min_deg',60)]:
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):calculate({**self.p,key:value})
        with self.assertRaises(ValueError):calculate({**self.p,'made_up':1})
        with self.assertRaises(ValueError):calculate({k:v for k,v in self.p.items() if k!='wavelength_nm'})

    def test_changed_input_changes_hash_not_input(self):
        original=copy.deepcopy(self.p);before=calculate(self.p)
        self.assertEqual(self.p,original)
        self.p['source_lumens']+=1
        self.assertNotEqual(before['input_hash'],calculate(self.p)['input_hash'])

class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name);self.w=Workbench(data_dir=self.base/'data')
    def tearDown(self):self.tmp.cleanup()

    def test_revision_persistence_and_stale_write(self):
        p=self.w.new_project(name='可迁移原型');old=copy.deepcopy(p)
        p['parameters']['source_lumens']=1234;p=self.w.save_project(p)
        self.assertEqual(p['version'],2)
        with self.assertRaisesRegex(ValueError,'另一个窗口'):self.w.save_project(old)
        reopened=Workbench(data_dir=self.base/'data');self.assertEqual(reopened.project(p['id'])['parameters']['source_lumens'],1234)
        with reopened.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM project_revisions WHERE project_id=?',(p['id'],)).fetchone()[0],2)

    def test_sync_preserves_projects_and_literal_search(self):
        p=self.w.new_project();self.w.sync();self.assertEqual(self.w.project(p['id']),p)
        self.assertEqual(self.w.library('演示 资料')['total'],1)
        self.assertEqual(self.w.library('%')['total'],0)

    def test_import_recalculates_ignores_forged_output(self):
        p=self.w.new_project();export=self.w.export_project(p['id'])
        export['calculation']['power']['output_lumens']=9999999
        imported=self.w.import_project(export)
        self.assertNotEqual(imported['id'],p['id']);self.assertEqual(imported['calculation'],p['calculation'])
        self.assertNotIn('paths',export['project'])

    def test_missing_component_migration(self):
        export=self.w.export_project(self.w.projects()[0]['id']);export['project']['selected_components']={'collimators':'device-on-another-machine'}
        p=self.w.import_project(export)
        self.assertEqual(p['selected_components'],{});self.assertIn('重新关联',p['notes'])

    def test_private_index_never_overwritten_by_accidental_demo(self):
        source=self.base/'inventory.json';source.write_text(json.dumps([dict(sha256='synthetic-id',files=[dict(path='private/example.md')],reading_status='registered_partial_review',review_records=[],bytes=1)]),encoding='utf8')
        config=self.base/'config.json';config.write_text(json.dumps(dict(data_dir='./private-db',coverage_file='./inventory.json')),encoding='utf8')
        w=Workbench(config_path=config);self.assertEqual(w.stats()['mode'],'local_private')
        with self.assertRaisesRegex(ValueError,'不会用演示'):Workbench(data_dir=self.base/'private-db')
        self.assertEqual(w.document('synthetic-id')['title'],'example.md')
        source.unlink()
        with self.assertRaises(ValueError):w.sync()
        self.assertEqual(w.stats()['documents'],1)

if __name__=='__main__':unittest.main()
