# Connect skills and plugins to the local workbench

The web UI and MCP server use the same `Workbench` Python core and SQLite data. Install the repository in the Python environment used by your MCP client:

```sh
python -m pip install -e .
python -m optics_workbench.mcp_server --help
```

The server uses only Python's standard library. No separate workbench API key or optical-software license is needed for parameter budgets or paraxial scene previews driven by the connected Codex/host model. It does not start a web server or run LightTools/Zemax. The web UI's optional built-in AI chat is a separate server-side API integration.

## Codex connection

Use the installed environment's Python executable. A virtual environment's absolute interpreter path is usually preferable when several Python installations exist. The path below is a placeholder to replace locally; do not commit your actual configuration or private paths.

```toml
[mcp_servers.optics_workbench]
command = "python"
args = ["-m", "optics_workbench.mcp_server"]
env_vars = ["OPTICS_WORKBENCH_CONFIG", "OPTICS_WORKBENCH_DATA"]
startup_timeout_sec = 20
tool_timeout_sec = 120
```

Equivalent basic CLI registration:

```sh
codex mcp add optics_workbench -- python -m optics_workbench.mcp_server
codex mcp list
```

Set `OPTICS_WORKBENCH_CONFIG` to your local configuration file and `OPTICS_WORKBENCH_DATA` to the same data directory used by the web UI, or pass `--config` and `--data-dir` explicitly in `args`. Arguments take precedence over environment variables. Configure and test the chosen Python command locally before enabling it in the client. These configuration fields and registration commands follow [official Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli).

## Portable plugin

The `plugin/` directory contains a root `plugin.json`, `mcp.json` and one skill. The manifests follow the [Agent Plugins plugin schema](https://agent-plugins.org/schemas/1.0.0/plugin.schema.json) and [stdio MCP schema](https://agent-plugins.org/schemas/1.0.0/mcp.schema.json). This distribution requires the workbench package to be installed in the selected Python environment first; the plugin is not a bundled Python runtime.

Copy/import that directory using a host that supports local Agent Plugins. Its default command is `python -m optics_workbench.mcp_server`. Configure your own interpreter and local data settings for that host, and keep those changes private. A host that lacks plugin import can connect the same command directly as a stdio MCP server, then install/copy the skill separately. Host import and startup behavior must be checked on each target machine.

This repository is suitable for GitHub code distribution. It is not a claim of acceptance in a hosted plugin directory. The [official plugin packaging guidance](https://developers.openai.com/plugins/build/plugins) distinguishes portable package structure, local installation and public-directory submission. Local stdio does not automatically make a personal database reachable from another device or from hosted ChatGPT.

## Available operations

| Area | Tools | Effect |
| --- | --- | --- |
| Coverage | `optics_stats`, `optics_search_documents`, `optics_get_document` | Read indexed metadata and provenance |
| Components and rules | `optics_search_components`, `optics_search_knowledge`, `optics_get_reference`, `optics_search_models` | Read configured candidates, rules and model metadata |
| Prototype reading | `optics_list_prototypes`, `optics_get_prototype` | Read saved parameter projects |
| Optical scene | `optics_get_scene`, `optics_trace_scene` | Read or preview a bounded, deterministic paraxial ray fan without saving |
| Scene and design writing | `optics_save_scene`, `optics_apply_design` | Save a scene or atomically update scene and scalar parameters using the current version |
| Budget | `optics_calculate_budget` | Compute without saving; no ray tracing |
| Prototype writing | `optics_create_prototype`, `optics_save_prototype`, `optics_import_prototype` | Write local projects |
| Migration | `optics_export_prototype` | Return portable JSON; no file-path argument |
| Refresh | `optics_sync_knowledge` | Refresh local indexes from preconfigured sources |

Results contain `content` with serialized JSON. Successful modern and 2025 responses also provide `structuredContent: {"data": ...}`; 2024 clients receive text. Call `optics_create_prototype` with `{"template":"dlp","name":"Demo A"}`, edit the returned project's `parameters`, then call `optics_calculate_budget` or `optics_save_prototype` with `{"project": ...}`. Saving uses the project's optimistic `version`; stale versions fail rather than silently overwriting.

## Scene editing from Codex or another MCP host

The current catalog has 27 tools. Start by reading `optics_get_prototype` and `optics_get_scene` for the same project ID. `optics_get_scene` returns `{project_id, version, scene, trace}`; older projects get an unsaved default scene. The web UI reads the same project store when both processes use the same local configuration.

| Tool arguments | Result and persistence |
| --- | --- |
| `optics_get_scene({project_id})` | Scene envelope, current version and preview; no project write |
| `optics_trace_scene({scene})` | Validated deterministic ray fan; no project write |
| `optics_save_scene({project_id, version, scene})` | Complete project, one new version; budget parameters preserved |
| `optics_apply_design({project_id, version, scene?, parameter_updates?, color_budget?, note?})` | Complete project, one atomic new version; include a scene or parameter update, optional note ≤2000 characters |

`version` is the expected current positive integer, not the desired new version. A stale write returns a tool error. Reread and reconcile the latest project instead of blindly retrying. Unknown parameter names or invalid scene fields are rejected by the shared core; a failed combined update does not partially save either part. `--read-only` advertises both scene read tools and blocks both scene write tools, including direct calls to hidden tools.

Scenes use schema version 1 and mm on an unfolded longitudinal axis. Preserve the IDs returned by `optics_get_scene`. Elements contain `id`, `kind`, `label`, `z_mm`, `aperture_mm`, `width_mm` and optional `y_mm`; lens/flyeye elements additionally require `focal_mm`, flyeyes require `pitch_mm`, and prisms require `bend_deg` of 0 or 90. Exactly one source is first and one screen last; the engine validates the ordered, finite bounded geometry and rejects unknown fields. Ray settings contain `half_angle_deg`, `rays_per_point`, `source_points` and `wavelength_nm`. The engine limits angles to 15°, rays per source point to 21 and source points to 9.

For a synthetic preview, pass this object as the `scene` argument:

```json
{
  "schema_version": 1,
  "units": "mm",
  "elements": [
    {"id":"source","kind":"source","label":"Demo source","z_mm":0,"aperture_mm":1,"width_mm":1},
    {"id":"lens","kind":"lens","label":"Lens symbol","z_mm":20,"aperture_mm":10,"width_mm":2,"focal_mm":20},
    {"id":"screen","kind":"screen","label":"Target","z_mm":40,"aperture_mm":10,"width_mm":1}
  ],
  "rays": {"half_angle_deg":5,"rays_per_point":5,"source_points":3,"wavelength_nm":550}
}
```

The trace result identifies `kind: "paraxial_ray_fan"`, normalized `scene`, ray points and blocked/reached states, a summary, warnings and assumptions. It uses a first-order thin-lens slope law and cell-local flyeye approximation. Lens shapes are symbols, and prism folding is ideal display geometry without Snell/coating calculation. **Ray-count ratios are not optical efficiency.** These previews do not calculate diffraction, polarization, spectral throughput or validated manufacturing prescriptions.

Scene geometry and scalar budget parameters remain independent. Changing one does not automatically rewrite the other. Use `optics_apply_design` to make intended changes to both explicit. Exports keep portable schema version 1 and include `project.scene` when saved; imports validate and preserve it. A legacy full-project save that omits `scene` retains the existing saved scene.

## Protocol implementation and limits

Checked against official specifications on 2026-10-09:

- Modern `2026-07-28`: `server/discover`, `tools/list` and `tools/call`; each request supplies protocol version and client capabilities in `params._meta`. Results include `resultType`, server identity, and list/discovery cache hints. See [versioning](https://modelcontextprotocol.io/specification/2026-07-28/basic/versioning), [request metadata](https://modelcontextprotocol.io/specification/2026-07-28/basic) and the [schema](https://modelcontextprotocol.io/specification/2026-07-28/schema).
- Legacy `2025-11-25`, `2025-06-18`, `2024-11-05`: `initialize`, `notifications/initialized`, `ping`, `tools/list`, `tools/call`. An unsupported initialize version receives the implemented `2025-11-25` version for client acceptance/rejection. See the [legacy lifecycle](https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle).
- UTF-8 newline-delimited JSON-RPC over stdin/stdout; logging goes to stderr; EOF closes the process. This follows the official [stdio transport](https://modelcontextprotocol.io/specification/2026-07-28/basic/transports/stdio). The HTTP UI's `/api` routes are not MCP endpoints.
- Tools are the only advertised capability. Resources, prompts, subscriptions, task extensions, sampling, elicitation, OAuth and Streamable HTTP are not implemented. Operations run synchronously; cancellation cannot interrupt a core calculation or an already-started index refresh. Closing stdin exits after the current operation finishes.
- Requests are limited to 2 MiB each. Batches, duplicate JSON keys, malformed UTF-8, non-finite numbers and invalid argument types fail explicitly. Unknown methods/tools return JSON-RPC errors; domain validation and optimistic-save conflicts return tool `isError: true`, following [tool error handling](https://modelcontextprotocol.io/specification/2025-11-25/server/tools).

Example modern discovery request (one physical line):

```json
{"jsonrpc":"2.0","id":1,"method":"server/discover","params":{"_meta":{"io.modelcontextprotocol/protocolVersion":"2026-07-28","io.modelcontextprotocol/clientCapabilities":{},"io.modelcontextprotocol/clientInfo":{"name":"example-client","version":"1"}}}}
```

The project tests exercise request framing, both protocol eras, validation, read-only mode and real temporary-database create/export/import workflows. Scene tests also exercise actual stdio subprocess calls, optimistic conflicts, atomic scene/parameter changes and optional-scene migration. All fixtures are synthetic; these tests do not use a production database or private source files. Passing these tests does not mean the server has passed the full official conformance suite or every host's integration tests.

Run the dependency-free suite with `python -m unittest discover -s tests -p test_mcp.py -v`. During development on 2026-10-09, an additional check using the official Python MCP SDK 1.26.0 completed legacy initialization, discovery of 15 tools, prototype creation, calculation, export and import through an actual subprocess. Modern discovery/list/call responses were validated against the official `2026-07-28` JSON Schema; this is schema validation, not a modern SDK end-to-end certification. Both portable manifests were also checked against their fetched official schemas.

## Data boundary

MCP only accesses the locally configured workbench. No tool runs arbitrary code, downloads files, accepts new source filesystem paths, modifies original documents or publishes anything. `--read-only` removes mutation tools; startup may still initialize the local database, so this flag is not an operating-system filesystem sandbox.

Private record text and source locations returned by read tools can be sent to the MCP client's model provider as tool context. Choose the data sources and client accordingly. An export excludes source text and machine paths, but user-entered names, notes and scene labels may themselves be confidential: review the exported JSON before public sharing. Private knowledge/database migration is an explicit separate transfer, not part of a public plugin package.

## Color and brightness

Read `optics_list_color_cases` and `optics_get_color_case(case_id)` for local reviewed evidence, cache/recalculation comparisons and source scope. Public-only installations offer a synthetic case. For a project read `optics_get_color_budget(project_id)`; its `saved` flag distinguishes an unsaved default. Edit a copy of `budget`, preview with `optics_calculate_color_budget(budget)`, then save with `optics_save_color_budget(project_id, version, budget)` or the optional `color_budget` argument of `optics_apply_design`. The complete budget and recomputed result are versioned together. Scene and scalar inputs are preserved.

Unknown fields, nonfinite inputs, impossible automatic white points and stale versions fail without partial saves. An average source input cannot be reverse-solved as CW timing. Keep source/receiving-plane units explicit. Neither gamut area nor ray-count ratios are optical efficiency; predicted screen lumens are not measured ANSI/CVIA. See [formulas](color-brightness.md). Export includes saved color inputs but not workbook evidence. Personal values may be present in those inputs; inspect before sharing.

## v0.4 linked design workflow

Read the current prototype and color budget before editing. `optics_search_evidence` returns bounded source snippets and review scope; `optics_create_chain_template` produces an unsaved optical-only chain starting after the specified input plane; `optics_preview_design` validates a proposed scene/parameter/color change and returns field differences without writing. `optics_calculate_color_budget` accepts optional `parameters`; linked chains require the current full parameter object and never reuse saved efficiency snapshots. Apply with the current version using `optics_apply_design`. See [the exact schema and boundaries](design-workflow.md).
