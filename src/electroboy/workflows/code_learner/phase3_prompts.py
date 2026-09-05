"""Bounded, file-backed prompts for Phase 3 analysis roles."""

from __future__ import annotations

from pathlib import Path

from .skills import skill_prompt_reference


def component_discovery_prompt(
    root: Path | str,
    *,
    analysis_run_id: str,
    repository_revision: str,
    source_manifest_path: Path | str,
    files_path: Path | str,
    ctags_path: Path | str,
    schema_path: Path | str,
    prior_artifact_paths: tuple[Path | str, ...] = (),
) -> str:
    """Create the complete Phase 3 component-candidate invocation."""

    repository = Path(root).expanduser().resolve()
    prior = "\n".join(f"- {Path(path)}" for path in prior_artifact_paths) or "- none"
    return f"""You are the ElectroBoy Phase 3 component discovery analyst.

{skill_prompt_reference("codebase-analysis")}

Repository root: {repository}
Analysis run ID: {analysis_run_id}
Repository revision: {repository_revision}

Read these authoritative inputs before inspecting source:
- Source manifest: {source_manifest_path}
- Complete file records: {files_path}
- Raw Universal Ctags JSONL: {ctags_path}
- Phase 3 output schema: {schema_path}

Prior validated artifacts, if any:
{prior}

Objective:
- Inspect the complete selected file manifest.
- Return architecturally meaningful component candidates grounded in actual
  file IDs and source-oriented symbol locators.
- Use source-defined names when available and record whether each name is
  source-defined or inferred.
- Distinguish owned implementation references from supporting references.
- Discover extension implementations generically without assuming a specific
  language, framework, directory layout, or closed vocabulary.

Granularity:
- A component may be one important function, related functions, a type and its
  operations, one file, several files, or a registered implementation.
- Do not emit one component per symbol without architectural reason.
- Do not emit a repository-wide or miscellaneous component that erases useful
  boundaries or merely consumes unassigned files.

Output contract:
- Return strict JSONL only, with one object per line.
- Emit only component_candidate records from the supplied schema.
- Candidate IDs are temporary and unique within this invocation.
- Use the exact analysis run ID and repository revision above.
- Every candidate must include at least one real file ID.
- Include precise symbol locators whenever the component is narrower than a
  whole file.
- Report limitations on the candidate; do not emit separate modules,
  relationships, diagrams, courses, or lesson prose.

Runtime rules:
- Read the repository and supplied artifacts only.
- Do not modify repository files or any .electroboy state.
- Do not build, compile, link, test, or execute the learned repository.
- The active branch diff is evidence, not the analysis scope.
- Do not wrap JSONL in Markdown or add explanatory text.
""".strip()
