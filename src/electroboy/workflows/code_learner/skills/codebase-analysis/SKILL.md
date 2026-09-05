---
name: codebase-analysis
description: Build or enrich a durable, source-grounded knowledge graph for an unfamiliar code repository. Use for Code Learner discovery and targeted knowledge requests, not for writing lessons.
---

# Codebase Analysis

Build verified repository knowledge, not course prose. Treat the repository as
read-only except for the ElectroBoy state paths explicitly supplied in the
invocation.

## Operating Contract

- Read the canonical knowledge schema named by the invocation before emitting
  records.
- Use the supplied run ID, repository revision, scope, and output paths.
- Emit strict JSONL only. Preserve stable IDs from existing records.
- Attach repository-relative source references to behavioral claims.
- Record uncertainty, exclusions, and unresolved dynamic behavior as
  diagnostics. Never invent a relationship to make the graph complete.
- Append concise progress and heartbeat records to the supplied progress path.
- Persist the supplied checkpoint after every validated pass so another fresh
  invocation can continue without hidden conversation history.
- Use fresh source evidence rather than treating the active branch diff or one
  prominent subsystem as the repository architecture.
- Do not write Architecture, Module, or Function lessons.

## Pass Routing

Read only the references required for the requested pass:

- Inventory or module discovery: [repository-discovery.md](references/repository-discovery.md)
- Record emission or enrichment: [knowledge-schema.md](references/knowledge-schema.md)
- Relationship or runtime-flow analysis: [relationship-types.md](references/relationship-types.md)
- Symbol discovery: [language-tooling.md](references/language-tooling.md)
- Validation or stopping: [completeness-rules.md](references/completeness-rules.md)

For an enrichment request, inspect only the requested entity and the smallest
caller, callee, relationship, flow, or source neighborhood needed to resolve
it. Stop after the requested facts are supported or a diagnostic explains why
they cannot be established.
