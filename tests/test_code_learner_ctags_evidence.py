from __future__ import annotations

import json
from pathlib import Path

import pytest

from electroboy.workflows.code_learner.ctags_evidence import (
    CtagsCapability,
    CtagsEvidenceService,
    CtagsToolError,
    LocatorResolution,
    ProcessResult,
    SymbolLocatorResolver,
    UniversalCtagsToolchain,
)
from electroboy.workflows.code_learner.source_manifest import SourceManifestService


class FakeToolchain:
    def __init__(self, *, error: str = "") -> None:
        self.error = error

    def prepare(self) -> CtagsCapability:
        if self.error:
            raise CtagsToolError(self.error)
        return CtagsCapability(
            executable="/fake/ctags",
            version="Universal Ctags 1.0",
            source_revision="pinned",
            json_supported=True,
            json_output_version="1.0",
            languages=("C", "Python", "JavaScript"),
            features=("json",),
        )


class FakeProcess:
    def __init__(self, records: list[dict[str, object]]) -> None:
        self.records = records
        self.calls: list[tuple[list[str], Path, bytes]] = []

    def run(
        self,
        command,
        *,
        cwd: Path,
        input_bytes: bytes = b"",
        timeout: float = 30.0,
    ) -> ProcessResult:
        self.calls.append((list(command), cwd, input_bytes))
        raw = "".join(json.dumps(record) + "\n" for record in self.records).encode()
        return ProcessResult(0, raw, b"")


class VerifyProcess:
    def __init__(self, version: str = "Universal Ctags 1.0") -> None:
        self.version = version

    def run(
        self,
        command,
        *,
        cwd: Path,
        input_bytes: bytes = b"",
        timeout: float = 30.0,
    ) -> ProcessResult:
        argument = command[1] if len(command) > 1 else ""
        if argument == "--version":
            return ProcessResult(0, (self.version + "\n").encode(), b"")
        if argument == "--list-features":
            return ProcessResult(
                0,
                b"#NAME DESCRIPTION\njson supports json format output\n"
                b"wildcards supports wildcard file names\n",
                b"",
            )
        if argument == "--list-languages":
            return ProcessResult(0, b"C\nPython\n", b"")
        return ProcessResult(
            0,
            b'{"_type": "ptag", "name": "JSON_OUTPUT_VERSION", "path": "1.0"}\n'
            b'{"_type": "tag", "name": "smoke", "path": "smoke.c", '
            b'"kind": "function", "line": 1}\n',
            b"",
        )


def _repository(root: Path) -> SourceManifestService:
    (root / "app.py").write_text(
        "def main():\n    return 1\n\ndef duplicate():\n    return 2\n",
        encoding="utf-8",
    )
    (root / "main.c").write_text("int start(void) { return 0; }\n")
    (root / "view.js").write_text("export function render() {}\n")
    source = SourceManifestService(root)
    source.generate()
    return source


def _tag(
    name: str,
    path: str,
    language: str,
    line: int,
    *,
    kind: str = "function",
    scope: str = "",
) -> dict[str, object]:
    return {
        "_type": "tag",
        "name": name,
        "path": path,
        "language": language,
        "kind": kind,
        "line": line,
        "end": line + 1,
        "scope": scope,
    }


def test_capture_uses_exact_manifest_paths_and_preserves_raw_jsonl(
    tmp_path: Path,
) -> None:
    source = _repository(tmp_path)
    records = [
        {"_type": "ptag", "name": "JSON_OUTPUT_VERSION", "path": "1.0"},
        _tag("main", "app.py", "Python", 1),
        _tag("start", "main.c", "C", 1),
        _tag("render", "view.js", "JavaScript", 1),
    ]
    process = FakeProcess(records)
    evidence = CtagsEvidenceService(
        tmp_path,
        toolchain=FakeToolchain(),
        process=process,
    )

    capture = evidence.capture(source.load())

    command, cwd, stdin = process.calls[0]
    assert cwd == tmp_path
    assert "--options=NONE" in command
    assert set(command[-3:]) == {
        "app.py",
        "main.c",
        "view.js",
    }
    assert stdin == b""
    assert capture.metadata["input_transport"] == "bounded-argv-batches"
    assert capture.metadata["invocation_count"] == 1
    assert capture.metadata["raw_tag_count"] == 3
    assert capture.raw_path.read_text().count("\n") == 4
    assert source.load().manifest["raw_tag_count"] == 3


def test_locator_resolver_handles_exact_ambiguous_and_fallback_matches(
    tmp_path: Path,
) -> None:
    source = _repository(tmp_path)
    process = FakeProcess(
        [
            _tag("main", "app.py", "Python", 1),
            _tag("duplicate", "app.py", "Python", 4, scope="one"),
            _tag("duplicate", "app.py", "Python", 4, scope="two"),
        ]
    )
    evidence = CtagsEvidenceService(
        tmp_path, toolchain=FakeToolchain(), process=process
    )
    evidence.capture(source.load())
    resolver = SymbolLocatorResolver(tmp_path, source=source, evidence=evidence)

    exact = resolver.resolve(
        {
            "file_id": "file:app.py",
            "name": "main",
            "kind": "function",
            "start_line": 1,
            "end_line": 2,
        }
    )
    ambiguous = resolver.resolve(
        {
            "file_id": "file:app.py",
            "name": "duplicate",
            "kind": "function",
            "start_line": 1,
            "end_line": 1,
        }
    )
    fallback = resolver.resolve(
        {
            "file_id": "file:main.c",
            "name": "start",
            "kind": "function",
            "start_line": 1,
            "end_line": 1,
        }
    )

    assert isinstance(exact, LocatorResolution)
    assert exact.status == "exact" and exact.provenance == "universal-ctags"
    assert ambiguous.status == "ambiguous" and len(ambiguous.matches) == 2
    assert fallback.status == "exact" and fallback.provenance == "repository-search"
    assert len(process.calls) == 2
    assert process.calls[-1][0][-1] == "main.c"
    assert process.calls[-1][2] == b""
    assert any(evidence.targeted_root.glob("*.jsonl"))


def test_ctags_unavailable_is_a_coverage_warning_not_a_source_failure(
    tmp_path: Path,
) -> None:
    source = _repository(tmp_path)
    evidence = CtagsEvidenceService(
        tmp_path,
        toolchain=FakeToolchain(error="JSON support unavailable"),
        process=FakeProcess([]),
    )

    capture = evidence.capture(source.load())

    assert capture.metadata["status"] == "complete_with_warnings"
    assert capture.metadata["warnings"] == ["JSON support unavailable"]
    assert source.load().manifest["status"] == "complete"


def test_toolchain_rejects_non_universal_ctags(tmp_path: Path) -> None:
    executable = tmp_path / "ctags"
    executable.write_text("fixture\n")
    toolchain = UniversalCtagsToolchain(
        source_root=tmp_path,
        executable=executable,
        process=VerifyProcess("Exuberant Ctags 5.9"),
    )

    with pytest.raises(CtagsToolError, match="not Universal"):
        toolchain.verify(executable)


def test_toolchain_verifies_json_parsers_and_smoke_output(tmp_path: Path) -> None:
    executable = tmp_path / "ctags"
    executable.write_text("fixture\n")
    capability = UniversalCtagsToolchain(
        source_root=tmp_path,
        executable=executable,
        process=VerifyProcess(),
    ).verify(
        executable,
        source_revision="pinned-ctags",
        jansson_revision="pinned-jansson",
    )

    assert capability.json_supported is True
    assert capability.json_output_version == "1.0"
    assert capability.source_revision == "pinned-ctags"
    assert capability.to_dict()["dependencies"] == {"jansson": "pinned-jansson"}
    assert capability.languages == ("C", "Python")


def test_tool_cache_key_includes_ctags_jansson_platform_and_json(
    tmp_path: Path,
) -> None:
    toolchain = UniversalCtagsToolchain(
        source_root=tmp_path / "ctags",
        dependency_root=tmp_path / "jansson",
        cache_root=tmp_path / "cache",
    )

    first = toolchain._cached_executable("ctags-a", "jansson-a")
    different_ctags = toolchain._cached_executable("ctags-b", "jansson-a")
    different_jansson = toolchain._cached_executable("ctags-a", "jansson-b")

    assert first.name == "ctags"
    assert first.parent.name == "bin"
    assert first != different_ctags
    assert first != different_jansson
