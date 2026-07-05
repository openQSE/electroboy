"""Manual runtime adapter placeholder."""

from __future__ import annotations

from .base import AgentInvocation, AgentResult, AgentRuntime


class ManualRuntime(AgentRuntime):
    """Runtime that records prompts for a human-managed agent turn."""

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        return AgentResult(
            ok=False,
            final_message="manual runtime invocation is not implemented yet",
        )
