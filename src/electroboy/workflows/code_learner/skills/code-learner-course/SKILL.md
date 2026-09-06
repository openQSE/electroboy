---
name: code-learner-course
description: Convert validated Code Learner knowledge records into an evidence-grounded Architecture, Module, or Function course. Do not use for repository-wide discovery.
---

# Code Learner Course

Create one scoped course from validated knowledge. Teach concrete behavior,
relationships, constraints, and tradeoffs; do not perform repository-wide
rediscovery or invent facts for narrative completeness.

## Operating Contract

- Read the canonical course schema and supplied Phase 3 source, component,
  module, relationship, and scoped knowledge manifests.
- Emit strict document/section JSONL only, with Markdown in section bodies.
- Link every section and diagram to knowledge IDs and source evidence.
- Preserve uncertainty from the knowledge model.
- Keep sections slide-sized while providing enough detail for a real lesson.
- Treat the supplied frozen Phase 3 manifests and scoped knowledge as the
  factual boundary. Do not assume a generic entity graph is canonical. Read only the
  source references it names for targeted verification. Do not inspect
  ElectroBoy implementation code, validators, tests, other courses, or
  unrelated repository files to discover more context or infer output fields.
- If evidence is missing, preserve that limitation explicitly while producing
  the most useful grounded course supported by the validated input.
- Never restart component discovery, component reconciliation, module
  synthesis, or relationship generation from a course invocation.

## Mode Routing

Read [course-schema.md](references/course-schema.md),
[layered-navigation.md](references/layered-navigation.md), and
[mermaid-guidelines.md](references/mermaid-guidelines.md). Then read exactly one
mode reference:

- [architecture-course.md](references/architecture-course.md)
- [module-course.md](references/module-course.md)
- [function-course.md](references/function-course.md)

## Incomplete Evidence

Do not emit `knowledge_request` records from a course-building pass. Explain
material gaps as limitations without inventing facts. Targeted knowledge
expansion is a separate analysis operation and must not prevent a usable course
from being generated.
