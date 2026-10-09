# Connect skills and plugins to the local workbench

The web UI and MCP server use the same `Workbench` Python core and SQLite data. Install the repository in the Python environment used by your MCP client:

```sh
python -m pip install -e .
python -m optics_workbench.mcp_server --help
```

The server uses only Python's standard library. No API key or optical-software license is needed for parameter calculations. It does not start a web server or run LightTools/Zemax.

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
| Budget | `optics_calculate_budget` | Compute without saving; no ray tracing |
| Prototype writing | `optics_create_prototype`, `optics_save_prototype`, `optics_import_prototype` | Write local projects |
| Migration | `optics_export_prototype` | Return portable JSON; no file-path argument |
| Refresh | `optics_sync_knowledge` | Refresh local indexes from preconfigured sources |

Results contain `content` with serialized JSON. Successful modern and 2025 responses also provide `structuredContent: {"data": ...}`; 2024 clients receive text. Call `optics_create_prototype` with `{"template":"dlp","name":"Demo A"}`, edit the returned project's `parameters`, then call `optics_calculate_budget` or `optics_save_prototype` with `{"project": ...}`. Saving uses the project's optimistic `version`; stale versions fail rather than silently overwriting.

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

The project tests exercise request framing, both protocol eras, validation, read-only mode and real temporary-database create/export/import workflows. Passing these tests does not mean the server has passed the full official conformance suite or every host's integration tests.

Run the dependency-free suite with `python -m unittest discover -s tests -p test_mcp.py -v`. During development on 2026-10-09, an additional check using the official Python MCP SDK 1.26.0 completed legacy initialization, discovery of 15 tools, prototype creation, calculation, export and import through an actual subprocess. Modern discovery/list/call responses were validated against the official `2026-07-28` JSON Schema; this is schema validation, not a modern SDK end-to-end certification. Both portable manifests were also checked against their fetched official schemas.

## Data boundary

MCP only accesses the locally configured workbench. No tool runs arbitrary code, downloads files, accepts new source filesystem paths, modifies original documents or publishes anything. `--read-only` removes mutation tools; startup may still initialize the local database, so this flag is not an operating-system filesystem sandbox.

Private record text and source locations returned by read tools can be sent to the MCP client's model provider as tool context. Choose the data sources and client accordingly. An export excludes source text and machine paths, but user-entered names/notes may themselves be confidential: review the exported JSON before public sharing. Private knowledge/database migration is an explicit separate transfer, not part of a public plugin package.
