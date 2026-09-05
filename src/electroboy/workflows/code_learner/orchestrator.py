"""Staged AI orchestration for durable Code Learner knowledge."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from time import sleep
from typing import Protocol
from uuid import uuid4

from electroboy.adapters.base import AgentInvocation, AgentResult, AgentRuntime
from electroboy.models import utc_now
from electroboy.runtime import runtime_for_role

from .analysis_passes import (
    ANALYSIS_PASSES,
    AnalysisPass,
    AnalysisScope,
    analysis_scopes,
    validate_pass_output,
)
from .contracts import parse_jsonl
from .domain import CodeLearnerError, repository_revision
from .knowledge_store import KnowledgeStore
from .skills import skill_prompt_reference, validate_packaged_skill

ANALYSIS_ROLE = "code_learner_analysis"
ProgressCallback = Callable[[dict[str, object]], None]


class RuntimeFactory(Protocol):
    def __call__(self, role: str, root: Path) -> AgentRuntime: ...


def analysis_pass_prompt(
    root: Path,
    analysis_pass: AnalysisPass,
    *,
    run_id: str,
    revision: str,
    store: KnowledgeStore,
    scope: AnalysisScope | None = None,
) -> str:
    """Build a narrowly scoped, explicit skill invocation."""

    schema = Path(__file__).with_name("schemas") / "knowledge.schema.json"
    existing = [
        path.relative_to(root).as_posix()
        for path in (
            store.knowledge_path("knowledge_manifest"),
            store.knowledge_path("entity"),
            store.knowledge_path("relationship"),
            store.knowledge_path("runtime_flow"),
            store.knowledge_path("diagnostic"),
            store.knowledge_path("knowledge_request"),
        )
        if path.is_file()
    ]
    existing_text = "\n".join(f"- {path}" for path in existing) or "- none"
    scope = scope or AnalysisScope("all")
    scope_text = ", ".join(scope.entity_ids) or "repository-wide"
    return f"""{skill_prompt_reference("codebase-analysis")}

Repository root: {root}
Analysis run ID: {run_id}
Repository revision: {revision}
Pass: {analysis_pass.name}
Pass scope: {scope.key}
Scoped entity IDs: {scope_text}
Canonical schema: {schema}

Objective:
{analysis_pass.objective}

Existing validated knowledge streams:
{existing_text}

Output expectation:
{analysis_pass.output_expectation}

{analysis_pass.contract}

Rules:
- Use a fresh context for this pass and durable files for continuity.
- Inspect the repository read-only and never modify tracked source.
- Do not write course prose.
- Preserve stable IDs from existing knowledge.
- Return strict JSONL only, with no Markdown fence or surrounding prose.
- Every emitted record must use the supplied run ID and revision.
- Later-pass output may be a patch; all referenced IDs must exist in existing
  knowledge or the same output.
""".strip()


class AnalysisOrchestrator:
    """Run bounded AI passes and durably merge each validated result."""

    def __init__(
        self,
        root: Path | str,
        *,
        runtime_factory: RuntimeFactory | None = None,
        passes: Iterable[AnalysisPass] = ANALYSIS_PASSES,
        max_attempts: int = 2,
        retry_delay: float = 0.0,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = KnowledgeStore(self.root)
        self.passes = tuple(passes)
        self.runtime_factory = runtime_factory or _default_runtime_factory
        self.max_attempts = max(1, max_attempts)
        self.retry_delay = max(0.0, retry_delay)

    def run(
        self,
        progress_callback: ProgressCallback | None = None,
    ) -> list[dict[str, object]]:
        validate_packaged_skill("codebase-analysis")
        checkpoint = self._checkpoint()
        run_id = str(checkpoint["analysis_run_id"])
        revision = str(checkpoint["repository_revision"])
        runtime = self.runtime_factory(ANALYSIS_ROLE, self.root)
        for analysis_pass in self.passes:
            pass_state = _pass_state(checkpoint, analysis_pass.name)
            if pass_state.get("status") == "completed":
                continue
            self._run_pass(
                runtime,
                analysis_pass,
                checkpoint,
                run_id=run_id,
                revision=revision,
                progress_callback=progress_callback,
            )
        checkpoint["status"] = "validated"
        checkpoint["completed_at"] = utc_now()
        self.store.save_checkpoint(checkpoint)
        self._progress(
            {
                "phase": "knowledge_validated",
                "percent": 92,
                "message": "Knowledge model validated.",
            },
            progress_callback,
        )
        return self.store.load_knowledge()

    def _run_pass(
        self,
        runtime: AgentRuntime,
        analysis_pass: AnalysisPass,
        checkpoint: dict[str, object],
        *,
        run_id: str,
        revision: str,
        progress_callback: ProgressCallback | None,
    ) -> None:
        pass_state = _pass_state(checkpoint, analysis_pass.name)
        pass_state.update({"status": "running", "started_at": utc_now()})
        self.store.save_checkpoint(checkpoint)
        scopes = analysis_scopes(analysis_pass, self.store.load_knowledge())
        for scope in scopes:
            self._run_scope(
                runtime,
                analysis_pass,
                scope,
                checkpoint,
                run_id=run_id,
                revision=revision,
                progress_callback=progress_callback,
            )
        pass_state.update(
            {"status": "completed", "completed_at": utc_now(), "error": ""}
        )
        self.store.save_checkpoint(checkpoint)

    def _run_scope(
        self,
        runtime: AgentRuntime,
        analysis_pass: AnalysisPass,
        scope: AnalysisScope,
        checkpoint: dict[str, object],
        *,
        run_id: str,
        revision: str,
        progress_callback: ProgressCallback | None,
    ) -> None:
        pass_state = _pass_state(checkpoint, analysis_pass.name)
        jobs = pass_state.setdefault("jobs", {})
        if not isinstance(jobs, dict):
            raise CodeLearnerError(
                f"analysis checkpoint jobs are invalid: {analysis_pass.name}"
            )
        job_state = jobs.setdefault(
            scope.key, {"status": "pending", "attempts": 0}
        )
        if not isinstance(job_state, dict):
            raise CodeLearnerError(
                f"analysis checkpoint job is invalid: {scope.key}"
            )
        if job_state.get("status") == "completed":
            return
        job_state.update({"status": "running", "started_at": utc_now()})
        self.store.save_checkpoint(checkpoint)
        self._progress(
            {
                "phase": analysis_pass.name,
                "percent": analysis_pass.percent,
                "message": (
                    f"Running {analysis_pass.name} knowledge pass ({scope.key})."
                ),
                "scope_ids": list(scope.entity_ids),
            },
            progress_callback,
        )
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            job_state["attempts"] = attempt
            self.store.save_checkpoint(checkpoint)
            result = runtime.invoke(
                AgentInvocation(
                    role=ANALYSIS_ROLE,
                    prompt=analysis_pass_prompt(
                        self.root,
                        analysis_pass,
                        run_id=run_id,
                        revision=revision,
                        store=self.store,
                        scope=scope,
                    ),
                    context_paths=[
                        path.relative_to(self.root).as_posix()
                        for path in self.store.knowledge_root.glob("*.jsonl")
                    ],
                )
            )
            try:
                self._accept_result(analysis_pass, scope, result)
            except (CodeLearnerError, ValueError) as error:
                last_error = str(error)
                job_state.update({"status": "retrying", "error": last_error})
                self.store.save_checkpoint(checkpoint)
                if attempt < self.max_attempts and self.retry_delay:
                    sleep(self.retry_delay)
                continue
            job_state.update(
                {"status": "completed", "completed_at": utc_now(), "error": ""}
            )
            self.store.save_checkpoint(checkpoint)
            return
        job_state.update({"status": "failed", "error": last_error})
        pass_state.update({"status": "failed", "error": last_error})
        checkpoint["status"] = "failed"
        self.store.save_checkpoint(checkpoint)
        raise CodeLearnerError(
            f"{analysis_pass.name} analysis scope {scope.key} failed after "
            f"{self.max_attempts} attempts: {last_error}"
        )

    def _accept_result(
        self,
        analysis_pass: AnalysisPass,
        scope: AnalysisScope,
        result: AgentResult,
    ) -> None:
        if not result.ok:
            raise CodeLearnerError(
                result.error or result.final_message or "analysis runtime failed"
            )
        output = result.final_message.strip()
        if not output:
            raise CodeLearnerError("analysis pass returned no JSONL")
        records = parse_jsonl(output, artifact="analysis pass")
        existing = self.store.load_knowledge()
        combined = {str(record["id"]): record for record in existing}
        combined.update({str(record.get("id") or ""): record for record in records})
        validate_pass_output(
            analysis_pass,
            combined.values(),
            scope_ids=scope.entity_ids,
        )
        if existing:
            self.store.merge_knowledge(records)
        else:
            self.store.save_knowledge(records)

    def _checkpoint(self) -> dict[str, object]:
        revision = repository_revision(self.root)
        existing = self.store.load_checkpoint()
        if existing and existing.get("repository_revision") == revision:
            return existing
        checkpoint: dict[str, object] = {
            "schema_version": 1,
            "analysis_run_id": uuid4().hex,
            "repository_revision": revision,
            "status": "running",
            "created_at": utc_now(),
            "passes": {
                analysis_pass.name: {"status": "pending", "attempts": 0}
                for analysis_pass in self.passes
            },
        }
        self.store.save_checkpoint(checkpoint)
        return checkpoint

    def _progress(
        self,
        record: dict[str, object],
        callback: ProgressCallback | None,
    ) -> None:
        event = {**record, "record_type": "progress", "updated_at": utc_now()}
        self.store.append_progress(event)
        if callback is not None:
            callback(event)


def _pass_state(checkpoint: dict[str, object], pass_name: str) -> dict[str, object]:
    passes = checkpoint.setdefault("passes", {})
    if not isinstance(passes, dict):
        raise CodeLearnerError("analysis checkpoint passes must be an object")
    state = passes.setdefault(pass_name, {"status": "pending", "attempts": 0})
    if not isinstance(state, dict):
        raise CodeLearnerError(f"analysis checkpoint pass is invalid: {pass_name}")
    return state


def _default_runtime_factory(role: str, root: Path) -> AgentRuntime:
    return runtime_for_role(role, root, execution_root=root)
