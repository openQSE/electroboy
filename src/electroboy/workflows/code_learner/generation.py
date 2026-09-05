"""Explicit Code Learner storage-generation selection and compatibility."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from electroboy.models import utc_now

from .domain import CodeLearnerError

STATE_ROOT = Path(".electroboy") / "code-learner"
GENERATION_PATH = STATE_ROOT / "generation.json"
SUPPORTED_GENERATIONS = frozenset({"phase2", "phase3"})


@dataclass(frozen=True)
class LearnerGeneration:
    """The durable format selected for one learned repository revision."""

    generation: str
    repository_revision: str
    selected_at: str

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "generation": self.generation,
            "repository_revision": self.repository_revision,
            "selected_at": self.selected_at,
        }


class LearnerGenerationStore:
    """Keep Phase 2 and Phase 3 canonical writes explicitly separated."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / GENERATION_PATH

    def load(self) -> LearnerGeneration | None:
        if not self.path.is_file():
            return self._detect_legacy_phase2()
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CodeLearnerError(
                f"could not load learner generation metadata: {error}"
            ) from error
        if not isinstance(value, dict) or value.get("schema_version") != 1:
            raise CodeLearnerError("learner generation metadata is invalid")
        generation = str(value.get("generation") or "")
        if generation not in SUPPORTED_GENERATIONS:
            raise CodeLearnerError(
                f"unsupported learner generation: {generation or '<empty>'}"
            )
        return LearnerGeneration(
            generation=generation,
            repository_revision=str(value.get("repository_revision") or ""),
            selected_at=str(value.get("selected_at") or ""),
        )

    def select(
        self,
        generation: str,
        repository_revision: str,
        *,
        replace: bool = False,
    ) -> LearnerGeneration:
        selected = str(generation or "").strip().lower()
        if selected not in SUPPORTED_GENERATIONS:
            raise CodeLearnerError(f"unsupported learner generation: {generation}")
        current = self.load()
        if current is not None and current.generation != selected and not replace:
            raise CodeLearnerError(
                "learner state already uses "
                f"{current.generation}; clear or explicitly migrate it before "
                f"selecting {selected}"
            )
        value = LearnerGeneration(
            generation=selected,
            repository_revision=str(repository_revision or ""),
            selected_at=utc_now(),
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(value.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)
        return value

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def _detect_legacy_phase2(self) -> LearnerGeneration | None:
        phase2_paths = (
            self.root / STATE_ROOT / "knowledge" / "manifest.jsonl",
            self.root / STATE_ROOT / "course-corpus.jsonl",
        )
        if not any(path.is_file() for path in phase2_paths):
            return None
        return LearnerGeneration(
            generation="phase2",
            repository_revision="",
            selected_at="",
        )
