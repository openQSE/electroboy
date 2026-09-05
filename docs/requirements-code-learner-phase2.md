# Code Learner Phase 2 Requirements

## Status

This document defines the Phase 2 direction for the ElectroBoy Code Learner
workflow. It builds on `docs/requirements-code-learner.md` and replaces the
single-pass course-generation model with a staged, durable knowledge-building
and course-authoring pipeline.

The requirements apply to arbitrary source repositories. They must not assume
a particular programming language, build system, framework, repository layout,
or extension mechanism. Providers, plugins, drivers, adapters, services,
packages, handlers, workflows, and backends are examples of architectural
concepts that the analyzer may discover; none is universally required.

## Skills To Create

Phase 2 requires two separate AI skills. The skills have different purposes,
inputs, outputs, and quality gates. ElectroBoy orchestrates both skills and
owns the schemas, storage, validation, progress, retry, and rendering behavior.

Phase 2 must retain the v1 `course_manifest`, `architecture_step`, `module`,
`module_step`, `function_index_entry`, and `function_lesson` fields through a
read compatibility adapter. Existing v1 corpora remain readable and are not
rewritten destructively. New Phase 2 knowledge and course records use their
canonical schemas; fields with no Phase 2 equivalent are retained only in the
v1 compatibility representation and are deprecated for new generation.

### `codebase-analysis`

The `codebase-analysis` skill builds and incrementally enriches a durable,
source-linked knowledge model of an unfamiliar repository. It records verified
facts and relationships. It does not write course lessons or optimize its
findings for presentation.

The skill must teach an AI agent how to:

- survey an arbitrary repository without assuming its language or architecture
- identify repository boundaries, languages, build systems, executable entry
  points, public APIs, command surfaces, persistent state, processes, services,
  and external systems
- infer architectural modules from code, build configuration, registration
  tables, runtime composition, dependency declarations, documentation, and
  tests
- identify extension families and enumerate their concrete implementations
  when the repository uses provider, plugin, driver, adapter, backend, handler,
  workflow, transport, or similar patterns
- distinguish conceptual architecture from the current Git branch, recent
  commits, or a single locally modified subsystem
- identify symbols, ownership, interfaces, important data types, and runtime
  flows
- discover and type relationships such as contains, calls, implements,
  depends-on, creates, reads, writes, publishes, subscribes, configures, tests,
  and deploys
- use language-aware tools when available without making them mandatory
- record incomplete, dynamic, ambiguous, or unverified relationships as
  diagnostics rather than inventing certainty
- append or revise durable findings without duplicating stable records
- preserve exact source references and confidence for important claims
- report coverage and remaining analysis gaps

The skill must not:

- produce Architecture, Module, or Function course prose
- narrow repository-wide analysis to the active branch's recent changes unless
  the operator explicitly selects that scope
- treat directory names as sufficient proof of module boundaries
- omit discovered extension implementations merely because one implementation
  appears more important or has more recent changes
- claim a complete static call graph when dynamic dispatch, reflection,
  function pointers, generated code, macros, runtime registration, or external
  code prevents that conclusion
- edit tracked repository source files

Recommended skill structure:

```text
codebase-analysis/
|-- SKILL.md
`-- references/
    |-- repository-discovery.md
    |-- knowledge-schema.md
    |-- relationship-types.md
    |-- language-tooling.md
    `-- completeness-rules.md
```

`SKILL.md` should contain the shared purpose, operating constraints, staged
analysis workflow, and routing instructions. Detailed schemas and specialized
guidance should live in focused references so the agent loads only what its
current pass requires.

### `code-learner-course`

The `code-learner-course` skill converts a validated knowledge model into
layered educational material. It teaches from recorded evidence. It may inspect
targeted source locations to verify or clarify evidence, but it must not repeat
the repository-wide discovery pass.

The skill must teach an AI agent how to:

- create Architecture, Module, and Function courses from a supplied knowledge
  scope
- define learning objectives, prerequisites, lesson order, transitions, and
  appropriate depth
- create horizontal learning paths at one abstraction level and vertical links
  into related modules and functions
- avoid repeating the same prose at every layer
- explain concrete relationships, flows, responsibilities, constraints, and
  tradeoffs rather than presenting a folder tour
- generate Markdown-capable JSONL sections compatible with ElectroBoy's
  existing structured-document rendering path
- select from every Mermaid diagram type supported by ElectroBoy when that
  diagram materially improves the explanation; diagram selection must not be
  limited to a fixed Architecture, Module, or Function allowlist
- connect every lesson section to knowledge entity IDs, relationship IDs,
  runtime-flow IDs, and source references
- request targeted knowledge enrichment when required evidence is absent
- preserve uncertainty and confidence from the knowledge model
- produce slide-sized sections while allowing detailed notes and deeper child
  sections

The skill must not:

- invent architectural facts to make a course read smoothly
- silently omit a module or extension implementation required by the selected
  course scope
- use hidden conversational history as the only source of continuity
- emit a separate proprietary presentation format when the existing structured
  JSONL and Markdown body format can represent the material
- implement its own Markdown or Mermaid renderer

Recommended skill structure:

```text
code-learner-course/
|-- SKILL.md
`-- references/
    |-- course-schema.md
    |-- architecture-course.md
    |-- module-course.md
    |-- function-course.md
    |-- layered-navigation.md
    `-- mermaid-guidelines.md
```

The skill should select only the reference for the requested course mode plus
the shared course schema and diagram guidance.

### Skill Packaging And Invocation

- Both skills must be packaged or installed so every supported ElectroBoy AI
  runtime can discover them.
- ElectroBoy must explicitly invoke the required skill in each generated prompt
  rather than depending only on implicit skill selection.
- Skill discovery and invocation failures must be reported before a long-running
  analysis begins.
- Skill instructions must reference versioned ElectroBoy schemas instead of
  carrying an independent, drifting copy of the data contract.
- If human-readable schema references are included in a skill, they must be
  generated from or validated against the canonical schemas owned by
  ElectroBoy.
- Updating a skill must not require changing the storage or rendering code when
  the relevant schema version remains compatible.

## Knowledge-Building Pass

### Purpose

The knowledge-building pass maximizes verified understanding and
cross-referencing before course prose is generated. Its result is a durable
repository knowledge model that can support course generation, contextual Q&A,
impact exploration, module navigation, function lookup, and future analysis
without repeatedly reading the entire repository.

The pass should favor useful completeness over early presentation. It should
collect as much relevant detail as practical while avoiding duplicated,
unsupported, or low-value observations.

### Invocation Model

The knowledge pass is a logical pipeline composed of multiple bounded AI
invocations. It must not be one large prompt that asks the AI to discover the
repository, infer architecture, and write every course at once.

All invocations belong to the same ElectroBoy analysis run and repository
revision, but they should normally use fresh AI conversation contexts. Durable
JSONL records provide continuity between invocations.

Each invocation receives:

- repository root and permitted scope
- analysis run ID and source revision
- its specific pass objective
- canonical input and output schema locations
- paths to relevant existing knowledge records
- paths to progress and checkpoint files
- explicit read-only source rules
- completion and coverage expectations

Each invocation should load only the relevant durable evidence. A module
relationship pass should not receive every function body in the repository. A
function enrichment pass should receive the owning module and the necessary
caller/callee neighborhood rather than the entire knowledge graph.

### Required Analysis Stages

#### Repository Inventory

The inventory stage must identify, where present:

- repository identity, purpose, source revision, and selected scope
- source languages and generated, vendored, cached, or excluded regions
- build systems, package managers, dependency manifests, and configuration
- produced executables, libraries, services, packages, plugins, and artifacts
- public APIs, commands, routes, protocols, and user-facing entry points
- runtime entry points and process boundaries
- tests, fixtures, examples, benchmarks, and validation surfaces
- documentation that describes intended architecture or supported extensions
- persistence mechanisms and important state files
- external services, operating-system facilities, hardware interfaces, and
  third-party systems
- available symbol-analysis tools and their applicability

The inventory must record what was excluded and why. Exclusion must not be
silent.

#### Module And Extension-Family Discovery

The module-discovery stage must infer coherent architectural units from
multiple forms of evidence. A module may correspond to a package, directory,
service, process, library, subsystem, component, feature boundary, or concrete
implementation in an extension family.

The analyzer must identify extension families before selecting representative
implementations. For each discovered family it must:

- name and describe the extension contract
- identify registration, discovery, selection, or dispatch mechanisms
- enumerate concrete implementations present in the selected checkout
- record the files and interfaces supporting each implementation
- create a distinct module entity for each concrete implementation when it has
  meaningful independent behavior
- record intentionally excluded implementations with a reason
- distinguish shared infrastructure from concrete implementations

This requirement is generic. A networking repository may expose providers; an
editor may expose language plugins; a web application may expose route
handlers, persistence adapters, or authentication backends; a compiler may
expose frontends and optimization passes.

#### Relationship Deep Dive

After the initial module catalog exists, the AI must perform a deeper pass to
understand how modules relate. This pass must identify, where inferable:

- ownership and containment
- compile-time and runtime dependencies
- incoming and outgoing interfaces
- direct calls and dispatch-mediated calls
- object construction and lifecycle ownership
- shared state and data ownership
- data transformations and message formats
- event publication and subscription
- configuration and feature selection
- error propagation and recovery boundaries
- concurrency, locking, queues, asynchronous work, and progress models
- persistence reads, writes, transactions, migrations, and caches
- tests and diagnostics that cover each relationship
- deployment, process, and external-system communication

The relationship pass must inspect all module families sufficiently to avoid
using one implementation as an undocumented proxy for every implementation.
Depth may differ according to importance, but breadth and omissions must be
reported explicitly.

#### Runtime-Flow Discovery

The analyzer must identify important end-to-end flows instead of leaving all
relationships as disconnected graph edges. Examples include:

- startup and shutdown
- configuration loading
- request or command handling
- object construction and lifecycle
- authentication and authorization
- data ingestion and persistence
- message send, receive, and completion
- plugin or provider selection
- background jobs and asynchronous processing
- error handling and retry

Each flow must contain ordered steps, participants, source references, and
confidence. Alternate branches and unresolved dynamic dispatch should be
represented explicitly.

#### Symbol And Call Indexing

The knowledge pass must build a broad symbol index appropriate to the languages
present. It should record functions, methods, classes, interfaces, important
types, commands, routes, and other meaningful symbols.

The analyzer may use language servers, compiler indexes, tags, Tree-sitter,
repository search, or language-specific call-graph tools when available. Such
tools must be accessed through a replaceable analysis adapter; Code Learner
must not depend on a Vim installation or a specific editor plugin.

For each indexed symbol, record where practical:

- qualified and display names
- symbol kind and language
- owning module
- declaration and implementation locations
- purpose
- visibility or public/private status
- signature or interface shape
- important callers and callees
- implemented or overridden interfaces
- input and output types
- side effects and state access
- related tests
- confidence and analysis limitations

The initialization pass does not need to generate a full course for every
symbol. It must create enough of an index to resolve later Function requests.

#### Completeness And Consistency Validation

Before course generation begins, ElectroBoy must validate the knowledge model.
Validation must check more than JSON syntax.

Required checks include:

- every record conforms to the canonical schema version
- every referenced entity, relationship, flow, and source ID exists
- stable IDs are unique
- source paths remain inside the repository scope
- referenced files and line ranges exist
- module dependency references point to known modules
- every discovered extension implementation has a module record or explicit
  exclusion diagnostic
- every major entry point belongs to a module and at least one runtime flow
- every major module has purpose, interfaces, relationships, and source
  evidence
- flow participants and ordered steps resolve to known entities
- confidence values and diagnostics are preserved
- manifest counts match emitted records
- the recorded source revision matches the analyzed checkout

Validation failures that indicate missing knowledge should create targeted
enrichment work rather than causing the entire analysis to restart.

### Knowledge Enrichment Loop

Any later pass may discover that the knowledge model is incomplete or wrong.
ElectroBoy must support a bounded enrichment loop:

1. Record a structured knowledge request describing the missing facts.
2. Invoke `codebase-analysis` with the smallest relevant scope.
3. Inspect targeted source and related evidence.
4. Add, revise, or deprecate knowledge records.
5. Re-run referential and completeness validation.
6. Mark affected course sections and diagrams stale.
7. Regenerate only the affected course material.

Enrichment must preserve stable IDs when the represented concept has not
changed. Superseded records should remain traceable when required for course or
session history.

## Knowledge Data Contract

### Schema Ownership

ElectroBoy owns canonical, versioned JSON Schemas for knowledge and course
records. Skills explain how to use the schemas, but deterministic application
code validates them.

Every knowledge record must contain:

- `schema_version`
- `record_type`
- stable `id`
- `analysis_run_id`
- `repository_revision`
- confidence when the record contains inferred information
- source references when the record asserts repository behavior

### Source Reference

```json
{
  "path": "repository/relative/path.ext",
  "start_line": 10,
  "end_line": 30,
  "symbol": "optional qualified symbol",
  "reason": "What this range proves",
  "revision": "source revision used during inspection"
}
```

Source references must be repository-relative, bounded to the selected source
root, and verified before course activation.

### Knowledge Manifest

The manifest records repository identity, source revision, analysis status,
record counts, discovered categories, exclusions, active diagnostics, and
completion state.

```json
{
  "schema_version": 1,
  "record_type": "knowledge_manifest",
  "id": "knowledge.manifest",
  "analysis_run_id": "run-id",
  "repository_revision": "revision",
  "repository_name": "example",
  "scope_path": ".",
  "status": "validated",
  "entity_count": 0,
  "relationship_count": 0,
  "flow_count": 0,
  "diagnostic_count": 0
}
```

### Entity Record

Entity records provide a language-independent identity layer. Specialized
details may be stored under `attributes` without weakening the common fields.

Required entity kinds should include:

- repository
- module
- extension-family
- implementation
- entry-point
- interface
- symbol
- data-type
- state-store
- process
- external-system
- test-surface
- build-target

```json
{
  "schema_version": 1,
  "record_type": "entity",
  "id": "module.storage",
  "analysis_run_id": "run-id",
  "repository_revision": "revision",
  "kind": "module",
  "name": "Storage",
  "summary": "Owns durable application state.",
  "parent_id": "repository.root",
  "tags": ["persistence"],
  "attributes": {},
  "source_refs": [],
  "confidence": "high"
}
```

### Relationship Record

Relationships are first-class records so course generation can traverse the
knowledge graph and produce accurate diagrams.

Supported relationship kinds should include at least:

- contains
- calls
- implements
- extends
- depends-on
- creates
- owns
- reads
- writes
- publishes
- subscribes
- sends-to
- receives-from
- configures
- selects
- registers
- dispatches-to
- persists-to
- tests
- deploys

```json
{
  "schema_version": 1,
  "record_type": "relationship",
  "id": "relationship.api-calls-storage",
  "analysis_run_id": "run-id",
  "repository_revision": "revision",
  "kind": "calls",
  "from_id": "module.api",
  "to_id": "module.storage",
  "summary": "API handlers invoke the storage service.",
  "attributes": {},
  "source_refs": [],
  "confidence": "high"
}
```

### Runtime Flow Record

```json
{
  "schema_version": 1,
  "record_type": "runtime_flow",
  "id": "flow.request-processing",
  "analysis_run_id": "run-id",
  "repository_revision": "revision",
  "name": "Request processing",
  "kind": "request",
  "participant_ids": ["module.api", "module.storage"],
  "steps": [
    {
      "order": 1,
      "from_id": "entry.http",
      "to_id": "module.api",
      "action": "Dispatch request",
      "relationship_ids": []
    }
  ],
  "alternate_flows": [],
  "source_refs": [],
  "confidence": "high"
}
```

### Diagnostic Record

Diagnostics must represent missing coverage, ambiguity, stale evidence,
unsupported tooling, unresolved dynamic behavior, and explicit exclusions.
They must identify related entities and the action needed to improve the model.

### Knowledge Request Record

A course pass or validator may emit a `knowledge_request` when it cannot create
grounded material. The request must identify its scope, missing facts, related
records, suggested source locations, and whether course generation is blocked.

### Suggested Storage Layout

```text
.electroboy/code-learner/
|-- knowledge/
|   |-- manifest.jsonl
|   |-- entities.jsonl
|   |-- relationships.jsonl
|   |-- flows.jsonl
|   |-- diagnostics.jsonl
|   `-- requests.jsonl
|-- courses/
|   |-- architecture.jsonl
|   |-- architecture.md
|   |-- modules/
|   |   |-- <module-id>.jsonl
|   |   `-- <module-id>.md
|   `-- functions/
|       |-- <symbol-id>.jsonl
|       `-- <symbol-id>.md
|-- progress.jsonl
|-- checkpoint.json
`-- tutor-context.json
```

The final design may combine knowledge streams physically, but the logical
record boundaries and independent validation must remain.

## Course-Building Pass

### Purpose

The course-building pass projects validated repository knowledge into a
teachable course graph. It should not be responsible for discovering the whole
repository. It should select, organize, explain, and visualize already recorded
knowledge for the requested scope and audience.

### Separate Invocations

Course generation must use separate, narrowly scoped AI invocations:

- one Architecture course invocation after the architecture knowledge model is
  validated
- one Module course invocation per selected or required module
- one Function course invocation per requested function that lacks fresh course
  material

Each invocation uses a fresh AI context by default and receives the relevant
knowledge subgraph. Durable records, not hidden conversation history, carry
facts between stages.

Architecture receives all module summaries, extension-family summaries, major
relationships, and major runtime flows. A Module invocation receives the
selected module, contained entities, public interfaces, runtime flows, and
directly connected modules. A Function invocation receives the selected
symbol, owning module, signature, source, relevant types, callers, callees,
side effects, tests, and one or two relationship hops as needed.

### Course Artifact Format

Code Learner courses must use the existing structured-document model:

- JSONL is the source of truth.
- A deterministic renderer creates a Markdown companion.
- Prose, lists, tables, and Mermaid diagrams live in Markdown-capable `body`
  fields.
- Stable IDs and hierarchy live in record fields rather than headings.
- ElectroBoy's existing document and file-pane rendering code displays the
  generated Markdown.
- Code Learner must not introduce a second Markdown or Mermaid renderer.

ElectroBoy may need to add a generic `course` artifact type to the structured
artifact registry. That extension should reuse the same record ordering,
Markdown body preservation, Mermaid promotion, document pane, zoom, pop-out,
and file-pane behavior already used by other structured documents.

### Course Document Record

```json
{
  "record_type": "document",
  "schema_version": 1,
  "id": "course.architecture",
  "title": "Architecture",
  "course_mode": "architecture",
  "scope_id": "repository.root",
  "analysis_run_id": "run-id",
  "repository_revision": "revision",
  "audience": "general",
  "status": "generated"
}
```

### Course Section Record

```json
{
  "record_type": "section",
  "schema_version": 1,
  "id": "architecture.request-flow",
  "parent_id": "course.architecture",
  "heading_level": 2,
  "order": 30,
  "title": "Request Flow",
  "body": "Markdown with source-grounded explanation and Mermaid diagrams.",
  "detail_level": "architecture",
  "knowledge_entity_ids": ["module.api", "module.storage"],
  "relationship_ids": ["relationship.api-calls-storage"],
  "runtime_flow_ids": ["flow.request-processing"],
  "related_module_ids": ["module.api", "module.storage"],
  "related_symbol_ids": [],
  "prerequisite_section_ids": [],
  "source_refs": [],
  "confidence": "high"
}
```

### Layered Course Graph

Architecture, Module, and Function material must form one navigable graph
rather than three disconnected collections.

Horizontal navigation keeps the learner at the current abstraction level:

- Architecture: purpose, boundaries, components, dependencies, runtime flows,
  state, deployment, testing, and tradeoffs
- Module: purpose, interfaces, dependencies, internals, data structures,
  runtime behavior, tests, and change risks
- Function: purpose, contract, local flow, call graph, state access, errors,
  tests, and related symbols

Vertical navigation follows explicit links:

- Architecture component to Module course
- Architecture sequence participant to Module course
- Module interface or important symbol to Function course
- Function caller or callee to another Function course
- Any lesson section back to its parent layer

Every course section must identify its parent, related knowledge records, and
available deeper targets. Previous and Next navigate horizontally. A distinct
deep-dive action navigates vertically. Breadcrumb or Back returns to the prior
layer and position.

### Architecture Course Requirements

Architecture mode must explain the repository as a complete working system,
not as a selected subsystem or current branch diff.

It must include:

- repository purpose, users, and external boundaries
- public APIs, commands, events, or other entry surfaces
- major components and their responsibilities
- extension families and their concrete implementations at an appropriate
  architectural level
- component dependencies and ownership
- major runtime flows
- state, persistence, and data ownership
- process, service, thread, or deployment topology when relevant
- testing, build, packaging, and operational boundaries
- major tradeoffs, constraints, and known uncertainty

At least one Mermaid component diagram and one Mermaid sequence diagram are
required. The component diagram should use Mermaid flowchart syntax and
subgraphs when Mermaid has no native notation suitable for the repository.

The course author should add other diagrams when they materially clarify the
system:

- class diagrams for type and interface relationships
- state diagrams for lifecycle, protocol, and workflow state
- entity-relationship diagrams for persistent data
- data-flow diagrams
- deployment or process-topology diagrams
- dependency diagrams

Every diagram must be generated from knowledge records, use stable entity IDs
where practical, have explanatory prose, and link to source evidence through
its containing course section.

### Module Course Requirements

Every module selected for full course generation must include:

- purpose and architectural boundary
- ownership and contained entities
- incoming interfaces and callers
- outgoing dependencies and external systems
- key data types and state
- construction, startup, shutdown, and lifecycle behavior
- important runtime flows through the module
- extension or implementation relationship when applicable
- relevant configuration and feature flags
- tests and diagnostics
- common change paths
- risks, concurrency concerns, dynamic behavior, and uncertainty
- links to important functions

An extension family must have a family-level module and concrete module entries
for meaningful implementations. Shared infrastructure should not replace
implementation-specific coverage.

Module courses may use any Mermaid diagram type supported by ElectroBoy when
it materially clarifies the selected module. Diagram selection must follow the
module's actual structure and behavior rather than a fixed per-mode list. For
example, a module may benefit from flowcharts, sequence diagrams, class
diagrams, state diagrams, entity-relationship diagrams, mind maps, timelines,
Git graphs, quadrant charts, requirement diagrams, C4 diagrams, Sankey
diagrams, XY charts, block diagrams, packet diagrams, architecture diagrams,
Kanban diagrams, or another Mermaid syntax supported by the installed
renderer. This list is illustrative, not exhaustive, and unsupported or
inapplicable diagram types must not be generated merely to increase diagram
count.

A module may contain multiple diagram types when they answer different
questions. A module dependency or component-style diagram is required when
the module has multiple important incoming or outgoing relationships. A
sequence or flow diagram should be added when ordered runtime behavior is
central to understanding the module. State, class, entity-relationship, data,
deployment, protocol, and other specialized diagrams should be selected when
the corresponding knowledge exists.

### Function Course Requirements

Function mode must accept a function, method, class, route, command, or other
indexed symbol appropriate to the repository's languages.

A Function course should include, where applicable:

- resolved qualified identity and owning module
- declaration, implementation, signature, and visibility
- purpose and contract
- inputs, outputs, mutations, and side effects
- local control flow and important branches
- error and cleanup paths
- callers and invocation conditions
- callees and delegated responsibilities
- accessed state, data types, external systems, and concurrency primitives
- related tests
- dynamic-dispatch or call-resolution limitations
- links back to the owning Module and relevant Architecture flow

A Mermaid call graph is required when at least one meaningful caller or callee
can be established. The graph must distinguish verified static edges, inferred
or dynamic edges, and unresolved boundaries when possible.

### On-Demand Function Enrichment

Initialization must build a broad symbol index but does not need to generate a
complete lesson for every symbol. When a user selects a symbol without current
course material, ElectroBoy must:

1. Resolve the symbol against the durable symbol index.
2. Show candidate choices when resolution is ambiguous.
3. Report a genuine missing symbol when it cannot be resolved.
4. If resolved, start a scoped `codebase-analysis` enrichment pass when caller,
   callee, state, or flow evidence is insufficient.
5. Validate and merge new knowledge records.
6. Invoke `code-learner-course` in Function mode.
7. Validate and render the function JSONL artifact.
8. Add the new Function course to the durable course graph.
9. Display the course without requiring repository initialization to run again.
10. Reuse the cached course while its source references remain fresh.

The UI must distinguish `resolving`, `analyzing`, `building course`,
`validating`, `ready`, `ambiguous`, `missing`, and `failed` states.

## Mermaid And Rendering Requirements

- Mermaid source must be stored inside fenced `mermaid` blocks in Markdown
  body fields.
- Every Mermaid diagram type supported by the installed renderer is eligible
  for Architecture, Module, or Function material when it is useful and can be
  grounded in the knowledge model.
- Diagram-type policy must be capability-driven rather than encoded as a
  closed per-course-mode allowlist.
- The course artifact should record the selected diagram type and the
  knowledge question it is intended to answer.
- The existing structured-document Markdown renderer and file-pane Mermaid
  renderer must be reused.
- Generated Mermaid must be syntax-validated before course activation when a
  deterministic validator is available.
- A malformed diagram must not invalidate otherwise usable course prose.
- Diagram failures must display a useful error and preserve the Mermaid source
  for inspection or regeneration.
- Diagrams must remain readable in embedded, full-pane, and pop-out views.
- Course rendering must preserve source links, headings, lists, tables, code
  blocks, and diagrams.
- Rendering must not execute arbitrary script from generated Markdown.
- Mermaid node labels must avoid leaking absolute filesystem paths.
- Course artifacts must remain exportable as Markdown with Mermaid fences.

## Contextual Tutor Requirements

The shared workspace Agent Input remains the only learner question composer.
ElectroBoy must not prepend or append a large serialized learner-context prompt
to every submitted question. The user's question should be sent to the active
tutor session as written, apart from minimal transport metadata required by the
AI runtime.

### Tutor Session Bootstrap

When a tutor session is created, ElectroBoy gives it one stable bootstrap
instruction. That instruction identifies the repository root and the relative
path `.electroboy/code-learner/tutor-context.json`, and requires the tutor to:

1. read the context file before answering every learner question
2. treat its current version as authoritative for the learner's location
3. follow referenced course, knowledge, and source artifacts only as needed
4. avoid relying on an older course position retained in conversation history
5. report a missing, unreadable, incompatible, or stale context file instead
   of silently guessing the user's location

The bootstrap instruction is sent once when the tutor session starts. It must
not contain the complete course, knowledge subgraph, or source excerpt. An AI
runtime used for contextual tutoring must provide repository-scoped file-read
capability or an equivalent tool that resolves the same context-file contract.

### Tutor Context File

`tutor-context.json` is a small, mutable context pointer. It is not a transcript
and must not duplicate the full lesson or knowledge graph. ElectroBoy owns and
atomically rewrites it whenever the learner changes course, section, layer,
module, function, source selection, or repository revision.

The canonical schema must include:

- schema and monotonically increasing context versions
- project and repository identity
- repository revision and stale status
- current course document, mode, scope, and section IDs
- horizontal position and vertical navigation path
- selected knowledge entity, relationship, and runtime-flow IDs
- active module or symbol ID
- visible source path and selected line range when present
- repository-relative paths to the active course artifact and knowledge root
- update timestamp and writer/session identity for diagnostics

Example:

```json
{
  "schema_version": 1,
  "context_version": 42,
  "project_id": "project-id",
  "repository_revision": "revision",
  "stale": false,
  "course": {
    "document_id": "course.module.storage",
    "mode": "module",
    "scope_id": "module.storage",
    "section_id": "module.storage.write-path",
    "horizontal_index": 4,
    "vertical_path": [
      "course.architecture",
      "course.module.storage"
    ]
  },
  "selection": {
    "module_id": "module.storage",
    "symbol_id": null,
    "knowledge_entity_ids": ["module.storage"],
    "relationship_ids": ["relationship.api-calls-storage"],
    "runtime_flow_ids": ["flow.request-processing"]
  },
  "source": {
    "path": "src/storage.ext",
    "start_line": 10,
    "end_line": 30
  },
  "artifacts": {
    "course": ".electroboy/code-learner/courses/modules/module.storage.jsonl",
    "knowledge_root": ".electroboy/code-learner/knowledge"
  },
  "updated_at": "2026-09-04T12:00:00Z",
  "writer_id": "electroboy-session-id"
}
```

All paths in the file must be repository-relative and validated against the
attached project root. Optional selections must use explicit `null` or empty
collections so the tutor can distinguish an absent selection from a malformed
file.

### Question-Time Behavior

Before ElectroBoy enables question submission after a navigation change, it
must atomically persist the new context version. The tutor then reads the
context file at question time and loads the smallest useful evidence set:

- the current course section and nearby course structure
- directly referenced knowledge entities, relationships, and runtime flows
- visible or selected source only when needed to answer the question
- additional repository evidence only when the referenced material is
  insufficient

Conversation history remains available for conversational continuity, but it
must not override the current file-backed navigation context. Repeated
questions at the same location reuse the same context file without resending
its contents. Navigation changes update the file without restarting the tutor
session.

If the answer reveals new durable knowledge, the tutor may propose a structured
enrichment request. Ordinary Q&A must not silently mutate the knowledge model,
course artifacts, or tutor context file.

## Persistence, Revision, And Invalidation

- Knowledge and course JSONL are durable project state.
- Every analysis and course artifact records the repository revision.
- ElectroBoy must compare referenced files or repository revisions when a
  course is reopened.
- Changed source references mark related entities, relationships, flows,
  sections, and diagrams stale.
- Unaffected knowledge and course artifacts remain usable.
- Regeneration should operate on the smallest stale scope.
- Interrupted analysis resumes from validated durable records rather than only
  an AI conversation transcript.
- Partial module and function courses must be saved independently.
- A failed module invocation must not discard completed Architecture or other
  Module courses.
- Schema migrations must be explicit and preserve or clearly invalidate older
  records.

## Progress And Observability

Progress must reflect actual staged work rather than AI-authored completion
claims alone.

ElectroBoy must report:

- overall initialization stage and percentage
- active AI invocation and scope
- knowledge record counts
- discovered and analyzed module counts
- completed and remaining module deep dives
- current validation or enrichment work
- course artifacts generated and rendered
- function generation status for on-demand requests
- elapsed time and useful activity heartbeat
- final-response delivery, validation, persistence, and rendering phases

One active job per repository and scope should be enforced where duplicate work
would conflict. Independent module course jobs may run concurrently only when
their writes and progress records are isolated.

## Functional Requirements

### Skills

- `CL2-SK-1` ElectroBoy provides a discoverable `codebase-analysis` skill.
- `CL2-SK-2` ElectroBoy provides a discoverable `code-learner-course` skill.
- `CL2-SK-3` Analysis prompts explicitly invoke `codebase-analysis`.
- `CL2-SK-4` Course prompts explicitly invoke `code-learner-course` with one
  requested mode and scope.
- `CL2-SK-5` Skills reference canonical versioned schemas owned by ElectroBoy.
- `CL2-SK-6` Missing or incompatible skills fail before expensive analysis.

### Knowledge

- `CL2-KN-1` Initialization creates a durable repository knowledge manifest.
- `CL2-KN-2` Initialization uses multiple bounded AI invocations with durable
  JSONL continuity.
- `CL2-KN-3` The analyzer supports arbitrary repository languages and layouts.
- `CL2-KN-4` The analyzer records entities, relationships, runtime flows,
  diagnostics, source evidence, confidence, and coverage.
- `CL2-KN-5` The analyzer identifies extension families generically and
  enumerates concrete implementations present in the checkout.
- `CL2-KN-6` Current branch changes do not silently redefine repository-wide
  course scope.
- `CL2-KN-7` Every major module has source-linked interfaces and relationships.
- `CL2-KN-8` Every important runtime flow has ordered, source-linked steps.
- `CL2-KN-9` Initialization creates a broad, language-appropriate symbol index.
- `CL2-KN-10` ElectroBoy validates schema, references, completeness, and source
  ranges before course generation.
- `CL2-KN-11` Missing knowledge creates targeted enrichment requests.
- `CL2-KN-12` Enrichment updates only affected knowledge and invalidates only
  affected course material.

### Courses

- `CL2-CR-1` Course generation consumes validated knowledge instead of
  combining repository discovery and teaching in one prompt.
- `CL2-CR-2` Architecture, each Module, and each requested Function use separate
  scoped AI invocations.
- `CL2-CR-3` Course JSONL uses document and section records with Markdown body
  fields.
- `CL2-CR-4` Course JSONL is the source of truth and Markdown is generated
  deterministically.
- `CL2-CR-5` Architecture, Module, and Function courses form one linked course
  graph.
- `CL2-CR-6` Previous and Next navigate horizontally at the current layer.
- `CL2-CR-7` Deep-dive navigation moves vertically while preserving return
  position.
- `CL2-CR-8` Architecture includes component and sequence Mermaid diagrams.
- `CL2-CR-9` The course author adds other Mermaid diagrams when they materially
  clarify repository behavior.
- `CL2-CR-10` Module courses cover boundaries, interfaces, relationships,
  internals, flows, state, tests, and risks.
- `CL2-CR-11` Function courses cover contract, local flow, callers, callees,
  side effects, errors, tests, and uncertainty.
- `CL2-CR-12` Function courses include a Mermaid call graph when meaningful call
  relationships are available.
- `CL2-CR-13` All course claims and diagrams remain linked to knowledge and
  source evidence.
- `CL2-CR-14` Module courses may use any Mermaid diagram type supported by the
  installed renderer when the diagram is evidence-grounded and useful.
- `CL2-CR-15` Diagram selection is not restricted by a closed per-mode
  allowlist, and multiple diagram types may appear in one module course.

### Function Fallback

- `CL2-FN-1` Selecting an indexed function without a lesson starts targeted
  generation instead of returning only a missing-lesson error.
- `CL2-FN-2` Ambiguous function names present candidate symbols before
  generation.
- `CL2-FN-3` Unresolved symbols display a genuine missing-symbol state and
  useful candidates when available.
- `CL2-FN-4` Targeted function analysis may enrich the durable knowledge graph.
- `CL2-FN-5` Generated Function courses are validated, persisted, cached, and
  linked into the course graph.
- `CL2-FN-6` Stale Function courses can be regenerated independently.

### Rendering And UI

- `CL2-UI-1` Code Learner reuses the existing structured JSONL-to-Markdown
  renderer.
- `CL2-UI-2` Code Learner reuses the existing file-pane Markdown and Mermaid
  rendering path.
- `CL2-UI-3` Code Learner does not maintain a separate Markdown or Mermaid
  implementation.
- `CL2-UI-4` Selecting a course section synchronizes its primary source
  reference with the read-only code pane.
- `CL2-UI-5` Mermaid diagrams work in embedded, pane, and pop-out views.
- `CL2-UI-6` The shared workspace Agent Input remains the only learner question
  composer.
- `CL2-UI-7` Progress distinguishes analysis, delivery, validation, course
  construction, rendering, and readiness.
- `CL2-UI-8` ElectroBoy atomically maintains a compact, canonical
  `.electroboy/code-learner/tutor-context.json` file.
- `CL2-UI-9` Tutor sessions receive one bootstrap instruction requiring them
  to read the current context file before every answer.
- `CL2-UI-10` ElectroBoy does not serialize and inject the full learner context
  into each user question.
- `CL2-UI-11` Contextual tutoring is enabled only when the AI runtime can read
  the repository-scoped context file or access an equivalent context tool.

## Quality Requirements

- Repository-wide analysis must prioritize verified completeness over recent
  branch activity.
- AI contexts must remain bounded enough that one deeply inspected subsystem
  does not dominate unrelated course generation.
- Durable knowledge must be independently inspectable and machine-validatable.
- Course generation must be reproducible from a validated knowledge revision.
- Module and function failures must be isolated and retryable.
- Large repositories must support incremental and on-demand generation.
- Static-analysis limitations must be visible instead of hidden.
- Generated diagrams must remain traceable to source-grounded knowledge.
- Course artifacts must remain useful when Mermaid rendering is unavailable.
- The design must allow additional AI runtimes and language-analysis adapters.
- No analysis or course pass may edit tracked source files.
- Absolute project paths and sensitive local details must not appear in exported
  course artifacts.

## Non-Goals

- Guarantee a perfect call graph for every language or runtime.
- Generate full Function courses for every symbol during initialization.
- Require a specific editor, Vim plugin, language server, or compiler tool.
- Replace source-level debugging, profiling, or runtime tracing.
- Treat the active branch diff as the default course scope.
- Build a second document or Mermaid renderer inside Code Learner.
- Require every repository to contain the same module or diagram types.
- Allow course generation to invent facts missing from the knowledge model.

## Acceptance Criteria

- A multi-language fixture repository can be initialized through at least two
  distinct knowledge-building AI invocations.
- Initialization produces valid manifests, entities, relationships, runtime
  flows, diagnostics, and source references.
- A fixture containing an extension family produces a family record and a
  distinct module for every concrete implementation or an explicit exclusion
  diagnostic.
- Recent changes to one fixture module do not cause unrelated modules to be
  omitted from repository-wide knowledge.
- Relationship validation catches unknown entity IDs and invalid source ranges.
- Missing required module coverage produces an enrichment request or blocks
  course activation.
- Architecture generation uses a fresh scoped invocation and produces a
  structured course artifact.
- The Architecture course contains a rendered Mermaid component diagram and
  sequence diagram.
- Additional state, class, entity-relationship, dependency, or deployment
  diagrams can be generated and rendered when selected by the course author.
- A Module course includes incoming and outgoing relationships, important
  flows, state, tests, and deeper symbol links.
- A Module course can select any evidence-grounded Mermaid diagram type
  supported by the installed renderer, including more than one type when the
  diagrams explain different aspects of the module.
- Architecture-to-Module deep dive and return navigation preserve the prior
  horizontal position.
- Selecting an indexed symbol without a Function lesson starts targeted
  analysis and course generation.
- The generated Function course contains a call graph when caller or callee
  evidence exists.
- Ambiguous symbols present candidates and do not start generation against an
  arbitrary match.
- Generated course JSONL renders to Markdown through the existing structured
  document code.
- Mermaid uses the existing file-pane renderer and works in a pop-out pane.
- Changing one referenced source file marks only related knowledge and course
  sections stale.
- Restarting ElectroBoy resumes from durable validated knowledge without
  replaying completed repository analysis.
- Progress remains below 100 percent until validation, persistence, rendering,
  and activation complete.
- A tutor session receives its context-file bootstrap only once, reads the
  current context file before each answer, and answers through the shared Agent
  Input without full context being injected into each question.
- Moving to another course section atomically updates the context file, and the
  next answer uses the new section without restarting the tutor session.

## Detailed Implementation Checklist

Use this checklist as the ordered implementation sequence. Complete and verify
each functional boundary before moving to the next. Commit at the end of each
boundary so later work can be reviewed or reverted independently.

### Boundary 1: Baseline And Compatibility

1. [x] Record the current Code Learner corpus, walkthrough, initialization,
   module selection, function selection, rendering, and tutor behavior.
2. [x] Add characterization tests for the current JSONL parser and persisted
   corpus.
3. [x] Add characterization tests for Architecture, Module, and Function
   walkthrough creation.
4. [x] Add a fixture for a repository containing multiple architectural
   modules and an extension family with multiple implementations.
5. [x] Add fixtures for at least Python, TypeScript or JavaScript, and C or C++
   source layouts.
6. [x] Confirm existing v1 course artifacts remain readable during migration.
7. [x] Define which v1 fields will be migrated, deprecated, or retained.
8. [x] Verify unrelated software and creative-writing workflows remain
   unaffected.
9. [x] Commit baseline fixtures and characterization tests.

### Boundary 2: Canonical Schemas

10. [x] Choose canonical package locations for knowledge and course schemas.
11. [x] Define common schema fields, ID rules, confidence values, revision
    metadata, and source references.
12. [x] Define the knowledge manifest schema.
13. [x] Define entity kinds and the entity schema.
14. [x] Define relationship kinds and the relationship schema.
15. [x] Define runtime-flow and ordered-step schemas.
16. [x] Define diagnostic, exclusion, coverage, and knowledge-request schemas.
17. [x] Define course document, section, diagram-metadata, and compact tutor
    context schemas.
18. [x] Define horizontal and vertical course-link fields.
19. [x] Define schema-version compatibility and migration behavior.
20. [x] Implement deterministic schema loading and validation.
21. [x] Add valid and invalid schema fixtures.
22. [x] Test duplicate IDs, unknown references, invalid enums, malformed source
    references, and incompatible schema versions.
23. [x] Commit canonical schemas and validators.

### Boundary 3: `codebase-analysis` Skill

24. [x] Scaffold the `codebase-analysis` skill with automatic discoverability.
25. [x] Write a concise `SKILL.md` describing purpose, constraints, staged
    operation, and reference routing.
26. [x] Add repository-discovery guidance that remains language-independent.
27. [x] Add knowledge-schema guidance referencing the canonical schemas.
28. [x] Add relationship-type guidance with concrete evidence expectations.
29. [x] Add extension-family discovery and completeness guidance.
30. [x] Add language-tooling guidance covering optional adapters and fallback
    behavior.
31. [x] Add explicit instructions preventing active-branch overfitting.
32. [x] Add explicit instructions against course-prose generation.
33. [x] Add checkpoint, progress, source-safety, and stopping rules.
34. [x] Validate the skill package with the skill validator.
35. [x] Forward-test the skill independently against an unfamiliar fixture.
36. [x] Review whether the skill discovers all fixture implementations and
    records uncertainty correctly.
37. [x] Commit the analysis skill and behavioral tests.

### Boundary 4: `code-learner-course` Skill

38. [x] Scaffold the `code-learner-course` skill with automatic
    discoverability.
39. [x] Write a concise `SKILL.md` describing evidence-only course generation
    and mode routing.
40. [x] Add shared course-schema and evidence-grounding guidance.
41. [x] Add Architecture course guidance.
42. [x] Add Module course guidance.
43. [x] Add Function course guidance.
44. [x] Add layered horizontal and vertical navigation guidance.
45. [x] Add capability-driven Mermaid selection, syntax, labeling, and evidence
    guidance without a closed per-mode diagram allowlist.
46. [x] Require component and sequence diagrams for Architecture.
47. [x] Require call graphs for Function courses when call evidence exists.
48. [x] Add knowledge-request behavior for insufficient evidence.
49. [x] Add instructions preventing repository-wide rediscovery during course
    generation.
50. [x] Validate the skill package.
51. [x] Forward-test each course mode using a fixed knowledge fixture without
    providing expected prose.
52. [x] Verify the skill preserves uncertainty and does not invent missing
    relationships.
53. [x] Commit the course skill and behavioral tests.

### Boundary 5: Knowledge Store

54. [x] Introduce a knowledge-store domain boundary independent from browser
    routes and renderers.
55. [x] Implement safe paths for manifest, entities, relationships, flows,
    diagnostics, requests, progress, and checkpoints.
56. [x] Implement atomic JSONL writes and append/update behavior.
57. [x] Implement stable-record merge semantics.
58. [x] Implement conflict detection for incompatible records with the same ID.
59. [x] Implement record deprecation or replacement metadata.
60. [x] Implement query operations by ID, kind, module, source path, and
    relationship neighborhood.
61. [x] Implement manifest count and status updates.
62. [x] Implement source-revision and source-reference freshness checks.
63. [x] Add tests for interrupted writes, malformed records, duplicate IDs,
    merges, revisions, and stale references.
64. [x] Add migration or import support for useful v1 corpus data.
65. [x] Commit the durable knowledge store.

### Boundary 6: Analysis Runtime And Pass Orchestration

66. [ ] Replace the monolithic initialization prompt with an analysis-run
    orchestrator.
67. [x] Define explicit inventory, module, relationship, flow, symbol, and
    validation pass types.
68. [x] Give each pass a fresh AI invocation by default.
69. [x] Pass only relevant durable artifact paths and scope to each invocation.
70. [x] Explicitly invoke `codebase-analysis` in every analysis prompt.
71. [x] Verify skill availability before starting the first pass.
72. [x] Assign one analysis run ID and source revision across all passes.
73. [x] Persist pass status before and after each invocation.
74. [x] Parse and validate each pass output before merging it.
75. [x] Preserve completed pass output when a later pass fails.
76. [x] Resume from the first incomplete or invalid pass after restart.
77. [ ] Enforce a single conflicting initialization job per repository.
78. [x] Add bounded retry behavior for transient runtime failures.
79. [x] Ensure retries cannot duplicate knowledge records.
80. [x] Add orchestration tests with deterministic fake AI outputs.
81. [x] Commit staged analysis orchestration.

### Boundary 7: Repository Inventory Pass

82. [x] Implement the inventory prompt and input contract.
83. [x] Record repository identity, scope, revision, languages, and exclusions.
84. [x] Record build systems, dependency manifests, and produced artifacts.
85. [x] Record entry points, public surfaces, processes, tests, and external
    systems.
86. [x] Record available language-analysis tools without requiring them.
87. [x] Validate that excluded regions have explicit reasons.
88. [x] Test monorepos, generated trees, vendored dependencies, missing docs,
    and mixed-language repositories.
89. [x] Commit the repository inventory pass.

### Boundary 8: Module And Extension Discovery

90. [x] Implement the module-discovery prompt and scope contract.
91. [x] Infer modules from code relationships, build configuration, runtime
    registration, documentation, and tests.
92. [x] Detect extension families without relying on fixed names such as
    provider or plugin.
93. [x] Enumerate concrete implementations for each extension family.
94. [x] Separate family infrastructure, shared utility modules, and concrete
    implementations.
95. [x] Require a module or exclusion diagnostic for each implementation.
96. [x] Record public interfaces, ownership, primary source, and initial
    dependencies for every major module.
97. [x] Add a coverage report comparing inventory evidence with emitted module
    records.
98. [x] Test multiple extension-family naming and registration patterns.
99. [x] Test that a recent branch change does not hide unrelated modules.
100. [x] Commit module and extension-family discovery.

### Boundary 9: Relationship And Runtime-Flow Deep Dive

101. [x] Implement scoped relationship-deep-dive prompts.
102. [x] Process modules in bounded batches or independent invocations.
103. [x] Record typed incoming and outgoing relationships.
104. [x] Record construction, lifecycle, ownership, and cleanup behavior.
105. [x] Record state, persistence, events, messages, and external interactions.
106. [x] Record concurrency and asynchronous behavior where present.
107. [x] Implement runtime-flow discovery and ordered flow steps.
108. [x] Record alternate and error flows.
109. [x] Reconcile contradictory relationships from separate passes.
110. [x] Generate diagnostics for unresolved dispatch or incomplete evidence.
111. [x] Verify every major module has sufficient relationship coverage.
112. [x] Test cyclic dependencies, event-driven flow, dynamic registration,
    and cross-process communication.
113. [x] Commit relationship and runtime-flow analysis.

### Boundary 10: Symbol Index And Analysis Adapters

114. [x] Define a reusable symbol-analysis adapter contract.
115. [x] Implement a repository-search fallback available for every language.
116. [x] Detect optional language servers, tags, Tree-sitter, compiler indexes,
    or call-graph tools.
117. [x] Add adapters only where they materially improve evidence quality.
118. [x] Normalize adapter output into language-independent symbol records.
119. [x] Record qualified names, kinds, owners, locations, signatures, and
    visibility.
120. [x] Record known callers, callees, types, tests, state, and limitations.
121. [x] Distinguish verified, inferred, and unresolved call edges.
122. [x] Avoid a hard dependency on Vim or any editor integration.
123. [x] Test overloaded names, methods, generated symbols, dynamic dispatch,
    function pointers, and symbols absent from optional indexes.
124. [x] Commit symbol indexing and adapter boundary.

### Boundary 11: Knowledge Validation And Enrichment

125. [x] Implement cross-record referential validation.
126. [x] Implement source path and line-range validation.
127. [x] Implement module and extension-family completeness validation.
128. [x] Implement entry-point and runtime-flow coverage validation.
129. [x] Implement manifest count validation.
130. [x] Convert actionable gaps into structured knowledge requests.
131. [x] Add a targeted enrichment-job controller.
132. [x] Merge enrichment output with stable-ID preservation.
133. [x] Mark affected knowledge and course records stale.
134. [x] Prevent unbounded enrichment loops with explicit attempt and diagnostic
    limits.
135. [x] Test successful enrichment, unresolved enrichment, conflicting
    evidence, and partial validation.
136. [x] Commit validation and enrichment behavior.

### Boundary 12: Generic Course Artifact Support

137. [x] Add a generic `course` artifact type to the structured artifact
    boundary.
138. [x] Reuse existing JSONL reading, record ordering, hierarchy, and Markdown
    body rendering.
139. [x] Reuse existing Markdown, Mermaid, file-pane, zoom, and pop-out
    rendering.
140. [x] Add course document and section field preservation.
141. [x] Add deterministic JSONL-to-Markdown generation for Architecture,
    Module, and Function artifacts.
142. [x] Preserve Mermaid fences exactly in generated Markdown.
143. [x] Add safe course artifact routes and paths.
144. [x] Confirm no Code Learner-specific Markdown or Mermaid renderer remains.
145. [x] Test headings, nesting, prose, tables, code blocks, source links, and
    multiple Mermaid diagram types.
146. [x] Commit generic course artifact and renderer reuse.

### Boundary 13: Architecture Course Generation

147. [x] Build the Architecture knowledge-subgraph selector.
148. [x] Include all major modules, extension families, relationships, runtime
    flows, state, external systems, and diagnostics.
149. [x] Implement a scoped Architecture course prompt invoking
    `code-learner-course`.
150. [x] Generate document and hierarchical section records.
151. [x] Require a Mermaid component diagram.
152. [x] Require at least one Mermaid sequence diagram for a major runtime flow.
153. [x] Allow the skill to select class, state, ER, data-flow, dependency, or
    deployment diagrams when useful.
154. [x] Validate knowledge links and source references for every section.
155. [x] Validate required diagram presence and Mermaid syntax where possible.
156. [x] Render and persist `architecture.jsonl` and `architecture.md`.
157. [x] Test architectural breadth against multi-module fixtures.
158. [x] Test that branch-local changes do not dominate the Architecture course.
159. [x] Commit Architecture course generation.

### Boundary 14: Module Course Generation

160. [x] Build a module knowledge-subgraph selector with direct relationship
    neighbors.
161. [x] Implement one scoped course invocation per module.
162. [x] Generate module purpose, interfaces, dependencies, internals, state,
    flows, tests, changes, and risks.
163. [x] Generate dependency or component-style diagrams for sufficiently
    connected modules.
164. [x] Allow every Mermaid diagram type supported by the installed renderer,
    select diagrams from module evidence, and support multiple complementary
    diagram types in one module course.
165. [x] Persist each module JSONL and Markdown independently.
166. [x] Isolate module generation failures.
167. [x] Track module generation completion in the knowledge manifest or course
    index.
168. [x] Link family modules, concrete implementations, shared infrastructure,
    and related functions.
169. [x] Support retrying one module without rebuilding Architecture or other
    modules.
170. [x] Test module completeness, cross-links, independent failures, and
    retries.
171. [x] Commit Module course generation.

### Boundary 15: Layered Course Navigation

172. [x] Define a course graph projection from document and section records.
173. [x] Preserve horizontal order separately at each course layer.
174. [x] Add explicit vertical links from Architecture sections to modules.
175. [x] Add explicit vertical links from Module sections to functions.
176. [x] Add parent links and return-position state.
177. [x] Implement Previous and Next within the current layer.
178. [x] Implement Deep Dive, Back, and breadcrumb behavior.
179. [x] Synchronize each selected section with its primary source reference.
180. [x] Preserve code-pane selection and scroll behavior across horizontal
    navigation.
181. [x] Preserve prior horizontal position when returning from a deep dive.
182. [x] Add missing, stale, generating, and failed target states.
183. [x] Test multi-level navigation and browser reload restoration.
184. [x] Commit layered course navigation.

### Boundary 16: On-Demand Function Courses

185. [x] Change Function selection to resolve against the durable symbol index.
186. [x] Preserve exact, qualified, partial, ambiguous, and missing resolution
    states.
187. [x] Detect whether a fresh Function course already exists.
188. [x] Build the targeted function knowledge subgraph.
189. [x] Create an enrichment request when call, state, or flow evidence is
    insufficient.
190. [x] Run scoped function enrichment without restarting initialization.
191. [x] Invoke `code-learner-course` in Function mode after knowledge validates.
192. [x] Generate contract, control-flow, call, side-effect, error, and test
    sections.
193. [x] Generate a Mermaid call graph when meaningful edges exist.
194. [x] Distinguish verified, inferred, dynamic, and unresolved graph edges.
195. [x] Persist and cache the Function course by stable symbol ID and revision.
196. [x] Add the generated course to Module and Architecture cross-links where
    applicable.
197. [ ] Expose resolving, analyzing, generating, validating, ready, ambiguous,
    missing, and failed UI states.
198. [x] Test symbols with and without eager lessons, ambiguous names, absent
    symbols, dynamic calls, stale sources, and retry behavior.
199. [x] Commit on-demand Function generation.

### Boundary 17: Contextual Tutor Integration

200. [x] Implement the canonical compact tutor-context schema with project,
    revision, course, navigation, knowledge, source, artifact, and version
    fields.
201. [x] Keep the shared workspace Agent Input as the only question composer.
202. [x] Add an atomic context-file writer with monotonically increasing
    versions and repository-relative path validation.
203. [x] Update the context file for course, section, layer, module, function,
    source-selection, and repository-revision changes.
204. [x] Define the one-time tutor bootstrap instruction requiring a context
    file read before every answer.
205. [x] Add an AI-runtime capability check for repository-scoped context-file
    reads or an equivalent context tool.
206. [x] Send user questions without serialized course or knowledge context
    while preserving ordinary conversation history.
207. [x] Make the tutor resolve only the referenced course section, knowledge
    neighborhood, and source evidence needed for the answer.
208. [x] Handle missing, malformed, stale, incompatible, and concurrently
    updated context files without guessing the learner's location.
209. [x] Prevent ordinary Q&A from mutating durable state, allow structured
    enrichment proposals, test navigation races and session reuse, and commit
    file-backed tutor integration.

### Boundary 18: Progress, Recovery, And Invalidation

210. [ ] Define overall progress weights for inventory, modules, relationships,
    flows, symbols, validation, courses, rendering, and activation.
211. [ ] Report active invocation scope and durable record counts.
212. [ ] Report completed and remaining module-analysis and course jobs.
213. [ ] Preserve the host-owned 100-percent completion rule.
214. [ ] Add heartbeats for long AI inspections and final-response delivery.
215. [ ] Persist checkpoints after every validated pass and completed course.
216. [ ] Resume without repeating completed invocations.
217. [ ] Detect source revision changes and compute affected record scopes.
218. [ ] Mark affected knowledge, diagrams, and courses stale.
219. [ ] Regenerate only stale scopes and downstream projections.
220. [ ] Test service restart, AI interruption, malformed output, partial
    module completion, source changes, and resumed rendering.
221. [ ] Commit progress, recovery, and invalidation behavior.

### Boundary 19: End-To-End Validation

222. [ ] Run the complete Code Learner unit and integration test suites.
223. [ ] Run distribution and packaging boundary tests for both skills and
    canonical schemas.
224. [ ] Test a Python repository with packages, services, and persistence.
225. [ ] Test a TypeScript or JavaScript repository with routes, components,
    and runtime dependencies.
226. [ ] Test a C or C++ repository with function pointers, build targets, and
    multiple concrete implementations.
227. [ ] Verify Architecture breadth and mandatory diagrams in every fixture.
228. [ ] Verify every discovered extension implementation is covered or
    explicitly excluded.
229. [ ] Verify Module courses expose relationships and vertical function links.
230. [ ] Verify an uncached Function selection generates and displays a course.
231. [ ] Verify Mermaid component, sequence, dependency, state, class, ER, and
    call-graph examples through the existing renderer.
232. [ ] Verify embedded, full-pane, and pop-out layouts at desktop and mobile
    widths.
233. [ ] Verify the read-only code pane follows selected course source links.
234. [ ] Verify the shared Agent Input receives current layered context.
235. [ ] Verify restart, resume, targeted retry, and stale-source regeneration.
236. [ ] Measure initialization time, per-module time, function-generation time,
    knowledge size, course size, and browser rendering performance.
237. [ ] Confirm no tracked source files in learned repositories are modified.
238. [ ] Confirm existing v1 projects migrate or fail with actionable guidance.
239. [ ] Review all diagnostics and unresolved requirements with the operator.
240. [ ] Commit final integration fixes and record remaining limitations.

## Open Decisions

- Whether knowledge records should live in one JSONL stream or several physical
  streams behind one logical store
- Which JSON Schema implementation should enforce canonical contracts
- Which skill installation and discovery mechanism should be used by packaged
  ElectroBoy distributions
- Which language-analysis adapters should ship initially versus remain optional
- Whether independent module analysis or course jobs should run concurrently
- How much module course content should be generated during initialization
  versus when the user first selects that module
- How to validate Mermaid syntax without requiring network access
- How to present verified, inferred, dynamic, and unresolved call-graph edges
- How source-level staleness should be computed when no Git revision exists
- Whether user edits to generated courses should be preserved across targeted
  regeneration
- Whether knowledge and course artifacts should be exportable or shareable
  independently from other ElectroBoy state
