# Code Learner Phase 3 Requirements

## Status

This document defines the Phase 3 direction for the ElectroBoy Code Learner
workflow. It builds on `docs/requirements-code-learner.md` and preserves the
Phase 2 course, rendering, navigation, progress, and contextual tutor goals.
It replaces the Phase 2 entity-first knowledge-building pipeline with a
simpler source-manifest, component, module, and course pipeline.

Phase 3 is a substantial refactor. Existing Phase 2 behavior must remain
characterized while the new boundaries are introduced. Implementation must
proceed in the checklist order at the end of this document and be committed at
the end of each functional boundary.

## Purpose

Code Learner must use AI to interpret an arbitrary source repository and teach
its architecture, modules, and important functions. ElectroBoy must constrain
that interpretation to concrete files and symbols without trying to recreate a
compiler, prove the complete program, or become the author of the repository's
architectural abstractions.

The Phase 3 pipeline is:

```text
Repository source manifest
  -> Universal Ctags evidence capture
  -> AI component discovery
  -> symbol-overlap reconciliation
  -> file-disposition coverage and one missing-file investigation
  -> reconciled component manifest
  -> AI module synthesis
  -> module relationship generation
  -> horizontal and vertical architecture knowledge
  -> horizontal and vertical module knowledge
  -> eager and on-demand function knowledge
  -> rendered courses and contextual tutoring
```

## Motivation

The Phase 2 pipeline allowed separate AI passes to create and reference a
general entity graph. That created several sources of drift:

- an AI pass could introduce an abstraction that no earlier pass had defined
- later passes could use a different name or ID for the same concept
- a retry could regenerate broad knowledge instead of repairing one rejected
  record
- inferred architectural categories could become canonical dependency targets
- one invalid reference could reject a large otherwise useful response
- a writable AI runtime could bypass ElectroBoy validation and modify durable
  knowledge directly
- a valid domain JSON object could be mistaken for an agent response envelope

Phase 3 limits canonical source truth to repository files and verifiable raw
symbol evidence. The AI continues to create the architectural interpretation,
but every component it creates must reference concrete files and resolved
symbol locators.

## Governing Principles

1. ElectroBoy owns source enumeration, source-reference validation, durable
   storage, orchestration, rendering, and progress.
2. The AI owns the semantic interpretation that identifies components,
   composes modules, explains relationships, and authors learning material.
3. ElectroBoy does not semantically create components or modules.
4. Every AI component must reference real files from the source manifest and,
   where applicable, symbol locators resolved against source evidence.
5. File overlap alone never triggers component consolidation.
6. Shared canonical symbol location is the only automatic trigger for component
   reconciliation.
7. Component reconciliation decides only whether candidates are the same or
   distinct. It does not create relationships.
8. Modules are AI-authored compositions of reconciled components.
9. Relationships are generated only after the module manifest is frozen.
10. Course prose and diagrams are projections of reconciled components,
    modules, relationships, and source evidence.
11. Initialization does not require configuring, compiling, linking, or
    executing the learned repository.
12. Universal Ctags is the initial source-symbol provider. Compiler,
    language-server, Tree-sitter, Cscope, or runtime evidence may be added
    later as optional enrichment; none is required for the initial Phase 3
    implementation.
13. AI runtimes used for analysis and course generation are read-only with
    respect to repository and ElectroBoy state.
14. Only ElectroBoy persists validated AI output.
15. Uncertainty is retained and displayed rather than repaired by inventing
    ungrounded entities.
16. Repository understanding is best-effort. Evidence gaps and incomplete AI
    scopes are diagnostics unless they prevent creation of any usable course.
17. Every in-scope file receives an explicit component-coverage disposition,
    but unresolved files do not block course generation after one focused
    investigation pass.
18. Initialization activates a usable course in either `complete` or
    `complete_with_warnings` state. `failed` is reserved for operational or
    data-integrity failures that prevent creation of a usable course.

## Responsibility Boundary

### ElectroBoy Responsibilities

ElectroBoy must:

- enumerate the selected repository scope
- create the canonical file manifest and retain raw symbol evidence
- provide and invoke a pinned Universal Ctags toolchain
- resolve AI-provided symbol locators against raw Ctags and source evidence
- assign and validate repository-relative source references
- verify that referenced files and symbol locators exist at the analyzed
  revision
- reject unknown, stale, malformed, or out-of-scope references
- persist AI-authored component candidates without changing their meaning
- detect components that share one or more exact canonical symbol locators
- invoke a focused AI reconciliation pass for overlap groups
- apply AI `same` or `distinct` decisions deterministically
- persist the reconciled component manifest
- derive one disposition for every in-scope file
- run at most one focused AI investigation for unresolved file dispositions
- preserve unresolved files and exhausted semantic scopes as diagnostics
- enforce that modules contain only known component IDs
- enforce that relationships connect only known module IDs
- validate source evidence attached to module relationships and course claims
- checkpoint every completed boundary
- expose detailed progress, validation failures, and retry activity
- publish the terminal `complete`, `complete_with_warnings`, or `failed` state
- render course JSONL through the existing artifact and file-pane path

ElectroBoy may allocate opaque storage IDs after AI records validate. An opaque
storage ID is an address for a persisted AI-authored record; allocating it does
not mean ElectroBoy discovered or defined the component or module.

### AI Responsibilities

The AI must:

- inspect the complete selected repository scope
- interpret source organization and behavior
- identify architecturally meaningful component candidates
- cite file IDs and source-oriented symbol locators for every component
- decide whether symbol-overlapping candidates are the same or distinct
- choose component names, descriptions, kinds, and responsibilities
- synthesize modules from the reconciled component manifest
- identify and explain relationships between frozen modules
- build horizontal and vertical architecture views
- build horizontal and vertical module views
- identify important functions for eager analysis
- create detailed function material on demand
- generate evidence-grounded Mermaid diagrams
- classify files left without component ownership or supporting membership
- report missing evidence or unresolved interpretation explicitly

The AI must not:

- create repository file IDs or canonical symbol locator tuples
- reference a file or symbol locator that ElectroBoy cannot resolve
- write directly to `.electroboy/code-learner/`
- edit tracked or untracked repository files
- introduce a component during module relationship generation
- introduce a module while emitting a relationship
- resolve component overlap by inventing a relationship
- treat file overlap alone as proof that two components are duplicates
- emit a dependency endpoint that is not present in the frozen module manifest
- silently replace a source-defined name with a new inferred name
- claim compiler-grade call resolution when no such evidence exists

## Terminology

### Repository Revision

The repository revision identifies the source snapshot used for analysis. A
Git commit may be used for clean tracked content. A deterministic file
signature must be used when tracked working-tree changes are included or when
the source is not in Git.

### Source Manifest

The source manifest is ElectroBoy's canonical dictionary of concrete
repository files plus metadata that identifies the raw symbol-evidence
artifacts available for those files. It contains no architectural components,
modules, relationships, or course prose. Raw Universal Ctags JSONL remains the
symbol evidence of record; ElectroBoy does not duplicate every tag into a
second normalized symbol manifest.

### File Record

A file record identifies one source object in the selected repository scope.

```json
{
  "schema_version": 1,
  "record_type": "source_file",
  "id": "file:src/hmem.c",
  "repository_revision": "revision",
  "path": "src/hmem.c",
  "content_hash": "sha256:...",
  "size": 12345,
  "language": "c",
  "source_status": "tracked"
}
```

The `language` field is classification metadata, not an architectural claim.
The `source_status` distinguishes tracked, selected modified, generated, and
explicitly included untracked content.

### Symbol Locator

A symbol locator is the source-oriented description the AI uses to cite a
concrete language construct found in a file.

```json
{
  "schema_version": 1,
  "file_id": "file:src/hmem.c",
  "path": "src/hmem.c",
  "name": "ofi_hmem_init",
  "kind": "function",
  "scope": null,
  "start_line": 423,
  "end_line": 448
}
```

ElectroBoy resolves the locator by querying raw Universal Ctags JSONL for the
current revision. An exact match is accepted. Multiple matches require
disambiguation using scope, kind, signature, or source range. No match enters
targeted Ctags and repository-search resolution. Once accepted, ElectroBoy
stores the resolved locator and validation provenance directly in the
component or function record that uses it.

For equality and overlap detection, ElectroBoy derives a canonical locator
tuple from repository revision, file path, language, kind, scope, name, and
definition location. That tuple is a comparison key, not a separately
persisted architecture entity and not an ID supplied by the AI. Raw Ctags line
ordering and Ctags-internal fields must never become durable identity.

### Hard Source Reference

A hard source reference points to a file ID and may include a symbol locator
or a narrower source range.

```json
{
  "file_id": "file:src/hmem.c",
  "symbol": {
    "name": "ofi_hmem_init",
    "kind": "function",
    "scope": null
  },
  "start_line": 423,
  "end_line": 448,
  "reason": "Initializes each configured HMEM implementation."
}
```

A hard source reference is structurally true when ElectroBoy can resolve its
file and optional symbol locator against the current source evidence. Its
`reason` remains an AI interpretation.

### File Disposition

A file disposition records how one in-scope file participates in component
discovery. Each file receives exactly one derived disposition:

- `owned`: one or more validated components claim implementation membership
- `supporting`: no component owns it, but one or more components cite it as
  supporting evidence
- `repository_infrastructure`: build, CI, packaging, release, or repository
  tooling that is not itself an architectural component
- `excluded`: intentionally outside component coverage, with a specific reason
- `unresolved`: no validated association or accepted explanation was found

`unresolved` is a warning after the single missing-file investigation pass. It
does not authorize a catch-all component and does not block a usable course.

### Diagnostic

A diagnostic records an evidence gap, quarantined scope, failed operation, or
resolved attempt without turning it into course content.

```json
{
  "schema_version": 1,
  "id": "diagnostic:unresolved-file:0014",
  "repository_revision": "revision",
  "severity": "warning",
  "active": true,
  "scope_type": "file",
  "scope_id": "file:src/optional_backend.c",
  "code": "unresolved_source_file",
  "attempt_count": 1,
  "message": "No validated component association was found.",
  "recovery_action": "Review or regenerate component coverage."
}
```

Supported severity values are `info`, `warning`, and `fatal`. A resolved retry
may be retained as inactive or informational history. Only active warnings
contribute to `complete_with_warnings`; an active fatal diagnostic is valid
only when no usable course can be activated and the terminal state is
`failed`.

### Component Candidate

A component candidate is an AI-authored proposal for the smallest useful
architectural construct. A component may consist of:

- one architecturally important function or method
- multiple related functions or methods
- a type and related operations
- an entire file
- multiple files
- a registered implementation
- another source-backed code unit appropriate to the repository

Not every source symbol must become a component. Components are selected for
architectural and teaching usefulness.

### Component Manifest

The component manifest is the reconciled set of AI-authored components. Every
component references source-manifest records. The manifest contains no
component relationships.

### Module

A module is an AI-authored architectural grouping of one or more reconciled
components. Components are the smallest construct available to module
synthesis. Modules provide the vocabulary used by architecture and Module
learning modes.

### Module Relationship

A module relationship is an AI-authored, source-supported connection between
two modules in the frozen module manifest. Phase 3 does not require a separate
canonical component-relationship graph.

### Horizontal Slice

A horizontal slice explains peer concepts at one abstraction level. Examples
include the repository's major modules, a module's interfaces, or important
functions within one module.

### Vertical Slice

A vertical slice follows one responsibility or behavior from a higher-level
entry point through modules, components, selected functions, state, and
external boundaries.

## Source Manifest Requirements

### Repository Scope

ElectroBoy must enumerate all files in the selected repository scope before
component discovery. Tracked files are included by default. Modified tracked
files are included with the working-tree-aware revision signature.

Ignored, generated, vendored, and untracked content must not silently become
canonical source. The source manifest must record inclusion policy and explicit
exclusions. The AI may inspect excluded metadata only when the policy permits
it, but may not cite excluded paths as component composition.

Submodules and nested repositories must be represented explicitly. ElectroBoy
must not flatten their revision or ownership into the parent repository.

### File Enumeration

File enumeration must be deterministic for a repository revision and scope.
The manifest must preserve:

- repository-relative normalized path
- content hash
- byte size
- source status
- language classification when known
- executable or symlink metadata when relevant
- exclusion reason for omitted source-shaped regions

Path IDs may be path-derived because they identify source locations rather
than semantic architecture. Paths must be normalized without exposing absolute
host paths in exportable artifacts.

### Symbol Evidence Capture

ElectroBoy must enumerate discoverable symbols with Universal Ctags as the
initial primary provider. Universal Ctags performs language parsing and emits
machine-readable JSONL tag records. ElectroBoy retains that output as evidence
and implements indexed queries over its fields; it must not implement its own
source-language parser or produce a second full normalized symbol catalog.

Universal Ctags must remain behind a replaceable `SourceSymbolProvider`
boundary so a future language server, compiler index, Tree-sitter adapter, or
other source tool can supplement or replace it without changing component,
module, course, route, or frontend code. The existing repository-search
provider remains the fallback for unsupported files and targeted recovery.

The initial Phase 3 implementation must not require:

- a successful repository build
- a generated compilation database
- compiler AST output
- object files or debug information
- a language server
- a specific editor or editor plugin
- network access

Universal Ctags is an ElectroBoy tool dependency, not a build requirement for
the learned repository. Building or installing the pinned Ctags executable
must happen before repository AI analysis and must be cached independently from
the learned repository.

The Ctags evidence should be broad enough to let the AI reference functions,
methods, classes, types, interfaces, commands, routes, and other relevant
language constructs. The source manifest must record extractor limitations
and must not claim perfect coverage for dynamic or unsupported languages.

### Universal Ctags Integration

ElectroBoy must include a Git submodule pointer to a reviewed Universal Ctags
revision under a conventional third-party source path such as:

```text
third_party/universal-ctags
```

The submodule revision must be pinned. Runtime behavior must not depend on the
current head of the upstream repository or an arbitrary system `ctags`
executable.

ElectroBoy may use a packaged executable built from the pinned source or build
the executable into an ElectroBoy-managed tool cache. It must not build the
tool inside the learned repository or place Ctags output in the learned source
tree. The cache key must include:

- Universal Ctags source revision
- target platform and architecture
- relevant build feature set
- JSON output capability

The packaged or locally built executable must include Universal Ctags JSON
support, which requires `libjansson` at Ctags build time. Preparing the tool
must not install dependencies into or otherwise modify the learned repository.

Before indexing source, ElectroBoy must verify:

- the executable identifies itself as Universal Ctags
- its version and source revision are supported
- JSON output is available
- the JSON output version is supported
- required language parsers can be listed
- the executable can process a controlled smoke-test file

Universal Ctags JSON output is JSONL. ElectroBoy must parse each tag object as
data and retain supported fields such as:

- tag name
- repository-relative path
- language
- long-form kind
- source line and end line when available
- scope name and scope kind when available
- signature or typeref when available
- file-local or other relevant tag properties
- parser and output version metadata

The adapter must ignore or diagnose unknown fields instead of depending on the
complete internal shape of one Ctags release. Ctags pseudo-tags must be used to
validate output and parser versions; they must not become source symbols.

ElectroBoy must pass the exact accepted file-manifest paths to Universal Ctags.
It must not use unconstrained recursive discovery because that could index
ignored, generated, vendored, untracked, or `.electroboy` content outside the
selected source policy.

User-level and repository-level Ctags configuration must be disabled for the
canonical indexing run. The output must depend on the pinned executable,
ElectroBoy-owned options, the exact input file list, and the repository
revision rather than ambient editor configuration.

The symbol resolver must derive a canonical locator tuple from source identity,
not raw Ctags ordering. At minimum, equality must distinguish:

```text
repository revision
repository-relative file path
qualified or scoped symbol name when available
symbol kind
definition location
```

The raw Ctags JSONL, invocation metadata, and diagnostics must remain
separately inspectable. Component discovery receives paths to the file
manifest and raw Ctags evidence plus instructions for emitting source-oriented
locators. It does not receive Ctags-internal IDs, and ElectroBoy does not
persist a redundant normalized record for every Ctags tag.

Universal Ctags output establishes that the tool located a symbol declaration
or definition. It does not establish architectural ownership, component
membership, module relationships, runtime calls, or behavioral correctness.
The AI remains responsible for those interpretations.

For a language or file that Universal Ctags does not support, ElectroBoy must
record an explicit coverage diagnostic and use repository-search or AI-supplied
source ranges for targeted symbol resolution. Unsupported parser coverage must
not silently remove the file from component discovery.

The Universal Ctags license and notices must be preserved in source and binary
distribution workflows. ElectroBoy must invoke Ctags through the process
adapter boundary rather than link its parser implementation into Code Learner.

### Missing Symbol Resolution

An AI component may identify a legitimate symbol that the initial adapter did
not enumerate. It must provide a file ID, symbol name, and source range. In
that case ElectroBoy performs a targeted symbol-resolution operation:

1. verify the file ID and source range
2. verify that the source text identifies the requested construct
3. invoke Universal Ctags against the referenced file for targeted resolution
4. use repository search when Ctags does not resolve the symbol
5. attach the resolved locator and validation provenance to the candidate
6. reject the reference or mark it unresolved when it cannot be confirmed
7. revalidate the component candidate

This operation extends the source dictionary. It does not create or modify the
component's semantic definition.

### Source Manifest Persistence

The source manifest must be written atomically and must record:

- schema version
- repository identity and revision
- scope and inclusion policy
- extractor names and versions
- file and raw tag counts
- extraction warnings and limitations
- completion status

Component discovery must not start until the manifest is structurally valid.

### File Coverage And Missing-File Investigation

After initial component discovery and reconciliation, ElectroBoy must derive a
reverse coverage map from every in-scope file to validated component owned and
supporting references. Files without either association remain unclassified
until the AI supplies an accepted `repository_infrastructure` or `excluded`
disposition. All others become `unresolved`.

The coverage report must include:

```text
in_scope_count
owned_count
supporting_count
repository_infrastructure_count
excluded_count
unresolved_count
unresolved_file_ids
```

ElectroBoy must perform exactly one focused missing-file investigation when
the initial report contains unresolved files. Before that invocation it must
persist an investigation context bundle that inventories all Phase 3
information collected up to that checkpoint and references the authoritative
artifacts containing it:

- repository identity and revision
- source manifest and complete file records
- raw Universal Ctags JSONL and invocation metadata
- validated component candidates and validation results
- overlap groups and accepted reconciliation records
- current reconciled component records
- current file dispositions and unresolved file IDs
- prior diagnostics and attempts relevant to those files
- current checkpoint and completed-scope metadata
- schemas for permitted investigation output

The prompt must point to these persisted artifacts rather than duplicate their
contents. It must instruct the AI to treat them as the current authoritative
working set, read the complete context bundle before investigating, inspect
source only where needed, and avoid rediscovering the repository from scratch
if its conversation context was compacted or a new AI session was started.

For each unresolved file, the AI may:

1. add it as owned evidence to an existing component
2. add it as supporting evidence to an existing component
3. propose a new component grounded in file and symbol locators
4. classify it as repository infrastructure with a reason
5. classify it as excluded with a reason
6. leave it unresolved with an explanation

New or amended component candidates must pass the normal source validation,
overlap detection, and reconciliation paths. ElectroBoy then recomputes file
coverage once. It must not start a second repository-wide or missing-file AI
pass during the same initialization.

Remaining unresolved files are persisted as warning diagnostics. They do not
prevent module synthesis, course rendering, or activation. ElectroBoy must not
create or accept a `miscellaneous`, `unclassified`, or equivalent catch-all
component solely to force the unresolved count to zero.

## Component Discovery Requirements

### Invocation

Component discovery is a dedicated AI invocation or bounded set of AI
invocations. It receives:

- repository root
- repository revision
- path to the source manifest
- path to the component-candidate schema
- explicit instructions to inspect the full selected scope
- explicit instructions to return source-backed candidates only
- explicit read-only and no-direct-persistence rules

The source manifest is provided by path. ElectroBoy must not duplicate a large
file and symbol dictionary in every prompt.

### Candidate Contract

Each candidate must include:

- invocation-local candidate ID
- AI-proposed name
- component kind
- concise responsibility
- one or more file IDs
- zero or more symbol locators
- owned source references
- supporting source references where needed
- name basis and its source reference when a source-defined name exists
- confidence and unresolved limitations

```json
{
  "schema_version": 1,
  "record_type": "component_candidate",
  "candidate_id": "candidate-17",
  "name": "CUDA HMEM backend",
  "kind": "backend",
  "responsibility": "Implements HMEM operations for CUDA memory.",
  "file_ids": [
    "file:src/hmem_cuda.c"
  ],
  "symbols": [
    {
      "file_id": "file:src/hmem_cuda.c",
      "name": "cuda_hmem_init",
      "kind": "function",
      "start_line": 390
    },
    {
      "file_id": "file:src/hmem_cuda.c",
      "name": "cuda_copy_to_hmem",
      "kind": "function",
      "start_line": 250
    }
  ],
  "owned_source_refs": [],
  "supporting_source_refs": [
    {
      "file_id": "file:src/hmem.c",
      "start_line": 66,
      "end_line": 86,
      "reason": "Associates the CUDA interface with its implementation."
    }
  ],
  "name_basis": "source-defined",
  "confidence": "high",
  "limitations": []
}
```

The candidate ID is temporary and has meaning only within the discovery run.

### Component Granularity

The AI should choose the smallest component granularity that remains useful
for architecture and teaching. It must avoid both extremes:

- one component per source symbol without architectural justification
- one repository-wide component that hides meaningful responsibilities

A single function may be a component when it is independently important, such
as a dispatcher, registration function, lifecycle coordinator, algorithm, or
public entry point. Helper functions normally remain source symbols within a
larger component.

### Candidate Validation

ElectroBoy validates only structural grounding and schema conformance. It must
check:

- every file ID resolves to the current source manifest
- every symbol locator resolves against current Ctags or targeted source
  evidence
- ranges are within the referenced file
- symbol and file references are consistent
- the candidate references at least one file or symbol
- the candidate belongs to the current repository revision
- confidence and limitations use supported values
- the AI did not emit modules, relationships, diagrams, or course prose

ElectroBoy must not reject a candidate merely because it disagrees with the
AI's architectural description. Semantic conflicts are handled through scoped
AI reconciliation or later diagnostics.

### Candidate Persistence

Validated candidates must be persisted separately from the reconciled
component manifest. Raw AI output, validation results, and source-manifest
revision must remain inspectable for diagnosis.

Invalid candidates must not enter reconciliation. A candidate with a resolvable
missing symbol may enter targeted symbol resolution first. Other failures must
produce a precise validation error and a bounded repair prompt for that
candidate rather than restarting repository discovery.

## Component Reconciliation Requirements

### Reconciliation Trigger

ElectroBoy must build a reverse index from exact resolved canonical symbol
locator to validated component candidates.

```text
(revision, src/foo.c, c, function, null, blah, 40)
  -> candidate-A
  -> candidate-B
```

Candidates enter the same overlap group when they are connected by one or more
shared canonical symbol locators. The grouping may be transitive, but every
shared-symbol edge must remain visible to the reconciliation prompt and
result.

The following must not trigger reconciliation:

- shared file IDs without shared canonical symbol locators
- shared directories
- similar names
- similar descriptions
- similar component kinds
- inferred semantic similarity
- one candidate citing another candidate's file only as supporting evidence

This conservative trigger avoids treating ordinary file-level co-location as
duplication.

### Reconciliation Decision

The reconciliation AI receives:

- every candidate in one overlap group
- complete shared and candidate-exclusive symbol sets
- owned and supporting source references
- relevant source-manifest paths
- a focused instruction to read the referenced source

The only permitted semantic decisions are:

```text
same
distinct
```

Reconciliation must not create:

- dependencies
- parent-child relationships
- ownership edges
- call edges
- module membership
- runtime flows
- new components unrelated to the overlap group

For an overlap group with more than two candidates, the AI returns a partition
of candidates into same-component sets. Separate partitions are distinct.

### Same Decision

When candidates are the same component, the AI must return:

- all merged candidate IDs
- canonical component name
- retained aliases
- canonical kind and responsibility
- union of valid file IDs and resolved symbol locators
- merged owned and supporting references
- reason the candidates describe one component
- unresolved differences, if any

ElectroBoy applies the merge exactly as returned after validating that no new
source IDs were introduced.

### Distinct Decision

When candidates are distinct, the AI must return:

- the candidate partitions that remain distinct
- a concise reason for the distinction
- the shared canonical symbol locators
- the candidate-exclusive canonical symbol locators
- any clarified component names, responsibilities, and references

Both components may continue to reference the same symbol. The reconciliation
record documents that the overlap was intentional. No relationship is inferred
or persisted from that overlap.

### Reconciliation Validation

ElectroBoy must validate that:

- every candidate appears in exactly one output partition
- every output candidate ID came from the overlap group
- every referenced file and resolved symbol locator remains valid
- `same` output produces one merged component
- `distinct` output preserves two or more components
- no relationship or module records are present
- no candidate outside the overlap group is modified

Malformed or incomplete reconciliation receives a focused repair prompt. The
validated candidates and earlier reconciliation groups remain intact.

### Non-Overlapping Candidates

Candidates with no shared canonical symbol locators pass directly into the
reconciled component manifest after structural validation. ElectroBoy does not
attempt to deduplicate them by name, file, directory, or description.

This may preserve two semantically similar components with disjoint symbols.
That is preferable to ElectroBoy making an unsupported semantic merge. The AI
may group them into the same module during module synthesis.

## Reconciled Component Manifest

The component manifest is generated only after every overlap group is
reconciled or explicitly unresolved.

A component record must contain:

- opaque persisted record ID
- AI-authored canonical name
- aliases
- component kind
- responsibility
- file IDs
- resolved symbol locators and validation provenance
- owned and supporting source references
- source-defined or inferred name basis
- confidence and limitations
- originating candidate IDs
- reconciliation record IDs when applicable
- repository revision

```json
{
  "schema_version": 1,
  "record_type": "component",
  "id": "component:0042",
  "repository_revision": "revision",
  "name": "Request preparation and validation",
  "aliases": ["Request validation"],
  "kind": "processing-component",
  "responsibility": "Validates and prepares requests for dispatch.",
  "file_ids": ["file:src/foo.c"],
  "symbols": [
    {
      "file_id": "file:src/foo.c",
      "name": "blah",
      "kind": "function",
      "start_line": 40,
      "validated_by": "universal-ctags"
    },
    {
      "file_id": "file:src/foo.c",
      "name": "blah2",
      "kind": "function",
      "start_line": 75,
      "validated_by": "universal-ctags"
    }
  ],
  "origin_candidate_ids": ["candidate-A", "candidate-B"],
  "reconciliation_ids": ["reconciliation:0007"],
  "confidence": "high",
  "limitations": []
}
```

The persisted ID must not be derived from the AI-authored name. Renaming a
component must not require rewriting every downstream reference. The ID has no
architectural semantics.

The component manifest must record completion state, unresolved overlap
groups, file coverage, source-manifest revision, record counts, and generation
run ID. Candidates in an unresolved overlap group remain quarantined, but
unrelated validated components may proceed into module synthesis. An
unresolved overlap group contributes a warning rather than failing the entire
initialization.

## Module Synthesis Requirements

### Purpose

Module synthesis asks the AI to organize reconciled components into coherent
architectural modules. A module is an interpretation over components, not a
direct replacement for a file or directory.

### Invocation

The module-synthesis AI receives:

- repository root and revision
- source-manifest path
- frozen component-manifest path
- module schema path
- repository-wide scope requirement
- explicit permission to inspect source read-only
- explicit prohibition against changing component records
- explicit prohibition against generating relationships or course prose

### Module Contract

Every module must include:

- opaque persisted module ID
- AI-authored canonical name
- aliases when useful
- module kind
- purpose and responsibility
- one or more component IDs
- primary component IDs
- public or entry component IDs when applicable
- module-level source references drawn from member components
- rationale for grouping the components
- confidence and limitations
- optional parent module ID for a useful module hierarchy

Every module must be reducible to its component membership. A module may not
claim direct ownership of a file or symbol that is absent from all member
components.

Components may appear in more than one module when the AI determines that
multiple architectural views are necessary. Repeated membership must be
explicit and include a rationale. The module manifest must identify one primary
module for a component when one can be determined.

### Missing Component During Module Synthesis

If the AI discovers a missing component, it must emit a separate
`component_discovery_request` containing hard source references. It must not
silently add the component to a module.

ElectroBoy must resolve the request through targeted component discovery,
symbol-overlap reconciliation, and component-manifest revision. Only affected
module synthesis is retried.

### Module Validation

ElectroBoy must validate:

- every component ID exists in the frozen component manifest
- every module has at least one component
- every required component is assigned to at least one module or explicitly
  marked intentionally ungrouped
- primary component IDs are members of the module
- parent module IDs resolve and do not create cycles
- repeated component membership has an explanation
- module source references resolve through member components
- no relationship, diagram, or course records are mixed into the output

After validation, the module manifest is frozen for relationship generation.

## Module Relationship Requirements

### Scope

Relationships are generated only between modules in the frozen module
manifest. Phase 3 does not infer component relationships during component
discovery or reconciliation.

The AI may inspect component symbols and source to explain a module
relationship. Component and symbol references serve as evidence; they are not
promoted into a separate component relationship graph by default.

### Invocation

The relationship AI receives:

- frozen module manifest
- frozen component manifest
- source manifest
- one bounded module or module pair scope
- relevant source paths and symbols
- supported relationship vocabulary
- explicit prohibition against creating modules or components

### Relationship Contract

A relationship must contain:

- source module ID
- target module ID
- relationship kind
- concise semantic explanation
- supporting component IDs
- supporting symbol and file references
- directionality
- configuration or runtime condition when applicable
- confidence and unresolved limitations

```json
{
  "schema_version": 1,
  "record_type": "module_relationship",
  "id": "relationship:0019",
  "from_module_id": "module:0003",
  "to_module_id": "module:0011",
  "kind": "dispatches-to",
  "summary": "The HMEM dispatcher selects an implementation backend.",
  "supporting_component_ids": [
    "component:0010",
    "component:0042"
  ],
  "source_refs": [
    {
      "file_id": "file:src/hmem.c",
      "start_line": 45,
      "end_line": 169,
      "reason": "Defines the implementation dispatch table."
    }
  ],
  "confidence": "high",
  "limitations": []
}
```

### Relationship Validation

ElectroBoy must validate:

- both endpoints exist in the frozen module manifest
- supporting component IDs exist and belong to the endpoint modules unless an
  explicit shared-membership explanation is present
- every source reference resolves through the source manifest
- relationship kinds use the canonical vocabulary
- self-relationships are explicit and justified
- duplicate directional relationships are reconciled or retained with
  distinct semantics
- no new module or component IDs appear in the output

Unknown endpoints create a targeted discovery request. They must not trigger a
repository-wide retry or enter the canonical relationship set.

## Architecture Knowledge Requirements

### Architecture Purpose

Architecture knowledge explains the repository as a complete system using the
frozen module manifest, module relationships, member components, and source
references. It must not use branch-local activity as the default scope.

### Horizontal Architecture

Horizontal architecture must cover, where applicable:

- repository purpose and goals
- users and external boundaries
- public APIs, commands, events, and entry surfaces
- all major modules and their responsibilities
- module families and implementation breadth
- module dependencies and interaction categories
- build, packaging, process, deployment, and test boundaries
- state and data ownership
- important constraints, tradeoffs, and unresolved interpretation

The horizontal view must include a repository-wide Mermaid component or module
diagram. Diagram nodes must resolve to module IDs or explicitly identified
external actors. Diagram edges must resolve to accepted module relationships.

### Vertical Architecture

Vertical architecture must select important end-to-end behaviors and trace
them through:

```text
entry surface
  -> module
  -> member component
  -> selected important symbol
  -> downstream module or external boundary
  -> completion, state change, or error
```

Each vertical slice must include ordered steps, source evidence, alternate or
error behavior when relevant, and links to deeper Module or Function material.
At least one Mermaid sequence diagram is required when an ordered cross-module
flow can be established.

The AI may choose any other supported Mermaid diagram type when it clarifies
the repository. Diagrams may include flowcharts, state diagrams, class
diagrams, entity-relationship diagrams, dependency diagrams, data-flow views,
deployment views, and other supported forms. Diagram type must follow evidence
and teaching need rather than a fixed quota.

## Module Knowledge Requirements

### Horizontal Module Detail

For every generated module course, the AI must explain:

- purpose and architectural boundary
- member components and why they are grouped
- public and internal interfaces
- incoming and outgoing module relationships
- configuration and feature selection
- state and data responsibilities
- relevant tests and diagnostics
- common change paths and risks
- uncertainty and unsupported behavior
- peer modules and horizontal navigation order

### Vertical Module Detail

The module's vertical material must explain, where applicable:

- internal progression through member components
- initialization and cleanup
- normal execution paths
- alternate and error paths
- important data transformations
- concurrency or asynchronous behavior
- important functions and dispatch points
- transitions into neighboring modules
- source evidence for each major step

Module diagrams may use any Mermaid type supported by the existing renderer.
Every module diagram node must map to a module, component, symbol, state, data
object, or explicit external actor. Canonical module edges must reference
accepted module relationships.

## Function Knowledge Requirements

### Important Function Selection

Initialization may eagerly generate function knowledge for functions the AI
identifies as important, including:

- public entry points
- dispatch functions
- registration functions
- lifecycle coordinators
- cross-module call sites
- core algorithms
- state transition functions
- completion and error handlers

An important function does not need to be a component. Conversely, a
single-function component may identify that function as its primary symbol.

### Function Contract

Function knowledge must include, where applicable:

- exact resolved symbol locator and validation provenance
- owning or related component IDs
- related module IDs
- declaration, implementation, signature, and visibility
- purpose and contract
- inputs, outputs, mutations, and side effects
- local control flow and important branches
- callers, invocation conditions, and dispatch limitations
- callees and delegated responsibilities
- state and data access
- errors and cleanup
- concurrency behavior
- related tests
- links to horizontal and vertical module material
- Mermaid call or flow diagram when useful

### On-Demand Function Generation

When the user enters or selects a symbol without current function knowledge,
ElectroBoy must:

1. resolve the request against raw Ctags and targeted source evidence
2. present candidate definitions when ambiguous
3. identify related components and modules
4. invoke a narrowly scoped read-only AI analysis
5. validate every returned source, component, and module reference
6. persist and render the function course independently
7. update course links and tutor context
8. cache the result by canonical symbol locator and source revision

On-demand function generation must not restart repository initialization.

## Course Generation Requirements

The existing `code-learner-course` skill remains the course-authoring boundary,
but its inputs change from a general Phase 2 entity graph to Phase 3 manifests
and knowledge artifacts.

Course generation must:

- use separate Architecture, Module, and Function invocations
- receive frozen manifest paths instead of copied prompt-sized catalogs
- use reconciled names and IDs consistently
- preserve horizontal and vertical navigation
- connect every lesson section to source, component, module, relationship, or
  function records
- render through the existing structured JSONL-to-Markdown path
- render Mermaid through the existing file-pane renderer
- preserve slide-sized sections and deeper notes
- request targeted missing knowledge instead of inventing it

Course generation must not rerun repository-wide component discovery.

## Contextual Tutor Requirements

The existing file-backed tutor context remains required. The context file must
be updated to reference Phase 3 records:

- repository revision
- current course and section
- horizontal or vertical navigation position
- selected module ID
- selected component IDs
- selected function symbol locator
- relevant module relationship IDs
- source references
- generated artifact path

The tutor receives one bootstrap instruction requiring it to read the context
file before answering. ElectroBoy must not inject the full source, manifest, or
course context into every question.

The tutor must treat manifests as navigation and grounding. It may read the
actual source needed to answer the learner's question. Ordinary tutor answers
must not modify source or durable learner state.

## Prompt And Runtime Requirements

Every Phase 3 AI invocation must:

- name one role and one bounded output contract
- identify the repository root and revision
- provide paths to relevant canonical manifests
- provide paths to prior validated artifacts and diagnostics needed by the
  bounded stage
- explicitly invoke the appropriate packaged skill
- prohibit direct durable-state writes
- run with a read-only sandbox
- return strict structured output only
- preserve exact source-manifest IDs
- preserve validated canonical symbol locators
- report unresolved discoveries in a dedicated record type

ElectroBoy must distinguish a domain JSON record from an agent-result envelope.
A single valid component, module, relationship, or manifest JSON object must
not be converted into an empty final response.

Retries must receive:

- the exact validation failure
- the rejected record or bounded affected subset
- the current frozen input manifest
- an instruction to repair only the affected output

Retries must not receive permission to rewrite canonical files and must not
restart completed discovery scopes.

## Persistence Layout

The logical Phase 3 storage layout is:

```text
.electroboy/code-learner/
|-- source/
|   |-- manifest.json
|   |-- files.jsonl
|   |-- universal-ctags.raw.jsonl
|   |-- universal-ctags-invocation.json
|   `-- diagnostics.jsonl
|-- components/
|   |-- candidates.jsonl
|   |-- overlap-groups.jsonl
|   |-- reconciliations.jsonl
|   |-- file-dispositions.jsonl
|   |-- coverage.json
|   |-- investigation-context.json
|   |-- manifest.json
|   `-- components.jsonl
|-- modules/
|   |-- manifest.json
|   |-- modules.jsonl
|   `-- relationships.jsonl
|-- knowledge/
|   |-- architecture.jsonl
|   |-- modules/
|   `-- functions/
|-- courses/
|   |-- architecture.jsonl
|   |-- architecture.md
|   |-- modules/
|   `-- functions/
|-- checkpoint.json
|-- progress.jsonl
|-- diagnostics.jsonl
|-- attempts/
|-- initialization-result.json
`-- tutor-context.json
```

The physical implementation may combine streams behind repository interfaces,
but the logical ownership boundaries must remain independent. Candidate,
reconciliation, canonical manifest, knowledge, and rendered course records
must not share implicit mutation semantics.

All canonical writes must be atomic. AI attempt output should be retained in a
diagnostic or attempt area until validated, then promoted by ElectroBoy.

## Revision, Cache, And Invalidation

- Every manifest and generated artifact records the source revision.
- A changed file invalidates its Ctags evidence and resolved symbol locators.
- Changed or removed symbol locators invalidate components that reference them.
- Changed components invalidate containing modules.
- Changed modules invalidate their relationships and affected Architecture and
  Module knowledge.
- Unaffected component, module, relationship, and course artifacts remain
  usable.
- On-demand Function artifacts are invalidated by changes to their symbol
  source or required module context.
- `Clear Cache` removes source, component, module, relationship, knowledge,
  course, progress, checkpoint, and tutor-context artifacts.
- After cache clearing, only initialization remains enabled and all course
  outlines and learner content are empty.

Phase 2 artifacts may remain readable through compatibility adapters, but they
must not be silently mixed with a Phase 3 manifest. A project must identify its
active learner schema generation explicitly.

## Progress And Observability

Initialization progress must reflect the actual Phase 3 stages:

```text
source file enumeration
Universal Ctags evidence capture
component discovery
component candidate validation
symbol-overlap grouping
component reconciliation
file coverage
missing-file investigation when required
component manifest finalization
module synthesis
module validation
module relationship generation
architecture knowledge generation
module knowledge generation
important function generation
course rendering
activation
```

Progress must display:

- current stage and bounded scope
- active AI invocation
- meaningful streamed AI activity
- file and raw Ctags tag counts
- component candidate and validation counts
- overlap groups completed and remaining
- file disposition and unresolved-file counts
- missing-file investigation state
- reconciled component count
- module count
- relationship scopes completed and remaining
- Architecture and Module knowledge completion
- eager Function completion
- validation, persistence, rendering, and activation status
- exact retry reason and attempt number
- warning count and a concise warning summary
- terminal completion status beneath the progress bar

Progress must remain below 100 percent until all required manifests validate,
required course artifacts render, and the course is activated or the run has
ended in `failed` state.

The completion status displayed beneath the progress bar must be unambiguous:

- `complete`: the course is active and no material discrepancies remain
- `complete_with_warnings`: the course is active and diagnostics describe
  unresolved evidence or omitted scopes
- `failed`: no usable course could be activated because of an operational or
  data-integrity failure

Resolved retries may remain in the attempt log as informational history, but
they do not force `complete_with_warnings`. That state is selected when one or
more warning diagnostics remain active at termination and usable course
content was activated. `failed` always implies `course_active: false`.

The GUI must enable Architecture, Module, and Function for both successful
states. For `complete_with_warnings`, it must show the warning count and provide
access to the persisted diagnostics without presenting invalid records as
course content. For `failed`, course actions remain disabled and the GUI shows
the failed scope and recovery action.

### Terminal Initialization Result

ElectroBoy must persist one terminal result independently from transient
progress output:

```json
{
  "schema_version": 1,
  "repository_revision": "revision",
  "status": "complete_with_warnings",
  "course_active": true,
  "warning_count": 14,
  "diagnostic_ids": ["diagnostic:unresolved-file:0014"],
  "failed_scope": null,
  "recovery_action": null,
  "completed_at": "timestamp"
}
```

The status row must appear immediately beneath the progress bar after the run
terminates. It must use text and an icon in addition to color, preserve the
existing ElectroBoy color scheme, and display:

- `Complete` for `complete`
- `Complete with warnings` plus the warning count for
  `complete_with_warnings`
- `Failed` plus the affected scope for `failed`

Selecting the warning summary must expose the persisted diagnostics. Selecting
the failure summary must expose the recovery action. Neither interaction may
replace or obscure the detailed AI activity stream.

## Failure And Recovery

- One initialization job per repository revision is permitted.
- AI processes must never be the owner of canonical state writes.
- Completed source, component, reconciliation, and module boundaries survive a
  later failure.
- Component discovery, file coverage, reconciliation, module, relationship,
  knowledge, and course discrepancies are recoverable quality issues when a
  usable course can still be constructed.
- A candidate validation failure retries only that candidate or candidate
  batch.
- A reconciliation failure retries only that overlap group.
- A module validation failure retries only the affected module output.
- A relationship failure retries only the affected module or module pair.
- A course failure does not invalidate accepted manifests.
- Restart resumes from the first incomplete checkpoint boundary.
- Failed attempt output remains inspectable but never appears as canonical
  learner content.
- Validation errors must be written to progress and checkpoint state before a
  retry starts.
- The missing-file investigation runs at most once per initialization and is
  not recursively retried as repository-wide discovery.
- Exhausted semantic retries quarantine the invalid scope, write a warning,
  and allow independent downstream work to continue.
- A hard `failed` result is permitted only when an operational or
  data-integrity failure prevents creation or activation of any usable course.
- Every terminal result records the specific affected scope, diagnostics, and
  recovery action rather than reporting a generic initialization failure.

## Functional Requirements

### Source Manifest

- `CL3-SRC-1` Initialization creates a deterministic file manifest for the
  selected repository revision.
- `CL3-SRC-2` File records use normalized repository-relative paths and content
  hashes.
- `CL3-SRC-3` Initialization captures language-appropriate raw Universal Ctags
  JSONL without requiring a learned-repository build.
- `CL3-SRC-4` AI symbol locators resolve to a file and bounded source location.
- `CL3-SRC-5` Extractor identity, limitations, and coverage are persisted.
- `CL3-SRC-6` Missing AI-referenced symbols can enter targeted symbol
  resolution.
- `CL3-SRC-7` Unknown or stale file references and unresolved symbol locators
  cannot enter component records.
- `CL3-SRC-8` Ignored, generated, vendored, and untracked source policy is
  explicit.
- `CL3-SRC-9` A pinned Universal Ctags submodule is the initial primary source
  symbol provider.
- `CL3-SRC-10` ElectroBoy verifies Universal Ctags identity, JSON capability,
  output version, parser inventory, and smoke-test behavior before indexing.
- `CL3-SRC-11` Universal Ctags receives only the exact accepted file-manifest
  paths with ambient configuration disabled.
- `CL3-SRC-12` Raw Ctags JSONL remains inspectable and is queried without
  requiring a duplicated normalized symbol catalog.
- `CL3-SRC-13` Unsupported files receive explicit coverage diagnostics and a
  repository-search fallback.
- `CL3-SRC-14` Ctags source, binary, license, and notice handling is preserved
  by development and distribution workflows.

### File Coverage

- `CL3-COV-1` Every in-scope file receives one derived disposition: `owned`,
  `supporting`, `repository_infrastructure`, `excluded`, or `unresolved`.
- `CL3-COV-2` ElectroBoy computes file dispositions from validated component
  references and accepted AI classifications.
- `CL3-COV-3` Unresolved files trigger at most one focused investigation pass
  per initialization.
- `CL3-COV-4` The investigation receives persisted paths to all relevant
  collected evidence, accepted records, attempts, and diagnostics.
- `CL3-COV-5` Investigation output follows normal component validation,
  overlap detection, and reconciliation.
- `CL3-COV-6` Remaining unresolved files become warning diagnostics and do not
  prevent module or course generation.
- `CL3-COV-7` ElectroBoy does not create or accept an ungrounded catch-all
  component merely to obtain full file coverage.

### Components

- `CL3-CMP-1` Components are authored by AI interpretation, not deterministic
  ElectroBoy architecture rules.
- `CL3-CMP-2` Every component references one or more source-manifest files or
  symbols.
- `CL3-CMP-3` AI candidate IDs remain temporary until reconciliation completes.
- `CL3-CMP-4` ElectroBoy validates structural references without rewriting
  component meaning.
- `CL3-CMP-5` Invalid candidates remain isolated from the canonical component
  manifest.
- `CL3-CMP-6` Candidate repair is targeted and bounded.
- `CL3-CMP-7` A component may contain one symbol, multiple symbols, one file,
  or multiple files.
- `CL3-CMP-8` Not every symbol is required to become a component.

### Reconciliation

- `CL3-REC-1` Reconciliation candidates are detected only through exact shared
  canonical symbol locators.
- `CL3-REC-2` File, directory, name, kind, or description overlap alone does
  not trigger reconciliation.
- `CL3-REC-3` Reconciliation decisions are limited to `same` and `distinct`.
- `CL3-REC-4` Multi-candidate groups are resolved as complete partitions.
- `CL3-REC-5` A `same` decision merges candidate composition and preserves
  aliases and provenance.
- `CL3-REC-6` A `distinct` decision preserves intentional symbol overlap.
- `CL3-REC-7` Reconciliation never creates component relationships.
- `CL3-REC-8` Failed groups can be retried independently.

### Modules

- `CL3-MOD-1` Module synthesis consumes only the reconciled component manifest
  and source evidence.
- `CL3-MOD-2` Every module contains at least one known component ID.
- `CL3-MOD-3` The AI authors module names, kinds, purposes, boundaries, and
  component composition.
- `CL3-MOD-4` Missing components produce discovery requests rather than inline
  component creation.
- `CL3-MOD-5` Every required component is grouped or explicitly marked
  intentionally ungrouped.
- `CL3-MOD-6` Repeated component membership is explicit and justified.
- `CL3-MOD-7` Parent module references resolve and remain acyclic.
- `CL3-MOD-8` The module manifest is frozen before relationship generation.

### Relationships

- `CL3-REL-1` Canonical Phase 3 relationships connect modules, not unresolved
  component candidates.
- `CL3-REL-2` Relationship endpoints must exist in the frozen module manifest.
- `CL3-REL-3` Relationships include supporting component and source evidence.
- `CL3-REL-4` Relationship generation cannot introduce modules or components.
- `CL3-REL-5` Unknown endpoints produce targeted discovery requests.
- `CL3-REL-6` Relationship scopes validate and persist independently.
- `CL3-REL-7` Duplicate and contradictory module edges are explicitly
  reconciled.
- `CL3-REL-8` Dynamic or uncertain behavior remains marked as such.

### Architecture And Modules

- `CL3-ARC-1` Architecture knowledge includes horizontal repository-wide
  module coverage.
- `CL3-ARC-2` Architecture knowledge includes vertical end-to-end slices.
- `CL3-ARC-3` Architecture includes a Mermaid module/component diagram.
- `CL3-ARC-4` Architecture includes a Mermaid sequence diagram when a supported
  ordered cross-module flow exists.
- `CL3-ARC-5` Diagram nodes and canonical edges resolve to frozen records.
- `CL3-MDK-1` Module knowledge includes horizontal responsibility, interface,
  neighbor, state, configuration, test, and risk coverage.
- `CL3-MDK-2` Module knowledge includes vertical component and function flow.
- `CL3-MDK-3` Module diagrams use the existing Mermaid rendering path.
- `CL3-MDK-4` Module failures are isolated and independently retryable.

### Functions

- `CL3-FUN-1` Initialization may eagerly analyze AI-selected important
  functions.
- `CL3-FUN-2` Important-function records resolve to canonical symbol locators.
- `CL3-FUN-3` Any resolvable symbol can receive an on-demand Function course.
- `CL3-FUN-4` Ambiguous names present candidates before analysis starts.
- `CL3-FUN-5` On-demand generation uses related component and module context.
- `CL3-FUN-6` Function courses include call or flow diagrams when useful and
  supported by evidence.
- `CL3-FUN-7` On-demand Function generation does not restart initialization.
- `CL3-FUN-8` Function artifacts are cached and invalidated by source revision.

### Runtime, Storage, And UI

- `CL3-RUN-1` All analysis and course AI invocations use read-only repository
  access.
- `CL3-RUN-2` AI output cannot write canonical ElectroBoy state directly.
- `CL3-RUN-3` Domain JSON objects are not mistaken for agent envelopes.
- `CL3-RUN-4` Validation failures appear in progress before targeted retry.
- `CL3-RUN-5` Checkpoints preserve each completed functional boundary.
- `CL3-RUN-6` Exhausted semantic retries become warning diagnostics when the
  remaining validated material can produce a usable course.
- `CL3-RUN-7` Terminal initialization state is exactly `complete`,
  `complete_with_warnings`, or `failed`.
- `CL3-UI-1` Architecture, Module, and Function remain the learner modes.
- `CL3-UI-2` Horizontal and vertical navigation preserve return position.
- `CL3-UI-3` The existing Markdown and Mermaid renderer remains shared.
- `CL3-UI-4` The shared workspace Agent Input remains the only tutor composer.
- `CL3-UI-5` Tutor context references Phase 3 manifest identities.
- `CL3-UI-6` Clearing cache removes all outlines, learner output, and context.
- `CL3-UI-7` The GUI displays terminal completion status beneath the progress
  bar, including warning count or failure recovery details.
- `CL3-UI-8` Both `complete` and `complete_with_warnings` enable Architecture,
  Module, and Function; `failed` leaves them disabled.

## Quality Requirements

- Initialization must not require a successful repository build.
- File enumeration and Ctags evidence capture should complete before expensive
  AI work begins.
- The design must support repositories in arbitrary languages and mixed
  languages.
- Universal Ctags integration must remain behind reusable process-adapter and
  source-symbol-provider boundaries.
- A learned repository must never be required to build merely so Ctags can
  index its source.
- AI contexts must be bounded by one stage and relevant manifest paths.
- Component reconciliation must be deterministic apart from the explicit AI
  `same` or `distinct` decision.
- No AI pass may mutate canonical source or learner state.
- Failed scopes must be observable and independently recoverable.
- Semantic incompleteness must degrade course coverage rather than abort an
  otherwise usable initialization.
- Stable storage IDs must not encode mutable AI names.
- Source references must remain repository-relative in exportable artifacts.
- Course generation must remain useful when Universal Ctags lacks parser
  coverage for selected files or Mermaid rendering is unavailable.
- The source, component, module, relationship, course, tutor, and UI layers
  must have separate reusable domain boundaries.
- Browser routes and frontend state must not implement reconciliation,
  validation, or manifest mutation rules.

## Non-Goals

- Build, compile, link, or execute every learned repository during
  initialization.
- Add Cscope, GNU Global, compiler AST, object, linker, or runtime-trace
  dependencies to the initial Phase 3 implementation.
- Produce a formally verified architecture.
- Guarantee a complete symbol index for every language.
- Guarantee a complete static or dynamic call graph.
- Make ElectroBoy infer semantic components without AI.
- Deduplicate components based on file paths, names, or descriptions alone.
- Create component relationships during reconciliation.
- Generate full Function courses for every source symbol eagerly.
- Replace language compilers, parsers, language servers, debuggers, or
  profilers.
- Implement a second Markdown or Mermaid renderer.
- Treat AI-proposed external categories as source-defined repository entities.
- Hide unresolved candidates or relationships to make initialization appear
  complete.
- Retry missing-file investigation repeatedly until artificial full coverage
  is reached.
- Create a catch-all component solely to consume unresolved files.

## Acceptance Criteria

- A repository initializes without running its configure, build, link, or test
  commands.
- Initialization produces a revision-bound file manifest and raw Universal
  Ctags evidence artifact.
- Symbol evidence is produced primarily from a pinned Universal Ctags
  executable with supported JSON output and is queried through a resolver.
- Universal Ctags indexes only files accepted by the ElectroBoy file manifest.
- User and repository Ctags configuration cannot change canonical indexing
  output.
- Ctags pseudo-tags and unknown output fields do not become resolved symbol
  locators.
- A Ctags parser gap produces an explicit diagnostic and does not remove the
  affected source file from AI component discovery.
- Repeating Ctags indexing with the same revision, pinned tool, and options
  produces equivalent raw evidence and canonical resolver results.
- An AI component candidate referencing an unknown file is rejected before
  component persistence.
- An AI component candidate referencing a legitimate symbol missing from the
  initial index enters targeted symbol resolution.
- Two candidates that share a file but no symbols do not enter reconciliation.
- Two candidates that share a symbol enter the same overlap group.
- A multi-candidate overlap group is resolved into complete `same` or
  `distinct` partitions.
- A `same` decision creates one reconciled component and preserves aliases and
  candidate provenance.
- A `distinct` decision preserves both components and records intentional
  symbol overlap without creating a relationship.
- Non-overlapping validated candidates enter the component manifest unchanged.
- Every in-scope file receives an explicit coverage disposition.
- Initial unresolved files cause one focused AI investigation that receives
  paths to prior evidence and accepted work instead of rediscovering the
  repository from scratch.
- Files unresolved after that pass remain visible as warning diagnostics and
  do not prevent module synthesis or course activation.
- Missing-file handling does not create a catch-all component merely to claim
  complete coverage.
- Module synthesis references only reconciled component IDs.
- A missing component found during module synthesis creates a targeted request
  and cannot be inserted inline.
- Every canonical module contains at least one component.
- Module relationships reference only frozen module IDs and include source
  evidence.
- A relationship response containing an unknown endpoint is isolated and does
  not corrupt the module manifest.
- Architecture output covers all required modules horizontally and at least one
  important behavior vertically.
- Architecture diagrams resolve their module nodes and relationship edges.
- Module output provides both horizontal context and vertical implementation
  detail.
- Important functions resolve to canonical symbol locators and generate
  independent Function artifacts.
- Selecting an uncached resolvable function starts on-demand generation.
- A single domain JSON object returned by the AI remains available to the
  domain validator and is not converted into an empty response.
- An analysis AI attempting to modify `.electroboy` or repository files is
  prevented by runtime policy.
- Exact validation errors and retry scopes appear in progress output.
- Exhausted semantic retries quarantine invalid records and produce
  `complete_with_warnings` when a usable course remains.
- `complete` and `complete_with_warnings` both activate learner actions;
  `failed` does not.
- The GUI displays the terminal completion status beneath the progress bar and
  exposes warning count or failure recovery information.
- Restart resumes from the first incomplete Phase 3 scope.
- Clearing cache leaves no course outline, content, progress, checkpoint, or
  tutor context and enables only initialization.
- Existing Phase 2 course artifacts remain readable or receive explicit
  migration guidance.

## Detailed Implementation Checklist

Use this checklist as the authoritative implementation sequence. Do not begin
a later boundary while an earlier boundary has unresolved contract or test
failures. Check off an item only after implementation and verification. Commit
at the end of each boundary so the refactor remains reviewable and recoverable.

### Boundary 1: Phase 2 Characterization And Phase 3 Cutover Plan

1. [x] Record the current Phase 2 initialization stages, persisted files,
   routes, frontend states, and runtime roles.
2. [x] Identify every code path that reads or writes Phase 2 knowledge entity,
   relationship, flow, course, checkpoint, progress, and tutor records.
3. [x] Add or update characterization tests for current source revision and
   source-reference validation.
4. [x] Add characterization tests for current module discovery, relationship
   generation, Architecture generation, Module generation, and Function
   generation.
5. [x] Add a regression fixture reproducing a dangling AI-created entity ID.
6. [x] Add a regression fixture reproducing a single domain JSON object being
   mistaken for an agent result envelope.
7. [x] Add a regression fixture proving that an analysis AI cannot safely own
   canonical knowledge writes.
8. [x] Document in test names which Phase 2 behavior is retained, replaced, or
   removed by Phase 3.
9. [x] Define a feature/version switch that prevents Phase 2 and Phase 3 state
   from being mixed in one initialization run.
10. [x] Define the temporary compatibility strategy for already initialized
    Phase 2 projects.
11. [x] Confirm software-engineering and creative-writing workflows remain
    outside the refactor boundary.
12. [x] Run the complete pre-refactor Code Learner test suite and record the
    baseline result.
13. [x] Commit Phase 2 characterization tests and the Phase 3 cutover seam.

Boundary 1 validation notes:

- The pre-refactor repository suite completed with 601 passing tests and 11
  pre-existing failures: eight unrelated browser corkboard or mind-map tests,
  two software requirements session-recovery tests, and one environment-bound
  service-port assertion.
- Existing Phase 2 characterization tests cover all learner modes, source
  revision checks, malformed references, runtime read-only behavior, targeted
  retry, restart, migration, and single-record AI responses.
- `LearnerGenerationStore` detects unmarked Phase 2 state and requires an
  explicit replacement or migration before selecting Phase 3.

### Boundary 2: Phase 3 Domain Contracts And Schemas

14. [x] Define the Phase 3 source manifest schema and generation metadata.
15. [x] Define `source_file` records with normalized path, hash, size,
    language, and source status.
16. [x] Define source-oriented symbol locators, canonical comparison tuples,
    and validation provenance without a standalone normalized symbol catalog.
17. [x] Define reusable hard source-reference and file-disposition fields.
18. [x] Define `component_candidate` records and invocation-local candidate ID
    rules.
19. [x] Define overlap-group records containing exact shared-symbol edges.
20. [x] Define reconciliation input and output records with only `same` and
    `distinct` decisions.
21. [x] Define canonical component records with opaque persisted IDs, aliases,
    provenance, and reconciliation links.
22. [x] Define component-manifest metadata, file-coverage reports, warning
    diagnostics, and completion states.
23. [x] Define module records, component membership, optional hierarchy, and
    repeated-membership rationale.
24. [x] Define module-manifest metadata and freeze state.
25. [x] Define module relationship records with supporting components and
    source evidence.
26. [x] Define component-discovery, missing-file investigation, and
    missing-endpoint request records.
27. [x] Define Architecture, Module, and Function knowledge references to
    Phase 3 IDs.
28. [x] Define schema-version and learner-generation discrimination.
29. [x] Implement schema loading without coupling it to routes or rendering.
30. [x] Add valid and invalid fixtures for every Phase 3 record type.
31. [x] Test unknown IDs, stale revisions, invalid ranges, malformed
    partitions, file dispositions, terminal states, cycles, and mixed records.
32. [x] Commit Phase 3 contracts, schemas, fixtures, and validators.

### Boundary 3: Source File Manifest

33. [x] Introduce a source-manifest service independent from the Phase 2
    knowledge store.
34. [x] Enumerate tracked files for Git repositories.
35. [x] Support deterministic enumeration for non-Git source roots.
36. [x] Include modified tracked content in the repository revision signature.
37. [x] Normalize all manifest paths relative to the selected source root.
38. [x] Reject paths that escape the source root.
39. [x] Record file content hashes and sizes.
40. [x] Record symlink and executable metadata where relevant.
41. [x] Define explicit policy for ignored, generated, vendored, and untracked
    files.
42. [x] Represent nested repositories and submodules without flattening their
    revisions.
43. [x] Add language classification as non-semantic metadata.
44. [x] Write file records and source-manifest metadata atomically.
45. [x] Add query operations by file ID, normalized path, language, and status.
46. [x] Test clean, dirty, non-Git, symlink, submodule, generated, and mixed
    language fixtures.
47. [x] Test repeat generation produces identical records at the same revision.
48. [x] Commit deterministic source file manifest support.

### Boundary 4: Universal Ctags Evidence And Symbol Resolution

49. [x] Define reusable process-adapter and `SourceSymbolProvider` contracts
    independently from component, module, course, route, and frontend code.
50. [x] Add Universal Ctags as a Git submodule at the agreed third-party path,
    pin a reviewed revision, and preserve required license and notice files.
51. [x] Add a tool installer that uses a packaged pinned executable or builds
    the submodule into an ElectroBoy-managed, platform-specific cache.
52. [x] Verify executable identity, source version, JSON feature, JSON output
    version, parser inventory, and controlled smoke-test behavior.
53. [x] Invoke Ctags with ambient user and repository configuration disabled
    and pass only exact file-manifest paths.
54. [x] Capture raw Ctags JSONL and complete invocation metadata outside the
    learned source tree.
55. [x] Parse tag and pseudo-tag records with explicit output-version checks
    and tolerate compatible unknown fields.
56. [x] Build indexed raw-evidence queries over name, path, language, long
    kind, range, scope, signature, typeref, and file-local status.
57. [x] Exclude pseudo-tags from symbol matches and derive canonical locator
    tuples from source identity rather than Ctags output ordering.
58. [x] Distinguish declarations, definitions, same-name symbols, nested
    scopes, file-local symbols, and overloads as far as Ctags evidence permits.
59. [x] Record Ctags version, parser, confidence, coverage, and limitations in
    the source manifest without asserting architecture or call relationships.
60. [x] Preserve repository-search fallback and explicit diagnostics for files
    or languages unsupported by Universal Ctags.
61. [x] Implement targeted Ctags resolution for an AI-referenced missing
    symbol before requiring file, name, and source-range fallback evidence.
62. [x] Attach confirmed locator evidence to the referencing record and
    preserve an unresolved diagnostic when targeted resolution fails.
63. [x] Test C, C++, Python, and JavaScript symbols, duplicate names, nested
    scopes, file-local symbols, overloads, unsupported syntax, and parser gaps.
64. [x] Test deterministic raw evidence and resolver results, exact file-list
    enforcement, disabled configuration, cache reuse, and tool failure.
65. [x] Verify no test requires configuring or compiling a learned fixture
    repository, then commit the pinned Ctags evidence and resolver integration.

### Boundary 5: Component Discovery Skill And Prompt

66. [x] Replace the entity-first discovery guidance in `codebase-analysis`
    with Phase 3 component discovery guidance.
67. [x] Teach the skill that ElectroBoy supplies file identities and validates
    AI-authored source-oriented symbol locators.
68. [x] Teach the skill that it authors semantic component candidates.
69. [x] Require at least one hard source reference per candidate.
70. [x] Require explicit file membership and precise symbol locators where
    components are narrower than whole files.
71. [x] Explain valid component granularity from one important function through
    multiple files.
72. [x] Prohibit one-component-per-symbol output without architectural reason.
73. [x] Prohibit repository-wide components that erase meaningful boundaries.
74. [x] Require source-defined name evidence when one is available.
75. [x] Distinguish owned references from supporting references.
76. [x] Prohibit module, relationship, diagram, and course output during
    component discovery.
77. [x] Prohibit direct writes to source or `.electroboy` state.
78. [x] Build a component discovery prompt that passes file manifest, raw Ctags
    evidence, prior artifact, and schema paths rather than embedding catalogs.
79. [x] Add bounded repository-scope instructions that avoid branch-diff
    overfitting.
80. [x] Add skill package validation for the revised references.
81. [x] Forward-test the prompt against C, Python, and mixed-language fixtures.
82. [x] Commit the Phase 3 component discovery skill and prompt contract.

### Boundary 6: Component Candidate Validation And Persistence

83. [x] Introduce a component-candidate service independent from module and
    course services.
84. [x] Parse strict candidate JSONL without interpreting domain objects as
    agent result envelopes.
85. [x] Validate every file ID against the active source manifest.
86. [x] Resolve every symbol locator against raw Ctags or targeted source
    evidence and derive its canonical comparison tuple.
87. [x] Validate source ranges and symbol-to-file consistency.
88. [x] Reject cross-revision candidate references.
89. [x] Route resolvable missing symbols through targeted symbol resolution.
90. [x] Reject candidates that remain ungrounded after targeted resolution.
91. [x] Preserve AI-authored name, kind, responsibility, and limitations without
    semantic rewriting.
92. [x] Persist raw attempts separately from validated candidates.
93. [x] Persist precise per-candidate validation results.
94. [x] Build bounded repair prompts containing only rejected candidates and
    exact errors.
95. [x] Prevent repair invocations from changing already validated candidates.
96. [x] Verify analysis runtime roles use read-only sandbox policy.
97. [x] Verify direct `.electroboy` and repository writes fail during analysis.
98. [x] Test valid candidates, unknown files, unresolved and ambiguous
    locators, stale evidence, bad ranges, mixed output, and targeted repairs.
99. [x] Commit component candidate validation, persistence, and runtime safety.

### Boundary 7: Symbol-Overlap Detection

100. [x] Build a reverse index from exact canonical symbol locator to validated
     candidate IDs.
101. [x] Create overlap edges only when two candidates share an exact
     canonical symbol locator.
102. [x] Build transitive overlap groups while retaining every direct shared
     symbol edge.
103. [x] Exclude supporting-only symbol references from overlap when they are
     not declared as component members.
104. [x] Confirm shared file IDs without shared symbols do not create overlap
     groups.
105. [x] Confirm same names without shared symbols do not create overlap groups.
106. [x] Confirm same descriptions or kinds do not create overlap groups.
107. [x] Preserve candidate-exclusive symbol sets for reconciliation prompts.
108. [x] Persist overlap groups atomically with source and candidate revision.
109. [x] Add deterministic ordering for groups, candidates, and symbol
     locators.
110. [x] Add queries for groups by candidate and symbol.
111. [x] Test pair overlap, transitive overlap, disjoint candidates, same-file
     disjoint symbols, and supporting-reference overlap.
112. [x] Commit exact symbol-overlap detection.

### Boundary 8: AI Component Reconciliation

113. [x] Add focused reconciliation guidance to the analysis skill.
114. [x] Build a reconciliation prompt containing one complete overlap group.
115. [x] Include shared and exclusive symbols for every candidate.
116. [x] Include candidate names, responsibilities, membership, and source
     references.
117. [x] Restrict decisions to `same` and `distinct`.
118. [x] Require a complete partition for groups larger than two candidates.
119. [x] Prohibit relationships, hierarchy, module membership, and unrelated
     discovery in reconciliation output.
120. [x] Validate that every input candidate appears exactly once.
121. [x] Validate that no external candidate or source ID is introduced.
122. [x] Apply `same` by merging only the AI-selected partitions.
123. [x] Preserve aliases, origin candidate IDs, and reconciliation provenance.
124. [x] Apply `distinct` without creating a component relationship.
125. [x] Record intentional shared-symbol membership for distinct components.
126. [x] Persist each reconciliation independently.
127. [x] Build bounded repair prompts for malformed partitions.
128. [x] Resume from the first unresolved overlap group after interruption.
129. [x] Test same, distinct, mixed partition, malformed partition,
     contradictory response, retry, and restart behavior.
130. [x] Commit AI component reconciliation.

### Boundary 9: Reconciled Component Manifest

131. [x] Introduce a component-manifest builder over validated candidates and
     reconciliations.
132. [x] Pass non-overlapping candidates through without semantic deduplication.
133. [x] Convert same-component partitions into one canonical component.
134. [x] Preserve distinct overlapping components independently.
135. [x] Allocate opaque persisted component record IDs.
136. [x] Ensure persisted IDs do not encode AI-authored names.
137. [x] Preserve file IDs, resolved symbol locators, source references,
     aliases, validation provenance, and candidate provenance.
138. [x] Quarantine unresolved overlap groups, record warnings, and allow
     unrelated validated components to continue downstream.
139. [x] Build the reverse file-coverage map and derive exactly one disposition
     for every in-scope file.
140. [x] Persist the coverage report and an investigation context bundle that
     references all collected evidence, accepted records, and diagnostics.
141. [x] Run at most one focused missing-file investigation, route proposed
     component changes through normal validation and reconciliation, and
     recompute coverage once.
142. [x] Persist remaining unresolved files as warnings and reject catch-all
     components proposed solely to force full coverage.
143. [x] Freeze the usable component manifest with counts, revision, run ID,
     completion state, and queries by component, candidate, file, locator,
     name, alias, and disposition; test warning-bearing and clean rebuilds.
144. [x] Commit reconciled component manifest support.

### Boundary 10: Module Synthesis

145. [x] Replace Phase 2 module/entity discovery with module synthesis over the
     reconciled component manifest.
146. [x] Add Phase 3 module-synthesis guidance to the analysis skill.
147. [x] Build prompts with source and frozen component manifest paths.
148. [x] Require module name, kind, purpose, responsibility, component IDs, and
     grouping rationale.
149. [x] Require every module to contain at least one component.
150. [x] Require primary and entry component IDs where applicable.
151. [x] Support optional acyclic module hierarchy.
152. [x] Permit repeated component membership only with explicit rationale.
153. [x] Require one primary module per component when inferable.
154. [x] Represent intentionally ungrouped components explicitly.
155. [x] Reject direct module ownership of source absent from member components.
156. [x] Reject unknown component IDs.
157. [x] Convert missing component discoveries into targeted requests.
158. [x] Run targeted component discovery and reconciliation for accepted
     requests.
159. [x] Regenerate only module scopes affected by new components.
160. [x] Persist and freeze the validated module manifest.
161. [x] Test complete grouping, ungrouped components, repeated membership,
     hierarchy cycles, unknown components, and targeted discovery.
162. [x] Commit Phase 3 module synthesis and module manifest.

### Boundary 11: Module Relationship Generation

163. [x] Remove component reconciliation from all relationship-generation code.
164. [x] Define bounded relationship scopes by module or module pair.
165. [x] Build prompts with frozen module, component, and source manifest paths.
166. [x] Restrict relationship endpoints to frozen module IDs.
167. [x] Require supporting component IDs and hard source references.
168. [x] Require direction, kind, summary, condition, confidence, and
     limitations.
169. [x] Validate endpoint existence and source revision.
170. [x] Validate supporting component membership against endpoint modules.
171. [x] Reject inline component or module creation.
172. [x] Convert unknown endpoint discoveries into targeted requests.
173. [x] Detect exact duplicate module edges.
174. [x] Add a focused AI reconciliation path for contradictory module edges.
175. [x] Preserve dynamic and uncertain relationship limitations.
176. [x] Persist successful relationship scopes independently.
177. [x] Resume and retry one failed relationship scope without rebuilding
     manifests.
178. [x] Test direct, conditional, dynamic, duplicate, contradictory, unknown,
     self-referential, and failed relationships.
179. [x] Commit module relationship generation.

### Boundary 12: Horizontal And Vertical Architecture Knowledge

180. [x] Replace the Phase 2 architecture knowledge selector with a Phase 3
     module/component selector.
181. [x] Define horizontal Architecture output fields and coverage rules.
182. [x] Require repository purpose, external boundaries, entry surfaces, all
     major modules, relationships, state, build, tests, and constraints.
183. [x] Define vertical Architecture slice and ordered-step fields.
184. [x] Select important cross-module behaviors without reducing architecture
     scope to one recent subsystem.
185. [x] Resolve every horizontal module reference to the frozen manifest.
186. [x] Resolve every vertical component reference to manifests and every
     symbol locator through the source-evidence resolver.
187. [x] Require a Mermaid module/component diagram using accepted nodes and
     edges.
188. [x] Require a Mermaid sequence diagram when an ordered cross-module flow
     exists.
189. [x] Permit additional evidence-grounded Mermaid diagrams.
190. [x] Validate diagram node and canonical edge references before rendering.
191. [x] Preserve alternate, error, dynamic, and unresolved flow information.
192. [x] Add deep links from Architecture sections into modules and functions.
193. [x] Test repository breadth, horizontal order, vertical slices, mandatory
     diagrams, unsupported flows, and stale references.
194. [x] Commit Phase 3 Architecture knowledge generation.

### Boundary 13: Horizontal And Vertical Module Knowledge

195. [x] Replace Phase 2 module subgraph selection with Phase 3 manifest
     selection.
196. [x] Build one independent module-knowledge scope per module.
197. [x] Define horizontal module fields for purpose, interfaces, neighbors,
     configuration, state, tests, risks, and peer navigation.
198. [x] Define vertical module fields for components, initialization, normal
     flow, alternate flow, errors, data, concurrency, and important functions.
199. [x] Resolve every component reference against frozen manifests and every
     symbol locator through the source-evidence resolver.
200. [x] Resolve every canonical neighbor edge against module relationships.
201. [x] Allow AI-selected Mermaid diagram types based on module evidence.
202. [x] Validate canonical diagram nodes and edges before rendering.
203. [x] Link horizontal peer modules independently from vertical deep dives.
204. [x] Preserve module-level uncertainty and intentional component overlap.
205. [x] Persist each module knowledge artifact independently.
206. [x] Retry one failed module without rebuilding other module knowledge.
207. [x] Test modules with one component, many components, repeated components,
     no relationships, dynamic behavior, and multiple diagrams.
208. [x] Commit Phase 3 Module knowledge generation.

### Boundary 14: Important And On-Demand Function Knowledge

209. [x] Define AI important-function selection over resolved symbol locators,
     components, modules, and vertical flows.
210. [x] Require important-function selections to resolve to exact canonical
     symbol locators.
211. [x] Bound eager generation by importance and configured initialization
     budget.
212. [x] Refactor Function knowledge selection to use Phase 3 component and
     module context.
213. [x] Preserve exact, qualified, partial, ambiguous, and missing symbol
     resolution.
214. [x] Require user disambiguation before analyzing an ambiguous symbol.
215. [x] Generate purpose, contract, local flow, callers, callees, state,
     errors, concurrency, tests, and limitations.
216. [x] Generate a Mermaid call or flow graph when useful evidence exists.
217. [x] Distinguish direct, inferred, dynamic, and unresolved calls in prose
     and diagrams.
218. [x] Persist eager Function artifacts independently.
219. [x] Start targeted generation for an uncached resolvable Function request.
220. [x] Prevent on-demand generation from restarting initialization.
221. [x] Cache by canonical symbol locator and source revision.
222. [x] Link generated Function material into related Module and Architecture
     vertical paths.
223. [x] Test important selection, arbitrary on-demand generation, ambiguous
     names, missing symbols, single-function components, and stale cache.
224. [x] Commit Phase 3 Function knowledge generation.

### Boundary 15: Course Skill, Rendering, And Navigation

225. [x] Update `code-learner-course` guidance to consume Phase 3 source,
     component, module, relationship, and knowledge manifests.
226. [x] Remove assumptions that a generic Phase 2 entity graph is canonical.
227. [x] Preserve separate Architecture, Module, and Function course
     invocations.
228. [x] Preserve structured JSONL document and section records.
229. [x] Preserve deterministic JSONL-to-Markdown rendering.
230. [x] Preserve the shared file-pane Markdown and Mermaid renderer.
231. [x] Map horizontal Previous and Next to the current abstraction level.
232. [x] Map vertical Deep Dive and Back to Architecture, Module, component, and
     Function targets.
233. [x] Preserve return position across vertical navigation.
234. [x] Synchronize selected sections with primary source references.
235. [x] Add missing, generating, stale, failed, and unresolved target states.
236. [x] Validate all course links against Phase 3 IDs.
237. [x] Ensure course prompts cannot restart component or module discovery.
238. [x] Test headings, sections, source links, diagrams, horizontal navigation,
     vertical navigation, and reload restoration.
239. [x] Commit Phase 3 course skill, projection, rendering, and navigation.

### Boundary 16: Contextual Tutor Integration

240. [x] Update the tutor-context schema for Phase 3 component, module,
     relationship, symbol-locator, and navigation identities.
241. [x] Keep the shared workspace Agent Input as the only tutor composer.
242. [x] Update context atomically on course, section, module, component,
     function, source, and navigation changes.
243. [x] Preserve the one-time tutor bootstrap instruction.
244. [x] Require the tutor to read the current context file before each answer.
245. [x] Avoid injecting full manifests or course content into each question.
246. [x] Let the tutor read only relevant manifest records and source files.
247. [x] Treat missing, stale, malformed, or incompatible context as explicit
     states.
248. [x] Prevent tutor Q&A from mutating source or canonical learner state.
249. [x] Test horizontal navigation, vertical navigation, source selection,
     rapid context changes, stale context, and session reuse.
250. [x] Commit Phase 3 contextual tutor integration.

### Boundary 17: Orchestration, Progress, Retry, And Recovery

251. [x] Replace Phase 2 pass ordering with explicit Phase 3 stages.
252. [x] Define independent checkpoint keys for source files, Ctags evidence,
     components, overlap groups, reconciliations, file coverage,
     missing-file investigation, modules, relationships, knowledge, courses,
     rendering, and activation.
253. [x] Enforce one conflicting initialization job per repository revision.
254. [x] Verify every AI stage runs read-only.
255. [x] Stream meaningful AI reasoning, commands, and bounded output activity.
256. [x] Report file, raw tag, candidate, overlap, disposition, unresolved-file,
     component, module, relationship, knowledge, course, and warning counts.
257. [x] Write exact validation errors to progress before retry.
258. [x] Build targeted retries for candidate, reconciliation, module,
     relationship, knowledge, and course scopes while limiting missing-file
     investigation to one pass.
259. [x] Prevent retries from rewriting completed canonical scopes.
260. [x] Preserve raw failed attempt output outside canonical stores.
261. [x] Resume from the first incomplete scope after process or service
     restart.
262. [x] Keep progress below 100 percent through validation, persistence,
     rendering, and activation.
263. [x] Define and persist `complete`, `complete_with_warnings`, and `failed`;
     convert exhausted semantic scopes into warnings when a usable course
     remains and reserve `failed` for a run that cannot activate usable course
     content.
264. [x] Test interruption at every Phase 3 stage.
265. [x] Test malformed output, empty output, single-record output, direct-write
     attempts, one-pass missing-file investigation, warning completion, hard
     failure, retry repair, and restart recovery.
266. [x] Commit Phase 3 orchestration, progress, retry, and recovery.

### Boundary 18: Revision, Cache, And Phase 2 Compatibility

267. [x] Add learner-generation metadata to project state.
268. [x] Prevent Phase 2 entities from entering a Phase 3 component or module
     manifest implicitly.
269. [x] Define read-only compatibility for completed Phase 2 courses.
270. [x] Define explicit reinitialize-to-Phase-3 behavior.
271. [x] Invalidate changed file Ctags evidence and resolved locators by
     revision and hash.
272. [x] Propagate invalidation from resolved locators to components, modules,
     relationships, knowledge, and courses.
273. [x] Preserve unaffected Phase 3 artifacts.
274. [x] Update `Clear Cache` to remove every Phase 3 source, component, module,
     relationship, knowledge, course, checkpoint, progress, and tutor artifact.
275. [ ] Clear frontend outlines and active learner content immediately after
     cache removal.
276. [ ] Disable Architecture, Module, and Function until reinitialization
     activates a `complete` or `complete_with_warnings` course.
277. [ ] Test source changes, symbol removal, component invalidation, targeted
     regeneration, Phase 2 opening, Phase 3 reinitialization, and cache clear.
278. [ ] Commit revision, invalidation, compatibility, and cache behavior.

### Boundary 19: Service And Frontend Integration

279. [ ] Update service status responses with Phase 3 manifest, stage, warning
     count, terminal completion status, and recovery state.
280. [ ] Update initialization routes to start or resume the Phase 3 pipeline.
281. [ ] Update Architecture selection to use Phase 3 course artifacts.
282. [ ] Update Module lists to use the frozen Phase 3 module manifest.
283. [ ] Update Function resolution to use the Phase 3 Ctags evidence resolver.
284. [ ] Display terminal completion status beneath the progress bar and expose
     warning count, failed scope, and recovery details without invalid content.
285. [ ] Enable learner actions for `complete` and `complete_with_warnings`; keep
     them disabled while unavailable or after `failed`.
286. [ ] Preserve current ElectroBoy menu styling and selection behavior.
287. [ ] Preserve one progress label and one detailed activity stream.
288. [ ] Ensure long source and AI stages do not block status polling.
289. [ ] Ensure course outlines update after targeted module or function
     generation.
290. [ ] Verify code-pane source synchronization for file-only and symbol-level
     components.
291. [ ] Test desktop and mobile layouts for long names, progress output,
     completion statuses, warning details, diagrams, and course navigation.
292. [ ] Commit Phase 3 service and frontend integration.

### Boundary 20: End-To-End Validation And Cutover

293. [ ] Add a C fixture with multiple components in one file and overlapping
     component symbols.
294. [ ] Add a C fixture with two components sharing a file but no symbols.
295. [ ] Add an object-oriented fixture with classes, methods, and inheritance.
296. [ ] Add a dynamic-language fixture with incomplete symbol resolution.
297. [ ] Add a mixed-language fixture with modules spanning language
     boundaries.
298. [ ] Verify initialization completes without configuring or building every
     fixture and that each file receives a disposition.
299. [ ] Verify component candidates are complete enough to synthesize useful
     modules.
300. [ ] Verify exact symbol overlap triggers reconciliation and file overlap
     does not.
301. [ ] Verify `same` and `distinct` decisions produce the expected component
     manifest.
302. [ ] Verify no relationships are produced before the module manifest.
303. [ ] Verify module relationship endpoints and evidence remain grounded.
304. [ ] Verify Architecture horizontal coverage across every fixture module.
305. [ ] Verify Architecture vertical slices traverse modules, components, and
     functions.
306. [ ] Verify Module courses support horizontal peer movement and vertical
     deep dives.
307. [ ] Verify important and on-demand Function courses render and cache.
308. [ ] Verify Mermaid component, sequence, flow, state, class, dependency, and
     call examples through the existing renderer where applicable.
309. [ ] Verify the tutor follows the current Phase 3 context without prompt
     duplication.
310. [ ] Verify direct AI writes are prevented in a real runtime invocation.
311. [ ] Verify single-object and multi-record AI outputs both reach domain
     validation intact.
312. [ ] Verify one missing-file investigation receives persisted prior context,
     unresolved files remain warnings, and targeted failures remain isolated.
313. [ ] Verify restart and resume at representative long-running boundaries.
314. [ ] Verify `Clear Cache` resets backend state and visible UI state.
315. [ ] Run the complete Code Learner test suite.
316. [ ] Run the complete repository test suite and classify unrelated
     failures.
317. [ ] Measure file manifest, Ctags evidence capture and lookup, component
     discovery, reconciliation, file investigation, module synthesis,
     relationship, course, and rendering time on a representative repository.
318. [ ] Inspect desktop and mobile screenshots for overlap, clipping,
     navigation, and Mermaid rendering.
319. [ ] Confirm no learned repository source files were modified.
320. [ ] Verify `complete`, `complete_with_warnings`, and `failed` GUI behavior,
     then review all unresolved diagnostics and open decisions with the
     operator.
321. [ ] Remove or quarantine obsolete Phase 2 write paths only after Phase 3
     acceptance passes.
322. [ ] Commit final Phase 3 integration fixes and cutover.

## Open Decisions

- Which source-symbol provider, if any, should be added after Universal Ctags
  and repository search demonstrate a concrete coverage gap.
- Whether file-only component candidates should be encouraged to enumerate
  their important symbols before reconciliation.
- Whether component storage IDs should be sequential, UUID-based, or
  deterministic opaque hashes.
- Whether a component may have more than one primary module.
- How much important-function material should be generated during
  initialization by default.
- Whether external actors and systems need a separate source-grounded manifest
  or can remain diagram/course annotations until a later phase.
- How module relationship vocabulary should vary across repository domains
  without allowing arbitrary synonyms.
- How to preserve user-authored notes when a component or module is
  reconciled, renamed, or regenerated.
