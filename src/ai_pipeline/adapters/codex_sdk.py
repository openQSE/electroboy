"""Codex SDK runtime adapter placeholder."""

from __future__ import annotations

from .base import AgentInvocation, AgentResult, AgentRuntime


class CodexSdkRuntime(AgentRuntime):
    """Runtime for a future SDK-backed Codex integration."""

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        return AgentResult(
            ok=False,
            final_message="Codex SDK runtime invocation is not implemented yet",
        )
