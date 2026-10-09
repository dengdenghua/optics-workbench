import copy
import json
import math
import unittest

from optics_workbench.calculations import template_parameters
from optics_workbench.scene import default_scene, trace_scene, validate_scene


def element(eid, kind, z, aperture=100, **extra):
    return dict(id=eid, kind=kind, label=eid, z_mm=z, y_mm=0, aperture_mm=aperture, width_mm=1, **extra)


def scene(*middle, source_y=0, source_height=1, screen_z=60, screen_height=100,
          points=3, fan=5, half_angle=3):
    source = element('source', 'source', 0, source_height)
    source['y_mm'] = source_y
    return dict(schema_version=1, units='mm',
                elements=[source, *middle, element('screen', 'screen', screen_z, screen_height)],
                rays=dict(half_angle_deg=half_angle, rays_per_point=fan, source_points=points, wavelength_nm=550))


class MathematicalRayTests(unittest.TestCase):
    def test_focal_plane_point_collimates_every_launch_angle(self):
        result = trace_scene(scene(element('lens', 'lens', 20, focal_mm=20), points=1))
        self.assertEqual(result['summary']['reached'], 5)
        for ray in result['rays']:
            hit, end = ray['points'][1:]
            self.assertAlmostEqual(hit['y_mm'], 20 * math.radians(ray['angle_deg']))
            self.assertAlmostEqual(end['y_mm'], hit['y_mm'])

    def test_off_axis_focal_source_has_parallel_tilted_bundle(self):
        result = trace_scene(scene(element('lens', 'lens', 20, focal_mm=20), source_y=.5, points=1))
        for ray in result['rays']:
            hit, end = ray['points'][1:]
            self.assertAlmostEqual((end['y_mm'] - hit['y_mm']) / 40, -.5 / 20)

    def test_finite_conjugates_form_inverted_two_times_image(self):
        # 1/30 + 1/60 = 1/20: all angles from each object point meet at -2*y.
        result = trace_scene(scene(element('lens', 'lens', 30, focal_mm=20), screen_z=90))
        self.assertEqual(result['summary']['reached'], 15)
        for ray in result['rays']:
            self.assertAlmostEqual(ray['points'][-1]['y_mm'], -2 * ray['source_y_mm'], places=12)

    def test_negative_lens_diverges_and_positive_lens_focuses(self):
        for focal, expected in [(-20, 2), (20, 0)]:
            with self.subTest(focal=focal):
                r = trace_scene(scene(element('lens', 'lens', 10, focal_mm=focal), source_y=1, points=1, fan=1, screen_z=30))
                self.assertAlmostEqual(r['rays'][0]['points'][-1]['y_mm'], expected)

    def test_decentered_lens_kick_uses_local_height(self):
        lens = element('lens', 'lens', 10, focal_mm=20)
        lens['y_mm'] = .5
        r = trace_scene(scene(lens, points=1, fan=1, screen_z=30))
        self.assertAlmostEqual(r['rays'][0]['points'][-1]['y_mm'], .5)

    def test_free_propagation_is_declared_paraxial_radian_not_tangent(self):
        r = trace_scene(scene(points=1, fan=3, half_angle=5, screen_z=100))
        y = r['rays'][-1]['points'][-1]['y_mm']
        self.assertAlmostEqual(y, 100 * math.radians(5))
        self.assertNotAlmostEqual(y, 100 * math.tan(math.radians(5)), places=4)

    def test_flyeye_lens_uses_cell_centre_instead_of_global_axis(self):
        fly = element('fly', 'flyeye', 10, focal_mm=10, pitch_mm=1)
        r = trace_scene(scene(fly, source_y=1.2, points=1, fan=1, screen_z=20))
        self.assertAlmostEqual(r['rays'][0]['points'][-1]['y_mm'], 1)
        fly['y_mm'] = .2
        r = trace_scene(scene(fly, source_y=1.4, points=1, fan=1, screen_z=20))
        self.assertAlmostEqual(r['rays'][0]['points'][-1]['y_mm'], 1.2)

    def test_flyeye_exact_boundary_has_declared_half_open_ownership(self):
        for source_y, expected in [(.5, 1), (-.5, 0)]:
            r = trace_scene(scene(element('fly', 'flyeye', 10, focal_mm=10, pitch_mm=1),
                                  source_y=source_y, points=1, fan=1, screen_z=20))
            self.assertAlmostEqual(r['rays'][0]['points'][-1]['y_mm'], expected)

    def test_prism_fold_does_not_fake_snell_or_change_unfolded_trace(self):
        s = scene(element('prism', 'prism', 10, bend_deg=0))
        straight = trace_scene(s)
        s['elements'][1]['bend_deg'] = 90
        folded = trace_scene(s)
        self.assertEqual(straight['rays'], folded['rays'])
        self.assertEqual(straight['summary'], folded['summary'])

    def test_blocked_rays_stop_at_first_aperture(self):
        r = trace_scene(scene(element('stop', 'aperture', 10, aperture=.5), points=1, half_angle=3))
        self.assertEqual(r['summary']['reached'], 1)
        self.assertEqual(r['summary']['blocked'], 4)
        for ray in r['rays']:
            if ray['status'] == 'blocked':
                self.assertEqual(ray['blocked_by'], 'stop')
                self.assertEqual([p['element_id'] for p in ray['points']], ['source', 'stop'])

    def test_aperture_rim_included_but_real_excess_blocked(self):
        for y, status in [(1, 'reached'), (1 + 1e-6, 'blocked')]:
            r = trace_scene(scene(element('stop', 'aperture', 10, aperture=2), source_y=y, points=1, fan=1))
            self.assertEqual(r['rays'][0]['status'], status)

    def test_decentered_screen_and_no_hits_null_extent(self):
        s = scene(source_y=1, points=1, fan=1, screen_height=.2)
        r = trace_scene(s)
        self.assertEqual(r['summary']['reached'], 0)
        self.assertIsNone(r['summary']['screen_min_y_mm'])
        self.assertIsNone(r['summary']['screen_max_y_mm'])
        self.assertEqual(r['rays'][0]['blocked_by'], 'screen')
        s['elements'][-1]['y_mm'] = 1
        self.assertEqual(trace_scene(s)['summary']['reached'], 1)

    def test_source_sampling_and_counts_are_not_flux(self):
        r = trace_scene(scene(source_y=2, source_height=2, points=3, fan=3, half_angle=0))
        self.assertEqual(sorted(set(x['source_y_mm'] for x in r['rays'])), [1, 2, 3])
        self.assertEqual(r['summary']['launched'], 9)
        self.assertNotIn('efficiency', r['summary'])
        self.assertTrue(any('不是效率' in s for s in r['assumptions']))

    def test_large_input_or_intermediate_slope_warns(self):
        for s in [scene(half_angle=6), scene(element('lens', 'lens', 10, focal_mm=.1), source_y=1, points=1, fan=1)]:
            self.assertTrue(any('5°' in w for w in trace_scene(s)['warnings']))


class SceneValidationTests(unittest.TestCase):
    def test_normalizes_sorting_default_decenter_without_mutation(self):
        s = scene(element('lens', 'lens', 20, focal_mm=20))
        del s['elements'][1]['y_mm']
        s['elements'].reverse()
        before = copy.deepcopy(s)
        normalized = validate_scene(s)
        self.assertEqual(s, before)
        self.assertEqual([x['id'] for x in normalized['elements']], ['source', 'lens', 'screen'])
        self.assertEqual(normalized['elements'][1]['y_mm'], 0)
        self.assertEqual(trace_scene(s), trace_scene(s))

    def test_unknown_fields_rejected_at_every_level(self):
        base = scene(element('lens', 'lens', 20, focal_mm=20))
        for location, key in [('top', 'trace_energy'), ('rays', 'seed'), ('element', 'tilt_deg'), ('element', 'pitch_mm')]:
            s = copy.deepcopy(base)
            target = s if location == 'top' else s['rays'] if location == 'rays' else s['elements'][1]
            target[key] = 1
            with self.subTest(location=location, key=key), self.assertRaises(ValueError):
                trace_scene(s)

    def test_finite_numeric_bounds_bool_and_integer_types(self):
        for key, bad in [('half_angle_deg', -1), ('half_angle_deg', 15.01), ('half_angle_deg', True),
                         ('source_points', 0), ('source_points', 10), ('source_points', 3.),
                         ('rays_per_point', 22), ('rays_per_point', False),
                         ('wavelength_nm', 0), ('wavelength_nm', math.inf), ('wavelength_nm', math.nan),
                         ('wavelength_nm', 10 ** 500)]:
            s = scene();s['rays'][key] = bad
            with self.subTest(key=key, bad=str(bad)), self.assertRaises(ValueError):validate_scene(s)
        for key, bad in [('aperture_mm', 0), ('width_mm', -1), ('z_mm', -1), ('y_mm', 1000001),
                         ('z_mm', math.nan), ('focal_mm', 0), ('focal_mm', .0001), ('focal_mm', math.inf)]:
            s = scene(element('lens', 'lens', 20, focal_mm=20));s['elements'][1][key] = bad
            with self.subTest(key=key, bad=bad), self.assertRaises(ValueError):validate_scene(s)

    def test_max_fan_size_and_units(self):
        s = scene(points=9, fan=21, half_angle=15)
        self.assertEqual(trace_scene(s)['summary']['launched'], 189)
        for key, bad in [('units', 'm'), ('schema_version', True), ('schema_version', 1.), ('schema_version', 2)]:
            broken = copy.deepcopy(s);broken[key] = bad
            with self.assertRaises(ValueError):validate_scene(broken)

    def test_structural_and_identifier_errors(self):
        variants = []
        for eid in ['中文', 'a b', 'a' * 65, '1bad']:
            s = scene();s['elements'][0]['id'] = eid;variants.append(s)
        s = scene();s['elements'][1]['id'] = 'source';variants.append(s)
        s = scene();s['elements'][1]['z_mm'] = 0;variants.append(s)
        s = scene();s['elements'][0]['kind'] = 'aperture';variants.append(s)
        s = scene();s['elements'][1]['kind'] = 'source';variants.append(s)
        s = scene();s['elements'][0]['label'] = '\n';variants.append(s)
        s = scene();del s['rays'];variants.append(s)
        s = scene();s['rays']['mystery'] = {};variants.append(s)
        s = scene();s['elements'][0][1] = 'nonstring-key';variants.append(s)
        s = scene();s['elements'] *= 17;variants.append(s)
        for s in variants:
            with self.subTest(scene=s), self.assertRaises(ValueError):validate_scene(s)

    def test_pitch_bend_and_kind_specific_requirements(self):
        for mid in [element('fly', 'flyeye', 10, focal_mm=10, pitch_mm=0),
                    element('prism', 'prism', 10, bend_deg=45),
                    element('lens', 'lens', 10), element('x', 'mirror', 10)]:
            with self.subTest(element=mid), self.assertRaises(ValueError):validate_scene(scene(mid))

    def test_both_public_defaults_are_finite_deterministic_and_reach_screen(self):
        for template in ('dlp', 'compact'):
            p = template_parameters(template);before = copy.deepcopy(p)
            s = default_scene(p);r = trace_scene(s)
            self.assertEqual(p, before)
            self.assertEqual(r, trace_scene(default_scene(p)))
            self.assertEqual(r['summary']['launched'], 15)
            self.assertGreater(r['summary']['reached'], 0)
            self.assertEqual(s['elements'][1]['z_mm'], p['reference_efl_mm'])
            self.assertEqual(s['elements'][1]['focal_mm'], p['reference_efl_mm'])
            self.assertLessEqual(s['rays']['half_angle_deg'], 3)
            self.assertNotEqual(s['rays']['half_angle_deg'], p['collection_half_angle_deg'])
            json.dumps(r, allow_nan=False)

    def test_width_and_wavelength_are_metadata_not_fake_optical_physics(self):
        s = scene(element('lens', 'lens', 20, focal_mm=20));r = trace_scene(s)
        s['elements'][1]['width_mm'] = 50;s['rays']['wavelength_nm'] = 450
        self.assertEqual(r['rays'], trace_scene(s)['rays'])


if __name__ == '__main__':unittest.main()
