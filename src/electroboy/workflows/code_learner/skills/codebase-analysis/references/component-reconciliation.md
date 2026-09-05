# Component Reconciliation

Reconcile exactly one supplied exact-symbol overlap group. Read every supplied
candidate and its referenced source. Shared symbols trigger review; they do not
prove that candidates are the same component.

The only decisions are `same` and `distinct`. Use `same` only when all
candidates form one component. Otherwise use `distinct` and return a complete
partition: candidates within one partition describe the same component, while
separate partitions remain distinct. Every candidate must appear exactly once.

Use only supplied candidate IDs, file IDs, canonical symbol keys, and source
references. Preserve aliases, candidate provenance, limitations, shared
symbols, and exclusive symbols. A distinct result records intentional overlap;
it does not create a relationship.

Do not create modules, hierarchy, relationships, runtime flows, diagrams,
courses, unrelated components, or additional repository discovery. Return one
`component_reconciliation` record only.
