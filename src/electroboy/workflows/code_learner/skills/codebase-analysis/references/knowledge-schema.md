# Knowledge Schema

The invocation identifies the canonical JSON Schema and existing knowledge
streams. The schema is authoritative; this reference explains how to use it.

- Emit one JSON object per line with no Markdown fence or surrounding prose.
- Use stable lowercase dot-separated IDs based on concept identity, not list
  position.
- Keep entities, typed relationships, ordered runtime flows, diagnostics, and
  knowledge requests as separate records.
- Use `kind` for entity and relationship kinds, `from_id` and `to_id` for
  relationship endpoints, and the manifest's top-level count fields exactly as
  named by the schema. Do not invent aliases for canonical fields.
- Reuse an existing ID when the concept still exists. Replace or deprecate its
  evidence instead of creating a duplicate.
- Use the exact run ID and repository revision supplied by ElectroBoy.
- Source references must include a repository-relative path, valid inclusive
  line range, and a concise statement of what that range proves.
- Use confidence to distinguish verified facts from high, medium, low, or
  unknown inference.
- Keep language-specific details in `attributes`; do not weaken common fields.

An enrichment response contains only added, revised, deprecated, diagnostic,
or resolved-request records for its scope. It does not repeat the whole graph.
