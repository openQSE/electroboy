"""Domain model and deterministic planning for the Code Learner workflow."""

from __future__ import annotations

import ast
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from electroboy.models import utc_now
from electroboy.service.file_watch import file_signature
from electroboy.state_store import StateError

WORKFLOW_ID = "code-learner"
LEARNER_STATE_RELATIVE_PATH = (
    Path(".electroboy") / "code-learner" / "walkthroughs.json"
)
LEARNER_CORPUS_RELATIVE_PATH = (
    Path(".electroboy") / "code-learner" / "course-corpus.jsonl"
)
LEARNER_INIT_PROGRESS_RELATIVE_PATH = (
    Path(".electroboy") / "code-learner" / "initialize-progress.jsonl"
)
COURSE_CORPUS_SCHEMA_VERSION = 1
SUPPORTED_LEARNING_MODES = frozenset({"architecture", "module", "function"})
COURSE_CORPUS_RECORD_TYPES = frozenset(
    {
        "course_manifest",
        "architecture_step",
        "module",
        "module_step",
        "function_index_entry",
        "function_lesson",
        "diagnostic",
    }
)
IGNORED_COURSE_CORPUS_RECORD_TYPES = frozenset({"progress"})
SOURCE_FILE_LIMIT = 500
SYMBOL_FILE_LIMIT = 300
MAX_SOURCE_BYTES = 2_000_000
QA_HISTORY_LIMIT = 40

IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".agent-pipeline",
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
SOURCE_EXTENSIONS = frozenset(LANGUAGE_BY_EXTENSION)


class CodeLearnerError(RuntimeError):
    """Raised when Code Learner cannot satisfy a user operation."""


@dataclass(frozen=True)
class SourceReference:
    """A durable pointer from course text to source code."""

    file_path: str
    start_line: int = 1
    end_line: int = 1
    symbol: str = ""
    label: str = ""
    kind: str = "source"

    def normalized(self) -> "SourceReference":
        start = max(1, int(self.start_line or 1))
        end = max(start, int(self.end_line or start))
        return SourceReference(
            file_path=self.file_path,
            start_line=start,
            end_line=end,
            symbol=self.symbol,
            label=self.label,
            kind=self.kind,
        )

    def to_dict(self) -> dict[str, object]:
        reference = self.normalized()
        return {
            "file_path": reference.file_path,
            "start_line": reference.start_line,
            "end_line": reference.end_line,
            "symbol": reference.symbol,
            "label": reference.label,
            "kind": reference.kind,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "SourceReference":
        return cls(
            file_path=str(data.get("file_path") or ""),
            start_line=int(data.get("start_line") or 1),
            end_line=int(data.get("end_line") or data.get("start_line") or 1),
            symbol=str(data.get("symbol") or ""),
            label=str(data.get("label") or ""),
            kind=str(data.get("kind") or "source"),
        ).normalized()


@dataclass(frozen=True)
class WalkthroughStep:
    """One lesson step inside a Code Learner course."""

    id: str
    title: str
    explanation: str
    primary_reference: SourceReference
    secondary_references: tuple[SourceReference, ...] = ()
    prerequisites: tuple[str, ...] = ()
    followups: tuple[str, ...] = ()
    confidence: float | None = None
    review_status: str = "generated"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "explanation": self.explanation,
            "primary_reference": self.primary_reference.to_dict(),
            "secondary_references": [
                reference.to_dict() for reference in self.secondary_references
            ],
            "prerequisites": list(self.prerequisites),
            "followups": list(self.followups),
            "confidence": self.confidence,
            "review_status": self.review_status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "WalkthroughStep":
        primary = data.get("primary_reference")
        if not isinstance(primary, dict):
            primary = {}
        secondary = data.get("secondary_references")
        return cls(
            id=str(data.get("id") or ""),
            title=str(data.get("title") or ""),
            explanation=str(data.get("explanation") or ""),
            primary_reference=SourceReference.from_dict(primary),
            secondary_references=tuple(
                SourceReference.from_dict(reference)
                for reference in (secondary if isinstance(secondary, list) else [])
                if isinstance(reference, dict)
            ),
            prerequisites=tuple(
                str(item)
                for item in (
                    data.get("prerequisites")
                    if isinstance(data.get("prerequisites"), list)
                    else []
                )
            ),
            followups=tuple(
                str(item)
                for item in (
                    data.get("followups")
                    if isinstance(data.get("followups"), list)
                    else []
                )
            ),
            confidence=(
                float(data["confidence"])
                if isinstance(data.get("confidence"), (int, float))
                else None
            ),
            review_status=str(data.get("review_status") or "generated"),
        )


@dataclass(frozen=True)
class Walkthrough:
    """Durable Code Learner course data independent from the UI layout."""

    id: str
    title: str
    source_root: str
    learning_mode: str
    mode_target: str = ""
    intended_audience: str = ""
    steps: tuple[WalkthroughStep, ...] = ()
    current_step_id: str = ""
    generated_at: str = field(default_factory=utc_now)
    source_revision: str = ""
    review_status: str = "generated"
    qa_history: tuple[dict[str, object], ...] = ()

    def current_step(self) -> WalkthroughStep | None:
        if self.current_step_id:
            for step in self.steps:
                if step.id == self.current_step_id:
                    return step
        return self.steps[0] if self.steps else None

    def with_current_step(self, step_id: str) -> "Walkthrough":
        if not any(step.id == step_id for step in self.steps):
            raise CodeLearnerError(f"unknown walkthrough step: {step_id}")
        return Walkthrough(
            id=self.id,
            title=self.title,
            source_root=self.source_root,
            learning_mode=self.learning_mode,
            mode_target=self.mode_target,
            intended_audience=self.intended_audience,
            steps=self.steps,
            current_step_id=step_id,
            generated_at=self.generated_at,
            source_revision=self.source_revision,
            review_status=self.review_status,
            qa_history=self.qa_history,
        )

    def with_qa_history(self, history: list[dict[str, object]]) -> "Walkthrough":
        return Walkthrough(
            id=self.id,
            title=self.title,
            source_root=self.source_root,
            learning_mode=self.learning_mode,
            mode_target=self.mode_target,
            intended_audience=self.intended_audience,
            steps=self.steps,
            current_step_id=self.current_step_id,
            generated_at=self.generated_at,
            source_revision=self.source_revision,
            review_status=self.review_status,
            qa_history=tuple(history[-QA_HISTORY_LIMIT:]),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "title": self.title,
            "source_root": self.source_root,
            "learning_mode": self.learning_mode,
            "mode_target": self.mode_target,
            "intended_audience": self.intended_audience,
            "steps": [step.to_dict() for step in self.steps],
            "current_step_id": self.current_step_id,
            "generated_at": self.generated_at,
            "source_revision": self.source_revision,
            "review_status": self.review_status,
            "qa_history": list(self.qa_history),
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Walkthrough":
        steps = tuple(
            WalkthroughStep.from_dict(step)
            for step in (data.get("steps") if isinstance(data.get("steps"), list) else [])
            if isinstance(step, dict)
        )
        current_step_id = str(data.get("current_step_id") or "")
        if not current_step_id and steps:
            current_step_id = steps[0].id
        qa_history = data.get("qa_history")
        return cls(
            id=str(data.get("id") or ""),
            title=str(data.get("title") or ""),
            source_root=str(data.get("source_root") or ""),
            learning_mode=str(data.get("learning_mode") or ""),
            mode_target=str(data.get("mode_target") or ""),
            intended_audience=str(data.get("intended_audience") or ""),
            steps=steps,
            current_step_id=current_step_id,
            generated_at=str(data.get("generated_at") or ""),
            source_revision=str(data.get("source_revision") or ""),
            review_status=str(data.get("review_status") or "generated"),
            qa_history=tuple(
                dict(item)
                for item in (qa_history if isinstance(qa_history, list) else [])
                if isinstance(item, dict)
            ),
        )


@dataclass(frozen=True)
class SourceFile:
    """A read result from the source adapter."""

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


@dataclass(frozen=True)
class SymbolCandidate:
    """A discovered symbol candidate for Function mode."""

    name: str
    qualified_name: str
    kind: str
    file_path: str
    start_line: int
    end_line: int
    calls: tuple[str, ...] = ()

    def reference(self) -> SourceReference:
        return SourceReference(
            file_path=self.file_path,
            start_line=self.start_line,
            end_line=self.end_line,
            symbol=self.qualified_name,
            label=self.qualified_name,
            kind=self.kind,
        ).normalized()

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "qualified_name": self.qualified_name,
            "kind": self.kind,
            "file_path": self.file_path,
            "start_line": self.start_line,
            "end_line": self.end_line,
            "calls": list(self.calls),
        }


@dataclass(frozen=True)
class SymbolResolution:
    """Result of resolving a user-provided function or symbol name."""

    status: str
    symbol: SymbolCandidate | None = None
    candidates: tuple[SymbolCandidate, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "symbol": self.symbol.to_dict() if self.symbol else None,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


@dataclass(frozen=True)
class RepositoryAnalysis:
    """Source summary used by course planners and the start UI."""

    source_root: str
    source_files: tuple[str, ...]
    language_counts: dict[str, int]
    modules: tuple[dict[str, object], ...]
    symbols: tuple[SymbolCandidate, ...]
    truncated: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "source_root": self.source_root,
            "source_files": list(self.source_files),
            "language_counts": dict(self.language_counts),
            "modules": [dict(module) for module in self.modules],
            "symbols": [symbol.to_dict() for symbol in self.symbols],
            "truncated": self.truncated,
        }


class SourceAdapter:
    """Read source files and resolve source locations within a repository."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()

    def resolve(self, relative_path: str) -> Path:
        requested = str(relative_path or "").strip()
        if not requested:
            raise CodeLearnerError("source path is required")
        path = Path(requested)
        if path.is_absolute():
            resolved = path.expanduser().resolve()
        else:
            resolved = (self.root / path).resolve()
        if not _is_relative_to(resolved, self.root):
            raise CodeLearnerError("source path escapes the repository root")
        return resolved

    def relative_path(self, path: Path | str) -> str:
        resolved = Path(path).expanduser().resolve()
        if not _is_relative_to(resolved, self.root):
            raise CodeLearnerError("source path escapes the repository root")
        return resolved.relative_to(self.root).as_posix()

    def language(self, relative_path: str) -> str:
        return language_for_path(relative_path)

    def read_file(self, relative_path: str) -> SourceFile:
        path = self.resolve(relative_path)
        if not path.is_file():
            raise CodeLearnerError(f"source file not found: {relative_path}")
        signature = file_signature(path)
        size = int(signature.get("size") or 0)
        truncated = size > MAX_SOURCE_BYTES
        if truncated:
            with path.open("rb") as handle:
                data = handle.read(MAX_SOURCE_BYTES)
            text = data.decode("utf-8", errors="replace")
        else:
            text = path.read_text(encoding="utf-8", errors="replace")
        return SourceFile(
            path=self.relative_path(path),
            language=self.language(path.as_posix()),
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
        lines = source.text.splitlines()
        if not lines:
            lines = [""]
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
                "active": (
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

    def extract_range(
        self,
        reference: SourceReference,
        *,
        max_lines: int = 80,
    ) -> str:
        source = self.read_file(reference.file_path)
        lines = source.text.splitlines()
        start = max(1, reference.start_line)
        end = min(len(lines), max(reference.end_line, start + max_lines - 1))
        return "\n".join(
            f"{number}: {lines[number - 1]}" for number in range(start, end + 1)
        )

    def verify_reference(self, reference: SourceReference) -> dict[str, object]:
        try:
            source = self.read_file(reference.file_path)
        except CodeLearnerError as error:
            return {
                "ok": False,
                "status": "missing",
                "message": str(error),
                "reference": reference.to_dict(),
            }
        normalized = reference.normalized()
        ok = normalized.start_line <= source.line_count
        return {
            "ok": ok,
            "status": "ok" if ok else "range-out-of-bounds",
            "message": (
                ""
                if ok
                else f"line {normalized.start_line} exceeds {source.line_count}"
            ),
            "reference": normalized.to_dict(),
            "signature": source.signature,
            "line_count": source.line_count,
            "language": source.language,
        }


class CodeLearnerStore:
    """Durable walkthrough storage under a repository root."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.path = self.root / LEARNER_STATE_RELATIVE_PATH
        self.corpus_path = self.root / LEARNER_CORPUS_RELATIVE_PATH
        self.initialization_progress_path = (
            self.root / LEARNER_INIT_PROGRESS_RELATIVE_PATH
        )
        self.initialization_progress_relative_path = (
            LEARNER_INIT_PROGRESS_RELATIVE_PATH
        )

    def load_corpus_records(self) -> list[dict[str, object]]:
        """Load the AI-generated JSONL learning corpus for this repository."""

        if not self.corpus_path.exists():
            return []
        return parse_course_corpus_jsonl(
            self.corpus_path.read_text(encoding="utf-8"),
        )

    def save_corpus_jsonl(self, text: str) -> list[dict[str, object]]:
        """Validate and persist raw AI JSONL course material."""

        records = parse_course_corpus_jsonl(text)
        self.save_corpus_records(records)
        return records

    def save_corpus_records(self, records: list[dict[str, object]]) -> None:
        if not records:
            raise CodeLearnerError("AI course corpus is empty")
        self.corpus_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.corpus_path.with_suffix(
            f"{self.corpus_path.suffix}.{uuid4().hex}.tmp"
        )
        temporary.write_text(
            "\n".join(json.dumps(record, sort_keys=True) for record in records)
            + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.corpus_path)

    def course_corpus_payload(self) -> dict[str, object] | None:
        records = self.load_corpus_records()
        if not records:
            return None
        return course_corpus_payload(records)

    def corpus_analysis(self) -> RepositoryAnalysis | None:
        records = self.load_corpus_records()
        if not records:
            return None
        return analysis_from_course_corpus(self.root, records)

    def load(self) -> dict[str, object]:
        if not self.path.exists():
            return {
                "schema_version": 1,
                "current_walkthrough_id": "",
                "walkthroughs": [],
            }
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise StateError(f"could not load Code Learner state: {error}") from error
        if not isinstance(payload, dict):
            raise StateError("Code Learner state is not a JSON object")
        payload.setdefault("schema_version", 1)
        payload.setdefault("current_walkthrough_id", "")
        payload.setdefault("walkthroughs", [])
        return payload

    def walkthroughs(self) -> list[Walkthrough]:
        payload = self.load()
        entries = payload.get("walkthroughs")
        return [
            Walkthrough.from_dict(entry)
            for entry in (entries if isinstance(entries, list) else [])
            if isinstance(entry, dict)
        ]

    def current_walkthrough_id(self) -> str:
        return str(self.load().get("current_walkthrough_id") or "")

    def current(self) -> Walkthrough | None:
        current_id = self.current_walkthrough_id()
        walkthroughs = self.walkthroughs()
        if current_id:
            for walkthrough in walkthroughs:
                if walkthrough.id == current_id:
                    return walkthrough
        return walkthroughs[0] if walkthroughs else None

    def get(self, walkthrough_id: str) -> Walkthrough:
        requested = str(walkthrough_id or "").strip()
        if not requested:
            current = self.current()
            if current is None:
                raise CodeLearnerError("no Code Learner walkthrough exists")
            return current
        for walkthrough in self.walkthroughs():
            if walkthrough.id == requested:
                return walkthrough
        raise CodeLearnerError(f"unknown Code Learner walkthrough: {requested}")

    def save_walkthrough(self, walkthrough: Walkthrough) -> Walkthrough:
        entries = [
            existing
            for existing in self.walkthroughs()
            if existing.id != walkthrough.id
        ]
        entries.insert(0, walkthrough)
        payload = {
            "schema_version": 1,
            "current_walkthrough_id": walkthrough.id,
            "walkthroughs": [entry.to_dict() for entry in entries[:50]],
        }
        self._write(payload)
        return walkthrough

    def set_current_step(self, walkthrough_id: str, step_id: str) -> Walkthrough:
        walkthrough = self.get(walkthrough_id).with_current_step(step_id)
        return self.save_walkthrough(walkthrough)

    def record_question(
        self,
        walkthrough_id: str,
        question: str,
        context: dict[str, object],
    ) -> Walkthrough:
        walkthrough = self.get(walkthrough_id)
        step = walkthrough.current_step()
        history = [
            *walkthrough.qa_history,
            {
                "asked_at": utc_now(),
                "question": question,
                "step_id": step.id if step else "",
                "file_path": str(context.get("file_path") or ""),
                "start_line": context.get("start_line"),
                "end_line": context.get("end_line"),
            },
        ]
        walkthrough = walkthrough.with_qa_history(history)
        return self.save_walkthrough(walkthrough)

    def _write(self, payload: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(f"{self.path.suffix}.{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)


def parse_course_corpus_jsonl(text: str) -> list[dict[str, object]]:
    """Validate AI-produced JSONL records for a Code Learner corpus."""

    records: list[dict[str, object]] = []
    for line_number, line in enumerate(_course_corpus_lines(text), start=1):
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as error:
            raise CodeLearnerError(
                f"course corpus line {line_number} is not valid JSON: {error.msg}"
            ) from error
        if not isinstance(payload, dict):
            raise CodeLearnerError(
                f"course corpus line {line_number} must be a JSON object"
            )
        record = dict(payload)
        record_type = _record_type(record)
        if not record_type:
            raise CodeLearnerError(
                f"course corpus line {line_number} is missing record_type"
            )
        if record_type not in COURSE_CORPUS_RECORD_TYPES:
            if record_type in IGNORED_COURSE_CORPUS_RECORD_TYPES:
                continue
            raise CodeLearnerError(
                f"course corpus line {line_number} has unknown record_type: "
                f"{record_type}"
            )
        record["record_type"] = record_type
        records.append(record)
    if not records:
        raise CodeLearnerError("AI course corpus is empty")
    if not any(_record_type(record) == "course_manifest" for record in records):
        raise CodeLearnerError("AI course corpus is missing course_manifest")
    return records


def course_corpus_payload(records: list[dict[str, object]]) -> dict[str, object]:
    """Return a compact browser payload for an AI-generated learning corpus."""

    manifest = next(
        (record for record in records if _record_type(record) == "course_manifest"),
        {},
    )
    diagnostics = [
        record for record in records if _record_type(record) == "diagnostic"
    ]
    return {
        "schema_version": COURSE_CORPUS_SCHEMA_VERSION,
        "record_count": len(records),
        "manifest": dict(manifest),
        "diagnostics": diagnostics,
        "architecture_step_count": _record_count(records, "architecture_step"),
        "module_count": _record_count(records, "module"),
        "module_step_count": _record_count(records, "module_step"),
        "function_index_count": _record_count(records, "function_index_entry"),
        "function_lesson_count": _record_count(records, "function_lesson"),
    }


def analysis_from_course_corpus(
    root: Path | str,
    records: list[dict[str, object]],
) -> RepositoryAnalysis:
    """Build the UI's analysis payload from AI-inferred corpus records."""

    adapter = SourceAdapter(root)
    source_files = _course_corpus_source_files(records)
    language_counts: dict[str, int] = {}
    for source_file in source_files:
        language = language_for_path(source_file)
        language_counts[language] = language_counts.get(language, 0) + 1
    modules = tuple(_course_corpus_modules(records))
    symbols = tuple(_course_corpus_symbols(records))
    return RepositoryAnalysis(
        source_root=str(adapter.root),
        source_files=tuple(source_files),
        language_counts=language_counts,
        modules=modules,
        symbols=symbols,
        truncated=False,
    )


def normalize_learning_mode(mode: str) -> str:
    normalized = str(mode or "").strip().lower().replace("_", "-")
    aliases = {
        "arch": "architecture",
        "architecture": "architecture",
        "module": "module",
        "function": "function",
        "symbol": "function",
    }
    normalized = aliases.get(normalized, normalized)
    if normalized not in SUPPORTED_LEARNING_MODES:
        raise CodeLearnerError(
            "learning mode must be one of: Architecture, Module, Function"
        )
    return normalized


def language_for_path(path: str | Path) -> str:
    suffix = Path(str(path)).suffix.lower()
    return LANGUAGE_BY_EXTENSION.get(suffix, "plain")


def _course_corpus_lines(text: str):
    lines = text.splitlines()
    fenced: list[str] = []
    in_fence = False
    saw_fence = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("```"):
            saw_fence = True
            in_fence = not in_fence
            continue
        if in_fence:
            fenced.append(line)
    source = fenced if saw_fence and fenced else lines
    for line in source:
        stripped = line.strip()
        if stripped:
            yield stripped


def _record_type(record: dict[str, object]) -> str:
    return str(record.get("record_type") or record.get("type") or "").strip()


def _record_count(records: list[dict[str, object]], record_type: str) -> int:
    return sum(1 for record in records if _record_type(record) == record_type)


def _text_value(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        return "\n".join(f"- {_text_value(item)}" for item in value if _text_value(item))
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value).strip()


def _string_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _course_corpus_source_references(
    record: dict[str, object],
    *,
    kind: str | None = None,
) -> list[SourceReference]:
    references: list[SourceReference] = []
    raw_refs = record.get("source_refs")
    if isinstance(raw_refs, list):
        for raw in raw_refs:
            if not isinstance(raw, dict):
                continue
            reference = _source_reference_from_payload(
                raw,
                kind=kind or _record_type(record),
                fallback_symbol=str(record.get("symbol") or ""),
                fallback_label=str(record.get("title") or record.get("name") or ""),
            )
            if reference is not None:
                references.append(reference)
    if references:
        return references
    fallback_path = ""
    if _record_type(record) == "function_index_entry":
        fallback_path = str(record.get("path") or record.get("file_path") or "")
    if not fallback_path:
        return []
    start = int(record.get("start_line") or 1)
    end = int(record.get("end_line") or start)
    return [
        SourceReference(
            file_path=fallback_path,
            start_line=start,
            end_line=end,
            symbol=str(record.get("symbol") or ""),
            label=str(record.get("display_name") or record.get("symbol") or ""),
            kind=kind or _record_type(record),
        ).normalized()
    ]


def _source_reference_from_payload(
    payload: dict[str, object],
    *,
    kind: str,
    fallback_symbol: str = "",
    fallback_label: str = "",
) -> SourceReference | None:
    path = str(payload.get("path") or payload.get("file_path") or "").strip()
    if not path:
        return None
    start = int(payload.get("start_line") or 1)
    end = int(payload.get("end_line") or start)
    return SourceReference(
        file_path=path,
        start_line=start,
        end_line=end,
        symbol=str(payload.get("symbol") or fallback_symbol or ""),
        label=str(payload.get("label") or payload.get("reason") or fallback_label or ""),
        kind=kind,
    ).normalized()


def _course_corpus_source_files(records: list[dict[str, object]]) -> list[str]:
    files: list[str] = []
    for record in records:
        for path in _string_list(record.get("primary_files")):
            files.append(path)
        for reference in _course_corpus_source_references(record):
            files.append(reference.file_path)
    return _unique(files)


def _course_corpus_modules(records: list[dict[str, object]]) -> list[dict[str, object]]:
    modules: list[dict[str, object]] = []
    for record in records:
        if _record_type(record) != "module":
            continue
        module_id = str(record.get("id") or "").strip()
        if not module_id:
            continue
        name = str(record.get("name") or record.get("label") or module_id).strip()
        primary_files = _string_list(record.get("primary_files"))
        if not primary_files:
            primary_files = [
                reference.file_path
                for reference in _course_corpus_source_references(record, kind="module")
            ]
        primary_files = _unique(primary_files)
        language_counts: dict[str, int] = {}
        for relative_path in primary_files:
            language = language_for_path(relative_path)
            language_counts[language] = language_counts.get(language, 0) + 1
        modules.append(
            {
                "id": module_id,
                "path": module_id,
                "label": name,
                "name": name,
                "purpose": _text_value(record.get("purpose")),
                "responsibilities": _string_list(record.get("responsibilities")),
                "public_interfaces": _string_list(record.get("public_interfaces")),
                "depends_on_module_ids": _string_list(
                    record.get("depends_on_module_ids")
                ),
                "used_by_module_ids": _string_list(record.get("used_by_module_ids")),
                "primary_files": primary_files,
                "file_count": len(primary_files),
                "language_counts": language_counts,
                "confidence": _confidence(record),
            }
        )
    return modules


def _course_corpus_symbols(records: list[dict[str, object]]) -> list[SymbolCandidate]:
    symbols: list[SymbolCandidate] = []
    for record in records:
        if _record_type(record) != "function_index_entry":
            continue
        symbol = str(record.get("symbol") or record.get("display_name") or "").strip()
        if not symbol:
            continue
        references = _course_corpus_source_references(
            record,
            kind=str(record.get("kind") or "function"),
        )
        if not references:
            continue
        reference = references[0]
        symbols.append(
            SymbolCandidate(
                name=symbol.split(".")[-1],
                qualified_name=symbol,
                kind=str(record.get("kind") or "function"),
                file_path=reference.file_path,
                start_line=reference.start_line,
                end_line=reference.end_line,
                calls=tuple(_string_list(record.get("known_callees"))),
            )
        )
    return sorted(
        symbols,
        key=lambda item: (item.file_path, item.start_line, item.qualified_name),
    )


def analyze_repository(root: Path | str) -> RepositoryAnalysis:
    adapter = SourceAdapter(root)
    files, truncated = _source_files(adapter.root)
    language_counts: dict[str, int] = {}
    for file_path in files:
        language = language_for_path(file_path)
        language_counts[language] = language_counts.get(language, 0) + 1
    modules = tuple(_module_candidates(files, language_counts))
    symbols = tuple(_discover_symbols(adapter, files[:SYMBOL_FILE_LIMIT]))
    return RepositoryAnalysis(
        source_root=str(adapter.root),
        source_files=tuple(files),
        language_counts=language_counts,
        modules=modules,
        symbols=symbols,
        truncated=truncated or len(files) > SYMBOL_FILE_LIMIT,
    )


def create_walkthrough(
    root: Path | str,
    *,
    learning_mode: str,
    target: str = "",
    intended_audience: str = "",
) -> Walkthrough:
    mode = normalize_learning_mode(learning_mode)
    adapter = SourceAdapter(root)
    records = CodeLearnerStore(adapter.root).load_corpus_records()
    if not records:
        raise CodeLearnerError(
            "initialize Code Learner before generating a course"
        )
    if mode == "architecture":
        draft = _architecture_steps_from_corpus(records)
        title = _architecture_title(adapter, records)
        mode_target = ""
    elif mode == "module":
        module = _course_corpus_module_for_target(records, target)
        mode_target = str(module.get("id") or target).strip()
        draft = _module_steps_from_corpus(records, module)
        title = f"Module Deep Dive: {module.get('name') or mode_target}"
    else:
        lesson = _function_lesson_for_target(records, target)
        mode_target = str(lesson.get("symbol") or target).strip()
        draft = _function_steps_from_corpus(records, lesson)
        title = f"Function Deep Dive: {lesson.get('display_name') or mode_target}"
    return formalize_walkthrough(
        adapter,
        title=title,
        learning_mode=mode,
        mode_target=mode_target,
        intended_audience=intended_audience,
        draft_steps=draft,
    )


def formalize_walkthrough(
    adapter: SourceAdapter,
    *,
    title: str,
    learning_mode: str,
    mode_target: str,
    intended_audience: str,
    draft_steps: list[dict[str, object]],
) -> Walkthrough:
    steps: list[WalkthroughStep] = []
    for index, draft in enumerate(draft_steps, start=1):
        reference_data = draft.get("primary_reference")
        if not isinstance(reference_data, SourceReference):
            if not isinstance(reference_data, dict):
                raise CodeLearnerError("draft step is missing a primary reference")
            reference = SourceReference.from_dict(reference_data)
        else:
            reference = reference_data
        verified = adapter.verify_reference(reference)
        if not verified["ok"]:
            review_status = str(verified["status"])
            confidence = 0.25
        else:
            review_status = "generated"
            confidence = float(draft.get("confidence") or 0.75)
        step_id = str(draft.get("id") or f"step-{index:03d}")
        secondary = draft.get("secondary_references")
        steps.append(
            WalkthroughStep(
                id=step_id,
                title=str(draft.get("title") or f"Step {index}"),
                explanation=str(draft.get("explanation") or ""),
                primary_reference=reference.normalized(),
                secondary_references=tuple(
                    reference
                    if isinstance(reference, SourceReference)
                    else SourceReference.from_dict(reference)
                    for reference in (
                        secondary if isinstance(secondary, list) else []
                    )
                    if isinstance(reference, (SourceReference, dict))
                ),
                prerequisites=tuple(
                    str(item)
                    for item in (
                        draft.get("prerequisites")
                        if isinstance(draft.get("prerequisites"), list)
                        else []
                    )
                ),
                followups=tuple(
                    str(item)
                    for item in (
                        draft.get("followups")
                        if isinstance(draft.get("followups"), list)
                        else []
                    )
                ),
                confidence=confidence,
                review_status=review_status,
            )
        )
    if not steps:
        raise CodeLearnerError("planner produced no walkthrough steps")
    for index, step in enumerate(steps):
        followups = (steps[index + 1].id,) if index + 1 < len(steps) else ()
        prerequisites = (steps[index - 1].id,) if index > 0 else ()
        steps[index] = WalkthroughStep(
            id=step.id,
            title=step.title,
            explanation=step.explanation,
            primary_reference=step.primary_reference,
            secondary_references=step.secondary_references,
            prerequisites=step.prerequisites or prerequisites,
            followups=step.followups or followups,
            confidence=step.confidence,
            review_status=step.review_status,
        )
    return Walkthrough(
        id=uuid4().hex,
        title=title,
        source_root=str(adapter.root),
        learning_mode=normalize_learning_mode(learning_mode),
        mode_target=mode_target,
        intended_audience=intended_audience,
        steps=tuple(steps),
        current_step_id=steps[0].id,
        generated_at=utc_now(),
        source_revision=repository_revision(adapter.root),
    )


def resolve_symbol(
    analysis: RepositoryAnalysis,
    name: str,
) -> SymbolResolution:
    requested = str(name or "").strip()
    if not requested:
        return SymbolResolution("missing")
    lowered = requested.lower()
    matches = [
        symbol
        for symbol in analysis.symbols
        if symbol.qualified_name.lower() == lowered
        or symbol.name.lower() == lowered
        or symbol.qualified_name.lower().endswith(f".{lowered}")
    ]
    if not matches:
        partial = [
            symbol
            for symbol in analysis.symbols
            if lowered in symbol.qualified_name.lower()
        ][:20]
        return SymbolResolution("missing", candidates=tuple(partial))
    if len(matches) > 1:
        return SymbolResolution("ambiguous", candidates=tuple(matches[:20]))
    return SymbolResolution("resolved", symbol=matches[0], candidates=tuple(matches))


def build_learner_context(
    root: Path | str,
    walkthrough: Walkthrough,
    *,
    selected_file_path: str = "",
    selected_start_line: int | None = None,
    selected_end_line: int | None = None,
    visible_start_line: int | None = None,
    visible_end_line: int | None = None,
) -> dict[str, object]:
    adapter = SourceAdapter(root)
    step = walkthrough.current_step()
    if step is None:
        raise CodeLearnerError("walkthrough has no current step")
    reference = step.primary_reference
    selected_path = selected_file_path.strip()
    if selected_path:
        start = selected_start_line or reference.start_line
        end = selected_end_line or start
        reference = SourceReference(
            file_path=selected_path,
            start_line=int(start),
            end_line=int(end),
            kind="selection",
        ).normalized()
    elif selected_start_line is not None:
        start = selected_start_line
        end = selected_end_line or start
        reference = SourceReference(
            file_path=reference.file_path,
            start_line=int(start),
            end_line=int(end),
            symbol=reference.symbol,
            label=reference.label,
            kind="selection",
        ).normalized()
    visible_range = {
        "start_line": visible_start_line,
        "end_line": visible_end_line,
    }
    verification = adapter.verify_reference(reference)
    excerpt = ""
    if verification.get("ok"):
        excerpt = adapter.extract_range(reference, max_lines=100)
    return {
        "workflow": WORKFLOW_ID,
        "walkthrough_id": walkthrough.id,
        "learning_mode": walkthrough.learning_mode,
        "mode_target": walkthrough.mode_target,
        "step_id": step.id,
        "step_title": step.title,
        "step_position": _step_position(walkthrough, step.id),
        "file_path": reference.file_path,
        "start_line": reference.start_line,
        "end_line": reference.end_line,
        "symbol": reference.symbol,
        "selection_active": bool(selected_path or selected_start_line is not None),
        "visible_range": visible_range,
        "related_references": [
            item.to_dict() for item in step.secondary_references
        ],
        "source_status": verification,
        "source_excerpt": excerpt,
        "recent_questions": list(walkthrough.qa_history)[-8:],
    }


def learner_prompt(question: str, context: dict[str, object]) -> str:
    """Wrap a user question with the active Code Learner source context."""

    source_excerpt = str(context.get("source_excerpt") or "").strip()
    context_lines = [
        "[ElectroBoy Code Learner context]",
        f"Walkthrough: {context.get('walkthrough_id')}",
        f"Mode: {context.get('learning_mode')}",
        f"Target: {context.get('mode_target')}",
        f"Step: {context.get('step_position')} {context.get('step_title')}",
        (
            "Source: "
            f"{context.get('file_path')}:{context.get('start_line')}-"
            f"{context.get('end_line')}"
        ),
        "Use this context to answer the user's learning question. Explain only;",
        "do not edit files, run commands, or perform implementation work.",
    ]
    if source_excerpt:
        context_lines.extend(["", "Source excerpt:", source_excerpt])
    context_lines.extend(
        [
            "[/ElectroBoy Code Learner context]",
            "",
            str(question or "").strip(),
        ]
    )
    return "\n".join(context_lines).strip() + "\n"


def learner_question_payload(
    root: Path | str,
    walkthrough: Walkthrough,
    question: str,
    **context_options: object,
) -> dict[str, object]:
    context = build_learner_context(root, walkthrough, **context_options)
    prompt = learner_prompt(question, context)
    return {
        "status": "prepared",
        "question": question,
        "context": context,
        "prompt": prompt,
    }


def repository_revision(root: Path | str) -> str:
    adapter = SourceAdapter(root)
    files, _truncated = _source_files(adapter.root)
    digest = hashlib.sha256()
    for relative_path in files[:SOURCE_FILE_LIMIT]:
        try:
            path = adapter.resolve(relative_path)
        except CodeLearnerError:
            continue
        signature = file_signature(path)
        digest.update(relative_path.encode("utf-8", errors="replace"))
        digest.update(b"\0")
        digest.update(str(signature.get("mtime_ns") or 0).encode())
        digest.update(b":")
        digest.update(str(signature.get("size") or 0).encode())
        digest.update(b"\0")
    return f"file-signature:{digest.hexdigest()[:24]}"


def _source_files(root: Path) -> tuple[list[str], bool]:
    files: list[str] = []
    truncated = False
    for current, dirnames, filenames in os.walk(root):
        current_path = Path(current)
        dirnames[:] = sorted(
            dirname
            for dirname in dirnames
            if dirname not in IGNORED_DIRECTORY_NAMES
            and not dirname.startswith(".")
        )
        for filename in sorted(filenames):
            path = current_path / filename
            if path.suffix.lower() not in SOURCE_EXTENSIONS:
                continue
            try:
                relative = path.resolve().relative_to(root).as_posix()
            except (OSError, ValueError):
                continue
            files.append(relative)
            if len(files) >= SOURCE_FILE_LIMIT:
                return files, True
    return files, truncated


def _module_candidates(
    files: list[str],
    language_counts: dict[str, int],
) -> list[dict[str, object]]:
    grouped: dict[str, dict[str, object]] = {}
    root_files = 0
    for relative_path in files:
        parts = relative_path.split("/")
        if len(parts) == 1:
            root_files += 1
            continue
        module_path = parts[0]
        if module_path == "src" and len(parts) > 2:
            module_path = "/".join(parts[:3] if len(parts) > 3 else parts[:2])
        entry = grouped.setdefault(
            module_path,
            {
                "path": module_path,
                "label": module_path,
                "file_count": 0,
                "language_counts": {},
            },
        )
        entry["file_count"] = int(entry["file_count"]) + 1
        language = language_for_path(relative_path)
        module_languages = entry["language_counts"]
        if isinstance(module_languages, dict):
            module_languages[language] = int(module_languages.get(language) or 0) + 1
    modules = sorted(
        grouped.values(),
        key=lambda item: (-int(item.get("file_count") or 0), str(item.get("path"))),
    )
    if root_files:
        modules.insert(
            0,
            {
                "path": ".",
                "label": "repository root",
                "file_count": root_files,
                "language_counts": dict(language_counts),
            },
        )
    return modules[:80]


def _discover_symbols(adapter: SourceAdapter, files: list[str]) -> list[SymbolCandidate]:
    symbols: list[SymbolCandidate] = []
    for relative_path in files:
        language = language_for_path(relative_path)
        if language == "python":
            symbols.extend(_python_symbols(adapter, relative_path))
        elif language in {"javascript", "typescript"}:
            symbols.extend(_javascript_symbols(adapter, relative_path))
    return sorted(
        symbols,
        key=lambda item: (item.file_path, item.start_line, item.qualified_name),
    )


def _python_symbols(adapter: SourceAdapter, relative_path: str) -> list[SymbolCandidate]:
    try:
        source = adapter.read_file(relative_path)
        tree = ast.parse(source.text)
    except (CodeLearnerError, SyntaxError, UnicodeDecodeError):
        return []

    symbols: list[SymbolCandidate] = []

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.stack: list[str] = []

        def visit_ClassDef(self, node: ast.ClassDef) -> Any:
            self._record(node, "class")
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
            self._record(node, "function" if not self.stack else "method")
            self.stack.append(node.name)
            self.generic_visit(node)
            self.stack.pop()

        def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
            self.visit_FunctionDef(node)  # type: ignore[arg-type]

        def _record(
            self,
            node: ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef,
            kind: str,
        ) -> None:
            name = node.name
            qualified = ".".join([*self.stack, name]) if self.stack else name
            symbols.append(
                SymbolCandidate(
                    name=name,
                    qualified_name=qualified,
                    kind=kind,
                    file_path=relative_path,
                    start_line=int(getattr(node, "lineno", 1)),
                    end_line=int(
                        getattr(node, "end_lineno", getattr(node, "lineno", 1))
                    ),
                    calls=tuple(sorted(_python_call_names(node))),
                )
            )

    Visitor().visit(tree)
    return symbols


def _python_call_names(node: ast.AST) -> set[str]:
    calls: set[str] = set()
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        if isinstance(child.func, ast.Name):
            calls.add(child.func.id)
        elif isinstance(child.func, ast.Attribute):
            calls.add(child.func.attr)
    return calls


_JS_SYMBOL_PATTERNS = (
    re.compile(
        r"^\s*(?:export\s+)?(?:async\s+)?function\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)\s*\(",
    ),
    re.compile(r"^\s*(?:export\s+)?class\s+(?P<name>[A-Za-z_$][\w$]*)\b"),
    re.compile(
        r"^\s*(?:export\s+)?(?:const|let|var)\s+"
        r"(?P<name>[A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|"
        r"[A-Za-z_$][\w$]*)\s*=>",
    ),
)


def _javascript_symbols(
    adapter: SourceAdapter,
    relative_path: str,
) -> list[SymbolCandidate]:
    try:
        source = adapter.read_file(relative_path)
    except CodeLearnerError:
        return []
    lines = source.text.splitlines()
    symbols: list[SymbolCandidate] = []
    for index, line in enumerate(lines, start=1):
        match = next(
            (pattern.match(line) for pattern in _JS_SYMBOL_PATTERNS if pattern.match(line)),
            None,
        )
        if match is None:
            continue
        name = match.group("name")
        end_line = _brace_end_line(lines, index)
        kind = "class" if "class" in line else "function"
        symbols.append(
            SymbolCandidate(
                name=name,
                qualified_name=name,
                kind=kind,
                file_path=relative_path,
                start_line=index,
                end_line=end_line,
                calls=tuple(sorted(_javascript_call_names(lines[index - 1 : end_line]))),
            )
        )
    return symbols


def _brace_end_line(lines: list[str], start_line: int) -> int:
    depth = 0
    seen_brace = False
    for index in range(start_line, min(len(lines), start_line + 240) + 1):
        line = lines[index - 1]
        depth += line.count("{")
        if "{" in line:
            seen_brace = True
        depth -= line.count("}")
        if seen_brace and depth <= 0:
            return index
    return min(len(lines), start_line + 80)


def _javascript_call_names(lines: list[str]) -> set[str]:
    calls: set[str] = set()
    pattern = re.compile(r"\b([A-Za-z_$][\w$]*)\s*\(")
    keywords = {"if", "for", "while", "switch", "catch", "function"}
    for line in lines:
        for match in pattern.finditer(line):
            name = match.group(1)
            if name not in keywords:
                calls.add(name)
    return calls


def _architecture_steps_from_corpus(
    records: list[dict[str, object]],
) -> list[dict[str, object]]:
    manifest = _course_corpus_manifest(records)
    requested_ids = _string_list(manifest.get("architecture_step_ids"))
    architecture_records = _ordered_course_records(
        records,
        "architecture_step",
        requested_ids,
    )
    if not architecture_records:
        raise CodeLearnerError("AI course corpus has no architecture steps")
    return [
        _course_step_from_record(record, "architecture", index)
        for index, record in enumerate(architecture_records, start=1)
    ]


def _module_steps_from_corpus(
    records: list[dict[str, object]],
    module: dict[str, object],
) -> list[dict[str, object]]:
    module_id = str(module.get("id") or "").strip()
    module_records = [
        record
        for record in records
        if _record_type(record) == "module_step"
        and str(record.get("module_id") or "").strip() == module_id
    ]
    if not module_records:
        module_records = [module]
    return [
        _course_step_from_record(record, "module", index)
        for index, record in enumerate(module_records, start=1)
    ]


def _function_steps_from_corpus(
    records: list[dict[str, object]],
    lesson: dict[str, object],
) -> list[dict[str, object]]:
    references = _course_corpus_source_references(lesson, kind="function")
    if not references:
        index_entry = _function_index_for_target(
            records,
            str(lesson.get("symbol") or ""),
        )
        if index_entry is not None:
            references = _course_corpus_source_references(index_entry, kind="function")
    if not references:
        raise CodeLearnerError(
            f"function lesson has no source references: {lesson.get('symbol')}"
        )
    sections = [
        (
            "purpose",
            str(lesson.get("title") or "Purpose and Shape"),
            [
                _text_value(lesson.get("summary")),
                _text_value(lesson.get("body")),
            ],
        ),
        (
            "call-flow",
            "Call Tree",
            [_text_value(lesson.get("call_flow"))],
        ),
        (
            "inputs-outputs",
            "Inputs and Outputs",
            [
                _section_with_label("Inputs", lesson.get("inputs")),
                _section_with_label("Outputs", lesson.get("outputs")),
            ],
        ),
        (
            "effects-errors",
            "Side Effects and Error Paths",
            [
                _section_with_label("Side effects", lesson.get("side_effects")),
                _section_with_label("Error paths", lesson.get("error_paths")),
            ],
        ),
    ]
    symbol = _stable_id(str(lesson.get("symbol") or "function"))
    steps: list[dict[str, object]] = []
    secondary = [reference.to_dict() for reference in references[1:]]
    for index, (section_id, title, parts) in enumerate(sections, start=1):
        explanation = "\n\n".join(part for part in parts if part)
        if not explanation:
            continue
        steps.append(
            {
                "id": f"function.{symbol}.{section_id}",
                "title": title,
                "explanation": explanation,
                "primary_reference": references[0],
                "secondary_references": secondary,
                "confidence": _confidence(lesson),
            }
        )
    if not steps:
        steps.append(_course_step_from_record(lesson, "function", 1))
    return steps


def _course_step_from_record(
    record: dict[str, object],
    kind: str,
    index: int,
) -> dict[str, object]:
    references = _course_corpus_source_references(record, kind=kind)
    if not references:
        raise CodeLearnerError(
            f"{kind} course record has no source references: "
            f"{record.get('id') or record.get('title') or record.get('name')}"
        )
    return {
        "id": str(record.get("id") or f"{kind}-{index:03d}"),
        "title": str(
            record.get("title")
            or record.get("name")
            or record.get("display_name")
            or f"Step {index}"
        ),
        "explanation": _course_record_explanation(record),
        "primary_reference": references[0],
        "secondary_references": [reference.to_dict() for reference in references[1:]],
        "confidence": _confidence(record),
    }


def _course_record_explanation(record: dict[str, object]) -> str:
    parts = [
        _text_value(record.get("summary")),
        _text_value(record.get("body")),
        _section_with_label("Purpose", record.get("purpose")),
        _section_with_label("Responsibilities", record.get("responsibilities")),
        _section_with_label("Public interfaces", record.get("public_interfaces")),
    ]
    explanation = "\n\n".join(part for part in parts if part)
    if explanation:
        return explanation
    return _text_value(record.get("message"))


def _section_with_label(label: str, value: object) -> str:
    text = _text_value(value)
    if not text:
        return ""
    return f"{label}: {text}"


def _course_corpus_manifest(records: list[dict[str, object]]) -> dict[str, object]:
    return next(
        (record for record in records if _record_type(record) == "course_manifest"),
        {},
    )


def _ordered_course_records(
    records: list[dict[str, object]],
    record_type: str,
    requested_ids: list[str],
) -> list[dict[str, object]]:
    candidates = [
        record for record in records if _record_type(record) == record_type
    ]
    if not requested_ids:
        return candidates
    by_id = {str(record.get("id") or ""): record for record in candidates}
    ordered = [
        by_id[record_id]
        for record_id in requested_ids
        if record_id in by_id
    ]
    remaining = [
        record for record in candidates if record not in ordered
    ]
    return [*ordered, *remaining]


def _course_corpus_module_for_target(
    records: list[dict[str, object]],
    target: str,
) -> dict[str, object]:
    requested = str(target or "").strip().lower()
    if not requested:
        raise CodeLearnerError("module target required")
    for module in _course_corpus_modules(records):
        values = {
            str(module.get("id") or "").strip().lower(),
            str(module.get("path") or "").strip().lower(),
            str(module.get("label") or "").strip().lower(),
            str(module.get("name") or "").strip().lower(),
        }
        if requested in values:
            return module
    raise CodeLearnerError(f"module target was not found: {target}")


def _function_lesson_for_target(
    records: list[dict[str, object]],
    target: str,
) -> dict[str, object]:
    requested = str(target or "").strip().lower()
    if not requested:
        raise CodeLearnerError("function target required")
    matches = [
        record
        for record in records
        if _record_type(record) == "function_lesson"
        and _function_record_matches(record, requested)
    ]
    if len(matches) > 1:
        raise CodeLearnerError(f"function target is ambiguous: {target}")
    if matches:
        return matches[0]
    raise CodeLearnerError(
        "function lesson was not generated during initialization: "
        f"{target}"
    )


def _function_index_for_target(
    records: list[dict[str, object]],
    target: str,
) -> dict[str, object] | None:
    requested = str(target or "").strip().lower()
    if not requested:
        return None
    for record in records:
        if _record_type(record) == "function_index_entry" and _function_record_matches(
            record,
            requested,
        ):
            return record
    return None


def _function_record_matches(record: dict[str, object], requested: str) -> bool:
    values = [
        str(record.get("symbol") or ""),
        str(record.get("display_name") or ""),
    ]
    return any(
        value.strip().lower() == requested
        or value.strip().lower().endswith(f".{requested}")
        for value in values
    )


def _architecture_title(
    adapter: SourceAdapter,
    records: list[dict[str, object]],
) -> str:
    manifest = _course_corpus_manifest(records)
    name = str(manifest.get("repository_name") or adapter.root.name).strip()
    return f"Architecture Tour: {name}"


def _confidence(record: dict[str, object]) -> float | None:
    value = record.get("confidence")
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _stable_id(value: str) -> str:
    text = re.sub(r"[^a-z0-9]+", ".", value.lower()).strip(".")
    return text or "item"


def _architecture_steps(analysis: RepositoryAnalysis) -> list[dict[str, object]]:
    files = list(analysis.source_files)
    pyproject = _first_existing(files, ("pyproject.toml", "package.json", "Cargo.toml"))
    readme = _first_matching(files, lambda path: Path(path).name.lower() == "readme.md")
    entry = _first_matching(
        files,
        lambda path: Path(path).name
        in {"__main__.py", "main.py", "cli.py", "app.py", "server.py"},
    )
    module_file = _first_matching(
        files,
        lambda path: "/workflows/" in path or "/modules/" in path or "/service/" in path,
    )
    selected = [item for item in [readme, pyproject, entry, module_file] if item]
    if not selected:
        selected = files[:4]
    steps = []
    for index, relative_path in enumerate(_unique(selected)[:4], start=1):
        title = {
            1: "Project Purpose",
            2: "Packaging and APIs",
            3: "Execution Entry Point",
            4: "Major Component Boundary",
        }.get(index, "Architecture Reference")
        steps.append(
            {
                "id": f"architecture-{index:03d}",
                "title": title,
                "explanation": _architecture_explanation(index, relative_path, analysis),
                "primary_reference": SourceReference(
                    file_path=relative_path,
                    start_line=1,
                    end_line=_default_end_line(relative_path),
                    kind="architecture",
                ),
            }
        )
    return _ensure_minimum_steps(steps, files, "architecture")


def _module_steps(
    adapter: SourceAdapter,
    analysis: RepositoryAnalysis,
    module_path: str,
) -> list[dict[str, object]]:
    files = [
        path
        for path in analysis.source_files
        if module_path == "." or path == module_path or path.startswith(f"{module_path}/")
    ]
    if not files:
        raise CodeLearnerError(f"module has no source files: {module_path}")
    selected = _prioritize_module_files(files)
    steps = []
    for index, relative_path in enumerate(selected[:8], start=1):
        title = "Module Boundary" if index == 1 else f"Key File {index}"
        if Path(relative_path).name in {"__init__.py", "index.ts", "index.js"}:
            title = "Public Interface"
        steps.append(
            {
                "id": f"module-{index:03d}",
                "title": title,
                "explanation": (
                    f"`{relative_path}` is part of the `{module_path}` module. "
                    "Read this step for the file's responsibility, how it relates "
                    "to neighboring files, and where the module exposes behavior "
                    "to the rest of the repository."
                ),
                "primary_reference": _file_reference(adapter, relative_path, "module"),
            }
        )
    return _ensure_minimum_steps(steps, files, "module")


def _function_steps(
    adapter: SourceAdapter,
    analysis: RepositoryAnalysis,
    symbol: SymbolCandidate,
) -> list[dict[str, object]]:
    callers = [
        candidate
        for candidate in analysis.symbols
        if candidate.file_path != symbol.file_path
        and (symbol.name in candidate.calls or symbol.qualified_name in candidate.calls)
    ][:5]
    callees = [
        candidate
        for candidate in analysis.symbols
        if candidate.name in symbol.calls or candidate.qualified_name in symbol.calls
    ][:5]
    steps = [
        {
            "id": "function-001",
            "title": "Purpose and Shape",
            "explanation": (
                f"`{symbol.qualified_name}` is a `{symbol.kind}` defined in "
                f"`{symbol.file_path}`. This step introduces the symbol, its "
                "local inputs and outputs, and the code region that owns its behavior."
            ),
            "primary_reference": symbol.reference(),
        },
        {
            "id": "function-002",
            "title": "Local Control Flow",
            "explanation": (
                "Walk through the highlighted implementation in order. Pay attention "
                "to branches, early returns, state changes, and calls that move work "
                "outside the function."
            ),
            "primary_reference": symbol.reference(),
        },
        {
            "id": "function-003",
            "title": "Call Tree",
            "explanation": _call_tree_explanation(symbol, callers, callees),
            "primary_reference": (
                callers[0].reference()
                if callers
                else callees[0].reference()
                if callees
                else symbol.reference()
            ),
            "secondary_references": [
                candidate.reference() for candidate in [*callers, *callees]
            ],
        },
    ]
    if len(symbol.calls) > 0:
        steps.append(
            {
                "id": "function-004",
                "title": "Side Effects and Dependencies",
                "explanation": (
                    "Review the calls made by this symbol to identify dependencies, "
                    "side effects, persistence behavior, or external boundaries."
                ),
                "primary_reference": symbol.reference(),
            }
        )
    return steps


def _resolve_module_target(
    adapter: SourceAdapter,
    analysis: RepositoryAnalysis,
    target: str,
) -> str:
    requested = str(target or "").strip().strip("/")
    if not requested:
        raise CodeLearnerError("Module mode requires a module path")
    if requested == ".":
        return "."
    resolved = adapter.resolve(requested)
    if not resolved.exists():
        raise CodeLearnerError(f"module target does not exist: {target}")
    if not resolved.is_dir():
        raise CodeLearnerError(f"module target is not a directory: {target}")
    relative = adapter.relative_path(resolved)
    if any(module.get("path") == relative for module in analysis.modules):
        return relative
    if any(path.startswith(f"{relative}/") for path in analysis.source_files):
        return relative
    raise CodeLearnerError(f"module has no supported source files: {target}")


def _file_reference(
    adapter: SourceAdapter,
    relative_path: str,
    kind: str,
) -> SourceReference:
    try:
        source = adapter.read_file(relative_path)
        end_line = min(source.line_count, 80)
    except CodeLearnerError:
        end_line = 1
    return SourceReference(
        file_path=relative_path,
        start_line=1,
        end_line=end_line,
        kind=kind,
    )


def _default_end_line(relative_path: str) -> int:
    return 120 if language_for_path(relative_path) == "markdown" else 80


def _architecture_explanation(
    index: int,
    relative_path: str,
    analysis: RepositoryAnalysis,
) -> str:
    language_summary = ", ".join(
        f"{language}: {count}"
        for language, count in sorted(analysis.language_counts.items())
    )
    if index == 1:
        return (
            f"Start with `{relative_path}` to understand the project's purpose, "
            "main audience, and repository-level goals before diving into code."
        )
    if index == 2:
        return (
            f"`{relative_path}` describes how the project is packaged or exposed. "
            f"The repository scan found these source languages: {language_summary}."
        )
    if index == 3:
        return (
            f"`{relative_path}` is a likely execution entry point. Use it to trace "
            "how commands, APIs, or browser service startup paths enter the system."
        )
    return (
        f"`{relative_path}` is a representative component boundary. Use it to see "
        "how major services, modules, or workflows are connected."
    )


def _call_tree_explanation(
    symbol: SymbolCandidate,
    callers: list[SymbolCandidate],
    callees: list[SymbolCandidate],
) -> str:
    caller_text = (
        ", ".join(f"`{candidate.qualified_name}`" for candidate in callers)
        if callers
        else "No direct callers were inferred by the v1 source scan."
    )
    callee_text = (
        ", ".join(f"`{candidate.qualified_name}`" for candidate in callees)
        if callees
        else "No repository-local callees were inferred by the v1 source scan."
    )
    direct_calls = (
        ", ".join(f"`{call}`" for call in symbol.calls[:20])
        if symbol.calls
        else "No direct calls were detected in the selected symbol."
    )
    return (
        f"Call tree for `{symbol.qualified_name}`. Inferred callers: {caller_text}. "
        f"Inferred repository callees: {callee_text}. Direct call names observed "
        f"inside the symbol: {direct_calls}."
    )


def _first_existing(files: list[str], names: tuple[str, ...]) -> str:
    wanted = {name.lower() for name in names}
    return next(
        (path for path in files if Path(path).name.lower() in wanted),
        "",
    )


def _first_matching(files: list[str], predicate: Any) -> str:
    return next((path for path in files if predicate(path)), "")


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


def _prioritize_module_files(files: list[str]) -> list[str]:
    def key(path: str) -> tuple[int, int, str]:
        name = Path(path).name
        priority = 0
        if name in {"__init__.py", "index.js", "index.ts"}:
            priority = -2
        elif name in {"routes.py", "controller.py", "plugin.py", "domain.py"}:
            priority = -1
        return (priority, path.count("/"), path)

    return sorted(files, key=key)


def _ensure_minimum_steps(
    steps: list[dict[str, object]],
    files: list[str],
    prefix: str,
) -> list[dict[str, object]]:
    used = {
        step["primary_reference"].file_path
        for step in steps
        if isinstance(step.get("primary_reference"), SourceReference)
    }
    for relative_path in files:
        if len(steps) >= 3:
            break
        if relative_path in used:
            continue
        steps.append(
            {
                "id": f"{prefix}-{len(steps) + 1:03d}",
                "title": "Supporting Source",
                "explanation": (
                    f"`{relative_path}` is included as supporting context for "
                    "this course because it is part of the selected source set."
                ),
                "primary_reference": SourceReference(
                    file_path=relative_path,
                    start_line=1,
                    end_line=_default_end_line(relative_path),
                    kind=prefix,
                ),
            }
        )
        used.add(relative_path)
    return steps


def _step_position(walkthrough: Walkthrough, step_id: str) -> str:
    total = len(walkthrough.steps)
    for index, step in enumerate(walkthrough.steps, start=1):
        if step.id == step_id:
            return f"{index}/{total}"
    return f"?/{total}"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True
