"""Provider process-launch boundary used by IDE sandbox adapters."""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from .domain import IDEProfile


@dataclass
class IDEProcessLaunch:
    """A root provider process and resources coupled to its lifetime."""

    process: subprocess.Popen[str]
    line_observer: Callable[[str], None] = field(default=lambda _line: None)
    cleanup: Callable[[], None] = field(default=lambda: None)
    enforcement: dict[str, object] = field(default_factory=dict)


class IDEProcessLauncher(Protocol):
    """Start a provider process under a selected isolation policy."""

    def launch(
        self,
        arguments: list[str],
        *,
        cwd: Path,
        profile: IDEProfile,
    ) -> IDEProcessLaunch: ...


class DirectIDEProcessLauncher:
    """Launch a provider directly, primarily for configured system mode."""

    def launch(
        self,
        arguments: list[str],
        *,
        cwd: Path,
        profile: IDEProfile,
    ) -> IDEProcessLaunch:
        del profile
        process = subprocess.Popen(
            arguments,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )
        return IDEProcessLaunch(
            process,
            enforcement={"mode": "direct", "enforced": False},
        )
