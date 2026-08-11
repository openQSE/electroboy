"""Deterministic rendering for structured JSONL artifacts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .feature_artifacts import artifact_paths_for_run, resolve_artifact_path
from .planning import implementation_plan_jsonl_path
from .state_store import StateError, StateStore


ARTIFACT_DEFAULT_MARKDOWN_PATHS = {
    "requirements": "docs/requirements.md",
    "design": "docs/detailed-design.md",
    "implementation-plan": "docs/implementation-plan.md",
    "test-plan": "docs/test-plan.md",
}

ARTIFACT_TITLES = {
    "requirements": "Requirements",
    "design": "Detailed Design",
    "implementation-plan": "Implementation Plan",
    "test-plan": "Test Plan",
}


@dataclass(frozen=True)
class RenderResult:
    """Result of rendering one structured artifact."""

    artifact: str
    jsonl_path: str
    markdown_path: str
    record_count: int


def render_artifact(
    root: Path,
    artifact: str,
    *,
    jsonl_path: str | None = None,
    markdown_path: str | None = None,
) -> RenderResult:
    """Render an artifact JSONL file into its Markdown companion."""

    root = Path(root).resolve()
    artifact = normalize_artifact_name(artifact)
    resolved_markdown = markdown_path or artifact_markdown_path(root, artifact)
    resolved_jsonl = jsonl_path or artifact_jsonl_path(root, artifact, resolved_markdown)
    records = read_artifact_records(root, resolved_jsonl)
    markdown = render_artifact_markdown(artifact, records)
    output_path = _safe_project_path(root, resolved_markdown)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(markdown, encoding="utf-8")
    return RenderResult(
        artifact=artifact,
        jsonl_path=resolved_jsonl,
        markdown_path=resolved_markdown,
        record_count=len(records),
    )


def normalize_artifact_name(value: str) -> str:
    """Normalize user-facing artifact aliases."""

    artifact = value.strip().replace("_", "-")
    aliases = {
        "requirements": "requirements",
        "requirement": "requirements",
        "design": "design",
        "detailed-design": "design",
        "implementation-plan": "implementation-plan",
        "plan": "implementation-plan",
        "test-plan": "test-plan",
        "tests": "test-plan",
    }
    if artifact not in aliases:
        known = ", ".join(sorted(ARTIFACT_DEFAULT_MARKDOWN_PATHS))
        raise StateError(f"unknown artifact: {value}; choose one of: {known}")
    return aliases[artifact]


def artifact_markdown_path(root: Path, artifact: str) -> str:
    """Return the run-aware Markdown path for an artifact."""

    artifact = normalize_artifact_name(artifact)
    default_path = ARTIFACT_DEFAULT_MARKDOWN_PATHS[artifact]
    run_id = StateStore(root).current_run_id()
    if not run_id:
        return default_path
    return resolve_artifact_path(artifact_paths_for_run(root, run_id), default_path)


def artifact_jsonl_path(
    root: Path,
    artifact: str,
    markdown_path: str | None = None,
) -> str:
    """Return the JSONL path paired with an artifact Markdown path."""

    artifact = normalize_artifact_name(artifact)
    markdown_path = markdown_path or artifact_markdown_path(root, artifact)
    if artifact == "implementation-plan":
        return implementation_plan_jsonl_path(markdown_path)
    path = Path(markdown_path)
    if path.suffix == ".md":
        return path.with_suffix(".jsonl").as_posix()
    return f"{markdown_path}.jsonl"


def read_artifact_records(root: Path, jsonl_path: str) -> list[dict[str, object]]:
    """Read and validate JSON objects from a project-relative JSONL file."""

    path = _safe_project_path(root, jsonl_path)
    if not path.exists():
        raise StateError(f"structured artifact does not exist: {jsonl_path}")
    records: list[dict[str, object]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise StateError(
                f"{jsonl_path}:{line_number}: invalid JSON: {error.msg}"
            ) from error
        if not isinstance(record, dict):
            raise StateError(f"{jsonl_path}:{line_number}: record must be an object")
        records.append(record)
    if not records:
        raise StateError(f"structured artifact has no records: {jsonl_path}")
    return records


def render_artifact_markdown(
    artifact: str,
    records: list[dict[str, object]],
) -> str:
    """Render structured artifact records to Markdown."""

    artifact = normalize_artifact_name(artifact)
    if artifact == "requirements":
        lines = _render_requirements(records)
    elif artifact == "design":
        lines = _render_design(records)
    elif artifact == "implementation-plan":
        lines = _render_implementation_plan(records)
    elif artifact == "test-plan":
        lines = _render_test_plan(records)
    else:  # pragma: no cover - normalize_artifact_name guards this branch.
        raise StateError(f"unknown artifact: {artifact}")
    return _finalize_markdown(lines)


def _render_requirements(records: list[dict[str, object]]) -> list[str]:
    lines = _document_heading(records, "requirements")
    for record in _ordered_content_records(records):
        record_type = _record_type(record)
        if record_type == "section":
            _append_heading(lines, 2, _record_title(record, "Section"), record)
            _append_body(lines, record)
            continue
        if record_type == "requirement":
            _append_heading(lines, 2, _record_title(record, "Requirement"), record)
            _append_field(lines, "Statement", _string(record.get("statement")))
            _append_body(lines, record)
            _append_field(lines, "Rationale", _string(record.get("rationale")))
            _append_field(lines, "Priority", _string(record.get("priority")))
            _append_list_field(
                lines,
                "Acceptance Criteria",
                _string_list(record.get("acceptance_criteria")),
            )
            _append_list_field(lines, "Verification", _string_list(record.get("verification")))
            _append_list_field(lines, "Dependencies", _string_list(record.get("dependencies")))
            _append_field(lines, "Status", _string(record.get("status")))
            continue
        _append_generic_record(lines, record)
    return lines


def _render_design(records: list[dict[str, object]]) -> list[str]:
    lines = _document_heading(records, "design")
    for record in _ordered_content_records(records):
        record_type = _record_type(record)
        _append_heading(lines, 2, _record_title(record, record_type.title()), record)
        _append_body(lines, record)
        if record_type == "decision":
            _append_field(lines, "Context", _string(record.get("context")))
            _append_field(lines, "Decision", _string(record.get("decision")))
            _append_list_field(lines, "Consequences", _string_list(record.get("consequences")))
        if record_type == "interface":
            _append_field(lines, "Kind", _string(record.get("kind")))
            _append_field(lines, "Producer", _string(record.get("producer")))
            _append_field(lines, "Consumer", _string(record.get("consumer")))
            _append_json_field(lines, "Schema", record.get("schema"))
        _append_list_field(lines, "Requirements", _string_list(record.get("requirements")))
        _append_list_field(lines, "Interfaces", _string_list(record.get("interfaces")))
        _append_field(lines, "Status", _string(record.get("status")))
    return lines


def _render_implementation_plan(records: list[dict[str, object]]) -> list[str]:
    lines = _document_heading(records, "implementation-plan")
    active_phase: int | None = None
    for record in _ordered_content_records(records):
        phase = _int_or_none(record.get("phase"))
        if phase is not None and phase != active_phase:
            lines.extend(["", f"## Phase {phase}"])
            active_phase = phase
        title = _record_title(record, "Implementation Unit")
        _append_heading(lines, 3 if phase is not None else 2, title, record)
        _append_body(lines, record)
        _append_list_field(lines, "Commit Tasks", _commit_tasks(record))
        _append_field(lines, "Scope", _string(record.get("scope")))
        _append_list_field(lines, "Requirements", _string_list(record.get("requirements")))
        _append_list_field(
            lines,
            "Design Sections",
            _string_list(record.get("design_sections")),
        )
        _append_list_field(lines, "Exit Criteria", _string_list(record.get("exit_criteria")))
        _append_list_field(lines, "Paths", _string_list(record.get("paths")))
        _append_list_field(lines, "Dependencies", _string_list(record.get("dependencies")))
    return lines


def _render_test_plan(records: list[dict[str, object]]) -> list[str]:
    lines = _document_heading(records, "test-plan")
    for record in _ordered_content_records(records):
        record_type = _record_type(record)
        _append_heading(lines, 2, _record_title(record, record_type.title()), record)
        _append_body(lines, record)
        if record_type == "test":
            _append_field(lines, "Level", _string(record.get("level")))
            _append_field(lines, "Suite", _string(record.get("suite")))
            _append_list_field(lines, "Preconditions", _string_list(record.get("preconditions")))
            _append_list_field(lines, "Steps", _string_list(record.get("steps")))
            _append_list_field(
                lines,
                "Expected Results",
                _string_list(record.get("expected_results")),
            )
            _append_json_field(lines, "Automation", record.get("automation"))
        if record_type == "suite":
            _append_field(lines, "Scope", _string(record.get("scope")))
        _append_list_field(lines, "Requirements", _string_list(record.get("requirements")))
        _append_list_field(
            lines,
            "Design Sections",
            _string_list(record.get("design_sections")),
        )
        _append_list_field(
            lines,
            "Implementation Units",
            _string_list(record.get("implementation_units")),
        )
        _append_field(lines, "Status", _string(record.get("status")))
    return lines


def _document_heading(records: list[dict[str, object]], artifact: str) -> list[str]:
    document = next(
        (record for record in records if _record_type(record) == "document"),
        None,
    )
    title = _string(document.get("title")) if document else ""
    lines = [f"# {title or ARTIFACT_TITLES[artifact]}"]
    if document:
        _append_field(lines, "Summary", _string(document.get("summary")))
        _append_body(lines, document)
        _append_list_field(lines, "Scope", _string_list(document.get("scope")))
        _append_list_field(
            lines,
            "Out of Scope",
            _string_list(document.get("out_of_scope")),
        )
        _append_list_field(lines, "Personas", _string_list(document.get("personas")))
        _append_field(lines, "Status", _string(document.get("status")))
    return lines


def _ordered_content_records(records: list[dict[str, object]]) -> list[dict[str, object]]:
    return sorted(
        [record for record in records if _record_type(record) != "document"],
        key=_record_sort_key,
    )


def _record_sort_key(record: dict[str, object]) -> tuple[float, str]:
    order = record.get("order")
    if isinstance(order, int | float):
        sort_order = float(order)
    else:
        sort_order = 1_000_000.0
    return sort_order, _record_id(record)


def _append_heading(
    lines: list[str],
    level: int,
    title: str,
    record: dict[str, object],
) -> None:
    record_id = _record_id(record)
    heading = f"{record_id}. {title}" if record_id else title
    lines.extend(["", f"{'#' * level} {heading}"])


def _append_generic_record(lines: list[str], record: dict[str, object]) -> None:
    _append_heading(lines, 2, _record_title(record, "Record"), record)
    _append_body(lines, record)
    _append_field(lines, "Status", _string(record.get("status")))


def _append_body(lines: list[str], record: dict[str, object]) -> None:
    body = _string(record.get("body"))
    if body:
        lines.extend(["", body])


def _append_field(lines: list[str], label: str, value: str) -> None:
    if value:
        lines.extend(["", f"**{label}:** {value}"])


def _append_list_field(lines: list[str], label: str, values: list[str]) -> None:
    if not values:
        return
    lines.extend(["", f"**{label}:**"])
    lines.extend(f"- {value}" for value in values)


def _append_json_field(lines: list[str], label: str, value: object) -> None:
    if value in (None, "", [], {}):
        return
    lines.extend(["", f"**{label}:**", "```json"])
    lines.extend(json.dumps(value, indent=2, sort_keys=True).splitlines())
    lines.append("```")


def _commit_tasks(record: dict[str, object]) -> list[str]:
    tasks = _string_list(record.get("commit_tasks"))
    if tasks:
        return tasks
    return _string_list(record.get("plan_tasks"))


def _record_type(record: dict[str, object]) -> str:
    return _string(record.get("record_type")) or "unit"


def _record_id(record: dict[str, object]) -> str:
    return _string(record.get("id")) or _string(record.get("unit_id"))


def _record_title(record: dict[str, object], fallback: str) -> str:
    return _string(record.get("title")) or fallback


def _string(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _string_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Iterable) and not isinstance(value, dict):
        return [_string(item) for item in value if _string(item)]
    return [_string(value)]


def _int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _finalize_markdown(lines: list[str]) -> str:
    while lines and lines[-1] == "":
        lines.pop()
    return "\n".join(lines) + "\n"


def _safe_project_path(root: Path, relative_path: str) -> Path:
    path = Path(relative_path)
    if path.is_absolute():
        raise StateError("artifact path must be relative")
    resolved = (root / path).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise StateError("artifact path cannot escape the project") from error
    return resolved
