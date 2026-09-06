"""Small domain primitives retained by the Code Learner UI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from electroboy.service.file_watch import file_signature

MAX_SOURCE_BYTES = 2_000_000
LANGUAGE_BY_EXTENSION = {
    ".c": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cs": "csharp",
    ".css": "css",
    ".go": "go",
    ".h": "c",
    ".hpp": "cpp",
    ".html": "html",
    ".java": "java",
    ".js": "javascript",
    ".jsx": "javascript",
    ".json": "json",
    ".md": "markdown",
    ".py": "python",
    ".rs": "rust",
    ".sh": "shell",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".toml": "toml",
    ".yaml": "yaml",
    ".yml": "yaml",
}


class CodeLearnerError(RuntimeError):
    """Raised when Code Learner cannot satisfy a user operation."""


@dataclass(frozen=True)
class SourceFile:
    """A bounded source-file read for the learner code pane."""

    path: str
    language: str
    text: str
    line_count: int
    signature: dict[str, object]
    truncated: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "path": self.path,
            "language": self.language,
            "text": self.text,
            "line_count": self.line_count,
            "signature": self.signature,
            "truncated": self.truncated,
        }


class SourceAdapter:
    """Read a bounded repository source file for display."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()

    def resolve(self, relative_path: str) -> Path:
        requested = str(relative_path or "").strip()
        if not requested:
            raise CodeLearnerError("source path is required")
        path = Path(requested)
        resolved = (
            path.expanduser().resolve()
            if path.is_absolute()
            else (self.root / path).resolve()
        )
        if not _is_relative_to(resolved, self.root):
            raise CodeLearnerError("source path escapes the repository root")
        return resolved

    def relative_path(self, path: Path | str) -> str:
        resolved = Path(path).expanduser().resolve()
        if not _is_relative_to(resolved, self.root):
            raise CodeLearnerError("source path escapes the repository root")
        return resolved.relative_to(self.root).as_posix()

    def read_file(self, relative_path: str) -> SourceFile:
        path = self.resolve(relative_path)
        if not path.is_file():
            raise CodeLearnerError(f"source file not found: {relative_path}")
        signature = file_signature(path)
        size = int(signature.get("size") or 0)
        truncated = size > MAX_SOURCE_BYTES
        if truncated:
            with path.open("rb") as handle:
                text = handle.read(MAX_SOURCE_BYTES).decode(
                    "utf-8",
                    errors="replace",
                )
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
        return SourceFile(
            path=self.relative_path(path),
            language=language_for_path(path),
            text=text,
            line_count=len(text.splitlines()) or 1,
            signature=signature,
            truncated=truncated,
        )

    def source_payload(
        self,
        relative_path: str,
        *,
        start_line: int | None = None,
        end_line: int | None = None,
        padding: int = 80,
    ) -> dict[str, object]:
        source = self.read_file(relative_path)
        lines = source.text.splitlines() or [""]
        if start_line is None or end_line is None:
            window_start = 1
            window_end = len(lines)
            active_start = None
            active_end = None
        else:
            active_start = max(1, int(start_line))
            active_end = max(active_start, int(end_line))
            window_start = max(1, active_start - padding)
            window_end = min(len(lines), active_end + padding)
        rows = [
            {
                "number": number,
                "text": lines[number - 1],
                "active": bool(
                    active_start is not None
                    and active_start <= number <= int(active_end or active_start)
                ),
            }
            for number in range(window_start, window_end + 1)
        ]
        return {
            **source.to_dict(),
            "window_start_line": window_start,
            "window_end_line": window_end,
            "active_start_line": active_start,
            "active_end_line": active_end,
            "lines": rows,
        }


def language_for_path(path: str | Path) -> str:
    return LANGUAGE_BY_EXTENSION.get(Path(str(path)).suffix.lower(), "plain")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
