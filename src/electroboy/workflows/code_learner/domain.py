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
SUPPORTED_LEARNING_MODES = frozenset({"architecture", "module", "function"})
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
    analysis = analyze_repository(adapter.root)
    if mode == "architecture":
        draft = _architecture_steps(analysis)
        title = f"Architecture Tour: {adapter.root.name}"
        mode_target = ""
    elif mode == "module":
        mode_target = _resolve_module_target(adapter, analysis, target)
        draft = _module_steps(adapter, analysis, mode_target)
        title = f"Module Deep Dive: {mode_target}"
    else:
        resolution = resolve_symbol(analysis, target)
        if resolution.status == "ambiguous":
            raise CodeLearnerError("function target is ambiguous")
        if resolution.symbol is None:
            raise CodeLearnerError("function target was not found")
        mode_target = resolution.symbol.qualified_name
        draft = _function_steps(adapter, analysis, resolution.symbol)
        title = f"Function Deep Dive: {mode_target}"
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
            module_path = "/".join(parts[:3])
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
