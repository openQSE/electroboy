"""Atomic repository-scoped persistence for Code Learner Phase 3."""

from __future__ import annotations

import json
import os
import shutil
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path

from electroboy.models import utc_now

from .domain import CodeLearnerError
from .phase3_contracts import validate_diagnostic, validate_terminal_result
from .source_manifest import PHASE3_ROOT


class Phase3Store:
    """Own Phase 3 storage paths without leaking them into domain services."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.state_root = self.root / PHASE3_ROOT
        self.components_root = self.state_root / "components"
        self.modules_root = self.state_root / "modules"
        self.knowledge_root = self.state_root / "knowledge"
        self.courses_root = self.state_root / "courses"
        self.attempts_root = self.state_root / "attempts"
        self.diagnostics_path = self.state_root / "diagnostics.jsonl"
        self.checkpoint_path = self.state_root / "checkpoint.json"
        self.progress_path = self.state_root / "progress.jsonl"
        self.result_path = self.state_root / "initialization-result.json"
        self.tutor_context_path = self.state_root / "tutor-context.json"
        self._lock = threading.RLock()

    def read_json(self, path: Path) -> dict[str, object] | None:
        if not path.is_file():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CodeLearnerError(f"could not load {self._relative(path)}: {error}")
        if not isinstance(value, dict):
            raise CodeLearnerError(f"{self._relative(path)} must contain an object")
        return value

    def read_jsonl(self, path: Path) -> list[dict[str, object]]:
        if not path.is_file():
            return []
        records: list[dict[str, object]] = []
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1
        ):
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise CodeLearnerError(
                    f"could not load {self._relative(path)} line {line_number}: "
                    f"{error.msg}"
                ) from error
            if not isinstance(value, dict):
                raise CodeLearnerError(
                    f"{self._relative(path)} line {line_number} is not an object"
                )
            records.append(value)
        return records

    def write_json(self, path: Path, value: Mapping[str, object]) -> None:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f"{path.suffix}.tmp")
            temporary.write_text(
                json.dumps(dict(value), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, path)

    def write_jsonl(
        self,
        path: Path,
        records: Iterable[Mapping[str, object]],
    ) -> None:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f"{path.suffix}.tmp")
            temporary.write_text(
                "".join(
                    json.dumps(dict(record), sort_keys=True) + "\n"
                    for record in records
                ),
                encoding="utf-8",
            )
            os.replace(temporary, path)

    def append_progress(self, record: Mapping[str, object]) -> None:
        payload = {"recorded_at": utc_now(), **dict(record)}
        self._append_jsonl(self.progress_path, payload)

    def save_diagnostic(self, record: Mapping[str, object]) -> dict[str, object]:
        normalized = validate_diagnostic(record)
        current = {
            str(item.get("id") or ""): item
            for item in self.read_jsonl(self.diagnostics_path)
        }
        current[str(normalized["id"])] = normalized
        self.write_jsonl(
            self.diagnostics_path,
            sorted(current.values(), key=lambda item: str(item.get("id") or "")),
        )
        return normalized

    def active_diagnostics(self, severity: str = "") -> list[dict[str, object]]:
        return [
            record
            for record in self.read_jsonl(self.diagnostics_path)
            if record.get("active", True) is True
            and (not severity or record.get("severity") == severity)
        ]

    def save_terminal_result(self, record: Mapping[str, object]) -> dict[str, object]:
        normalized = validate_terminal_result(record)
        self.write_json(self.result_path, normalized)
        return normalized

    def load_terminal_result(self) -> dict[str, object] | None:
        value = self.read_json(self.result_path)
        return validate_terminal_result(value) if value is not None else None

    def clear(self) -> dict[str, int]:
        files = (
            [path for path in self.state_root.rglob("*") if path.is_file()]
            if self.state_root.is_dir()
            else []
        )
        size = sum(path.stat().st_size for path in files)
        if self.state_root.exists():
            shutil.rmtree(self.state_root)
        return {"removed_file_count": len(files), "removed_bytes": size}

    def _append_jsonl(self, path: Path, value: Mapping[str, object]) -> None:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(dict(value), sort_keys=True) + "\n")

    def _relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return str(path)
