"""Shared adapter interfaces."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class AgentInvocation:
    """Input passed to an agent runtime."""

    role: str
    prompt: str
    context_paths: list[str] = field(default_factory=list)
    output_schema: dict[str, object] | None = None


@dataclass
class AgentResult:
    """Normalized result returned by an agent runtime."""

    ok: bool
    final_message: str
    issues: list[dict[str, object]] = field(default_factory=list)
    raw_events: list[dict[str, object]] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    created_files: list[str] = field(default_factory=list)
    commands: list[str] = field(default_factory=list)
    commit_message: str | None = None
    error: str | None = None


class AgentRuntime:
    """Runtime interface implemented by CLI and manual adapters."""

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        raise NotImplementedError
