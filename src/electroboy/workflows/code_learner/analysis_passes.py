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


@dataclass(frozen=True)
class AnalysisScope:
    """A bounded entity scope within one analysis pass."""

    key: str
    entity_ids: tuple[str, ...] = ()


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

MODULE_CONTRACT = """Module discovery output contract:
- Preserve knowledge_manifest.attributes.inventory and add
  knowledge_manifest.attributes.module_catalog.
- module_catalog contains arrays major_module_ids, extension_family_ids,
  shared_infrastructure_module_ids, and an object coverage.
- coverage records candidate_count, module_count,
  implementation_candidate_count, implementation_module_count,
  excluded_count, and a non-empty evidence_paths_reviewed array.
- Every major module has source evidence and attributes containing
  boundary_evidence, interface_ids, initial_dependency_ids, and
  extension_family_id (empty when not part of a family).
- boundary_evidence names at least two independent signals when available,
  such as build ownership, imports/calls, runtime composition/registration,
  public interfaces, tests, or architecture documentation. If only one signal
  exists, preserve uncertainty in a diagnostic rather than inventing proof.
- Every extension-family entity has attributes containing contract_ids,
  registration_ids, implementation_module_ids, and excluded_implementations.
- Every concrete implementation with meaningful independent behavior is a
  module in implementation_module_ids and names its extension_family_id.
- Each excluded implementation has name, reason, and evidence_paths.
- Shared family infrastructure is separate from concrete implementation
  modules and appears in shared_infrastructure_module_ids when it is a major
  module.
- Discover families by contracts and runtime selection/dispatch patterns, not
  by a closed vocabulary of directory names. Consider plugins, providers,
  drivers, adapters, backends, handlers, transports, workflows, passes,
  strategies, and repository-specific equivalents only as search hypotheses.
- Inspect the full selected checkout. Recent commits and the active branch are
  evidence, never the repository scope.
"""

RELATIONSHIP_CONTRACT = """Relationship deep-dive output contract:
- Analyze only the supplied module scope and its direct neighbors. Do not
  repeat repository inventory or unrelated module discovery.
- For every scoped module, revise its attributes.relationship_analysis with
  incoming_relationship_ids, outgoing_relationship_ids, diagnostic_ids, and
  categories.
- categories has an explicit present, not-applicable, or unresolved value for
  each of: interfaces, construction, lifecycle, cleanup, state, persistence,
  events, messages, external_interactions, concurrency, asynchronous_behavior,
  configuration, errors, tests, and deployment.
- Emit typed relationships for verified or inferred edges. Use confidence and
  source references to distinguish those cases.
- Reconcile an apparent contradiction against existing records. Revise the
  stable record when evidence improves; otherwise emit a diagnostic naming
  both claims and the evidence still needed.
- Represent unresolved registration, reflection, callbacks, function
  pointers, generated dispatch, or external behavior as diagnostics rather
  than fabricated direct calls.
"""

FLOW_CONTRACT = """Runtime-flow output contract:
- Preserve the manifest and add knowledge_manifest.attributes.flow_catalog
  with flow_ids, major_entry_point_ids, covered_entry_point_ids, and
  uncovered_entry_points.
- Every uncovered entry-point item has id, reason, and diagnostic_id.
- Trace important end-to-end behavior across module, process, state, event,
  message, persistence, and external-system boundaries where present.
- Every runtime_flow has participants, contiguous ordered steps, source
  evidence, confidence, and attributes containing normal_path_summary,
  alternate_flows, error_flows, concurrency_notes, and unresolved_dispatch.
- alternate_flows and error_flows are arrays. Empty arrays explicitly mean no
  material branch was found in inspected evidence.
- Step endpoints and relationship IDs resolve. Dynamic dispatch limitations
  remain explicit and do not become invented direct edges.
"""

SYMBOL_CONTRACT = """Symbol indexing output contract:
- Read the normalized auxiliary symbol evidence when provided. Treat fallback
  text matches as candidates requiring source verification, not proven calls.
- Preserve the manifest and add knowledge_manifest.attributes.symbol_catalog
  with symbol_ids, adapter_capabilities, indexed_paths, and skipped_paths.
- Every symbol is an entity with parent_id set to its owning module and
  attributes containing qualified_name, symbol_kind, language,
  owning_module_id, implementation_refs, visibility, signature, caller_ids,
  callee_ids, input_types, output_types, side_effects, state_access_ids,
  test_ids, analysis_limitations, and call_edge_confidence.
- caller_ids and callee_ids contain stable symbol IDs only. Unresolved names,
  overload ambiguity, generated declarations, reflection, dynamic dispatch,
  callbacks, and function pointers belong in analysis_limitations and a
  diagnostic when they materially affect the index.
- call_edge_confidence maps related symbol IDs to verified, inferred, or
  unresolved. Emit calls relationships for resolved edges with matching
  confidence and source evidence.
- Index overloaded methods and same-name functions as distinct stable symbols
  based on qualified identity and source location.
- Do not require Vim, an editor plugin, Ctags, a language server, Tree-sitter,
  or a compiler index. Report each capability and continue with repository
  search when optional tools are absent.
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
        MODULE_CONTRACT,
    ),
    AnalysisPass(
        "relationships",
        42,
        "Deeply map module ownership, dependencies, APIs, calls, construction, "
        "lifecycle, state, data, events, configuration, errors, concurrency, "
        "persistence, tests, deployment, and external communication.",
        "Emit only relationship/entity enrichments, diagnostics, and an updated "
        "manifest.",
        RELATIONSHIP_CONTRACT,
    ),
    AnalysisPass(
        "flows",
        58,
        "Identify and trace important ordered end-to-end runtime flows, branches, "
        "participants, dispatch boundaries, and failure paths.",
        "Emit runtime flows and only the supporting knowledge changes required.",
        FLOW_CONTRACT,
    ),
    AnalysisPass(
        "symbols",
        74,
        "Build a broad language-appropriate symbol index with module ownership, "
        "locations, signatures, callers, callees, state access, side effects, "
        "tests, and limitations.",
        "Emit symbol entities and supporting relationships or diagnostics.",
        SYMBOL_CONTRACT,
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
    *,
    scope_ids: Iterable[str] = (),
) -> None:
    """Apply deterministic quality gates specific to one analysis pass."""

    normalized = [dict(record) for record in records]
    if analysis_pass.name == "inventory":
        _validate_inventory(normalized)
    elif analysis_pass.name == "modules":
        _validate_modules(normalized)
    elif analysis_pass.name == "relationships":
        _validate_relationships(normalized, tuple(scope_ids))
    elif analysis_pass.name == "flows":
        _validate_flows(normalized)
    elif analysis_pass.name == "symbols":
        _validate_symbols(normalized)


def analysis_scopes(
    analysis_pass: AnalysisPass,
    records: Iterable[Mapping[str, object]],
    *,
    batch_size: int = 4,
) -> tuple[AnalysisScope, ...]:
    """Derive deterministic bounded scopes for a pass from durable knowledge."""

    if analysis_pass.name != "relationships":
        return (AnalysisScope("all"),)
    normalized = [dict(record) for record in records]
    manifest = _single_manifest(normalized, "relationship")
    attributes = manifest.get("attributes")
    catalog = attributes.get("module_catalog") if isinstance(attributes, dict) else None
    module_ids = catalog.get("major_module_ids") if isinstance(catalog, dict) else None
    if not isinstance(module_ids, list):
        raise CodeLearnerError(
            "relationship analysis requires module_catalog.major_module_ids"
        )
    size = max(1, batch_size)
    return tuple(
        AnalysisScope(
            f"modules-{index // size + 1}",
            tuple(str(item) for item in module_ids[index : index + size]),
        )
        for index in range(0, len(module_ids), size)
    ) or (AnalysisScope("modules-empty"),)


def _validate_inventory(records: list[dict[str, object]]) -> None:
    manifests = [
        record
        for record in records
        if record.get("record_type") == "knowledge_manifest"
    ]
    repositories = [
        record
        for record in records
        if record.get("record_type") == "entity" and record.get("kind") == "repository"
    ]
    if len(manifests) != 1:
        raise CodeLearnerError("inventory pass requires exactly one manifest")
    if len(repositories) != 1:
        raise CodeLearnerError("inventory pass requires exactly one repository entity")

    attributes = manifests[0].get("attributes")
    inventory = attributes.get("inventory") if isinstance(attributes, dict) else None
    if not isinstance(inventory, dict):
        raise CodeLearnerError("inventory manifest requires attributes.inventory")
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
                f"inventory excluded_regions[{index}] requires path, category, "
                "and reason"
            )
    for index, item in enumerate(inventory["analysis_tools"]):
        if not isinstance(item, dict):
            raise CodeLearnerError(
                f"inventory analysis_tools[{index}] must be an object"
            )
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


def _validate_modules(records: list[dict[str, object]]) -> None:
    manifest = _single_manifest(records, "module")
    attributes = manifest.get("attributes")
    catalog = attributes.get("module_catalog") if isinstance(attributes, dict) else None
    if not isinstance(catalog, dict):
        raise CodeLearnerError("module manifest requires attributes.module_catalog")
    for field in (
        "major_module_ids",
        "extension_family_ids",
        "shared_infrastructure_module_ids",
    ):
        if not isinstance(catalog.get(field), list):
            raise CodeLearnerError(f"module catalog requires array {field}")

    coverage = catalog.get("coverage")
    if not isinstance(coverage, dict):
        raise CodeLearnerError("module catalog requires coverage")
    for field in (
        "candidate_count",
        "module_count",
        "implementation_candidate_count",
        "implementation_module_count",
        "excluded_count",
    ):
        value = coverage.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise CodeLearnerError(
                f"module catalog coverage requires nonnegative integer {field}"
            )
    reviewed = coverage.get("evidence_paths_reviewed")
    if not isinstance(reviewed, list) or not reviewed:
        raise CodeLearnerError(
            "module catalog coverage requires evidence_paths_reviewed"
        )

    entities = {
        str(record.get("id")): record
        for record in records
        if record.get("record_type") == "entity"
    }
    module_ids = {
        record_id
        for record_id, record in entities.items()
        if record.get("kind") == "module"
    }
    family_ids = {
        record_id
        for record_id, record in entities.items()
        if record.get("kind") == "extension-family"
    }
    _require_known_ids(catalog["major_module_ids"], module_ids, "major modules")
    _require_known_ids(
        catalog["shared_infrastructure_module_ids"],
        module_ids,
        "shared infrastructure modules",
    )
    _require_known_ids(
        catalog["extension_family_ids"], family_ids, "extension families"
    )
    if coverage["module_count"] != len(catalog["major_module_ids"]):
        raise CodeLearnerError(
            "module catalog coverage module_count does not match major_module_ids"
        )
    if coverage["candidate_count"] < coverage["module_count"]:
        raise CodeLearnerError(
            "module catalog candidate_count cannot be smaller than module_count"
        )

    for module_id in catalog["major_module_ids"]:
        module = entities[module_id]
        details = module.get("attributes")
        if not isinstance(details, dict):
            raise CodeLearnerError(f"major module {module_id} requires attributes")
        for field in (
            "boundary_evidence",
            "interface_ids",
            "initial_dependency_ids",
        ):
            if not isinstance(details.get(field), list):
                raise CodeLearnerError(f"major module {module_id} requires {field}")
        if not details["boundary_evidence"]:
            raise CodeLearnerError(
                f"major module {module_id} requires boundary evidence"
            )
        if "extension_family_id" not in details:
            raise CodeLearnerError(
                f"major module {module_id} requires extension_family_id"
            )
        family_id = details["extension_family_id"]
        if family_id and family_id not in family_ids:
            raise CodeLearnerError(
                f"major module {module_id} references unknown extension family"
            )
        _require_known_ids(
            details["interface_ids"], set(entities), f"{module_id} interfaces"
        )
        _require_known_ids(
            details["initial_dependency_ids"], module_ids, f"{module_id} dependencies"
        )

    excluded_count = 0
    implementation_count = 0
    for family_id in catalog["extension_family_ids"]:
        family = entities[family_id]
        details = family.get("attributes")
        if not isinstance(details, dict):
            raise CodeLearnerError(f"extension family {family_id} requires attributes")
        for field in (
            "contract_ids",
            "registration_ids",
            "implementation_module_ids",
            "excluded_implementations",
        ):
            if not isinstance(details.get(field), list):
                raise CodeLearnerError(f"extension family {family_id} requires {field}")
        _require_known_ids(
            details["contract_ids"], set(entities), f"{family_id} contracts"
        )
        _require_known_ids(
            details["registration_ids"], set(entities), f"{family_id} registration"
        )
        _require_known_ids(
            details["implementation_module_ids"],
            module_ids,
            f"{family_id} implementations",
        )
        for implementation_id in details["implementation_module_ids"]:
            implementation = entities[implementation_id]
            implementation_attributes = implementation.get("attributes")
            if not isinstance(implementation_attributes, dict) or (
                implementation_attributes.get("extension_family_id") != family_id
            ):
                raise CodeLearnerError(
                    f"implementation module {implementation_id} must name {family_id}"
                )
        implementation_count += len(details["implementation_module_ids"])
        for index, exclusion in enumerate(details["excluded_implementations"]):
            if not isinstance(exclusion, dict) or any(
                not exclusion.get(field)
                for field in ("name", "reason", "evidence_paths")
            ):
                raise CodeLearnerError(
                    f"extension family {family_id} exclusion {index} requires "
                    "name, reason, and evidence_paths"
                )
        excluded_count += len(details["excluded_implementations"])
    for module_id in catalog["major_module_ids"]:
        module_attributes = entities[module_id]["attributes"]
        family_id = module_attributes["extension_family_id"]
        if not family_id:
            continue
        family_attributes = entities[family_id]["attributes"]
        if module_id not in family_attributes["implementation_module_ids"]:
            raise CodeLearnerError(
                f"implementation module {module_id} must name {family_id}"
            )
    if coverage["excluded_count"] != excluded_count:
        raise CodeLearnerError(
            "module catalog coverage excluded_count does not match family exclusions"
        )
    if coverage["implementation_module_count"] != implementation_count:
        raise CodeLearnerError(
            "module catalog coverage implementation_module_count does not match "
            "family implementations"
        )
    if (
        coverage["implementation_candidate_count"]
        != implementation_count + excluded_count
    ):
        raise CodeLearnerError(
            "module catalog implementation candidates must all be modules or exclusions"
        )


def _validate_relationships(
    records: list[dict[str, object]], scope_ids: tuple[str, ...]
) -> None:
    entities = {
        str(record.get("id")): record
        for record in records
        if record.get("record_type") == "entity"
    }
    relationships = {
        str(record.get("id")): record
        for record in records
        if record.get("record_type") == "relationship"
    }
    diagnostics = {
        str(record.get("id"))
        for record in records
        if record.get("record_type") == "diagnostic"
    }
    required_categories = {
        "interfaces",
        "construction",
        "lifecycle",
        "cleanup",
        "state",
        "persistence",
        "events",
        "messages",
        "external_interactions",
        "concurrency",
        "asynchronous_behavior",
        "configuration",
        "errors",
        "tests",
        "deployment",
    }
    allowed_statuses = {"present", "not-applicable", "unresolved"}
    for module_id in scope_ids:
        module = entities.get(module_id)
        if not module or module.get("kind") != "module":
            raise CodeLearnerError(
                f"relationship scope contains unknown module: {module_id}"
            )
        attributes = module.get("attributes")
        analysis = (
            attributes.get("relationship_analysis")
            if isinstance(attributes, dict)
            else None
        )
        if not isinstance(analysis, dict):
            raise CodeLearnerError(
                f"scoped module {module_id} requires relationship_analysis"
            )
        for field in (
            "incoming_relationship_ids",
            "outgoing_relationship_ids",
            "diagnostic_ids",
        ):
            if not isinstance(analysis.get(field), list):
                raise CodeLearnerError(f"scoped module {module_id} requires {field}")
        _require_known_ids(
            analysis["incoming_relationship_ids"],
            set(relationships),
            f"{module_id} incoming relationships",
        )
        _require_known_ids(
            analysis["outgoing_relationship_ids"],
            set(relationships),
            f"{module_id} outgoing relationships",
        )
        _require_known_ids(
            analysis["diagnostic_ids"], diagnostics, f"{module_id} diagnostics"
        )
        categories = analysis.get("categories")
        if not isinstance(categories, dict) or set(categories) != required_categories:
            raise CodeLearnerError(
                f"scoped module {module_id} requires all relationship categories"
            )
        if any(value not in allowed_statuses for value in categories.values()):
            raise CodeLearnerError(
                f"scoped module {module_id} has invalid relationship category status"
            )
        unresolved = any(value == "unresolved" for value in categories.values())
        if unresolved and not analysis["diagnostic_ids"]:
            raise CodeLearnerError(
                f"scoped module {module_id} requires diagnostics for "
                "unresolved categories"
            )


def _validate_flows(records: list[dict[str, object]]) -> None:
    manifest = _single_manifest(records, "flow")
    attributes = manifest.get("attributes")
    catalog = attributes.get("flow_catalog") if isinstance(attributes, dict) else None
    if not isinstance(catalog, dict):
        raise CodeLearnerError("flow manifest requires attributes.flow_catalog")
    for field in (
        "flow_ids",
        "major_entry_point_ids",
        "covered_entry_point_ids",
        "uncovered_entry_points",
    ):
        if not isinstance(catalog.get(field), list):
            raise CodeLearnerError(f"flow catalog requires array {field}")
    entities = {
        str(record.get("id")): record
        for record in records
        if record.get("record_type") == "entity"
    }
    flows = {
        str(record.get("id")): record
        for record in records
        if record.get("record_type") == "runtime_flow"
    }
    diagnostics = {
        str(record.get("id"))
        for record in records
        if record.get("record_type") == "diagnostic"
    }
    entry_points = {
        record_id
        for record_id, record in entities.items()
        if record.get("kind") == "entry-point"
    }
    _require_known_ids(catalog["flow_ids"], set(flows), "flow catalog")
    _require_known_ids(
        catalog["major_entry_point_ids"], entry_points, "major entry points"
    )
    _require_known_ids(
        catalog["covered_entry_point_ids"], entry_points, "covered entry points"
    )
    uncovered_ids: set[str] = set()
    for index, item in enumerate(catalog["uncovered_entry_points"]):
        if not isinstance(item, dict) or any(
            not str(item.get(field) or "").strip()
            for field in ("id", "reason", "diagnostic_id")
        ):
            raise CodeLearnerError(
                f"uncovered entry point {index} requires id, reason, and diagnostic_id"
            )
        entry_id = str(item["id"])
        if entry_id not in entry_points:
            raise CodeLearnerError(f"uncovered entry point is unknown: {entry_id}")
        if item["diagnostic_id"] not in diagnostics:
            raise CodeLearnerError(
                f"uncovered entry point {entry_id} requires a known diagnostic"
            )
        uncovered_ids.add(entry_id)
    expected = set(catalog["major_entry_point_ids"])
    actual = set(catalog["covered_entry_point_ids"]) | uncovered_ids
    if actual != expected:
        raise CodeLearnerError(
            "every major entry point must be covered or explicitly unresolved"
        )
    participants = {
        str(participant)
        for flow_id in catalog["flow_ids"]
        for participant in flows[flow_id].get("participant_ids", [])
    }
    missing_coverage = set(catalog["covered_entry_point_ids"]) - participants
    if missing_coverage:
        raise CodeLearnerError(
            "covered entry points must participate in a cataloged runtime flow: "
            + ", ".join(sorted(missing_coverage))
        )
    for flow_id in catalog["flow_ids"]:
        flow = flows[flow_id]
        details = flow.get("attributes")
        if not isinstance(details, dict):
            raise CodeLearnerError(f"runtime flow {flow_id} requires attributes")
        if not str(details.get("normal_path_summary") or "").strip():
            raise CodeLearnerError(
                f"runtime flow {flow_id} requires normal_path_summary"
            )
        for field in ("alternate_flows", "error_flows", "unresolved_dispatch"):
            if not isinstance(details.get(field), list):
                raise CodeLearnerError(f"runtime flow {flow_id} requires {field}")
        if not isinstance(details.get("concurrency_notes"), str):
            raise CodeLearnerError(f"runtime flow {flow_id} requires concurrency_notes")
        steps = flow.get("steps")
        if not isinstance(steps, list):
            raise CodeLearnerError(f"runtime flow {flow_id} requires steps")
        orders = [step.get("order") for step in steps if isinstance(step, dict)]
        if orders != list(range(1, len(steps) + 1)):
            raise CodeLearnerError(
                f"runtime flow {flow_id} steps must have contiguous order"
            )


def _validate_symbols(records: list[dict[str, object]]) -> None:
    manifest = _single_manifest(records, "symbol")
    manifest_attributes = manifest.get("attributes")
    catalog = (
        manifest_attributes.get("symbol_catalog")
        if isinstance(manifest_attributes, dict)
        else None
    )
    if not isinstance(catalog, dict):
        raise CodeLearnerError("symbol manifest requires attributes.symbol_catalog")
    for field in (
        "symbol_ids",
        "adapter_capabilities",
        "indexed_paths",
        "skipped_paths",
    ):
        if not isinstance(catalog.get(field), list):
            raise CodeLearnerError(f"symbol catalog requires array {field}")
    entities = {
        str(record.get("id")): record
        for record in records
        if record.get("record_type") == "entity"
    }
    symbol_ids = {
        record_id
        for record_id, record in entities.items()
        if record.get("kind") == "symbol"
    }
    _require_known_ids(catalog["symbol_ids"], symbol_ids, "symbol catalog")
    required_fields = (
        "qualified_name",
        "symbol_kind",
        "language",
        "owning_module_id",
        "implementation_refs",
        "visibility",
        "signature",
        "caller_ids",
        "callee_ids",
        "input_types",
        "output_types",
        "side_effects",
        "state_access_ids",
        "test_ids",
        "analysis_limitations",
        "call_edge_confidence",
    )
    for symbol_id in catalog["symbol_ids"]:
        symbol = entities[symbol_id]
        attributes = symbol.get("attributes")
        if not isinstance(attributes, dict):
            raise CodeLearnerError(f"symbol {symbol_id} requires attributes")
        missing = [field for field in required_fields if field not in attributes]
        if missing:
            raise CodeLearnerError(
                f"symbol {symbol_id} requires fields: {', '.join(missing)}"
            )
        owner = attributes["owning_module_id"]
        if owner not in entities or entities[owner].get("kind") != "module":
            raise CodeLearnerError(f"symbol {symbol_id} has unknown owning module")
        if symbol.get("parent_id") != owner:
            raise CodeLearnerError(
                f"symbol {symbol_id} parent_id must match owning_module_id"
            )
        for field in (
            "implementation_refs",
            "caller_ids",
            "callee_ids",
            "input_types",
            "output_types",
            "side_effects",
            "state_access_ids",
            "test_ids",
            "analysis_limitations",
        ):
            if not isinstance(attributes[field], list):
                raise CodeLearnerError(f"symbol {symbol_id} requires array {field}")
        _require_known_ids(attributes["caller_ids"], symbol_ids, f"{symbol_id} callers")
        _require_known_ids(attributes["callee_ids"], symbol_ids, f"{symbol_id} callees")
        if not isinstance(attributes["call_edge_confidence"], dict) or any(
            value not in {"verified", "inferred", "unresolved"}
            for value in attributes["call_edge_confidence"].values()
        ):
            raise CodeLearnerError(
                f"symbol {symbol_id} has invalid call_edge_confidence"
            )


def _single_manifest(
    records: list[dict[str, object]], pass_name: str
) -> dict[str, object]:
    manifests = [
        record
        for record in records
        if record.get("record_type") == "knowledge_manifest"
    ]
    if len(manifests) != 1:
        raise CodeLearnerError(f"{pass_name} pass requires exactly one manifest")
    return manifests[0]


def _require_known_ids(values: object, known: set[str], label: str) -> None:
    if not isinstance(values, list):
        raise CodeLearnerError(f"{label} must be an array")
    unknown = [str(value) for value in values if value not in known]
    if unknown:
        raise CodeLearnerError(f"{label} contain unknown IDs: {', '.join(unknown)}")
