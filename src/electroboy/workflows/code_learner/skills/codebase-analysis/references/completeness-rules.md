# Completeness Rules

Before returning a pass, verify record types, temporary or canonical IDs,
repository revision, file IDs, symbol locators, and source ranges. Do not emit
records belonging to a later pass.

Component discovery should inspect the complete selected file manifest, but it
does not have to force every file into a component. ElectroBoy computes file
coverage afterward and may request one focused missing-file investigation.
Classify build, CI, packaging, release, and repository tooling explicitly when
asked. Leave a file unresolved rather than inventing a component.

Report uncertainty and unsupported dynamic behavior. A bounded pass may finish
with diagnostics. Remaining discrepancies reduce confidence or course coverage
but do not require repository-wide retries or prevent ElectroBoy from building
a useful course from validated records.
