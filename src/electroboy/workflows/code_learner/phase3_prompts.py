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


def missing_file_investigation_prompt(
    root: Path | str,
    *,
    analysis_run_id: str,
    repository_revision: str,
    context_path: Path | str,
    unresolved_file_ids: Sequence[str],
) -> str:
    """Create the one allowed focused file-coverage investigation prompt."""

    repository = Path(root).expanduser().resolve()
    return f"""You are the ElectroBoy Phase 3 missing-file investigator.

{skill_prompt_reference("codebase-analysis")}

Repository root: {repository}
Analysis run ID: {analysis_run_id}
Repository revision: {repository_revision}
Authoritative investigation context: {context_path}
Unresolved file IDs: {json.dumps(list(unresolved_file_ids))}

Read the complete investigation context first. It references all source,
symbol, candidate, overlap, reconciliation, component, disposition, diagnostic,
attempt, and checkpoint evidence already collected. Use those artifacts as the
current working set; do not rediscover the repository from scratch after a new
session or context compaction. Inspect only source needed to resolve these files.

For each unresolved file, either amend or propose a source-grounded
component_candidate, emit one file_disposition of repository_infrastructure or
excluded with a concrete reason, or leave it unresolved with a reason. New and
amended candidates will pass normal validation, overlap, and reconciliation.

Return strict JSONL containing only component_candidate and file_disposition
records. Do not create catch-all miscellaneous or unclassified components just
to force full coverage. Do not emit modules, relationships, diagrams, courses,
or prose, and do not modify the repository or .electroboy state.
""".strip()


def module_synthesis_prompt(
    root: Path | str,
    *,
    analysis_run_id: str,
    repository_revision: str,
    source_manifest_path: Path | str,
    component_manifest_path: Path | str,
    components_path: Path | str,
    schema_path: Path | str,
    affected_component_ids: Sequence[str] = (),
    existing_modules_path: Path | str | None = None,
) -> str:
    """Build a bounded module-synthesis prompt over frozen components."""

    repository = Path(root).expanduser().resolve()
    scope = (
        json.dumps(list(affected_component_ids))
        if affected_component_ids
        else "all frozen components"
    )
    existing = str(existing_modules_path) if existing_modules_path else "none"
    return f"""You are the ElectroBoy Phase 3 module synthesis analyst.

{skill_prompt_reference("codebase-analysis")}

Repository root: {repository}
Analysis run ID: {analysis_run_id}
Repository revision: {repository_revision}
Source manifest: {source_manifest_path}
Frozen component manifest: {component_manifest_path}
Canonical components: {components_path}
Phase 3 output schema: {schema_path}
Affected component scope: {scope}
Existing accepted module draft: {existing}

Organize the frozen components into architecturally meaningful modules. Emit
module records with invocation-local IDs, name, kind, purpose, responsibility,
component IDs, grouping rationale, primary component IDs, entry component IDs
where applicable, confidence, and limitations. Optional parent module IDs may
form an acyclic hierarchy.

Every component must belong to at least one module or to an explicit module of
kind `intentionally_ungrouped`. Repeated component membership requires a
`repeated_component_rationales` entry in every affected module. Identify at
most one primary module per component through `primary_for_component_ids`.
Module source references may cite only files owned or supported by member
components.

Use only component IDs from the frozen manifest. If source reveals a missing
component, emit a separate open knowledge_request with request_type
`missing_component`, hard source references, and a reason. Do not create the
component inline. For a targeted retry, preserve unaffected accepted modules
and emit the complete resulting module set.

Return strict JSONL containing only module and knowledge_request records. Do
not alter components or emit relationships, flows, diagrams, course prose, or
repository changes.
""".strip()


def module_relationship_prompt(
    root: Path | str,
    *,
    analysis_run_id: str,
    repository_revision: str,
    scope_id: str,
    source_manifest_path: Path | str,
    component_manifest_path: Path | str,
    components_path: Path | str,
    module_manifest_path: Path | str,
    modules_path: Path | str,
    relationship_kinds: Sequence[str],
) -> str:
    """Create one independently retryable module-relationship scope prompt."""

    repository = Path(root).expanduser().resolve()
    return f"""You are the ElectroBoy Phase 3 module relationship analyst.

{skill_prompt_reference("codebase-analysis")}

Repository root: {repository}
Analysis run ID: {analysis_run_id}
Repository revision: {repository_revision}
Relationship scope module ID: {scope_id}
Source manifest: {source_manifest_path}
Frozen component manifest: {component_manifest_path}
Canonical components: {components_path}
Frozen module manifest: {module_manifest_path}
Canonical modules: {modules_path}
Allowed relationship kinds: {json.dumps(list(relationship_kinds))}

Analyze only relationships touching the scoped module. Relationship endpoints
must be frozen module IDs. Components and hard source references are supporting
evidence only; they are not relationship endpoints.

Each module_relationship requires invocation-local ID, from/to module IDs,
kind, summary, direction, condition (empty when unconditional), confidence,
supporting component IDs, source references, and limitations. Preserve dynamic,
conditional, inferred, and unresolved behavior explicitly. A self relationship
requires `self_relationship_reason`.

If evidence identifies an unknown endpoint, emit an open knowledge_request with
request_type `missing_endpoint` and hard source references instead of creating
a module or component. Return strict JSONL containing only
module_relationship and knowledge_request records. Do not reconcile components,
change manifests, or emit modules, flows, diagrams, courses, or prose.
""".strip()


def relationship_conflict_prompt(
    *,
    left: Mapping[str, object],
    right: Mapping[str, object],
) -> str:
    """Create a focused contradiction-only relationship repair prompt."""

    return f"""Resolve one contradictory Phase 3 module relationship pair.

Both records use the same frozen endpoints, kind, and condition:
{json.dumps([dict(left), dict(right)], indent=2, sort_keys=True)}

Read their cited source and return exactly one corrected module_relationship
JSON object using only the existing endpoint, component, and source IDs. Do not
create or reconcile components or modules and do not inspect unrelated scope.
""".strip()


def architecture_knowledge_prompt(
    root: Path | str,
    *,
    analysis_run_id: str,
    repository_revision: str,
    source_manifest_path: Path | str,
    component_manifest_path: Path | str,
    module_manifest_path: Path | str,
    relationships_path: Path | str,
    schema_path: Path | str,
) -> str:
    """Build the repository-wide Phase 3 Architecture knowledge prompt."""

    repository = Path(root).expanduser().resolve()
    return f"""You are the ElectroBoy Phase 3 Architecture knowledge analyst.

{skill_prompt_reference("codebase-analysis")}

Repository root: {repository}
Analysis run ID: {analysis_run_id}
Repository revision: {repository_revision}
Source manifest: {source_manifest_path}
Frozen component manifest: {component_manifest_path}
Frozen module manifest: {module_manifest_path}
Canonical module relationships: {relationships_path}
Phase 3 schema: {schema_path}

Generate exactly one architecture_knowledge record. This is structured
knowledge, not final course prose. Its horizontal object must cover repository
purpose, external boundaries, entry surfaces, every major module and accepted
relationship, state, build, tests, and constraints. Do not narrow scope to a
recent or prominent subsystem.

Add vertical_slices for important cross-module behaviors. Each slice needs
ordered_steps with canonical module and component IDs plus source-grounded
symbol locators where useful, and explicit alternate_flows, error_flows,
dynamic_behavior, and unresolved items. Add deep_links to Module and Function
targets.

Include a Mermaid component or flowchart diagram using only accepted module
and component node IDs and canonical relationship edge IDs. Include a Mermaid
sequence diagram whenever a vertical slice has an ordered cross-module flow.
Other evidence-grounded Mermaid diagram types are allowed. Every diagram must
list node_ids and relationship_ids separately so ElectroBoy can validate the
graph before rendering.

Return strict JSONL only. Preserve limitations and unsupported paths. Do not
create or modify source, components, modules, relationships, courses, or state.
""".strip()


def module_knowledge_prompt(
    root: Path | str,
    *,
    analysis_run_id: str,
    repository_revision: str,
    module_id: str,
    source_manifest_path: Path | str,
    component_manifest_path: Path | str,
    module_manifest_path: Path | str,
    relationships_path: Path | str,
    schema_path: Path | str,
) -> str:
    """Build one independent horizontal/vertical Module knowledge prompt."""

    repository = Path(root).expanduser().resolve()
    return f"""You are the ElectroBoy Phase 3 Module knowledge analyst.

{skill_prompt_reference("codebase-analysis")}

Repository root: {repository}
Analysis run ID: {analysis_run_id}
Repository revision: {repository_revision}
Module scope ID: {module_id}
Source manifest: {source_manifest_path}
Frozen component manifest: {component_manifest_path}
Frozen module manifest: {module_manifest_path}
Canonical module relationships: {relationships_path}
Phase 3 schema: {schema_path}

Generate exactly one module_knowledge record for the scoped frozen module.
Horizontal knowledge covers purpose, interfaces, canonical neighbor edges,
configuration, state, tests, risks, and peer-module navigation. Vertical
knowledge covers member components, initialization, normal and alternate flow,
errors, data, concurrency, and important exact symbol locators.

Keep horizontal peer navigation separate from vertical deep-dive links.
Preserve intentional component overlap, dynamic behavior, uncertainty, and
limitations. Select any Mermaid diagram types useful for this module and list
canonical node_ids and relationship_ids for validation. Use only frozen IDs.

Return strict JSONL only. Do not rebuild components, modules, relationships, or
other module scopes, and do not emit course prose or modify state.
""".strip()
