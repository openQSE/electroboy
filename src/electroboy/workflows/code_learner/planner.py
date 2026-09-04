"""AI planner prompt and invocation for Code Learner initialization."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from pathlib import Path

from electroboy.adapters.base import AgentInvocation
from electroboy.runtime import runtime_for_role

from .domain import CodeLearnerError

CODE_LEARNER_INITIALIZE_ROLE = "code_learner_initialize"
ProgressCallback = Callable[[dict[str, object]], None]


def code_learner_initialize_prompt(
    root: Path | str,
    progress_path: str | None = None,
) -> str:
    repository_root = Path(root).expanduser().resolve()
    state_directory_rule = (
        "  site-packages, except for the progress file explicitly named below."
        if progress_path
        else "  site-packages."
    )
    progress_rules = ""
    if progress_path:
        progress_rules = f"""

Progress reporting:
- Append progress updates to this repository-relative JSONL file:
  {progress_path}
- The progress file is the only file you may create or modify while planning.
- Append one JSON object per line with this shape:
  {{"record_type":"progress","phase":"repository_survey","percent":5,"message":"Scanning project layout"}}
- Use integer percent values from 0 to 99 while work is in progress. Do not
  report 100 percent until the final course JSONL is ready.
- Emit progress at these approximate milestones when applicable:
  2 setup, 8 repository_survey, 15 source_map, 25 architecture,
  40 module_map, 55 module_lessons, 70 function_index,
  85 function_lessons, 94 validation, 98 final_output.
- Keep messages brief, factual, and user-safe for display.
- Do not include progress records in the final answer.
"""
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
{state_directory_rule}
- Prefer evidence from source files over guesses.
- Every important claim must include source references.
- If you are uncertain, emit a diagnostic record instead of inventing facts.
{progress_rules}

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


class _ProgressFileMonitor:
    """Poll a progress JSONL file while the planner subprocess is running."""

    def __init__(
        self,
        path: Path,
        callback: ProgressCallback | None,
        interval: float = 1.0,
    ) -> None:
        self.path = path
        self.callback = callback
        self.interval = interval
        self._offset = 0
        self._buffer = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.callback is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("", encoding="utf-8")
        self._thread = threading.Thread(
            target=self._run,
            name="code-learner-progress-monitor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if self.callback is None:
            return
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=max(0.2, self.interval * 2))
        self._read_available()

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            self._read_available()

    def _read_available(self) -> None:
        try:
            size = self.path.stat().st_size
        except OSError:
            return
        if size < self._offset:
            self._offset = 0
            self._buffer = ""
        try:
            with self.path.open("r", encoding="utf-8") as stream:
                stream.seek(self._offset)
                chunk = stream.read()
                self._offset = stream.tell()
        except OSError:
            return
        if not chunk:
            return
        self._buffer += chunk
        complete = self._buffer.endswith("\n")
        lines = self._buffer.split("\n")
        self._buffer = "" if complete else lines.pop()
        for line in lines:
            self._emit(line)

    def _emit(self, line: str) -> None:
        stripped = line.strip()
        if not stripped:
            return
        try:
            payload = json.loads(stripped)
        except json.JSONDecodeError:
            return
        if not isinstance(payload, dict):
            return
        record_type = str(payload.get("record_type") or payload.get("type") or "")
        if record_type != "progress":
            return
        if self.callback is None:
            return
        try:
            self.callback(dict(payload))
        except Exception:
            return


def generate_code_learner_course_corpus_jsonl(
    root: Path | str,
    *,
    progress_path: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> str:
    """Ask the configured AI runtime to generate the Code Learner corpus."""

    repository_root = Path(root).expanduser().resolve()
    progress_file = (
        _resolve_progress_path(repository_root, progress_path)
        if progress_path
        else None
    )
    monitor = (
        _ProgressFileMonitor(progress_file, progress_callback)
        if progress_file is not None
        else None
    )
    runtime = runtime_for_role(
        CODE_LEARNER_INITIALIZE_ROLE,
        repository_root,
        execution_root=repository_root,
    )
    if monitor is not None:
        monitor.start()
    try:
        result = runtime.invoke(
            AgentInvocation(
                role=CODE_LEARNER_INITIALIZE_ROLE,
                prompt=code_learner_initialize_prompt(
                    repository_root,
                    progress_path=progress_path,
                ),
                progress_path=progress_path,
            )
        )
    finally:
        if monitor is not None:
            monitor.stop()
    if not result.ok:
        raise CodeLearnerError(
            result.error or result.final_message or "AI course initialization failed"
        )
    output = result.final_message.strip()
    if not output:
        raise CodeLearnerError("AI course initialization returned no JSONL")
    return output


def _resolve_progress_path(root: Path, progress_path: str | None) -> Path:
    requested = Path(str(progress_path or ""))
    if requested.is_absolute():
        return requested
    return root / requested
