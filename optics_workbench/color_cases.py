"""Adapters for already-reviewed local workbook evidence; never read originals."""
import copy
import json
from pathlib import Path
from .color import calculate, default_budget, source, GROUPS


def _read(base, filename):
    p=base/'assets'/filename
    if not p.is_file():return None
    if p.stat().st_size>8*1024*1024:raise ValueError('配色案例证据文件超过8 MiB')
    return json.loads(p.read_text('utf-8-sig'))


def _comparison(case):
    result=calculate(case['budget'])
    manual=copy.deepcopy(case['budget']);manual['allocation']='manual';manual['angles_deg']=case['original']['angles_deg']
    fixed=calculate(manual)
    case['comparison']=dict(solved=dict(lumens=result['output']['lumens'],x=result['output']['x'],y=result['output']['y'],
                                        angles_deg={r['group']:r['angle_deg'] for r in result['rgb']},gamut=result['gamut']),
                            same_original_angles=dict(lumens=fixed['output']['lumens'],x=fixed['output']['x'],y=fixed['output']['y']),
                            input_total_lumens=result['input_total']['lumens'])
    return case


def all_cases(skill_dir=None):
    demo=default_budget();demo_result=calculate(demo)
    cases=[dict(id='synthetic-rgb',title='合成RGB演示',source_id='synthetic_demo',sheet='',budget=demo,
                original=dict(white_lumens=None,x=None,y=None,cw_lumens=None,angles_deg={r['group']:r['angle_deg'] for r in demo_result['rgb']}),
                audit=[],scope='合成演示，不对应个人表格、当前器件规格或实测。')]
    if not skill_dir:return [_comparison(cases[0])]
    base=Path(skill_dir)
    sst=_read(base,'sst-reviewed-cases.json')
    if sst:
        for index,entry in enumerate(sst.get('main_case_recalculations',[])):
            b=default_budget();b['sources']=[source(s['name'],GROUPS[i//2],s['x'],s['y'],s['lumens'],entry['sheet']+'!'+s['source_range']) for i,s in enumerate(entry['source_channel_cells'])]
            b['target_x']=entry['target_xy']['x'];b['target_y']=entry['target_xy']['y']
            b['receiving_plane']='原表配色输入共同接收面（实物面待确认）'
            scope='已核读选定输入、公式及缓存；独立全精度复算，只校正合计/坐标链，不等于全表重算或实测。后段η=1、屏幕1m²为占位假设。'
            identifier='sst-'+str(index)
            b['provenance']=dict(case_id=identifier,source_id=sst['source_id'],sheet=entry['sheet'],scope=scope)
            cached=entry['cached_final']
            original=dict(white_lumens=cached['lumens'],x=cached['x'],y=cached['y'],cw_lumens=entry['cached_CW_white_lumens'],
                          angles_deg=dict(zip(GROUPS,entry['original_angles_deg'])),power_rows=entry.get('laser_power_cross_check',[]),
                          cie1976_labeled_P3_ratio=entry.get('gamut_P3',{}).get('cached_CIE1976_label_ratio_B72'))
            audits=[dict(location=entry['sheet']+'!F32:H32',finding='原SUM第21–25行，漏第26行；现在合计全部启用光源。'),
                    dict(location='Laser!B39/D39',finding='断引用分母未恢复，不能猜原地址；不作为本模块公式输入。'),
                    dict(location='主方案B15:C17 / G15:G17',finding='光学W、电学W及WPE存在不一致；案例电热输入保持未确认，不输出可信整机能效。'),
                    dict(location=entry['sheet']+'!B69:B73 / T84:T88',finding='原CIE1976标签部分引用xy面积比；本模块分别算xy/u′v′面积比和交集覆盖。')]
            if entry.get('changed_xy_between_CW_and_timed_rows'):
                audits.append(dict(location=entry['sheet']+'!B50:D50',finding='时序输出蓝光坐标链与CW源不一致，z仍沿用旧链；参考计算保持同一源xy，重算z=1−x−y。'))
            audits.append(dict(location='工作簿fullPrecision=0 / 外部链接',finding='按显示精度与外链缓存的影响未重现；本模块保留已保存输入精度，不声称修复Excel。'))
            cases.append(_comparison(dict(id=identifier,title='SST · '+repr(entry['sheet']),source_id=sst['source_id'],sheet=entry['sheet'],budget=b,
                                         original=original,audit=audits,scope=scope,source_sha256=sst['source']['sha256'],reference_slug='hybrid-source-budget')))
    chaoguang=_read(base,'chaoguang-reviewed.json')
    if chaoguang:
        ev=chaoguang['evidence'];review=chaoguang['independent_review']
        sheet=next(s for s in ev['sheets'] if s['name']=='ALPD4.0光学计算');cells={c['address']:c['value'] for c in sheet['cells']}
        b=default_budget();b['sources']=[source(cells['B'+str(row)],group,cells['C'+str(row)],cells['D'+str(row)],cells['F'+str(row)],sheet['name']+'!B'+str(row)+':I'+str(row)) for row,group in zip(range(25,30),('R','R','G','G','B'))]
        b['target_x']=cells['C44'];b['target_y']=cells['D44'];b['available_angle_deg']=360-cells['J43'];b['receiving_plane']='原表配色输入共同接收面（实物面待确认）'
        scope='五源同RGB段共用时序；原整数角输出与精确求解分别展示。已核读三表并选定独立复算，未Excel全表重算或实测。后段η=1、屏幕1m²为占位假设。'
        b['provenance']=dict(case_id='chaoguang',source_id=chaoguang['source_id'],sheet=sheet['name'],scope=scope)
        original=dict(white_lumens=cells['F59'],x=cells['C59'],y=cells['D59'],cw_lumens=cells['F35'],angles_deg=dict(zip(GROUPS,[cells['G49'],cells['G51'],cells['G53']])))
        audit=[dict(location='ALPD4.0光学计算!G49:G53',finding='原输出使用手填整数角，未链接精确解；光源变化后须重新分配并回算白点。'),
               dict(location='ALPD4.0光学计算!F19:F20',finding='荧光激发系数在公式中的口径为lm/泵浦W，不是无量纲效率。'),
               dict(location='常用计算!I24:J26',finding='六处断引用未猜测恢复；本模块独立解XYZ矩阵。'),
               dict(location='ALPD4.0光学计算!F35/F59',finding='CW全开总和与扣12°消隐后的时序白场分开报告。')]
        cases.append(_comparison(dict(id='chaoguang',title='超光越影 · '+sheet['name'],source_id=chaoguang['source_id'],sheet=sheet['name'],budget=b,
                                     original=original,audit=audit,scope=scope,source_sha256=ev['sha256'],reference_slug='alpd-flyeye-budget')))
    cases[0]=_comparison(cases[0])
    return cases
