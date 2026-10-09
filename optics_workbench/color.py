"""XYZ mixing, explicit RGB timing and conditional luminous-flux budgets.

Public defaults are synthetic. Personal workbook scenarios are loaded only from
the user's explicitly configured Skill assets by the shared store.
"""
import copy
import hashlib
import json
import math
from .design import validate_chain, resolve_chain

GROUPS = ('R', 'G', 'B')
P3 = ((.68, .32), (.265, .69), (.15, .06))
REC709 = ((.64, .33), (.30, .60), (.15, .06))


def number(v, name, lo=0, hi=1e12, positive=False):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not lo <= v <= hi or (positive and v <= 0):
        raise ValueError(name + ' 需要符合范围的有限数字')
    return v


def keys(obj, allowed, name):
    if not isinstance(obj, dict) or set(obj)-set(allowed):
        raise ValueError(name + ' 类型错误或包含未知字段')


def xy(x, y):
    number(x, 'x', hi=1); number(y, 'y', lo=1e-8, hi=1)
    if x+y > 1+1e-12: raise ValueError('色坐标 x+y 不能大于1')
    return x, y


def validate(data):
    keys(data, {'schema_version','sources','target_x','target_y','available_angle_deg','timing','allocation','angles_deg','receiving_plane','downstream_efficiency','screen_area_m2','screen_gain','provenance','downstream_chain'}, '配色预算')
    if data.get('schema_version') != 1 or isinstance(data.get('schema_version'), bool): raise ValueError('配色预算版本应为1')
    d=copy.deepcopy(data); xy(d.get('target_x'),d.get('target_y'))
    if d.get('timing') not in ('sequential','simultaneous'): raise ValueError('请声明时序或同时点亮')
    if d.get('allocation') not in ('solve','manual'): raise ValueError('请选择求解或手动分配')
    number(d.get('available_angle_deg'),'有效角度',hi=360,positive=True)
    keys(d.get('angles_deg'),GROUPS,'RGB角度')
    if set(d['angles_deg'])!=set(GROUPS):raise ValueError('请提供全部RGB角度')
    for g in GROUPS:number(d['angles_deg'][g],g+'角度',hi=360)
    if d['allocation']=='manual' and d['timing']=='sequential' and sum(d['angles_deg'].values())>d['available_angle_deg']+1e-8:
        raise ValueError('RGB有效角度总和超过已扣消隐的可用角度')
    if not isinstance(d.get('receiving_plane'),str) or not 1<=len(d['receiving_plane'])<=200:raise ValueError('请声明输入光通量所在接收面')
    number(d.get('downstream_efficiency'),'接收面到屏幕效率',hi=1)
    if 'downstream_chain' in d:
        validate_chain(d['downstream_chain'], d['receiving_plane'])
        if d['downstream_efficiency'] != 1: raise ValueError('启用分段链时总效率占位必须为1，防止重复乘损失')
    number(d.get('screen_area_m2'),'屏幕面积m²',hi=1e6,positive=True)
    number(d.get('screen_gain'),'方向性屏幕增益',hi=100,positive=True)
    provenance=d.get('provenance',{})
    keys(provenance,{'case_id','source_id','sheet','scope','source_sha256','reference_slug','baseline_hash'},'来源')
    if any(not isinstance(v,str) or len(v)>2000 for v in provenance.values()):raise ValueError('来源说明过长或类型错误')
    for key in ('source_sha256','baseline_hash'):
        if key in provenance and (len(provenance[key]) != 64 or any(c not in '0123456789abcdef' for c in provenance[key])):
            raise ValueError('来源文件或基线指纹应为SHA-256')
    d['provenance']=provenance
    if not isinstance(d.get('sources'),list) or not 3<=len(d['sources'])<=24:raise ValueError('提供3–24个光源，分组到RGB')
    names=set()
    for s in d['sources']:
        keys(s,{'name','group','x','y','input_kind','input_value','efficacy_lm_per_w','quantity','current_factor','thermal_factor','path_efficiency','electrical_w','time_basis','enabled','reference'},'光源')
        if not isinstance(s.get('name'),str) or not 1<=len(s['name'])<=120 or s['name'] in names:raise ValueError('光源名称应非空且唯一')
        names.add(s['name']);xy(s.get('x'),s.get('y'))
        if s.get('group') not in GROUPS or s.get('input_kind') not in ('lumens','optical_w','pump_w'):raise ValueError('光源分组或输入功率口径错误')
        if s.get('time_basis') not in ('CW','average'):raise ValueError('必须声明CW或全周期已平均输入')
        if not isinstance(s.get('enabled'),bool):raise ValueError('光源启用状态应为布尔值')
        number(s.get('input_value'),'单颗输入')
        number(s.get('efficacy_lm_per_w'),'光谱光效/泵浦转换系数',hi=1e6,positive=True)
        if s['input_kind']=='optical_w' and s['efficacy_lm_per_w']>683.002:raise ValueError('光谱lm/输出光学W不能超过明视觉最大光效；泵浦转换另选pump_w')
        number(s.get('quantity'),'颗数',hi=100000,positive=True)
        if not isinstance(s['quantity'],int):raise ValueError('颗数应为正整数')
        number(s.get('current_factor'),'电流修正',hi=100);number(s.get('thermal_factor'),'温度修正',hi=100);number(s.get('path_efficiency'),'前段效率',hi=1)
        if s.get('electrical_w') is not None:number(s['electrical_w'],'同工况单颗电功率',positive=True)
        if not isinstance(s.get('reference'),str) or len(s['reference'])>500:raise ValueError('光源来源定位过长或类型错误')
        if s['enabled'] and s['time_basis']=='average' and d['allocation']=='solve':raise ValueError('已平均输入不能直接反推CW时序；请用手动分配核对，或补充CW输入')
    return d


def default_budget():
    sources=[]
    for group,(x,y),lm in zip(GROUPS,REC709,(1000,2500,400)):
        sources.append(source(group,group,x,y,lm,'合成演示，不对应器件规格'))
    return dict(schema_version=1,sources=sources,target_x=.3127,target_y=.329,available_angle_deg=360,
                timing='sequential',allocation='solve',angles_deg=dict(R=120,G=120,B=120),
                receiving_plane='示例RGB共同接收面',downstream_efficiency=1.,screen_area_m2=1.,screen_gain=1.,
                provenance=dict(source_id='synthetic_demo',scope='合成演示；屏幕面积和效率为待确认假设'))


def source(name, group, x, y, lumens, reference=''):
    return dict(name=name,group=group,x=x,y=y,input_kind='lumens',input_value=lumens,efficacy_lm_per_w=300.,quantity=1,
                current_factor=1.,thermal_factor=1.,path_efficiency=1.,electrical_w=None,time_basis='CW',enabled=True,reference=reference)


def xyz(x,y,Y):return [x*Y/y,Y,(1-x-y)*Y/y]


def mixed(values):
    sums=[math.fsum(v[i] for v in values) for i in range(3)];total=math.fsum(sums)
    return dict(X=sums[0],Y=sums[1],Z=sums[2],x=sums[0]/total if total>0 else None,y=sums[1]/total if total>0 else None,lumens=sums[1])


def solve(matrix, rhs):
    work=[]
    for row,r in zip(matrix,rhs):
        scale=max(map(abs,row))
        if scale==0:raise ValueError('基色矩阵退化')
        work.append([v/scale for v in row]+[r/scale])
    for i in range(3):
        pivot=max(range(i,3),key=lambda k:abs(work[k][i]))
        if abs(work[pivot][i])<1e-11:raise ValueError('基色矩阵共线或过度病态，不能可靠求解白点')
        work[i],work[pivot]=work[pivot],work[i];divisor=work[i][i];work[i]=[v/divisor for v in work[i]]
        for j in range(3):
            if i!=j:
                f=work[j][i];work[j]=[a-f*b for a,b in zip(work[j],work[i])]
    return [row[3] for row in work]


def uv(p):
    x,y=p;den=-2*x+12*y+3
    return (4*x/den,9*y/den)


def area(poly):
    return abs(math.fsum(a[0]*b[1]-b[0]*a[1] for a,b in zip(poly,poly[1:]+poly[:1])))/2 if len(poly)>=3 else 0.


def intersection(subject, clip):
    poly=list(subject);signed=sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(clip,clip[1:]+clip[:1]));sign=1 if signed>=0 else -1
    for a,b in zip(clip,clip[1:]+clip[:1]):
        def side(p):return sign*((b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0]))
        out=[]
        if not poly:break
        prev=poly[-1];sp=side(prev)
        for curr in poly:
            sc=side(curr)
            if (sc>=0)!=(sp>=0):
                t=sp/(sp-sc);out.append((prev[0]+t*(curr[0]-prev[0]),prev[1]+t*(curr[1]-prev[1])))
            if sc>=0:out.append(curr)
            prev,sp=curr,sc
        poly=out
    return poly


def fingerprint(data):
    d=copy.deepcopy(data);d.pop('provenance',None)
    return hashlib.sha256(json.dumps(d,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def calculate(data, parameters=None):
    d=validate(data);rows=[];warnings=[];grouped=[]
    chain=resolve_chain(d,parameters)
    for s in d['sources']:
        multiplier=s['quantity']*s['current_factor']*s['thermal_factor'] if s['enabled'] else 0.
        emitted=s['input_value']*multiplier
        flux=emitted*(s['efficacy_lm_per_w'] if s['input_kind']!='lumens' else 1)*s['path_efficiency']
        optical=emitted if s['input_kind']=='optical_w' else None
        electric=s['electrical_w']*s['quantity'] if s['enabled'] and s['electrical_w'] is not None else 0. if not s['enabled'] else None
        valid_power=optical is None or electric is None or optical<=electric+1e-10
        if not valid_power:warnings.append(s['name']+'：光学W大于同工况电学W，电效率与热预算不可采用。')
        if s['time_basis']=='average' and s['enabled']:warnings.append(s['name']+'输入已按全周期平均，计算不再乘占空比；改时序须重新提供对应平均量。')
        rows.append(dict(name=s['name'],group=s['group'],input_lumens=flux,XYZ=xyz(s['x'],s['y'],flux),
                         optical_w=optical,electrical_w=electric,power_valid=valid_power,time_basis=s['time_basis'],enabled=s['enabled']))
    for g in GROUPS:
        values=[r['XYZ'] for r in rows if r['group']==g];m=mixed(values)
        if m['lumens']<=0:raise ValueError(g+'组接收面光通量必须大于0，无法建立三基色白点预算')
        grouped.append(dict(group=g,**m))
    effective=[dict(p,lumens=p['lumens']*(chain['efficiencies'][p['group']] if chain['mode']=='chain' else 1.)) for p in grouped]
    if d['allocation']=='solve' and any(p['lumens']<=0 for p in effective):
        raise ValueError('逐色后段损失使RGB组输出为零，不能求解屏幕白点')
    matrix=[[p['x']/p['y'] for p in effective],[1.,1.,1.],[(1-p['x']-p['y'])/p['y'] for p in effective]]
    rhs=[d['target_x']/d['target_y'],1.,(1-d['target_x']-d['target_y'])/d['target_y']]
    fractions=solve(matrix,rhs)
    feasible=min(fractions)>=-1e-10
    if not feasible:
        if d['allocation']=='solve':raise ValueError('目标白点在三基色可实现范围外；负通道不能裁零后假称达到目标')
        warnings.append('目标白点在当前三基色范围外；手动输出仍可计算，但不能宣称达到目标。')
    if feasible:fractions=[max(0.,f)/sum(max(0.,v) for v in fractions) for f in fractions]
    if d['allocation']=='solve':
        if d['timing']=='sequential':
            white=d['available_angle_deg']/math.fsum(f/(p['lumens']/360) for f,p in zip(fractions,effective))
        else:white=min(p['lumens']/f for p,f in zip(effective,fractions) if f>1e-12)
        weights={p['group']:white*f/p['lumens'] for p,f in zip(effective,fractions)}
    else:weights={g:d['angles_deg'][g]/360 for g in GROUPS}
    for r,s in zip(rows,d['sources']):
        duty=weights[r['group']] if s['time_basis']=='CW' else 1.
        r['weight']=duty;r['average_lumens']=r['input_lumens']*duty
        r['screen_lumens']=r['average_lumens']*chain['efficiencies'][r['group']]
        r['average_electrical_w']=r['electrical_w']*duty if r['electrical_w'] is not None else None
        r['source_heat_w']=(r['electrical_w']-r['optical_w'])*duty if r['power_valid'] and r['electrical_w'] is not None and r['optical_w'] is not None else None
    output=mixed([xyz(s['x'],s['y'],r['average_lumens']) for s,r in zip(d['sources'],rows)])
    screen_output=mixed([xyz(s['x'],s['y'],r['screen_lumens']) for s,r in zip(d['sources'],rows)])
    cw=mixed([r['XYZ'] for r in rows])
    rgb=[dict(group=g,weight=weights[g],angle_deg=weights[g]*360,average_lumens=sum(r['average_lumens'] for r in rows if r['group']==g),target_Y_fraction=f) for g,f in zip(GROUPS,fractions)]
    complete_power=all(r['average_electrical_w'] is not None and r['power_valid'] for r in rows)
    electrical=sum(r['average_electrical_w'] for r in rows) if complete_power else None
    if electrical is None:warnings.append('电功率/工况未完整或不一致，不输出可信光源lm/电学W；屏幕光通量仍是指定条件预算。')
    heat=sum(r['source_heat_w'] for r in rows if r['enabled']) if all(r['source_heat_w'] is not None for r in rows if r['enabled']) else None
    flux=screen_output['lumens'];tri=[(p['x'],p['y']) for p in grouped];gamut={}
    for name,ref in [('DCI-P3',P3),('BT.709',REC709)]:
        gamut[name]={}
        for coords,transform in [('xy',lambda p:p),('uv_prime',uv)]:
            a=[transform(p) for p in tri];b=[transform(p) for p in ref];ref_area=area(b)
            gamut[name][coords]=dict(area_ratio=area(a)/ref_area,intersection_coverage=min(1.,area(intersection(a,b))/ref_area),reference=[list(p) for p in b])
    delta_uv=math.dist(uv((screen_output['x'],screen_output['y'])),uv((d['target_x'],d['target_y']))) if flux else None
    for stage in chain['stages']:
        stage['rgb_lumens']={g:sum(r['average_lumens'] for r in rows if r['group']==g)*stage['cumulative_efficiencies'][g] for g in GROUPS}
        stage['lumens']=sum(stage['rgb_lumens'].values())
    return dict(kind='color_brightness_budget',calculator_version='1.1',input_hash=hashlib.sha256(json.dumps(dict(budget=d,resolved_chain=chain),sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest(),
                input_total=cw,grouped=grouped,sources=rows,rgb=rgb,output=output,screen_output=screen_output,screen_lumens=flux,downstream=chain,
                mean_illuminance_lx=flux/d['screen_area_m2'],estimated_luminance_cd_m2=flux*d['screen_gain']/(math.pi*d['screen_area_m2']),
                average_electrical_w=electrical,screen_lm_per_electrical_w=flux/electrical if electrical else None,source_heat_w=heat,
                target_feasible=feasible,target_delta_uv_prime=delta_uv,gamut=gamut,warnings=warnings,
                assumptions=['同RGB组的光源共用时序/调光；先做XYZ相加，禁止lm加权直接平均xy。',
                             '前段效率必须与输入lm/W的接收面相匹配；温降/电流倍率是用户工况假设，不作器件通用规律。',
                             '分段链为逐色光学损失，目标白点在屏幕求解；各RGB组内假设不改变谱形。光谱选择性损失仍需逐谱模型。',
                             '面积比与三角形交集覆盖分别在xy、u′v′中计算；都不是色容积或色准。',
                             '屏幕lm为预测光通量，无ANSI/CVIA固定换算；lx与cd/m²按面积和给定方向性增益估算，非实测。',
                             '热预算仅在同工况电功率与源发出的光功率齐全时给出源级差值，不把光路损失全当吸热。'])
