# Phase 3 Analysis Records

The supplied JSON Schema is authoritative. Emit one object per line with no
Markdown fence or surrounding prose. Use the exact repository revision.

During component discovery emit only `component_candidate` records. Candidate
IDs are invocation-local and do not become permanent identity. Include:

- candidate ID, name, kind, responsibility, confidence, and limitations
- every owned file ID
- precise symbol locators when the component is narrower than a whole file
- owned source references and supporting source references
- whether the name is source-defined or inferred

A symbol locator includes file ID, name, kind, scope when known, and inclusive
source range. Never invent a symbol ID. ElectroBoy resolves the locator against
raw Ctags and source evidence and assigns canonical comparison data.

In later passes, reuse opaque component and module IDs exactly. Emit missing
component or endpoint requests separately instead of introducing canonical
objects inline. Diagnostics are separate records and never substitute for an
invalid component, module, relationship, or knowledge record.
