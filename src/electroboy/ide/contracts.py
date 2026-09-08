"""Responsibility-oriented interfaces for IDE providers and runtimes."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from .domain import (
    IDEEndpoint,
    IDEInstance,
    IDEInstanceStatus,
    IDELocation,
    IDEProfile,
    IDERuntime,
    IDERuntimeMode,
    IDEWorkspace,
)

ProgressCallback = Callable[[str, int | None], None]


class RuntimeResolver(Protocol):
    """Locate a usable provider runtime without starting it."""

    def resolve(
        self,
        mode: IDERuntimeMode,
        *,
        system_executable: Path | None = None,
    ) -> IDERuntime | None: ...


class RuntimeInstaller(Protocol):
    """Acquire and publish a pinned managed runtime."""

    def install(self, progress: ProgressCallback | None = None) -> IDERuntime: ...


class IDEProvider(Protocol):
    """Run and control one provider behind provider-neutral operations."""

    @property
    def provider_id(self) -> str: ...

    def start(
        self,
        workspace: IDEWorkspace,
        runtime: IDERuntime,
        profile: IDEProfile,
    ) -> IDEInstance: ...

    def status(self, instance: IDEInstance) -> IDEInstanceStatus: ...

    def wait_until_ready(
        self,
        instance: IDEInstance,
        timeout: float,
    ) -> IDEInstance: ...

    def endpoint(self, instance: IDEInstance) -> IDEEndpoint: ...

    def open_location(
        self,
        instance: IDEInstance,
        location: IDELocation,
    ) -> str | None: ...

    def stop(self, instance: IDEInstance, reason: str) -> IDEInstance: ...
