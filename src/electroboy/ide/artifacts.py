"""Pinned IDE runtime artifact manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from .domain import IDEError, IDEErrorCategory


@dataclass(frozen=True)
class RuntimeArtifact:
    """One installable runtime archive for a platform and architecture."""

    platform: str
    architecture: str
    url: str
    sha256: str
    size: int
    archive_format: str
    archive_root: str
    executable: str


@dataclass(frozen=True)
class RuntimeArtifactManifest:
    """A versioned provider release and its supported artifacts."""

    schema_version: int
    provider: str
    version: str
    artifacts: tuple[RuntimeArtifact, ...]

    def artifact(self, platform: str, architecture: str) -> RuntimeArtifact:
        for artifact in self.artifacts:
            if (
                artifact.platform == platform
                and artifact.architecture == architecture
            ):
                return artifact
        raise IDEError(
            IDEErrorCategory.UNSUPPORTED,
            f"no {self.provider} {self.version} runtime is available for "
            f"{platform}/{architecture}",
        )


def load_runtime_manifest(
    path: Path | None = None,
    *,
    resource_name: str = "runtime-artifacts.json",
) -> RuntimeArtifactManifest:
    """Load and validate the packaged runtime artifact manifest."""

    if path is None:
        raw = (
            resources.files("electroboy.ide")
            .joinpath(resource_name)
            .read_text(encoding="utf-8")
        )
    else:
        raw = path.read_text(encoding="utf-8")
    try:
        payload = json.loads(raw)
        artifacts = tuple(
            RuntimeArtifact(
                platform=_required_text(row, "platform"),
                architecture=_required_text(row, "architecture"),
                url=_required_text(row, "url"),
                sha256=_required_digest(row, "sha256"),
                size=_required_positive_integer(row, "size"),
                archive_format=_required_text(row, "archive_format"),
                archive_root=_required_text(row, "archive_root"),
                executable=_required_text(row, "executable"),
            )
            for row in payload["artifacts"]
        )
        manifest = RuntimeArtifactManifest(
            schema_version=int(payload["schema_version"]),
            provider=_required_text(payload, "provider"),
            version=_required_text(payload, "version"),
            artifacts=artifacts,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise IDEError(
            IDEErrorCategory.RUNTIME_INCOMPATIBLE,
            f"invalid IDE runtime artifact manifest: {error}",
        ) from error
    if manifest.schema_version != 1 or not manifest.artifacts:
        raise IDEError(
            IDEErrorCategory.RUNTIME_INCOMPATIBLE,
            "unsupported or empty IDE runtime artifact manifest",
        )
    return manifest


def _required_text(payload: object, key: str) -> str:
    if not isinstance(payload, dict):
        raise TypeError(f"{key} parent must be an object")
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value.strip()


def _required_digest(payload: object, key: str) -> str:
    value = _required_text(payload, key).lower()
    if len(value) != 64 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError(f"{key} must be a SHA-256 digest")
    return value


def _required_positive_integer(payload: object, key: str) -> int:
    if not isinstance(payload, dict):
        raise TypeError(f"{key} parent must be an object")
    value = int(payload.get(key, 0))
    if value < 1:
        raise ValueError(f"{key} must be a positive integer")
    return value
