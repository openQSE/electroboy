# Module Synthesis

Organize only the supplied frozen components into architectural modules. A
module is a teaching and architecture boundary reducible to its component
membership; it does not directly own files or symbols outside those members.

Every module needs a name, kind, purpose, responsibility, grouping rationale,
and one or more component IDs. Record primary and entry components where they
exist. Optional parent modules must form an acyclic hierarchy. Repeated
component membership requires explicit rationale, and at most one module may
claim primary status for a component. Represent intentionally ungrouped
components explicitly rather than silently omitting them.

Never invent or mutate a component ID. When source reveals a missing
component, emit a targeted `missing_component` knowledge request with hard
source references. Do not emit relationships, flows, diagrams, or course
material during module synthesis.
