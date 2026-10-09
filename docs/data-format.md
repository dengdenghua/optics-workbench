# Local data inputs

All paths in the local JSON configuration resolve relative to that file. Environment variables and `~` are expanded locally. `data_dir` holds `workbench.sqlite3`. This file contains metadata, imported notes, private paths and prototypes; it is not a public seed database. Keep backups while the server and MCP process are stopped.

## Coverage inventory

`coverage_file` is a JSON array grouped by content SHA-256. Example using deliberately synthetic content:

```json
[
  {
    "sha256": "synthetic-document-id",
    "files": [{"path": "my-documents/example.md"}],
    "bytes": 100,
    "reading_status": "registered_partial_review",
    "review_records": [
      {"record": {
        "id": "EXAMPLE-1",
        "read_scope": "Read the assumptions section; other sections remain unchecked.",
        "reference": "references/example.md"
      }}
    ]
  }
]
```

Real inventories should use the actual SHA-256, paths and status. The importer trusts the recorded read status; it does not certify the document or recompute hashes. Multiple `files` can represent duplicate paths. `unread_or_no_registered_review` and `registered_partial_review` are displayed separately. Read scope can also come from `review_scope`, `use` or `scope`. The displayed reference slug omits a leading `references/`.

## Optional distilled Skill directory

`skill_dir` supports these optional files:

- `references/**/*.md`: indexed as plain text; relative filename is its stable slug.
- `assets/model-index.csv`: UTF-8 CSV with at least a `path` column; other columns are retained as metadata. Indexing does not parse or open the native model.
- `assets/component-catalog.json`: optional historical candidate catalog below.

```json
{
  "collimators": [{
    "name": "Synthetic collimator",
    "source_id": "EXAMPLE-2",
    "source_sheet": "Demo",
    "source_row": 2,
    "fields": {"G": {"header_as_recorded": "EFL at 550 nm", "value": 15, "cell": "G2"}}
  }],
  "flyeyes": [],
  "prisms": []
}
```

This adapter preserves the historical catalog's column mapping: collimator `G` is an EFL candidate; flyeye `L` is EFL and `N` may describe dimensions with `x-1.0 y-0.6`. Do not reuse these mappings for a different spreadsheet layout without adapting the importer. Flyeye dimensions may suggest both pitch and clear size as an explicitly unverified starting assumption; the user must choose to apply it. Prism angle/index is not inferred. Component IDs combine kind, source ID and source row; ensure these uniquely identify the source record.

## SQLite and migration

The version 1 structure is maintained in `optics_workbench/schema.sql`: `metadata`, `documents`, `components`, `knowledge`, `models`, `projects`, `project_revisions`. Imported tables refresh in one transaction; project revisions are retained. Invalid/missing configured sources fail before replacing imported rows.

The JSON prototype envelope uses `schema: "optics-workbench.prototype"` and `schema_version: 1`. It carries user parameters and notes, not original source files. Import assigns a new ID and recalculates outputs. Unknown component references become a migration note. File paths contained in a user's notes are not sanitized; exports must be reviewed before public sharing.

New database versions must implement explicit migrations. The current release does not have a server-to-server sync or database format upgrader.
