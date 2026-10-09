# AI visual workbench implementation contract

This addition uses the existing shared project store. Original files remain read-only. The new scene is a first-order, unfolded-axis optical prototype; lens shapes are symbols, not manufactured prescriptions. No external optical applications start automatically.

## Scene and trace

`optics_workbench.scene`: `default_scene(parameters)`, `validate_scene(scene)` returns normalized scene, `trace_scene(scene)` returns the shape below. Standard library only.

Scene: `{schema_version:1, units:"mm", elements:[...], rays:{half_angle_deg:5, rays_per_point:5, source_points:3, wavelength_nm:550}}`.

Each element has `id` (ASCII identifier, unique), `kind` (`source`, `lens`, `flyeye`, `prism`, `aperture`, `screen`), `label`, `z_mm` (unfolded longitudinal coordinate), `y_mm` (decenter, default 0), `aperture_mm` (full meridional height), `width_mm` (full transverse symbol width). `lens` and `flyeye` additionally have nonzero `focal_mm`; `flyeye` also positive `pitch_mm`. `prism` additionally `bend_deg` (0 or 90; ideal display folding only, no Snell/coating calculation). Elements are sorted by z; exactly one source first and one screen last, other kinds in between; <=32 elements. Strict finite bounded validation, IDs stable. No extra keys silently ignored. Source points/rays bounded (<=9/21). Angles <=15 degrees; warn beyond paraxial comfort, not an energy Monte Carlo model.

Default: source, collimator one focal length later, two flyeyes, relay lens, prism, target screen. Derived starting positions and focal lengths use existing parameters; initial ray fan intentionally small and explicitly not the full collection cone. Scene is independently edited and does not automatically change scalar budget parameters.

Trace: `{kind:"paraxial_ray_fan", scene, rays:[{id,source_y_mm,angle_deg,points:[{z_mm,y_mm,element_id}],status:"reached"|"blocked",blocked_by:null|id}], summary:{launched,reached,blocked,screen_min_y_mm,screen_max_y_mm}, warnings:[string], assumptions:[string]}`. Deterministic paraxial slope lens law and cell-local flyeye lens law; apertures terminate rays. Prism passes the unfolded bundle; view may fold coordinates ideally by bend_deg. Trace ray-count ratios are never optical efficiency. `trace_scene` must validate.

## Shared core + HTTP

Projects optionally persist `scene`; older projects get default scene only when requested, no forced resave. Exports keep schema_version 1 and optionally include `project.scene`; import preserves it after validation. Saves/version history preserve scene. Legacy clients omitting it on existing project save retain the latest stored scene.

`Workbench.scene(project_id)` -> `{project_id, version, scene, trace}`.
`Workbench.save_scene(project_id, version, scene)` -> complete saved project; optimistic version required.
`Workbench.preview_scene(scene)` -> trace only, no DB writes.
`Workbench.apply_design(project_id, version, scene=None, parameter_updates=None, note="")` -> complete project, atomic single version; valid current parameters only, no unknown keys. Both scene and budget remain explicitly separate.

GET `/api/projects/{id}/scene` -> scene envelope. POST `/api/scene/trace` `{scene}` -> trace. POST `/api/scene/save` `{project_id,version,scene}` -> complete saved project. POST `/api/design/apply` `{project_id,version,scene?,parameter_updates?,note?}` -> complete saved project.
GET `/api/ai/status` -> `{configured, model, provider:"openai", message}` (never any secret).
POST `/api/ai/chat` `{project_id,version,message,history?:[{role:"user"|"assistant",content:string}]}` -> `{reply,project,actions:[{tool,summary}],trace}`. All routes retain loopback + CSRF protection. Missing key returns clear error, never simulated AI reply. Model API solely on server.

## MCP

Add `optics_get_scene(project_id)`, `optics_trace_scene(scene)` (reads); `optics_save_scene(project_id,version,scene)`, `optics_apply_design(project_id,version,scene?,parameter_updates?,note?)` (writes). Existing get/save/export/import preserve scene. Tool descriptions make budgets, paraxial ray fans and real optical simulation distinct. Add meaningful transport/tool tests and update portable bridge Skill/docs.

## Frontend

Own web/index.html, app.js, styles.css, optional `optical-view.js`/`optical-view.css` (root updates serving/packaging). Integrate scene panel into current selected project, include 2D + rotatable projected 3D, clickable optical elements, parameter inspector, add/remove lens/flyeye/prism/aperture, editable bounded source ray fan, preview and save. Symbols labeled, ray clipping visible, show scale/legend/model scope. Scene edits use dirty/version safeguards; do not lose current scalar form edits. HTTP polling observes external MCP changes; refresh automatically only if no unsaved input, otherwise show explicit update notice.

AI pane supports built-in OpenAI chat and current Codex/MCP guidance with copyable command including project id. Never pretend copy sends to Codex or an unconfigured API is answering. Display API configured state, action results/version, natural language assistant text via textContent. Call root endpoints above. CSP has no inline JS/CSS/CDN dependencies. Focus on an attractive functional optical workspace, not a static diagram.

## Validation

All automated fixtures are synthetic. Tests cover optical mathematics, scene validation, versioned persistence, HTTP protections, real stdio MCP transport and simulated Responses tool calls. Live API authentication and model execution must be verified separately from simulated transport. Private knowledge, configurations and database files remain outside public artifacts.
