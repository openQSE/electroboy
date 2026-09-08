"""Codex exec runtime adapter placeholder."""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..config import RuntimeConfig
from .base import AgentInvocation, AgentResult
from .generic_cli import GenericCliRuntime
from .interactive_cli import CodexInteractiveRuntime


class CodexExecRuntime(GenericCliRuntime):
    """Runtime for `codex exec --json` agent turns."""

    INTERACTIVE_ROLES = {
        "design_author",
        "design-author",
        "coding_interactive",
        "coding-interactive",
    }

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
        "corkboard_generation",
        "corkboard-generation",
        "code_learner_initialize",
        "code-learner-initialize",
        "code_learner_analysis",
        "code-learner-analysis",
        "code_learner_course",
        "code-learner-course",
    }

    def __init__(self, config: RuntimeConfig, root: Path | str = ".") -> None:
        self.config = config
        self.root = Path(root).resolve()

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        if invocation.role in self.INTERACTIVE_ROLES:
            return CodexInteractiveRuntime(self.config, self.root).invoke(invocation)
        if invocation.provider_session_id and invocation.fork_provider_session_id:
            raise ValueError("an invocation cannot resume and fork a Codex session")
        result = super().invoke(invocation)
        result.provider = "codex"
        result.resumed_session = invocation.provider_session_id is not None
        if result.provider_session_id is None and invocation.provider_session_id:
            result.provider_session_id = invocation.provider_session_id
        if (
            invocation.role in {"corkboard_generation", "corkboard-generation"}
            and not result.structured_output
        ):
            try:
                payload = json.loads(result.final_message)
            except json.JSONDecodeError:
                pass
            else:
                if isinstance(payload, dict):
                    result.structured_output = True
                    result.structured_payload = payload
        return result

    def _command(self, invocation: AgentInvocation) -> list[str]:
        command = [self.config.command, *self.config.args]
        if (
            invocation.role in {"corkboard_generation", "corkboard-generation"}
            and not any("model_reasoning_summary" in part for part in command)
        ):
            command.extend(["-c", 'model_reasoning_summary="concise"'])
        if "--sandbox" not in command and "-s" not in command:
            sandbox = self.config.options.get("sandbox")
            if sandbox is None:
                if invocation.progress_path:
                    sandbox = "workspace-write"
                else:
                    sandbox = (
                        "read-only"
                        if invocation.role in self.READ_ONLY_ROLES
                        else "workspace-write"
                    )
            command.extend(["--sandbox", sandbox])
        if invocation.provider_session_id:
            command.extend(["resume", invocation.provider_session_id, "-"])
        elif invocation.fork_provider_session_id:
            command.extend(["fork", invocation.fork_provider_session_id, "-"])
        return command

    def _parse_stdout(self, stdout: str) -> AgentResult:
        events: list[dict[str, object]] = []
        final_message = ""
        issues: list[dict[str, object]] = []
        provider_session_id: str | None = None
        for line in stdout.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                final_message += line + "\n"
                continue
            events.append(event)
            if (
                event.get("type") == "thread.started"
                and isinstance(event.get("thread_id"), str)
            ):
                provider_session_id = str(event["thread_id"])
            issues.extend(self._extract_issues(event))
            final_message = self._extract_final_message(event, final_message)
        structured = self._extract_final_message_result(final_message)
        if structured is not None:
            issues.extend(structured.issues)
            return AgentResult(
                ok=structured.ok,
                final_message=structured.final_message,
                raw_events=[*events, *structured.raw_events],
                issues=issues,
                changed_files=structured.changed_files,
                created_files=structured.created_files,
                commands=structured.commands,
                commit_message=structured.commit_message,
                error=structured.error,
                provider="codex",
                provider_session_id=provider_session_id,
                structured_output=structured.structured_output,
                structured_payload=structured.structured_payload,
            )
        return AgentResult(
            ok=True,
            final_message=final_message,
            raw_events=events,
            issues=issues,
            provider="codex",
            provider_session_id=provider_session_id,
        )

    @classmethod
    def _activity_from_stdout_line(cls, line: str) -> str:
        """Translate one Codex JSONL event into user-facing activity."""

        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return ""
        if not isinstance(event, dict):
            return ""
        item = event.get("item")
        if not isinstance(item, dict):
            return ""
        item_type = str(item.get("type") or "").strip().lower()
        if item_type in {"agent_message", "reasoning"}:
            text = item.get("text") or item.get("message") or item.get("summary")
            if isinstance(text, list):
                text = " ".join(
                    str(entry.get("text") or "")
                    for entry in text
                    if isinstance(entry, dict)
                )
            return cls._concise_activity(text)
        if item_type == "command_execution":
            return cls._command_activity(item)
        return ""

    @staticmethod
    def _concise_activity(value: object) -> str:
        text = " ".join(str(value or "").split())
        if not text or text.startswith(("{", "[", "```")):
            return ""
        if len(text) > 240:
            text = text[:237].rstrip() + "..."
        return text

    @classmethod
    def _command_activity(cls, item: dict[str, object]) -> str:
        command = item.get("command")
        if isinstance(command, list):
            command_text = " ".join(str(part) for part in command)
        else:
            command_text = str(command or "")
        if not command_text:
            return ""
        if re.search(r"(^|\s)(cat|head|tail|sed|rg)(\s|$)", command_text):
            return "Reading source material and identifying corkboard entries."
        return "Inspecting source material for corkboard structure."

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
        # A final agent message may itself be a domain JSON object. Only unwrap
        # the explicit AgentResult envelope; otherwise preserve the message for
        # the workflow-specific parser.
        if "final_message" not in parsed:
            return None
        issues = parsed.get("issues")
        if not isinstance(issues, list):
            issues = []
        commit_message = parsed.get("commit_message")
        return AgentResult(
            ok=bool(parsed.get("ok", True)),
            final_message=str(parsed.get("final_message", parsed.get("message", ""))),
            issues=[issue for issue in issues if isinstance(issue, dict)],
            raw_events=[parsed],
            changed_files=list(parsed.get("changed_files", [])),
            created_files=list(parsed.get("created_files", [])),
            commands=list(parsed.get("commands", [])),
            commit_message=(
                commit_message if isinstance(commit_message, str) else None
            ),
            error=parsed.get("error"),
            structured_output=True,
            structured_payload=parsed,
        )
