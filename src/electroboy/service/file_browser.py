"""Core filesystem browsing primitives used by file-picker modules."""

from __future__ import annotations

from pathlib import Path

from electroboy.state_store import StateError


def browse_directories(
    path: Path | str,
    *,
    show_hidden: bool = False,
) -> dict[str, object]:
    """Return visible child directories for a directory picker."""

    directory = _readable_directory(path)
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
            {"name": child.name, "path": str(child)} for child in children[:200]
        ],
    }


def browse_files(
    path: Path | str,
    *,
    show_hidden: bool = False,
) -> dict[str, object]:
    """Return visible child directories and files for a file picker."""

    return _browse_matching_files(path, show_hidden=show_hidden)


def browse_markdown_files(
    path: Path | str,
    *,
    show_hidden: bool = False,
) -> dict[str, object]:
    """Return child directories and Markdown files for a document picker."""

    return _browse_matching_files(
        path,
        show_hidden=show_hidden,
        suffix=".md",
    )


def _browse_matching_files(
    path: Path | str,
    *,
    show_hidden: bool,
    suffix: str | None = None,
) -> dict[str, object]:
    directory = _readable_directory(path)
    try:
        children = sorted(
            [
                child
                for child in directory.iterdir()
                if child.is_dir()
                or (
                    child.is_file()
                    and (suffix is None or child.suffix.lower() == suffix)
                )
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


def _readable_directory(path: Path | str) -> Path:
    directory = Path(path).expanduser().resolve()
    if not directory.exists():
        raise StateError(f"directory does not exist: {directory}")
    if not directory.is_dir():
        raise StateError(f"path is not a directory: {directory}")
    return directory


def _browser_entry_visible(path: Path, show_hidden: bool) -> bool:
    return show_hidden or not path.name.startswith(".")
