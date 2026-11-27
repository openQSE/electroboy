"""Agent executable discovery and immutable launch selections."""

from __future__ import annotations

import json
import os
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from electroboy.adapters.base import AgentRuntime
from electroboy.runtime import backend_config, runtime_for_role

from .sessions import AgentSession, AgentSessionError


def _provider_for_binary(binary: object) -> str:
    """Recognize provider commands and Codex wrapper names, never paths."""
    if isinstance(binary, str) and "\0" not in binary and Path(binary).name == binary:
        if binary in {"codex", "opencode"}:
            return binary
        # Codex's sandbox helper cannot run agent conversations.
        if binary.startswith("codex-") and binary not in {
            "codex-", "codex-linux-sandbox",
        }:
            return "codex"
    raise ValueError("Unknown backend binary.")


def _discover_agent_binaries() -> set[str]:
    binaries = set()
    for directory in os.get_exec_path():
        try:
            with os.scandir(directory or os.curdir) as entries:
                for entry in entries:
                    try:
                        if (
                            _provider_for_binary(entry.name)
                            and shutil.which(entry.name) is not None
                        ):
                            binaries.add(entry.name)
                    except (OSError, ValueError):
                        continue
        except OSError:
            continue
    return binaries


@dataclass(frozen=True)
class AgentSelection:
    """Immutable selection captured for an agent or background job."""

    binary: str
    provider: str
    executable: str


def migrate_agent_selection(metadata: dict[str, object]) -> dict[str, object]:
    """Normalize recorded executable identity without guessing missing values."""
    result = dict(metadata)
    binary = str(result.get("provider_binary") or "")
    if not binary:
        binary = Path(str(result.get("provider_executable") or "")).name
    provider = str(result.get("provider") or "")
    try:
        derived = _provider_for_binary(binary)
        if provider and provider != derived:
            raise ValueError("Provider does not match executable")
    except ValueError:
        result["provider_binary"] = ""
        result["selection_status"] = "unresolved"
    else:
        result["provider"] = derived
        result["provider_binary"] = binary
        result["selection_status"] = "resolved"
    return result


def resume_agent_binary(
    records: Iterable[dict[str, object] | None], requested: str,
) -> str:
    """Choose a recorded executable or require an explicit legacy choice."""
    binaries: set[str] = set()
    providers: set[str] = set()
    unresolved = False
    for record in records:
        if not record:
            continue
        metadata = record.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else record
        provider = str(metadata.get("provider") or "")
        if provider:
            providers.add(provider)
        binary = str(metadata.get("provider_binary") or "")
        if binary:
            binaries.add(binary)
        elif metadata.get("selection_status") == "unresolved":
            unresolved = True
    if len(binaries) > 1:
        raise AgentSessionError("Session records disagree about the executable.")
    if binaries:
        binary = next(iter(binaries))
        if requested and requested != binary:
            raise AgentSessionError("Agent session uses a different executable.")
        return binary
    if requested and providers and providers != {_provider_for_binary(requested)}:
        raise AgentSessionError("Agent session uses a different provider.")
    if unresolved and not requested:
        raise AgentSessionError("Select the executable used by this session before resuming.")
    return requested


class AgentBackend:
    """Discover agent executables and prepare immutable selections."""

    def __init__(
        self,
        lock,
        roots: Callable[[], Iterable[Path]],
        state_path: Path | None = None,
    ) -> None:
        self.lock = lock
        self.roots = roots
        self.binary = "codex"
        if state_path and state_path.exists():
            try:
                saved = json.loads(state_path.read_text(encoding="utf-8"))
                if isinstance(saved, dict):
                    binary = saved.get("binary")
                    _provider_for_binary(binary)
                    self.binary = binary
            except (OSError, ValueError, TypeError):
                pass

    def payload(self, root: Path | None = None, binary: str = "") -> dict[str, object]:
        selected = binary or self.binary
        provider = _provider_for_binary(selected)
        discovered = _discover_agent_binaries() | {selected}
        binaries = sorted(discovered)
        roots = [root] if root is not None else list(self.roots()) or [Path(".")]
        return {
            "backend": selected,
            "provider": provider,
            "backends": binaries,
            "availability": {
                item: all(
                    shutil.which(self._command(item, project, interactive)) is not None
                    for project in roots for interactive in (False, True)
                )
                for item in binaries
            },
        }

    def _command(self, binary: str, root: Path, interactive: bool) -> str:
        if binary != _provider_for_binary(binary):
            return binary
        return backend_config(binary, root, interactive=interactive).command

    def resolve(self, binary: str, root: Path) -> AgentSelection:
        """Validate and capture a selection independently of other agents."""
        provider = _provider_for_binary(binary)
        command = self._command(binary, root, interactive=True)
        executable = shutil.which(command)
        if executable is None:
            raise AgentSessionError(f"Backend executable is unavailable: {command}")
        return AgentSelection(binary, provider, executable)

    def prepare_selection(self, session: AgentSession, selection: AgentSelection) -> None:
        """Prepare a session without binding it to later default changes."""
        session.metadata["provider"] = selection.provider
        session.metadata["provider_binary"] = selection.binary
        session.metadata["provider_executable"] = selection.executable
        session.metadata["selection_status"] = "resolved"
        session.environment["ELECTROBOY_AGENT_BACKEND"] = selection.provider
        session.environment["ELECTROBOY_AGENT_EXECUTABLE"] = (
            selection.binary if selection.binary != selection.provider else ""
        )
        command = backend_config(selection.provider, session.cwd, interactive=True).command
        if selection.binary != selection.provider and session.command and session.command[0] == command:
            session.command = [selection.binary, *session.command[1:]]

    def selected_runtime_factory(self, selection: AgentSelection):
        """Capture a selection for the lifetime of a background job."""
        def factory(role: str, root: Path) -> AgentRuntime:
            return runtime_for_role(
                role, root, backend=selection.provider,
                executable=(selection.binary if selection.binary != selection.provider else None),
            )

        return factory
