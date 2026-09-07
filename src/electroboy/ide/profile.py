"""Managed IDE profile defaults."""

from __future__ import annotations

import json

from .domain import IDEProfile

MANAGED_IDE_SETTINGS: dict[str, object] = {
    "telemetry.telemetryLevel": "off",
    "workbench.enableExperiments": False,
    "update.mode": "none",
    "extensions.autoCheckUpdates": False,
    "extensions.autoUpdate": False,
    "extensions.ignoreRecommendations": True,
    "extensions.showRecommendationsOnlyOnDemand": True,
}


def configure_managed_profile(profile: IDEProfile) -> None:
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
    settings_path.write_text(
        json.dumps(existing, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
