"""Generic CLI runtime adapter placeholder."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from .base import AgentInvocation, AgentResult, AgentRuntime
from ..config import RuntimeConfig


class GenericCliRuntime(AgentRuntime):
    """Runtime for configured non-interactive agent CLI tools."""

    def __init__(self, config: RuntimeConfig, root: Path | str = ".") -> None:
        self.config = config
        self.root = Path(root).resolve()

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        command = self._command(invocation)
        prompt = self._build_prompt(invocation)
        timeout = float(self.config.options.get("timeout", "300"))
        try:
            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                cwd=self.root,
                env=self._runtime_env(),
                timeout=timeout,
                check=False,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as error:
            return AgentResult(
                ok=False,
                final_message=f"Agent runtime failed: {error}",
                raw_events=[{"error": str(error)}],
                commands=[" ".join(command)],
                error=str(error),
            )
        result = self._parse_stdout(completed.stdout)
        result.ok = result.ok and completed.returncode == 0
        if completed.returncode != 0:
            result.error = completed.stderr.strip() or f"exit code {completed.returncode}"
        if completed.stderr.strip():
            result.raw_events.append({"stream": "stderr", "text": completed.stderr})
        result.commands.append(" ".join(command))
        return result

    def _command(self, invocation: AgentInvocation) -> list[str]:
        return [self.config.command, *self.config.args]

    def _runtime_env(self) -> dict[str, str]:
        allowlist = self.config.env or ["PATH"]
        return {
            name: os.environ[name]
            for name in allowlist
            if name in os.environ
        }

    def _build_prompt(self, invocation: AgentInvocation) -> str:
        context = "\n".join(f"- {path}" for path in invocation.context_paths)
        if context:
            return f"{invocation.prompt}\n\nContext paths:\n{context}\n"
        return invocation.prompt

    def _parse_stdout(self, stdout: str) -> AgentResult:
        text = stdout.strip()
        if not text:
            return AgentResult(ok=True, final_message="")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return AgentResult(ok=True, final_message=stdout)
        if isinstance(parsed, dict):
            commit_message = parsed.get("commit_message")
            provider = parsed.get("provider")
            provider_session_id = parsed.get("provider_session_id")
            return AgentResult(
                ok=bool(parsed.get("ok", True)),
                final_message=str(parsed.get("final_message", parsed.get("message", ""))),
                issues=list(parsed.get("issues", [])),
                raw_events=[parsed],
                changed_files=list(parsed.get("changed_files", [])),
                created_files=list(parsed.get("created_files", [])),
                commands=list(parsed.get("commands", [])),
                commit_message=(
                    commit_message if isinstance(commit_message, str) else None
                ),
                error=parsed.get("error"),
                provider=provider if isinstance(provider, str) else None,
                provider_session_id=(
                    provider_session_id
                    if isinstance(provider_session_id, str)
                    else None
                ),
                resumed_session=bool(parsed.get("resumed_session", False)),
            )
        return AgentResult(ok=True, final_message=stdout, raw_events=[{"value": parsed}])
