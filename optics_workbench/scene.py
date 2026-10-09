"""Deterministic meridional, first-order ray fans for editable optical prototypes.

Coordinates are millimetres along an *unfolded* axis. Ray slope u is the paraxial
angle in radians: propagation y += distance*u, thin lens u -= (y-centre)/f.
This is neither a lens prescription nor radiometric/non-sequential ray tracing.
"""
import math
import re

from .calculations import validate as validate_parameters


KINDS = frozenset(('source', 'lens', 'flyeye', 'prism', 'aperture', 'screen'))
COMMON = frozenset(('id', 'kind', 'label', 'z_mm', 'y_mm', 'aperture_mm', 'width_mm'))
EXTRA = {'lens': {'focal_mm'}, 'flyeye': {'focal_mm', 'pitch_mm'}, 'prism': {'bend_deg'}}
COMFORT_RAD = math.radians(5)
MIN_LENGTH = 1e-6
MAX_LENGTH = 1e6


def _object(value, name):
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ValueError(name + ' 必须是使用字符串键的对象')
    return value


def _keys(value, allowed, required, name):
    _object(value, name)
    unknown = set(value) - set(allowed)
    missing = set(required) - set(value)
    if unknown:
        raise ValueError(name + ' 未知字段：' + ', '.join(sorted(unknown)))
    if missing:
        raise ValueError(name + ' 缺少字段：' + ', '.join(sorted(missing)))


def _number(value, name, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(name + ' 必须是有限数字')
    try:
        finite = math.isfinite(value)
    except OverflowError:
        finite = False
    if not finite or not low <= value <= high:
        raise ValueError(name + f' 必须是 {low:g} 至 {high:g} 范围内的有限数字')
    return float(value)


def _integer(value, name, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(name + f' 必须是 {low} 至 {high} 的整数')
    return value


def validate_scene(scene):
    """Return a new normalized scene; reject unknown fields and ambiguous planes.

    Only ``y_mm`` is optional (default zero). z planes must be distinct. Element
    order in input is immaterial, but source/screen must bound the sorted axis.
    width_mm is only a drawing width; aperture_mm is the full meridional opening.
    """
    top = {'schema_version', 'units', 'elements', 'rays'}
    _keys(scene, top, top, 'scene')
    if type(scene['schema_version']) is not int or scene['schema_version'] != 1:
        raise ValueError('不支持的 scene.schema_version')
    if scene['units'] != 'mm':
        raise ValueError('scene.units 必须为 mm')
    raw_elements = scene['elements']
    if not isinstance(raw_elements, list) or not 2 <= len(raw_elements) <= 32:
        raise ValueError('scene.elements 应有 2 至 32 个元件')
    elements = []
    ids = set()
    for raw in raw_elements:
        _object(raw, 'element')
        kind = raw.get('kind')
        if not isinstance(kind, str) or kind not in KINDS:
            raise ValueError('未知元件 kind')
        allowed = COMMON | EXTRA.get(kind, set())
        _keys(raw, allowed, allowed - {'y_mm'}, 'element')
        eid = raw['id']
        if not isinstance(eid, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,63}', eid):
            raise ValueError('元件 id 必须是 1–64 位 ASCII 标识符')
        if eid in ids:
            raise ValueError('元件 id 重复：' + eid)
        ids.add(eid)
        label = raw['label']
        if not isinstance(label, str) or not 1 <= len(label.strip()) <= 120 or any(ord(c) < 32 or ord(c) == 127 for c in label):
            raise ValueError('元件 label 应为 1–120 字符的非空单行文字')
        e = dict(id=eid, kind=kind, label=label.strip(),
                 z_mm=_number(raw['z_mm'], eid + '.z_mm', 0, 1e7),
                 y_mm=_number(raw.get('y_mm', 0), eid + '.y_mm', -MAX_LENGTH, MAX_LENGTH),
                 aperture_mm=_number(raw['aperture_mm'], eid + '.aperture_mm', MIN_LENGTH, MAX_LENGTH),
                 width_mm=_number(raw['width_mm'], eid + '.width_mm', MIN_LENGTH, MAX_LENGTH))
        if kind in ('lens', 'flyeye'):
            e['focal_mm'] = _number(raw['focal_mm'], eid + '.focal_mm', -MAX_LENGTH, MAX_LENGTH)
            if abs(e['focal_mm']) < .001:
                raise ValueError(eid + '.focal_mm 的绝对值须至少为 0.001 mm')
        if kind == 'flyeye':
            e['pitch_mm'] = _number(raw['pitch_mm'], eid + '.pitch_mm', MIN_LENGTH, MAX_LENGTH)
        if kind == 'prism':
            bend = _number(raw['bend_deg'], eid + '.bend_deg', 0, 90)
            if bend not in (0., 90.):
                raise ValueError(eid + '.bend_deg 仅支持 0 或 90 度的理想显示折转')
            e['bend_deg'] = bend
        elements.append(e)
    elements.sort(key=lambda e: e['z_mm'])
    if len({e['z_mm'] for e in elements}) != len(elements):
        raise ValueError('元件 z_mm 必须互异，不能有次序不明的重合平面')
    kinds = [e['kind'] for e in elements]
    if kinds.count('source') != 1 or kinds[0] != 'source' or kinds.count('screen') != 1 or kinds[-1] != 'screen':
        raise ValueError('按 z 排序后必须恰有一个首端 source 和一个末端 screen')
    ray_keys = {'half_angle_deg', 'rays_per_point', 'source_points', 'wavelength_nm'}
    r = scene['rays']
    _keys(r, ray_keys, ray_keys, 'rays')
    rays = dict(half_angle_deg=_number(r['half_angle_deg'], 'half_angle_deg', 0, 15),
                rays_per_point=_integer(r['rays_per_point'], 'rays_per_point', 1, 21),
                source_points=_integer(r['source_points'], 'source_points', 1, 9),
                wavelength_nm=_number(r['wavelength_nm'], 'wavelength_nm', 1, 1e6))
    return dict(schema_version=1, units='mm', elements=elements, rays=rays)


def default_scene(parameters):
    """Seed a symbolic layout from scalar inputs without modifying that budget.

    Only a small meridional fan is sampled, irrespective of the scalar collection
    cone (65 degrees in the public demo). Aligned centre rays ensure the normal
    demonstration has nonzero arrivals; this is not a throughput prediction.
    Out-of-range geometry is rejected rather than silently scaling physical units.
    """
    p = validate_parameters(parameters)
    f = p['reference_efl_mm']
    cell_f = p['cell_efl_mm']
    relay_f = p['relay_efl_mm']
    half_angle = min(3., p['output_half_angle_y_deg'])
    source_height = p['source_height_mm']
    span = p['rows'] * p['pitch_y_mm']
    bundle = source_height + 2 * f * math.radians(half_angle)
    clear = max(span, bundle * 1.2, p['target_height_mm'] * 2)
    fly1 = f + max(f, 2 * cell_f)
    fly2 = fly1 + cell_f
    relay = fly2 + relay_f
    screen = relay + relay_f

    def element(eid, kind, label, z, aperture, width, **extra):
        return dict(id=eid, kind=kind, label=label, z_mm=z, y_mm=0., aperture_mm=aperture, width_mm=width, **extra)

    scene = dict(schema_version=1, units='mm', elements=[
        element('source', 'source', '有限光源 · 近轴采样', 0., source_height, 1.),
        element('collimator', 'lens', '准直薄透镜', f, clear, 2., focal_mm=f),
        element('flyeye1', 'flyeye', '第一复眼 · 单截面', fly1, span, 1., focal_mm=cell_f, pitch_mm=p['pitch_y_mm']),
        element('flyeye2', 'flyeye', '第二复眼 · 单截面', fly2, span, 1., focal_mm=cell_f, pitch_mm=p['pitch_y_mm']),
        element('relay', 'lens', '中继薄透镜', relay, clear, 2., focal_mm=relay_f),
        element('prism', 'prism', '棱镜 · 理想显示折转', relay + .45 * relay_f, clear, 4., bend_deg=0 if p['prism_behavior'] == 'transmit' else 90),
        element('screen', 'screen', '目标面', screen, p['target_height_mm'], 1.),
    ], rays=dict(half_angle_deg=half_angle, rays_per_point=5, source_points=3, wavelength_nm=p['wavelength_nm']))
    return validate_scene(scene)


def _samples(half_span, count):
    return [0.] if count == 1 else [(2 * i / (count - 1) - 1) * half_span for i in range(count)]


def _outside(local_y, half_aperture):
    # Include the aperture rim, allowing only a few floating-point ulps at it.
    tolerance = max(math.ulp(half_aperture) * 4, 1e-12)
    return abs(local_y) > half_aperture and not math.isclose(abs(local_y), half_aperture, rel_tol=0., abs_tol=tolerance)


def trace_scene(scene):
    """Trace a deterministic, unweighted paraxial fan through validated planes.

    Flyeye cells have centres y_mm + k*pitch_mm and half-open ownership
    [-pitch/2, pitch/2); an exact upper boundary belongs to the next cell.
    Each array's overall aperture may clip a cell. No diffraction or fill factor.
    Prism bend_deg changes only the display fold, never the unfolded ray state.
    """
    s = validate_scene(scene)
    source = s['elements'][0]
    settings = s['rays']
    rays = []
    screen_hits = []
    steep = False
    for si, offset in enumerate(_samples(source['aperture_mm'] / 2, settings['source_points'])):
        start_y = source['y_mm'] + offset
        for ai, angle in enumerate(_samples(settings['half_angle_deg'], settings['rays_per_point'])):
            y, z, slope = start_y, source['z_mm'], math.radians(angle)
            steep = steep or abs(slope) > COMFORT_RAD
            points = [dict(z_mm=z, y_mm=y, element_id=source['id'])]
            ray = dict(id=f'r{si}_{ai}', source_y_mm=start_y, angle_deg=angle, points=points, status='reached', blocked_by=None)
            for e in s['elements'][1:]:
                y += (e['z_mm'] - z) * slope
                z = e['z_mm']
                if not math.isfinite(y):
                    raise ValueError('光线坐标超出有限计算范围')
                points.append(dict(z_mm=z, y_mm=y, element_id=e['id']))
                local_y = y - e['y_mm']
                if _outside(local_y, e['aperture_mm'] / 2):
                    ray['status'], ray['blocked_by'] = 'blocked', e['id']
                    break
                if e['kind'] == 'lens':
                    slope -= local_y / e['focal_mm']
                elif e['kind'] == 'flyeye':
                    cell = math.floor(local_y / e['pitch_mm'] + .5)
                    slope -= (local_y - cell * e['pitch_mm']) / e['focal_mm']
                if not math.isfinite(slope):
                    raise ValueError('光线斜率超出有限计算范围')
                steep = steep or abs(slope) > COMFORT_RAD
            if ray['status'] == 'reached':
                screen_hits.append(y)
            rays.append(ray)
    warnings = []
    if steep:
        warnings.append('存在超过约 5° 的输入或中间近轴斜率；这是超出舒适小角范围的线性外推，不能据此确认实际光路。')
    blocked = len(rays) - len(screen_hits)
    if blocked:
        warnings.append(f'{blocked} 条采样光线在元件孔径或目标面处终止；光线条数比不是能量效率。')
    if not screen_hits:
        warnings.append('当前采样没有光线到达目标面，请检查布局、孔径、位置和焦距。')
    return dict(kind='paraxial_ray_fan', scene=s, rays=rays,
                summary=dict(launched=len(rays), reached=len(screen_hits), blocked=blocked,
                             screen_min_y_mm=min(screen_hits) if screen_hits else None,
                             screen_max_y_mm=max(screen_hits) if screen_hits else None),
                warnings=warnings,
                assumptions=[
                    '采用空气 n=1 的单个子午截面、薄透镜与展开轴近似；斜率 u=θ（弧度），传播 y+=距离×u，透镜 u-=(y-中心)/f。',
                    '近轴小角光扇仅作几何起算；默认少量光线不代表预算中的 65° 等大角度收集锥，也不模拟全部二维场点。',
                    '复眼为节距规则、中心位于 y_mm+k×pitch_mm 的理想薄透镜单元；边界归右侧单元，整体孔径可截断边缘单元。',
                    'aperture_mm 是完整子午孔径，边缘包含在内；width_mm 只控制符号宽度，不能当镜片厚度或制造面形。',
                    '棱镜只支持显示中的理想 0°/90° 折转；展开轴计算不作 Snell 折射、TIR/PBS、膜系或偏振判断。',
                    '光线无辐射权重，命中数/发射数不是效率、EE、均匀性或概率；不包含像差、衍射、散射、相干、热和公差统计。',
                    'wavelength_nm 仅为波长标记，未提供色散或波长相关焦距；焦距由场景直接输入。',
                    '场景与标量预算分别编辑；本结果不启动 LightTools/Zemax，不构成已验证处方或新实测。',
                ])
