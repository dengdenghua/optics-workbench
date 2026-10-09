"""SQLite store shared by the browser workbench and MCP. Sources are read only."""
import csv
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
from datetime import datetime,timezone
import uuid
from .calculations import calculate,template_parameters,TEMPLATES,FIELDS
from .scene import default_scene,validate_scene,trace_scene
from .color import validate as validate_color, calculate as calculate_color, default_budget, fingerprint
from .color_cases import all_cases
from .design import differences, chain_template

def now():return datetime.now(timezone.utc).isoformat(timespec='seconds')
def dumps(v):return json.dumps(v,ensure_ascii=False,allow_nan=False,separators=(',',':'))
def loads(s):return json.loads(s,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('不支持非有限数值 '+v)))
def basename(p):return str(p).replace('\\','/').rsplit('/',1)[-1]

class ClosingConnection(sqlite3.Connection):
    def __exit__(self,*args):
        try:return super().__exit__(*args)
        finally:self.close()

class Workbench:
    def __init__(self,config_path=None,data_dir=None):
        self.lock=threading.RLock();self.config_path=Path(config_path).expanduser().resolve() if config_path else None
        self.config={}
        if self.config_path:
            if not self.config_path.is_file():raise ValueError('本地配置文件不存在')
            self.config=loads(self.config_path.read_text(encoding='utf-8-sig'))
            if not isinstance(self.config,dict):raise ValueError('配置应为 JSON 对象')
        self.base=self.config_path.parent if self.config_path else Path.cwd()
        self.data_dir=self._path(data_dir or self.config.get('data_dir') or str(Path.home()/'.optics-workbench'))
        self.data_dir.mkdir(parents=True,exist_ok=True);self.db_path=self.data_dir/'workbench.sqlite3'
        with self.connect() as db:db.executescript((Path(__file__).parent/'schema.sql').read_text(encoding='utf-8'))
        self.sync()
        if not self.projects():self.new_project(name='我的第一个光学原型 · 演示')

    def _path(self,v):
        p=Path(os.path.expandvars(str(v))).expanduser()
        return (p if p.is_absolute() else self.base/p).resolve()

    def connect(self):
        db=sqlite3.connect(self.db_path,timeout=30,factory=ClosingConnection);db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');return db

    def _meta(self,db,key,value):db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',(key,dumps(value)))

    def sync(self):
        """Import metadata and distilled notes, never alter/read full original models."""
        with self.lock:
            inv=self._path(self.config['coverage_file']) if self.config.get('coverage_file') else None
            skill=self._path(self.config['skill_dir']) if self.config.get('skill_dir') else None
            with self.connect() as db:
                previous=db.execute("SELECT value FROM metadata WHERE key='mode'").fetchone()
            if not inv and not skill and previous and loads(previous[0])=='local_private':
                raise ValueError('此数据库已有个人资料索引，请提供原本的 --config 配置；不会用演示数据覆盖')
            if inv and not inv.is_file():raise ValueError('配置的覆盖清单不存在；数据库未覆盖')
            if skill and not skill.is_dir():raise ValueError('配置的 Skill 目录不存在；数据库未覆盖')
            groups=loads(inv.read_text(encoding='utf-8')) if inv else []
            if not isinstance(groups,list):raise ValueError('覆盖清单格式错误')
            docs=[]
            for g in groups:
                paths=[x['path'] for x in g['files']];reviews=[];ids=[]
                for rev in g.get('review_records',[]):
                    r=rev.get('record',{});sid=str(r.get('id',''))
                    if sid and sid not in ids:ids.append(sid)
                    scope=r.get('read_scope') or r.get('review_scope') or r.get('use') or r.get('scope') or ''
                    if not isinstance(scope,str):scope=dumps(scope)
                    reference=r.get('reference') or r.get('reader') or ''
                    if not isinstance(reference,str):reference=''
                    if reference.startswith('references/'):reference=reference[len('references/'):]
                    reviews.append(dict(source_id=sid,scope=scope,reference=reference))
                title=basename(paths[0]) if paths else g['sha256']
                docs.append((g['sha256'],title,Path(title).suffix.lower(),g['reading_status'],dumps(paths),dumps(ids),'\n'.join(r['scope'] for r in reviews),dumps(reviews),g.get('bytes',0)))
            components=[];notes=[];models=[]
            if skill:
                catalog_path=skill/'assets/component-catalog.json'
                if catalog_path.exists():
                    catalog=loads(catalog_path.read_text(encoding='utf-8'))
                    for kind in ('collimators','flyeyes','prisms'):
                        for i,c in enumerate(catalog.get(kind,[])):
                            cid=f'{kind}:{c.get("source_id","catalog")}:{c.get("source_row",i)}'
                            fields=[dict(label=str(v.get('header_as_recorded') or col),value=v.get('value'),cell=v.get('cell',col)) for col,v in c.get('fields',{}).items()]
                            suggestions=[]
                            recorded_notes='；'.join(str(x.get('value','')) for x in c.get('fields',{}).values() if '备注' in str(x.get('header_as_recorded','')))
                            noncollimated=any('非准直' in str(x.get('value','')) for x in c.get('fields',{}).values())
                            if kind=='collimators':
                                v=c.get('fields',{}).get('G',{}).get('value')
                                if isinstance(v,(int,float)) and not noncollimated:suggestions.append(dict(parameter='reference_efl_mm',value=v,note='历史目录 @550nm 的 EFL；须核当前波长与处方。'+recorded_notes))
                            if kind=='flyeyes':
                                v=c.get('fields',{}).get('L',{}).get('value')
                                if isinstance(v,(int,float)):suggestions.append(dict(parameter='cell_efl_mm',value=v,note='历史目录 @550nm 的 EFL；单/双面定义及当前波长待核。'))
                                dims=str(c.get('fields',{}).get('N',{}).get('value') or '')
                                for axis,parameter,clear in [('x','pitch_x_mm','cell_clear_width_mm'),('y','pitch_y_mm','cell_clear_height_mm')]:
                                    match=re.search(rf'{axis}\s*[-:=：]\s*(\d+(?:\.\d+)?)',dims,re.I)
                                    if match:
                                        val=float(match.group(1))
                                        for key in (parameter,clear):suggestions.append(dict(parameter=key,value=val,note='起算假设：把历史单元尺寸同时作为节距和有效尺寸；实际过渡区/孔径须另核。'))
                            entry=dict(id=cid,name=c.get('name','未命名器件'),kind=kind,source_id=c.get('source_id',''),source_sheet=c.get('source_sheet',''),source_row=c.get('source_row'),fields=fields,suggestions=suggestions,status='历史候选，非当前供应商保证')
                            if noncollimated:entry['status']='历史候选，原记录注明非准直出射；不自动建议准直焦距'
                            components.append((cid,entry['name'],kind,dumps(entry)))
                for f in sorted((skill/'references').rglob('*.md')):
                    body=f.read_text(encoding='utf-8-sig');title=next((s.lstrip('# ').strip() for s in body.splitlines() if s.strip()),f.stem)
                    notes.append((f.relative_to(skill/'references').as_posix(),title,body))
                index=skill/'assets/model-index.csv'
                if index.exists():
                    with index.open(encoding='utf-8-sig',newline='') as f:
                        for i,r in enumerate(csv.DictReader(f)):
                            mid=hashlib.sha256((r.get('path','')+'|'+str(i)).encode()).hexdigest()[:24]
                            models.append((mid,basename(r.get('path','')),r.get('path',''),dumps(r)))
            demo=not inv and not skill
            if demo:
                docs=[('demo-evidence','演示资料：参数预算的适用条件','.md','demo',dumps([]),dumps(['DEMO']),'公开演示记录，不包含个人工作文档。',dumps([dict(source_id='DEMO',scope='用于演示资料检索与来源关联。',reference='demo-budget.md')]),0)]
                notes=[('demo-budget.md','参数预算的适用条件','# 参数预算的适用条件\n\n本工作台计算解析预算，不生成光学处方。默认数值均为演示假设。\n\n先核光源尺寸、角分布和波长，再核准直焦距、复眼单元与目标面、棱镜内部角与材料。\n\n候选器件引用不等于已完成适配。用少量确定性光线检查位置—角度映射；实际效率、均匀性、偏振和公差需要相应模型或测量。')]
                for kind,name in [('collimators','演示准直组'),('flyeyes','演示复眼阵列'),('prisms','演示 TIR 界面')]:
                    cid='demo-'+kind;entry=dict(id=cid,name=name,kind=kind,source_id='DEMO',source_sheet='',source_row=None,fields=[dict(label='数据状态',value='合成演示，非真实器件',cell='')],suggestions=[],status='演示假设');components.append((cid,name,kind,dumps(entry)))
            with self.connect() as db:
                for table in ('documents','components','knowledge','models'):db.execute(f'DELETE FROM {table}')
                db.executemany('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?)',docs)
                db.executemany('INSERT INTO components VALUES(?,?,?,?)',components)
                db.executemany('INSERT INTO knowledge VALUES(?,?,?)',notes)
                db.executemany('INSERT INTO models VALUES(?,?,?,?)',models)
                self._meta(db,'synced_at',now());self._meta(db,'mode','demo' if demo else 'local_private')
                self._meta(db,'path_count',sum(len(loads(d[4])) for d in docs));self._meta(db,'schema_version',1)
                self._meta(db,'source_snapshot',self.config.get('snapshot_note','元数据导入；未重新核验全部原文件'))
            return self.stats()

    def stats(self):
        with self.connect() as db:
            meta={r['key']:loads(r['value']) for r in db.execute('SELECT * FROM metadata')}
            counts={t:db.execute(f'SELECT count(*) FROM {t}').fetchone()[0] for t in ('documents','components','knowledge','models','projects')}
            statuses={r[0]:r[1] for r in db.execute('SELECT status,count(*) FROM documents GROUP BY status')}
        return {**counts,**meta,'reading_status_counts':statuses,'reviewed':statuses.get('registered_partial_review',0),'unread':statuses.get('unread_or_no_registered_review',0),'portability':'代码、结构与演示公开；个人资料、路径和数据库仅本地'}

    def _search(self,query,columns):
        if not isinstance(query,str) or len(query)>500:raise ValueError('检索词过长')
        parts=query.strip().split()[:12];sql=[];args=[]
        for part in parts:
            sql.append('('+' OR '.join(f'{c} LIKE ? ESCAPE \'\\\'' for c in columns)+')')
            pattern='%'+part.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%';args.extend([pattern]*len(columns))
        return (' AND '.join(sql) or '1'),args

    def library(self,query='',status='',page=1,limit=30):
        page=max(1,int(page));limit=max(1,min(100,int(limit)));where,args=self._search(query,['title','paths','summary','source_ids'])
        if status:where+=' AND status=?';args.append(status)
        with self.connect() as db:
            total=db.execute('SELECT count(*) FROM documents WHERE '+where,args).fetchone()[0]
            rows=db.execute('SELECT * FROM documents WHERE '+where+' ORDER BY CASE status WHEN \'registered_partial_review\' THEN 0 ELSE 1 END,title LIMIT ? OFFSET ?',args+[limit,(page-1)*limit]).fetchall()
        items=[dict(id=r['id'],title=r['title'],format=r['format'],status=r['status'],path_count=len(loads(r['paths'])),source_ids=loads(r['source_ids']),summary=r['summary'][:700]) for r in rows]
        return dict(items=items,total=total,page=page,limit=limit)

    def document(self,source_id):
        with self.connect() as db:r=db.execute('SELECT * FROM documents WHERE id=?',(source_id,)).fetchone()
        if not r:raise ValueError('资料未找到')
        d=dict(r)
        for key in ('paths','source_ids','reviews'):d[key]=loads(d[key])
        return d

    def components(self,kind='',query=''):
        where,args=self._search(query,['name','payload'])
        if kind:where+=' AND kind=?';args.append(kind)
        with self.connect() as db:return [loads(r[0]) for r in db.execute('SELECT payload FROM components WHERE '+where+' ORDER BY kind,name',args)]

    def knowledge(self,query='',limit=30):
        where,args=self._search(query,['title','body']);limit=max(1,min(200,int(limit)))
        with self.connect() as db:rows=db.execute('SELECT * FROM knowledge WHERE '+where+' ORDER BY title LIMIT ?',args+[limit]).fetchall()
        return [dict(slug=r['slug'],title=r['title'],excerpt=r['body'][:500]) for r in rows]

    def reference(self,slug):
        with self.connect() as db:r=db.execute('SELECT * FROM knowledge WHERE slug=?',(slug,)).fetchone()
        if not r:raise ValueError('规则未找到')
        return dict(r)

    def models(self,query='',limit=30):
        where,args=self._search(query,['title','path','payload']);limit=max(1,min(100,int(limit)))
        with self.connect() as db:
            total=db.execute('SELECT count(*) FROM models WHERE '+where,args).fetchone()[0]
            rows=db.execute('SELECT * FROM models WHERE '+where+' ORDER BY title LIMIT ?',args+[limit]).fetchall()
        return dict(items=[dict(id=r['id'],title=r['title'],path=r['path'],metadata=loads(r['payload'])) for r in rows],total=total)

    def projects(self):
        with self.connect() as db:return [dict(r) for r in db.execute('SELECT id,name,template,version,created_at,updated_at FROM projects ORDER BY updated_at DESC,id')]

    def project(self,project_id):
        with self.connect() as db:r=db.execute('SELECT payload FROM projects WHERE id=?',(project_id,)).fetchone()
        if not r:raise ValueError('原型未找到')
        return loads(r[0])

    def calculate(self,data):
        if not isinstance(data,dict):raise ValueError('原型应为对象')
        return calculate(data.get('parameters'))

    def new_project(self,template='dlp',name=None):
        name=name or next((t['name'] for t in TEMPLATES if t['id']==template),'新原型')
        return self.save_project(dict(name=name,template=template,notes='演示假设。请用自己的规格替换参数，并核对器件与波长。',parameters=template_parameters(template),selected_components={}))

    def save_project(self,data):
        if not isinstance(data,dict):raise ValueError('原型应为对象')
        name=data.get('name','').strip() if isinstance(data.get('name'),str) else ''
        if not name or len(name)>120:raise ValueError('原型名称应为 1–120 个字符')
        notes=data.get('notes','')
        if not isinstance(notes,str) or len(notes)>20000:raise ValueError('备注过长或类型错误')
        result=self.calculate(data)
        scene=validate_scene(data['scene']) if 'scene' in data else None
        color=validate_color(data['color_budget']) if 'color_budget' in data else None
        color_result=self.calculate_color(color,data['parameters']) if color is not None else None
        selected=data.get('selected_components',{})
        if not isinstance(selected,dict) or set(selected)-{'collimators','flyeyes','prisms'}:raise ValueError('器件引用格式错误')
        if any(v is not None and (not isinstance(v,str) or len(v)>250) for v in selected.values()):raise ValueError('器件 ID 格式错误')
        pid=data.get('id') or uuid.uuid4().hex
        if not isinstance(pid,str) or not re.fullmatch(r'[a-f0-9]{32}',pid):raise ValueError('原型 ID 格式错误')
        with self.lock,self.connect() as db:
            db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT * FROM projects WHERE id=?',(pid,)).fetchone()
            if row and (isinstance(data.get('version'),bool) or data.get('version')!=row['version']):raise ValueError('原型已由另一个窗口更新，请重新加载后再保存')
            if data.get('id') and not row:raise ValueError('原型不存在；导入请使用导入功能')
            for kind,cid in selected.items():
                if cid and not db.execute('SELECT 1 FROM components WHERE id=? AND kind=?',(cid,kind)).fetchone():raise ValueError('选中的器件不存在或类型不符，请重新选择：'+cid)
            stamp=now();version=row['version']+1 if row else 1
            project=dict(id=pid,name=name,template=str(data.get('template','dlp'))[:30],notes=notes,parameters=data['parameters'],selected_components=selected,version=version,created_at=row['created_at'] if row else stamp,updated_at=stamp,calculation=result)
            # Older clients may omit optional modules. Preserve their state.
            if scene is not None:project['scene']=scene
            elif row:
                previous=loads(row['payload'])
                if 'scene' in previous:project['scene']=previous['scene']
            if color is not None:
                project['color_budget']=color;project['color_calculation']=color_result
            elif row:
                previous=loads(row['payload'])
                if 'color_budget' in previous:
                    project['color_budget']=previous['color_budget'];project['color_calculation']=self.calculate_color(previous['color_budget'],data['parameters'])
            encoded=dumps(project)
            db.execute('INSERT INTO projects VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,template=excluded.template,version=excluded.version,updated_at=excluded.updated_at,payload=excluded.payload',(pid,name,project['template'],version,project['created_at'],stamp,encoded))
            db.execute('INSERT INTO project_revisions VALUES(?,?,?,?)',(pid,version,stamp,encoded))
        return project

    def export_project(self,project_id):
        p=self.project(project_id)
        fields={k:p[k] for k in ('name','template','notes','parameters','selected_components')}
        if 'scene' in p:fields['scene']=p['scene']
        if 'color_budget' in p:fields['color_budget']=p['color_budget']
        return dict(schema='optics-workbench.prototype',schema_version=1,exported_at=now(),project=fields,calculation=p['calculation'],scope='参数迁移文件，不附原始资料文件或原生模型；名称、备注及器件引用可能包含私人信息，分享前请检查。')

    def import_project(self,payload):
        if not isinstance(payload,dict) or payload.get('schema')!='optics-workbench.prototype' or payload.get('schema_version')!=1:raise ValueError('不支持的原型文件格式或版本')
        raw=payload.get('project');self.calculate(raw)
        if not isinstance(raw.get('selected_components',{}),dict):raise ValueError('器件引用格式错误')
        p={k:raw.get(k) for k in ('name','template','notes','parameters')};p['selected_components']={}
        if 'scene' in raw:p['scene']=validate_scene(raw['scene'])
        if 'color_budget' in raw:p['color_budget']=validate_color(raw['color_budget'])
        missing=[]
        with self.connect() as db:
            for kind,cid in raw.get('selected_components',{}).items():
                if kind not in ('collimators','flyeyes','prisms'):raise ValueError('未知器件类别')
                if cid and db.execute('SELECT 1 FROM components WHERE id=? AND kind=?',(cid,kind)).fetchone():p['selected_components'][kind]=cid
                elif cid:missing.append(str(cid))
        if missing:p['notes']=(p.get('notes') or '')+'\n迁移提示：本机未找到以下器件引用，参数保留，需重新关联：'+', '.join(missing)
        return self.save_project(p)

    def scene(self,project_id):
        p=self.project(project_id)
        scene=validate_scene(p['scene']) if 'scene' in p else default_scene(p['parameters'])
        return dict(project_id=p['id'],version=p['version'],scene=scene,trace=trace_scene(scene))

    def preview_scene(self,scene):
        return trace_scene(scene)

    def save_scene(self,project_id,version,scene):
        return self.apply_design(project_id,version,scene=scene)

    def color_cases(self):
        cases=all_cases(self._path(self.config['skill_dir']) if self.config.get('skill_dir') else None)
        return [{k:c.get(k) for k in ('id','title','source_id','sheet','scope')} for c in cases]

    def color_case(self,case_id):
        cases=all_cases(self._path(self.config['skill_dir']) if self.config.get('skill_dir') else None)
        match=next((c for c in cases if c['id']==case_id),None)
        if match is None:raise ValueError('配色案例未找到；个人案例需要本机Skill配置')
        return match

    def color_budget(self,project_id):
        p=self.project(project_id);b=p.get('color_budget') or default_budget()
        return dict(project_id=p['id'],version=p['version'],budget=b,calculation=self.calculate_color(b,p['parameters']),saved='color_budget' in p)

    def calculate_color(self,budget,parameters=None):
        result=calculate_color(budget,parameters)
        provenance=budget.get('provenance',{})
        context=dict(source_id=provenance.get('source_id',''),case_id=provenance.get('case_id',''),
                     scope=provenance.get('scope',''),status='unverified',changes=dict(items=[],total=0,truncated=False))
        if provenance.get('source_id')=='synthetic_demo':context['status']='synthetic'
        if provenance.get('case_id'):
            try:
                case=self.color_case(provenance['case_id'])
                before=copy.deepcopy(case['budget']);after=copy.deepcopy(budget)
                before.pop('provenance',None);after.pop('provenance',None)
                context.update(title=case['title'],source_sha256=case.get('source_sha256',''),reference_slug=case.get('reference_slug',''),
                               changes=differences(before,after,60),status='case_unchanged' if before==after else 'case_modified')
                if provenance.get('source_sha256') and provenance['source_sha256'] != case.get('source_sha256'):
                    context['status']='source_changed'
            except ValueError:context['status']='case_unavailable'
        elif provenance.get('baseline_hash'):
            context['status']='baseline_unchanged' if fingerprint(budget)==provenance['baseline_hash'] else 'baseline_modified'
        result['source_context']=context
        return result

    def chain_template(self,parameters,receiving_plane,start_stage):
        return chain_template(parameters,receiving_plane,start_stage)

    def preview_design(self,project_id,version,scene=None,parameter_updates=None,color_budget=None,note=''):
        if type(version) is not int or version<1:raise ValueError('请提供当前原型的整数版本')
        original=self.project(project_id)
        if original['version']!=version:raise ValueError('原型已更新，请重新载入后预览')
        if not isinstance(note,str) or len(note)>2000:raise ValueError('设计说明过长或类型错误')
        p=copy.deepcopy(original)
        if scene is not None:p['scene']=validate_scene(scene)
        if parameter_updates is not None:
            if not isinstance(parameter_updates,dict) or set(parameter_updates)-set(p['parameters']):raise ValueError('参数修改包含未知字段')
            p['parameters'].update(parameter_updates)
        if color_budget is not None:p['color_budget']=validate_color(color_budget)
        if note:p['notes']=(p.get('notes','')+'\n'+note).strip()
        if len(p.get('notes',''))>20000:raise ValueError('备注过长')
        p['calculation']=self.calculate(p)
        if 'color_budget' in p:p['color_calculation']=self.calculate_color(p['color_budget'],p['parameters'])
        paths=('parameters','scene','color_budget','notes')
        diff=differences({k:original.get(k) for k in paths},{k:p.get(k) for k in paths})
        return dict(project_id=project_id,version=version,draft=p,differences=diff,
                    trace=trace_scene(p.get('scene') or default_scene(p['parameters'])),scope='只预览；未保存、未运行原生光学仿真')

    def search_evidence(self,query='',limit=8):
        """Bounded local snippets; original source files are never opened."""
        if type(limit) is not int or not 1<=limit<=20:raise ValueError('证据检索数量应为1–20')
        where,args=self._search(query,['title','body'])
        with self.connect() as db:notes=db.execute('SELECT * FROM knowledge WHERE '+where+' ORDER BY title LIMIT ?',args+[limit]).fetchall()
        items=[];terms=query.lower().split()
        for row in notes:
            lines=row['body'].splitlines()
            start=next((i for i,line in enumerate(lines) if any(t in line.lower() for t in terms)),0)
            end=min(len(lines),start+10);excerpt='\n'.join(lines[start:end])[:1800]
            ident='reference:'+row['slug']+'#L'+str(start+1)+'-'+str(end)+':'+hashlib.sha256(excerpt.encode()).hexdigest()[:16]
            items.append(dict(id=ident,title=row['title'],kind='reference',location=row['slug']+':'+str(start+1),
                              excerpt=excerpt,source_ids=sorted(set(re.findall(r'\bS\d{2,3}\b',excerpt))),scope='已蒸馏条目的选定行；不是全部源文档核读',line_start=start+1,line_end=end))
        for case in self.color_cases():
            hay=' '.join(str(case.get(k,'') or '') for k in ('title','source_id','sheet','scope')).lower()
            if all(t in hay for t in terms) and len(items)<limit:
                ident='case:'+case['id']+':'+hashlib.sha256(dumps(case).encode()).hexdigest()[:16]
                items.append(dict(id=ident,title=case['title'],kind='case',location=case['source_id']+' / '+(case.get('sheet') or '合成演示'),
                                  excerpt=case['scope'],source_ids=[case['source_id']],scope=case['scope']))
        return dict(items=items,query=query,scope='本机资料检索；仅索引及蒸馏证据，不读取原始工作文件')

    def selected_evidence(self,identifiers):
        if not isinstance(identifiers,list) or len(identifiers)>8 or any(not isinstance(i,str) for i in identifiers) or len(set(identifiers))!=len(identifiers):raise ValueError('最多选择8项不同证据')
        items=[]
        for ident in identifiers:
            if not isinstance(ident,str) or len(ident)>300:raise ValueError('证据编号错误')
            if ident.startswith('reference:'):
                match=re.fullmatch(r'reference:(.+)#L(\d+)-(\d+):([a-f0-9]{16})',ident)
                if not match:raise ValueError('证据片段编号错误')
                slug,first,last,digest=match.groups();first=int(first);last=int(last)
                if not 1<=first<=last or last-first>=10:raise ValueError('证据片段范围错误')
                ref=self.reference(slug);excerpt='\n'.join(ref['body'].splitlines()[first-1:last])[:1800]
                if hashlib.sha256(excerpt.encode()).hexdigest()[:16]!=digest:raise ValueError('所选证据已更新，请重新检索并选择')
                items.append(dict(id=ident,title=ref['title'],location=ref['slug']+':'+str(first),excerpt=excerpt,scope='用户选择的条目片段'))
            elif ident.startswith('case:'):
                match=re.fullmatch(r'case:([^:]+):([a-f0-9]{16})',ident)
                if not match:raise ValueError('案例证据编号错误')
                case=self.color_case(match[1]);summary=next(c for c in self.color_cases() if c['id']==match[1])
                if hashlib.sha256(dumps(summary).encode()).hexdigest()[:16]!=match[2]:raise ValueError('所选案例已更新，请重新选择')
                items.append(dict(id=ident,title=case['title'],location=case['source_id']+' / '+case.get('sheet',''),excerpt=case['scope'],scope=case['scope']))
            else:raise ValueError('未知证据编号')
        return items

    def save_color(self,project_id,version,budget):
        return self.apply_design(project_id,version,color_budget=budget)

    def apply_design(self,project_id,version,scene=None,parameter_updates=None,note='',color_budget=None):
        if isinstance(version,bool) or not isinstance(version,int) or version<1:
            raise ValueError('请提供当前原型的整数版本')
        if not isinstance(note,str) or len(note)>2000:raise ValueError('设计说明应为不超过2000字的文本')
        if scene is None and parameter_updates is None and color_budget is None:raise ValueError('没有提供光路或参数修改')
        p=copy.deepcopy(self.project(project_id))
        if p['version']!=version:raise ValueError('原型已由另一个窗口更新，请重新加载后再保存')
        if scene is not None:p['scene']=validate_scene(scene)
        if color_budget is not None:p['color_budget']=validate_color(color_budget)
        if parameter_updates is not None:
            if not isinstance(parameter_updates,dict) or set(parameter_updates)-set(p['parameters']):raise ValueError('参数修改包含未知字段')
            p['parameters'].update(parameter_updates)
        if note:p['notes']=(p.get('notes','')+'\n'+note).strip()
        # save_project rechecks the version inside the SQLite write transaction.
        return self.save_project(p)
