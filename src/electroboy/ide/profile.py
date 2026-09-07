"""Managed IDE profile defaults."""

from __future__ import annotations

import json
import shutil
from importlib.resources import as_file, files
from pathlib import Path

from .domain import IDEProfile

MANAGED_IDE_SETTINGS: dict[str, object] = {
    "telemetry.telemetryLevel": "off",
    "workbench.enableExperiments": False,
    "update.mode": "none",
    "extensions.autoCheckUpdates": False,
    "extensions.autoUpdate": False,
    "extensions.ignoreRecommendations": True,
    "extensions.showRecommendationsOnlyOnDemand": True,
    "workbench.colorTheme": "ElectroBoy",
}


def configure_managed_profile(
    profile: IDEProfile,
    additional_settings: dict[str, object] | None = None,
) -> None:
    """Apply privacy-preserving defaults without reading user VS Code state."""

    settings_path = profile.user_data / "User" / "settings.json"
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, object] = {}
    if settings_path.is_file():
        try:
            value = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(value, dict):
                existing = value
        except (OSError, json.JSONDecodeError):
            existing = {}
    existing.update(MANAGED_IDE_SETTINGS)
    existing.update(additional_settings or {})
    settings_path.write_text(
        json.dumps(existing, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _install_bundled_extensions(profile.extensions)


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
