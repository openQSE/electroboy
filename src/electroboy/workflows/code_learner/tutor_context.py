"""Compact current-view context for the Code Learner tutor."""

from __future__ import annotations

from pathlib import Path

from .domain import CodeLearnerError
from .store import LearnerStore

TUTOR_CONTEXT_RELATIVE_PATH = ".electroboy/code-learner/tutor-context.json"


class TutorContextStore:
    """Persist the learner's current course and code view."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = LearnerStore(self.root)
        self.path = self.store.tutor_context_path

    def load(self, *, required: bool = True) -> dict[str, object] | None:
        value = self.store.read_object(self.path)
        if not value and required:
            raise CodeLearnerError(
                f"tutor context is missing: {TUTOR_CONTEXT_RELATIVE_PATH}"
            )
        return value or None

    def write_navigation(
        self,
        navigation: dict[str, object],
        *,
        project_id: str,
        writer_id: str,
    ) -> dict[str, object]:
        current = navigation.get("current")
        current = current if isinstance(current, dict) else {}
        nav = navigation.get("navigation")
        nav = nav if isinstance(nav, dict) else {}
        previous = self.load(required=False) or {}
        payload = {
            "schema_version": 1,
            "context_version": int(previous.get("context_version") or 0) + 1,
            "project_id": project_id,
            "writer_id": writer_id,
            "course": {
                "course_id": str(navigation.get("course_id") or ""),
                "mode": str(navigation.get("mode") or ""),
                "scope_id": str(navigation.get("scope_id") or ""),
                "concept_title": str(current.get("concept_title") or ""),
                "lesson_title": str(current.get("lesson_title") or ""),
                "lesson_path": str(current.get("lesson_path") or ""),
                "section_id": str(current.get("id") or ""),
                "section_title": str(current.get("title") or ""),
            },
            "source": dict(nav.get("code_view") or {}),
            "artifacts": {
                "components": self.store.relative(self.store.components_path),
                "modules": self.store.relative(self.store.modules_path),
                "raw_ai_knowledge": self.store.relative(
                    self.store.raw_knowledge_root
                ),
            },
        }
        self.store.write_state(self.path, payload)
        return payload


def tutor_bootstrap_prompt(root: Path | str, **_options: object) -> str:
    repository = Path(root).expanduser().resolve()
    return f"""
You are the ElectroBoy Code Learner tutor for this repository:
{repository}

Before answering every learner question, read this context file:
{TUTOR_CONTEXT_RELATIVE_PATH}

The file tells you which Architecture, Module, or Function course the learner
is viewing; the current concept, lesson, and slide; and the code file and range
currently visible in the workspace. Treat that file as the learner's current
question context. Inspect the referenced lesson JSONL and repository source as
needed before answering.

Answer the learner's actual question directly. Do not require the learner to
repeat filenames, symbols, line numbers, module names, or slide titles already
present in the context file. Explain the code at the depth implied by the
current course and question. Distinguish what the code demonstrates from what
you infer, but do not discuss ElectroBoy's internal orchestration.
""".strip()


def require_repository_read_capability(command: list[str], root: Path | str) -> None:
    repository = str(Path(root).expanduser().resolve())
    rendered = " ".join(command)
    if repository not in rendered or TUTOR_CONTEXT_RELATIVE_PATH not in rendered:
        raise CodeLearnerError("Code Learner tutor command lacks repository context")
