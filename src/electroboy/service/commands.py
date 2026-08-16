"""Command construction shared by service capabilities and workflows."""

from __future__ import annotations

import shlex
import sys
from pathlib import Path


def service_module_search_path() -> Path:
    """Return the source or installation root containing the package."""

    return Path(__file__).resolve().parents[2]


def electroboy_command(root: Path, args: list[str]) -> list[str]:
    """Build an ElectroBoy command that honors a project's activation script."""

    activate_script = root / ".electroboy" / "bin" / "activate"
    command_parts = [
        sys.executable,
        "-m",
        "electroboy",
        "--root",
        str(root),
        *args,
    ]
    command_text = " ".join(shlex.quote(part) for part in command_parts)
    if activate_script.exists():
        module_path = shlex.quote(str(service_module_search_path()))
        return [
            "/bin/sh",
            "-c",
            f". {shlex.quote(str(activate_script))} >/dev/null && "
            f"PYTHONPATH={module_path}${{PYTHONPATH:+:$PYTHONPATH}} "
            f"{command_text}",
        ]
    return command_parts
