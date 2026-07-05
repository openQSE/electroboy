"""Runtime configuration placeholders."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RuntimeConfig:
    """Configured agent runtime command."""

    name: str
    adapter: str
    command: str
    args: list[str] = field(default_factory=list)
