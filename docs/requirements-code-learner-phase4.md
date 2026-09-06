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
- The AI assigns component and module IDs using ElectroBoy's formats.
- The AI writes component, module, course-index, and lesson files directly to
  paths supplied by ElectroBoy beneath the master course directory.
- Every analysis and course-generation AI invocation reads accumulated raw AI
  knowledge and writes newly learned knowledge as additional Markdown files.
- The AI writes all instructional content and Mermaid diagrams.
- ElectroBoy creates the repository-named master course directory.
- ElectroBoy creates the shared `raw-ai-knowledge` directory and assigns a
  unique invocation UUID to every AI invocation that may write there.
- ElectroBoy adopts and reads the files written by the AI.
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
11. Share accumulated AI understanding across independent Module and Function
    sessions without copying it into their prompts.

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
- parse, index, organize, validate, or display raw AI knowledge
- modify, merge, deduplicate, or reconcile raw AI knowledge files
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
component array, including the component IDs assigned during the first AI turn.

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
ElectroBoy creates courses/<repository-name>/
  -> One reusable AI session
  -> Turn 1: AI discovers components, assigns comp-* IDs, and writes components.json
  -> Turn 2: AI reads components.json, discovers modules, assigns mod-* IDs,
             and writes modules.json
  -> Turn 3: AI reads both files and writes the complete Architecture course
  -> ElectroBoy activates and displays Architecture
  -> Background: independent AI sessions generate Module courses concurrently
  -> On demand: an independent AI session generates a requested Function course
```

The first three turns use the same AI session. The repository understanding
built during component discovery remains available during module discovery and
Architecture authoring.

After Architecture is available, ElectroBoy may distribute Module courses
across a bounded pool of independent AI sessions. Function courses use
independent AI sessions and do not wait for a Module worker to release the
primary session.
Every independent session receives the shared raw-knowledge directory and uses
it as persistent repository context.

## Persistent Layout

No state directory or filename contains a phase number. ElectroBoy obtains the
repository name from the repository root directory name and creates the master
course directory before starting the AI session. For a repository rooted at
`/home/user/src/qhw-datastructures`, the master directory is
`qhw-datastructures`.

```text
.electroboy/code-learner/
  status.json
  progress.jsonl
  tutor-context.json
  courses/
    qhw-datastructures/
      components.json
      modules.json
      raw-ai-knowledge/
        <AI-chosen-concept>-<invocation-uuid>.md
      architecture/
        course.json
        01.System-Context/
          01.Overview.jsonl
          02.Primary-Flows.jsonl
        02.Runtime-Behavior/
          01.Overview.jsonl
      modules/
        mod-001/
          course.json
          01.Module-Structure/
            01.Overview.jsonl
      functions/
        <function-course-id>/
          course.json
          01.Function-Flow/
            01.Overview.jsonl
```

The master directory name is exactly the repository root directory's basename.
ElectroBoy creates this master directory before invoking the AI and does not
rewrite its name. ElectroBoy gives the AI exact output paths beneath it. The AI
creates the required `architecture`, `modules`, `functions`, concept, and lesson
directories as part of its assigned turns.

## Raw AI Knowledge

ElectroBoy creates `raw-ai-knowledge/` directly beneath the repository-named
master course directory before the first AI invocation. This directory is
shared, append-only working memory for all Code Learner discovery and
course-generation AI sessions. Its contents are for AI consumption only and
are not course material or GUI data.

Component and module discovery must place as much detailed implementation
knowledge there as possible. Architecture, Module, and Function course sessions
use that accumulated knowledge as their primary repository briefing so they do
not repeat the initial repository-wide code dive.

ElectroBoy imposes no semantic structure, schema, concept taxonomy, manifest,
index, or file count. The AI decides what knowledge is useful, how to divide it
among Markdown files, and which existing files are relevant to a later task.
ElectroBoy does not read or validate the content.

For every AI invocation that can write knowledge, ElectroBoy generates a new
UUID and supplies both the UUID and the absolute `raw-ai-knowledge` path in the
prompt. The AI must never edit, rename, replace, or delete an existing knowledge
file. It records new knowledge only by creating new Markdown files. Every new
filename must append that invocation's UUID immediately before `.md`, for
example:

```text
provider-lifecycle-550e8400-e29b-41d4-a716-446655440000.md
```

An invocation may create multiple knowledge files when that better separates
the primary concepts it discovers. Each filename created by that invocation
uses the same supplied UUID suffix and an AI-chosen, distinct prefix. This is a
prompt contract only; ElectroBoy does not inspect or enforce the filenames or
the contents.

Concurrent sessions may read the directory while other sessions add files.
Knowledge is therefore eventually consistent: each invocation uses the files
available when it reads the directory, and its additions become available to
later invocations. Course workers write course output only to their assigned
course directories and knowledge only as new files under `raw-ai-knowledge/`.
ElectroBoy does not lock the directory after Architecture generation or prevent
later Module and Function sessions from adding knowledge.

## Component Discovery

### AI-Written Component File

ElectroBoy supplies the exact `components.json` path. The first AI turn assigns
component IDs and writes the complete JSON array directly to that path:

```json
[
  {
    "eb_comp_id": "comp-001",
    "ai_component_name": "Circuit serialization",
    "ai_file_list": [
      "src/circuit.py",
      "src/serialization.py"
    ]
  }
]
```

The AI uses `comp-001`, `comp-002`, and subsequent unique numbers. ElectroBoy
adopts these IDs without checking or replacing them.

For a repository named `qhw-datastructures`, the supplied path is:

```text
.electroboy/code-learner/courses/qhw-datastructures/components.json
```

## Module Discovery

The second turn uses the same AI session. ElectroBoy supplies the existing
`components.json` path and the exact `modules.json` output path. The AI reads
the component file directly.

### AI-Written Module File

The AI assigns module IDs and writes one JSON array directly to `modules.json`.
It uses `eb_comp_id` values from `components.json` in `ai_comp_list`:

```json
[
  {
    "eb_module_id": "mod-001",
    "ai_module_name": "Circuit model",
    "ai_comp_list": [
      "comp-001",
      "comp-004"
    ]
  }
]
```

The AI uses `mod-001`, `mod-002`, and subsequent unique numbers. ElectroBoy
adopts these IDs and does not verify any component reference.

For a repository named `qhw-datastructures`, the supplied output path is:

```text
.electroboy/code-learner/courses/qhw-datastructures/modules.json
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

## Direct Course Writing

Course-generation turns write directly inside the repository-named master
course directory created by ElectroBoy. The AI creates concept directories,
lesson JSONL files, and one `course.json` index at the exact course root supplied
by ElectroBoy. Large course content is never returned through the final AI
response and ElectroBoy does not unpack a course bundle.

The AI-written `course.json` records the display order:

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
          "lesson_title": "Overview"
        }
      ]
    }
  ]
}
```

The corresponding records are written directly to
`01.System-Context/01.Overview.jsonl` using the Lesson JSONL Format above.
ElectroBoy reads and displays the files written by the AI without validating or
modifying them.

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

Initialization creates one reusable primary AI session for the repository.
ElectroBoy retains its provider session identifier and resumes it for the three
foreground turns so component discovery, module discovery, and Architecture
authoring share live context.

The session sequence is:

```text
component discovery
  -> module discovery
  -> Architecture course
  -> Architecture becomes available
  -> independent Module and Function sessions use raw-ai-knowledge/
```

After Architecture is active, ElectroBoy starts independent Module sessions
through a bounded worker pool. Each worker receives one module assignment, the
repository and persisted-array paths, the raw-knowledge path, a fresh invocation
UUID, and a unique course output directory. Function generation starts another
independent session with the same shared inputs and its own output directory.
These sessions may run concurrently.

The learner AI process runs with permission to write beneath the
ElectroBoy-created master course directory. ElectroBoy supplies absolute input
and output paths for every turn. It does not copy, unpack, rewrite, or
semantically inspect the files after the AI writes them.

## Shared AI Instructions

The following text is prepended verbatim to every Code Learner analysis and
course-generation prompt:

```text
You are operating as an ElectroBoy Code Learner AI session. Reuse any live
repository context available in this session and the accumulated knowledge
provided below.

Follow the source-inspection scope in the current turn. When source inspection
is required, read repository source code directly. Documentation, build files,
examples, and tests are useful evidence, but they are not substitutes for
examining the implementation.

Exclude generated files, vendored dependencies, caches, build outputs, binary
assets, and version-control metadata unless needed to understand the
implementation.

Be deliberate, complete, and internally consistent. Follow the exact ID formats
and input and output paths supplied in each prompt.

Accumulated repository knowledge is available at:
{{RAW_AI_KNOWLEDGE_DIRECTORY}}

Your unique invocation UUID is:
{{AI_INVOCATION_UUID}}

Read and use the accumulated knowledge as you see fit. As you inspect the
repository and develop additional understanding, record useful new knowledge
in one or more Markdown files in that directory. You decide the concepts,
organization, number of files, and descriptive filename prefixes.

The knowledge directory is append-only and may be shared with concurrent AI
sessions. Never edit, rename, replace, or delete an existing knowledge file.
Create new files only. Every new knowledge filename must append your exact
invocation UUID immediately before the `.md` extension, for example
`request-flow-{{AI_INVOCATION_UUID}}.md`. If you create multiple files, give
each one a distinct descriptive prefix and the same UUID suffix.

Do not modify repository source files. Write only the Code Learner output files
requested by the turn. After the files are complete, return one concise sentence
identifying the completed artifact and its path. Do not repeat file contents in
your final response.
```

ElectroBoy appends genuine AI progress messages to `progress.jsonl` and to the
GUI transcript. It deduplicates identical messages. ElectroBoy does not invent
heartbeat sentences when the AI is quiet.

ElectroBoy expands `{{RAW_AI_KNOWLEDGE_DIRECTORY}}` with the same absolute
directory path for every invocation and expands `{{AI_INVOCATION_UUID}}` with a
new UUID for that invocation. It passes the directory path rather than inlining
the directory's contents into the prompt.

## Exact Component Discovery Prompt

The first turn receives this prompt after the shared instructions:

```text
Repository root:
{{REPOSITORY_ROOT}}

ElectroBoy-created master course directory:
{{MASTER_COURSE_DIRECTORY}}

Write the component array directly to this exact path:
{{COMPONENTS_PATH}}

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
Include the files that you consider part of each component.

As you build this understanding, capture as much detailed, reusable repository
knowledge as possible in new Markdown files under the supplied raw AI knowledge
directory. This knowledge will be the primary input used by the Architecture
course turn and by independent Module and Function course sessions. Record the
implementation details, responsibilities, interactions, important symbols,
control and data flows, state, failure behavior, extension points, tests, and
other findings that later course authors should not need to rediscover. Separate
primary concepts into multiple files when useful. Follow the append-only and
invocation-UUID filename rules in the shared instructions.

Progress reporting for this turn is part of the task. Approximately every ten
seconds, emit one concise intermediate status sentence naming the source area,
file, directory, implementation responsibility, component boundary, or raw
knowledge concept you are currently examining or recording. Send an update when
you change focus. Never repeat a status sentence. Never emit generic messages
such as "still working", "processing", "analyzing the repository", or an
elapsed-time heartbeat. Do not write progress messages into output files.

Assign each component a unique ID in discovery order. IDs must use the exact
format `comp-<three-digit-number>`, beginning with `comp-001` and incrementing
without reuse.

Write one complete JSON array to `{{COMPONENTS_PATH}}`. Do not wrap the array in
another object.

Every array element must have exactly this shape:
{
  "eb_comp_id": "comp-001",
  "ai_component_name": "AI-assigned component name",
  "ai_file_list": [
    "repository/path/to/file"
  ]
}

The master course directory already exists. Do not rename or replace it. When
the file has been completely written, return only a concise sentence confirming
the artifact and path. Do not return the JSON array in your final response.
```

## Exact Module Discovery Prompt

The second turn resumes the same session and receives this prompt after the
shared instructions:

```text
You previously inspected this repository and wrote its implementation
components to:
{{COMPONENTS_PATH}}

Read that complete component array before beginning this turn.

Write the module array directly to this exact path:
{{MODULES_PATH}}

Using your existing repository understanding and the component array above,
identify all architectural modules in the codebase.

A module is a coherent higher-level grouping of components that should be
taught together. Derive modules from the code's architecture and behavior, not
merely from directory names. Include infrastructure, runtime, extension,
integration, data-model, user-interface, command-line, testing, or other module
families when they are architecturally meaningful in this repository.

Read the accumulated raw AI knowledge as you see fit. Record as much detailed,
reusable knowledge as possible about module boundaries, cross-module
interactions, runtime flows, interfaces, dependencies, state, extension points,
failure behavior, tests, important symbols, and other findings. This knowledge
will be the primary input used by the Architecture course turn and by independent
Module and Function course sessions, so later course authors should not need to
repeat the repository-wide code dive. Write the additional knowledge in new
Markdown files and follow the append-only and invocation-UUID filename rules in
the shared instructions.

Progress reporting for this turn is part of the task. Approximately every ten
seconds, emit one concise intermediate status sentence naming the components,
module boundary, dependency, cross-module interaction, runtime flow, or raw
knowledge concept you are currently examining or recording. Send an update when
you change focus. Never repeat a status sentence. Never emit generic messages
such as "still working", "processing", "analyzing the repository", or an
elapsed-time heartbeat. Do not write progress messages into output files.

Assign each module a unique ID in discovery order. IDs must use the exact format
`mod-<three-digit-number>`, beginning with `mod-001` and incrementing without
reuse.

Write one complete JSON array to `{{MODULES_PATH}}`. Do not wrap the array in
another object.

Every array element must have exactly this shape:
{
  "eb_module_id": "mod-001",
  "ai_module_name": "AI-assigned module name",
  "ai_comp_list": [
    "comp-001"
  ]
}

Use the `eb_comp_id` values in the component file in `ai_comp_list`. Do not
repeat component objects. When the file has been completely written, return
only a concise sentence confirming the artifact and path. Do not return the
JSON array in your final response.
```

## Exact Architecture Course Prompt

The third turn resumes the same session and receives this prompt after the
shared instructions:

```text
You have already inspected this repository, identified its components, and
organized those components into modules.

Read the complete persisted component array from:
{{COMPONENTS_PATH}}

Read the complete persisted module array from:
{{MODULES_PATH}}

The accumulated raw AI knowledge directory is:
{{RAW_AI_KNOWLEDGE_DIRECTORY}}

Write the complete Architecture course beneath this exact directory:
{{ARCHITECTURE_COURSE_DIRECTORY}}

Create the complete Architecture course for this repository.

Before authoring the course, read and use the accumulated raw AI knowledge as
the primary source for the repository understanding gathered during component
and module discovery. Reuse the live context from those turns. Do not repeat a
repository-wide code dive. Inspect targeted source files only when the
accumulated knowledge has a material gap that prevents a clear or accurate
lesson. Add any newly gathered architectural understanding only through new
Markdown files that follow the append-only and invocation-UUID filename rules
in the shared instructions.

Progress reporting for this turn is part of the task. Approximately every ten
seconds, emit one concise intermediate status sentence naming the raw knowledge
concept, architectural concept, lesson, slide, or Mermaid diagram you are
currently using or creating. Send an update when you change focus. Never repeat
a status sentence. Never emit generic messages such as "still working",
"processing", "creating the course", or an elapsed-time heartbeat. Do not write
progress messages into course or knowledge files.

Organize the course around the primary architectural concepts needed to
understand the system. Architectural concepts are teaching themes and do not
need to map one-to-one to modules. Give every concept one or more lessons.

Each concept is represented by one directory. Number concept directory names
in course order, for example 01.System-Context and 02.Runtime-Behavior. Every
concept's first lesson must be named 01.Overview.jsonl. Number later lessons in
order using names such as 02.Primary-Flows.jsonl.

Create each lesson as a JSONL file. Its first line must be a document record
using the existing ElectroBoy structured-document envelope:
{
  "schema_version": 1,
  "artifact_type": "course",
  "record_type": "document",
  "id": "unique lesson id",
  "order": 0,
  "title": "Lesson title",
  "status": "draft"
}

Every remaining line is one GUI slide and must use this existing section shape:
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

Write the complete instructional content for every slide as Markdown in that
section record's `body` field. Put explanatory prose, lists, tables, code blocks,
source paths, symbol references, and fenced Mermaid diagrams in `body`; do not
leave lesson details only in titles, metadata, or the course index.

Start every lesson with a broad Overview slide. Follow it with progressively
more detailed slides and vertical deep dives. Explain purpose and context
before implementation details. Keep each section focused enough to display as
one slide, but include enough technical detail to teach the code accurately.

Ground the course in the implementation knowledge already collected. Include
concrete file paths, important symbols, control flow, data flow, state changes,
extension points, failure paths, tests, and operational constraints wherever
they improve the lesson.

Use fenced Mermaid diagrams in section body fields whenever diagrams increase
clarity. All Mermaid diagram types are available. The first lesson of the first
concept must include:

1. An architectural component or flowchart diagram showing the primary modules
   and how they interact.
2. At least one sequence diagram showing an important end-to-end runtime flow.

Add further component, flowchart, sequence, class, state, dependency,
entity-relationship, or other Mermaid diagrams wherever useful.

Write `course.json` at the root of `{{ARCHITECTURE_COURSE_DIRECTORY}}` using this
index shape:
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
          "lesson_title": "Overview"
        }
      ]
    }
  ]
}

Write every indexed lesson to its concept directory beneath
`{{ARCHITECTURE_COURSE_DIRECTORY}}`. Populate every JSONL record completely
using the shapes above. Do not use abbreviated placeholder records from the
shape example. Create all required directories and files. When the complete
course has been written, return only a concise sentence confirming the course
and its path. Do not return the course contents in your final response.
```

## Exact Module Course Prompt

After Architecture is active, ElectroBoy distributes entries from the persisted
module array across independent background AI sessions. Each invocation receives
this prompt after the shared instructions:

```text
Create the complete Module course for this module ID:
{{SELECTED_MODULE_ID}}

Read the complete persisted component array from:
{{COMPONENTS_PATH}}

Read the complete persisted module array from:
{{MODULES_PATH}}

Find `{{SELECTED_MODULE_ID}}` in that module file, then write its complete
Module course beneath this exact directory:
{{MODULE_COURSE_DIRECTORY}}

Use the accumulated raw AI knowledge as you see fit. Revisit the source files
belonging to the selected module's components and inspect any collaborating code
needed to explain the module accurately. Write newly gathered understanding to
new UUID-suffixed files in the raw-knowledge directory as required by the shared
instructions.

Progress reporting for this turn is part of the task. Approximately every ten
seconds, emit one concise intermediate status sentence naming the selected
module, relevant component, source area, runtime flow, lesson, slide, Mermaid
diagram, or new raw knowledge concept you are currently using or creating. Send
an update when you change focus. Never repeat a status sentence. Never emit
generic messages such as "still working", "processing", "creating the module
course", or an elapsed-time heartbeat. Do not write progress messages into
course or knowledge files.

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
course generation. Write all instructional detail as Markdown in each section
record's `body` field, including explanatory prose, lists, tables, code blocks,
source paths, symbol references, and fenced Mermaid diagrams. Do not leave
lesson details only in titles, metadata, or the course index. Use any Mermaid
diagram type that improves understanding. Include sequence or flow diagrams for
important runtime behavior.

Write `course.json` at the root of `{{MODULE_COURSE_DIRECTORY}}` using this index
shape:
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
          "lesson_title": "Overview"
        }
      ]
    }
  ]
}

Write every indexed lesson to its concept directory beneath
`{{MODULE_COURSE_DIRECTORY}}`. Populate every JSONL record completely. Create
all required directories and files. When the complete course has been written,
return only a concise sentence confirming the course and its path. Do not return
the course contents in your final response.
```

## Exact Function Course Prompt

Function courses are generated on demand. The user supplies a symbol string;
ElectroBoy does not prevalidate or resolve it. The AI receives this prompt after
the shared instructions:

```text
Create a Function course for the user-requested symbol:
{{USER_SYMBOL_TEXT}}

Read the complete persisted component array from:
{{COMPONENTS_PATH}}

Read the complete persisted module array from:
{{MODULES_PATH}}

Write the complete Function course beneath this exact directory:
{{FUNCTION_COURSE_DIRECTORY}}

Use the accumulated raw AI knowledge as you see fit and inspect the code
directly. Locate the requested symbol as best you can. Write newly gathered
understanding to new UUID-suffixed files in the raw-knowledge directory as
required by the shared instructions. Explain any ambiguity naturally in the
lesson rather than asking ElectroBoy to validate or resolve the symbol.

Progress reporting for this turn is part of the task. Approximately every ten
seconds, emit one concise intermediate status sentence naming the requested
symbol, definition, caller, callee, branch, state change, call flow, lesson,
slide, Mermaid diagram, or new raw knowledge concept you are currently using or
creating. Send an update when you change focus. Never repeat a status sentence.
Never emit generic messages such as "still working", "processing", "creating
the function course", or an elapsed-time heartbeat. Do not write progress
messages into course or knowledge files.

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
Architecture course. Write all instructional detail as Markdown in each section
record's `body` field, including explanatory prose, lists, tables, code blocks,
source paths, symbol references, and fenced Mermaid diagrams. Do not leave
lesson details only in titles, metadata, or the course index.

Write `course.json` at the root of `{{FUNCTION_COURSE_DIRECTORY}}` using this
index shape:
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
          "lesson_title": "Overview"
        }
      ]
    }
  ]
}

Write every indexed lesson to its concept directory beneath
`{{FUNCTION_COURSE_DIRECTORY}}`. Populate every JSONL record completely. Create
all required directories and files. When the complete course has been written,
return only a concise sentence confirming the course and its path. Do not return
the course contents in your final response.
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

Each exact turn prompt contains a progress instruction limited to that turn's
actual work. The AI is instructed to report approximately every ten seconds.
When the AI runtime emits no status event, ElectroBoy leaves the latest useful
status in place rather than inventing an explanation.

## GUI Behavior

### Initialization

Before initialization, only Initialize is active. Architecture, Module, and
Function controls remain disabled.

Initialization progress shows:

1. Master course directory creation.
2. Component discovery and direct file writing.
3. Module discovery and direct file writing.
4. Architecture course generation and direct file writing.
5. Architecture activation.

When Architecture is persisted, initialization is complete and Architecture
becomes selectable. Background Module generation does not hold the progress bar
below 100 percent.

### Architecture

The Architecture menu opens the first concept, first lesson, and first section.
The outline lists concepts and lessons from the AI-written `course.json` index.
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

- `discovery.py`: component and module direct-writing AI turns
- `course_generation.py`: primary Architecture generation plus concurrent
  Module and Function course-worker orchestration
- `store.py`: repository-named master directory creation, status, progress, and
  access to the raw-knowledge directory and AI-written component, module, index,
  and lesson files
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

- [x] Record the current GUI, Abort, Continue, Replace, Clear Cache, tutor, and
      navigation behaviors that must remain.
- [x] Identify all Phase 3 imports and state-path dependencies in the controller,
      routes, workflow registration, frontend, and tests.
- [x] Confirm the new persistent layout has no phase-numbered names.
- [x] Confirm no implementation file or symbol is named with `phase4`.

Commit boundary: characterization tests and replacement boundary.

### 2. Add the Simple Store

- [x] Derive the repository name from the repository root directory's basename.
- [x] Create `.electroboy/code-learner/courses/<repository-name>/` before the
      first AI turn.
- [x] Create `<repository-name>/raw-ai-knowledge/` before the first AI turn.
- [x] Do not rewrite, slugify, or otherwise normalize the repository name used
      for the master directory.
- [x] Supply exact paths beneath the master directory to every AI turn.
- [x] Add responsibility-named accessors for AI-written `components.json`,
      `modules.json`, `course.json`, and lesson JSONL files.
- [x] Expose the absolute raw-knowledge path without parsing, indexing, or
      validating its contents.
- [x] Keep ElectroBoy-owned `status.json`, `progress.jsonl`, and
      `tutor-context.json` outside the repository-named course directory.
- [x] Add cache clearing for the replacement layout.
- [x] Add focused tests for repository-name derivation, directory creation,
      path handoff, file access, and cache clearing.

Commit boundary: repository-named course storage.

### 3. Implement AI Sessions and Shared Knowledge

- [x] Reuse one primary provider session across component discovery, module
      discovery, and Architecture generation.
- [x] Generate a fresh UUID for every discovery or course-generation AI
      invocation.
- [x] Pass the absolute `raw-ai-knowledge` path and invocation UUID through the
      exact shared AI instructions.
- [x] Instruct every invocation to read accumulated knowledge as it sees fit.
- [x] Instruct every invocation to create new knowledge files only and never
      modify, rename, replace, or delete existing knowledge.
- [x] Require every new knowledge filename to append the invocation UUID before
      its `.md` extension.
- [x] Do not validate knowledge filenames or contents.
- [x] Apply the exact shared AI instructions from this document.
- [x] Preserve Abort behavior for the active provider process.
- [x] Preserve Continue by reading already persisted turn outputs.
- [x] Add tests proving foreground turns receive the primary provider session
      ID and every invocation receives a distinct UUID and the same raw-knowledge
      path.

Commit boundary: AI sessions and append-only shared knowledge.

### 4. Implement Component Discovery

- [x] Use the exact Component Discovery prompt.
- [x] Give the AI the ElectroBoy-created master directory and exact
      `components.json` path.
- [x] Tell the AI to persist its detailed repository understanding as new
      UUID-suffixed Markdown files under `raw-ai-knowledge/` while it discovers
      components.
- [x] Explain that later Architecture, Module, and Function course sessions use
      this detailed raw knowledge to avoid rediscovering the repository.
- [x] Require the AI to assign `comp-001`, `comp-002`, and subsequent IDs in
      discovery order.
- [x] Require the AI to write the complete array directly to `components.json`.
- [x] Adopt the AI-written IDs and content without host-side rewriting.
- [x] Do not enumerate files, invoke Ctags, reconcile overlap, or investigate
      coverage.
- [x] Stream genuine nonrepeating AI progress.
- [x] Add focused tests for prompt content, exact output-path handoff, direct AI
      writing, and subsequent file visibility.

Commit boundary: trusted component discovery.

### 5. Implement Module Discovery

- [x] Resume the same AI session.
- [x] Give the AI the exact existing `components.json` path and exact
      `modules.json` output path.
- [x] Require the AI to read the complete component array from disk.
- [x] Tell the AI to read existing raw knowledge and append new UUID-suffixed
      Markdown files while it discovers modules and cross-module behavior.
- [x] Require component and module discovery to capture as much implementation
      detail as possible for later course authoring.
- [x] Require the AI to assign `mod-001`, `mod-002`, and subsequent IDs in
      discovery order.
- [x] Require the AI to write the complete array directly to `modules.json`.
- [x] Adopt the AI-written IDs and content without host-side rewriting.
- [x] Do not validate `ai_comp_list`.
- [x] Add focused tests for context reuse, prompt content, exact path handoff,
      direct AI writing, and subsequent file visibility.

Commit boundary: trusted module discovery.

### 6. Implement Architecture Generation

- [x] Resume the same AI session.
- [x] Give the AI the exact `components.json`, `modules.json`, raw-knowledge, and
      Architecture output-directory paths.
- [x] Require the AI to read both arrays from disk and write `course.json`,
      concept directories, and lesson JSONL files directly.
- [x] Tell the AI to read accumulated raw knowledge and append newly gathered
      knowledge using its invocation UUID.
- [x] Use accumulated knowledge and live discovery context as the primary course
      inputs; do not repeat a repository-wide source dive.
- [x] Permit only targeted source inspection for material knowledge gaps.
- [x] Require every section's instructional detail to be Markdown in its `body`
      field.
- [x] Do not generate Markdown companions.
- [x] Do not validate course content, diagrams, references, or IDs.
- [x] Activate Architecture when the Architecture turn reports completion.
- [x] Add a small-repository acceptance test requiring only three foreground AI
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
- [ ] Use a bounded worker pool to generate Module courses concurrently in
      independent AI sessions.
- [ ] Use the exact Module Course prompt.
- [ ] Give each turn the component and module input paths, selected module ID,
      raw-knowledge path, invocation UUID, and exact Module course output path.
- [ ] Tell every Module worker to read accumulated knowledge as it sees fit and
      add newly gathered knowledge only through new UUID-suffixed Markdown files.
- [ ] Require the AI to write each `course.json`, concept directory, and lesson
      JSONL file directly.
- [ ] Require every section's instructional detail to be Markdown in its `body`
      field.
- [ ] Expose pending, generating, and ready status in the Module selector.
- [ ] Ensure one Module failure does not disable Architecture or other modules.
- [ ] Add scheduler and GUI status tests.

Commit boundary: background Module courses.

### 9. Implement On-Demand Function Courses

- [ ] Accept the user's symbol text without host-side resolution.
- [ ] Use the exact Function Course prompt.
- [ ] Give the AI the component and module input paths and exact Function course
      output path, plus the raw-knowledge path and a fresh invocation UUID.
- [ ] Start Function generation in an independent AI session without waiting for
      a Module worker or the primary session.
- [ ] Tell the Function worker to read accumulated knowledge as it sees fit and
      add newly gathered knowledge only through new UUID-suffixed Markdown files.
- [ ] Require the AI to write `course.json`, concept directories, and lesson
      JSONL files directly.
- [ ] Require every section's instructional detail to be Markdown in its `body`
      field.
- [ ] Display the AI-written course directly.
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

- [ ] Keep progress instructions out of the shared prompt text.
- [ ] Add a ten-second progress instruction tailored to the work and vocabulary
      of each exact AI turn.
- [ ] Ensure discovery prompts do not request lesson, slide, or diagram progress.
- [ ] Ensure course prompts request only progress relevant to their selected
      Architecture, Module, or Function course.
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
- [ ] Populate Module choices from the repository master's `modules.json`.
- [ ] Activate Architecture after its direct-writing AI turn completes.
- [ ] Keep unavailable Module and Function content visibly pending rather than
      disabling the completed Architecture course.
- [ ] Remove phase-numbered API and payload concepts.

Commit boundary: simplified workflow cutover.

### 13. Remove Phase 3 and Validation Infrastructure

- [ ] Remove all Phase 3 Code Learner code and artifacts, including production
      modules, tests, schemas, imports, fallback or compatibility branches, and
      Phase 3 state-path handling.
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
- [ ] Confirm ElectroBoy creates
      `.electroboy/code-learner/courses/qhw-datastructures/` before invoking the
      AI.
- [ ] Confirm ElectroBoy creates `raw-ai-knowledge/` under that master directory.
- [ ] Confirm every discovery and course-generation invocation receives the same
      raw-knowledge path and a distinct invocation UUID.
- [ ] Confirm AI sessions add UUID-suffixed Markdown knowledge files without
      changing existing files.
- [ ] Confirm exactly three foreground AI turns produce visible Architecture.
- [ ] Confirm the AI writes component and module arrays with `comp-*` and
      `mod-*` IDs at the paths supplied by ElectroBoy.
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
2. ElectroBoy creates one master course directory named exactly after the
   repository root directory before starting the AI session.
3. ElectroBoy creates an append-only `raw-ai-knowledge/` directory beneath the
   master course directory.
4. Every discovery and course-generation invocation receives that directory and
   a unique invocation UUID, reads accumulated knowledge as it sees fit, and
   records new knowledge only in newly created UUID-suffixed Markdown files.
5. ElectroBoy never parses, validates, organizes, or displays raw AI knowledge.
6. Component and module discovery record enough detailed implementation
   knowledge for later course sessions to avoid another repository-wide dive.
7. The AI writes `components.json` with its component interpretations and
   `comp-*` IDs directly beneath that master directory.
8. The AI writes `modules.json` with its module interpretations and `mod-*` IDs
   directly beneath that master directory.
9. Architecture lessons are written only as JSONL, put all instructional detail
   as Markdown in section `body` fields, and display those sections directly as
   slides.
10. Architecture generation uses accumulated knowledge and live discovery
    context instead of repeating a repository-wide source inspection.
11. The first Architecture Overview includes an architecture diagram and a
   sequence diagram.
12. Module courses generate concurrently after Architecture is available.
13. Function courses accept manually entered symbols without host validation or
    waiting for another course-generation session.
14. ElectroBoy performs no semantic validation of AI component, module, course,
   diagram, path, relationship, or symbol content.
15. No semantic repair or verification AI passes remain.
16. No active implementation file, class, function, state path, or payload uses
    `phase3` or `phase4` naming.
17. Ctags and its supporting dependencies are absent when no other feature uses
    them.
18. Every AI turn receives a progress instruction tailored to that turn's work;
    progress contains only stage events and useful, nonrepeating AI status.
19. The GUI retains the existing ElectroBoy Code Learner visual language and
    workflows while using the simplified backend.
