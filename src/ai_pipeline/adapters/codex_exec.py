"""Codex exec runtime adapter placeholder."""

from __future__ import annotations

from .base import AgentInvocation, AgentResult, AgentRuntime


class CodexExecRuntime(AgentRuntime):
    """Runtime for `codex exec --json` agent turns."""

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        return AgentResult(
            ok=False,
            final_message="Codex exec runtime invocation is not implemented yet",
        )
