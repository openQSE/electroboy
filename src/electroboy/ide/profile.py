"""Managed IDE profile defaults."""

from __future__ import annotations

import json
import shutil
import threading
from importlib.resources import as_file, files
from pathlib import Path

from .domain import IDEProfile

MANAGED_IDE_SETTINGS: dict[str, object] = {
    # vscode-neovim 1.19 requires Monaco's textarea input path for key dispatch.
    "editor.editContext": False,
    "telemetry.telemetryLevel": "off",
    "workbench.enableExperiments": False,
    "update.mode": "none",
    "extensions.autoCheckUpdates": False,
    "extensions.autoUpdate": False,
    "extensions.ignoreRecommendations": True,
    "extensions.showRecommendationsOnlyOnDemand": True,
    "workbench.colorTheme": "ElectroBoy",
}
_EXTENSION_REGISTRY_LOCK = threading.Lock()


def configure_managed_profile(
    profile: IDEProfile,
    additional_settings: dict[str, object] | None = None,
) -> None:
    """Apply privacy-preserving defaults without reading user VS Code state."""

    settings = {**MANAGED_IDE_SETTINGS, **(additional_settings or {})}
    _merge_settings(profile.user_data / "User" / "settings.json", settings)
    _merge_settings(profile.user_data / "Machine" / "settings.json", settings)
    _install_bundled_extensions(profile.extensions)


def _merge_settings(settings_path: Path, settings: dict[str, object]) -> None:
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, object] = {}
    if settings_path.is_file():
        try:
            value = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                existing = value
        except (OSError, json.JSONDecodeError):
            existing = {}
    existing.update(settings)
    settings_path.write_text(
        json.dumps(existing, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _install_bundled_extensions(extensions_directory: Path) -> None:
    source_root = files("electroboy.ide").joinpath("extensions")
    extensions_directory.mkdir(parents=True, exist_ok=True)
    for source in source_root.iterdir():
        if not source.is_dir():
            continue
        destination = extensions_directory / source.name
        staging = extensions_directory / f".{source.name}.staging"
        shutil.rmtree(staging, ignore_errors=True)
        with as_file(source) as source_path:
            shutil.copytree(source_path, staging)
        if destination.exists():
            shutil.rmtree(destination)
        staging.replace(destination)
        register_managed_extension(destination)


def register_managed_extension(extension_directory: Path) -> None:
    """Register an unpacked managed extension with the OpenVSCode profile."""

    package = _extension_package(extension_directory)
    extension_id = f"{package['publisher']}.{package['name']}"
    resolved = extension_directory.resolve()
    record = {
        "identifier": {"id": extension_id},
        "version": package["version"],
        "location": {
            "$mid": 1,
            "fsPath": str(resolved),
            "path": str(resolved),
            "scheme": "file",
        },
        "relativeLocation": extension_directory.name,
    }
    with _EXTENSION_REGISTRY_LOCK:
        registry_path = extension_directory.parent / "extensions.json"
        registry = _read_extension_registry(registry_path)
        registry = [
            entry
            for entry in registry
            if entry.get("identifier", {}).get("id") != extension_id
        ]
        registry.append(record)
        _write_json_atomic(registry_path, registry)
        _clear_obsolete(extension_directory.parent, extension_id)


def unregister_managed_extension(
    extensions_directory: Path,
    extension_id: str,
) -> None:
    """Remove a managed extension from the OpenVSCode profile registry."""

    with _EXTENSION_REGISTRY_LOCK:
        registry_path = extensions_directory / "extensions.json"
        if registry_path.is_file():
            registry = _read_extension_registry(registry_path)
            retained = [
                entry
                for entry in registry
                if entry.get("identifier", {}).get("id") != extension_id
            ]
            if retained != registry:
                _write_json_atomic(registry_path, retained)
        _clear_obsolete(extensions_directory, extension_id)


def _extension_package(extension_directory: Path) -> dict[str, str]:
    payload = json.loads(
        (extension_directory / "package.json").read_text(encoding="utf-8")
    )
    package: dict[str, str] = {}
    for field in ("publisher", "name", "version"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"extension package {field} must be a non-empty string")
        package[field] = value.strip()
    return package


def _read_extension_registry(path: Path) -> list[dict[str, object]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [entry for entry in payload if isinstance(entry, dict)]


def _write_json_atomic(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        json.dumps(payload, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _clear_obsolete(extensions_directory: Path, extension_id: str) -> None:
    obsolete_path = extensions_directory / ".obsolete"
    if not obsolete_path.is_file():
        return
    try:
        payload = json.loads(obsolete_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(payload, dict):
        return
    retained = {
        key: value
        for key, value in payload.items()
        if key != extension_id and not key.startswith(f"{extension_id}-")
    }
    if retained != payload:
        _write_json_atomic(obsolete_path, retained)
