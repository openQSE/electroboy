"""Verified installation of pinned managed IDE runtimes."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
import threading
import urllib.request
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import BinaryIO

from .contracts import ProgressCallback
from .domain import IDEError, IDEErrorCategory, IDERuntime, IDERuntimeMode
from .resolver import OpenVSCodeRuntimeResolver

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on non-POSIX hosts
    fcntl = None  # type: ignore[assignment]

OpenURL = Callable[..., BinaryIO]
_LOCKS: dict[Path, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


class ManagedRuntimeInstaller:
    """Download, verify, and atomically publish one pinned runtime."""

    def __init__(
        self,
        resolver: OpenVSCodeRuntimeResolver,
        *,
        open_url: OpenURL = urllib.request.urlopen,
    ) -> None:
        self.resolver = resolver
        self.open_url = open_url

    def install(self, progress: ProgressCallback | None = None) -> IDERuntime:
        target = self.resolver.managed_install_root()
        target.parent.mkdir(parents=True, exist_ok=True)
        process_lock = _lock_for(target)
        with process_lock, _file_lock(target.parent / ".install.lock"):
            runtime = self._verified_existing()
            if runtime is not None:
                _report(progress, "Using verified managed IDE runtime", 100)
                return runtime
            return self._install_locked(progress)

    def cleanup_unused_versions(self) -> list[Path]:
        current = self.resolver.manifest.version
        provider_root = (
            self.resolver.data_root
            / "ide"
            / "runtimes"
            / self.resolver.manifest.provider
        )
        removed: list[Path] = []
        if not provider_root.is_dir():
            return removed
        for child in provider_root.iterdir():
            if child.name == current or not child.is_dir() or child.is_symlink():
                continue
            shutil.rmtree(child)
            removed.append(child)
        return removed

    def _verified_existing(self) -> IDERuntime | None:
        target = self.resolver.managed_install_root()
        marker = target / ".electroboy-runtime.json"
        if not marker.is_file():
            return None
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        artifact = self.resolver.managed_artifact()
        expected = {
            "provider": self.resolver.manifest.provider,
            "version": self.resolver.manifest.version,
            "platform": artifact.platform,
            "architecture": artifact.architecture,
            "sha256": artifact.sha256,
        }
        if any(payload.get(key) != value for key, value in expected.items()):
            return None
        try:
            return self.resolver.resolve(IDERuntimeMode.MANAGED)
        except IDEError:
            return None

    def _install_locked(self, progress: ProgressCallback | None) -> IDERuntime:
        artifact = self.resolver.managed_artifact()
        target = self.resolver.managed_install_root()
        staging = Path(
            tempfile.mkdtemp(prefix=f".{target.name}.staging-", dir=target.parent)
        )
        archive = staging / "runtime.tar.gz"
        try:
            _report(progress, "Downloading managed IDE runtime", 0)
            digest, size = self._download(
                artifact.url,
                archive,
                artifact.size,
                progress,
            )
            if size != artifact.size:
                raise IDEError(
                    IDEErrorCategory.INSTALLATION_FAILED,
                    "runtime archive size mismatch: "
                    f"expected {artifact.size}, got {size}",
                )
            if digest != artifact.sha256:
                raise IDEError(
                    IDEErrorCategory.INSTALLATION_FAILED,
                    "runtime archive checksum does not match the pinned digest",
                )
            _report(progress, "Extracting managed IDE runtime", 92)
            extraction = staging / "extracted"
            extraction.mkdir()
            self._extract(archive, extraction)
            extracted_root = extraction / artifact.archive_root
            executable = extracted_root / artifact.executable
            if not executable.is_file():
                raise IDEError(
                    IDEErrorCategory.INSTALLATION_FAILED,
                    f"runtime archive is missing {artifact.executable}",
                )
            executable.chmod(executable.stat().st_mode | 0o100)
            marker = {
                "schema_version": 1,
                "provider": self.resolver.manifest.provider,
                "version": self.resolver.manifest.version,
                "platform": artifact.platform,
                "architecture": artifact.architecture,
                "sha256": artifact.sha256,
                "source_url": artifact.url,
            }
            (extracted_root / ".electroboy-runtime.json").write_text(
                json.dumps(marker, indent=2) + "\n",
                encoding="utf-8",
            )
            if target.exists():
                shutil.rmtree(target)
            os.replace(extracted_root, target)
            _report(progress, "Managed IDE runtime is ready", 100)
            runtime = self.resolver.resolve(IDERuntimeMode.MANAGED)
            assert runtime is not None
            return runtime
        except IDEError:
            raise
        except Exception as error:
            raise IDEError(
                IDEErrorCategory.INSTALLATION_FAILED,
                f"managed IDE installation failed: {error}",
                recoverable=True,
            ) from error
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _download(
        self,
        url: str,
        destination: Path,
        expected_size: int,
        progress: ProgressCallback | None,
    ) -> tuple[str, int]:
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "ElectroBoy IDE runtime installer"},
        )
        digest = hashlib.sha256()
        downloaded = 0
        with self.open_url(request, timeout=30) as response:
            with destination.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    percentage = min(90, int(downloaded * 90 / expected_size))
                    _report(progress, "Downloading managed IDE runtime", percentage)
        return digest.hexdigest(), downloaded

    @staticmethod
    def _extract(archive: Path, destination: Path) -> None:
        with tarfile.open(archive, mode="r:gz") as bundle:
            for member in bundle.getmembers():
                _validate_archive_member(member)
            bundle.extractall(destination, filter="data")


def _validate_archive_member(member: tarfile.TarInfo) -> None:
    path = PurePosixPath(member.name)
    if path.is_absolute() or ".." in path.parts:
        raise IDEError(
            IDEErrorCategory.INSTALLATION_FAILED,
            f"runtime archive entry escapes extraction root: {member.name}",
        )
    if member.isdev():
        raise IDEError(
            IDEErrorCategory.INSTALLATION_FAILED,
            f"runtime archive contains a device entry: {member.name}",
        )
    if member.issym() or member.islnk():
        link = PurePosixPath(member.linkname)
        combined = path.parent / link
        depth = 0
        for part in combined.parts:
            if part == "..":
                depth -= 1
            elif part not in ("", "."):
                depth += 1
            if depth < 0:
                break
        if link.is_absolute() or depth < 0:
            raise IDEError(
                IDEErrorCategory.INSTALLATION_FAILED,
                f"runtime archive link escapes extraction root: {member.name}",
            )


def _lock_for(path: Path) -> threading.Lock:
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(path, threading.Lock())


@contextlib.contextmanager
def _file_lock(path: Path):
    with path.open("a+b") as stream:
        if fcntl is not None:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _report(
    progress: ProgressCallback | None,
    message: str,
    percentage: int | None,
) -> None:
    if progress is not None:
        progress(message, percentage)
