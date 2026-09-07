"""Managed VSCode Neovim extension and host executable profile."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import zipfile
from dataclasses import asdict, dataclass
from importlib.resources import files
from pathlib import Path, PurePosixPath

from .domain import IDEProfile
from .downloads import AuditedDownloadClient
from .profile import configure_managed_profile

_VERSION = re.compile(r"NVIM\s+v?(\d+)\.(\d+)\.(\d+)", re.IGNORECASE)
_INSTALL_LOCK = threading.Lock()


@dataclass(frozen=True)
class ExtensionArtifact:
    id: str
    version: str
    source: str
    url: str
    sha256: str
    size: int
    minimum_ide_version: str
    minimum_neovim_version: str


@dataclass(frozen=True)
class NeovimConfiguration:
    enabled: bool = True
    executable: str = ""


class NeovimProfileManager:
    """Resolve Neovim and materialize its pinned extension per IDE profile."""

    def __init__(
        self,
        data_root: Path,
        download_client: AuditedDownloadClient,
        *,
        platform: str = "linux",
    ) -> None:
        self.data_root = data_root
        self.download_client = download_client
        self.platform = platform
        self.artifact = load_neovim_artifact()
        self.config_path = data_root / "ide" / "neovim.json"
        self._last_status = self.status()

    def configuration(self) -> NeovimConfiguration:
        try:
            payload = json.loads(self.config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return NeovimConfiguration()
        return NeovimConfiguration(
            enabled=bool(payload.get("enabled", True)),
            executable=str(payload.get("executable") or "").strip(),
        )

    def configure(
        self,
        *,
        enabled: bool,
        executable: str = "",
    ) -> dict[str, object]:
        configuration = NeovimConfiguration(enabled, executable.strip())
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(asdict(configuration), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.config_path)
        self._last_status = self.status(configuration)
        return {**self._last_status, "restart_required": True}

    def prepare(self, profile: IDEProfile) -> dict[str, object]:
        configuration = self.configuration()
        status = self.status(configuration)
        destination = profile.extensions / self.extension_directory_name
        if status["status"] != "enabled":
            shutil.rmtree(destination, ignore_errors=True)
            self._last_status = status
            return status
        try:
            extension = self._cached_extension()
            profile.extensions.mkdir(parents=True, exist_ok=True)
            staging = profile.extensions / f".{destination.name}.staging"
            shutil.rmtree(staging, ignore_errors=True)
            shutil.copytree(extension, staging)
            shutil.rmtree(destination, ignore_errors=True)
            staging.replace(destination)
        except Exception as error:
            status = {
                **status,
                "status": "unavailable",
                "installed": False,
                "reason": f"extension installation failed: {error}",
            }
            self._last_status = status
            return status
        executable = str(status["executable"])
        configure_managed_profile(
            profile,
            {
                f"vscode-neovim.neovimExecutablePaths.{self.platform}": executable,
                "vscode-neovim.neovimClean": True,
            },
        )
        status = {**status, "installed": True}
        self._last_status = status
        return status

    def status(
        self,
        configuration: NeovimConfiguration | None = None,
    ) -> dict[str, object]:
        selected = configuration or self.configuration()
        base: dict[str, object] = {
            "status": "disabled" if not selected.enabled else "unavailable",
            "enabled": selected.enabled,
            "configured_executable": selected.executable or None,
            "executable": None,
            "version": None,
            "minimum_version": self.artifact.minimum_neovim_version,
            "extension": {
                "id": self.artifact.id,
                "version": self.artifact.version,
                "source": self.artifact.source,
            },
            "installed": False,
        }
        if not selected.enabled:
            return base
        executable = self._resolve_executable(selected.executable)
        if executable is None:
            return {**base, "reason": "Neovim executable was not found"}
        version = _neovim_version(executable)
        if version is None:
            return {
                **base,
                "status": "incompatible",
                "executable": str(executable),
                "reason": "Neovim returned an unrecognized version",
            }
        minimum = _version_tuple(self.artifact.minimum_neovim_version)
        if version < minimum:
            return {
                **base,
                "status": "incompatible",
                "executable": str(executable),
                "version": ".".join(map(str, version)),
                "reason": f"Neovim {self.artifact.minimum_neovim_version}+ is required",
            }
        return {
            **base,
            "status": "enabled",
            "executable": str(executable),
            "version": ".".join(map(str, version)),
        }

    @property
    def extension_directory_name(self) -> str:
        return f"{self.artifact.id}-{self.artifact.version}"

    def diagnostics(self) -> dict[str, object]:
        return dict(self._last_status)

    def _resolve_executable(self, configured: str) -> Path | None:
        if configured:
            candidate = Path(configured).expanduser().resolve()
            return (
                candidate
                if os.access(candidate, os.X_OK) and candidate.is_file()
                else None
            )
        discovered = shutil.which("nvim")
        return Path(discovered).resolve() if discovered else None

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


def load_neovim_artifact() -> ExtensionArtifact:
    payload = json.loads(
        files("electroboy.ide")
        .joinpath("extension-artifacts.json")
        .read_text(encoding="utf-8")
    )
    record = payload["extensions"][0]
    return ExtensionArtifact(**record)


def _neovim_version(executable: Path) -> tuple[int, int, int] | None:
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
    return tuple(map(int, match.groups())) if match else None


def _version_tuple(value: str) -> tuple[int, int, int]:
    parts = [int(part) for part in value.split(".")[:3]]
    return tuple([*parts, 0, 0][:3])


def _valid_marker(path: Path, artifact: ExtensionArtifact) -> bool:
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
