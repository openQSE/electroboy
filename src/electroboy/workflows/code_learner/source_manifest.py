"""Deterministic Phase 3 repository file inventory and persistence."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from electroboy.models import utc_now

from .domain import CodeLearnerError, language_for_path
from .phase3_contracts import validate_manifest, validate_source_files

PHASE3_ROOT = Path(".electroboy") / "code-learner" / "phase3"
DEFAULT_EXCLUDED_DIRECTORIES = frozenset(
    {
        ".codex",
        ".electroboy",
        ".git",
        ".hg",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".svn",
        ".tox",
        ".venv",
        "__pycache__",
        "build",
        "dist",
        "htmlcov",
        "node_modules",
        "site-packages",
        "vendor",
    }
)


@dataclass(frozen=True)
class SourceManifestSnapshot:
    """One validated source manifest and its ordered file dictionary."""

    manifest: dict[str, object]
    files: tuple[dict[str, object], ...]

    @property
    def revision(self) -> str:
        return str(self.manifest["repository_revision"])

    def by_id(self) -> dict[str, dict[str, object]]:
        return {str(record["id"]): dict(record) for record in self.files}


@dataclass(frozen=True)
class _EnumeratedPath:
    path: str
    source_status: str
    git_mode: str = ""
    submodule_revision: str = ""


class SourceManifestService:
    """Enumerate and query repository files without semantic interpretation."""

    def __init__(
        self,
        root: Path | str,
        *,
        excluded_directories: Iterable[str] = DEFAULT_EXCLUDED_DIRECTORIES,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.state_root = self.root / PHASE3_ROOT / "source"
        self.manifest_path = self.state_root / "manifest.json"
        self.files_path = self.state_root / "files.jsonl"
        self.excluded_directories = frozenset(
            str(item) for item in excluded_directories
        )
        self._lock = threading.RLock()

    def generate(self) -> SourceManifestSnapshot:
        """Build and atomically persist a complete selected-file snapshot."""

        if not self.root.is_dir():
            raise CodeLearnerError(f"source root is not a directory: {self.root}")
        git_root = self._git_root()
        enumerated = self._git_paths() if git_root == self.root else self._walk_paths()
        provisional = [self._file_record(item, "pending") for item in enumerated]
        revision = _source_revision(provisional, git_head=self._git_head())
        files = [{**record, "repository_revision": revision} for record in provisional]
        validate_source_files(files, repository_revision=revision)
        manifest = {
            "schema_version": 1,
            "record_type": "source_manifest",
            "id": "source_manifest:current",
            "learner_generation": "phase3",
            "repository_revision": revision,
            "repository_root_name": self.root.name,
            "scope_path": ".",
            "status": "complete",
            "file_ids": [str(record["id"]) for record in files],
            "file_count": len(files),
            "raw_tag_count": 0,
            "git_head": self._git_head(),
            "inclusion_policy": {
                "git": "tracked files including working-tree modifications",
                "non_git": "all regular files not in excluded directories",
                "untracked": "excluded by default in Git repositories",
                "generated_and_vendored": "excluded by directory policy",
            },
            "excluded_regions": [
                {"path": name, "reason": "excluded directory policy"}
                for name in sorted(self.excluded_directories)
            ],
            "generated_at": utc_now(),
        }
        validate_manifest(
            manifest,
            manifest_type="source_manifest",
            repository_revision=revision,
        )
        self._save(manifest, files)
        return SourceManifestSnapshot(manifest, tuple(files))

    def load(self) -> SourceManifestSnapshot | None:
        if not self.manifest_path.is_file() or not self.files_path.is_file():
            return None
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            files = [
                json.loads(line)
                for line in self.files_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        except (OSError, json.JSONDecodeError) as error:
            raise CodeLearnerError(f"could not load Phase 3 source manifest: {error}")
        if not isinstance(manifest, dict) or any(
            not isinstance(record, dict) for record in files
        ):
            raise CodeLearnerError("Phase 3 source manifest storage is invalid")
        revision = str(manifest.get("repository_revision") or "")
        validate_manifest(
            manifest,
            manifest_type="source_manifest",
            repository_revision=revision,
        )
        normalized = validate_source_files(files, repository_revision=revision)
        if manifest.get("file_ids") != [record["id"] for record in normalized]:
            raise CodeLearnerError("source manifest file IDs do not match files.jsonl")
        return SourceManifestSnapshot(manifest, tuple(normalized))

    def query(
        self,
        *,
        file_id: str = "",
        path: str = "",
        language: str = "",
        source_status: str = "",
    ) -> list[dict[str, object]]:
        snapshot = self.load()
        if snapshot is None:
            return []
        return [
            dict(record)
            for record in snapshot.files
            if (not file_id or record.get("id") == file_id)
            and (not path or record.get("path") == _normalize_path(path))
            and (not language or record.get("language") == language)
            and (not source_status or record.get("source_status") == source_status)
        ]

    def _save(
        self,
        manifest: Mapping[str, object],
        files: Iterable[Mapping[str, object]],
    ) -> None:
        with self._lock:
            self.state_root.mkdir(parents=True, exist_ok=True)
            manifest_tmp = self.manifest_path.with_suffix(".tmp")
            files_tmp = self.files_path.with_suffix(".tmp")
            manifest_tmp.write_text(
                json.dumps(dict(manifest), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            files_tmp.write_text(
                "".join(
                    json.dumps(dict(record), sort_keys=True) + "\n" for record in files
                ),
                encoding="utf-8",
            )
            os.replace(files_tmp, self.files_path)
            os.replace(manifest_tmp, self.manifest_path)

    def _git_root(self) -> Path | None:
        result = _run_git(self.root, "rev-parse", "--show-toplevel")
        if result is None:
            return None
        try:
            return Path(result.strip()).resolve()
        except OSError:
            return None

    def _git_head(self) -> str:
        result = _run_git(self.root, "rev-parse", "HEAD")
        return result.strip() if result else ""

    def _git_paths(self) -> list[_EnumeratedPath]:
        output = _run_git(self.root, "ls-files", "--stage", "-z")
        if output is None:
            return self._walk_paths()
        modified = set(
            filter(
                None,
                (_run_git(self.root, "diff", "--name-only", "-z") or "").split("\0"),
            )
        )
        paths: list[_EnumeratedPath] = []
        for entry in output.split("\0"):
            if not entry:
                continue
            metadata, separator, raw_path = entry.partition("\t")
            if not separator:
                continue
            mode, object_id, _stage = metadata.split(" ", 2)
            normalized = _normalize_path(raw_path)
            if self._excluded(normalized):
                continue
            if mode == "160000":
                paths.append(
                    _EnumeratedPath(
                        normalized,
                        "submodule",
                        git_mode=mode,
                        submodule_revision=object_id,
                    )
                )
                continue
            path = self.root / normalized
            if path.is_file() or path.is_symlink():
                paths.append(
                    _EnumeratedPath(
                        normalized,
                        "modified" if normalized in modified else "tracked",
                        git_mode=mode,
                    )
                )
        return sorted(paths, key=lambda item: item.path)

    def _walk_paths(self) -> list[_EnumeratedPath]:
        selected: list[_EnumeratedPath] = []
        for current, dirnames, filenames in os.walk(self.root, followlinks=False):
            relative_dir = Path(current).relative_to(self.root)
            dirnames[:] = sorted(
                name
                for name in dirnames
                if name not in self.excluded_directories
                and not self._excluded((relative_dir / name).as_posix())
            )
            for name in sorted(filenames):
                relative = _normalize_path((relative_dir / name).as_posix())
                if self._excluded(relative):
                    continue
                selected.append(_EnumeratedPath(relative, "non_git"))
        return selected

    def _excluded(self, relative_path: str) -> bool:
        return any(
            part in self.excluded_directories
            for part in PurePosixPath(relative_path).parts
        )

    def _file_record(
        self,
        item: _EnumeratedPath,
        repository_revision: str,
    ) -> dict[str, object]:
        path = self.root / item.path
        if item.source_status == "submodule":
            size = 0
            digest = f"gitlink:{item.submodule_revision}"
            executable = False
            symlink = False
            symlink_target = ""
        else:
            try:
                metadata = path.lstat()
            except OSError as error:
                raise CodeLearnerError(
                    f"could not inspect source file {item.path}: {error}"
                )
            symlink = stat.S_ISLNK(metadata.st_mode)
            symlink_target = os.readlink(path) if symlink else ""
            content = symlink_target.encode() if symlink else path.read_bytes()
            size = len(content)
            digest = "sha256:" + hashlib.sha256(content).hexdigest()
            executable = bool(metadata.st_mode & stat.S_IXUSR)
        return {
            "schema_version": 1,
            "record_type": "source_file",
            "id": f"file:{item.path}",
            "repository_revision": repository_revision,
            "path": item.path,
            "content_hash": digest,
            "size": size,
            "language": language_for_path(item.path),
            "source_status": item.source_status,
            "executable": executable,
            "symlink": symlink,
            "symlink_target": symlink_target,
            "git_mode": item.git_mode,
            "submodule_revision": item.submodule_revision,
        }


def _normalize_path(value: str) -> str:
    path = PurePosixPath(str(value).replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        raise CodeLearnerError(f"source path escapes repository root: {value}")
    normalized = path.as_posix()
    if normalized.startswith("./"):
        normalized = normalized[2:]
    if not normalized or normalized == ".":
        raise CodeLearnerError("source path must name a file")
    return normalized


def _source_revision(
    records: Iterable[Mapping[str, object]],
    *,
    git_head: str,
) -> str:
    digest = hashlib.sha256()
    digest.update(git_head.encode())
    digest.update(b"\0")
    for record in sorted(records, key=lambda item: str(item.get("path") or "")):
        digest.update(str(record.get("path") or "").encode())
        digest.update(b"\0")
        digest.update(str(record.get("content_hash") or "").encode())
        digest.update(b"\0")
    return f"source-signature:{digest.hexdigest()[:24]}"


def _run_git(root: Path, *arguments: str) -> str | None:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), *arguments],
            capture_output=True,
            check=False,
            timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.decode("utf-8", errors="surrogateescape")
