"""Disposable repository workspace for Code Learner AI turns."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from collections.abc import Iterable, Mapping
from pathlib import Path

from electroboy.adapters.base import AgentInvocation, AgentResult, AgentRuntime

from .domain import CodeLearnerError
from .source_manifest import PHASE3_ROOT


class IsolatedAnalysisWorkspace:
    """Run AI inspection against a disposable copy of selected repository data."""

    def __init__(self, root: Path | str, runtime_factory) -> None:
        self.root = Path(root).expanduser().resolve()
        self.runtime_factory = runtime_factory
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        self.workspace: Path | None = None

    def open(self, files: Iterable[Mapping[str, object]]) -> Path:
        self.close()
        self._temporary = tempfile.TemporaryDirectory(prefix="electroboy-code-learner-")
        self.workspace = Path(self._temporary.name) / self.root.name
        self.workspace.mkdir(parents=True)
        _initialize_git_metadata(self.workspace)
        for record in files:
            relative = Path(str(record.get("path") or ""))
            source = self.root / relative
            if not _valid_relative_path(relative):
                raise CodeLearnerError(
                    f"cannot isolate source-manifest path: {relative.as_posix()}"
                )
            target = self.workspace / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            self._copy_manifest_entry(record, source, target)
        self._copy_support_state()
        return self.workspace

    def runtime(self, role: str) -> AgentRuntime:
        if self.workspace is None:
            raise CodeLearnerError("isolated analysis workspace is not open")
        self._copy_support_state()
        return _RelocatedRuntime(
            self.runtime_factory(role, self.workspace),
            source_root=self.root,
            workspace=self.workspace,
        )

    def close(self) -> None:
        if self._temporary is not None:
            self._temporary.cleanup()
        self._temporary = None
        self.workspace = None

    def _copy_support_state(self) -> None:
        if self.workspace is None:
            return
        source = self.root / PHASE3_ROOT
        if source.is_dir():
            shutil.copytree(
                source,
                self.workspace / PHASE3_ROOT,
                dirs_exist_ok=True,
            )
        rules = self.root / ".electroboy" / "local" / "agent-rules"
        if rules.is_dir():
            shutil.copytree(
                rules,
                self.workspace / ".electroboy" / "local" / "agent-rules",
                dirs_exist_ok=True,
            )

    def _copy_manifest_entry(
        self,
        record: Mapping[str, object],
        source: Path,
        target: Path,
    ) -> None:
        if record.get("source_status") == "submodule":
            target.mkdir(exist_ok=True)
            return
        if bool(record.get("symlink")):
            if not source.is_symlink():
                raise CodeLearnerError(
                    f"source-manifest symlink is unavailable: {record.get('path')}"
                )
            link_target = str(record.get("symlink_target") or "")
            if not link_target or link_target != source.readlink().as_posix():
                raise CodeLearnerError(
                    f"source-manifest symlink changed: {record.get('path')}"
                )
            resolved_target = (source.parent / link_target).resolve()
            if not _within(self.root, resolved_target):
                raise CodeLearnerError(
                    f"source-manifest symlink escapes repository: {record.get('path')}"
                )
            target.symlink_to(
                link_target,
                target_is_directory=resolved_target.is_dir(),
            )
            return
        if not source.is_file():
            raise CodeLearnerError(
                f"cannot isolate source-manifest path: {record.get('path')}"
            )
        shutil.copy2(source, target)


class _RelocatedRuntime(AgentRuntime):
    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        source_root: Path,
        workspace: Path,
    ) -> None:
        self.runtime = runtime
        self.source_root = source_root
        self.workspace = workspace

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        source = str(self.source_root)
        target = str(self.workspace)
        relocated = AgentInvocation(
            role=invocation.role,
            prompt=invocation.prompt.replace(source, target),
            context_paths=[
                path.replace(source, target) for path in invocation.context_paths
            ],
            output_schema=invocation.output_schema,
            provider_session_id=invocation.provider_session_id,
            fork_provider_session_id=invocation.fork_provider_session_id,
            progress_path=invocation.progress_path,
            event_callback=invocation.event_callback,
            cancel_event=invocation.cancel_event,
        )
        return self.runtime.invoke(relocated)


def _within(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _valid_relative_path(path: Path) -> bool:
    return bool(path.parts) and not path.is_absolute() and ".." not in path.parts


def _initialize_git_metadata(workspace: Path) -> None:
    try:
        completed = subprocess.run(
            ["git", "init", "--quiet"],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        raise CodeLearnerError(f"cannot initialize isolated Git metadata: {error}")
    if completed.returncode != 0:
        raise CodeLearnerError(
            "cannot initialize isolated Git metadata: "
            + (completed.stderr.strip() or f"exit code {completed.returncode}")
        )
