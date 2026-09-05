"""Pinned Universal Ctags toolchain, raw evidence, and symbol resolution."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from electroboy.models import utc_now

from .analysis_adapters import RepositorySearchAdapter
from .domain import CodeLearnerError
from .phase3_contracts import SymbolLocator
from .source_manifest import SourceManifestService, SourceManifestSnapshot


class CtagsToolError(CodeLearnerError):
    """Raised when the pinned Universal Ctags tool cannot be prepared."""


@dataclass(frozen=True)
class ProcessResult:
    returncode: int
    stdout: bytes
    stderr: bytes


class ProcessAdapter(Protocol):
    """Replaceable process boundary for tool preparation and invocation."""

    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        input_bytes: bytes = b"",
        timeout: float = 30.0,
    ) -> ProcessResult: ...


class SubprocessAdapter:
    def run(
        self,
        command: Sequence[str],
        *,
        cwd: Path,
        input_bytes: bytes = b"",
        timeout: float = 30.0,
    ) -> ProcessResult:
        try:
            completed = subprocess.run(
                list(command),
                cwd=cwd,
                input=input_bytes,
                capture_output=True,
                check=False,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise CtagsToolError(f"Universal Ctags command failed: {error}") from error
        return ProcessResult(completed.returncode, completed.stdout, completed.stderr)


@dataclass(frozen=True)
class CtagsCapability:
    executable: str
    version: str
    source_revision: str
    json_supported: bool
    json_output_version: str
    languages: tuple[str, ...]
    features: tuple[str, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "name": "universal-ctags",
            "executable": self.executable,
            "version": self.version,
            "source_revision": self.source_revision,
            "json_supported": self.json_supported,
            "json_output_version": self.json_output_version,
            "languages": list(self.languages),
            "features": list(self.features),
        }


class UniversalCtagsToolchain:
    """Prepare and verify the repository-pinned Universal Ctags revision."""

    def __init__(
        self,
        *,
        source_root: Path | str | None = None,
        cache_root: Path | str | None = None,
        executable: Path | str | None = None,
        process: ProcessAdapter | None = None,
    ) -> None:
        checkout = Path(__file__).resolve().parents[4]
        self.source_root = Path(
            source_root or checkout / "third_party" / "universal-ctags"
        ).resolve()
        cache = (
            cache_root
            or Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
            / "electroboy"
            / "tools"
            / "universal-ctags"
        )
        self.cache_root = Path(cache).expanduser().resolve()
        override = executable or os.environ.get("ELECTROBOY_UNIVERSAL_CTAGS")
        self.executable = Path(override).expanduser().resolve() if override else None
        self.process = process or SubprocessAdapter()

    def prepare(self) -> CtagsCapability:
        source_revision = self._source_revision()
        executable = self.executable or self._cached_executable(source_revision)
        if not executable.is_file():
            executable = self._build(source_revision, executable)
        capability = self.verify(executable, source_revision=source_revision)
        self.executable = executable
        return capability

    def verify(
        self,
        executable: Path,
        *,
        source_revision: str = "",
    ) -> CtagsCapability:
        version = self._text(executable, "--version")
        if "Universal Ctags" not in version:
            raise CtagsToolError("configured ctags is not Universal Ctags")
        features = tuple(
            line.strip()
            for line in self._text(executable, "--list-features").splitlines()
            if line.strip()
        )
        if not any(feature.lower() == "json" for feature in features):
            raise CtagsToolError("Universal Ctags was built without JSON support")
        languages = tuple(
            line.strip()
            for line in self._text(executable, "--list-languages").splitlines()
            if line.strip()
        )
        with tempfile.TemporaryDirectory(prefix="electroboy-ctags-smoke-") as temp:
            root = Path(temp)
            (root / "smoke.c").write_text("int smoke(void) { return 0; }\n")
            result = self.process.run(
                _ctags_command(executable),
                cwd=root,
                input_bytes=b"smoke.c\0",
            )
            smoke_records, _warnings = _parse_raw_jsonl(result.stdout)
            output_version = next(
                (
                    str(record.get("path") or "")
                    for record in smoke_records
                    if record.get("_type") == "ptag"
                    and record.get("name") == "JSON_OUTPUT_VERSION"
                ),
                "",
            )
            smoke_found = any(
                record.get("_type") == "tag" and record.get("name") == "smoke"
                for record in smoke_records
            )
            if result.returncode != 0 or not smoke_found or not output_version:
                error = result.stderr.decode("utf-8", errors="replace").strip()
                raise CtagsToolError(f"Universal Ctags JSON smoke test failed: {error}")
        return CtagsCapability(
            executable=str(executable),
            version=version.splitlines()[0],
            source_revision=source_revision,
            json_supported=True,
            json_output_version=output_version,
            languages=languages,
            features=features,
        )

    def _text(self, executable: Path, *arguments: str) -> str:
        result = self.process.run([str(executable), *arguments], cwd=self.source_root)
        if result.returncode != 0:
            raise CtagsToolError(
                result.stderr.decode("utf-8", errors="replace").strip()
                or f"Universal Ctags {' '.join(arguments)} failed"
            )
        return result.stdout.decode("utf-8", errors="replace")

    def _source_revision(self) -> str:
        result = self.process.run(
            ["git", "rev-parse", "HEAD"], cwd=self.source_root, timeout=10
        )
        if result.returncode != 0:
            raise CtagsToolError("pinned Universal Ctags submodule is unavailable")
        return result.stdout.decode().strip()

    def _cached_executable(self, source_revision: str) -> Path:
        platform_key = f"{platform.system().lower()}-{platform.machine().lower()}"
        return self.cache_root / source_revision / platform_key / "bin" / "ctags"

    def _build(self, source_revision: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="electroboy-ctags-build-", dir=destination.parent.parent
        ) as temp:
            build_root = Path(temp) / "source"
            shutil.copytree(self.source_root, build_root, symlinks=True)
            commands = (
                ["./autogen.sh"],
                ["./configure", "--enable-json"],
                ["make", f"-j{max(1, os.cpu_count() or 1)}"],
            )
            for command in commands:
                result = self.process.run(command, cwd=build_root, timeout=300)
                if result.returncode != 0:
                    detail = result.stderr.decode("utf-8", errors="replace").strip()
                    raise CtagsToolError(
                        f"could not build pinned Universal Ctags: {detail}"
                    )
            built = build_root / "ctags"
            if not built.is_file():
                raise CtagsToolError("Universal Ctags build produced no executable")
            temporary = destination.with_suffix(".tmp")
            shutil.copy2(built, temporary)
            temporary.chmod(0o755)
            os.replace(temporary, destination)
        return destination


@dataclass(frozen=True)
class CtagsCapture:
    raw_path: Path
    invocation_path: Path
    records: tuple[dict[str, object], ...]
    metadata: dict[str, object]


class CtagsEvidenceService:
    """Capture raw Ctags JSONL for exactly the accepted file manifest."""

    def __init__(
        self,
        root: Path | str,
        *,
        toolchain: UniversalCtagsToolchain | None = None,
        process: ProcessAdapter | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.source = SourceManifestService(self.root)
        self.state_root = self.source.state_root
        self.raw_path = self.state_root / "universal-ctags.raw.jsonl"
        self.invocation_path = self.state_root / "universal-ctags-invocation.json"
        self.targeted_root = self.state_root / "targeted"
        self.process = process or SubprocessAdapter()
        self.toolchain = toolchain or UniversalCtagsToolchain(process=self.process)
        self._lock = threading.RLock()

    def capture(self, snapshot: SourceManifestSnapshot | None = None) -> CtagsCapture:
        snapshot = snapshot or self.source.load()
        if snapshot is None:
            raise CodeLearnerError("source manifest must be generated before Ctags")
        paths = [
            str(record["path"])
            for record in snapshot.files
            if record.get("source_status") != "submodule"
            and record.get("symlink") is not True
        ]
        started = utc_now()
        warning = ""
        capability: CtagsCapability | None = None
        raw = b""
        command: list[str] = []
        try:
            capability = self.toolchain.prepare()
            executable = Path(capability.executable)
            command = _ctags_command(executable)
            result = self.process.run(
                command,
                cwd=self.root,
                input_bytes=b"\0".join(path.encode() for path in paths) + b"\0",
                timeout=max(30.0, len(paths) / 10),
            )
            if result.returncode != 0:
                raise CtagsToolError(
                    result.stderr.decode("utf-8", errors="replace").strip()
                    or "Universal Ctags indexing failed"
                )
            raw = result.stdout
        except CtagsToolError as error:
            warning = str(error)
        records, parse_warnings = _parse_raw_jsonl(raw)
        warnings = [item for item in [warning, *parse_warnings] if item]
        metadata = {
            "schema_version": 1,
            "repository_revision": snapshot.revision,
            "status": "complete" if capability else "complete_with_warnings",
            "started_at": started,
            "completed_at": utc_now(),
            "command": command,
            "ambient_configuration_disabled": True,
            "input_paths": paths,
            "input_path_count": len(paths),
            "input_hash": _path_hash(paths),
            "raw_tag_count": sum(1 for item in records if item.get("_type") == "tag"),
            "raw_record_count": len(records),
            "warnings": warnings,
            "capability": capability.to_dict() if capability else {},
        }
        self._save(raw, metadata)
        self.source.record_symbol_evidence(
            {
                "provider": "universal-ctags",
                "raw_path": self.raw_path.relative_to(self.root).as_posix(),
                "invocation_path": self.invocation_path.relative_to(
                    self.root
                ).as_posix(),
                "raw_tag_count": metadata["raw_tag_count"],
                "warnings": warnings,
            }
        )
        return CtagsCapture(
            self.raw_path, self.invocation_path, tuple(records), metadata
        )

    def capture_target(self, path: str) -> list[dict[str, object]]:
        """Run a bounded one-file Ctags query before text-search fallback."""

        try:
            capability = self.toolchain.prepare()
            result = self.process.run(
                _ctags_command(Path(capability.executable)),
                cwd=self.root,
                input_bytes=path.encode() + b"\0",
            )
            if result.returncode != 0:
                return []
        except CtagsToolError:
            return []
        records, _warnings = _parse_raw_jsonl(result.stdout)
        selected = [
            record
            for record in records
            if record.get("_type") == "tag"
            and Path(str(record.get("path") or "")).as_posix() == path
        ]
        digest = hashlib.sha256(path.encode()).hexdigest()[:16]
        self.targeted_root.mkdir(parents=True, exist_ok=True)
        target = self.targeted_root / f"{digest}.jsonl"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(
            "".join(json.dumps(record, sort_keys=True) + "\n" for record in records),
            encoding="utf-8",
        )
        os.replace(temporary, target)
        return selected

    def load(self) -> CtagsCapture | None:
        if not self.raw_path.is_file() or not self.invocation_path.is_file():
            return None
        raw = self.raw_path.read_bytes()
        records, warnings = _parse_raw_jsonl(raw)
        try:
            metadata = json.loads(self.invocation_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CodeLearnerError(f"could not load Ctags invocation metadata: {error}")
        if not isinstance(metadata, dict):
            raise CodeLearnerError("Ctags invocation metadata must be an object")
        if warnings:
            metadata = {
                **metadata,
                "warnings": [*metadata.get("warnings", []), *warnings],
            }
        return CtagsCapture(
            self.raw_path, self.invocation_path, tuple(records), metadata
        )

    def _save(self, raw: bytes, metadata: Mapping[str, object]) -> None:
        with self._lock:
            self.state_root.mkdir(parents=True, exist_ok=True)
            raw_tmp = self.raw_path.with_suffix(".tmp")
            invocation_tmp = self.invocation_path.with_suffix(".tmp")
            raw_tmp.write_bytes(raw)
            invocation_tmp.write_text(
                json.dumps(dict(metadata), indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            os.replace(raw_tmp, self.raw_path)
            os.replace(invocation_tmp, self.invocation_path)


@dataclass(frozen=True)
class LocatorResolution:
    status: str
    locator: dict[str, object]
    canonical_key: str
    provenance: str
    matches: tuple[dict[str, object], ...] = ()
    message: str = ""


class SymbolLocatorResolver:
    """Query raw Ctags evidence and targeted source fallback on demand."""

    def __init__(
        self,
        root: Path | str,
        *,
        source: SourceManifestService | None = None,
        evidence: CtagsEvidenceService | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.source = source or SourceManifestService(self.root)
        self.evidence = evidence or CtagsEvidenceService(self.root)

    def query(
        self,
        *,
        name: str = "",
        file_id: str = "",
        kind: str = "",
        scope: str = "",
    ) -> list[dict[str, object]]:
        capture = self.evidence.load()
        if capture is None:
            return []
        files = self.source.load()
        if files is None:
            return []
        paths = {str(item["id"]): str(item["path"]) for item in files.files}
        expected_path = paths.get(file_id, "") if file_id else ""
        return [
            dict(record)
            for record in capture.records
            if record.get("_type") == "tag"
            and (not name or record.get("name") == name)
            and (
                not expected_path
                or Path(str(record.get("path") or "")).as_posix() == expected_path
            )
            and (not kind or record.get("kind") == kind)
            and (not scope or record.get("scope") == scope)
        ]

    def resolve(self, value: Mapping[str, object]) -> LocatorResolution:
        locator = SymbolLocator.from_mapping(value)
        snapshot = self.source.load()
        if snapshot is None:
            return LocatorResolution(
                "unresolved",
                locator.to_dict(),
                "",
                "",
                message="source manifest is missing",
            )
        file = snapshot.by_id().get(locator.file_id)
        if file is None:
            return LocatorResolution(
                "unresolved",
                locator.to_dict(),
                "",
                "",
                message="source file ID is unknown",
            )
        matches = self.query(
            name=locator.name,
            file_id=locator.file_id,
            kind=locator.kind if locator.kind != "symbol" else "",
            scope=locator.scope,
        )
        narrowed = _narrow_matches(matches, locator)
        if len(narrowed) == 1:
            resolved = _locator_from_tag(locator.file_id, narrowed[0], file)
            return LocatorResolution(
                "exact",
                resolved.to_dict(),
                resolved.canonical_key(snapshot.revision, str(file["path"])),
                "universal-ctags",
                (narrowed[0],),
            )
        if len(narrowed) > 1:
            return LocatorResolution(
                "ambiguous",
                locator.to_dict(),
                "",
                "universal-ctags",
                tuple(narrowed),
                "multiple Ctags definitions match the locator",
            )
        targeted = [
            record
            for record in self.evidence.capture_target(str(file["path"]))
            if record.get("name") == locator.name
            and (locator.kind == "symbol" or record.get("kind") == locator.kind)
            and (not locator.scope or record.get("scope") == locator.scope)
        ]
        targeted = _narrow_matches(targeted, locator)
        if len(targeted) == 1:
            resolved = _locator_from_tag(locator.file_id, targeted[0], file)
            return LocatorResolution(
                "exact",
                resolved.to_dict(),
                resolved.canonical_key(snapshot.revision, str(file["path"])),
                "targeted-universal-ctags",
                (targeted[0],),
            )
        if len(targeted) > 1:
            return LocatorResolution(
                "ambiguous",
                locator.to_dict(),
                "",
                "targeted-universal-ctags",
                tuple(targeted),
                "multiple targeted Ctags definitions match the locator",
            )
        fallback = RepositorySearchAdapter().analyze(self.root, [str(file["path"])])
        fallback_matches = [fact for fact in fallback if fact.name == locator.name]
        if len(fallback_matches) == 1:
            fact = fallback_matches[0]
            resolved = SymbolLocator(
                file_id=locator.file_id,
                name=fact.name,
                kind=fact.kind,
                scope="",
                language=fact.language,
                signature=fact.signature,
                start_line=fact.start_line,
                end_line=fact.end_line,
            )
            return LocatorResolution(
                "exact",
                resolved.to_dict(),
                resolved.canonical_key(snapshot.revision, str(file["path"])),
                "repository-search",
            )
        return LocatorResolution(
            "unresolved",
            locator.to_dict(),
            "",
            "repository-search",
            message="symbol was not confirmed by Ctags or repository search",
        )


def _ctags_command(executable: Path) -> list[str]:
    return [
        str(executable),
        "--options=NONE",
        "--output-format=json",
        "--fields=+neKSEs",
        "--extras=+p",
        "-f",
        "-",
        "--files0-from=-",
    ]


def _parse_raw_jsonl(raw: bytes) -> tuple[list[dict[str, object]], list[str]]:
    records: list[dict[str, object]] = []
    warnings: list[str] = []
    for line_number, line in enumerate(
        raw.decode("utf-8", errors="replace").splitlines(), 1
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            warnings.append(f"Ctags line {line_number}: {error.msg}")
            continue
        if not isinstance(record, dict):
            warnings.append(f"Ctags line {line_number}: record is not an object")
            continue
        records.append(record)
    return records, warnings


def _narrow_matches(
    matches: Sequence[Mapping[str, object]],
    locator: SymbolLocator,
) -> list[dict[str, object]]:
    selected = [dict(record) for record in matches]
    if locator.start_line > 0:
        exact = [record for record in selected if _line(record) == locator.start_line]
        if exact:
            selected = exact
    if locator.signature:
        exact = [
            record
            for record in selected
            if record.get("signature") == locator.signature
        ]
        if exact:
            selected = exact
    return selected


def _locator_from_tag(
    file_id: str,
    record: Mapping[str, object],
    file: Mapping[str, object],
) -> SymbolLocator:
    start = _line(record)
    return SymbolLocator(
        file_id=file_id,
        name=str(record.get("name") or ""),
        kind=str(record.get("kind") or "symbol"),
        scope=str(record.get("scope") or ""),
        language=str(record.get("language") or file.get("language") or ""),
        signature=str(record.get("signature") or ""),
        start_line=start,
        end_line=_positive(record.get("end"), start),
    )


def _line(record: Mapping[str, object]) -> int:
    return _positive(record.get("line"), 1)


def _positive(value: object, default: int) -> int:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and value > 0
        else default
    )


def _path_hash(paths: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.encode())
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()
