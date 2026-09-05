"""Replaceable, editor-independent symbol analysis adapters."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from .domain import (
    IGNORED_DIRECTORY_NAMES,
    LANGUAGE_BY_EXTENSION,
    CodeLearnerError,
    SourceAdapter,
    language_for_path,
)


@dataclass(frozen=True)
class ToolCapability:
    """Availability and limitations of one optional analysis tool."""

    name: str
    available: bool
    applies_to: tuple[str, ...]
    limitation: str
    executable: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class SymbolFact:
    """Language-independent symbol evidence emitted by an adapter."""

    name: str
    qualified_name: str
    kind: str
    language: str
    path: str
    start_line: int
    end_line: int
    signature: str = ""
    visibility: str = "unknown"
    callers: tuple[str, ...] = ()
    callees: tuple[str, ...] = ()
    state_access: tuple[str, ...] = ()
    side_effects: tuple[str, ...] = ()
    related_tests: tuple[str, ...] = ()
    confidence: str = "medium"
    limitations: tuple[str, ...] = ()
    adapter: str = "repository-search"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class SymbolAnalysisAdapter(Protocol):
    """Contract implemented by optional and fallback symbol analyzers."""

    name: str

    def capability(self) -> ToolCapability: ...

    def analyze(self, root: Path, paths: Sequence[str]) -> list[SymbolFact]: ...


class RepositorySearchAdapter:
    """Always-available conservative declaration search for source text."""

    name = "repository-search"

    def capability(self) -> ToolCapability:
        return ToolCapability(
            name=self.name,
            available=True,
            applies_to=("all text source languages",),
            limitation=(
                "Declaration patterns do not resolve overloads, macros, dynamic "
                "dispatch, reflection, generated symbols, or indirect calls."
            ),
        )

    def analyze(self, root: Path, paths: Sequence[str]) -> list[SymbolFact]:
        source = SourceAdapter(root)
        facts: list[SymbolFact] = []
        for relative_path in paths:
            try:
                file = source.read_file(relative_path)
            except CodeLearnerError:
                continue
            facts.extend(_text_symbols(file.path, file.language, file.text))
        return _deduplicate_facts(facts)


class UniversalCtagsAdapter:
    """Optional Universal Ctags adapter with normalized JSON output."""

    name = "universal-ctags"

    def __init__(self, executable: str | None = None, *, timeout: float = 30.0) -> None:
        self.executable = executable or shutil.which("ctags") or ""
        self.timeout = timeout

    def capability(self) -> ToolCapability:
        return ToolCapability(
            name=self.name,
            available=bool(self.executable),
            applies_to=("languages supported by the installed Ctags build",),
            limitation=(
                "Tags identify declarations but generally do not prove callers, "
                "callees, runtime dispatch, side effects, or data flow."
            ),
            executable=self.executable,
        )

    def analyze(self, root: Path, paths: Sequence[str]) -> list[SymbolFact]:
        if not self.executable or not paths:
            return []
        command = [
            self.executable,
            "--output-format=json",
            "--fields=+neK",
            "-f",
            "-",
            *paths,
        ]
        try:
            result = subprocess.run(
                command,
                cwd=root,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if result.returncode != 0:
            return []
        facts: list[SymbolFact] = []
        for line in result.stdout.splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict) or record.get("_type") != "tag":
                continue
            path = str(record.get("path") or "")
            name = str(record.get("name") or "")
            if not path or not name:
                continue
            line_number = _positive_int(record.get("line"), 1)
            scope = str(record.get("scope") or "")
            qualified = f"{scope}.{name}" if scope else name
            facts.append(
                SymbolFact(
                    name=name,
                    qualified_name=qualified,
                    kind=str(record.get("kind") or "symbol"),
                    language=language_for_path(path),
                    path=Path(path).as_posix(),
                    start_line=line_number,
                    end_line=_positive_int(record.get("end"), line_number),
                    signature=str(record.get("signature") or ""),
                    visibility=str(record.get("access") or "unknown"),
                    confidence="high",
                    limitations=(self.capability().limitation,),
                    adapter=self.name,
                )
            )
        return _deduplicate_facts(facts)


class SymbolAdapterRegistry:
    """Detect optional capabilities and provide a dependable fallback."""

    OPTIONAL_EXECUTABLES = {
        "clangd": (("c", "cpp"), "Language server availability only."),
        "gopls": (("go",), "Language server availability only."),
        "rust-analyzer": (("rust",), "Language server availability only."),
        "pyright-langserver": (("python",), "Language server availability only."),
        "typescript-language-server": (
            ("javascript", "typescript"),
            "Language server availability only.",
        ),
        "tree-sitter": (
            ("parser-supported languages",),
            "CLI availability does not guarantee a repository grammar.",
        ),
    }

    def __init__(self) -> None:
        self.fallback = RepositorySearchAdapter()
        self.ctags = UniversalCtagsAdapter()

    def capabilities(self) -> list[ToolCapability]:
        capabilities = [self.fallback.capability(), self.ctags.capability()]
        capabilities.extend(
            ToolCapability(
                name=name,
                available=bool(path := shutil.which(name)),
                applies_to=languages,
                limitation=limitation,
                executable=path or "",
            )
            for name, (languages, limitation) in self.OPTIONAL_EXECUTABLES.items()
        )
        return capabilities


class SymbolEvidenceCollector:
    """Collect bounded normalized evidence without requiring optional tools."""

    def __init__(
        self,
        root: Path | str,
        *,
        registry: SymbolAdapterRegistry | None = None,
        file_limit: int = 1000,
        excluded_regions: Iterable[str] = (),
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.registry = registry or SymbolAdapterRegistry()
        self.file_limit = max(1, file_limit)
        self.excluded_regions = tuple(
            Path(item).as_posix().strip("/")
            for item in excluded_regions
            if str(item).strip()
        )

    def source_paths(self) -> tuple[list[str], list[str]]:
        selected: list[str] = []
        skipped: list[str] = []
        for path in sorted(self.root.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(self.root)
            if any(part in IGNORED_DIRECTORY_NAMES for part in relative.parts[:-1]):
                continue
            relative_text = relative.as_posix()
            if any(
                relative_text == prefix or relative_text.startswith(f"{prefix}/")
                for prefix in self.excluded_regions
            ):
                continue
            if path.suffix.lower() not in LANGUAGE_BY_EXTENSION:
                continue
            if len(selected) >= self.file_limit:
                skipped.append(relative_text)
                continue
            selected.append(relative_text)
        return selected, skipped

    def collect(self) -> dict[str, object]:
        paths, skipped = self.source_paths()
        # Ctags materially improves declaration precision when available. The
        # fallback fills languages and files omitted by an optional index.
        optional = self.registry.ctags.analyze(self.root, paths)
        fallback = self.registry.fallback.analyze(self.root, paths)
        facts = _deduplicate_facts([*optional, *fallback])
        return {
            "schema_version": 1,
            "record_type": "symbol_evidence",
            "capabilities": [
                capability.to_dict() for capability in self.registry.capabilities()
            ],
            "indexed_paths": paths,
            "skipped_paths": skipped,
            "symbols": [fact.to_dict() for fact in facts],
        }

    def write(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f"{path.suffix}.tmp")
        temporary.write_text(
            json.dumps(self.collect(), sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
        return path


_DECLARATION_PATTERNS = (
    ("class", re.compile(r"^\s*(?:export\s+)?class\s+([A-Za-z_$][\w$]*)")),
    (
        "function",
        re.compile(
            r"^\s*(?:export\s+)?(?:async\s+)?(?:def|function|func|fn)\s+"
            r"([A-Za-z_$][\w$]*)\s*[(<]"
        ),
    ),
    (
        "function",
        re.compile(
            r"^\s*(?:[\w:*&<>\[\]]+\s+)+([A-Za-z_$][\w$]*)\s*\([^;]*\)\s*"
            r"(?:\{|$)"
        ),
    ),
    (
        "function",
        re.compile(
            r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*"
            r"(?:async\s*)?(?:\([^)]*\)|[A-Za-z_$][\w$]*)\s*=>"
        ),
    ),
)


def _text_symbols(path: str, language: str, text: str) -> list[SymbolFact]:
    facts: list[SymbolFact] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        for kind, pattern in _DECLARATION_PATTERNS:
            match = pattern.match(line)
            if not match:
                continue
            name = match.group(1)
            facts.append(
                SymbolFact(
                    name=name,
                    qualified_name=name,
                    kind=kind,
                    language=language,
                    path=path,
                    start_line=line_number,
                    end_line=line_number,
                    signature=line.strip()[:500],
                    visibility=_text_visibility(name, line),
                    confidence="medium",
                    limitations=(
                        "Text pattern found a declaration; ownership and call edges "
                        "require semantic or source inspection.",
                    ),
                )
            )
            break
    return facts


def _text_visibility(name: str, line: str) -> str:
    if name.startswith("_") or re.search(r"\b(?:private|static)\b", line):
        return "private"
    if re.search(r"\b(?:export|public|pub)\b", line):
        return "public"
    return "unknown"


def _deduplicate_facts(facts: Iterable[SymbolFact]) -> list[SymbolFact]:
    by_location: dict[tuple[str, int, str], SymbolFact] = {}
    for fact in facts:
        key = (fact.path, fact.start_line, fact.qualified_name)
        current = by_location.get(key)
        if current is None or fact.confidence == "high":
            by_location[key] = fact
    return sorted(
        by_location.values(),
        key=lambda item: (item.path, item.start_line, item.qualified_name),
    )


def _positive_int(value: object, fallback: int) -> int:
    try:
        parsed = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback
