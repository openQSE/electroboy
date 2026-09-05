from __future__ import annotations

from pathlib import Path

from electroboy.adapters.base import AgentInvocation, AgentResult
from electroboy.workflows.code_learner.isolated_runtime import (
    IsolatedAnalysisWorkspace,
)
from electroboy.workflows.code_learner.source_manifest import SourceManifestService


class _WritingRuntime:
    def __init__(self, root: Path, observations: list[tuple[Path, str]]) -> None:
        self.root = root
        self.observations = observations

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        self.observations.append((self.root, invocation.prompt))
        (self.root / "ai-created.txt").write_text("discarded", encoding="utf-8")
        return AgentResult(True, "{}")


def test_isolated_runtime_discards_unreported_ai_writes_and_relocates_paths(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "main.py").write_text("print('source')\n", encoding="utf-8")
    source = SourceManifestService(root).generate()
    observations: list[tuple[Path, str]] = []
    workspace = IsolatedAnalysisWorkspace(
        root,
        lambda _role, runtime_root: _WritingRuntime(runtime_root, observations),
    )

    isolated_root = workspace.open(source.files)
    assert (isolated_root / ".git").is_dir()
    result = workspace.runtime("code_learner_analysis").invoke(
        AgentInvocation(
            role="code_learner_analysis",
            prompt=f"Inspect {root / 'main.py'}.",
        )
    )

    assert result.ok is True
    assert observations == [(isolated_root, f"Inspect {isolated_root / 'main.py'}.")]
    assert (isolated_root / "ai-created.txt").is_file()
    assert (root / "ai-created.txt").exists() is False
    workspace.close()
    assert isolated_root.exists() is False


def test_isolated_runtime_refreshes_host_owned_phase3_state(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    (root / "main.py").write_text("print('source')\n", encoding="utf-8")
    source = SourceManifestService(root).generate()
    workspace = IsolatedAnalysisWorkspace(root, lambda _role, _root: None)
    isolated_root = workspace.open(source.files)
    host_state = root / ".electroboy/code-learner/phase3/modules/manifest.json"
    host_state.parent.mkdir(parents=True, exist_ok=True)
    host_state.write_text('{"status":"complete"}\n', encoding="utf-8")

    workspace._copy_support_state()

    isolated_state = isolated_root / host_state.relative_to(root)
    assert isolated_state.read_text(encoding="utf-8") == '{"status":"complete"}\n'
    workspace.close()


def test_isolated_runtime_preserves_internal_directory_symlink(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    config = root / "config"
    config.mkdir(parents=True)
    (config / "settings.conf").write_text("enabled=true\n", encoding="utf-8")
    link = root / "prov" / "psm3" / "config"
    link.parent.mkdir(parents=True)
    link.symlink_to("../../config", target_is_directory=True)
    records = [
        {"path": "config/settings.conf"},
        {
            "path": "prov/psm3/config",
            "symlink": True,
            "symlink_target": "../../config",
        },
    ]
    workspace = IsolatedAnalysisWorkspace(root, lambda _role, _root: None)

    isolated_root = workspace.open(records)

    isolated_link = isolated_root / "prov/psm3/config"
    assert isolated_link.is_symlink()
    assert isolated_link.readlink().as_posix() == "../../config"
    assert (isolated_link / "settings.conf").read_text(encoding="utf-8") == (
        "enabled=true\n"
    )
    workspace.close()


def test_isolated_runtime_tolerates_unavailable_submodule_gitlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repository"
    root.mkdir()
    workspace = IsolatedAnalysisWorkspace(root, lambda _role, _root: None)

    isolated_root = workspace.open(
        [
            {
                "path": "vendor/optional-library",
                "source_status": "submodule",
                "submodule_revision": "0123456789abcdef",
            }
        ]
    )

    assert (isolated_root / "vendor/optional-library").is_dir()
    workspace.close()
