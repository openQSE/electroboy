"""Direct navigation over AI-written lesson JSONL files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .domain import CodeLearnerError
from .store import LearnerStore


class CourseNavigator:
    """Project course indexes and section records into stable learner views."""

    def __init__(self, root: Path | str, *, store: LearnerStore | None = None) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = store or LearnerStore(self.root)

    def open(
        self, mode: str, scope_id: str = "", section_id: str = ""
    ) -> dict[str, object]:
        slides = self._slides(mode, scope_id)
        if not slides:
            raise CodeLearnerError(f"{mode.title()} course is not available")
        position = next(
            (
                index
                for index, slide in enumerate(slides)
                if str(slide.get("id") or "") == section_id
            ),
            0,
        )
        state = {
            "mode": mode,
            "scope_id": scope_id,
            "position": position,
            "code_view": {},
        }
        self.store.write_state(self.store.navigation_path, state)
        return self._view(state, slides)

    def select(self, section_id: str) -> dict[str, object]:
        state = self._state()
        slides = self._slides(str(state["mode"]), str(state["scope_id"]))
        for index, slide in enumerate(slides):
            if str(slide.get("id") or "") == section_id:
                state["position"] = index
                self.store.write_state(self.store.navigation_path, state)
                return self._view(state, slides)
        raise CodeLearnerError(f"unknown course section: {section_id}")

    def move(self, direction: str) -> dict[str, object]:
        state = self._state()
        slides = self._slides(str(state["mode"]), str(state["scope_id"]))
        delta = -1 if direction == "previous" else 1
        state["position"] = max(
            0,
            min(len(slides) - 1, int(state.get("position") or 0) + delta),
        )
        self.store.write_state(self.store.navigation_path, state)
        return self._view(state, slides)

    def update_code_view(self, code_view: dict[str, object]) -> dict[str, object]:
        state = self._state()
        state["code_view"] = dict(code_view)
        self.store.write_state(self.store.navigation_path, state)
        return self._view(state)

    def state(self) -> dict[str, object]:
        state = self.store.read_object(self.store.navigation_path)
        if not state:
            return {}
        return self._view(state)

    def walkthrough(self, view: dict[str, object] | None = None) -> dict[str, object]:
        current_view = view or self.state()
        if not current_view:
            raise CodeLearnerError("no course is currently open")
        mode = str(current_view["mode"])
        scope_id = str(current_view["scope_id"])
        slides = self._slides(mode, scope_id)
        current = current_view["current"]
        return {
            "id": f"course:{mode}:{scope_id or 'current'}",
            "title": str(current_view.get("course_title") or mode.title()),
            "learning_mode": mode,
            "mode_target": scope_id,
            "current_step_id": str(current.get("id") or ""),
            "generated_at": "",
            "source_revision": "",
            "review_status": "generated",
            "qa_history": [],
            "can_go_back": False,
            "steps": [self._step(slide) for slide in slides],
        }

    def artifact(self, view: dict[str, object] | None = None) -> dict[str, object]:
        current_view = view or self.state()
        if not current_view:
            return {}
        current = current_view.get("current")
        if not isinstance(current, dict):
            return {}
        return {
            "artifact": "course",
            "path": str(current.get("lesson_path") or ""),
            "jsonl_path": str(current.get("lesson_path") or ""),
            "title": str(current.get("lesson_title") or "Course"),
        }

    def _state(self) -> dict[str, object]:
        state = self.store.read_object(self.store.navigation_path)
        if not state.get("mode"):
            raise CodeLearnerError("no course is currently open")
        return state

    def _view(
        self,
        state: dict[str, object],
        slides: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        mode = str(state.get("mode") or "")
        scope_id = str(state.get("scope_id") or "")
        records = slides if slides is not None else self._slides(mode, scope_id)
        if not records:
            raise CodeLearnerError(f"{mode.title()} course is not available")
        position = max(0, min(len(records) - 1, int(state.get("position") or 0)))
        current = records[position]
        index = self.store.course_index(mode, scope_id)
        return {
            "mode": mode,
            "scope_id": scope_id,
            "course_id": f"course:{mode}:{scope_id or 'current'}",
            "course_title": str(index.get("course_title") or mode.title()),
            "current": current,
            "navigation": {
                "position": position,
                "count": len(records),
                "can_go_previous": position > 0,
                "can_go_next": position + 1 < len(records),
                "code_view": dict(state.get("code_view") or {}),
            },
        }

    def _slides(self, mode: str, scope_id: str) -> list[dict[str, object]]:
        slides: list[dict[str, object]] = []
        for lesson in self.store.lessons(mode, scope_id):
            path = lesson.get("path")
            if not isinstance(path, Path):
                continue
            records = self.store.read_lesson(path)
            document = next(
                (
                    record
                    for record in records
                    if record.get("record_type") == "document"
                ),
                {},
            )
            sections = [
                record
                for record in records
                if record.get("record_type") == "section"
            ]
            sections.sort(key=lambda item: _integer(item.get("order"), 0))
            for index, section in enumerate(sections):
                slide = dict(section)
                slide.setdefault("id", f"{path.as_posix()}:{index}")
                slide["concept_title"] = str(lesson.get("concept_title") or "")
                slide["lesson_title"] = str(
                    lesson.get("lesson_title") or document.get("title") or "Lesson"
                )
                slide["lesson_path"] = self.store.relative(path)
                slides.append(slide)
        return slides

    @staticmethod
    def _step(slide: dict[str, Any]) -> dict[str, object]:
        references = slide.get("source_refs")
        first = references[0] if isinstance(references, list) and references else {}
        first = first if isinstance(first, dict) else {}
        path = str(first.get("path") or first.get("file_path") or "")
        start = _integer(first.get("start_line"), 1)
        end = _integer(first.get("end_line"), start)
        return {
            "id": str(slide.get("id") or ""),
            "title": str(slide.get("title") or "Slide"),
            "explanation": str(slide.get("body") or ""),
            "primary_reference": {
                "file_path": path,
                "start_line": start,
                "end_line": end,
                "symbol": str(first.get("symbol") or ""),
                "label": str(first.get("reason") or ""),
                "kind": "source",
            },
            "secondary_references": [],
            "prerequisites": [],
            "followups": [],
            "review_status": "generated",
            "concept_title": str(slide.get("concept_title") or ""),
            "lesson_title": str(slide.get("lesson_title") or ""),
        }


def _integer(value: object, default: int) -> int:
    try:
        return int(value or default)
    except (TypeError, ValueError):
        return default
