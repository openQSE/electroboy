"""Generic CLI runtime adapter placeholder."""

from __future__ import annotations

from .base import AgentInvocation, AgentResult, AgentRuntime


class GenericCliRuntime(AgentRuntime):
    """Runtime for configured non-interactive agent CLI tools."""

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        return AgentResult(
            ok=False,
            final_message="generic CLI runtime invocation is not implemented yet",
        )
