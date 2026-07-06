"""Codex SDK runtime adapter placeholder."""

from __future__ import annotations

from pathlib import Path

from .base import AgentInvocation, AgentResult, AgentRuntime
from ..config import RuntimeConfig


class CodexSdkRuntime(AgentRuntime):
    """Runtime for a future SDK-backed Codex integration."""

    def __init__(self, config: RuntimeConfig, root: Path | str = ".") -> None:
        self.config = config
        self.root = Path(root).resolve()

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        return AgentResult(
            ok=False,
            final_message="Codex SDK runtime invocation is not implemented yet",
        )
