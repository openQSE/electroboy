"""Implementation-plan parsing helpers."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path


REQUIREMENT_ID_RE = re.compile(r"\bREQ-[A-Za-z0-9_.-]+\b")
REQUIREMENT_REF_RE = re.compile(r"\b[A-Z]+-\d+\b")
PHASE_HEADING_RE = re.compile(r"^#{2,}\s+Phase\s+(\d+)\b.*$", re.MULTILINE)
COMMIT_SEQUENCE_HEADING_RE = re.compile(
    r"^#{3,}\s+Phase\s+(\d+)\s+Commit Sequence\b.*$",
    re.MULTILINE,
)
TASK_HEADING_RE = re.compile(r"^\d+\.\s+(PH\d+\.\d+)\s+(.+)$", re.MULTILINE)
REQUIREMENTS_LINE_RE = re.compile(r"^Requirements:\s*(.+)$", re.MULTILINE)
PATHS_LINE_RE = re.compile(r"^(?:Paths|Files):\s*(.+)$", re.MULTILINE)
REQS_LINE_RE = re.compile(r"^\s*-\s+Reqs:\s*(.+)$", re.MULTILINE)
MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
COMMIT_UNIT_ID_RE = re.compile(r"^PH(?P<phase>\d+)-C(?P<sequence>\d+)$")


@dataclass(frozen=True)
class PlannedPhase:
    """One parsed implementation phase from the plan."""

    number: int
    heading: str
    requirement_ids: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ImplementationUnit:
    """One machine-readable implementation-plan unit."""

    unit_id: str
    phase: int
    sequence: int
    title: str
    primary_repos: list[str] = field(default_factory=list)
    plan_tasks: list[str] = field(default_factory=list)
    requirements: list[str] = field(default_factory=list)
    design_sections: list[str] = field(default_factory=list)
    scope: str = ""
    exit_criteria: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    dependencies: list[str] = field(default_factory=list)
    source_plan: str = "docs/implementation-plan.md"
    source_type: str = "markdown-commit-breakdown"
    schema_version: int = 1

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "ImplementationUnit":
        return cls(
            unit_id=str(data.get("unit_id", "")),
            phase=int(data.get("phase", 0)),
            sequence=int(data.get("sequence", 0)),
            title=str(data.get("title", "")),
            primary_repos=_string_list(data.get("primary_repos")),
            plan_tasks=_string_list(data.get("plan_tasks")),
            requirements=_string_list(data.get("requirements")),
            design_sections=_string_list(data.get("design_sections")),
            scope=str(data.get("scope", "")),
            exit_criteria=_string_list(data.get("exit_criteria")),
            paths=_string_list(data.get("paths")),
            dependencies=_string_list(data.get("dependencies")),
            source_plan=str(data.get("source_plan", "docs/implementation-plan.md")),
            source_type=str(data.get("source_type", "jsonl")),
            schema_version=int(data.get("schema_version", 1)),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "unit_id": self.unit_id,
            "phase": self.phase,
            "sequence": self.sequence,
            "title": self.title,
            "primary_repos": list(self.primary_repos),
            "plan_tasks": list(self.plan_tasks),
            "requirements": list(self.requirements),
            "design_sections": list(self.design_sections),
            "scope": self.scope,
            "exit_criteria": list(self.exit_criteria),
            "paths": list(self.paths),
            "dependencies": list(self.dependencies),
            "source_plan": self.source_plan,
            "source_type": self.source_type,
        }


def requirement_ids(
    root: Path,
    requirements_path: str = "docs/requirements.md",
) -> set[str]:
    path = root / requirements_path
    if not path.exists():
        return set()
    return set(REQUIREMENT_ID_RE.findall(path.read_text(encoding="utf-8")))


def planned_phases(
    root: Path,
    plan_path: str = "docs/implementation-plan.md",
) -> list[PlannedPhase]:
    path = root / plan_path
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    matches = list(PHASE_HEADING_RE.finditer(text))
    phases: list[PlannedPhase] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end]
        requirement_line = REQUIREMENTS_LINE_RE.search(body)
        ids = (
            REQUIREMENT_ID_RE.findall(requirement_line.group(1))
            if requirement_line
            else []
        )
        paths = [
            path
            for paths_line in PATHS_LINE_RE.findall(body)
            for path in _split_list(paths_line)
        ]
        phases.append(
            PlannedPhase(
                number=int(match.group(1)),
                heading=_clean_phase_heading(match.group(0)),
                requirement_ids=ids,
                paths=paths,
            )
        )
    return phases


def implementation_plan_jsonl_path(
    plan_path: str = "docs/implementation-plan.md",
) -> str:
    path = Path(plan_path)
    if path.suffix == ".md":
        return str(path.with_suffix(".jsonl"))
    return f"{plan_path}.jsonl"


def ensure_implementation_plan_jsonl(
    root: Path,
    plan_path: str = "docs/implementation-plan.md",
    jsonl_path: str | None = None,
) -> tuple[list[ImplementationUnit], bool]:
    """Read or create a structured implementation plan.

    Returns the parsed units and whether the JSONL file was created.
    """

    resolved_jsonl = jsonl_path or implementation_plan_jsonl_path(plan_path)
    path = root / resolved_jsonl
    if path.exists():
        return read_implementation_units(root, resolved_jsonl), False

    units = implementation_units_from_markdown(root, plan_path)
    if not units:
        return [], False

    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(unit.to_dict(), sort_keys=True)
        for unit in units
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return units, True


def read_implementation_units(
    root: Path,
    jsonl_path: str = "docs/implementation-plan.jsonl",
) -> list[ImplementationUnit]:
    path = root / jsonl_path
    if not path.exists():
        return []
    units: list[ImplementationUnit] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        data = json.loads(line)
        if isinstance(data, dict):
            unit = ImplementationUnit.from_dict(data)
            if unit.unit_id and unit.phase > 0:
                units.append(unit)
    return units


def implementation_units_from_markdown(
    root: Path,
    plan_path: str = "docs/implementation-plan.md",
) -> list[ImplementationUnit]:
    path = root / plan_path
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    task_details = _task_details_by_id(text)
    design_sections = _design_sections_by_phase(text)
    units = _commit_breakdown_units(text, plan_path, task_details, design_sections)
    if units:
        return units
    return _fallback_phase_units(root, plan_path)


def _commit_breakdown_units(
    text: str,
    plan_path: str,
    task_details: dict[str, dict[str, object]],
    design_sections: dict[int, list[str]],
) -> list[ImplementationUnit]:
    matches = list(COMMIT_SEQUENCE_HEADING_RE.finditer(text))
    units: list[ImplementationUnit] = []
    prior_by_phase: dict[int, list[str]] = {}
    for index, match in enumerate(matches):
        phase = int(match.group(1))
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        next_phase_body = re.search(r"^##\s+Phase\s+\d+\b", text[start:end], re.MULTILINE)
        if next_phase_body:
            end = start + next_phase_body.start()
        for row in _markdown_table_rows(text[start:end]):
            cells = _markdown_table_cells(row)
            if len(cells) < 4 or cells[0].lower() == "commit id":
                continue
            if all(set(cell) <= {"-"} for cell in cells):
                continue
            unit_match = COMMIT_UNIT_ID_RE.match(cells[0])
            if not unit_match:
                continue
            unit_phase = int(unit_match.group("phase"))
            sequence = int(unit_match.group("sequence"))
            if unit_phase != phase:
                phase = unit_phase
            plan_tasks = _split_list(cells[2])
            requirements = _unique_strings(
                requirement
                for task in plan_tasks
                for requirement in _string_list(
                    task_details.get(task, {}).get("requirements")
                )
            )
            task_titles = [
                str(task_details.get(task, {}).get("title") or "").strip()
                for task in plan_tasks
            ]
            title = "; ".join(title for title in task_titles if title)
            scope = _clean_inline_markdown(cells[3])
            if not title:
                title = _title_from_scope(scope)
            dependencies = list(prior_by_phase.get(phase, []))
            units.append(
                ImplementationUnit(
                    unit_id=cells[0],
                    phase=phase,
                    sequence=sequence,
                    title=title,
                    primary_repos=_split_list(cells[1]),
                    plan_tasks=plan_tasks,
                    requirements=requirements,
                    design_sections=design_sections.get(phase, []),
                    scope=scope,
                    exit_criteria=[scope] if scope else [],
                    dependencies=dependencies,
                    source_plan=plan_path,
                    source_type="markdown-commit-breakdown",
                )
            )
            prior_by_phase.setdefault(phase, []).append(cells[0])
    return units


def _fallback_phase_units(root: Path, plan_path: str) -> list[ImplementationUnit]:
    units: list[ImplementationUnit] = []
    for phase in planned_phases(root, plan_path):
        units.append(
            ImplementationUnit(
                unit_id=f"PH{phase.number}-C01",
                phase=phase.number,
                sequence=1,
                title=phase.heading,
                plan_tasks=[f"PH{phase.number}"],
                requirements=phase.requirement_ids,
                scope=phase.heading,
                paths=phase.paths,
                source_plan=plan_path,
                source_type="markdown-phase-fallback",
            )
        )
    return units


def _task_details_by_id(text: str) -> dict[str, dict[str, object]]:
    details: dict[str, dict[str, object]] = {}
    matches = list(TASK_HEADING_RE.finditer(text))
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        body = text[start:end]
        reqs_match = REQS_LINE_RE.search(body)
        requirements = []
        if reqs_match and reqs_match.group(1).strip().lower() != "none":
            requirements = REQUIREMENT_REF_RE.findall(reqs_match.group(1))
        details[match.group(1)] = {
            "title": _clean_inline_markdown(match.group(2)),
            "requirements": requirements,
        }
    return details


def _design_sections_by_phase(text: str) -> dict[int, list[str]]:
    sections: dict[int, list[str]] = {}
    for row in _markdown_table_rows(text):
        raw_cells = [
            cell.strip()
            for cell in row.strip().strip("|").split("|")
        ]
        if len(raw_cells) < 3:
            continue
        phase_cell = _clean_inline_markdown(raw_cells[0])
        if phase_cell.lower() == "phase":
            continue
        phase_match = re.match(r"Phase\s+(\d+)\b", phase_cell)
        if not phase_match:
            continue
        sections[int(phase_match.group(1))] = [
            _clean_inline_markdown(match)
            for match in MARKDOWN_LINK_RE.findall(raw_cells[1])
        ]
    return sections


def _markdown_table_rows(text: str) -> list[str]:
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("|") and line.strip().endswith("|")
    ]


def _markdown_table_cells(row: str) -> list[str]:
    return [
        _clean_inline_markdown(cell)
        for cell in row.strip().strip("|").split("|")
    ]


def _clean_phase_heading(heading: str) -> str:
    return re.sub(r"^#{2,}\s*", "", heading).strip()


def _clean_inline_markdown(text: str) -> str:
    text = MARKDOWN_LINK_RE.sub(r"\1", text)
    text = text.replace("`", "")
    return re.sub(r"\s+", " ", text).strip()


def _title_from_scope(scope: str) -> str:
    return scope.split(".", 1)[0].strip() or scope


def _split_list(text: str) -> list[str]:
    return [
        _clean_inline_markdown(item)
        for item in text.split(",")
        if item.strip()
    ]


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _unique_strings(values: object) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        text = str(value).strip()
        if text and text not in seen:
            seen.add(text)
            unique.append(text)
    return unique


def traceability_errors(
    root: Path,
    requirements_path: str = "docs/requirements.md",
    plan_path: str = "docs/implementation-plan.md",
) -> list[str]:
    phases = planned_phases(root, plan_path)
    known_requirements = requirement_ids(root, requirements_path)
    errors: list[str] = []
    if not phases:
        errors.append("implementation plan has no phase headings")
        return errors
    if not known_requirements:
        errors.append("requirements document has no REQ-* identifiers")
    for phase in phases:
        if not phase.requirement_ids:
            errors.append(f"phase {phase.number} has no Requirements line")
            continue
        unknown = sorted(set(phase.requirement_ids) - known_requirements)
        for requirement_id in unknown:
            errors.append(
                f"phase {phase.number} references unknown requirement {requirement_id}"
            )
    return errors


def has_traceability(
    root: Path,
    requirements_path: str = "docs/requirements.md",
    plan_path: str = "docs/implementation-plan.md",
) -> bool:
    return not traceability_errors(root, requirements_path, plan_path)
