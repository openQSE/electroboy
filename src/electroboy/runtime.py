"""Runtime adapter selection."""

from __future__ import annotations

import os
from pathlib import Path

from .adapters.base import AgentRuntime
from .adapters.codex_exec import CodexExecRuntime
from .adapters.codex_sdk import CodexSdkRuntime
from .adapters.generic_cli import GenericCliRuntime
from .adapters.interactive_cli import CodexInteractiveRuntime, InteractiveCliRuntime
from .adapters.manual import ManualRuntime
from .adapters.opencode_exec import OpenCodeExecRuntime
from .adapters.opencode_interactive import OpenCodeInteractiveRuntime
from .config import PipelineConfig, RuntimeConfig, load_pipeline_config


RUNTIME_CLASSES = {
    "manual": ManualRuntime,
    "generic_cli": GenericCliRuntime,
    "interactive_cli": InteractiveCliRuntime,
    "codex_exec": CodexExecRuntime,
    "codex_interactive": CodexInteractiveRuntime,
    "codex_sdk": CodexSdkRuntime,
    "opencode_exec": OpenCodeExecRuntime,
    "opencode_interactive": OpenCodeInteractiveRuntime,
}


class RuntimeErrorConfig(RuntimeError):
    """Raised when a configured runtime cannot be constructed."""


def runtime_for_role(
    role: str,
    root: Path | str = ".",
    config: PipelineConfig | None = None,
    execution_root: Path | str | None = None,
    backend: str | None = None,
) -> AgentRuntime:
    pipeline_config = config or load_pipeline_config(root)
    selected = backend or os.environ.get("ELECTROBOY_AGENT_BACKEND")
    runtime_config = (
        backend_config(
            selected,
            root,
            interactive=(
                role.replace("-", "_").endswith("_interactive")
                or role == "design_author"
            ),
            config=pipeline_config,
        )
        if selected
        else pipeline_config.runtime_for_role(role)
    )
    return runtime_from_config(runtime_config, execution_root or root)


def runtime_from_config(
    runtime_config: RuntimeConfig,
    root: Path | str = ".",
) -> AgentRuntime:
    try:
        runtime_class = RUNTIME_CLASSES[runtime_config.adapter]
    except KeyError as error:
        raise RuntimeErrorConfig(
            f"unknown runtime adapter: {runtime_config.adapter}"
        ) from error
    return runtime_class(runtime_config, root)


def backend_config(
    backend: str,
    root: Path | str = ".",
    *,
    interactive: bool = False,
    config: PipelineConfig | None = None,
) -> RuntimeConfig:
    """Resolve a GUI-selected provider without role overrides changing providers."""
    if backend not in {"codex", "opencode"}:
        raise RuntimeErrorConfig(f"unknown agent backend: {backend}")
    pipeline = config or load_pipeline_config(root)
    name = f"{backend}-interactive" if interactive else backend
    return pipeline.runtimes[name]


def interactive_command(
    root: Path | str,
    prompt: str,
    *,
    backend: str = "codex",
    session_id: str | None = None,
    sandbox: str = "workspace-write",
) -> list[str]:
    """Build a provider-specific terminal command with an explicit initial prompt."""
    from .adapters.interactive_cli import codex_interactive_command
    from .adapters.opencode_interactive import opencode_interactive_command

    config = backend_config(backend, root, interactive=True)
    if backend == "opencode":
        command = opencode_interactive_command(
            root, executable=config.command, args=config.args
        )
        if session_id:
            command.extend(["--session", session_id])
        if prompt:
            command.extend(["--prompt", prompt])
    else:
        command = codex_interactive_command(
            root, executable=config.command, args=config.args, sandbox=sandbox
        )
        if session_id:
            command.extend(["resume", session_id])
        if prompt:
            command.append(prompt)
    return command


def interactive_environment(
    backend: str, *, sandbox: str = "workspace-write"
) -> dict[str, str]:
    """Keep configuration content out of persisted commands and terminal logs."""
    if backend == "opencode" and sandbox == "read-only":
        from .adapters.opencode_interactive import readonly_config

        return {"OPENCODE_CONFIG_CONTENT": readonly_config()}
    return {}
