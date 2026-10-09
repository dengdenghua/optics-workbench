import copy
import tempfile
import unittest
from optics_workbench.core import Workbench


class VisualStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.w=Workbench(data_dir=self.tmp.name)
        self.p=self.w.project(self.w.projects()[0]['id'])

    def tearDown(self):self.tmp.cleanup()

    def test_default_scene_is_readonly_until_save(self):
        scene=self.w.scene(self.p['id'])
        self.assertEqual(scene['version'],self.p['version'])
        self.assertEqual(self.w.project(self.p['id']),self.p)
        self.assertEqual(scene['trace']['kind'],'paraxial_ray_fan')
        self.assertNotIn('scene',self.p)

    def test_roundtrip_scene_revision_and_legacy_client(self):
        scene=self.w.scene(self.p['id'])['scene']
        p=self.w.save_scene(self.p['id'],1,scene)
        self.assertEqual(p['version'],2)
        legacy=copy.deepcopy(p);del legacy['scene']
        legacy['parameters']['source_lumens']=1234
        p=self.w.save_project(legacy)
        self.assertEqual(p['scene'],scene)
        exported=self.w.export_project(p['id'])
        imported=self.w.import_project(exported)
        self.assertEqual(imported['scene'],scene)
        self.assertNotEqual(imported['id'],p['id'])
        with self.w.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM project_revisions WHERE project_id=?',(p['id'],)).fetchone()[0],3)

    def test_atomic_invalid_and_stale_design(self):
        scene=self.w.scene(self.p['id'])['scene']
        with self.assertRaises(ValueError):
            self.w.apply_design(self.p['id'],1,scene=scene,parameter_updates={'source_lumens':-1})
        self.assertEqual(self.w.project(self.p['id']),self.p)
        changed=self.w.apply_design(self.p['id'],1,scene=scene,parameter_updates={'reference_efl_mm':20},note='合成试验')
        self.assertEqual(changed['version'],2)
        self.assertEqual(changed['parameters']['reference_efl_mm'],20)
        with self.assertRaises(ValueError):self.w.save_scene(self.p['id'],1,scene)
        with self.assertRaises(ValueError):self.w.save_scene(self.p['id'],True,scene)
        with self.assertRaises(ValueError):self.w.apply_design(self.p['id'],2,parameter_updates={'madeup':1})
        self.assertEqual(self.w.project(self.p['id']),changed)


if __name__=='__main__':unittest.main()
