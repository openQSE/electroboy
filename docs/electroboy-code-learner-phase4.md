# ElectroBoy Code Learner Simplified Design

## Status

This document defines the replacement design for the ElectroBoy Code Learner.
It supersedes the Phase 3 source-manifest, Ctags, reconciliation, relationship,
knowledge-validation, and course-validation pipeline.

The phase number is used only in this planning document's filename. Production
modules, classes, functions, state directories, API payloads, and tests must be
named after their responsibilities. Names such as `phase4_pipeline.py` are
prohibited because they communicate chronology rather than purpose.

This document is intended for prompt review before implementation. The exact
prompts in this document are part of the design and must not be materially
changed during implementation without operator review.

## Core Decision

ElectroBoy trusts the AI's interpretation and generated course content.
ElectroBoy does not attempt to prove, validate, reconcile, normalize, repair,
or semantically reinterpret what the AI returns.

The responsibility split is deliberately narrow:

- The AI reads and interprets the repository.
- The AI identifies components and modules.
- The AI writes all instructional content and Mermaid diagrams.
- ElectroBoy assigns opaque component and module IDs.
- ElectroBoy persists AI output.
- ElectroBoy presents lesson JSONL records as slides.
- ElectroBoy maintains navigation, progress, background work, and tutor context.

ElectroBoy must not use Ctags, compiler output, source manifests, symbol
resolution, overlap reconciliation, file-coverage analysis, relationship
validation, knowledge graphs, semantic retries, or course-reference validation
in this workflow.

## Goals

1. Produce a usable Architecture course after three AI turns.
2. Make initialization practical for both small and large repositories.
3. Keep the AI in one reusable context while it discovers and teaches the code.
4. Let the AI inspect the complete repository rather than relying only on
   documentation or a static inventory.
5. Persist the AI's component and module interpretations without changing them.
6. Display Architecture as soon as it is generated.
7. Generate Module courses in the background without blocking Architecture.
8. Generate Function courses on demand from a manually entered symbol.
9. Use lesson JSONL records directly as GUI slides.
10. Preserve detailed, useful, nonrepeating AI progress messages.

## Non-Goals

ElectroBoy will not:

- determine whether the AI found every file
- determine whether an AI-provided file exists
- normalize or rewrite an AI-provided file path
- determine whether two components overlap
- reconcile duplicate component names or meanings
- validate component membership
- validate module membership
- validate architectural claims
- validate relationships between components or modules
- validate symbols, call graphs, or source ranges
- validate Mermaid semantics
- validate lesson claims or cross-references
- ask the AI to repair semantic discrepancies
- retry an AI turn because ElectroBoy disagrees with its content
- generate Markdown companion files for lessons
- compile, index, instrument, or execute the learned repository

The workflow assumes that the AI output is trustworthy.

## Terminology

### Component

A component is the smallest architectural grouping the AI finds useful for
understanding the repository. A component may contain one function, multiple
functions, one file, or multiple files. The AI chooses the boundary and name.

### Module

A module is a higher-level grouping of one or more AI-discovered components.
The AI chooses the module boundary and name after receiving the persisted
component array, including ElectroBoy's assigned component IDs.

### Architectural Concept

An architectural concept is a teachable theme in the Architecture course. It
need not correspond one-to-one with a module. Examples include system context,
request flow, persistence, scheduling, plugin discovery, or error handling.

### Lesson

A lesson is one JSONL file. It contains one `document` record followed by one
or more `section` records.

### Slide

Each `section` record in a lesson JSONL file is one GUI slide. ElectroBoy does
not transform the lesson into Markdown before displaying it.

## Simplified Workflow

```text
One reusable AI session
  -> Turn 1: discover components
  -> ElectroBoy assigns component IDs and persists components.json
  -> Turn 2: discover modules from the persisted component array
  -> ElectroBoy assigns module IDs and persists modules.json
  -> Turn 3: generate the complete Architecture course
  -> ElectroBoy persists lesson JSONL files
  -> ElectroBoy activates and displays Architecture
  -> Background: generate one complete course per module
  -> On demand: generate one complete course for a requested function
```

The first three turns use the same AI session. The repository understanding
built during component discovery remains available during module discovery and
Architecture authoring.

The first implementation will generate Module courses sequentially in the same
AI session. This keeps the model's repository understanding intact and avoids
repeated repository discovery. Architecture remains available while background
Module generation proceeds.

## Persistent Layout

No state directory or filename contains a phase number.

```text
.electroboy/code-learner/
  components.json
  modules.json
  status.json
  progress.jsonl
  tutor-context.json
  courses/
    architecture/
      course.json
      01.System-Context/
        01.Overview.jsonl
        02.Primary-Flows.jsonl
      02.Runtime-Behavior/
        01.Overview.jsonl
    modules/
      module-001/
        course.json
        01.Module-Structure/
          01.Overview.jsonl
    functions/
      <function-course-id>/
        course.json
        01.Function-Flow/
          01.Overview.jsonl
```

Directory and lesson names shown above are examples. The AI supplies course
concept directory names and lesson filenames in its course bundle. ElectroBoy
persists those values as returned.

## Component Discovery

### AI Response

The first AI turn returns one JSON array and nothing else:

```json
[
  {
    "ai_component_name": "Circuit serialization",
    "ai_file_list": [
      "src/circuit.py",
      "src/serialization.py"
    ]
  }
]
```

The AI may assign a file to more than one component. ElectroBoy does not inspect
or reconcile overlaps.

### Persisted Component Array

ElectroBoy adds one opaque ID to each array element without changing the AI's
name or file list:

```json
[
  {
    "eb_comp_id": "component-001",
    "ai_component_name": "Circuit serialization",
    "ai_file_list": [
      "src/circuit.py",
      "src/serialization.py"
    ]
  }
]
```

IDs are assigned in AI response order. A continued initialization reuses the
persisted IDs. A replacement initialization creates a new component array.

The complete array is persisted to:

```text
.electroboy/code-learner/components.json
```

## Module Discovery

The second turn uses the same AI session. ElectroBoy includes the complete
persisted component array in the prompt.

### AI Response

The AI returns one JSON array and uses `eb_comp_id` values in `ai_comp_list`:

```json
[
  {
    "ai_module_name": "Circuit model",
    "ai_comp_list": [
      "component-001",
      "component-004"
    ]
  }
]
```

ElectroBoy does not verify any component reference.

### Persisted Module Array

ElectroBoy adds one opaque module ID without changing the AI's module name or
component list:

```json
[
  {
    "eb_module_id": "module-001",
    "ai_module_name": "Circuit model",
    "ai_comp_list": [
      "component-001",
      "component-004"
    ]
  }
]
```

The complete array is persisted to:

```text
.electroboy/code-learner/modules.json
```

## Lesson JSONL Format

The lesson format reuses ElectroBoy's existing structured-document envelope.
No `lesson` or `slide` record type is introduced.

Each lesson file contains:

1. One `document` record describing the lesson.
2. Ordered `section` records containing the lesson slides.

Example:

```jsonl
{"schema_version":1,"artifact_type":"course","record_type":"document","id":"architecture-system-context-overview","order":0,"title":"Overview","status":"draft"}
{"schema_version":1,"artifact_type":"course","record_type":"section","id":"architecture-system-context-overview-01","parent_id":"architecture-system-context-overview","order":10,"heading_level":2,"title":"System Purpose","body":"The repository provides ...","status":"draft"}
{"schema_version":1,"artifact_type":"course","record_type":"section","id":"architecture-system-context-overview-02","parent_id":"architecture-system-context-overview","order":20,"heading_level":2,"title":"Primary Modules","body":"```mermaid\nflowchart LR\nA --> B\n```","status":"draft"}
```

The GUI reads the JSONL file directly:

- `document.title` is the lesson title.
- `section` records are sorted by `order`.
- Each `section` becomes one slide.
- `section.title` is the slide title.
- `section.body` is rendered as Markdown in the slide body.
- Fenced Mermaid in `section.body` is rendered as a diagram.
- Previous and Next move between section records and then lesson files.

No Markdown companion is generated or stored.

## Course Bundle Transport

One course-generation turn must return the entire course as one JSON object.
The bundle is transport data used by ElectroBoy to create directories and
lesson JSONL files. The lesson records themselves use the existing structured
document envelope.

```json
{
  "course_type": "architecture",
  "course_title": "Repository Architecture",
  "concepts": [
    {
      "directory_name": "01.System-Context",
      "concept_title": "System Context",
      "lessons": [
        {
          "file_name": "01.Overview.jsonl",
          "records": [
            {
              "schema_version": 1,
              "artifact_type": "course",
              "record_type": "document",
              "id": "architecture-system-context-overview",
              "order": 0,
              "title": "Overview",
              "status": "draft"
            },
            {
              "schema_version": 1,
              "artifact_type": "course",
              "record_type": "section",
              "id": "architecture-system-context-overview-01",
              "parent_id": "architecture-system-context-overview",
              "order": 10,
              "heading_level": 2,
              "title": "System Purpose",
              "body": "Markdown lesson content.",
              "status": "draft"
            }
          ]
        }
      ]
    }
  ]
}
```

ElectroBoy iterates this object and writes each `records` array as JSONL. It
does not validate or modify the records.

## Course Authoring Rules

The prompts instruct the AI to apply these teaching rules:

1. Organize the Architecture course around primary architectural concepts.
2. Give every concept one or more lessons.
3. Name the first lesson in every concept `01.Overview.jsonl`.
4. Start every lesson with a broad Overview slide.
5. Follow the Overview slide with progressively more detailed slides.
6. Explain purpose before implementation detail.
7. Use code and repository evidence directly, not documentation alone.
8. Include Mermaid whenever a diagram improves understanding.
9. Put the overall module/component diagram and at least one important sequence
   diagram in the first Architecture Overview lesson.
10. Use any Mermaid diagram type that clarifies the subject, including
    flowcharts, component diagrams, sequence diagrams, class diagrams, state
    diagrams, entity-relationship diagrams, and dependency graphs.
11. Keep each section record focused enough to function as one slide.
12. Put Markdown, source paths, code excerpts, and Mermaid directly in `body`.
13. Do not assume that one concept equals one module.
14. Create enough detail for both horizontal reading and vertical deep dives.

## AI Session Model

Initialization creates one reusable AI session for the repository. ElectroBoy
retains the provider session identifier and resumes it for every foreground
turn and background Module turn.

The session sequence is:

```text
component discovery
  -> module discovery
  -> Architecture course
  -> Module course 1
  -> Module course 2
  -> ...
```

Function generation may resume the same repository session when it is idle.
If Module generation is active, Function generation waits for the session
rather than creating a second repository-analysis pipeline in the first
implementation.

## Shared AI Instructions

The following text is prepended verbatim to every Code Learner analysis and
course-generation prompt:

```text
You are operating inside one persistent ElectroBoy Code Learner session.
Retain and reuse everything you have already learned about this repository.

Read the repository source code directly. Documentation, build files, examples,
and tests are useful evidence, but they are not substitutes for examining the
implementation. Inspect all parts of the repository needed to understand the
requested scope in its entirety.

ElectroBoy trusts your technical interpretation and will persist and display
your final output without semantically validating it. Be deliberate, complete,
and internally consistent. Reuse the exact ElectroBoy IDs supplied in the
prompt whenever an output field calls for those IDs.

Progress reporting is part of the task. Approximately every ten seconds while
you are working, emit one concise intermediate status sentence describing the
specific work you are doing now. Name the file, directory, component, module,
relationship, runtime flow, architectural concept, lesson, slide, or diagram
you are currently examining or creating. Send an update whenever you change
focus. Never repeat a status sentence. Never emit generic messages such as
"still working", "processing", "analyzing the repository", or elapsed-time
heartbeats. Do not include progress messages in your final JSON output.

Do not modify repository source files. Return exactly the final JSON value
requested by this turn, without a Markdown fence or explanatory prose.
```

ElectroBoy appends genuine AI progress messages to `progress.jsonl` and to the
GUI transcript. It deduplicates identical messages. ElectroBoy does not invent
heartbeat sentences when the AI is quiet.

## Exact Component Discovery Prompt

The first turn receives this prompt after the shared instructions:

```text
Repository root:
{{REPOSITORY_ROOT}}

Walk through this code repository in its entirety and identify the components
that best explain how the implementation is organized.

A component is the smallest cohesive implementation unit that is useful for
teaching this codebase. A component may consist of one function, several
functions, one file, or multiple files. Choose component boundaries based on
the implementation's actual responsibilities. Do not force components to match
directories, packages, classes, providers, or build targets unless that is how
this repository is genuinely organized.

Inspect source code, tests, build files, examples, tools, and documentation as
needed. Base the result on the code itself rather than only on documentation.
Include the files that you consider part of each component. A file may appear
in more than one component when that best represents the implementation.

Return one JSON array. Return no object around the array and no prose.

Every array element must have exactly this shape:
{
  "ai_component_name": "AI-assigned component name",
  "ai_file_list": [
    "repository/path/to/file"
  ]
}

Do not assign ElectroBoy IDs. ElectroBoy will add those after this turn.
```

## Exact Module Discovery Prompt

The second turn resumes the same session and receives this prompt after the
shared instructions:

```text
You previously inspected this repository and identified its implementation
components. ElectroBoy assigned an opaque ID to every component and persisted
the resulting array.

Here is the complete component array:
{{COMPONENT_ARRAY_JSON}}

Using your existing repository understanding and the component array above,
identify all architectural modules in the codebase.

A module is a coherent higher-level grouping of components that should be
taught together. Derive modules from the code's architecture and behavior, not
merely from directory names. Include infrastructure, runtime, extension,
integration, data-model, user-interface, command-line, testing, or other module
families when they are architecturally meaningful in this repository.

Return one JSON array. Return no object around the array and no prose.

Every array element must have exactly this shape:
{
  "ai_module_name": "AI-assigned module name",
  "ai_comp_list": [
    "component-001"
  ]
}

Use the supplied eb_comp_id values in ai_comp_list. Do not repeat component
objects and do not assign module IDs. ElectroBoy will add module IDs after this
turn.
```

## Exact Architecture Course Prompt

The third turn resumes the same session and receives this prompt after the
shared instructions:

```text
You have already inspected this repository, identified its components, and
organized those components into modules.

Here is the complete persisted component array:
{{COMPONENT_ARRAY_JSON}}

Here is the complete persisted module array:
{{MODULE_ARRAY_JSON}}

Create the complete Architecture course for this repository.

Organize the course around the primary architectural concepts needed to
understand the system. Architectural concepts are teaching themes and do not
need to map one-to-one to modules. Give every concept one or more lessons.

Each concept is represented by one directory. Number concept directory names
in course order, for example 01.System-Context and 02.Runtime-Behavior. Every
concept's first lesson must be named 01.Overview.jsonl. Number later lessons in
order using names such as 02.Primary-Flows.jsonl.

Each lesson is represented by one records array. The first record must be a
document record using the existing ElectroBoy structured-document envelope:
{
  "schema_version": 1,
  "artifact_type": "course",
  "record_type": "document",
  "id": "unique lesson id",
  "order": 0,
  "title": "Lesson title",
  "status": "draft"
}

Every remaining record is one GUI slide and must use this existing section
shape:
{
  "schema_version": 1,
  "artifact_type": "course",
  "record_type": "section",
  "id": "unique slide id",
  "parent_id": "lesson document id",
  "order": 10,
  "heading_level": 2,
  "title": "Slide title",
  "body": "Markdown slide content",
  "status": "draft"
}

Start every lesson with a broad Overview slide. Follow it with progressively
more detailed slides and vertical deep dives. Explain purpose and context
before implementation details. Keep each section focused enough to display as
one slide, but include enough technical detail to teach the code accurately.

Use the implementation directly. Include concrete file paths, important
symbols, control flow, data flow, state changes, extension points, failure
paths, tests, and operational constraints wherever they improve the lesson.

Use fenced Mermaid diagrams in section body fields whenever diagrams increase
clarity. All Mermaid diagram types are available. The first lesson of the first
concept must include:

1. An architectural component or flowchart diagram showing the primary modules
   and how they interact.
2. At least one sequence diagram showing an important end-to-end runtime flow.

Add further component, flowchart, sequence, class, state, dependency,
entity-relationship, or other Mermaid diagrams wherever useful.

Return exactly one JSON object with this shape:
{
  "course_type": "architecture",
  "course_title": "Repository Architecture",
  "concepts": [
    {
      "directory_name": "01.Concept-Name",
      "concept_title": "Concept Name",
      "lessons": [
        {
          "file_name": "01.Overview.jsonl",
          "records": [
            { "record_type": "document" },
            { "record_type": "section" }
          ]
        }
      ]
    }
  ]
}

Populate every record completely using the shapes above. Do not use abbreviated
placeholder records from the shape example. Return no prose outside the JSON
object.
```

## Exact Module Course Prompt

After Architecture is active, ElectroBoy loops over the persisted module array.
Each turn resumes the same session and receives this prompt after the shared
instructions:

```text
Create the complete Module course for this module:
{{SELECTED_MODULE_JSON}}

Here is the complete persisted component array:
{{COMPONENT_ARRAY_JSON}}

Here is the complete persisted module array:
{{MODULE_ARRAY_JSON}}

Use your existing understanding of the repository. Revisit the source files
belonging to the selected module's components and inspect any collaborating
code needed to explain the module accurately.

Teach the module horizontally and vertically. Explain its purpose, boundaries,
contained components, public entry points, internal collaboration, data and
control flow, state, extension points, dependencies, error behavior, tests,
and important implementation details. Show how it participates in the larger
architecture without regenerating the Architecture course.

Organize the Module course into architectural concepts. Every concept has one
or more lesson JSONL files, and every concept starts with 01.Overview.jsonl.
Each lesson starts with one broad Overview section and proceeds into more
detailed section records. Each section record is one GUI slide.

Use exactly the document and section record shapes defined during Architecture
course generation. Put Markdown and fenced Mermaid diagrams directly in body
fields. Use any Mermaid diagram type that improves understanding. Include
sequence or flow diagrams for important runtime behavior.

Return exactly one JSON object with this shape:
{
  "course_type": "module",
  "course_title": "Selected module name",
  "module_id": "exact eb_module_id from the selected module",
  "concepts": [
    {
      "directory_name": "01.Concept-Name",
      "concept_title": "Concept Name",
      "lessons": [
        {
          "file_name": "01.Overview.jsonl",
          "records": [
            { "record_type": "document" },
            { "record_type": "section" }
          ]
        }
      ]
    }
  ]
}

Populate every record completely. Return no prose outside the JSON object.
```

## Exact Function Course Prompt

Function courses are generated on demand. The user supplies a symbol string;
ElectroBoy does not prevalidate or resolve it. The AI receives this prompt after
the shared instructions:

```text
Create a Function course for the user-requested symbol:
{{USER_SYMBOL_TEXT}}

Here is the complete persisted component array:
{{COMPONENT_ARRAY_JSON}}

Here is the complete persisted module array:
{{MODULE_ARRAY_JSON}}

Use your existing repository understanding and inspect the code directly.
Locate the requested symbol as best you can. Explain any ambiguity naturally
in the lesson rather than asking ElectroBoy to validate or resolve the symbol.

Teach the function's purpose, location, inputs, outputs, callers, callees,
control flow, data flow, state changes, side effects, error paths, important
branches, and role in its component, module, and the overall architecture.
Include a Mermaid call graph and a Mermaid sequence or flow diagram whenever
they clarify execution.

Organize the Function course into one or more concepts. Every concept starts
with 01.Overview.jsonl. Each lesson starts with one broad Overview section and
then proceeds into progressively more detailed section records. Each section
record is one GUI slide.

Use exactly the existing document and section record shapes used by the
Architecture course. Put Markdown and fenced Mermaid directly in body fields.

Return exactly one JSON object with this shape:
{
  "course_type": "function",
  "course_title": "Requested function",
  "requested_symbol": "exact user-supplied symbol text",
  "concepts": [
    {
      "directory_name": "01.Function-Flow",
      "concept_title": "Function Flow",
      "lessons": [
        {
          "file_name": "01.Overview.jsonl",
          "records": [
            { "record_type": "document" },
            { "record_type": "section" }
          ]
        }
      ]
    }
  ]
}

Populate every record completely. Return no prose outside the JSON object.
```

## Contextual Tutor Prompt

ElectroBoy updates `.electroboy/code-learner/tutor-context.json` whenever the
user changes course, concept, lesson, slide, code file, or selected code range.
The tutor receives the path once when its session starts. Individual questions
do not include a large repeated context prompt.

Exact tutor session prompt:

```text
You are the ElectroBoy Code Learner tutor for this repository:
{{REPOSITORY_ROOT}}

Before answering every learner question, read this context file:
.electroboy/code-learner/tutor-context.json

The file tells you which Architecture, Module, or Function course the learner
is viewing; the current concept, lesson, and slide; and the code file and range
currently visible in the workspace. Treat that file as the learner's current
question context. Inspect the referenced lesson JSONL and repository source as
needed before answering.

Answer the learner's actual question directly. Do not require the learner to
repeat filenames, symbols, line numbers, module names, or slide titles already
present in the context file. Explain the code at the depth implied by the
current course and question. Distinguish what the code demonstrates from what
you infer, but do not discuss ElectroBoy's internal orchestration.
```

## Progress Behavior

Progress remains append-only and detailed:

- ElectroBoy appends stage transitions such as component discovery, module
  discovery, Architecture authoring, persistence, activation, and each
  background Module course.
- AI progress messages are appended in arrival order.
- Identical consecutive messages are discarded.
- Generic AI messages are discarded.
- Synthetic heartbeat messages are not generated.
- Warnings and errors from the AI runtime remain visually distinct.
- Course content is never included in the progress transcript.
- Architecture progress ends when Architecture is persisted and visible.
- Background Module progress continues independently after activation.

The AI is instructed to report approximately every ten seconds. When the AI
runtime emits no status event, ElectroBoy leaves the latest useful status in
place rather than inventing an explanation.

## GUI Behavior

### Initialization

Before initialization, only Initialize is active. Architecture, Module, and
Function controls remain disabled.

Initialization progress shows:

1. Component discovery.
2. Component persistence.
3. Module discovery.
4. Module persistence.
5. Architecture course generation.
6. Architecture activation.

When Architecture is persisted, initialization is complete and Architecture
becomes selectable. Background Module generation does not hold the progress bar
below 100 percent.

### Architecture

The Architecture menu opens the first concept, first lesson, and first section.
The outline lists concepts and lessons from the persisted course bundle.
Previous and Next traverse sections and lesson boundaries.

### Module

The Module selector is populated directly from `modules.json`. A Module course
may be:

- pending
- generating
- ready

Selecting a pending or generating module displays that status. Selecting a
ready module opens its first lesson.

### Function

The user enters a symbol manually. ElectroBoy passes the string to the AI
without symbol validation. When generation completes, the Function course is
displayed using the same concept, lesson, and slide navigation.

### Slide Rendering

The GUI renders a section record's `body` as Markdown and Mermaid. If content
cannot be rendered, the GUI displays the body as best it can. Rendering does
not alter initialization or course status.

## Code Organization

The replacement implementation must use domain-oriented names. It must not add
files, classes, functions, state keys, or API fields containing `phase4`.

The intended small set of implementation boundaries is:

- `discovery.py`: component and module AI turns plus ID assignment
- `course_generation.py`: Architecture, Module, and Function course turns plus
  course-bundle persistence
- `store.py`: components, modules, status, progress, lesson JSONL, and course
  index persistence
- `navigation.py`: concept, lesson, and section traversal
- `tutor_context.py`: compact current-view context
- `progress.py`: AI activity sanitization and append-only progress
- existing `controller.py`, `routes.py`, and frontend assets: service and GUI
  integration

Do not split contracts, prompts, validation, persistence, and orchestration into
separate files unless a real independent responsibility requires it. Prompts
should live beside the operation that invokes them or in one plainly named
`prompts.py` if sharing makes that simpler.

## Phase 3 Cleanup

The replacement is a cleanup, not another layer beside Phase 3.

After the new path is connected and characterized, remove:

- `phase3_pipeline.py`
- `phase3_store.py`
- `phase3_prompts.py`
- `phase3_contracts.py`
- `phase3_contract_catalog.py`
- `phase3_revision.py`
- `phase3_courses.py`
- `phase3_tutor.py`
- `schemas/phase3.schema.json`
- Phase 3 branches, payload keys, helper names, and state-path checks in
  `controller.py`
- Phase 3-specific tests

Also remove validation-era modules when no retained non-Phase-3 behavior uses
them:

- `ctags_evidence.py`
- `source_manifest.py`
- `component_contract.py`
- `component_manifest.py`
- `components.py`
- `overlap.py`
- `reconciliation.py`
- `modules.py`
- `relationships.py`
- `knowledge.py`
- `architecture_knowledge.py`
- `module_knowledge.py`
- `function_knowledge.py`
- `knowledge_validation.py`
- `analysis_adapters.py`
- `analysis_passes.py`
- `isolated_runtime.py`
- validation-only schemas and skills

Remove the Universal Ctags and Jansson submodules, `.gitmodules` entries, build
logic, and notices if no remaining ElectroBoy feature uses them.

Retain useful behavior rather than obsolete structure:

- reusable AI provider sessions
- initialization lease and Abort behavior
- continue-or-replace initialization choice
- cache clearing
- progress streaming and visual warning/error treatment
- background Module status
- course navigation
- contextual tutor integration
- existing Code Learner visual design

There must be one active Code Learner implementation after cutover. Do not keep
Phase 2, Phase 3, and the replacement behind generation-selection branches.
Existing old cache may be cleared rather than migrated.

## Failure and Retry Behavior

The workflow does not inspect AI content for semantic correctness and does not
run semantic repair turns.

There is no component reconciliation, module repair, relationship repair,
coverage repair, source-reference repair, diagram repair, or course repair.
There is no AI retry caused by an ElectroBoy content judgment.

Provider session execution and Abort behavior remain infrastructure concerns,
not content validation. Partial persisted results allow Continue to resume at
the next unfinished turn without rediscovering completed arrays.

## Implementation Checklist

Implementation must proceed in the order below. Check each item in this file as
it is completed and commit at the stated functional boundaries.

### 1. Characterize the Replacement Boundary

- [ ] Record the current GUI, Abort, Continue, Replace, Clear Cache, tutor, and
      navigation behaviors that must remain.
- [ ] Identify all Phase 3 imports and state-path dependencies in the controller,
      routes, workflow registration, frontend, and tests.
- [ ] Confirm the new persistent layout has no phase-numbered names.
- [ ] Confirm no implementation file or symbol is named with `phase4`.

Commit boundary: characterization tests and replacement boundary.

### 2. Add the Simple Store

- [ ] Add responsibility-named storage for `components.json`, `modules.json`,
      `status.json`, `progress.jsonl`, course bundles, and lesson JSONL files.
- [ ] Persist component and module arrays without semantic alteration.
- [ ] Persist each course lesson `records` array directly as JSONL.
- [ ] Add course indexes containing concept order, lesson order, and readiness.
- [ ] Add cache clearing for the replacement layout.
- [ ] Add focused persistence tests.

Commit boundary: trusted-output persistence.

### 3. Implement the Reusable AI Session

- [ ] Reuse one provider session across component, module, Architecture, and
      background Module turns.
- [ ] Apply the exact shared AI instructions from this document.
- [ ] Preserve Abort behavior for the active provider process.
- [ ] Preserve Continue by reading already persisted turn outputs.
- [ ] Add tests proving subsequent turns receive the provider session ID.

Commit boundary: reusable learner AI session.

### 4. Implement Component Discovery

- [ ] Use the exact Component Discovery prompt.
- [ ] Assign `component-001`, `component-002`, and subsequent IDs in response
      order.
- [ ] Persist the resulting array to `components.json`.
- [ ] Do not enumerate files, invoke Ctags, reconcile overlap, or investigate
      coverage.
- [ ] Stream genuine nonrepeating AI progress.
- [ ] Add focused tests for prompt content, ID assignment, and persistence.

Commit boundary: trusted component discovery.

### 5. Implement Module Discovery

- [ ] Resume the same AI session.
- [ ] Include the complete persisted component array in the exact Module
      Discovery prompt.
- [ ] Assign `module-001`, `module-002`, and subsequent IDs in response order.
- [ ] Persist the resulting array to `modules.json`.
- [ ] Do not validate `ai_comp_list`.
- [ ] Add focused tests for context reuse, prompt content, IDs, and persistence.

Commit boundary: trusted module discovery.

### 6. Implement Architecture Generation

- [ ] Resume the same AI session.
- [ ] Include both complete persisted arrays in the exact Architecture prompt.
- [ ] Persist the returned course bundle and each lesson JSONL file.
- [ ] Do not generate Markdown companions.
- [ ] Do not validate course content, diagrams, references, or IDs.
- [ ] Activate Architecture immediately after persistence.
- [ ] Add a small-repository acceptance test requiring only three foreground AI
      turns before Architecture becomes available.

Commit boundary: Architecture course generation and activation.

### 7. Implement Direct Slide Navigation

- [ ] Read lesson JSONL directly.
- [ ] Treat each `section` record as one slide.
- [ ] Traverse sections, lessons, and concepts with Previous and Next.
- [ ] Render `body` as Markdown and Mermaid without creating `.md` files.
- [ ] Display content as best as possible without changing course readiness.
- [ ] Update the outline from course concept and lesson indexes.
- [ ] Add navigation and rendering tests.

Commit boundary: direct JSONL lesson presentation.

### 8. Implement Background Module Courses

- [ ] Start Module generation only after Architecture is active.
- [ ] Generate modules sequentially in persisted module order using the same AI
      session.
- [ ] Use the exact Module Course prompt.
- [ ] Persist each returned bundle and its lesson JSONL files.
- [ ] Expose pending, generating, and ready status in the Module selector.
- [ ] Ensure one Module failure does not disable Architecture or other modules.
- [ ] Add scheduler and GUI status tests.

Commit boundary: background Module courses.

### 9. Implement On-Demand Function Courses

- [ ] Accept the user's symbol text without host-side resolution.
- [ ] Use the exact Function Course prompt.
- [ ] Persist and display the returned course bundle directly.
- [ ] Do not require a canonical symbol ID.
- [ ] Add function request, persistence, and navigation tests.

Commit boundary: on-demand Function courses.

### 10. Update Contextual Tutoring

- [ ] Write current course, module/function target, concept, lesson, slide, code
      file, and selected range to `tutor-context.json`.
- [ ] Start the tutor with the exact tutor prompt.
- [ ] Do not append the full context to every learner question.
- [ ] Update context whenever navigation or code selection changes.
- [ ] Add tutor-context tests.

Commit boundary: contextual tutoring.

### 11. Simplify Progress

- [ ] Require the exact shared ten-second progress instruction in every AI turn.
- [ ] Append AI status messages rather than replacing prior messages.
- [ ] Deduplicate identical consecutive messages.
- [ ] Suppress generic or synthetic heartbeat messages.
- [ ] Preserve visually distinct runtime warnings and errors.
- [ ] Separate foreground Architecture progress from background Module progress.
- [ ] Add progress transcript tests.

Commit boundary: useful learner progress.

### 12. Cut Over the Controller and GUI

- [ ] Replace Phase 3 branches with the single simplified implementation.
- [ ] Preserve Project, Learn, and Outline menu behavior and styling.
- [ ] Preserve Initialize, Abort, Continue, Replace, Clear Cache, and Clear List.
- [ ] Populate Module choices from `modules.json`.
- [ ] Activate Architecture after its course bundle is persisted.
- [ ] Keep unavailable Module and Function content visibly pending rather than
      disabling the completed Architecture course.
- [ ] Remove phase-numbered API and payload concepts.

Commit boundary: simplified workflow cutover.

### 13. Remove Phase 3 and Validation Infrastructure

- [ ] Delete all `phase3_*` implementation modules and schema files.
- [ ] Delete Ctags, source-manifest, reconciliation, relationship, knowledge,
      and semantic course-validation code no longer used.
- [ ] Remove Universal Ctags and Jansson dependencies when unused.
- [ ] Delete obsolete Phase 2/Phase 3 selection and migration branches.
- [ ] Delete obsolete tests and replace them with behavior-focused tests for the
      simplified implementation.
- [ ] Confirm no active source or test imports a removed module.
- [ ] Confirm no active state path contains `/phase3/`.
- [ ] Confirm no implementation identifier contains `phase4`.

Commit boundary: obsolete learner pipeline removal.

### 14. End-to-End Verification

- [ ] Initialize `qhw-datastructures` from an empty cache.
- [ ] Confirm exactly three foreground AI turns produce visible Architecture.
- [ ] Confirm component and module arrays are persisted with ElectroBoy IDs.
- [ ] Confirm the Architecture outline and first slide display immediately.
- [ ] Confirm Mermaid diagrams render from section bodies.
- [ ] Confirm Module courses continue in the background.
- [ ] Confirm a manually entered Function symbol generates a course on demand.
- [ ] Confirm the tutor answers using `tutor-context.json`.
- [ ] Confirm progress contains detailed, nonrepeating AI messages and no
      fabricated heartbeat sentence.
- [ ] Confirm Clear Cache returns the GUI to Initialize-only state.
- [ ] Run the complete Code Learner test suite.
- [ ] Run the complete repository test suite and report unrelated baseline
      failures separately.

Commit boundary: end-to-end simplified Code Learner verification.

## Acceptance Criteria

The replacement is complete when:

1. A clean initialization uses three foreground AI turns before Architecture is
   available.
2. `components.json` contains the AI component array plus ElectroBoy IDs.
3. `modules.json` contains the AI module array plus ElectroBoy IDs.
4. Architecture lessons are persisted only as JSONL and displayed directly as
   slides.
5. The first Architecture Overview includes an architecture diagram and a
   sequence diagram.
6. Module courses generate after Architecture is available.
7. Function courses accept manually entered symbols without host validation.
8. ElectroBoy performs no semantic validation of AI component, module, course,
   diagram, path, relationship, or symbol content.
9. No semantic repair or verification AI passes remain.
10. No active implementation file, class, function, state path, or payload uses
    `phase3` or `phase4` naming.
11. Ctags and its supporting dependencies are absent when no other feature uses
    them.
12. Progress contains only stage events and useful, nonrepeating AI status.
13. The GUI retains the existing ElectroBoy Code Learner visual language and
    workflows while using the simplified backend.
