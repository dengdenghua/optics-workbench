"""Analytical starting points, not optical ray tracing or acceptance tests.

All lengths are mm, angles degrees, wavelength nm, flux lumens. No proprietary
prescriptions or measured source data are included. Formulae are elementary
geometrical/phase-space relations with assumptions returned to the caller.
"""
import hashlib
import json
import math

DEFAULTS = dict(source_width_mm=2.5,source_height_mm=1.2,source_lumens=5000.,
 collection_half_angle_deg=65.,source_model='lambertian',custom_collection_fraction=.8,
 output_half_angle_x_deg=5.,output_half_angle_y_deg=5.,reference_efl_mm=15.,
 pitch_x_mm=1.,pitch_y_mm=.6,cell_clear_width_mm=1.,cell_clear_height_mm=.6,
 cell_efl_mm=4.,relay_efl_mm=48.,wavelength_nm=550.,columns=20,rows=24,
 target_width_mm=10.368,target_height_mm=5.832,margin_mm=.2,
 n_high=1.5,n_low=1.,incidence_min_deg=46.,incidence_max_deg=50.,required_margin_deg=2.,prism_behavior='reflect',
 collimator_transmission=.9,flyeye_transmission=.9,prism_transmission=.92,imager_efficiency=.64,lens_transmission=.9)

def number(value,key,minimum=0,maximum=None,positive=False,integer=False):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError(f'{key} 必须是有限数字')
    if (positive and value<=0) or value<minimum or (maximum is not None and value>maximum):
        raise ValueError(f'{key} 超出允许范围')
    if integer and (not isinstance(value,int) or value<1):raise ValueError(f'{key} 必须是正整数')
    return value

def validate(parameters):
    if not isinstance(parameters,dict):raise ValueError('parameters 必须是对象')
    extra=set(parameters)-set(DEFAULTS)
    if extra:raise ValueError('未知参数：'+', '.join(sorted(extra)))
    missing=set(DEFAULTS)-set(parameters)
    if missing:raise ValueError('缺少参数：'+', '.join(sorted(missing)))
    p=dict(parameters)
    for k,v in p.items():
        if k in ('source_model','prism_behavior'):continue
        number(v,k,positive=k not in ('source_lumens','margin_mm','required_margin_deg') and not k.endswith(('transmission','efficiency','fraction')) and not k.startswith('incidence_'))
    if p['source_model'] not in ('lambertian','custom'):raise ValueError('未知光源模型')
    if p['prism_behavior'] not in ('reflect','transmit','pbs'):raise ValueError('未知棱镜界面行为')
    for k in ('collection_half_angle_deg','output_half_angle_x_deg','output_half_angle_y_deg'):
        if not 0<p[k]<90:raise ValueError(k+' 应在 0° 与 90° 之间')
    for k in ('incidence_min_deg','incidence_max_deg'):number(p[k],k,maximum=90)
    if p['incidence_min_deg']>p['incidence_max_deg']:raise ValueError('最小内部入射角不能大于最大值')
    if p['prism_behavior']!='pbs' and p['n_high']<=p['n_low']:raise ValueError('临界角预算要求 n_high > n_low')
    for k in ('columns','rows'):number(p[k],k,integer=True,maximum=100000)
    for k in ('custom_collection_fraction','collimator_transmission','flyeye_transmission','prism_transmission','imager_efficiency','lens_transmission'):number(p[k],k,maximum=1)
    for a,b in (('cell_clear_width_mm','pitch_x_mm'),('cell_clear_height_mm','pitch_y_mm')):
        if p[a]>p[b]:raise ValueError('复眼有效单元尺寸不能大于节距')
    for k in ('source_width_mm','source_height_mm','reference_efl_mm','pitch_x_mm','pitch_y_mm','cell_efl_mm','relay_efl_mm','target_width_mm','target_height_mm'):
        number(p[k],k,maximum=1e6,positive=True)
    number(p['source_lumens'],'source_lumens',maximum=1e12)
    return p

def calculate(parameters):
    p=validate(parameters);rad=math.radians
    c=rad(p['collection_half_angle_deg']);ox=rad(p['output_half_angle_x_deg']);oy=rad(p['output_half_angle_y_deg'])
    wx,hy=p['source_width_mm'],p['source_height_mm']
    fx=wx/(2*math.tan(ox));fy=hy/(2*math.tan(oy))
    col=dict(axis_matched_output_width_mm=wx*math.sin(c)/math.sin(ox),axis_matched_output_height_mm=hy*math.sin(c)/math.sin(oy),
      source_axis_qx_mm=wx*math.sin(c),source_axis_qy_mm=hy*math.sin(c),
      first_order_focal_estimate_x_mm=fx,first_order_focal_estimate_y_mm=fy,first_order_common_focal_estimate_mm=max(fx,fy),
      normal_axis_source_G_mm2_sr=math.pi*wx*hy*math.sin(c)**2,
      reference_efl_output_half_angle_x_deg=math.degrees(math.atan(wx/(2*p['reference_efl_mm']))),
      reference_efl_output_half_angle_y_deg=math.degrees(math.atan(hy/(2*p['reference_efl_mm']))))
    mag=p['relay_efl_mm']/p['cell_efl_mm'];targetx=p['target_width_mm']+2*p['margin_mm'];targety=p['target_height_mm']+2*p['margin_mm']
    imagex=p['cell_clear_width_mm']*mag;imagey=p['cell_clear_height_mm']*mag
    coverx=imagex/targetx;covery=imagey/targety
    fly=dict(ideal_magnification=mag,projected_cell_width_mm=imagex,projected_cell_height_mm=imagey,
      target_with_margin_width_mm=targetx,target_with_margin_height_mm=targety,
      coverage_ratio_x=coverx,coverage_ratio_y=covery,covers_target_rectangle=min(coverx,covery)>=1-1e-12,
      minimum_ideal_relay_efl_mm=max(targetx/p['cell_clear_width_mm'],targety/p['cell_clear_height_mm'])*p['cell_efl_mm'],
      nominal_array_span_x_mm=p['columns']*p['pitch_x_mm'],nominal_array_span_y_mm=p['rows']*p['pitch_y_mm'],
      FN_x=p['cell_clear_width_mm']**2/(4*p['wavelength_nm']*1e-6*p['cell_efl_mm']),
      FN_y=p['cell_clear_height_mm']**2/(4*p['wavelength_nm']*1e-6*p['cell_efl_mm']))
    if p['prism_behavior']=='pbs':prism=dict(supported=False,note='PBS 需要膜系、内部角谱和偏振数据，本版本只使用手填通量效率。')
    else:
        critical=math.degrees(math.asin(p['n_low']/p['n_high']))
        clearance=p['incidence_min_deg']-critical if p['prism_behavior']=='reflect' else critical-p['incidence_max_deg']
        boundary=math.isclose(clearance,p['required_margin_deg'],rel_tol=0,abs_tol=1e-10)
        prism=dict(supported=True,critical_angle_deg=critical,intended_clearance_deg=clearance,required_margin_deg=p['required_margin_deg'],
          meets_requested_margin=clearance>p['required_margin_deg'] and not boundary,at_requested_margin_boundary=boundary,
          intended_behavior=p['prism_behavior'],minimum_incidence_deg=p['incidence_min_deg'],maximum_incidence_deg=p['incidence_max_deg'])
    collection=math.sin(c)**2 if p['source_model']=='lambertian' else p['custom_collection_fraction']
    flux=p['source_lumens'];total=1.;stages=[dict(name='光源',efficiency=1.,lumens=flux)]
    for name,e in [('角度收集',collection),('准直组',p['collimator_transmission']),('复眼',p['flyeye_transmission']),('棱镜',p['prism_transmission']),('成像器件',p['imager_efficiency']),('投影镜头',p['lens_transmission'])]:
        total*=e;flux*=e;stages.append(dict(name=name,efficiency=e,lumens=flux))
    checks=[dict(status='ok' if fly['covers_target_rectangle'] else 'attention',title='复眼几何覆盖',detail='按 m=f中继/f单元 计算；覆盖成立不代表均匀性或效率合格。'),
      dict(status='unknown' if not prism['supported'] else ('ok' if prism['meets_requested_margin'] else 'attention'),title='棱镜内部角度裕量',detail=prism.get('note','使用相对界面法线的内部角，不能用空气发散角或楔角替代。')),
      dict(status='ok' if p['reference_efl_mm']>=max(fx,fy) else 'attention',title='准直焦距起算',detail='仅理想薄透镜、源在焦面时的有限源角度估计；高 NA 仍需主平面、实际处方和光线复核。'),
      dict(status='unknown',title='照明效率与制造验证',detail='通量链使用输入的假设比例；未评价像差、偏振、相干、热、公差或杂散光。')]
    assumptions=['所有默认参数是演示假设，不是任何供应商器件的实测规格。',
      '准直的分轴扩展量匹配按空气 n=1 起算；薄透镜焦距是另一种起算关系，不输出透镜面形。',
      '复眼使用近轴重叠成像；有效单元尺寸、节距、EFL 和波长需分别核实。',
      '光源流明指进入收集预算前的量；角收集比例只乘一次，各下游透过率不应重复包含它。',
      '通量连乘没有自动计入上述覆盖/角裕量失败造成的损失；有注意项时只能看条件预算。',
      '临界角采用当前波长的实数折射率和非吸收介质；忽略膜系、有限空气隙和受抑全反射，PBS 占位不计算消光比。']
    if p['source_model']=='lambertian':assumptions.append('朗伯角收集比例为 sin²(收集半角)，不自动适用于激光或未知角分布。')
    else:assumptions.append('自定义角收集比例为用户输入；没有已验证角分布时保持为假设。')
    result=dict(kind='analytical_budget',input_hash=hashlib.sha256(json.dumps(p,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest(),
      calculator_version='0.1.0',collimator=col,flyeye=fly,prism=prism,power=dict(collection_fraction=collection,output_lumens=flux,total_efficiency=total,stages=stages),checks=checks,assumptions=assumptions)
    json.dumps(result,allow_nan=False)
    return result

LABELS=[
 ('source_width_mm','发光区宽度','mm','source'),('source_height_mm','发光区高度','mm','source'),('source_lumens','光源总光通量','lm','source'),('collection_half_angle_deg','收集半角','°','source'),('source_model','角分布模型','','source'),('custom_collection_fraction','自定义角收集比例','0–1','source'),
 ('output_half_angle_x_deg','目标输出半角 X','°','collimator'),('output_half_angle_y_deg','目标输出半角 Y','°','collimator'),('reference_efl_mm','候选准直组 EFL','mm','collimator'),
 ('pitch_x_mm','单元节距 X','mm','flyeye'),('pitch_y_mm','单元节距 Y','mm','flyeye'),('cell_clear_width_mm','单元有效宽度','mm','flyeye'),('cell_clear_height_mm','单元有效高度','mm','flyeye'),('cell_efl_mm','单元 EFL','mm','flyeye'),('relay_efl_mm','中继 EFL','mm','flyeye'),('wavelength_nm','计算波长','nm','flyeye'),('columns','阵列列数 X','','flyeye'),('rows','阵列行数 Y','','flyeye'),('target_width_mm','目标芯片宽度','mm','flyeye'),('target_height_mm','目标芯片高度','mm','flyeye'),('margin_mm','单边照明余量','mm','flyeye'),
 ('prism_behavior','界面行为','','prism'),('n_high','入射侧折射率','','prism'),('n_low','出射侧折射率','','prism'),('incidence_min_deg','最小内部入射角','°','prism'),('incidence_max_deg','最大内部入射角','°','prism'),('required_margin_deg','要求角裕量','°','prism'),
 ('collimator_transmission','准直组透过率','0–1','efficiency'),('flyeye_transmission','复眼通量效率','0–1','efficiency'),('prism_transmission','棱镜通量效率','0–1','efficiency'),('imager_efficiency','成像器件光学效率','0–1','efficiency'),('lens_transmission','投影镜头透过率','0–1','efficiency')]
FIELDS=[dict(key=k,label=label,unit=u,group=g,type='select' if k in ('source_model','prism_behavior') else 'number',step=1 if k in ('columns','rows') else 'any',min=0) for k,label,u,g in LABELS]
for f in FIELDS:
    if f['key']=='source_model':f['options']=[dict(value='lambertian',label='朗伯面光源（条件模型）'),dict(value='custom',label='自定义角收集比例')]
    if f['key']=='prism_behavior':f['options']=[dict(value='reflect',label='TIR 反射界面'),dict(value='transmit',label='低于临界角的透射界面'),dict(value='pbs',label='PBS：效率占位，待膜系')]
    if f['unit']=='0–1':f['max']=1
    if f['key']=='wavelength_nm':f['hint']='修改波长时需同时核对 EFL 与材料折射率。'
    if f['key'].startswith('incidence_'):f['hint']='高折射率介质内，相对当前界面法线。';f['max']=90
TEMPLATES=[dict(id='dlp',name='DLP 照明起算',description='0.47 英寸级目标面、准直、复眼和 TIR 条件预算。全部数值为演示输入。'),dict(id='compact',name='紧凑光源起算',description='较小发光区与目标面，使用自定义角收集比例。可从这里替换自己的参数。')]

def template_parameters(template):
    if template not in ('dlp','compact'):raise ValueError('未知原型模板')
    p=dict(DEFAULTS)
    if template=='compact':p.update(source_width_mm=1.2,source_height_mm=.8,source_lumens=2000.,source_model='custom',target_width_mm=7.2,target_height_mm=4.05,relay_efl_mm=36.,reference_efl_mm=10.)
    return p
