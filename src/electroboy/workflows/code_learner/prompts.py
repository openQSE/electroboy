"""Direct-write prompts for trusted Code Learner generation."""

from __future__ import annotations

from pathlib import Path


def shared_instructions(raw_knowledge: Path, invocation_id: str) -> str:
    return f"""
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
{raw_knowledge}

Your unique invocation UUID is:
{invocation_id}

Read and use the accumulated knowledge as you see fit. As you inspect the
repository and develop additional understanding, record useful new knowledge
in one or more Markdown files in that directory. You decide the concepts,
organization, number of files, and descriptive filename prefixes.

The knowledge directory is append-only and may be shared with concurrent AI
sessions. Never edit, rename, replace, or delete an existing knowledge file.
Create new files only. Every new knowledge filename must append your exact
invocation UUID immediately before the `.md` extension, for example
`request-flow-{invocation_id}.md`. If you create multiple files, give each one a
distinct descriptive prefix and the same UUID suffix.

Do not modify repository source files. Write only the Code Learner output files
requested by the turn. After the files are complete, return one concise sentence
identifying the completed artifact and its path. Do not repeat file contents in
your final response.
""".strip()


def component_discovery_prompt(
    root: Path,
    course_root: Path,
    raw_knowledge: Path,
    components_path: Path,
    invocation_id: str,
) -> str:
    task = f"""
Repository root:
{root}

ElectroBoy-created master course directory:
{course_root}

Write the component array directly to this exact path:
{components_path}

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
primary concepts into multiple files when useful.

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

Write one complete JSON array to {components_path}. Do not wrap the array in
another object. Every array element must have exactly this shape:

{{
  "eb_comp_id": "comp-001",
  "ai_component_name": "AI-assigned component name",
  "ai_file_list": ["repository/path/to/file"]
}}

The master course directory already exists. Do not rename or replace it. Do not
return the JSON array in your final response.
""".strip()
    return f"{shared_instructions(raw_knowledge, invocation_id)}\n\n{task}"


def module_discovery_prompt(
    components_path: Path,
    modules_path: Path,
    raw_knowledge: Path,
    invocation_id: str,
) -> str:
    task = f"""
You previously inspected this repository and wrote its implementation
components to:
{components_path}

Read that complete component array before beginning this turn.

Write the module array directly to this exact path:
{modules_path}

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
will be the primary input used by Architecture, Module, and Function course
sessions, so later course authors should not need to repeat the repository-wide
code dive.

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

Write one complete JSON array to {modules_path}. Do not wrap the array in
another object. Every array element must have exactly this shape:

{{
  "eb_module_id": "mod-001",
  "ai_module_name": "AI-assigned module name",
  "ai_comp_list": ["comp-001"]
}}

Use the `eb_comp_id` values in the component file in `ai_comp_list`. Do not
repeat component objects or return the JSON array in your final response.
""".strip()
    return f"{shared_instructions(raw_knowledge, invocation_id)}\n\n{task}"


_LESSON_FORMAT = """
Create each lesson as a JSONL file. Its first line must be a document record:
{
  "schema_version": 1,
  "artifact_type": "course",
  "record_type": "document",
  "id": "unique lesson id",
  "order": 0,
  "title": "Lesson title",
  "status": "draft"
}

Every remaining line is one GUI slide and must be a section record:
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
""".strip()


def architecture_course_prompt(
    components_path: Path,
    modules_path: Path,
    raw_knowledge: Path,
    output_root: Path,
    invocation_id: str,
) -> str:
    task = f"""
You have already inspected this repository, identified its components, and
organized those components into modules.

Read the complete persisted component array from:
{components_path}

Read the complete persisted module array from:
{modules_path}

The accumulated raw AI knowledge directory is:
{raw_knowledge}

Write the complete Architecture course beneath this exact directory:
{output_root}

Before authoring the course, read and use the accumulated raw AI knowledge as
the primary source for the repository understanding gathered during component
and module discovery. Reuse the live context from those turns. Do not repeat a
repository-wide code dive. Inspect targeted source files only when accumulated
knowledge has a material gap that prevents a clear or accurate lesson.

Progress reporting for this turn is part of the task. Approximately every ten
seconds, emit one concise intermediate status sentence naming the raw knowledge
concept, architectural concept, lesson, slide, or Mermaid diagram you are
currently using or creating. Send an update when you change focus. Never repeat
a status sentence. Never emit generic messages or elapsed-time heartbeats. Do
not write progress messages into course or knowledge files.

Organize the course around the primary architectural concepts needed to
understand the system. Give every concept one or more lessons. Number concept
directory names in course order. Every concept's first lesson must be named
`01.Overview.jsonl`; number later lessons in order.

{_LESSON_FORMAT}

Start every lesson with a broad Overview slide, then add progressively more
detailed slides and vertical deep dives. Ground the course in the implementation
knowledge already collected. Include concrete file paths, important symbols,
control and data flow, state changes, extension points, failure paths, tests,
and operational constraints wherever they improve the lesson.

Use fenced Mermaid diagrams in `body` fields whenever they increase clarity.
The first lesson of the first concept must include an architectural component or
flowchart diagram showing primary modules and their interactions, plus at least
one sequence diagram showing an important end-to-end runtime flow. Any Mermaid
diagram type may be used when useful.

Write `course.json` at {output_root / 'course.json'} with this shape:
{{
  "course_type": "architecture",
  "course_title": "Repository Architecture",
  "concepts": [{{
    "directory_name": "01.Concept-Name",
    "concept_title": "Concept Name",
    "lessons": [{{
      "file_name": "01.Overview.jsonl",
      "lesson_title": "Overview"
    }}]
  }}]
}}

Write every indexed lesson beneath {output_root}. Create all required
directories and files. Do not return course contents in your final response.
""".strip()
    return f"{shared_instructions(raw_knowledge, invocation_id)}\n\n{task}"


def module_course_prompt(
    module_id: str,
    components_path: Path,
    modules_path: Path,
    raw_knowledge: Path,
    output_root: Path,
    invocation_id: str,
) -> str:
    task = f"""
Create the complete Module course for this module ID:
{module_id}

Read components from {components_path} and modules from {modules_path}. Find
`{module_id}` in the module file. Write the complete course beneath:
{output_root}

Use accumulated raw AI knowledge as you see fit. Inspect only source needed to
explain this module accurately, and write newly gathered understanding to new
UUID-suffixed knowledge files.

Progress reporting for this turn is part of the task. Approximately every ten
seconds, emit one concise status naming the selected module, relevant component,
source area, runtime flow, lesson, slide, Mermaid diagram, or new knowledge
concept currently being used or created. Never repeat a status, emit a generic
working message or heartbeat, or write progress into output files.

Teach the module horizontally and vertically: purpose, boundaries, contained
components, public entry points, internal collaboration, data and control flow,
state, extension points, dependencies, error behavior, tests, and important
implementation details. Show its place in the larger architecture without
regenerating the Architecture course.

Organize the course into concepts. Every concept starts with
`01.Overview.jsonl`; each lesson starts with a broad Overview section and then
progresses into detailed section records. Each section is one GUI slide.

{_LESSON_FORMAT}

Use any useful Mermaid diagram type and include sequence or flow diagrams for
important runtime behavior. Write `course.json` at {output_root / 'course.json'}
with `course_type` `module`, a course title, `module_id` `{module_id}`, and the
same concept/lesson index shape as the Architecture course. Write every indexed
lesson beneath {output_root}. Do not return course contents in your final
response.
""".strip()
    return f"{shared_instructions(raw_knowledge, invocation_id)}\n\n{task}"


def function_course_prompt(
    symbol: str,
    components_path: Path,
    modules_path: Path,
    raw_knowledge: Path,
    output_root: Path,
    invocation_id: str,
) -> str:
    task = f"""
Create a Function course for the user-requested symbol:
{symbol}

Read components from {components_path} and modules from {modules_path}. Write
the complete Function course beneath:
{output_root}

Use accumulated raw AI knowledge as you see fit and inspect the code directly.
Locate the requested symbol as best you can. Explain ambiguity naturally in the
lesson rather than asking ElectroBoy to validate or resolve it. Write newly
gathered understanding to new UUID-suffixed knowledge files.

Progress reporting for this turn is part of the task. Approximately every ten
seconds, emit one concise status naming the requested symbol, definition,
caller, callee, branch, state change, call flow, lesson, slide, Mermaid diagram,
or new knowledge concept currently being used or created. Never repeat a status,
emit a generic working message or heartbeat, or write progress into output files.

Teach the function's purpose, location, inputs, outputs, callers, callees,
control flow, data flow, state changes, side effects, error paths, important
branches, and role in its component, module, and overall architecture. Include a
Mermaid call graph and a Mermaid sequence or flow diagram when they clarify
execution.

Organize the course into one or more concepts. Every concept starts with
`01.Overview.jsonl`; each lesson starts with a broad Overview section and then
progresses into detailed section records. Each section is one GUI slide.

{_LESSON_FORMAT}

Write `course.json` at {output_root / 'course.json'} with `course_type`
`function`, a course title, `requested_symbol` `{symbol}`, and the same
concept/lesson index shape as the Architecture course. Write every indexed
lesson beneath {output_root}. Do not return course contents in your final
response.
""".strip()
    return f"{shared_instructions(raw_knowledge, invocation_id)}\n\n{task}"
