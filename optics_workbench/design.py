"""Explicit receiving-plane chains and inspectable draft differences."""
import copy
import math

GROUPS = ('R', 'G', 'B')
STAGES = (
    ('collimator', '准直组', 'collimator_transmission', '准直组出口'),
    ('flyeye', '复眼', 'flyeye_transmission', '复眼出口'),
    ('prism', '棱镜', 'prism_transmission', '棱镜出口'),
    ('imager', '成像器件', 'imager_efficiency', '成像器件出口'),
    ('lens', '投影镜头', 'lens_transmission', '屏幕'),
)
PARAMETER_KEYS = {s[2] for s in STAGES}


def text(value, name, limit=500):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError(name + '应为非空文本')
    return value


def efficiency(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value) or not 0 <= value <= 1:
        raise ValueError('光学效率应在0–1之间')
    return value


def validate_chain(chain, receiving_plane):
    if not isinstance(chain, dict) or set(chain) != {'schema_version', 'stages'} or type(chain['schema_version']) is not int or chain['schema_version'] != 1:
        raise ValueError('分段预算链格式或版本错误')
    if not isinstance(chain['stages'], list) or not 1 <= len(chain['stages']) <= 12:
        raise ValueError('分段预算链需要1–12个阶段')
    current = receiving_plane
    ids = set()
    for s in chain['stages']:
        required = {'id', 'name', 'from_plane', 'to_plane', 'efficiencies', 'basis', 'status', 'reference'}
        if not isinstance(s, dict) or set(s) - required - {'parameter_key'} or not required <= s.keys():
            raise ValueError('预算阶段字段错误')
        for k in ('id', 'name', 'from_plane', 'to_plane', 'reference'):
            text(s[k], k, 500 if k == 'reference' else 200)
        if s['id'] in ids or s['to_plane'] == s['from_plane'] or s['from_plane'] != current or current == '屏幕':
            raise ValueError('预算阶段重复、接收面不连续或起点不符')
        ids.add(s['id']); current = s['to_plane']
        if s['basis'] != 'optical_only':
            raise ValueError('分段链只计光学损失，时序占空比另计一次')
        if s['status'] not in ('assumed', 'specified', 'measured'):
            raise ValueError('阶段证据状态错误')
        rates = s['efficiencies']
        if not isinstance(rates, dict) or set(rates) != set(GROUPS):
            raise ValueError('每段需要完整RGB效率')
        for v in rates.values(): efficiency(v)
        if s.get('parameter_key') is not None and s['parameter_key'] not in PARAMETER_KEYS:
            raise ValueError('阶段关联了未知标量参数')
    if current != '屏幕': raise ValueError('预算链末端应为屏幕')
    return copy.deepcopy(chain)


def resolve_chain(budget, parameters=None):
    chain = budget.get('downstream_chain')
    totals = dict.fromkeys(GROUPS, 1.)
    stages = []
    if not chain:
        return dict(mode='scalar', efficiencies=dict.fromkeys(GROUPS, budget['downstream_efficiency']), stages=[])
    validate_chain(chain, budget['receiving_plane'])
    for original in chain['stages']:
        s = copy.deepcopy(original)
        key = s.get('parameter_key')
        if key:
            if not isinstance(parameters, dict) or key not in parameters:
                raise ValueError('关联预算链需要当前原型parameters，不能使用旧效率快照')
            rate = efficiency(parameters[key])
            s['efficiencies'] = dict.fromkeys(GROUPS, rate)
        for g in GROUPS: totals[g] *= s['efficiencies'][g]
        s['cumulative_efficiencies'] = dict(totals)
        stages.append(s)
    return dict(mode='chain', efficiencies=totals, stages=stages)


def chain_template(parameters, receiving_plane, start_stage):
    if not isinstance(parameters, dict): raise ValueError('分段链模板需要当前原型parameters')
    text(receiving_plane, '输入接收面', 200)
    if start_stage not in {s[0] for s in STAGES}: raise ValueError('请选择输入面后第一个光学阶段')
    stages = []; current = receiving_plane
    for ident, name, key, end in STAGES:
        if not stages and ident != start_stage: continue
        rate = efficiency(parameters.get(key))
        stages.append(dict(id=ident, name=name, from_plane=current, to_plane=end,
                           efficiencies=dict.fromkeys(GROUPS, rate), parameter_key=key,
                           basis='optical_only', status='assumed', reference='当前原型参数：' + key + '；接收面和已包含损失需确认'))
        current = end
    return validate_chain(dict(schema_version=1, stages=stages), receiving_plane)


def differences(before, after, limit=120):
    rows = []
    def walk(a, b, path):
        if a == b: return
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(a.keys() | b.keys()): walk(a.get(key), b.get(key), path + ('.' if path else '') + key)
        elif isinstance(a, list) and isinstance(b, list):
            for i in range(max(len(a), len(b))): walk(a[i] if i < len(a) else None, b[i] if i < len(b) else None, path + '[' + str(i) + ']')
        else: rows.append(dict(path=path, before=a, after=b))
    walk(before, after, '')
    return dict(items=rows[:limit], total=len(rows), truncated=len(rows) > limit)
