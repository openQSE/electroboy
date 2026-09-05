from __future__ import annotations

import json
from pathlib import Path

import pytest

from electroboy.workflows.code_learner.domain import (
    CodeLearnerStore,
    analyze_repository,
    create_walkthrough,
)


def _write_repository(root: Path, layout: str) -> Path:
    root.mkdir()
    (root / "README.md").write_text(f"# {layout} fixture\n", encoding="utf-8")
    if layout == "python":
        source = root / "src" / "sample"
        source.mkdir(parents=True)
        (root / "pyproject.toml").write_text(
            "[project]\nname = 'sample'\n",
            encoding="utf-8",
        )
        (source / "service.py").write_text(
            "def transform(value):\n    return str(value)\n",
            encoding="utf-8",
        )
    elif layout == "javascript":
        source = root / "src"
        source.mkdir()
        (root / "package.json").write_text(
            '{"name":"sample","scripts":{"test":"node --test"}}\n',
            encoding="utf-8",
        )
        (source / "service.js").write_text(
            "export function transform(value) {\n  return String(value);\n}\n",
            encoding="utf-8",
        )
    else:
        source = root / "src"
        source.mkdir()
        (root / "Makefile").write_text("all:\n\tcc src/main.c\n", encoding="utf-8")
        (source / "main.c").write_text(
            "int transform(int value) { return value; }\n",
            encoding="utf-8",
        )
    return root


def _v1_corpus() -> str:
    records = [
        {
            "record_type": "course_manifest",
            "schema_version": 1,
            "repository_name": "Sample",
            "repository_purpose": "Characterize v1 course behavior.",
            "primary_languages": ["python"],
            "architecture_step_ids": ["architecture.purpose"],
            "module_ids": ["module.sample"],
            "function_index_count": 1,
            "confidence": 0.9,
        },
        {
            "record_type": "architecture_step",
            "id": "architecture.purpose",
            "title": "Purpose",
            "body": "The sample exposes one transformation module.",
            "source_refs": [{"path": "README.md", "start_line": 1, "end_line": 1}],
            "related_module_ids": ["module.sample"],
            "confidence": 0.9,
        },
        {
            "record_type": "module",
            "id": "module.sample",
            "name": "Sample",
            "purpose": "Transform values.",
            "primary_files": ["src/sample/service.py"],
            "source_refs": [
                {"path": "src/sample/service.py", "start_line": 1, "end_line": 2}
            ],
            "confidence": 0.9,
        },
        {
            "record_type": "module_step",
            "id": "module.sample.boundary",
            "module_id": "module.sample",
            "title": "Boundary",
            "body": "The module owns transformation.",
            "source_refs": [
                {"path": "src/sample/service.py", "start_line": 1, "end_line": 2}
            ],
            "confidence": 0.9,
        },
        {
            "record_type": "function_index_entry",
            "symbol": "transform",
            "display_name": "transform",
            "kind": "function",
            "module_id": "module.sample",
            "path": "src/sample/service.py",
            "start_line": 1,
            "end_line": 2,
            "purpose": "Transform one value.",
            "source_refs": [
                {"path": "src/sample/service.py", "start_line": 1, "end_line": 2}
            ],
            "confidence": 0.9,
        },
        {
            "record_type": "function_lesson",
            "symbol": "transform",
            "display_name": "transform",
            "title": "Transform",
            "body": "The function converts its input to text.",
            "source_refs": [
                {"path": "src/sample/service.py", "start_line": 1, "end_line": 2}
            ],
            "confidence": 0.9,
        },
    ]
    return "\n".join(json.dumps(record) for record in records)


def _write_extension_repository(root: Path) -> Path:
    transports = root / "src" / "transports"
    transports.mkdir(parents=True)
    (root / "README.md").write_text(
        "# Extension fixture\n\nSelects one transport at runtime.\n",
        encoding="utf-8",
    )
    (transports / "base.py").write_text(
        "class Transport:\n"
        "    def send(self, value):\n"
        "        raise NotImplementedError\n",
        encoding="utf-8",
    )
    (transports / "memory.py").write_text(
        "from .base import Transport\n\n"
        "class MemoryTransport(Transport):\n"
        "    def send(self, value):\n        return value\n",
        encoding="utf-8",
    )
    (transports / "tcp.py").write_text(
        "from .base import Transport\n\n"
        "class TcpTransport(Transport):\n"
        "    def send(self, value):\n        return value\n",
        encoding="utf-8",
    )
    return root


@pytest.mark.parametrize("layout", ["python", "javascript", "c"])
def test_current_repository_analysis_accepts_language_layouts(
    tmp_path: Path,
    layout: str,
) -> None:
    repository = _write_repository(tmp_path / layout, layout)

    analysis = analyze_repository(repository)

    assert analysis.source_files
    assert layout in analysis.language_counts
    assert not any(path.startswith(".electroboy/") for path in analysis.source_files)


def test_v1_corpus_supports_all_walkthrough_modes(tmp_path: Path) -> None:
    repository = _write_repository(tmp_path / "python", "python")
    records = CodeLearnerStore(repository).save_corpus_jsonl(_v1_corpus())

    architecture = create_walkthrough(repository, learning_mode="Architecture")
    module = create_walkthrough(
        repository,
        learning_mode="Module",
        target="module.sample",
    )
    function = create_walkthrough(
        repository,
        learning_mode="Function",
        target="transform",
    )

    assert records[0]["schema_version"] == 1
    assert architecture.learning_mode == "architecture"
    assert module.mode_target == "module.sample"
    assert function.mode_target == "transform"
    assert all(course.steps for course in (architecture, module, function))


def test_baseline_fixture_contains_multiple_extension_implementations(
    tmp_path: Path,
) -> None:
    repository = _write_extension_repository(tmp_path / "extensions")

    analysis = analyze_repository(repository)

    assert "src/transports/base.py" in analysis.source_files
    assert "src/transports/memory.py" in analysis.source_files
    assert "src/transports/tcp.py" in analysis.source_files
