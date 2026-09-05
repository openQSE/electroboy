# Module Course

Explain the selected module's purpose, boundary, ownership, incoming
interfaces, callers, outgoing dependencies, external systems, key data and
state, lifecycle, runtime flows, extension role, configuration, tests,
diagnostics, common changes, risks, concurrency, dynamic behavior, and
important symbols.

Set document `coverage_topics` to include `purpose`, `interfaces`,
`dependencies`, `internals`, `state`, `flows`, `tests`, `changes`, and `risks`.
Assign each section the corresponding `topic`; every topic must have
substantive evidence-grounded material, though one section may address related
concerns together.

Select diagrams from evidence, not a fixed list. Every Mermaid syntax supported
by the installed renderer is available when useful. A module may combine
component, dependency, sequence, flow, state, class, ER, C4, block, packet,
timeline, Git, requirement, architecture, or other diagrams when each answers
a different question. Never add diagrams solely to increase their count.

Use a dependency or component-style diagram for a well-connected module and a
sequence or flow diagram when ordered behavior is central. Link concrete
extension implementations separately from shared family infrastructure.
