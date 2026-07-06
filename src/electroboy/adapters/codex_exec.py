"""Codex exec runtime adapter placeholder."""

from __future__ import annotations

import json
from pathlib import Path

from .base import AgentInvocation, AgentResult, AgentRuntime
from .generic_cli import GenericCliRuntime
from ..config import RuntimeConfig


class CodexExecRuntime(GenericCliRuntime):
    """Runtime for `codex exec --json` agent turns."""

    READ_ONLY_ROLES = {
        "design_review",
        "design-review",
        "code_review",
        "code-review",
        "test_review",
        "test-review",
        "validation",
        "validation_review",
        "validation-review",
        "documentation_review",
        "documentation-review",
    }

    def __init__(self, config: RuntimeConfig, root: Path | str = ".") -> None:
        self.config = config
        self.root = Path(root).resolve()

    def _command(self, invocation: AgentInvocation) -> list[str]:
        command = [self.config.command, *self.config.args]
        if "--sandbox" in command or "-s" in command:
            return command
        sandbox = self.config.options.get("sandbox")
        if sandbox is None:
            sandbox = (
                "read-only"
                if invocation.role in self.READ_ONLY_ROLES
                else "workspace-write"
            )
        return [*command, "--sandbox", sandbox]

    def _parse_stdout(self, stdout: str) -> AgentResult:
        events: list[dict[str, object]] = []
        final_message = ""
        issues: list[dict[str, object]] = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                final_message += line + "\n"
                continue
            events.append(event)
            issues.extend(self._extract_issues(event))
            final_message = self._extract_final_message(event, final_message)
        structured = self._extract_final_message_result(final_message)
        if structured is not None:
            issues.extend(structured.issues)
            return AgentResult(
                ok=structured.ok,
                final_message=structured.final_message,
                raw_events=events,
                issues=issues,
                changed_files=structured.changed_files,
                commands=structured.commands,
                error=structured.error,
            )
        return AgentResult(
            ok=True,
            final_message=final_message,
            raw_events=events,
            issues=issues,
        )

    def _extract_final_message(
        self,
        event: dict[str, object],
        current: str,
    ) -> str:
        for key in ("final_message", "message", "text"):
            value = event.get(key)
            if isinstance(value, str):
                return value
        item = event.get("item")
        if isinstance(item, dict):
            for key in ("text", "message"):
                value = item.get(key)
                if isinstance(value, str):
                    return value
        return current

    def _extract_issues(self, event: dict[str, object]) -> list[dict[str, object]]:
        issues = event.get("issues")
        if isinstance(issues, list):
            return [issue for issue in issues if isinstance(issue, dict)]
        item = event.get("item")
        if isinstance(item, dict):
            nested = item.get("issues")
            if isinstance(nested, list):
                return [issue for issue in nested if isinstance(issue, dict)]
        return []

    def _extract_final_message_result(self, final_message: str) -> AgentResult | None:
        try:
            parsed = json.loads(final_message)
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        issues = parsed.get("issues")
        if not isinstance(issues, list):
            issues = []
        return AgentResult(
            ok=bool(parsed.get("ok", True)),
            final_message=str(parsed.get("final_message", parsed.get("message", ""))),
            issues=[issue for issue in issues if isinstance(issue, dict)],
            raw_events=[parsed],
            changed_files=list(parsed.get("changed_files", [])),
            commands=list(parsed.get("commands", [])),
            error=parsed.get("error"),
        )
