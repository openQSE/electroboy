"""Manual runtime adapter placeholder."""

from __future__ import annotations

from pathlib import Path

from .base import AgentInvocation, AgentResult, AgentRuntime
from ..config import RuntimeConfig


class ManualRuntime(AgentRuntime):
    """Runtime that records prompts for a human-managed agent turn."""

    def __init__(self, config: RuntimeConfig, root: Path | str = ".") -> None:
        self.config = config
        self.root = Path(root).resolve()

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        response_file = self.config.options.get("response_file")
        if response_file:
            path = self.root / response_file
            if path.exists():
                return AgentResult(
                    ok=True,
                    final_message=path.read_text(encoding="utf-8"),
                )
        return AgentResult(
            ok=False,
            final_message="manual response file was not provided",
            error="missing manual response",
        )
