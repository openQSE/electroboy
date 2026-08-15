"""Filesystem change detection used by streaming transports."""

from __future__ import annotations

from pathlib import Path


def file_signature(path: Path) -> dict[str, object]:
    """Return the stable fields needed to detect a file change."""

    try:
        stat = path.stat()
    except FileNotFoundError:
        return {"exists": False, "mtime_ns": 0, "size": 0}
    return {
        "exists": True,
        "mtime_ns": stat.st_mtime_ns,
        "size": stat.st_size,
    }
