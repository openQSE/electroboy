"""Shared adapter interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentInvocation:
    """Input passed to an agent runtime."""

    role: str
    prompt: str
    context_paths: list[str] = field(default_factory=list)


@dataclass
class AgentResult:
    """Normalized result returned by an agent runtime."""

    ok: bool
    final_message: str
    issues: list[dict[str, object]] = field(default_factory=list)


class AgentRuntime:
    """Runtime interface implemented by CLI and manual adapters."""

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        raise NotImplementedError
