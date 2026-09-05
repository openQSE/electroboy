# Phase 3 Analysis Records

The supplied JSON Schema is authoritative. Emit one object per line with no
Markdown fence or surrounding prose. Use the exact repository revision.

During component discovery emit only `component_candidate` records. Candidate
IDs are invocation-local and do not become permanent identity. Every record
must include:

- `schema_version`, `record_type`, `analysis_run_id`, and
  `repository_revision`
- `candidate_id`, `name`, `name_origin`, `kind`, and `responsibility`
- `file_ids`, `symbols`, `owned_source_refs`, and `supporting_source_refs`
- `confidence` and `limitations`

`name_origin` is exactly `source_defined` or `inferred`. `confidence` is
exactly `verified`, `high`, `medium`, `low`, or `unknown`; never emit a numeric
confidence score. `limitations` is an array of strings and may be empty.

Every source reference in `owned_source_refs` and `supporting_source_refs` has
`file_id`, positive inclusive `start_line`, positive inclusive `end_line`, and
a non-empty `reason`. Use `reason`, never `role`. A candidate must have at
least one owned source reference. The supporting array is required but may be
empty.

A symbol locator includes `file_id`, `name`, `kind`, positive inclusive
`start_line`, positive inclusive `end_line`, and `scope`, `language`, and
`signature` when known. The `symbols` array is required but may be empty when
the component owns complete files. Never invent a symbol ID. ElectroBoy
resolves the locator against raw Ctags and source evidence and assigns
canonical comparison data.

In later passes, reuse opaque component and module IDs exactly. Emit missing
component or endpoint requests separately instead of introducing canonical
objects inline. Diagnostics are separate records and never substitute for an
invalid component, module, relationship, or knowledge record.
