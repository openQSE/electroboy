"""Implementation-plan parsing helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


REQUIREMENT_ID_RE = re.compile(r"\bREQ-[A-Za-z0-9_.-]+\b")
PHASE_HEADING_RE = re.compile(r"^#{2,}\s+Phase\s+(\d+)\b.*$", re.MULTILINE)
REQUIREMENTS_LINE_RE = re.compile(r"^Requirements:\s*(.+)$", re.MULTILINE)
PATHS_LINE_RE = re.compile(r"^(?:Paths|Files):\s*(.+)$", re.MULTILINE)


@dataclass(frozen=True)
class PlannedPhase:
    """One parsed implementation phase from the plan."""

    number: int
    heading: str
    requirement_ids: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)


def requirement_ids(root: Path) -> set[str]:
    path = root / "docs" / "requirements.md"
    if not path.exists():
        return set()
    return set(REQUIREMENT_ID_RE.findall(path.read_text(encoding="utf-8")))


def planned_phases(root: Path) -> list[PlannedPhase]:
    path = root / "docs" / "implementation-plan.md"
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


def _clean_phase_heading(heading: str) -> str:
    return re.sub(r"^#{2,}\s*", "", heading).strip()


def _split_list(text: str) -> list[str]:
    return [
        item.strip().strip("`")
        for item in text.split(",")
        if item.strip()
    ]


def traceability_errors(root: Path) -> list[str]:
    phases = planned_phases(root)
    known_requirements = requirement_ids(root)
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


def has_traceability(root: Path) -> bool:
    return not traceability_errors(root)
