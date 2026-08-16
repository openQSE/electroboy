"""Structured event extraction from command-line progress snapshots."""

from __future__ import annotations

import re


_ISSUE_LINE = re.compile(
    r"^\s*ISSUE\s+FOUND\s*-\s*(BLOCKER|MAJOR|MINOR)\s*-\s*(.+?)\s*$",
    re.IGNORECASE,
)


def progress_issue_events(text: str) -> list[dict[str, str]]:
    """Extract structured review findings from a progress snapshot."""

    events: list[dict[str, str]] = []
    for line in text.splitlines():
        match = _ISSUE_LINE.match(line)
        if match is None:
            continue
        events.append(
            {
                "type": "issue",
                "severity": match.group(1).lower(),
                "summary": match.group(2).strip(),
            }
        )
    return events
