"""Feature-aware pipeline artifact path helpers."""

from __future__ import annotations

import json
from pathlib import Path


DEFAULT_ARTIFACT_PATHS = {
    "requirements": "docs/requirements.md",
    "design": "docs/detailed-design.md",
    "implementation_plan": "docs/implementation-plan.md",
    "test_plan": "docs/test-plan.md",
    "design_review": "docs/design-review.md",
    "implementation_log": "docs/implementation-log.md",
    "implementation_report": "docs/implementation-report.md",
    "validation_report": "docs/validation-report.md",
}

FEATURE_ARTIFACT_STEMS = {
    "requirements": "requirements",
    "design": "detailed-design",
    "implementation_plan": "implementation-plan",
    "test_plan": "test-plan",
    "design_review": "design-review",
    "implementation_log": "implementation-log",
    "implementation_report": "implementation-report",
    "validation_report": "validation-report",
}

DEFAULT_PATH_KEYS = {
    path: key
    for key, path in DEFAULT_ARTIFACT_PATHS.items()
}


def feature_artifact_paths(slug: str) -> dict[str, str]:
    """Return feature-scoped artifact paths for a normalized feature slug."""

    return {
        key: f"docs/{stem}-{slug}.md"
        for key, stem in FEATURE_ARTIFACT_STEMS.items()
    }


def read_feature_record(root: Path, run_id: str) -> dict[str, object] | None:
    """Read the feature metadata record for a run, when present."""

    path = root / ".electroboy" / "shared" / "runs" / run_id / "feature.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def artifact_paths_for_run(root: Path, run_id: str) -> dict[str, str]:
    """Return default or feature-scoped artifact paths for the given run."""

    paths = dict(DEFAULT_ARTIFACT_PATHS)
    record = read_feature_record(root, run_id)
    if not record:
        return paths
    artifacts = record.get("artifacts")
    if isinstance(artifacts, dict):
        for key, value in artifacts.items():
            if key in paths and isinstance(value, str) and value.strip():
                paths[key] = value
    return paths


def resolve_artifact_path(paths: dict[str, str], relative_path: str) -> str:
    """Resolve a default artifact path through a run artifact path map."""

    key = DEFAULT_PATH_KEYS.get(relative_path)
    if key is None:
        return relative_path
    return paths.get(key, relative_path)
