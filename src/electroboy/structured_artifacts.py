"""Deterministic rendering for structured JSONL artifacts."""

from __future__ import annotations

import json
import re
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


@dataclass(frozen=True)
class ImportResult:
    """Result of importing a Markdown artifact into JSONL."""

    artifact: str
    markdown_path: str
    jsonl_path: str
    record_count: int


@dataclass(frozen=True)
class MarkdownSection:
    """One heading-delimited Markdown section."""

    level: int
    title: str
    lines: list[str]


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


def import_artifact(
    root: Path,
    artifact: str,
    *,
    markdown_path: str | None = None,
    jsonl_path: str | None = None,
) -> ImportResult:
    """Import a Markdown artifact into its structured JSONL companion."""

    root = Path(root).resolve()
    artifact = normalize_artifact_name(artifact)
    resolved_markdown = markdown_path or artifact_markdown_path(root, artifact)
    resolved_jsonl = jsonl_path or artifact_jsonl_path(root, artifact, resolved_markdown)
    markdown_file = _safe_project_path(root, resolved_markdown)
    if not markdown_file.exists():
        raise StateError(f"Markdown artifact does not exist: {resolved_markdown}")
    records = markdown_to_artifact_records(
        artifact,
        markdown_file.read_text(encoding="utf-8"),
    )
    output_path = _safe_project_path(root, resolved_jsonl)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        "\n".join(json.dumps(record, sort_keys=True) for record in records) + "\n",
        encoding="utf-8",
    )
    return ImportResult(
        artifact=artifact,
        markdown_path=resolved_markdown,
        jsonl_path=resolved_jsonl,
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


def markdown_to_artifact_records(
    artifact: str,
    markdown: str,
) -> list[dict[str, object]]:
    """Convert a Markdown companion into structured artifact records."""

    artifact = normalize_artifact_name(artifact)
    sections = _markdown_sections(markdown)
    if not sections:
        return [
            _document_record(
                artifact,
                ARTIFACT_TITLES[artifact],
                _trim_markdown_lines(markdown.splitlines()),
            )
        ]
    document_section = sections[0] if sections[0].level == 1 else None
    records: list[dict[str, object]] = []
    if document_section:
        records.append(
            _document_record(
                artifact,
                document_section.title,
                document_section.lines,
            )
        )
        content_sections = sections[1:]
    else:
        records.append(_document_record(artifact, ARTIFACT_TITLES[artifact], []))
        content_sections = sections
    if artifact == "implementation-plan":
        records.extend(_implementation_records_from_markdown(content_sections))
        return records
    if artifact == "requirements":
        records.extend(_requirements_records_from_markdown(content_sections))
        return records
    for index, section in enumerate(content_sections, 1):
        records.append(_content_record_from_markdown(artifact, section, index))
    return records


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


def _markdown_sections(markdown: str) -> list[MarkdownSection]:
    sections: list[MarkdownSection] = []
    current_level = 0
    current_title = ""
    current_lines: list[str] = []
    in_fence = False
    heading_re = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
    for line in markdown.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
        heading = None if in_fence else heading_re.match(line)
        if heading:
            if current_title:
                sections.append(
                    MarkdownSection(
                        level=current_level,
                        title=current_title,
                        lines=_trim_blank_lines(current_lines),
                    )
                )
            current_level = len(heading.group(1))
            current_title = heading.group(2).strip()
            current_lines = []
            continue
        if current_title:
            current_lines.append(line)
    if current_title:
        sections.append(
            MarkdownSection(
                level=current_level,
                title=current_title,
                lines=_trim_blank_lines(current_lines),
            )
        )
    return sections


def _document_record(
    artifact: str,
    title: str,
    lines: list[str],
) -> dict[str, object]:
    fields, body = _extract_markdown_fields(lines, _list_field_keys() | {"scope"})
    record: dict[str, object] = {
        "schema_version": 1,
        "artifact_type": artifact,
        "record_type": "document",
        "id": _document_id(artifact),
        "order": 0,
        "title": title or ARTIFACT_TITLES[artifact],
    }
    record.update(fields)
    if body:
        record["body"] = body
    record.setdefault("status", "draft")
    return record


def _content_record_from_markdown(
    artifact: str,
    section: MarkdownSection,
    index: int,
) -> dict[str, object]:
    record_id, title = _split_record_heading(section.title)
    record_type = _content_record_type(artifact, record_id)
    if not record_id:
        record_id = _generated_content_id(artifact, record_type, index)
    fields, body = _extract_markdown_fields(section.lines)
    record: dict[str, object] = {
        "schema_version": 1,
        "artifact_type": artifact,
        "record_type": record_type,
        "id": record_id,
        "order": index * 10,
        "title": title,
    }
    record.update(fields)
    if body:
        record["body"] = body
    record.setdefault("status", "draft")
    return record


def _requirements_records_from_markdown(
    sections: list[MarkdownSection],
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    order = 10
    for index, section in enumerate(sections, 1):
        requirement_records, remaining_lines = _requirement_records_from_tables(
            section,
        )
        section_record = _content_record_from_markdown(
            "requirements",
            MarkdownSection(section.level, section.title, remaining_lines),
            index,
        )
        section_record["order"] = order
        records.append(section_record)
        order += 10
        for record in requirement_records:
            record["order"] = order
            records.append(record)
            order += 10
    return records


def _requirement_records_from_tables(
    section: MarkdownSection,
) -> tuple[list[dict[str, object]], list[str]]:
    records: list[dict[str, object]] = []
    remaining_lines: list[str] = []
    index = 0
    while index < len(section.lines):
        table = _parse_markdown_table(section.lines, index)
        if table is None:
            remaining_lines.append(section.lines[index])
            index += 1
            continue
        header, rows, next_index = table
        table_records = _requirement_table_records(section.title, header, rows)
        if not table_records:
            remaining_lines.extend(section.lines[index:next_index])
        else:
            records.extend(table_records)
        index = next_index
    return records, _trim_blank_lines(remaining_lines)


def _parse_markdown_table(
    lines: list[str],
    index: int,
) -> tuple[list[str], list[list[str]], int] | None:
    if index + 1 >= len(lines):
        return None
    header = _markdown_table_cells(lines[index])
    separator = _markdown_table_cells(lines[index + 1])
    if not header or not separator or len(separator) < len(header):
        return None
    if not all(_is_markdown_table_separator(cell) for cell in separator):
        return None
    rows: list[list[str]] = []
    cursor = index + 2
    while cursor < len(lines):
        cells = _markdown_table_cells(lines[cursor])
        if not cells:
            break
        if len(cells) < len(header):
            cells.extend([""] * (len(header) - len(cells)))
        rows.append(cells[: len(header)])
        cursor += 1
    if not rows:
        return None
    return header, rows, cursor


def _markdown_table_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    return [cell.strip() for cell in stripped.strip("|").split("|")]


def _is_markdown_table_separator(cell: str) -> bool:
    return re.fullmatch(r":?-{3,}:?", cell.strip()) is not None


def _requirement_table_records(
    section_title: str,
    header: list[str],
    rows: list[list[str]],
) -> list[dict[str, object]]:
    id_index = _requirement_table_id_index(header, rows)
    if id_index is None:
        return []
    statement_index = _requirement_table_statement_index(header, id_index)
    if statement_index is None:
        return []
    records: list[dict[str, object]] = []
    for row in rows:
        requirement_id = row[id_index].strip()
        if not _looks_like_requirement_id(requirement_id):
            continue
        statement = row[statement_index].strip()
        if not statement:
            continue
        record: dict[str, object] = {
            "schema_version": 1,
            "artifact_type": "requirements",
            "record_type": "requirement",
            "id": requirement_id,
            "title": _requirement_title_from_statement(
                statement,
                fallback=requirement_id,
            ),
            "statement": statement,
            "status": "draft",
        }
        if section_title:
            record["tags"] = [_slug_key(section_title)]
        extras = _requirement_table_extra_fields(
            header,
            row,
            skip_indexes={id_index, statement_index},
        )
        record.update(extras)
        records.append(record)
    return records


def _requirement_table_id_index(
    header: list[str],
    rows: list[list[str]],
) -> int | None:
    for index, value in enumerate(header):
        if _field_key(value) in {"id", "requirement_id", "req_id"}:
            return index
    for index in range(len(header)):
        if any(
            index < len(row) and _looks_like_requirement_id(row[index].strip())
            for row in rows
        ):
            return index
    return None


def _requirement_table_statement_index(
    header: list[str],
    id_index: int,
) -> int | None:
    preferred = {
        "description",
        "statement",
        "requirement",
        "requirement_statement",
        "summary",
    }
    for index, value in enumerate(header):
        if index != id_index and _field_key(value) in preferred:
            return index
    for index in range(len(header)):
        if index != id_index:
            return index
    return None


def _requirement_table_extra_fields(
    header: list[str],
    row: list[str],
    *,
    skip_indexes: set[int],
) -> dict[str, object]:
    fields: dict[str, object] = {}
    extra_lines: list[str] = []
    list_keys = _list_field_keys()
    for index, label in enumerate(header):
        if index in skip_indexes or index >= len(row):
            continue
        value = row[index].strip()
        if not value:
            continue
        key = _field_key(label)
        if key:
            fields[key] = _split_inline_list(value) if key in list_keys else value
        else:
            extra_lines.append(f"**{label.strip()}:** {value}")
    if extra_lines:
        fields["body"] = "\n\n".join(extra_lines)
    return fields


def _requirement_title_from_statement(statement: str, *, fallback: str) -> str:
    title = re.sub(
        r"^(?:the\s+system|users?|parents?|guardians?)\s+shall\s+",
        "",
        statement.strip(),
        flags=re.IGNORECASE,
    )
    title = title.rstrip(".")
    if len(title) > 80:
        title = title[:77].rstrip() + "..."
    return title or fallback


def _implementation_records_from_markdown(
    sections: list[MarkdownSection],
) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    active_phase: int | None = None
    sequence_by_phase: dict[int, int] = {}
    order = 10
    for section in sections:
        phase = _phase_heading_number(section.title)
        if phase is not None and section.level <= 2:
            active_phase = phase
            if section.lines:
                sequence_by_phase[phase] = sequence_by_phase.get(phase, 0) + 1
                records.append(
                    _implementation_record_from_section(
                        section,
                        phase=phase,
                        sequence=sequence_by_phase[phase],
                        order=order,
                    )
                )
                order += 10
            continue
        record_id, _title = _split_record_heading(section.title)
        unit_phase, unit_sequence = _unit_id_parts(record_id)
        phase = unit_phase or active_phase or _phase_heading_number(section.title) or 1
        if unit_sequence is None:
            sequence_by_phase[phase] = sequence_by_phase.get(phase, 0) + 1
            unit_sequence = sequence_by_phase[phase]
        else:
            sequence_by_phase[phase] = max(
                sequence_by_phase.get(phase, 0),
                unit_sequence,
            )
        records.append(
            _implementation_record_from_section(
                section,
                phase=phase,
                sequence=unit_sequence,
                order=order,
            )
        )
        order += 10
    return records


def _implementation_record_from_section(
    section: MarkdownSection,
    *,
    phase: int,
    sequence: int,
    order: int,
) -> dict[str, object]:
    record_id, title = _split_record_heading(section.title)
    if not record_id:
        record_id = f"PH{phase}-C{sequence}"
    fields, body = _extract_markdown_fields(section.lines)
    commit_tasks = _string_list(fields.pop("commit_tasks", []))
    plan_tasks = _string_list(fields.pop("plan_tasks", [])) or commit_tasks
    record: dict[str, object] = {
        "schema_version": 1,
        "artifact_type": "implementation-plan",
        "record_type": "unit",
        "unit_id": record_id,
        "phase": phase,
        "sequence": sequence,
        "order": order,
        "title": title,
        "commit_tasks": commit_tasks or plan_tasks,
        "plan_tasks": plan_tasks or commit_tasks,
    }
    record.update(fields)
    if body:
        record["body"] = body
    return record


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


def _extract_markdown_fields(
    lines: list[str],
    list_keys: set[str] | None = None,
) -> tuple[dict[str, object], str]:
    fields: dict[str, object] = {}
    body_lines: list[str] = []
    list_keys = list_keys or _list_field_keys()
    index = 0
    field_re = re.compile(r"^\*\*(?P<label>[^:*]+):\*\*\s*(?P<value>.*)$")
    while index < len(lines):
        line = lines[index]
        match = field_re.match(line.strip())
        key = _field_key(match.group("label")) if match else ""
        if not match or not key:
            body_lines.append(line)
            index += 1
            continue
        value = match.group("value").strip()
        if key in list_keys:
            values, index = _extract_markdown_list(lines, index, value)
            fields[key] = values
            continue
        if key in {"schema", "automation"}:
            parsed, index = _extract_json_field(lines, index, value)
            fields[key] = parsed
            continue
        fields[key] = value
        index += 1
    return fields, _trim_markdown_lines(body_lines)


def _extract_markdown_list(
    lines: list[str],
    index: int,
    inline_value: str,
) -> tuple[list[str], int]:
    if inline_value:
        return _split_inline_list(inline_value), index + 1
    values: list[str] = []
    cursor = index + 1
    while cursor < len(lines):
        line = lines[cursor]
        if not line.strip() and not values:
            cursor += 1
            continue
        stripped = line.strip()
        if not stripped.startswith("- "):
            break
        values.append(stripped[2:].strip())
        cursor += 1
    return values, cursor


def _extract_json_field(
    lines: list[str],
    index: int,
    inline_value: str,
) -> tuple[object, int]:
    if inline_value:
        try:
            return json.loads(inline_value), index + 1
        except json.JSONDecodeError:
            return inline_value, index + 1
    cursor = index + 1
    while cursor < len(lines) and not lines[cursor].strip():
        cursor += 1
    if cursor >= len(lines) or not lines[cursor].strip().startswith("```"):
        return {}, index + 1
    cursor += 1
    json_lines: list[str] = []
    while cursor < len(lines) and not lines[cursor].strip().startswith("```"):
        json_lines.append(lines[cursor])
        cursor += 1
    if cursor < len(lines):
        cursor += 1
    raw = "\n".join(json_lines).strip()
    if not raw:
        return {}, cursor
    try:
        return json.loads(raw), cursor
    except json.JSONDecodeError:
        return raw, cursor


def _field_key(label: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", label.strip().lower()).strip("_")
    aliases = {
        "acceptance_criteria": "acceptance_criteria",
        "commit_tasks": "commit_tasks",
        "desc": "description",
        "design_sections": "design_sections",
        "id": "id",
        "expected_results": "expected_results",
        "implementation_units": "implementation_units",
        "out_of_scope": "out_of_scope",
        "plan_tasks": "plan_tasks",
        "req_id": "req_id",
        "requirement": "requirement",
        "requirement_id": "requirement_id",
        "requirement_statement": "requirement_statement",
    }
    known = {
        "automation",
        "consequences",
        "consumer",
        "context",
        "decision",
        "description",
        "dependencies",
        "exit_criteria",
        "interfaces",
        "kind",
        "level",
        "paths",
        "personas",
        "preconditions",
        "priority",
        "producer",
        "rationale",
        "requirements",
        "schema",
        "scope",
        "statement",
        "status",
        "steps",
        "suite",
        "summary",
        "verification",
    }
    if normalized in aliases:
        return aliases[normalized]
    return normalized if normalized in known else ""


def _list_field_keys() -> set[str]:
    return {
        "acceptance_criteria",
        "commit_tasks",
        "consequences",
        "dependencies",
        "design_sections",
        "expected_results",
        "exit_criteria",
        "implementation_units",
        "interfaces",
        "out_of_scope",
        "paths",
        "personas",
        "plan_tasks",
        "preconditions",
        "requirements",
        "steps",
        "verification",
    }


def _split_inline_list(value: str) -> list[str]:
    if not value or value.strip().lower() in {"none", "n/a"}:
        return []
    if "," in value:
        return [item.strip() for item in value.split(",") if item.strip()]
    return [value.strip()]


def _document_id(artifact: str) -> str:
    return {
        "requirements": "REQ-DOC",
        "design": "DES-DOC",
        "implementation-plan": "PLAN-DOC",
        "test-plan": "TEST-DOC",
    }[artifact]


def _split_record_heading(title: str) -> tuple[str, str]:
    match = re.match(
        r"^((?:PH\d+-C\d+)|(?:[A-Za-z][A-Za-z0-9_.-]*-\d+))\.\s+(.+)$",
        title.strip(),
    )
    if not match:
        return "", title.strip()
    return match.group(1), match.group(2).strip()


def _content_record_type(artifact: str, record_id: str) -> str:
    if artifact == "requirements":
        if record_id.startswith("REQSEC-"):
            return "section"
        return "requirement" if _looks_like_requirement_id(record_id) else "section"
    if artifact == "design":
        if record_id.startswith("DEC-"):
            return "decision"
        if record_id.startswith("IFACE-"):
            return "interface"
        return "section"
    if artifact == "test-plan":
        if record_id.startswith("TEST-"):
            return "test"
        if record_id.startswith("TS-"):
            return "suite"
        return "suite"
    return "section"


def _generated_content_id(artifact: str, record_type: str, index: int) -> str:
    if artifact == "requirements" and record_type == "requirement":
        return f"REQ-{index:03d}"
    if artifact == "requirements":
        return f"REQSEC-{index:03d}"
    if artifact == "design":
        prefix = {"decision": "DEC", "interface": "IFACE"}.get(record_type, "DES")
        return f"{prefix}-{index:03d}"
    if artifact == "test-plan":
        prefix = "TEST" if record_type == "test" else "TS"
        return f"{prefix}-{index:03d}"
    return f"REC-{index:03d}"


def _looks_like_requirement_id(value: str) -> bool:
    return (
        re.fullmatch(r"[A-Z][A-Z0-9]{1,9}-\d+[A-Z0-9._-]*", value.strip())
        is not None
    )


def _slug_key(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "section"


def _phase_heading_number(title: str) -> int | None:
    match = re.match(r"^(?:Phase\s+)?(\d+)\b|^Phase\s+(\d+)\b", title.strip())
    if not match:
        return None
    value = match.group(1) or match.group(2)
    return int(value)


def _unit_id_parts(unit_id: str) -> tuple[int | None, int | None]:
    match = re.match(r"^PH(\d+)-C(\d+)$", unit_id)
    if not match:
        return None, None
    return int(match.group(1)), int(match.group(2))


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


def _trim_blank_lines(lines: list[str]) -> list[str]:
    trimmed = list(lines)
    while trimmed and not trimmed[0].strip():
        trimmed.pop(0)
    while trimmed and not trimmed[-1].strip():
        trimmed.pop()
    return trimmed


def _trim_markdown_lines(lines: list[str]) -> str:
    return "\n".join(_trim_blank_lines(lines)).strip()


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
