"""OpenCode JSON event adapter for noninteractive workflow turns."""

from __future__ import annotations

import json

from .base import AgentResult
from .generic_cli import GenericCliRuntime


class OpenCodeExecRuntime(GenericCliRuntime):
    def invoke(self, invocation):
        if invocation.provider_session_id and invocation.fork_provider_session_id:
            raise ValueError("cannot resume and fork an OpenCode session together")
        if invocation.role.replace("-", "_") in {"design_author", "coding_interactive"}:
            from .opencode_interactive import OpenCodeInteractiveRuntime

            return OpenCodeInteractiveRuntime(self.config, self.root).invoke(invocation)
        result = super().invoke(invocation)
        result.provider = "opencode"
        result.resumed_session = bool(invocation.provider_session_id)
        result.provider_session_id = (
            result.provider_session_id or invocation.provider_session_id
        )
        if invocation.output_schema and result.ok and not result.structured_output:
            result.ok = False
            result.error = "OpenCode did not return the required JSON result."
        return result

    def _command(self, invocation):
        command = [
            self.config.command,
            "run",
            "--standalone",
            "--format",
            "json",
            *self.config.args,
        ]
        if invocation.provider_session_id:
            command.extend(["--session", invocation.provider_session_id])
        if invocation.fork_provider_session_id:
            command.extend(["--session", invocation.fork_provider_session_id, "--fork"])
        return command

    def _build_prompt(self, invocation):
        prompt = super()._build_prompt(invocation)
        if invocation.output_schema:
            prompt += (
                "\nReturn only a JSON object matching this schema:\n"
                + json.dumps(invocation.output_schema)
            )
        return prompt

    def _parse_stdout(self, stdout):
        events, texts, errors = [], {}, []
        session_id = None
        for line in stdout.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                errors.append("Invalid OpenCode JSON event: " + line[:200])
                continue
            if not isinstance(event, dict):
                continue
            events.append(event)
            session_id = event.get("sessionID") or session_id
            part = event.get("part") or {}
            if event.get("type") == "text" and isinstance(part, dict):
                text = part.get("text")
                if isinstance(text, str):
                    message_id = str(part.get("messageID") or "final")
                    parts = texts.setdefault(message_id, {})
                    parts[str(part.get("id") or len(parts))] = text
            if event.get("type") == "error":
                errors.append(str(event.get("error") or event))
        final_parts = list(texts.values())[-1] if texts else {}
        message = "\n".join(final_parts.values()).strip()
        # A result can be a review envelope or a domain JSON object.
        json_text = message
        if json_text.startswith("```") and json_text.endswith("```"):
            json_text = json_text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        try:
            payload = json.loads(json_text)
        except json.JSONDecodeError:
            payload = None
        if isinstance(payload, dict):
            result = super()._parse_stdout(json.dumps(payload))
            if "final_message" not in payload:
                result.final_message = json_text
        else:
            result = AgentResult(ok=bool(message), final_message=message)
        result.raw_events = events
        result.provider = "opencode"
        result.provider_session_id = session_id
        if errors or not message:
            result.ok = False
            result.error = "; ".join(errors) or "OpenCode returned no final message."
        return result

    @staticmethod
    def _activity_from_stdout_line(line):
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            return ""
        if not isinstance(event, dict):
            return ""
        part = event.get("part") or {}
        if not isinstance(part, dict):
            return ""
        if event.get("type") in {"text", "reasoning"}:
            return " ".join(str(part.get("text") or "").split())[:240]
        if event.get("type") == "tool_use":
            return "Using " + str(part.get("tool") or "tool")
        return ""
