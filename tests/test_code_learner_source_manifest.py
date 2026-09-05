from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from electroboy.workflows.code_learner.domain import CodeLearnerError
from electroboy.workflows.code_learner.source_manifest import SourceManifestService


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def test_git_manifest_uses_tracked_working_tree_and_excludes_untracked(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    _git(root, "init", "-q")
    (root / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (root / "README.md").write_text("# Example\n", encoding="utf-8")
    _git(root, "add", "app.py", "README.md")
    (root / "ignored.py").write_text("ignored = True\n", encoding="utf-8")

    first = SourceManifestService(root).generate()
    first_revision = first.revision
    (root / "app.py").write_text("def main():\n    return 2\n", encoding="utf-8")
    second = SourceManifestService(root).generate()

    assert [record["path"] for record in first.files] == ["README.md", "app.py"]
    assert second.revision != first_revision
    assert (
        SourceManifestService(root).query(source_status="modified")[0]["path"]
        == "app.py"
    )


def test_non_git_manifest_is_deterministic_and_queries_mixed_languages(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "main.c").write_text("int main(void) { return 0; }\n")
    (tmp_path / "src" / "tool.py").write_text("def tool():\n    pass\n")
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "generated.c").write_text("int generated;\n")
    service = SourceManifestService(tmp_path)

    first = service.generate()
    second = service.generate()

    assert first.revision == second.revision
    assert [item["path"] for item in service.query(language="c")] == ["src/main.c"]
    assert not any(item["path"].startswith("build/") for item in first.files)


def test_manifest_records_symlink_without_reading_external_target(
    tmp_path: Path,
) -> None:
    target = tmp_path / "outside.txt"
    target.write_text("outside\n", encoding="utf-8")
    root = tmp_path / "repository"
    root.mkdir()
    os.symlink(target, root / "link.txt")

    record = SourceManifestService(root).generate().files[0]

    assert record["symlink"] is True
    assert record["symlink_target"] == str(target)
    assert record["size"] == len(str(target).encode())


def test_git_manifest_preserves_submodule_revision_and_executable_mode(
    tmp_path: Path,
) -> None:
    child = tmp_path / "child"
    child.mkdir()
    _git(child, "init", "-q")
    _git(child, "config", "user.email", "fixture@example.com")
    _git(child, "config", "user.name", "Fixture")
    (child / "library.py").write_text("VALUE = 1\n", encoding="utf-8")
    _git(child, "add", "library.py")
    _git(child, "commit", "-qm", "fixture")
    child_revision = subprocess.run(
        ["git", "-C", str(child), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    root = tmp_path / "parent"
    root.mkdir()
    _git(root, "init", "-q")
    script = root / "run.sh"
    script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    script.chmod(0o755)
    _git(root, "add", "run.sh")
    subprocess.run(
        [
            "git",
            "-c",
            "protocol.file.allow=always",
            "-C",
            str(root),
            "submodule",
            "add",
            "-q",
            str(child),
            "deps/child",
        ],
        check=True,
        capture_output=True,
    )

    files = SourceManifestService(root).generate().files
    by_path = {str(record["path"]): record for record in files}

    assert by_path["run.sh"]["executable"] is True
    assert by_path["deps/child"]["source_status"] == "submodule"
    assert by_path["deps/child"]["submodule_revision"] == child_revision


def test_source_query_rejects_escape_path(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Safe\n")
    service = SourceManifestService(tmp_path)
    service.generate()

    with pytest.raises(CodeLearnerError, match="escapes"):
        service.query(path="../outside")


def test_manifest_load_rejects_partial_or_mismatched_storage(tmp_path: Path) -> None:
    service = SourceManifestService(tmp_path)
    (tmp_path / "README.md").write_text("# Example\n")
    service.generate()
    service.files_path.write_text("", encoding="utf-8")

    with pytest.raises(CodeLearnerError, match="do not match"):
        service.load()
