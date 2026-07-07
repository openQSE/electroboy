"""Interactive CLI runtime adapter."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from .base import AgentInvocation, AgentResult
from .generic_cli import GenericCliRuntime
from ..config import RuntimeConfig


CODEX_SESSION_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
)


class InteractiveCliRuntime(GenericCliRuntime):
    """Runtime for configured agent CLIs that take over the terminal."""

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        command = [*self._command(invocation), self._build_prompt(invocation)]
        started_at = time.time()
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
        result = AgentResult(
            ok=ok,
            final_message=(
                "Interactive agent session completed."
                if ok
                else f"Interactive agent exited with code {completed.returncode}."
            ),
            commands=[" ".join(command)],
            error=None if ok else f"exit code {completed.returncode}",
        )
        return self._attach_session_metadata(result, invocation, started_at)

    def _attach_session_metadata(
        self,
        result: AgentResult,
        invocation: AgentInvocation,
        started_at: float,
    ) -> AgentResult:
        return result


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
        if invocation.provider_session_id:
            command.extend(["resume", invocation.provider_session_id])
        return command

    def _interactive_args(self) -> list[str]:
        return [
            arg
            for arg in self.config.args
            if arg not in {"exec", "e", "--json"}
        ]

    def _attach_session_metadata(
        self,
        result: AgentResult,
        invocation: AgentInvocation,
        started_at: float,
    ) -> AgentResult:
        result.provider = "codex"
        result.resumed_session = invocation.provider_session_id is not None
        result.provider_session_id = (
            invocation.provider_session_id
            or self._latest_codex_session_id(started_at)
        )
        return result

    def _latest_codex_session_id(self, started_at: float) -> str | None:
        sessions_dir = self._codex_sessions_dir()
        if not sessions_dir.exists():
            return None
        candidates: list[tuple[float, str]] = []
        for path in sessions_dir.rglob("*.jsonl"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime < started_at - 1:
                continue
            metadata = self._codex_session_metadata(path)
            cwd = metadata.get("cwd")
            if cwd and Path(cwd).resolve() != self.root:
                continue
            session_id = metadata.get("session_id") or self._session_id_from_path(path)
            if session_id:
                candidates.append((mtime, session_id))
        if not candidates:
            return None
        return max(candidates, key=lambda item: item[0])[1]

    def _codex_sessions_dir(self) -> Path:
        codex_home = os.environ.get("CODEX_HOME")
        if codex_home:
            return Path(codex_home) / "sessions"
        return Path(os.environ.get("HOME", str(Path.home()))) / ".codex" / "sessions"

    def _codex_session_metadata(self, path: Path) -> dict[str, str]:
        try:
            with path.open(encoding="utf-8") as stream:
                first_line = stream.readline()
            record = json.loads(first_line)
        except (OSError, json.JSONDecodeError):
            return {}
        payload = record.get("payload")
        if not isinstance(payload, dict):
            return {}
        session_id = payload.get("session_id") or payload.get("id")
        cwd = payload.get("cwd")
        metadata: dict[str, str] = {}
        if isinstance(session_id, str):
            metadata["session_id"] = session_id
        if isinstance(cwd, str):
            metadata["cwd"] = cwd
        return metadata

    def _session_id_from_path(self, path: Path) -> str | None:
        match = CODEX_SESSION_ID_RE.search(path.name)
        return match.group(0) if match else None
