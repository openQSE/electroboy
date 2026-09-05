"""Bounded, file-backed prompts for Phase 3 analysis roles."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
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


def component_reconciliation_prompt(
    root: Path | str,
    *,
    analysis_run_id: str,
    group: Mapping[str, object],
    candidates: Sequence[Mapping[str, object]],
    source_manifest_path: Path | str,
    files_path: Path | str,
    schema_path: Path | str,
) -> str:
    """Create one complete, source-grounded overlap reconciliation prompt."""

    repository = Path(root).expanduser().resolve()
    payload = {
        "overlap_group": dict(group),
        "candidates": [dict(candidate) for candidate in candidates],
    }
    return f"""You are the ElectroBoy Phase 3 component reconciliation analyst.

{skill_prompt_reference("codebase-analysis")}

Repository root: {repository}
Analysis run ID: {analysis_run_id}
Repository revision: {group.get("repository_revision", "")}
Source manifest: {source_manifest_path}
Complete file records: {files_path}
Phase 3 output schema: {schema_path}

Reconcile exactly this complete overlap group:
{json.dumps(payload, indent=2, sort_keys=True)}

Read the referenced source before deciding. Shared and candidate-exclusive
canonical symbol sets are authoritative reconciliation anchors. Candidate
names, responsibilities, member files, owned references, supporting references,
and limitations are evidence, not overlap triggers.

Output contract:
- Return exactly one component_reconciliation JSON object and no other text.
- Use decision `same` only when every candidate is one component and emit one
  partition.
- Otherwise use decision `distinct`; each partition is one same-component set
  and separate partitions are distinct.
- Include every input candidate exactly once. Do not introduce external
  candidate IDs, file IDs, symbol keys, or source references.
- A partition may clarify name, aliases, kind, responsibility, membership,
  references, reason, and limitations using only supplied evidence.
- Explain the decision and preserve unresolved differences.

Forbidden output:
- relationships, hierarchy, ownership edges, call edges, module membership,
  runtime flows, diagrams, courses, unrelated discovery, or repository edits.
- Markdown fences or explanatory prose outside the JSON object.
""".strip()
