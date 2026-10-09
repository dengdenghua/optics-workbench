# Implementation contract

Portable local optical parameter workbench. Public source code and synthetic demos; private knowledge/data/config are separate and ignored by Git. SQLite and Python standard library server, static browser UI, stdio MCP using the same core. No optical application operation or source-file mutation.

## Python core

`from optics_workbench.core import Workbench`
`Workbench(config_path=None, data_dir=None)` exposes:

- `stats()`, `sync()`
- `library(query='', status='', page=1, limit=30)`, `document(source_id)`
- `components(kind='', query='')`, `knowledge(query='', limit=30)`, `reference(slug)`
- `projects()`, `project(project_id)`, `new_project(template='dlp', name=None)`, `save_project(data)`
- `calculate(data)` where data is a project with `parameters` (flat object)
- `export_project(project_id)`, `import_project(payload)`
- `models(query='', limit=30)`
- `scene(project_id)`, `preview_scene(scene)`, `save_scene(project_id, version, scene)`
- `apply_design(project_id, version, scene=None, parameter_updates=None, note='')`

`new_project` persists a synthetic demo-derived project. `save_project` validates and calculates, increments optimistic `version`; conflict raises ValueError. No delete endpoint. Exports omit indexed machine paths and source documents, but include user-entered name and notes. Imported schemas validated. Core methods return JSON-compatible values, raise ValueError for invalid requests. Scene and scalar parameters remain independent; legacy saves omitting a scene preserve any stored scene.

## HTTP

GET `/api/bootstrap` => `{stats, templates, fields, projects, csrf_token}`.
POST `/api/sync` => stats. GET `/api/stats` => stats.
GET `/api/library?q=&status=&page=` => `{items:[{id,title,format,status,path_count,source_ids,summary}],total,page,limit}`.
GET `/api/library/{id}` => `{id,title,format,status,paths,source_ids,reviews:[{source_id,scope,reference}],...}`.
GET `/api/components?kind=&q=` => array `{id,name,kind,source_id,source_sheet,source_row,fields:[{label,value,cell}],suggestions:[{parameter,value,note}],status}`. Kinds `collimators,flyeyes,prisms`; historical catalog entries remain candidates. Applying suggestions must display their assumptions.
GET `/api/knowledge?q=` => array `{slug,title,excerpt}`. GET `/api/knowledge/{slug}` => `{slug,title,body}` plain Markdown text (render safely, never raw HTML).
GET `/api/models?q=` => `{items,total}`; index metadata only.
GET `/api/projects` => array project summaries `{id,name,updated_at,version,template}`.
GET `/api/projects/{id}` => complete project.
POST `/api/projects/new` body `{template,name?}` => complete project.
POST `/api/projects` body complete project => saved complete project.
POST `/api/calculate` body complete project => calculation object below.
GET `/api/projects/{id}/export` => portable JSON attachment.
POST `/api/projects/import` body portable export => newly persisted project (new id).
GET `/api/projects/{id}/scene` => `{project_id,version,scene,trace}` (default generation does not save).
POST `/api/scene/trace` body `{scene}` => paraxial trace.
POST `/api/scene/save` body `{project_id,version,scene}` => saved complete project.
POST `/api/design/apply` body `{project_id,version,scene?,parameter_updates?,note?}` => complete project, one new version.
GET `/api/ai/status` => `{configured,model,provider,message}` (no credentials).
POST `/api/ai/chat` body `{project_id,version,message,history?:[{role:'user'|'assistant',content}]}` => `{reply,project,actions,trace}`; API unavailable errors use HTTP 503. The draft is committed only after successful model completion with a matching version.
Errors JSON `{error: 'message'}` with non-2xx. Mutations require `X-Workbench-Token` from bootstrap, same-origin.

Project shape: `{id,name,template,notes,parameters,selected_components:{collimators:id|null,flyeyes:id|null,prisms:id|null},version,created_at,updated_at,calculation,scene?}`. Scene details and validation boundaries: [visual contract](VISUAL_AI_CONTRACT.md).

Templates: array `{id:'dlp'|'compact',name,description}`. Fields: array `{key,label,unit,group,type:'number'|'select',min?,max?,step?,options?:[{value,label}],hint?}`. Frontend builds forms from descriptors; unknown values should remain visibly unset.

Calculation: `{kind:'analytical_budget',input_hash,calculator_version,collimator,flyeye,prism,power:{collection_fraction,output_lumens,total_efficiency,stages:[{name,efficiency,lumens}]},checks:[{status:'ok'|'attention'|'unknown',title,detail}],assumptions:[string]}`. No performance certification; all budgets conditional. Every edited input makes displayed calculation stale until rerun/save.

Parameter keys (all numeric except source_model and prism_behavior):
`source_width_mm,source_height_mm,source_lumens,collection_half_angle_deg,source_model` (`lambertian` or `custom`),`custom_collection_fraction,output_half_angle_x_deg,output_half_angle_y_deg,reference_efl_mm,pitch_x_mm,pitch_y_mm,cell_clear_width_mm,cell_clear_height_mm,cell_efl_mm,relay_efl_mm,wavelength_nm,columns,rows,target_width_mm,target_height_mm,margin_mm,n_high,n_low,incidence_min_deg,incidence_max_deg,required_margin_deg,prism_behavior` (`reflect`,`transmit`,`pbs`),`collimator_transmission,flyeye_transmission,prism_transmission,imager_efficiency,lens_transmission`.

Frontend uses only local assets; secrets remain in the Python server. MCP and HTTP share the same versioned store. SQLite requires no schema migration for optional scene payloads.
