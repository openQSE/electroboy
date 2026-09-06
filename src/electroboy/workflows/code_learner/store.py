"""Repository-scoped storage for trusted Code Learner output."""

from __future__ import annotations

import json
import os
import shutil
import threading
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from electroboy.models import utc_now

from .domain import CodeLearnerError


class LearnerStore:
    """Own paths and ElectroBoy-authored state around AI-written courses."""

    _locks_guard = threading.Lock()
    _locks: dict[str, threading.RLock] = {}

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.state_root = self.root / ".electroboy" / "code-learner"
        self.courses_root = self.state_root / "courses"
        self.course_root = self.courses_root / self.root.name
        self.raw_knowledge_root = self.course_root / "raw-ai-knowledge"
        self.components_path = self.course_root / "components.json"
        self.modules_path = self.course_root / "modules.json"
        self.architecture_root = self.course_root / "architecture"
        self.module_courses_root = self.course_root / "modules"
        self.function_courses_root = self.course_root / "functions"
        self.status_path = self.state_root / "status.json"
        self.progress_path = self.state_root / "progress.jsonl"
        self.navigation_path = self.state_root / "navigation.json"
        self.tutor_context_path = self.state_root / "tutor-context.json"
        self.sessions_path = self.state_root / "agent-sessions.json"
        key = str(self.state_root)
        with self._locks_guard:
            self._lock = self._locks.setdefault(key, threading.RLock())

    def initialize_layout(self) -> None:
        self.raw_knowledge_root.mkdir(parents=True, exist_ok=True)

    def course_directory(self, mode: str, scope_id: str = "") -> Path:
        if mode == "architecture":
            return self.architecture_root
        if mode == "module":
            return self.module_courses_root / scope_id
        if mode == "function":
            return self.function_courses_root / scope_id
        raise CodeLearnerError(f"unsupported course mode: {mode}")

    def course_index_path(self, mode: str, scope_id: str = "") -> Path:
        return self.course_directory(mode, scope_id) / "course.json"

    def read_value(self, path: Path) -> Any:
        if not path.is_file():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CodeLearnerError(f"could not read {self.relative(path)}: {error}")

    def read_object(self, path: Path) -> dict[str, object]:
        value = self.read_value(path)
        return dict(value) if isinstance(value, dict) else {}

    def read_array(self, path: Path) -> list[dict[str, object]]:
        value = self.read_value(path)
        if not isinstance(value, list):
            return []
        return [dict(item) for item in value if isinstance(item, dict)]

    def read_lesson(self, path: Path) -> list[dict[str, object]]:
        if not path.is_file():
            return []
        records: list[dict[str, object]] = []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            raise CodeLearnerError(f"could not read {self.relative(path)}: {error}")
        for line in lines:
            if not line.strip():
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                records.append(dict(value))
        return records

    def write_state(self, path: Path, value: Mapping[str, object]) -> None:
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f"{path.suffix}.tmp")
            temporary.write_text(
                json.dumps(dict(value), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary, path)

    def load_status(self) -> dict[str, object]:
        return self.read_object(self.status_path)

    def save_status(self, **changes: object) -> dict[str, object]:
        with self._lock:
            status = self.load_status()
            status.update(changes)
            status["updated_at"] = utc_now()
            self.write_state(self.status_path, status)
            return status

    def append_progress(self, record: Mapping[str, object]) -> None:
        payload = {"recorded_at": utc_now(), **dict(record)}
        with self._lock:
            self.progress_path.parent.mkdir(parents=True, exist_ok=True)
            with self.progress_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(payload, sort_keys=True) + "\n")

    def progress(self, limit: int = 250) -> list[dict[str, object]]:
        records = self.read_lesson(self.progress_path)
        return records[-max(1, limit) :]

    def components(self) -> list[dict[str, object]]:
        return self.read_array(self.components_path)

    def modules(self) -> list[dict[str, object]]:
        return self.read_array(self.modules_path)

    def course_index(self, mode: str, scope_id: str = "") -> dict[str, object]:
        return self.read_object(self.course_index_path(mode, scope_id))

    def lessons(self, mode: str, scope_id: str = "") -> list[dict[str, object]]:
        course_root = self.course_directory(mode, scope_id)
        index = self.course_index(mode, scope_id)
        lessons: list[dict[str, object]] = []
        concepts = index.get("concepts")
        if not isinstance(concepts, list):
            return lessons
        for concept_order, concept in enumerate(concepts):
            if not isinstance(concept, dict):
                continue
            directory_name = str(concept.get("directory_name") or "")
            entries = concept.get("lessons")
            if not isinstance(entries, list):
                continue
            for lesson_order, lesson in enumerate(entries):
                if not isinstance(lesson, dict):
                    continue
                file_name = str(lesson.get("file_name") or "")
                path = course_root / directory_name / file_name
                lessons.append(
                    {
                        **lesson,
                        "concept_title": str(concept.get("concept_title") or ""),
                        "concept_order": concept_order,
                        "lesson_order": lesson_order,
                        "path": path,
                    }
                )
        return lessons

    def course_ready(self, mode: str, scope_id: str = "") -> bool:
        return any(
            isinstance(lesson.get("path"), Path)
            and lesson["path"].is_file()
            and bool(self.read_lesson(lesson["path"]))
            for lesson in self.lessons(mode, scope_id)
        )

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

    def relative(self, path: Path) -> str:
        try:
            return path.relative_to(self.root).as_posix()
        except ValueError:
            return str(path)
