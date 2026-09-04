"""AI planner prompt and invocation for Code Learner initialization."""

from __future__ import annotations

from pathlib import Path

from electroboy.adapters.base import AgentInvocation
from electroboy.runtime import runtime_for_role

from .domain import CodeLearnerError

CODE_LEARNER_INITIALIZE_ROLE = "code_learner_initialize"


def code_learner_initialize_prompt(root: Path | str) -> str:
    repository_root = Path(root).expanduser().resolve()
    return f"""You are the ElectroBoy Code Learner course planner.

Your task is to inspect this repository directly and generate structured
tutorial material for a learner. You are not being given a precomputed module
list because module boundaries must come from your understanding of the code.

Repository root:
{repository_root}

Operating rules:
- Read the codebase yourself.
- Use only read-only inspection commands.
- Do not modify files.
- Do not create commits.
- Do not run tests unless they are necessary for understanding and safe to run
  without modifying repository state.
- Ignore generated/cache/vendor/state directories such as .git, .electroboy,
  node_modules, dist, build, __pycache__, .pytest_cache, .venv, vendor, and
  site-packages.
- Prefer evidence from source files over guesses.
- Every important claim must include source references.
- If you are uncertain, emit a diagnostic record instead of inventing facts.

Output format:
- Return ONLY JSONL.
- Each line must be one valid JSON object.
- Use the field name "record_type" for the record discriminator.
- Do not wrap the output in Markdown.
- Do not include prose outside the JSONL.

Source reference shape:
{{
  "path": "repo-relative/path.ext",
  "start_line": 1,
  "end_line": 20,
  "symbol": "optional symbol name",
  "reason": "why this source supports the claim"
}}

Required record types:

1. course_manifest
One record describing the whole generated corpus.
Fields:
- record_type: "course_manifest"
- schema_version: 1
- repository_name
- repository_purpose
- primary_languages
- architecture_step_ids
- module_ids
- function_index_count
- confidence

2. architecture_step
Generate a slide-ready architecture course. Explain the repository as a
working system, not as a folder tour.
Fields:
- record_type: "architecture_step"
- id
- title
- summary
- body
- source_refs
- related_module_ids
- confidence

Architecture course should cover, where applicable:
- project goal and audience
- major runtime entry points
- public APIs and command surfaces
- main workflows
- service/controller/domain boundaries
- persistence/state model
- data flow
- extension/plugin boundaries
- frontend/backend interaction
- testing/build/deployment model
- important architectural tradeoffs

3. module
Infer conceptual modules from the codebase. A module may map to a folder,
package, workflow, service layer, frontend subsystem, or domain boundary. Do
not simply list directories.
Fields:
- record_type: "module"
- id
- name
- purpose
- responsibilities
- primary_files
- public_interfaces
- depends_on_module_ids
- used_by_module_ids
- source_refs
- confidence

4. module_step
For each important module, generate a module deep-dive course.
Fields:
- record_type: "module_step"
- module_id
- id
- title
- summary
- body
- source_refs
- related_function_symbols
- confidence

Each important module should usually have steps for:
- purpose and boundary
- main files, classes, or functions
- incoming API or caller surface
- outgoing dependencies
- important data structures
- common change path
- risks or confusing areas

5. function_index_entry
Build an AI-inferred index of important functions, classes, and methods for
Function mode. Do not document every trivial helper unless it is central to
understanding the system.
Fields:
- record_type: "function_index_entry"
- symbol
- display_name
- kind
- module_id
- path
- start_line
- end_line
- purpose
- why_important
- known_callers
- known_callees
- source_refs
- confidence

6. function_lesson
Generate full function lessons for the most important functions needed to
understand the system.
Fields:
- record_type: "function_lesson"
- symbol
- display_name
- title
- summary
- body
- call_flow
- inputs
- outputs
- side_effects
- error_paths
- source_refs
- related_symbols
- confidence

7. diagnostic
Use this for uncertainty, truncation, files skipped, ambiguous architecture, or
places where more inspection would be needed.
Fields:
- record_type: "diagnostic"
- severity: "info" | "warning" | "error"
- message
- source_refs

Quality bar:
- The course should teach how the codebase actually works.
- Avoid generic statements like "this file manages functionality."
- Prefer concrete relationships: "X calls Y", "route A invokes controller B",
  "state is persisted at C", "frontend action D calls endpoint E".
- Keep each body suitable for conversion into one slide plus speaker notes.
- Use stable IDs: lowercase, dot-separated, no spaces.
- Use repository-relative paths only.
""".strip()


def generate_code_learner_course_corpus_jsonl(root: Path | str) -> str:
    """Ask the configured AI runtime to generate the Code Learner corpus."""

    repository_root = Path(root).expanduser().resolve()
    runtime = runtime_for_role(
        CODE_LEARNER_INITIALIZE_ROLE,
        repository_root,
        execution_root=repository_root,
    )
    result = runtime.invoke(
        AgentInvocation(
            role=CODE_LEARNER_INITIALIZE_ROLE,
            prompt=code_learner_initialize_prompt(repository_root),
        )
    )
    if not result.ok:
        raise CodeLearnerError(
            result.error or result.final_message or "AI course initialization failed"
        )
    output = result.final_message.strip()
    if not output:
        raise CodeLearnerError("AI course initialization returned no JSONL")
    return output
