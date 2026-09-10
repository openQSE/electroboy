"""Managed clangd extension profile for C and C++ navigation."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path, PurePosixPath

from .domain import IDEProfile
from .downloads import AuditedDownloadClient
from .profile import (
    configure_managed_profile,
    register_managed_extension,
    unregister_managed_extension,
)

_VERSION = re.compile(r"clangd version\s+(\d+)(?:\.(\d+))?(?:\.(\d+))?", re.IGNORECASE)
_INSTALL_LOCK = threading.Lock()


@dataclass(frozen=True)
class ClangdExtensionArtifact:
    id: str
    version: str
    source: str
    url: str
    sha256: str
    size: int
    minimum_ide_version: str


class ClangdProfileManager:
    """Install clangd language support into the managed OpenVSCode profile."""

    def __init__(
        self,
        data_root: Path,
        download_client: AuditedDownloadClient,
    ) -> None:
        self.data_root = data_root
        self.download_client = download_client
        self.artifact = load_clangd_artifact()
        self._last_status = self.status()

    def prepare(self, profile: IDEProfile) -> dict[str, object]:
        status = self.status()
        try:
            extension = self._cached_extension()
            profile.extensions.mkdir(parents=True, exist_ok=True)
            destination = profile.extensions / self.extension_directory_name
            staging = profile.extensions / f".{destination.name}.staging"
            shutil.rmtree(staging, ignore_errors=True)
            shutil.copytree(extension, staging)
            shutil.rmtree(destination, ignore_errors=True)
            staging.replace(destination)
            register_managed_extension(destination)
        except Exception as error:
            status = {
                **status,
                "status": "unavailable",
                "installed": False,
                "reason": f"extension installation failed: {error}",
            }
            self._last_status = status
            return status
        configure_managed_profile(
            profile,
            {
                "clangd.path": str(status["executable"] or "clangd"),
                "clangd.arguments": ["--background-index"],
                "clangd.checkUpdates": False,
            },
        )
        status = {**status, "installed": True}
        self._last_status = status
        return status

    def status(self) -> dict[str, object]:
        base: dict[str, object] = {
            "status": "unavailable",
            "enabled": True,
            "executable": None,
            "origin": None,
            "version": None,
            "extension": {
                "id": self.artifact.id,
                "version": self.artifact.version,
                "source": self.artifact.source,
            },
            "installed": False,
        }
        executable, origin = self._resolve_executable()
        if executable is None:
            return {**base, "reason": "clangd executable was not found"}
        version = _clangd_version(executable)
        if version is None:
            return {
                **base,
                "status": "incompatible",
                "executable": str(executable),
                "origin": origin,
                "reason": "clangd returned an unrecognized version",
            }
        return {
            **base,
            "status": "enabled",
            "executable": str(executable),
            "origin": origin,
            "version": ".".join(map(str, version)),
        }

    @property
    def extension_directory_name(self) -> str:
        return f"{self.artifact.id}-{self.artifact.version}"

    def diagnostics(self) -> dict[str, object]:
        return dict(self._last_status)

    def _resolve_executable(self) -> tuple[Path | None, str | None]:
        configured = os.environ.get("ELECTROBOY_IDE_CLANGD_EXECUTABLE", "").strip()
        if configured:
            candidate = Path(configured).expanduser().resolve()
            return (
                (candidate, "configured")
                if os.access(candidate, os.X_OK) and candidate.is_file()
                else (None, None)
            )
        discovered = shutil.which("clangd")
        if discovered:
            return Path(discovered).resolve(), "system"
        return None, None

    def _cached_extension(self) -> Path:
        target = (
            self.data_root
            / "ide"
            / "extensions"
            / self.artifact.id
            / self.artifact.version
        )
        marker = target / ".electroboy-extension.json"
        with _INSTALL_LOCK:
            if (
                _valid_marker(marker, self.artifact)
                and (target / "package.json").is_file()
            ):
                return target
            target.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(
                tempfile.mkdtemp(
                    prefix=f".{self.artifact.version}.staging-",
                    dir=target.parent,
                )
            )
            try:
                archive = staging / "extension.vsix"
                self.download_client.download(
                    artifact_id=f"{self.artifact.id}-{self.artifact.version}",
                    url=self.artifact.url,
                    destination=archive,
                    sha256=self.artifact.sha256,
                    size=self.artifact.size,
                )
                extracted = staging / "extracted"
                extracted.mkdir()
                _extract_vsix(archive, extracted)
                source = extracted / "extension"
                if not (source / "package.json").is_file():
                    raise ValueError("VSIX does not contain extension/package.json")
                (source / ".electroboy-extension.json").write_text(
                    json.dumps(
                        {
                            "id": self.artifact.id,
                            "version": self.artifact.version,
                            "sha256": self.artifact.sha256,
                        },
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                shutil.rmtree(target, ignore_errors=True)
                source.replace(target)
                return target
            finally:
                shutil.rmtree(staging, ignore_errors=True)


def load_clangd_artifact() -> ClangdExtensionArtifact:
    payload = json.loads(
        files("electroboy.ide")
        .joinpath("extension-artifacts.json")
        .read_text(encoding="utf-8")
    )
    for record in payload["extensions"]:
        if record.get("id") == "llvm-vs-code-extensions.vscode-clangd":
            return ClangdExtensionArtifact(
                id=record["id"],
                version=record["version"],
                source=record["source"],
                url=record["url"],
                sha256=record["sha256"],
                size=record["size"],
                minimum_ide_version=record["minimum_ide_version"],
            )
    raise ValueError("clangd extension artifact is not pinned")


def _clangd_version(executable: Path) -> tuple[int, int, int] | None:
    try:
        completed = subprocess.run(
            [str(executable), "--version"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    match = _VERSION.search(completed.stdout)
    if not match:
        return None
    parts = [int(part or 0) for part in match.groups()]
    return tuple(parts[:3])


def _valid_marker(path: Path, artifact: ClangdExtensionArtifact) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        payload.get("id") == artifact.id
        and payload.get("version") == artifact.version
        and payload.get("sha256") == artifact.sha256
    )


def _extract_vsix(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            path = PurePosixPath(member.filename)
            if path.is_absolute() or ".." in path.parts:
                raise ValueError(
                    f"VSIX entry escapes extraction root: {member.filename}"
                )
        bundle.extractall(destination)
