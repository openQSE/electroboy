"""Pass definitions and pass-specific quality gates for repository analysis."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .domain import CodeLearnerError


@dataclass(frozen=True)
class AnalysisPass:
    """One bounded repository-knowledge objective and output contract."""

    name: str
    percent: int
    objective: str
    output_expectation: str
    contract: str


INVENTORY_CONTRACT = """Inventory output contract:
- Emit exactly one knowledge_manifest and one repository entity.
- Store these arrays under knowledge_manifest.attributes.inventory:
  languages, excluded_regions, build_systems, dependency_manifests,
  produced_artifact_ids, entry_point_ids, public_surface_ids, process_ids,
  test_surface_ids, external_system_ids, and analysis_tools.
- An absent category is an empty array, never an omitted field.
- Each language item has name and evidence_paths.
- Each excluded_regions item has path, category, and a non-empty reason.
- Each analysis_tools item has name, available, applies_to, and limitation.
- IDs in the *_ids arrays resolve to entity records in this output.
- Use build-target, entry-point, process, test-surface, and external-system
  entities for discovered inventory surfaces. Public APIs, commands, routes,
  protocols, and other user-facing surfaces use entry-point entities tagged
  with their surface kind.
- Missing documentation is not fatal. Record a warning diagnostic and derive
  repository purpose from source/build evidence with appropriate confidence.
- Monorepo packages remain in repository scope and must not be mistaken for
  excluded third-party trees.
"""


ANALYSIS_PASSES = (
    AnalysisPass(
        "inventory",
        8,
        "Inventory repository identity, scope, languages, exclusions, build "
        "systems, artifacts, entry points, public surfaces, processes, tests, "
        "external systems, and available language-analysis tools.",
        "Emit the initial complete knowledge snapshot with one manifest and "
        "repository/inventory entities. Explicitly diagnose exclusions.",
        INVENTORY_CONTRACT,
    ),
    AnalysisPass(
        "modules",
        24,
        "Infer architectural modules and extension families from source, build "
        "configuration, registration, documentation, and tests. Enumerate every "
        "concrete implementation in each family.",
        "Emit only added or revised entities, relationships, diagnostics, and "
        "an updated manifest.",
        "Preserve the inventory and emit source-backed module boundaries.",
    ),
    AnalysisPass(
        "relationships",
        42,
        "Deeply map module ownership, dependencies, APIs, calls, construction, "
        "lifecycle, state, data, events, configuration, errors, concurrency, "
        "persistence, tests, deployment, and external communication.",
        "Emit only relationship/entity enrichments, diagnostics, and an updated "
        "manifest.",
        "Preserve existing entities and emit typed, source-backed graph edges.",
    ),
    AnalysisPass(
        "flows",
        58,
        "Identify and trace important ordered end-to-end runtime flows, branches, "
        "participants, dispatch boundaries, and failure paths.",
        "Emit runtime flows and only the supporting knowledge changes required.",
        "Every flow has ordered steps, participants, source evidence, and "
        "explicit alternate or unresolved behavior where applicable.",
    ),
    AnalysisPass(
        "symbols",
        74,
        "Build a broad language-appropriate symbol index with module ownership, "
        "locations, signatures, callers, callees, state access, side effects, "
        "tests, and limitations.",
        "Emit symbol entities and supporting relationships or diagnostics.",
        "Normalize tool output into language-independent symbol entities.",
    ),
    AnalysisPass(
        "validation",
        88,
        "Audit breadth and consistency. Find missing major modules, extension "
        "implementations, entry-point ownership, runtime flows, source evidence, "
        "and unresolved references.",
        "Emit corrections, explicit diagnostics, or targeted knowledge requests. "
        "Set the manifest status to validated only when coverage is sufficient.",
        "Do not call partial coverage complete; emit targeted requests for gaps.",
    ),
)


def validate_pass_output(
    analysis_pass: AnalysisPass,
    records: Iterable[Mapping[str, object]],
) -> None:
    """Apply deterministic quality gates specific to one analysis pass."""

    normalized = [dict(record) for record in records]
    if analysis_pass.name == "inventory":
        _validate_inventory(normalized)


def _validate_inventory(records: list[dict[str, object]]) -> None:
    manifests = [
        record
        for record in records
        if record.get("record_type") == "knowledge_manifest"
    ]
    repositories = [
        record
        for record in records
        if record.get("record_type") == "entity"
        and record.get("kind") == "repository"
    ]
    if len(manifests) != 1:
        raise CodeLearnerError("inventory pass requires exactly one manifest")
    if len(repositories) != 1:
        raise CodeLearnerError("inventory pass requires exactly one repository entity")

    attributes = manifests[0].get("attributes")
    inventory = attributes.get("inventory") if isinstance(attributes, dict) else None
    if not isinstance(inventory, dict):
        raise CodeLearnerError(
            "inventory manifest requires attributes.inventory"
        )
    required_arrays = (
        "languages",
        "excluded_regions",
        "build_systems",
        "dependency_manifests",
        "produced_artifact_ids",
        "entry_point_ids",
        "public_surface_ids",
        "process_ids",
        "test_surface_ids",
        "external_system_ids",
        "analysis_tools",
    )
    for field in required_arrays:
        if not isinstance(inventory.get(field), list):
            raise CodeLearnerError(
                f"inventory manifest requires array attributes.inventory.{field}"
            )

    entity_ids = {
        str(record.get("id"))
        for record in records
        if record.get("record_type") == "entity"
    }
    for field in (
        "produced_artifact_ids",
        "entry_point_ids",
        "public_surface_ids",
        "process_ids",
        "test_surface_ids",
        "external_system_ids",
    ):
        unknown = [item for item in inventory[field] if item not in entity_ids]
        if unknown:
            raise CodeLearnerError(
                f"inventory {field} contains unknown entity IDs: {', '.join(unknown)}"
            )

    for index, item in enumerate(inventory["languages"]):
        if not isinstance(item, dict) or not str(item.get("name") or "").strip():
            raise CodeLearnerError(f"inventory languages[{index}] requires name")
        evidence = item.get("evidence_paths")
        if not isinstance(evidence, list) or not evidence:
            raise CodeLearnerError(
                f"inventory languages[{index}] requires evidence_paths"
            )
    for index, item in enumerate(inventory["excluded_regions"]):
        if not isinstance(item, dict) or any(
            not str(item.get(field) or "").strip()
            for field in ("path", "category", "reason")
        ):
            raise CodeLearnerError(
                f"inventory excluded_regions[{index}] requires path, category, and reason"
            )
    for index, item in enumerate(inventory["analysis_tools"]):
        if not isinstance(item, dict):
            raise CodeLearnerError(f"inventory analysis_tools[{index}] must be an object")
        if not str(item.get("name") or "").strip():
            raise CodeLearnerError(f"inventory analysis_tools[{index}] requires name")
        if not isinstance(item.get("available"), bool):
            raise CodeLearnerError(
                f"inventory analysis_tools[{index}] requires boolean available"
            )
        if not isinstance(item.get("applies_to"), list):
            raise CodeLearnerError(
                f"inventory analysis_tools[{index}] requires applies_to"
            )
        if not str(item.get("limitation") or "").strip():
            raise CodeLearnerError(
                f"inventory analysis_tools[{index}] requires limitation"
            )
