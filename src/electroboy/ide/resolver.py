"""IDE runtime selection and discovery."""

from __future__ import annotations

import os
import platform as host_platform
import subprocess
import sys
from pathlib import Path

from .artifacts import RuntimeArtifact, RuntimeArtifactManifest
from .domain import (
    IDEError,
    IDEErrorCategory,
    IDERuntime,
    IDERuntimeMode,
    IDERuntimeOrigin,
)

_ARCHITECTURE_ALIASES = {
    "amd64": "x86_64",
    "x64": "x86_64",
    "x86_64": "x86_64",
    "aarch64": "arm64",
    "arm64": "arm64",
    "armv7l": "armhf",
    "armv8l": "armhf",
}


class OpenVSCodeRuntimeResolver:
    """Resolve a configured or managed OpenVSCode Server executable."""

    def __init__(
        self,
        manifest: RuntimeArtifactManifest,
        data_root: Path,
        *,
        platform: str | None = None,
        architecture: str | None = None,
    ) -> None:
        self.manifest = manifest
        self.data_root = data_root.expanduser().resolve()
        self.platform = platform or normalize_platform(sys.platform)
        self.architecture = architecture or normalize_architecture(
            host_platform.machine()
        )
        self._diagnostics: dict[str, object] = {
            "mode": None,
            "status": "unresolved",
            "platform": self.platform,
            "architecture": self.architecture,
        }

    def resolve(
        self,
        mode: IDERuntimeMode,
        *,
        system_executable: Path | None = None,
    ) -> IDERuntime | None:
        selected = mode
        if mode is IDERuntimeMode.AUTO:
            selected = (
                IDERuntimeMode.SYSTEM
                if system_executable is not None
                else IDERuntimeMode.MANAGED
            )
        self._diagnostics = {
            "mode": selected.value,
            "status": "resolving",
            "platform": self.platform,
            "architecture": self.architecture,
        }
        try:
            if selected is IDERuntimeMode.DISABLED:
                self._diagnostics["status"] = "disabled"
                return None
            if selected is IDERuntimeMode.SYSTEM:
                runtime = self._resolve_system(system_executable)
            else:
                runtime = self._resolve_managed()
        except IDEError as error:
            self._diagnostics.update(
                status="error",
                error_category=error.category.value,
                message=str(error),
            )
            raise
        self._diagnostics.update(status="ready", runtime=runtime.payload())
        return runtime

    def diagnostics(self) -> dict[str, object]:
        return dict(self._diagnostics)

    def managed_artifact(self) -> RuntimeArtifact:
        return self.manifest.artifact(self.platform, self.architecture)

    def managed_install_root(self) -> Path:
        return (
            self.data_root
            / "ide"
            / "runtimes"
            / self.manifest.provider
            / self.manifest.version
            / f"{self.platform}-{self.architecture}"
        )

    def _resolve_managed(self) -> IDERuntime:
        artifact = self.managed_artifact()
        executable = self.managed_install_root() / artifact.executable
        if not _is_executable(executable):
            raise IDEError(
                IDEErrorCategory.RUNTIME_MISSING,
                f"managed {self.manifest.provider} {self.manifest.version} "
                "runtime is not installed",
                recoverable=True,
            )
        return IDERuntime(
            provider=self.manifest.provider,
            version=self.manifest.version,
            platform=self.platform,
            architecture=self.architecture,
            executable=executable,
            origin=IDERuntimeOrigin.MANAGED,
        )

    def _resolve_system(self, executable: Path | None) -> IDERuntime:
        if executable is None:
            raise IDEError(
                IDEErrorCategory.RUNTIME_MISSING,
                "system IDE mode requires an executable path",
                recoverable=True,
            )
        resolved = executable.expanduser().resolve()
        if not _is_executable(resolved):
            raise IDEError(
                IDEErrorCategory.RUNTIME_MISSING,
                f"system IDE executable is unavailable: {resolved}",
                recoverable=True,
            )
        try:
            completed = subprocess.run(
                [str(resolved), "--version"],
                check=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise IDEError(
                IDEErrorCategory.RUNTIME_INCOMPATIBLE,
                f"could not query system IDE version: {error}",
            ) from error
        version = completed.stdout.splitlines()[0].strip() if completed.stdout else ""
        if not version or not version[0].isdigit():
            raise IDEError(
                IDEErrorCategory.RUNTIME_INCOMPATIBLE,
                "system IDE executable returned an invalid version",
            )
        return IDERuntime(
            provider=self.manifest.provider,
            version=version,
            platform=self.platform,
            architecture=self.architecture,
            executable=resolved,
            origin=IDERuntimeOrigin.SYSTEM,
        )


def normalize_platform(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.startswith("linux"):
        return "linux"
    if normalized.startswith(("darwin", "macos")):
        return "darwin"
    if normalized.startswith(("win", "cygwin", "msys")):
        return "windows"
    return normalized or "unknown"


def normalize_architecture(value: str) -> str:
    normalized = value.strip().lower()
    return _ARCHITECTURE_ALIASES.get(normalized, normalized or "unknown")


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)
