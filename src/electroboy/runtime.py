"""Runtime adapter selection."""

from __future__ import annotations

from pathlib import Path

from .adapters.base import AgentRuntime
from .adapters.codex_exec import CodexExecRuntime
from .adapters.codex_sdk import CodexSdkRuntime
from .adapters.generic_cli import GenericCliRuntime
from .adapters.manual import ManualRuntime
from .config import PipelineConfig, RuntimeConfig, load_pipeline_config


RUNTIME_CLASSES = {
    "manual": ManualRuntime,
    "generic_cli": GenericCliRuntime,
    "codex_exec": CodexExecRuntime,
    "codex_sdk": CodexSdkRuntime,
}


class RuntimeErrorConfig(RuntimeError):
    """Raised when a configured runtime cannot be constructed."""


def runtime_for_role(
    role: str,
    root: Path | str = ".",
    config: PipelineConfig | None = None,
) -> AgentRuntime:
    pipeline_config = config or load_pipeline_config(root)
    runtime_config = pipeline_config.runtime_for_role(role)
    return runtime_from_config(runtime_config, root)


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
