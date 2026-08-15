"""File browser capability module declaration."""

from __future__ import annotations

from pathlib import Path

from electroboy.service.registry import ServiceModule
from electroboy.state_store import StateError

from .common import route


def module() -> ServiceModule:
    return ServiceModule(
        id="file_browser",
        label="File Browser",
        routes=(
            route("GET", "/file-browser", "file_browser", "window"),
            route("GET", "/api/files/browse", "file_browser", "browse"),
        ),
        capabilities=frozenset({"directory-picker", "file-picker"}),
        state_namespace="file_browser",
    )


def browse_directories(path: Path | str, *, show_hidden: bool = False) -> dict[str, object]:
    directory = Path(path).expanduser().resolve()
    if not directory.exists():
        raise StateError(f"directory does not exist: {directory}")
    if not directory.is_dir():
        raise StateError(f"path is not a directory: {directory}")

    try:
        children = sorted(
            [
                child
                for child in directory.iterdir()
                if child.is_dir() and _browser_entry_visible(child, show_hidden)
            ],
            key=lambda child: child.name.lower(),
        )
    except OSError as error:
        raise StateError(f"could not read directory: {error}") from error
    return {
        "path": str(directory),
        "parent": str(directory.parent) if directory.parent != directory else None,
        "entries": [
            {
                "name": child.name,
                "path": str(child),
            }
            for child in children[:200]
        ],
    }


def browse_files(path: Path | str, *, show_hidden: bool = False) -> dict[str, object]:
    directory = Path(path).expanduser().resolve()
    if not directory.exists():
        raise StateError(f"directory does not exist: {directory}")
    if not directory.is_dir():
        raise StateError(f"path is not a directory: {directory}")

    try:
        children = sorted(
            [
                child
                for child in directory.iterdir()
                if child.is_dir() or child.is_file()
                if _browser_entry_visible(child, show_hidden)
            ],
            key=lambda child: (not child.is_dir(), child.name.lower()),
        )
    except OSError as error:
        raise StateError(f"could not read directory: {error}") from error
    return {
        "path": str(directory),
        "parent": str(directory.parent) if directory.parent != directory else None,
        "entries": [
            {
                "name": child.name,
                "path": str(child),
                "type": "directory" if child.is_dir() else "file",
            }
            for child in children[:300]
        ],
    }


def browse_markdown_files(
    path: Path | str,
    *,
    show_hidden: bool = False,
) -> dict[str, object]:
    directory = Path(path).expanduser().resolve()
    if not directory.exists():
        raise StateError(f"directory does not exist: {directory}")
    if not directory.is_dir():
        raise StateError(f"path is not a directory: {directory}")

    try:
        children = sorted(
            [
                child
                for child in directory.iterdir()
                if child.is_dir()
                or (child.is_file() and child.suffix.lower() == ".md")
                if _browser_entry_visible(child, show_hidden)
            ],
            key=lambda child: (not child.is_dir(), child.name.lower()),
        )
    except OSError as error:
        raise StateError(f"could not read directory: {error}") from error
    return {
        "path": str(directory),
        "parent": str(directory.parent) if directory.parent != directory else None,
        "entries": [
            {
                "name": child.name,
                "path": str(child),
                "type": "directory" if child.is_dir() else "file",
            }
            for child in children[:300]
        ],
    }


def _browser_entry_visible(path: Path, show_hidden: bool) -> bool:
    return show_hidden or not path.name.startswith(".")
