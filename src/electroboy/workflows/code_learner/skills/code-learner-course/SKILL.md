---
name: code-learner-course
description: Convert validated Code Learner knowledge records into an evidence-grounded Architecture, Module, or Function course. Do not use for repository-wide discovery.
---

# Code Learner Course

Create one scoped course from validated knowledge. Teach concrete behavior,
relationships, constraints, and tradeoffs; do not perform repository-wide
rediscovery or invent facts for narrative completeness.

## Operating Contract

- Read the canonical course schema and supplied knowledge subgraph.
- Emit strict document/section JSONL only, with Markdown in section bodies.
- Link every section and diagram to knowledge IDs and source evidence.
- Preserve uncertainty from the knowledge model.
- Keep sections slide-sized while providing enough detail for a real lesson.
- Treat the supplied knowledge subgraph as the factual boundary. Read only the
  source references it names for targeted verification. Do not inspect
  ElectroBoy implementation code, validators, tests, other courses, or
  unrelated repository files to discover more context or infer output fields.
- If required evidence is missing, follow the request-only behavior below
  instead of guessing or embedding a knowledge request in lesson prose.

## Mode Routing

Read [course-schema.md](references/course-schema.md),
[layered-navigation.md](references/layered-navigation.md), and
[mermaid-guidelines.md](references/mermaid-guidelines.md). Read
[knowledge-request.md](references/knowledge-request.md) only when evidence may
block the requested course. Then read exactly one mode reference:

- [architecture-course.md](references/architecture-course.md)
- [module-course.md](references/module-course.md)
- [function-course.md](references/function-course.md)

## Request-Only Result

When missing knowledge prevents a grounded required section or diagram, do not
emit a partial course. Emit only one or more `knowledge_request` records using
the canonical knowledge schema supplied by ElectroBoy. The host validates and
routes those records to `codebase-analysis`, then invokes this skill again with
the enriched subgraph.
