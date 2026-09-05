---
name: codebase-analysis
description: Discover and reconcile source-grounded components, modules, relationships, and layered knowledge for Code Learner Phase 3. Use for bounded repository-analysis passes, not course prose.
---

# Codebase Analysis

Build source-grounded repository knowledge, not course prose. The repository
and ElectroBoy state are read-only. Return structured output to ElectroBoy,
which validates and persists it.

## Operating Contract

- Read the supplied Phase 3 schema and all input manifests before source
  inspection.
- Limit inspection to the learned repository and explicitly supplied skill,
  schema, manifest, and prior-artifact paths. Do not inspect ElectroBoy source,
  tests, caches, or unrelated host files to infer contracts or examples.
- Use the supplied run ID, revision, scope, and temporary candidate IDs.
- Emit strict JSONL only; do not write output or checkpoints directly.
- Cite exact file IDs and source-oriented symbol locators from the supplied
  evidence.
- Preserve accepted component and module IDs in later passes.
- Record uncertainty and missing evidence instead of inventing entities or
  relationships.
- Treat the full selected file manifest as scope. A branch diff or prominent
  subsystem is evidence, not the architecture boundary.
- Do not emit course documents or lesson prose.

## Pass Routing

Read only the references required for the requested pass:

- Component discovery: [repository-discovery.md](references/repository-discovery.md)
- Component reconciliation: [component-reconciliation.md](references/component-reconciliation.md)
- Module synthesis: [module-synthesis.md](references/module-synthesis.md)
- Layered knowledge: [layered-knowledge.md](references/layered-knowledge.md)
- Record emission: [knowledge-schema.md](references/knowledge-schema.md)
- Module relationships and flows: [relationship-types.md](references/relationship-types.md)
- Symbol grounding: [language-tooling.md](references/language-tooling.md)
- Validation and stopping: [completeness-rules.md](references/completeness-rules.md)

Perform only the pass named by the invocation. Component discovery must not
emit modules, relationships, diagrams, or courses. Reconciliation decides only
`same` or `distinct`. Later passes may consume frozen manifests but may not
silently add endpoints. Stop after the bounded contract is satisfied or a
diagnostic records what remains unresolved.
