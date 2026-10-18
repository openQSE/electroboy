"""OpenCode terminal adapter (v2 CLI)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from collections.abc import Iterable
from uuid import uuid4

from .interactive_cli import InteractiveCliRuntime


def opencode_interactive_command(
    root: Path | str,
    *,
    executable: str = "opencode",
    args: Iterable[str] = (),
    sandbox: str = "workspace-write",
) -> list[str]:
    # A private server belongs to this process tree and dies with the agent.
    return [executable, str(Path(root).resolve()), "--standalone", *args]


class OpenCodeInteractiveRuntime(InteractiveCliRuntime):
    def _command(self, invocation):
        command = opencode_interactive_command(
            self.root, executable=self.config.command, args=self.config.args
        )
        command.extend(
            ["--session", invocation.provider_session_id or "ses_" + uuid4().hex]
        )
        return command

    def invoke(self, invocation):
        # The TUI accepts its initial message through --prompt, not positionally.
        from dataclasses import replace

        resumed = bool(invocation.provider_session_id)
        invocation = replace(
            invocation,
            provider_session_id=invocation.provider_session_id or "ses_" + uuid4().hex,
        )
        result = super().invoke(invocation)
        result.resumed_session = resumed
        result.provider = "opencode"
        result.provider_session_id = invocation.provider_session_id
        return result

    def _interactive_command(self, invocation):
        return [*self._command(invocation), "--prompt", self._build_prompt(invocation)]


def readonly_config() -> str:
    """Keep the tutor's read-only tool policy when using OpenCode."""
    config = json.loads(os.environ.get("OPENCODE_CONFIG_CONTENT") or "{}")
    permissions = {
        "*": "deny",
        "read": {"*": "allow", "*.env": "deny", "*.env.*": "deny"},
        "glob": "allow",
        "grep": "allow",
        "list": "allow",
        "lsp": "allow",
    }
    agents = config.setdefault("agent", {})
    agents["electroboy-reader"] = {
        "description": "Read-only ElectroBoy tutor",
        "mode": "primary",
        "permission": permissions,
    }
    config["default_agent"] = "electroboy-reader"
    return json.dumps(config)
