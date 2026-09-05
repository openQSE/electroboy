"""Canonical Phase 2 contracts and deterministic validation.

The JSON Schema resources are the portable contract published to AI runtimes.
This module enforces the same invariants without requiring a third-party JSON
Schema runtime and adds repository and cross-record checks that schemas cannot
perform alone.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

SCHEMA_VERSION = 1
SCHEMA_NAMES = frozenset({"knowledge", "course", "tutor-context"})

KNOWLEDGE_RECORD_TYPES = frozenset(
    {
        "knowledge_manifest",
        "entity",
        "relationship",
        "runtime_flow",
        "diagnostic",
        "knowledge_request",
    }
)
COURSE_RECORD_TYPES = frozenset({"document", "section"})
ENTITY_KINDS = frozenset(
    {
        "repository",
        "module",
        "extension-family",
        "implementation",
        "entry-point",
        "interface",
        "symbol",
        "data-type",
        "state-store",
        "process",
        "external-system",
        "test-surface",
        "build-target",
    }
)
RELATIONSHIP_KINDS = frozenset(
    {
        "contains",
        "calls",
        "implements",
        "extends",
        "depends-on",
        "creates",
        "owns",
        "reads",
        "writes",
        "publishes",
        "subscribes",
        "sends-to",
        "receives-from",
        "configures",
        "selects",
        "registers",
        "dispatches-to",
        "persists-to",
        "tests",
        "deploys",
    }
)
CONFIDENCE_VALUES = frozenset({"verified", "high", "medium", "low", "unknown"})
COURSE_MODES = frozenset({"architecture", "module", "function"})
DIAGNOSTIC_SEVERITIES = frozenset({"info", "warning", "error"})
REQUEST_STATUSES = frozenset({"open", "resolved", "blocked", "dismissed"})


@dataclass(frozen=True)
class ContractIssue:
    """One deterministic contract failure."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}" if self.path else self.message


class ContractError(ValueError):
    """Raised when a Phase 2 artifact violates its canonical contract."""

    def __init__(self, artifact: str, issues: Iterable[ContractIssue]) -> None:
        self.artifact = artifact
        self.issues = tuple(issues)
        detail = "; ".join(str(issue) for issue in self.issues)
        super().__init__(f"invalid {artifact}: {detail}")


def load_contract_schema(name: str) -> dict[str, object]:
    """Load one packaged JSON Schema by stable contract name."""

    normalized = str(name or "").strip().lower().removesuffix(".schema.json")
    if normalized not in SCHEMA_NAMES:
        expected = ", ".join(sorted(SCHEMA_NAMES))
        raise KeyError(f"unknown Code Learner schema {name!r}; expected {expected}")
    path = Path(__file__).with_name("schemas") / f"{normalized}.schema.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(
            f"could not load Code Learner schema {normalized}: {error}"
        ) from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"Code Learner schema {normalized} is not an object")
    return payload


def parse_jsonl(text: str, *, artifact: str) -> list[dict[str, object]]:
    """Parse a strict JSONL stream before artifact-specific validation."""

    records: list[dict[str, object]] = []
    issues: list[ContractIssue] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as error:
            issues.append(ContractIssue(f"line[{line_number}]", error.msg))
            continue
        if not isinstance(value, dict):
            issues.append(
                ContractIssue(f"line[{line_number}]", "record must be an object")
            )
            continue
        records.append(dict(value))
    if not records and not issues:
        issues.append(ContractIssue("records", "at least one record is required"))
    if issues:
        raise ContractError(artifact, issues)
    return records


def validate_knowledge_records(
    records: Iterable[Mapping[str, object]],
    *,
    root: Path | str | None = None,
) -> list[dict[str, object]]:
    """Validate knowledge syntax, references, counts, and source evidence."""

    normalized = [dict(record) for record in records]
    issues: list[ContractIssue] = []
    ids = _validate_record_headers(
        normalized,
        allowed_types=KNOWLEDGE_RECORD_TYPES,
        artifact="knowledge",
        issues=issues,
    )
    entities = {
        str(record.get("id")): record
        for record in normalized
        if record.get("record_type") == "entity"
    }
    manifests = [
        record
        for record in normalized
        if record.get("record_type") == "knowledge_manifest"
    ]
    if len(manifests) != 1:
        issues.append(
            ContractIssue("records", "exactly one knowledge_manifest is required")
        )

    for index, record in enumerate(normalized):
        prefix = f"records[{index}]"
        record_type = record.get("record_type")
        if record_type == "knowledge_manifest":
            _require_strings(
                record, prefix, issues, "repository_name", "scope_path", "status"
            )
            for field in (
                "entity_count",
                "relationship_count",
                "flow_count",
                "diagnostic_count",
            ):
                _require_nonnegative_integer(record, prefix, field, issues)
        elif record_type == "entity":
            _require_strings(record, prefix, issues, "name", "summary")
            _require_enum(record, prefix, "kind", ENTITY_KINDS, issues)
            parent_id = record.get("parent_id")
            if parent_id not in (None, "") and parent_id not in entities:
                issues.append(ContractIssue(f"{prefix}.parent_id", "unknown entity ID"))
            _validate_confidence(record, prefix, issues)
            _validate_source_refs(record, prefix, issues, root=root)
        elif record_type == "relationship":
            _require_enum(record, prefix, "kind", RELATIONSHIP_KINDS, issues)
            _require_strings(record, prefix, issues, "from_id", "to_id", "summary")
            for field in ("from_id", "to_id"):
                if record.get(field) not in entities:
                    issues.append(
                        ContractIssue(f"{prefix}.{field}", "unknown entity ID")
                    )
            _validate_confidence(record, prefix, issues)
            _validate_source_refs(record, prefix, issues, root=root)
        elif record_type == "runtime_flow":
            _require_strings(record, prefix, issues, "name", "kind")
            _require_id_list(record, prefix, "participant_ids", entities, issues)
            _validate_flow_steps(record, prefix, entities, ids, issues)
            _validate_confidence(record, prefix, issues)
            _validate_source_refs(record, prefix, issues, root=root)
        elif record_type == "diagnostic":
            _require_enum(
                record,
                prefix,
                "severity",
                DIAGNOSTIC_SEVERITIES,
                issues,
            )
            _require_strings(record, prefix, issues, "message")
            _validate_source_refs(record, prefix, issues, root=root, required=False)
        elif record_type == "knowledge_request":
            _require_strings(record, prefix, issues, "scope_id", "missing_facts")
            _require_enum(record, prefix, "status", REQUEST_STATUSES, issues)
            related = record.get("related_record_ids", [])
            if not isinstance(related, list):
                issues.append(
                    ContractIssue(f"{prefix}.related_record_ids", "must be an array")
                )
            else:
                for item_index, related_id in enumerate(related):
                    if related_id not in ids:
                        issues.append(
                            ContractIssue(
                                f"{prefix}.related_record_ids[{item_index}]",
                                "unknown record ID",
                            )
                        )
            _validate_source_refs(record, prefix, issues, root=root, required=False)

    if manifests:
        manifest = manifests[0]
        expected_counts = {
            "entity_count": _record_count(normalized, "entity"),
            "relationship_count": _record_count(normalized, "relationship"),
            "flow_count": _record_count(normalized, "runtime_flow"),
            "diagnostic_count": _record_count(normalized, "diagnostic"),
        }
        for field, expected in expected_counts.items():
            actual = manifest.get(field)
            if (
                isinstance(actual, int)
                and not isinstance(actual, bool)
                and actual != expected
            ):
                issues.append(
                    ContractIssue(
                        f"knowledge_manifest.{field}",
                        f"expected {expected}, got {actual}",
                    )
                )
    if issues:
        raise ContractError("knowledge records", issues)
    return normalized


def validate_course_records(
    records: Iterable[Mapping[str, object]],
    *,
    knowledge_ids: Iterable[str] = (),
    root: Path | str | None = None,
) -> list[dict[str, object]]:
    """Validate a structured course and its optional knowledge links."""

    normalized = [dict(record) for record in records]
    issues: list[ContractIssue] = []
    ids = _validate_record_headers(
        normalized,
        allowed_types=COURSE_RECORD_TYPES,
        artifact="course",
        issues=issues,
    )
    documents = [
        record for record in normalized if record.get("record_type") == "document"
    ]
    if len(documents) != 1:
        issues.append(ContractIssue("records", "exactly one document is required"))
    known_knowledge = set(knowledge_ids)

    for index, record in enumerate(normalized):
        prefix = f"records[{index}]"
        if record.get("record_type") == "document":
            _require_strings(
                record,
                prefix,
                issues,
                "title",
                "scope_id",
                "analysis_run_id",
                "repository_revision",
                "status",
            )
            _require_enum(record, prefix, "course_mode", COURSE_MODES, issues)
        elif record.get("record_type") == "section":
            _require_strings(record, prefix, issues, "parent_id", "title", "body")
            if record.get("parent_id") not in ids:
                issues.append(ContractIssue(f"{prefix}.parent_id", "unknown course ID"))
            _require_nonnegative_integer(record, prefix, "order", issues)
            _require_nonnegative_integer(record, prefix, "heading_level", issues)
            _require_enum(record, prefix, "detail_level", COURSE_MODES, issues)
            _validate_confidence(record, prefix, issues)
            _validate_source_refs(record, prefix, issues, root=root, required=False)
            for field in (
                "knowledge_entity_ids",
                "relationship_ids",
                "runtime_flow_ids",
                "related_module_ids",
                "related_symbol_ids",
                "deep_dive_ids",
            ):
                value = record.get(field, [])
                if not isinstance(value, list):
                    issues.append(
                        ContractIssue(f"{prefix}.{field}", "must be an array")
                    )
                    continue
                if known_knowledge and field in {
                    "knowledge_entity_ids",
                    "relationship_ids",
                    "runtime_flow_ids",
                }:
                    for item_index, item in enumerate(value):
                        if item not in known_knowledge:
                            issues.append(
                                ContractIssue(
                                    f"{prefix}.{field}[{item_index}]",
                                    "unknown knowledge ID",
                                )
                            )
                elif any(not isinstance(item, str) for item in value):
                    issues.append(
                        ContractIssue(f"{prefix}.{field}", "must contain strings")
                    )
            for field in (
                "previous_section_id",
                "next_section_id",
                "return_section_id",
            ):
                linked_id = record.get(field)
                if linked_id not in (None, "") and linked_id not in ids:
                    issues.append(
                        ContractIssue(f"{prefix}.{field}", "unknown course ID")
                    )
            prerequisites = record.get("prerequisite_section_ids", [])
            if not isinstance(prerequisites, list):
                issues.append(
                    ContractIssue(
                        f"{prefix}.prerequisite_section_ids",
                        "must be an array",
                    )
                )
            else:
                for item_index, item in enumerate(prerequisites):
                    if item not in ids:
                        issues.append(
                            ContractIssue(
                                f"{prefix}.prerequisite_section_ids[{item_index}]",
                                "unknown course ID",
                            )
                        )
            _validate_diagrams(record, prefix, issues)
    if issues:
        raise ContractError("course records", issues)
    return normalized


def validate_tutor_context(
    context: Mapping[str, object],
    *,
    root: Path | str | None = None,
) -> dict[str, object]:
    """Validate the compact file-backed tutor context."""

    record = dict(context)
    issues: list[ContractIssue] = []
    if record.get("schema_version") != SCHEMA_VERSION:
        issues.append(ContractIssue("schema_version", f"must equal {SCHEMA_VERSION}"))
    _require_nonnegative_integer(record, "", "context_version", issues)
    _require_strings(
        record,
        "",
        issues,
        "project_id",
        "repository_revision",
        "updated_at",
        "writer_id",
    )
    if not isinstance(record.get("stale"), bool):
        issues.append(ContractIssue("stale", "must be a boolean"))
    course = _require_object(record, "course", issues)
    if course is not None:
        _require_strings(
            course, "course", issues, "document_id", "scope_id", "section_id"
        )
        _require_enum(course, "course", "mode", COURSE_MODES, issues)
        _require_nonnegative_integer(course, "course", "horizontal_index", issues)
        _require_string_list(course, "course", "vertical_path", issues)
    selection = _require_object(record, "selection", issues)
    if selection is not None:
        for field in (
            "knowledge_entity_ids",
            "relationship_ids",
            "runtime_flow_ids",
        ):
            _require_string_list(selection, "selection", field, issues)
        for field in ("module_id", "symbol_id"):
            if selection.get(field) is not None and not isinstance(
                selection.get(field), str
            ):
                issues.append(
                    ContractIssue(f"selection.{field}", "must be a string or null")
                )
    source = record.get("source")
    if source is not None:
        if not isinstance(source, dict):
            issues.append(ContractIssue("source", "must be an object or null"))
        else:
            _validate_path(
                str(source.get("path") or ""), "source.path", issues, root=root
            )
            _require_positive_integer(source, "source", "start_line", issues)
            _require_positive_integer(source, "source", "end_line", issues)
            if isinstance(source.get("start_line"), int) and isinstance(
                source.get("end_line"), int
            ):
                if int(source["end_line"]) < int(source["start_line"]):
                    issues.append(
                        ContractIssue("source.end_line", "must be >= start_line")
                    )
    artifacts = _require_object(record, "artifacts", issues)
    if artifacts is not None:
        for field in ("course", "knowledge_root"):
            _validate_path(
                str(artifacts.get(field) or ""), f"artifacts.{field}", issues, root=root
            )
    if issues:
        raise ContractError("tutor context", issues)
    return record


def _validate_record_headers(
    records: list[dict[str, object]],
    *,
    allowed_types: frozenset[str],
    artifact: str,
    issues: list[ContractIssue],
) -> set[str]:
    if not records:
        issues.append(ContractIssue("records", "at least one record is required"))
    ids: set[str] = set()
    for index, record in enumerate(records):
        prefix = f"records[{index}]"
        if record.get("schema_version") != SCHEMA_VERSION:
            issues.append(
                ContractIssue(
                    f"{prefix}.schema_version", f"must equal {SCHEMA_VERSION}"
                )
            )
        record_type = record.get("record_type")
        if record_type not in allowed_types:
            issues.append(
                ContractIssue(
                    f"{prefix}.record_type",
                    f"unknown {artifact} record type: {record_type!r}",
                )
            )
        for field in ("id", "analysis_run_id", "repository_revision"):
            _require_strings(record, prefix, issues, field)
        record_id = record.get("id")
        if isinstance(record_id, str) and record_id:
            if record_id in ids:
                issues.append(ContractIssue(f"{prefix}.id", "duplicate record ID"))
            ids.add(record_id)
    return ids


def _validate_source_refs(
    record: Mapping[str, object],
    prefix: str,
    issues: list[ContractIssue],
    *,
    root: Path | str | None,
    required: bool = True,
) -> None:
    source_refs = record.get("source_refs")
    if source_refs is None and not required:
        return
    if not isinstance(source_refs, list):
        issues.append(ContractIssue(f"{prefix}.source_refs", "must be an array"))
        return
    if required and not source_refs:
        issues.append(ContractIssue(f"{prefix}.source_refs", "must not be empty"))
    for index, source_ref in enumerate(source_refs):
        ref_prefix = f"{prefix}.source_refs[{index}]"
        if not isinstance(source_ref, dict):
            issues.append(ContractIssue(ref_prefix, "must be an object"))
            continue
        _validate_path(
            str(source_ref.get("path") or ""), f"{ref_prefix}.path", issues, root=root
        )
        _require_positive_integer(source_ref, ref_prefix, "start_line", issues)
        _require_positive_integer(source_ref, ref_prefix, "end_line", issues)
        _require_strings(source_ref, ref_prefix, issues, "reason")
        start = source_ref.get("start_line")
        end = source_ref.get("end_line")
        if isinstance(start, int) and isinstance(end, int) and end < start:
            issues.append(
                ContractIssue(f"{ref_prefix}.end_line", "must be >= start_line")
            )
        if root is not None and isinstance(end, int):
            candidate = _resolved_child(root, str(source_ref.get("path") or ""))
            if candidate is not None and candidate.is_file():
                try:
                    line_count = (
                        len(
                            candidate.read_text(
                                encoding="utf-8", errors="replace"
                            ).splitlines()
                        )
                        or 1
                    )
                except OSError:
                    line_count = 0
                if end > line_count:
                    issues.append(
                        ContractIssue(
                            f"{ref_prefix}.end_line",
                            f"exceeds file line count {line_count}",
                        )
                    )


def _validate_flow_steps(
    record: Mapping[str, object],
    prefix: str,
    entities: Mapping[str, object],
    record_ids: set[str],
    issues: list[ContractIssue],
) -> None:
    steps = record.get("steps")
    if not isinstance(steps, list) or not steps:
        issues.append(ContractIssue(f"{prefix}.steps", "must be a non-empty array"))
        return
    orders: list[int] = []
    for index, step in enumerate(steps):
        step_prefix = f"{prefix}.steps[{index}]"
        if not isinstance(step, dict):
            issues.append(ContractIssue(step_prefix, "must be an object"))
            continue
        _require_positive_integer(step, step_prefix, "order", issues)
        _require_strings(step, step_prefix, issues, "from_id", "to_id", "action")
        if isinstance(step.get("order"), int):
            orders.append(int(step["order"]))
        for field in ("from_id", "to_id"):
            if step.get(field) not in entities:
                issues.append(
                    ContractIssue(f"{step_prefix}.{field}", "unknown entity ID")
                )
        relationship_ids = step.get("relationship_ids", [])
        if not isinstance(relationship_ids, list):
            issues.append(
                ContractIssue(f"{step_prefix}.relationship_ids", "must be an array")
            )
        else:
            for relation_index, relation_id in enumerate(relationship_ids):
                if relation_id not in record_ids:
                    issues.append(
                        ContractIssue(
                            f"{step_prefix}.relationship_ids[{relation_index}]",
                            "unknown relationship ID",
                        )
                    )
    if orders != sorted(orders) or len(set(orders)) != len(orders):
        issues.append(
            ContractIssue(f"{prefix}.steps", "orders must be unique and ascending")
        )


def _validate_diagrams(
    record: Mapping[str, object],
    prefix: str,
    issues: list[ContractIssue],
) -> None:
    diagrams = record.get("diagrams", [])
    if not isinstance(diagrams, list):
        issues.append(ContractIssue(f"{prefix}.diagrams", "must be an array"))
        return
    for index, diagram in enumerate(diagrams):
        diagram_prefix = f"{prefix}.diagrams[{index}]"
        if not isinstance(diagram, dict):
            issues.append(ContractIssue(diagram_prefix, "must be an object"))
            continue
        _require_strings(diagram, diagram_prefix, issues, "id", "type", "question")


def _validate_confidence(
    record: Mapping[str, object],
    prefix: str,
    issues: list[ContractIssue],
) -> None:
    value = record.get("confidence")
    valid_number = (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 <= float(value) <= 1
    )
    if value not in CONFIDENCE_VALUES and not valid_number:
        issues.append(
            ContractIssue(
                f"{prefix}.confidence",
                "must be verified, high, medium, low, unknown, or a number from 0 to 1",
            )
        )


def _validate_path(
    value: str,
    path: str,
    issues: list[ContractIssue],
    *,
    root: Path | str | None,
) -> None:
    if not value:
        issues.append(ContractIssue(path, "must be a non-empty string"))
        return
    candidate = Path(value)
    if candidate.is_absolute() or ".." in candidate.parts:
        issues.append(ContractIssue(path, "must be repository-relative"))
        return
    if root is not None:
        resolved = _resolved_child(root, value)
        if resolved is None:
            issues.append(ContractIssue(path, "escapes repository root"))
        elif path.endswith(".path") and not resolved.is_file():
            issues.append(ContractIssue(path, "source file does not exist"))


def _resolved_child(root: Path | str, value: str) -> Path | None:
    repository_root = Path(root).expanduser().resolve()
    candidate = (repository_root / value).resolve()
    try:
        candidate.relative_to(repository_root)
    except ValueError:
        return None
    return candidate


def _require_object(
    record: Mapping[str, object],
    field: str,
    issues: list[ContractIssue],
) -> dict[str, object] | None:
    value = record.get(field)
    if not isinstance(value, dict):
        issues.append(ContractIssue(field, "must be an object"))
        return None
    return value


def _require_strings(
    record: Mapping[str, object],
    prefix: str,
    issues: list[ContractIssue],
    *fields: str,
) -> None:
    for field in fields:
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            location = f"{prefix}.{field}" if prefix else field
            issues.append(ContractIssue(location, "must be a non-empty string"))


def _require_string_list(
    record: Mapping[str, object],
    prefix: str,
    field: str,
    issues: list[ContractIssue],
) -> None:
    value = record.get(field)
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        issues.append(ContractIssue(f"{prefix}.{field}", "must be an array of strings"))


def _require_id_list(
    record: Mapping[str, object],
    prefix: str,
    field: str,
    known: Mapping[str, object],
    issues: list[ContractIssue],
) -> None:
    value = record.get(field)
    if not isinstance(value, list):
        issues.append(ContractIssue(f"{prefix}.{field}", "must be an array"))
        return
    for index, item in enumerate(value):
        if item not in known:
            issues.append(
                ContractIssue(f"{prefix}.{field}[{index}]", "unknown entity ID")
            )


def _require_enum(
    record: Mapping[str, object],
    prefix: str,
    field: str,
    allowed: frozenset[str],
    issues: list[ContractIssue],
) -> None:
    value = record.get(field)
    if value not in allowed:
        expected = ", ".join(sorted(allowed))
        issues.append(ContractIssue(f"{prefix}.{field}", f"must be one of: {expected}"))


def _require_positive_integer(
    record: Mapping[str, object],
    prefix: str,
    field: str,
    issues: list[ContractIssue],
) -> None:
    value = record.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        issues.append(ContractIssue(f"{prefix}.{field}", "must be a positive integer"))


def _require_nonnegative_integer(
    record: Mapping[str, object],
    prefix: str,
    field: str,
    issues: list[ContractIssue],
) -> None:
    value = record.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        location = f"{prefix}.{field}" if prefix else field
        issues.append(ContractIssue(location, "must be a non-negative integer"))


def _record_count(records: list[dict[str, object]], record_type: str) -> int:
    return sum(record.get("record_type") == record_type for record in records)
