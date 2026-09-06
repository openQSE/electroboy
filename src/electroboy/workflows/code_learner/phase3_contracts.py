"""Phase 3 domain contracts independent from storage, runtime, and UI."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .component_contract import (
    COMPONENT_CONFIDENCE_VALUES,
    COMPONENT_NAME_ORIGIN_VALUES,
    validate_component_schema_alignment,
)
from .domain import CodeLearnerError
from .phase3_contract_catalog import (
    ARCHITECTURE_KNOWLEDGE_REQUIRED_FIELDS,
    FUNCTION_KNOWLEDGE_REQUIRED_FIELDS,
    KNOWLEDGE_REQUEST_REQUIRED_FIELDS,
    KNOWLEDGE_REQUEST_STATUS_VALUES,
    KNOWLEDGE_REQUEST_TYPE_VALUES,
    MODULE_KNOWLEDGE_REQUIRED_FIELDS,
    MODULE_RELATIONSHIP_REQUIRED_FIELDS,
    MODULE_REQUIRED_FIELDS,
    RECONCILIATION_PARTITION_REQUIRED_FIELDS,
    RECONCILIATION_REQUIRED_FIELDS,
    validate_phase3_schema_alignment,
)

PHASE3_SCHEMA_VERSION = 1
PHASE3_GENERATION = "phase3"
COMPLETION_STATES = frozenset(
    {"pending", "running", "complete", "complete_with_warnings", "failed"}
)
TERMINAL_STATES = frozenset({"complete", "complete_with_warnings", "failed"})
CONFIDENCE_VALUES = frozenset(COMPONENT_CONFIDENCE_VALUES)
FILE_DISPOSITIONS = frozenset(
    {"owned", "supporting", "repository_infrastructure", "excluded", "unresolved"}
)
DIAGNOSTIC_SEVERITIES = frozenset({"info", "warning", "fatal"})
RECONCILIATION_DECISIONS = frozenset({"same", "distinct"})
MANIFEST_TYPES = frozenset({"source_manifest", "component_manifest", "module_manifest"})
KNOWLEDGE_TYPES = frozenset(
    {"architecture_knowledge", "module_knowledge", "function_knowledge"}
)
REQUEST_TYPES = frozenset(KNOWLEDGE_REQUEST_TYPE_VALUES)
REQUEST_STATUSES = frozenset(KNOWLEDGE_REQUEST_STATUS_VALUES)


@dataclass(frozen=True)
class Phase3Issue:
    """One structural Phase 3 contract violation."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}" if self.path else self.message


class Phase3ContractError(CodeLearnerError):
    """Raised when a Phase 3 artifact fails deterministic validation."""

    def __init__(self, artifact: str, issues: Iterable[Phase3Issue]) -> None:
        self.artifact = artifact
        self.issues = tuple(issues)
        detail = "; ".join(str(issue) for issue in self.issues)
        super().__init__(f"invalid {artifact}: {detail}")


@dataclass(frozen=True)
class SymbolLocator:
    """A source-oriented symbol citation authored by AI and resolved by host."""

    file_id: str
    name: str
    kind: str
    start_line: int
    end_line: int
    scope: str = ""
    language: str = ""
    signature: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, object]) -> SymbolLocator:
        start = _integer(value.get("start_line"), 1)
        return cls(
            file_id=str(value.get("file_id") or ""),
            name=str(value.get("name") or ""),
            kind=str(value.get("kind") or "symbol"),
            start_line=start,
            end_line=_integer(value.get("end_line"), start),
            scope=str(value.get("scope") or ""),
            language=str(value.get("language") or ""),
            signature=str(value.get("signature") or ""),
        )

    def canonical_key(self, repository_revision: str, path: str) -> str:
        parts = (
            repository_revision,
            path,
            self.language,
            self.kind,
            self.scope,
            self.name,
            str(self.start_line),
        )
        return "\x1f".join(parts)

    def to_dict(self) -> dict[str, object]:
        return {
            "file_id": self.file_id,
            "name": self.name,
            "kind": self.kind,
            "scope": self.scope,
            "language": self.language,
            "signature": self.signature,
            "start_line": self.start_line,
            "end_line": self.end_line,
        }


def load_phase3_schema() -> dict[str, object]:
    """Load the packaged portable Phase 3 JSON Schema."""

    path = Path(__file__).with_name("schemas") / "phase3.schema.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"could not load Code Learner Phase 3 schema: {error}")
    if not isinstance(value, dict):
        raise RuntimeError("Code Learner Phase 3 schema is not an object")
    validate_component_schema_alignment(value)
    validate_phase3_schema_alignment(value)
    return value


def parse_phase3_jsonl(text: str, *, artifact: str) -> list[dict[str, object]]:
    """Parse JSONL while preserving a single domain object as one record."""

    records: list[dict[str, object]] = []
    issues: list[Phase3Issue] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            issues.append(Phase3Issue(f"line[{line_number}]", error.msg))
            continue
        if not isinstance(value, dict):
            issues.append(
                Phase3Issue(f"line[{line_number}]", "record must be an object")
            )
            continue
        records.append(dict(value))
    if not records and not issues:
        issues.append(Phase3Issue("records", "at least one record is required"))
    if issues:
        raise Phase3ContractError(artifact, issues)
    return records


def validate_source_files(
    records: Iterable[Mapping[str, object]],
    *,
    repository_revision: str,
) -> list[dict[str, object]]:
    """Validate deterministic source-file records for one revision."""

    normalized = [dict(record) for record in records]
    issues: list[Phase3Issue] = []
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    for index, record in enumerate(normalized):
        prefix = f"records[{index}]"
        _header(record, prefix, "source_file", repository_revision, issues)
        file_id = _required_string(record, prefix, "id", issues)
        path = _required_string(record, prefix, "path", issues)
        _required_string(record, prefix, "content_hash", issues)
        _nonnegative_integer(record, prefix, "size", issues)
        _required_string(record, prefix, "source_status", issues)
        if file_id and file_id in seen_ids:
            issues.append(Phase3Issue(f"{prefix}.id", "duplicate file ID"))
        if path and path in seen_paths:
            issues.append(Phase3Issue(f"{prefix}.path", "duplicate source path"))
        if path and (path.startswith("/") or ".." in Path(path).parts):
            issues.append(Phase3Issue(f"{prefix}.path", "must be repository-relative"))
        seen_ids.add(file_id)
        seen_paths.add(path)
    _raise("source files", issues)
    return normalized


def validate_component_candidates(
    records: Iterable[Mapping[str, object]],
    *,
    repository_revision: str,
    files: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    """Validate candidate shape and concrete file grounding."""

    normalized = [dict(record) for record in records]
    issues: list[Phase3Issue] = []
    seen: set[str] = set()
    for index, record in enumerate(normalized):
        prefix = f"records[{index}]"
        _header(record, prefix, "component_candidate", repository_revision, issues)
        _required_string(record, prefix, "analysis_run_id", issues)
        candidate_id = _required_string(record, prefix, "candidate_id", issues)
        _required_string(record, prefix, "name", issues)
        _required_enum(
            record,
            prefix,
            "name_origin",
            COMPONENT_NAME_ORIGIN_VALUES,
            issues,
        )
        _required_string(record, prefix, "kind", issues)
        _required_string(record, prefix, "responsibility", issues)
        if candidate_id in seen:
            issues.append(Phase3Issue(f"{prefix}.candidate_id", "duplicate candidate"))
        seen.add(candidate_id)
        file_ids = _string_list(record, prefix, "file_ids", issues, required=True)
        for file_index, file_id in enumerate(file_ids):
            if file_id not in files:
                issues.append(
                    Phase3Issue(
                        f"{prefix}.file_ids[{file_index}]", "unknown source file ID"
                    )
                )
        symbols = _mapping_list(
            record, prefix, "symbols", issues, field_required=True
        )
        for symbol_index, symbol in enumerate(symbols):
            _validate_locator(
                symbol,
                f"{prefix}.symbols[{symbol_index}]",
                files,
                issues,
            )
        for field in ("owned_source_refs", "supporting_source_refs"):
            for ref_index, reference in enumerate(
                _mapping_list(
                    record,
                    prefix,
                    field,
                    issues,
                    field_required=True,
                    item_required=field == "owned_source_refs",
                )
            ):
                _validate_source_reference(
                    reference,
                    f"{prefix}.{field}[{ref_index}]",
                    files,
                    issues,
                )
        _required_enum(
            record, prefix, "confidence", COMPONENT_CONFIDENCE_VALUES, issues
        )
        if "limitations" not in record:
            issues.append(Phase3Issue(f"{prefix}.limitations", "field is required"))
        _string_list(record, prefix, "limitations", issues)
    _raise("component candidates", issues)
    return normalized


def validate_overlap_groups(
    records: Iterable[Mapping[str, object]],
    *,
    candidate_ids: set[str],
) -> list[dict[str, object]]:
    """Validate exact-symbol overlap groups."""

    normalized = [dict(record) for record in records]
    issues: list[Phase3Issue] = []
    for index, record in enumerate(normalized):
        prefix = f"records[{index}]"
        _header(record, prefix, "overlap_group", "", issues)
        _required_string(record, prefix, "id", issues)
        members = _string_list(record, prefix, "candidate_ids", issues, required=True)
        if len(set(members)) < 2:
            issues.append(
                Phase3Issue(f"{prefix}.candidate_ids", "needs two candidates")
            )
        _known_values(members, candidate_ids, f"{prefix}.candidate_ids", issues)
        edges = _mapping_list(record, prefix, "shared_symbol_edges", issues)
        if not edges:
            issues.append(
                Phase3Issue(f"{prefix}.shared_symbol_edges", "must not be empty")
            )
        for edge_index, edge in enumerate(edges):
            edge_prefix = f"{prefix}.shared_symbol_edges[{edge_index}]"
            _required_string(edge, edge_prefix, "canonical_key", issues)
            edge_members = _string_list(
                edge, edge_prefix, "candidate_ids", issues, required=True
            )
            if len(set(edge_members)) < 2:
                issues.append(
                    Phase3Issue(f"{edge_prefix}.candidate_ids", "needs two candidates")
                )
            _known_values(edge_members, set(members), edge_prefix, issues)
    _raise("overlap groups", issues)
    return normalized


def validate_reconciliations(
    records: Iterable[Mapping[str, object]],
    *,
    groups: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    """Validate complete same/distinct partitions for overlap groups."""

    normalized = [dict(record) for record in records]
    issues: list[Phase3Issue] = []
    for index, record in enumerate(normalized):
        prefix = f"records[{index}]"
        _header(record, prefix, "component_reconciliation", "", issues)
        _require_fields(record, prefix, RECONCILIATION_REQUIRED_FIELDS, issues)
        _required_string(record, prefix, "repository_revision", issues)
        _required_string(record, prefix, "analysis_run_id", issues)
        group_id = _required_string(record, prefix, "overlap_group_id", issues)
        decision = _required_string(record, prefix, "decision", issues)
        if decision not in RECONCILIATION_DECISIONS:
            issues.append(Phase3Issue(f"{prefix}.decision", "must be same or distinct"))
        group = groups.get(group_id)
        if group is None:
            issues.append(Phase3Issue(f"{prefix}.overlap_group_id", "unknown group"))
            continue
        expected = set(str(item) for item in group.get("candidate_ids", []))
        partitions = _mapping_list(record, prefix, "partitions", issues)
        flattened: list[str] = []
        for part_index, partition in enumerate(partitions):
            part_prefix = f"{prefix}.partitions[{part_index}]"
            _require_fields(
                partition,
                part_prefix,
                RECONCILIATION_PARTITION_REQUIRED_FIELDS,
                issues,
            )
            members = _string_list(
                partition,
                part_prefix,
                "candidate_ids",
                issues,
                required=True,
            )
            flattened.extend(members)
            _required_string(partition, part_prefix, "reason", issues)
        _required_string(record, prefix, "reason", issues)
        _string_list(record, prefix, "limitations", issues)
        if set(flattened) != expected or len(flattened) != len(expected):
            issues.append(
                Phase3Issue(
                    f"{prefix}.partitions",
                    "must contain every group candidate exactly once",
                )
            )
        if decision == "same" and len(partitions) != 1:
            issues.append(
                Phase3Issue(f"{prefix}.partitions", "same needs one partition")
            )
        if decision == "distinct" and len(partitions) < 2:
            issues.append(
                Phase3Issue(
                    f"{prefix}.partitions", "distinct needs at least two partitions"
                )
            )
    _raise("component reconciliations", issues)
    return normalized


def validate_components(
    records: Iterable[Mapping[str, object]],
    *,
    repository_revision: str,
    files: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    """Validate reconciled components without interpreting their semantics."""

    normalized = [dict(record) for record in records]
    issues: list[Phase3Issue] = []
    seen: set[str] = set()
    for index, record in enumerate(normalized):
        prefix = f"records[{index}]"
        _header(record, prefix, "component", repository_revision, issues)
        component_id = _required_string(record, prefix, "id", issues)
        _required_string(record, prefix, "name", issues)
        _required_string(record, prefix, "kind", issues)
        _required_string(record, prefix, "responsibility", issues)
        if component_id in seen:
            issues.append(Phase3Issue(f"{prefix}.id", "duplicate component ID"))
        seen.add(component_id)
        file_ids = _string_list(record, prefix, "file_ids", issues, required=True)
        _known_values(file_ids, set(files), f"{prefix}.file_ids", issues)
        for symbol_index, symbol in enumerate(
            _mapping_list(record, prefix, "symbols", issues)
        ):
            _validate_locator(
                symbol,
                f"{prefix}.symbols[{symbol_index}]",
                files,
                issues,
            )
    _raise("components", issues)
    return normalized


def validate_file_dispositions(
    records: Iterable[Mapping[str, object]],
    *,
    file_ids: set[str],
    component_ids: set[str],
) -> list[dict[str, object]]:
    """Require one explicit disposition for every in-scope file."""

    normalized = [dict(record) for record in records]
    issues: list[Phase3Issue] = []
    seen: set[str] = set()
    for index, record in enumerate(normalized):
        prefix = f"records[{index}]"
        _header(record, prefix, "file_disposition", "", issues)
        file_id = _required_string(record, prefix, "file_id", issues)
        disposition = _required_string(record, prefix, "disposition", issues)
        if file_id not in file_ids:
            issues.append(Phase3Issue(f"{prefix}.file_id", "unknown source file ID"))
        if file_id in seen:
            issues.append(Phase3Issue(f"{prefix}.file_id", "duplicate disposition"))
        seen.add(file_id)
        if disposition not in FILE_DISPOSITIONS:
            issues.append(Phase3Issue(f"{prefix}.disposition", "unsupported value"))
        members = _string_list(record, prefix, "component_ids", issues)
        _known_values(members, component_ids, f"{prefix}.component_ids", issues)
        if disposition in {"owned", "supporting"} and not members:
            issues.append(
                Phase3Issue(f"{prefix}.component_ids", "component membership required")
            )
        if disposition in {"repository_infrastructure", "excluded", "unresolved"}:
            _required_string(record, prefix, "reason", issues)
    missing = file_ids - seen
    if missing:
        issues.append(
            Phase3Issue(
                "records", f"missing dispositions: {', '.join(sorted(missing))}"
            )
        )
    _raise("file dispositions", issues)
    return normalized


def validate_modules(
    records: Iterable[Mapping[str, object]],
    *,
    repository_revision: str,
    component_ids: set[str],
) -> list[dict[str, object]]:
    """Validate module membership and acyclic optional hierarchy."""

    normalized = [dict(record) for record in records]
    issues: list[Phase3Issue] = []
    ids = {str(record.get("id") or "") for record in normalized}
    parents: dict[str, str] = {}
    for index, record in enumerate(normalized):
        prefix = f"records[{index}]"
        _header(record, prefix, "module", repository_revision, issues)
        _require_fields(record, prefix, MODULE_REQUIRED_FIELDS, issues)
        module_id = _required_string(record, prefix, "id", issues)
        _required_string(record, prefix, "name", issues)
        _required_string(record, prefix, "kind", issues)
        _required_string(record, prefix, "purpose", issues)
        _required_string(record, prefix, "responsibility", issues)
        _required_string(record, prefix, "grouping_rationale", issues)
        members = _string_list(record, prefix, "component_ids", issues, required=True)
        _known_values(members, component_ids, f"{prefix}.component_ids", issues)
        for field in (
            "primary_component_ids",
            "entry_component_ids",
            "primary_for_component_ids",
        ):
            _known_values(
                _string_list(record, prefix, field, issues),
                component_ids,
                f"{prefix}.{field}",
                issues,
            )
        _required_enum(record, prefix, "confidence", CONFIDENCE_VALUES, issues)
        _string_list(record, prefix, "limitations", issues)
        parent = str(record.get("parent_module_id") or "")
        if parent:
            parents[module_id] = parent
            if parent not in ids:
                issues.append(
                    Phase3Issue(f"{prefix}.parent_module_id", "unknown module ID")
                )
    for module_id in ids:
        visited: set[str] = set()
        current = module_id
        while current in parents:
            if current in visited:
                issues.append(
                    Phase3Issue("modules", "module hierarchy contains a cycle")
                )
                break
            visited.add(current)
            current = parents[current]
    _raise("modules", issues)
    return normalized


def validate_module_relationships(
    records: Iterable[Mapping[str, object]],
    *,
    repository_revision: str,
    module_ids: set[str],
    component_ids: set[str],
) -> list[dict[str, object]]:
    """Validate module-only relationship endpoints and supporting evidence."""

    normalized = [dict(record) for record in records]
    issues: list[Phase3Issue] = []
    for index, record in enumerate(normalized):
        prefix = f"records[{index}]"
        _header(record, prefix, "module_relationship", repository_revision, issues)
        _require_fields(record, prefix, MODULE_RELATIONSHIP_REQUIRED_FIELDS, issues)
        _required_string(record, prefix, "id", issues)
        for field in ("from_module_id", "to_module_id"):
            endpoint = _required_string(record, prefix, field, issues)
            if endpoint not in module_ids:
                issues.append(Phase3Issue(f"{prefix}.{field}", "unknown module ID"))
        _required_string(record, prefix, "kind", issues)
        _required_string(record, prefix, "summary", issues)
        supports = _string_list(record, prefix, "supporting_component_ids", issues)
        _known_values(
            supports, component_ids, f"{prefix}.supporting_component_ids", issues
        )
        _string_list(record, prefix, "limitations", issues)
    _raise("module relationships", issues)
    return normalized


def validate_manifest(
    record: Mapping[str, object],
    *,
    manifest_type: str,
    repository_revision: str,
) -> dict[str, object]:
    """Validate source, component, or frozen module manifest metadata."""

    normalized = dict(record)
    issues: list[Phase3Issue] = []
    if manifest_type not in MANIFEST_TYPES:
        raise KeyError(f"unknown Phase 3 manifest type: {manifest_type}")
    _header(normalized, "manifest", manifest_type, repository_revision, issues)
    _required_string(normalized, "manifest", "id", issues)
    status = _required_string(normalized, "manifest", "status", issues)
    if status not in COMPLETION_STATES:
        issues.append(Phase3Issue("manifest.status", "unsupported completion state"))
    if manifest_type == "source_manifest":
        _string_list(normalized, "manifest", "file_ids", issues)
        _nonnegative_integer(normalized, "manifest", "raw_tag_count", issues)
    elif manifest_type == "component_manifest":
        _string_list(normalized, "manifest", "component_ids", issues)
        _string_list(normalized, "manifest", "unresolved_overlap_group_ids", issues)
        _required_string(normalized, "manifest", "coverage_path", issues)
    else:
        _string_list(normalized, "manifest", "module_ids", issues)
        if not isinstance(normalized.get("frozen"), bool):
            issues.append(Phase3Issue("manifest.frozen", "must be boolean"))
    _raise(manifest_type, issues)
    return normalized


def validate_coverage_report(
    record: Mapping[str, object],
    *,
    repository_revision: str,
) -> dict[str, object]:
    """Validate aggregate file-disposition counts and unresolved identities."""

    normalized = dict(record)
    issues: list[Phase3Issue] = []
    _header(normalized, "coverage", "file_coverage", repository_revision, issues)
    for field in (
        "in_scope_count",
        "owned_count",
        "supporting_count",
        "repository_infrastructure_count",
        "excluded_count",
        "unresolved_count",
    ):
        _nonnegative_integer(normalized, "coverage", field, issues)
    unresolved = _string_list(normalized, "coverage", "unresolved_file_ids", issues)
    counts = [
        _integer(normalized.get(field), 0)
        for field in (
            "owned_count",
            "supporting_count",
            "repository_infrastructure_count",
            "excluded_count",
            "unresolved_count",
        )
    ]
    if sum(counts) != _integer(normalized.get("in_scope_count"), -1):
        issues.append(Phase3Issue("coverage", "disposition counts must cover scope"))
    if len(unresolved) != _integer(normalized.get("unresolved_count"), -1):
        issues.append(
            Phase3Issue("coverage.unresolved_file_ids", "count does not match")
        )
    _raise("file coverage", issues)
    return normalized


def validate_knowledge_artifacts(
    records: Iterable[Mapping[str, object]],
    *,
    repository_revision: str,
    component_ids: set[str],
    module_ids: set[str],
) -> list[dict[str, object]]:
    """Validate layered Architecture, Module, and Function knowledge records."""

    normalized = [dict(record) for record in records]
    issues: list[Phase3Issue] = []
    seen: set[str] = set()
    for index, record in enumerate(normalized):
        prefix = f"records[{index}]"
        record_type = str(record.get("record_type") or "")
        if record_type not in KNOWLEDGE_TYPES:
            issues.append(
                Phase3Issue(f"{prefix}.record_type", "unsupported knowledge type")
            )
            continue
        _header(record, prefix, record_type, repository_revision, issues)
        required_fields = {
            "architecture_knowledge": ARCHITECTURE_KNOWLEDGE_REQUIRED_FIELDS,
            "module_knowledge": MODULE_KNOWLEDGE_REQUIRED_FIELDS,
            "function_knowledge": FUNCTION_KNOWLEDGE_REQUIRED_FIELDS,
        }[record_type]
        _require_fields(record, prefix, required_fields, issues)
        record_id = _required_string(record, prefix, "id", issues)
        if record_id in seen:
            issues.append(Phase3Issue(f"{prefix}.id", "duplicate knowledge ID"))
        seen.add(record_id)
        _required_string(record, prefix, "title", issues)
        _required_string(record, prefix, "body", issues)
        _known_values(
            _string_list(record, prefix, "component_ids", issues),
            component_ids,
            f"{prefix}.component_ids",
            issues,
        )
        _known_values(
            _string_list(record, prefix, "module_ids", issues),
            module_ids,
            f"{prefix}.module_ids",
            issues,
        )
        if record_type == "module_knowledge":
            module_id = _required_string(record, prefix, "module_id", issues)
            if module_id not in module_ids:
                issues.append(Phase3Issue(f"{prefix}.module_id", "unknown module ID"))
        if record_type == "function_knowledge":
            locator = record.get("symbol")
            if not isinstance(locator, Mapping):
                issues.append(Phase3Issue(f"{prefix}.symbol", "must be an object"))
            else:
                _required_string(locator, f"{prefix}.symbol", "file_id", issues)
                _required_string(locator, f"{prefix}.symbol", "name", issues)
        diagrams = _mapping_list(record, prefix, "diagrams", issues)
        for diagram_index, diagram in enumerate(diagrams):
            diagram_prefix = f"{prefix}.diagrams[{diagram_index}]"
            _required_string(diagram, diagram_prefix, "type", issues)
            _required_string(diagram, diagram_prefix, "mermaid", issues)
    _raise("knowledge artifacts", issues)
    return normalized


def validate_knowledge_requests(
    records: Iterable[Mapping[str, object]],
    *,
    repository_revision: str,
) -> list[dict[str, object]]:
    """Validate targeted requests without allowing inline canonical creation."""

    normalized = [dict(record) for record in records]
    issues: list[Phase3Issue] = []
    for index, record in enumerate(normalized):
        prefix = f"records[{index}]"
        _header(record, prefix, "knowledge_request", repository_revision, issues)
        _require_fields(
            record, prefix, KNOWLEDGE_REQUEST_REQUIRED_FIELDS, issues
        )
        _required_string(record, prefix, "id", issues)
        request_type = _required_string(record, prefix, "request_type", issues)
        if request_type not in REQUEST_TYPES:
            issues.append(Phase3Issue(f"{prefix}.request_type", "unsupported value"))
        status = _required_string(record, prefix, "status", issues)
        if status not in REQUEST_STATUSES:
            issues.append(Phase3Issue(f"{prefix}.status", "unsupported value"))
        _required_string(record, prefix, "reason", issues)
    _raise("knowledge requests", issues)
    return normalized


def validate_diagnostic(record: Mapping[str, object]) -> dict[str, object]:
    normalized = dict(record)
    issues: list[Phase3Issue] = []
    _header(normalized, "diagnostic", "diagnostic", "", issues)
    _required_string(normalized, "diagnostic", "id", issues)
    severity = _required_string(normalized, "diagnostic", "severity", issues)
    if severity not in DIAGNOSTIC_SEVERITIES:
        issues.append(Phase3Issue("diagnostic.severity", "unsupported value"))
    _required_string(normalized, "diagnostic", "code", issues)
    _required_string(normalized, "diagnostic", "message", issues)
    _raise("diagnostic", issues)
    return normalized


def validate_terminal_result(record: Mapping[str, object]) -> dict[str, object]:
    """Validate terminal status and course activation invariants."""

    normalized = dict(record)
    issues: list[Phase3Issue] = []
    if normalized.get("schema_version") != PHASE3_SCHEMA_VERSION:
        issues.append(Phase3Issue("schema_version", "must be 1"))
    status = _required_string(normalized, "result", "status", issues)
    if status not in TERMINAL_STATES:
        issues.append(Phase3Issue("result.status", "unsupported terminal state"))
    active = normalized.get("course_active")
    if not isinstance(active, bool):
        issues.append(Phase3Issue("result.course_active", "must be boolean"))
    if status in {"complete", "complete_with_warnings"} and active is not True:
        issues.append(
            Phase3Issue("result.course_active", "successful result is active")
        )
    if status == "failed" and active is not False:
        issues.append(Phase3Issue("result.course_active", "failed result is inactive"))
    warnings = _integer(normalized.get("warning_count"), -1)
    if warnings < 0:
        issues.append(Phase3Issue("result.warning_count", "must be nonnegative"))
    if status == "complete" and warnings:
        issues.append(Phase3Issue("result.warning_count", "complete has no warnings"))
    if status == "complete_with_warnings" and warnings < 1:
        issues.append(
            Phase3Issue("result.warning_count", "warning completion needs warnings")
        )
    if status == "failed":
        _required_string(normalized, "result", "failed_scope", issues)
        _required_string(normalized, "result", "recovery_action", issues)
    _raise("terminal result", issues)
    return normalized


def _header(
    record: Mapping[str, object],
    prefix: str,
    record_type: str,
    repository_revision: str,
    issues: list[Phase3Issue],
) -> None:
    if record.get("schema_version") != PHASE3_SCHEMA_VERSION:
        issues.append(Phase3Issue(f"{prefix}.schema_version", "must be 1"))
    if record.get("record_type") != record_type:
        issues.append(Phase3Issue(f"{prefix}.record_type", f"must be {record_type}"))
    if repository_revision and record.get("repository_revision") != repository_revision:
        issues.append(
            Phase3Issue(f"{prefix}.repository_revision", "revision does not match")
        )


def _require_fields(
    record: Mapping[str, object],
    prefix: str,
    fields: Sequence[str],
    issues: list[Phase3Issue],
) -> None:
    for field in fields:
        if field not in record:
            issues.append(Phase3Issue(f"{prefix}.{field}", "field is required"))


def _validate_locator(
    value: Mapping[str, object],
    prefix: str,
    files: Mapping[str, Mapping[str, object]],
    issues: list[Phase3Issue],
) -> None:
    file_id = _required_string(value, prefix, "file_id", issues)
    _required_string(value, prefix, "name", issues)
    _required_string(value, prefix, "kind", issues)
    start = _positive_integer(value, prefix, "start_line", issues)
    end = _positive_integer(value, prefix, "end_line", issues, default=start)
    if end < start:
        issues.append(Phase3Issue(f"{prefix}.end_line", "must not precede start"))
    if file_id not in files:
        issues.append(Phase3Issue(f"{prefix}.file_id", "unknown source file ID"))


def _validate_source_reference(
    value: Mapping[str, object],
    prefix: str,
    files: Mapping[str, Mapping[str, object]],
    issues: list[Phase3Issue],
) -> None:
    file_id = _required_string(value, prefix, "file_id", issues)
    if file_id not in files:
        issues.append(Phase3Issue(f"{prefix}.file_id", "unknown source file ID"))
    start = _positive_integer(value, prefix, "start_line", issues)
    end = _positive_integer(value, prefix, "end_line", issues, default=start)
    if end < start:
        issues.append(Phase3Issue(f"{prefix}.end_line", "must not precede start"))
    _required_string(value, prefix, "reason", issues)


def _required_string(
    record: Mapping[str, object],
    prefix: str,
    field: str,
    issues: list[Phase3Issue],
) -> str:
    value = record.get(field)
    if not isinstance(value, str) or not value.strip():
        issues.append(Phase3Issue(f"{prefix}.{field}", "must be a non-empty string"))
        return ""
    return value.strip()


def _string_list(
    record: Mapping[str, object],
    prefix: str,
    field: str,
    issues: list[Phase3Issue],
    *,
    required: bool = False,
) -> list[str]:
    value = record.get(field, [])
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        issues.append(Phase3Issue(f"{prefix}.{field}", "must be an array of strings"))
        return []
    result = [item.strip() for item in value if item.strip()]
    if required and not result:
        issues.append(Phase3Issue(f"{prefix}.{field}", "must not be empty"))
    if len(result) != len(set(result)):
        issues.append(Phase3Issue(f"{prefix}.{field}", "must not contain duplicates"))
    return result


def _mapping_list(
    record: Mapping[str, object],
    prefix: str,
    field: str,
    issues: list[Phase3Issue],
    *,
    field_required: bool = False,
    item_required: bool = False,
) -> list[Mapping[str, object]]:
    if field_required and field not in record:
        issues.append(Phase3Issue(f"{prefix}.{field}", "field is required"))
    value = record.get(field, [])
    if not isinstance(value, list) or any(
        not isinstance(item, Mapping) for item in value
    ):
        issues.append(Phase3Issue(f"{prefix}.{field}", "must be an array of objects"))
        return []
    if item_required and not value:
        issues.append(Phase3Issue(f"{prefix}.{field}", "must not be empty"))
    return list(value)


def _optional_enum(
    record: Mapping[str, object],
    prefix: str,
    field: str,
    choices: Sequence[str] | set[str] | frozenset[str],
    issues: list[Phase3Issue],
) -> None:
    value = record.get(field)
    if value in (None, ""):
        return
    if value not in choices:
        issues.append(Phase3Issue(f"{prefix}.{field}", "unsupported value"))


def _required_enum(
    record: Mapping[str, object],
    prefix: str,
    field: str,
    choices: Sequence[str] | set[str] | frozenset[str],
    issues: list[Phase3Issue],
) -> None:
    value = _required_string(record, prefix, field, issues)
    if value and value not in choices:
        accepted = ", ".join(sorted(choices))
        issues.append(
            Phase3Issue(f"{prefix}.{field}", f"must be one of: {accepted}")
        )


def _positive_integer(
    record: Mapping[str, object],
    prefix: str,
    field: str,
    issues: list[Phase3Issue],
    *,
    default: int = 0,
) -> int:
    value = record.get(field, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        issues.append(Phase3Issue(f"{prefix}.{field}", "must be a positive integer"))
        return max(1, default)
    return value


def _nonnegative_integer(
    record: Mapping[str, object],
    prefix: str,
    field: str,
    issues: list[Phase3Issue],
) -> None:
    value = record.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        issues.append(Phase3Issue(f"{prefix}.{field}", "must be nonnegative integer"))


def _known_values(
    values: Iterable[str],
    known: set[str],
    prefix: str,
    issues: list[Phase3Issue],
) -> None:
    for index, value in enumerate(values):
        if value not in known:
            issues.append(Phase3Issue(f"{prefix}[{index}]", f"unknown ID: {value}"))


def _integer(value: object, default: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _raise(artifact: str, issues: list[Phase3Issue]) -> None:
    if issues:
        raise Phase3ContractError(artifact, issues)
