"""Progress snapshots and session export formatting."""

from __future__ import annotations

import re
import shlex
import subprocess
from pathlib import Path

from electroboy.models import utc_now
from electroboy.service.commands import electroboy_command
from electroboy.service.sessions import (
    AgentSession,
    _agent_process_env,
    _subprocess_output_text,
)

_electroboy_command = electroboy_command


def _download_name_part(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-._")
    return normalized or "export"


def _progress_once_command(root: Path) -> list[str]:
    return _electroboy_command(root, ["progress", "--once"])


def _progress_snapshot(root: Path | str, timeout: float = 5.0) -> tuple[str, bool]:
    project_root = Path(root).expanduser().resolve()
    try:
        completed = subprocess.run(
            _progress_once_command(project_root),
            cwd=project_root,
            env=_agent_process_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        output = _subprocess_output_text(error.stdout)
        if output and not output.endswith("\n"):
            output += "\n"
        return f"{output}progress command timed out\n", False
    output = completed.stdout or ""
    if completed.returncode != 0:
        if output and not output.endswith("\n"):
            output += "\n"
        output += f"progress command exited with code {completed.returncode}\n"
        return output, False
    return output or "progress: none\n", True


def _markdown_code_block(text: str, language: str = "") -> str:
    body = text.rstrip("\n")
    fence = "```"
    while fence in body:
        fence += "`"
    return f"{fence}{language}\n{body}\n{fence}"


def _session_export_filename(session: AgentSession) -> str:
    kind = _download_name_part(session.kind or "agent")
    timestamp = _download_name_part(utc_now())
    return f"agent-session-{kind}-{timestamp}.md"


def _progress_export_filename() -> str:
    return f"progress-log-{_download_name_part(utc_now())}.md"


def _session_events_markdown(session: AgentSession) -> str:
    events = session.events()
    payload = session.payload()
    lines = [
        "# Agent Session Export",
        "",
        "## Metadata",
        "",
        f"- Session id: `{session.session_id}`",
        f"- Kind: `{session.kind}`",
        f"- Label: {session.label}",
        f"- Status: `{payload.get('status', session.status)}`",
        f"- Created: {session.created_at}",
        f"- Exported: {utc_now()}",
        f"- Working directory: `{session.cwd}`",
        f"- Interactive: `{str(session.interactive).lower()}`",
        f"- Return code: `{session.returncode}`",
        "",
        "### Command",
        "",
        _markdown_code_block(shlex.join(session.command), "console"),
        "",
        "## Transcript",
        "",
    ]
    if not events:
        lines.extend(["No events were recorded.", ""])
        return "\n".join(lines).rstrip() + "\n"

    pending_output: list[str] = []
    pending_start: int | None = None
    pending_end: int | None = None

    def flush_output() -> None:
        nonlocal pending_output, pending_start, pending_end
        if not pending_output:
            return
        title = (
            f"### Output Events {pending_start}-{pending_end}"
            if pending_start != pending_end
            else f"### Output Event {pending_start}"
        )
        lines.extend([title, "", _markdown_code_block("".join(pending_output), "text"), ""])
        pending_output = []
        pending_start = None
        pending_end = None

    for event in events:
        event_id = int(event.get("id", 0) or 0)
        event_type = str(event.get("type") or "event")
        if event_type == "output":
            if pending_start is None:
                pending_start = event_id
            pending_end = event_id
            pending_output.append(str(event.get("text") or ""))
            continue
        flush_output()
        if event_type == "completed":
            lines.extend(
                [
                    f"### Event {event_id}: completed",
                    "",
                    f"- Return code: `{event.get('returncode')}`",
                    "",
                ]
            )
            continue
        text = str(event.get("text") or "")
        lines.extend(
            [
                f"### Event {event_id}: {event_type}",
                "",
                _markdown_code_block(text, "text") if text else "_No event text._",
                "",
            ]
        )
    flush_output()
    return "\n".join(lines).rstrip() + "\n"


def _progress_snapshot_markdown(project_root: Path, text: str, ok: bool) -> str:
    return "\n".join(
        [
            "# Progress Log Export",
            "",
            "## Metadata",
            "",
            f"- Project root: `{project_root}`",
            f"- Exported: {utc_now()}",
            f"- Snapshot status: `{'ok' if ok else 'error'}`",
            "",
            "## Progress",
            "",
            _markdown_code_block(text, "text"),
            "",
        ]
    )
