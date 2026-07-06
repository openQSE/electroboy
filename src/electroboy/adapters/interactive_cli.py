"""Interactive CLI runtime adapter."""

from __future__ import annotations

import subprocess
from pathlib import Path

from .base import AgentInvocation, AgentResult
from .generic_cli import GenericCliRuntime
from ..config import RuntimeConfig


class InteractiveCliRuntime(GenericCliRuntime):
    """Runtime for configured agent CLIs that take over the terminal."""

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        command = [*self._command(invocation), self._build_prompt(invocation)]
        try:
            completed = subprocess.run(
                command,
                cwd=self.root,
                env=self._runtime_env(),
                check=False,
            )
        except (FileNotFoundError, OSError) as error:
            return AgentResult(
                ok=False,
                final_message=f"Agent runtime failed: {error}",
                raw_events=[{"error": str(error)}],
                commands=[" ".join(command)],
                error=str(error),
            )
        ok = completed.returncode == 0
        return AgentResult(
            ok=ok,
            final_message=(
                "Interactive agent session completed."
                if ok
                else f"Interactive agent exited with code {completed.returncode}."
            ),
            commands=[" ".join(command)],
            error=None if ok else f"exit code {completed.returncode}",
        )


class CodexInteractiveRuntime(InteractiveCliRuntime):
    """Interactive runtime for authoring turns in the Codex CLI."""

    def __init__(self, config: RuntimeConfig, root: Path | str = ".") -> None:
        self.config = config
        self.root = Path(root).resolve()

    def _command(self, invocation: AgentInvocation) -> list[str]:
        command = [self.config.command, *self._interactive_args()]
        if "--cd" not in command and "-C" not in command:
            command.extend(["--cd", str(self.root)])
        if "--sandbox" not in command and "-s" not in command:
            sandbox = self.config.options.get("sandbox", "workspace-write")
            command.extend(["--sandbox", sandbox])
        return command

    def _interactive_args(self) -> list[str]:
        return [
            arg
            for arg in self.config.args
            if arg not in {"exec", "e", "--json"}
        ]
