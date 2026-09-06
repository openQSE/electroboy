"""Durable warning-tolerant orchestration for Code Learner Phase 3."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from time import perf_counter
from uuid import uuid4

from electroboy.adapters.base import AgentInvocation, AgentResult, AgentRuntime
from electroboy.models import utc_now
from electroboy.runtime import runtime_for_role

from .agent_retry import RetryableAgentError, parse_agent_jsonl, require_agent_output
from .agent_sessions import AgentSessionRegistry, ReusableAgentRuntime
from .architecture_knowledge import ArchitectureKnowledgeService
from .component_manifest import ComponentManifestService
from .components import ComponentCandidateService
from .ctags_evidence import CtagsEvidenceService
from .domain import CodeLearnerError
from .function_knowledge import FunctionKnowledgeService
from .generation import LearnerGenerationStore
from .initialization import InitializationLease
from .isolated_runtime import IsolatedAnalysisWorkspace
from .module_knowledge import ModuleKnowledgeService
from .modules import ModuleSynthesisService
from .overlap import ComponentOverlapService
from .phase3_contracts import load_phase3_schema, parse_phase3_jsonl
from .phase3_courses import Phase3CourseService
from .phase3_prompts import component_discovery_prompt
from .phase3_revision import Phase3RevisionInvalidator
from .phase3_store import Phase3Store
from .progress import AgentActivityReporter, InvocationHeartbeat
from .reconciliation import ComponentReconciliationService
from .relationships import ModuleRelationshipService
from .skills import validate_packaged_skill
from .source_manifest import SourceManifestService

ProgressCallback = Callable[[dict[str, object]], None]
RuntimeFactory = Callable[[str, Path], AgentRuntime]

STAGES = (
    "source_files",
    "ctags_evidence",
    "components",
    "overlap_groups",
    "reconciliations",
    "file_coverage",
    "missing_file_investigation",
    "component_manifest",
    "modules",
    "relationships",
    "architecture_knowledge",
    "module_knowledge",
    "important_functions",
    "courses",
    "rendering",
    "activation",
)
STAGE_PERCENT = {
    name: percent
    for name, percent in zip(
        STAGES,
        (2, 7, 14, 21, 27, 34, 39, 44, 52, 61, 69, 77, 84, 92, 97, 99),
        strict=True,
    )
}


@dataclass(frozen=True)
class Phase3InitializationResult:
    repository_revision: str
    status: str
    warning_count: int
    architecture_course_path: str
    module_course_count: int


class Phase3InitializationCancelled(RuntimeError):
    """Raised when an operator stops an active initialization run."""


class Phase3InitializationPipeline:
    """Run Phase 3 stages with host-owned state and independently resumable work."""

    def __init__(
        self,
        root: Path | str,
        *,
        runtime_factory: RuntimeFactory | None = None,
        eager_function_budget: int = 0,
        cancel_event: Event | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = Phase3Store(self.root)
        self.generation = LearnerGenerationStore(self.root)
        self.agent_sessions = AgentSessionRegistry(self.root, store=self.store)
        self.source = SourceManifestService(self.root)
        self.invalidator = Phase3RevisionInvalidator(self.root, store=self.store)
        self.ctags = CtagsEvidenceService(self.root)
        self.candidates = ComponentCandidateService(self.root, source=self.source)
        self.overlaps = ComponentOverlapService(self.root, store=self.store)
        self._base_runtime_factory = runtime_factory or _runtime_factory
        self._analysis_workspace = IsolatedAnalysisWorkspace(
            self.root, self._base_runtime_factory
        )
        self._callback: ProgressCallback | None = None
        self.cancel_event = cancel_event or Event()
        self.reconciliations = ComponentReconciliationService(
            self.root, store=self.store, runtime_factory=self._observed_runtime
        )
        self.components = ComponentManifestService(
            self.root,
            store=self.store,
            source=self.source,
            candidates=self.candidates,
            overlaps=self.overlaps,
            reconciliations=self.reconciliations,
        )
        self.modules = ModuleSynthesisService(
            self.root,
            store=self.store,
            source=self.source,
            components=self.components,
            runtime_factory=self._observed_runtime,
        )
        self.relationships = ModuleRelationshipService(
            self.root,
            store=self.store,
            source=self.source,
            components=self.components,
            modules=self.modules,
            runtime_factory=self._observed_runtime,
        )
        self.architecture = ArchitectureKnowledgeService(
            self.root,
            store=self.store,
            runtime_factory=self._observed_runtime,
        )
        self.module_knowledge = ModuleKnowledgeService(
            self.root,
            store=self.store,
            runtime_factory=self._observed_runtime,
        )
        self.functions = FunctionKnowledgeService(
            self.root,
            store=self.store,
            runtime_factory=self._observed_runtime,
            eager_budget=eager_function_budget,
        )
        self.courses = Phase3CourseService(
            self.root,
            store=self.store,
            runtime_factory=self._observed_runtime,
        )
        self._active_stage = "setup"

    def run(
        self,
        progress_callback: ProgressCallback | None = None,
        *,
        acquire_lease: bool = True,
    ) -> Phase3InitializationResult:
        self._callback = progress_callback
        job_id = uuid4().hex
        lease = None
        revision = "unknown"
        try:
            self._check_cancelled()
            load_phase3_schema()
            validate_packaged_skill("codebase-analysis")
            source_started = perf_counter()
            previous_source = self.source.load()
            source = self.source.generate()
            revision = source.revision
            self.agent_sessions.prepare(revision)
            if acquire_lease:
                lease = InitializationLease.acquire(
                    self.root,
                    job_id,
                    repository_revision=revision,
                )
            self.store.discard_failed_terminal_result()
            self.invalidator.run(previous_source, source)
            checkpoint = self._checkpoint(revision, job_id)
            self._complete_stage(
                checkpoint,
                "source_files",
                message=f"Enumerated {len(source.files)} selected repository files.",
                duration_seconds=perf_counter() - source_started,
            )
            self._check_cancelled()
            run_id = str(checkpoint["analysis_run_id"])
            self._run_stage(
                checkpoint,
                "ctags_evidence",
                lambda: self._capture_ctags(source),
                ready=lambda: self.ctags.load_current(source) is not None,
                resume=lambda: self.ctags.load_current(source),
            )
            self._run_stage(
                checkpoint,
                "components",
                lambda: self._discover_components(run_id, source.revision),
                ready=lambda: bool(self.candidates.load()),
                resume=self.candidates.load,
            )
            self._run_stage(
                checkpoint,
                "overlap_groups",
                lambda: self.overlaps.build(self.candidates.load()),
                ready=lambda: self.overlaps.path.is_file(),
                resume=self.overlaps.load,
            )
            self._run_stage(
                checkpoint,
                "reconciliations",
                lambda: self._reconcile_all(run_id),
                ready=lambda: not self.reconciliations.pending_group_ids(),
                warning_tolerant=True,
                resume=self.reconciliations.load,
                fallback=self.reconciliations.load,
            )
            component_snapshot = self._run_stage(
                checkpoint,
                "file_coverage",
                lambda: self.components.build(analysis_run_id=run_id),
                ready=lambda: self.components.load() is not None,
                resume=self.components.load,
            )
            unresolved_count = int(
                component_snapshot.coverage.get("unresolved_count") or 0
            )
            self._complete_stage(
                checkpoint,
                "missing_file_investigation",
                message=(
                    "Skipped AI file-coverage investigation; "
                    f"retained {unresolved_count} uncovered files as warnings."
                    if unresolved_count
                    else "No uncovered files require a coverage warning."
                ),
            )
            self._run_stage(
                checkpoint,
                "component_manifest",
                lambda: self.components.load(),
                ready=lambda: self.components.load() is not None,
                resume=self.components.load,
            )
            self._run_stage(
                checkpoint,
                "modules",
                lambda: self.modules.synthesize(analysis_run_id=run_id),
                ready=lambda: self.modules.load() is not None,
                resume=self.modules.load,
            )
            self._run_stage(
                checkpoint,
                "relationships",
                lambda: self.relationships.generate(analysis_run_id=run_id),
                ready=lambda: self.relationships.relationships_path.is_file(),
                warning_tolerant=True,
                resume=lambda: self.store.read_jsonl(
                    self.relationships.relationships_path
                ),
                fallback=self.relationships.rebuild,
            )
            self._run_stage(
                checkpoint,
                "architecture_knowledge",
                lambda: self.architecture.generate(analysis_run_id=run_id),
                ready=lambda: self.architecture.load() is not None,
                resume=self.architecture.load,
            )
            self._complete_stage(
                checkpoint,
                "module_knowledge",
                message="Deferred Module knowledge to background generation.",
            )
            self._complete_stage(
                checkpoint,
                "important_functions",
                message="Deferred Function knowledge until a symbol is requested.",
            )
            course_summary = self._run_stage(
                checkpoint,
                "courses",
                lambda: self._build_architecture_course(run_id),
                ready=self._required_courses_ready,
                resume=self._resume_course_summary,
            )
            self._run_stage(
                checkpoint,
                "rendering",
                self._verify_rendered_courses,
                ready=self._required_courses_rendered,
                resume=lambda: self.courses.markdown_path(
                    "architecture", "architecture:current"
                ),
            )
            self._run_stage(
                checkpoint,
                "activation",
                lambda: self._activate(revision),
                ready=lambda: self.store.load_terminal_result() is not None,
                resume=self.store.load_terminal_result,
            )
            terminal = self.store.load_terminal_result()
            return Phase3InitializationResult(
                revision,
                str(terminal["status"]),
                int(terminal["warning_count"]),
                str(course_summary["architecture_course_path"]),
                int(course_summary["module_course_count"]),
            )
        except Phase3InitializationCancelled:
            raise
        except Exception as error:
            self._fail(revision, error)
            raise
        finally:
            if lease is not None:
                lease.release()
            self._analysis_workspace.close()
            self._callback = None

    def _run_stage(
        self,
        checkpoint: dict[str, object],
        stage: str,
        operation: Callable[[], object],
        *,
        ready: Callable[[], bool],
        warning_tolerant: bool = False,
        resume: Callable[[], object] | None = None,
        fallback: Callable[[], object] | None = None,
    ):
        self._active_stage = stage
        self._check_cancelled()
        state = checkpoint["stages"][stage]
        if state.get("status") in {"complete", "complete_with_warnings"} and (
            ready() or state.get("status") == "complete_with_warnings"
        ):
            self._emit(stage, f"Resumed completed {stage.replace('_', ' ')} stage.")
            loader = resume or fallback
            return loader() if loader is not None else None
        state.update(
            {
                "status": "running",
                "attempts": int(state.get("attempts") or 0) + 1,
                "started_at": utc_now(),
                "error": "",
            }
        )
        self._save_checkpoint(checkpoint)
        self._emit(stage, f"Starting {stage.replace('_', ' ')}.")
        started = perf_counter()
        try:
            result = operation()
        except Exception as error:
            if self.cancel_event.is_set():
                state.update(
                    {
                        "status": "pending",
                        "error": "",
                        "interrupted_at": utc_now(),
                        "duration_seconds": round(perf_counter() - started, 6),
                    }
                )
                self._save_checkpoint(checkpoint)
                raise Phase3InitializationCancelled(
                    "Code Learner initialization was stopped."
                ) from error
            state.update(
                {
                    "status": "failed",
                    "error": str(error),
                    "failed_at": utc_now(),
                    "duration_seconds": round(perf_counter() - started, 6),
                }
            )
            self._save_checkpoint(checkpoint)
            if warning_tolerant and fallback is not None:
                self._warning(stage, str(error))
                state["status"] = "complete_with_warnings"
                self._save_checkpoint(checkpoint)
                return fallback()
            self._emit(
                stage,
                f"Initialization error: {error}",
                activity_kind="error",
            )
            raise
        state.update(
            {
                "status": "complete",
                "completed_at": utc_now(),
                "duration_seconds": round(perf_counter() - started, 6),
                "error": "",
            }
        )
        if stage == "activation" and isinstance(result, Mapping):
            checkpoint["status"] = result.get("status", "complete")
            checkpoint["activated_at"] = utc_now()
        self._save_checkpoint(checkpoint)
        self._emit(stage, f"Completed {stage.replace('_', ' ')}.")
        if stage != "activation":
            self._check_cancelled()
        return result

    def _check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise Phase3InitializationCancelled(
                "Code Learner initialization was stopped."
            )

    def _complete_stage(
        self,
        checkpoint: dict[str, object],
        stage: str,
        *,
        message: str,
        duration_seconds: float = 0.0,
    ) -> None:
        self._active_stage = stage
        checkpoint["stages"][stage].update(
            {
                "status": "complete",
                "completed_at": utc_now(),
                "duration_seconds": round(duration_seconds, 6),
                "error": "",
            }
        )
        self._save_checkpoint(checkpoint)
        self._emit(stage, message)

    def _capture_ctags(self, source):
        capture = self.ctags.capture(source)
        for index, warning in enumerate(capture.metadata.get("warnings", [])):
            self._warning("ctags_evidence", str(warning), suffix=str(index))
        return capture

    def _discover_components(self, run_id: str, revision: str):
        runtime = self._observed_runtime("code_learner_analysis", self.root)
        source = self.source.load()
        previous_error = ""
        for attempt in range(1, 3):
            prompt = component_discovery_prompt(
                self.root,
                analysis_run_id=run_id,
                repository_revision=revision,
                source_manifest_path=self.source.manifest_path,
                files_path=self.source.files_path,
                ctags_path=self.ctags.raw_path,
                schema_path=Path(__file__).with_name("schemas") / "phase3.schema.json",
                example_file_id=(
                    str(source.files[0]["id"])
                    if source is not None and source.files
                    else "file:replace-with-real-file-id"
                ),
            )
            if previous_error:
                prompt += (
                    f"\n\nPrevious output was not valid JSONL:\n- {previous_error}"
                )
            result = runtime.invoke(
                AgentInvocation(
                    role="code_learner_analysis",
                    prompt=prompt,
                    context_paths=[
                        self.source.manifest_path.relative_to(self.root).as_posix(),
                        self.source.files_path.relative_to(self.root).as_posix(),
                        self.ctags.raw_path.relative_to(self.root).as_posix(),
                    ],
                )
            )
            self.store.write_json(
                self.store.attempts_root
                / "components"
                / f"discovery-{run_id}-{attempt}.json",
                {
                    "attempt": attempt,
                    "output": result.final_message,
                    "error": result.error or "",
                    "recorded_at": utc_now(),
                },
            )
            try:
                output = require_agent_output(result, operation="Component discovery")
                parse_agent_jsonl(
                    output,
                    artifact=f"component discovery {run_id}",
                    parser=parse_phase3_jsonl,
                )
            except RetryableAgentError as error:
                previous_error = str(error)
                continue
            break
        else:
            raise CodeLearnerError(
                f"Component discovery failed after 2 attempts: {previous_error}"
            )
        validation = self.candidates.ingest(
            output,
            attempt_id=f"discovery-{run_id}",
            replace_existing=True,
        )
        for rejected in validation.rejected:
            candidate_id = rejected.candidate.get("candidate_id", "unknown")
            self._warning(
                "components",
                "; ".join(rejected.errors),
                suffix=str(candidate_id),
            )
        if not self.candidates.load():
            raise CodeLearnerError("component discovery produced no usable candidates")
        return self.candidates.load()

    def _reconcile_all(self, run_id: str):
        failures = []
        for group_id in self.reconciliations.pending_group_ids():
            try:
                self.reconciliations.reconcile_group(group_id, analysis_run_id=run_id)
            except CodeLearnerError as error:
                failures.append(f"{group_id}: {error}")
                self._warning("reconciliations", str(error), suffix=group_id)
        if failures:
            raise CodeLearnerError("; ".join(failures))
        return self.reconciliations.load()

    def _build_architecture_course(self, run_id: str):
        architecture = self.courses.build(
            "architecture", "architecture:current", analysis_run_id=run_id
        )
        return {
            "architecture_course_path": architecture["jsonl_path"],
            "module_course_count": self._resume_course_summary()["module_course_count"],
        }

    def _verify_rendered_courses(self):
        architecture = self.courses.markdown_path(
            "architecture", "architecture:current"
        )
        if not architecture.is_file():
            raise CodeLearnerError("Architecture course Markdown is missing")
        return architecture

    def _resume_course_summary(self) -> dict[str, object]:
        index = self.courses.index().get("targets", {})
        module_count = sum(
            1
            for item in (index.values() if isinstance(index, Mapping) else [])
            if isinstance(item, Mapping)
            and item.get("mode") == "module"
            and item.get("status") == "ready"
        )
        return {
            "architecture_course_path": self.courses.course_path(
                "architecture", "architecture:current"
            )
            .relative_to(self.root)
            .as_posix(),
            "module_course_count": module_count,
        }

    def _activate(self, revision: str):
        if not self._required_courses_rendered():
            raise CodeLearnerError("no usable Architecture course can be activated")
        warnings = self.store.active_diagnostics("warning")
        status = "complete_with_warnings" if warnings else "complete"
        result = {
            "schema_version": 1,
            "repository_revision": revision,
            "status": status,
            "course_active": True,
            "warning_count": len(warnings),
            "diagnostic_ids": [str(item["id"]) for item in warnings],
            "failed_scope": None,
            "recovery_action": None,
            "completed_at": utc_now(),
        }
        self.store.save_terminal_result(result)
        self.generation.select("phase3", revision, replace=True)
        self._emit("activation", f"Initialization {status}.")
        return result

    def _checkpoint(self, revision: str, job_id: str) -> dict[str, object]:
        checkpoint = self.store.read_json(self.store.checkpoint_path)
        if checkpoint and checkpoint.get("repository_revision") == revision:
            checkpoint["job_id"] = job_id
            checkpoint["resumed_at"] = utc_now()
            return checkpoint
        checkpoint = {
            "schema_version": 1,
            "learner_generation": "phase3",
            "analysis_run_id": uuid4().hex,
            "job_id": job_id,
            "repository_revision": revision,
            "status": "running",
            "created_at": utc_now(),
            "stages": {stage: {"status": "pending", "attempts": 0} for stage in STAGES},
        }
        self._save_checkpoint(checkpoint)
        return checkpoint

    def _save_checkpoint(self, checkpoint: Mapping[str, object]) -> None:
        self.store.write_json(self.store.checkpoint_path, checkpoint)

    def _observed_runtime(self, role: str, root: Path) -> AgentRuntime:
        if self._analysis_workspace.workspace is None:
            source = self.source.load()
            if source is None:
                raise CodeLearnerError(
                    "source manifest is unavailable for isolated AI analysis"
                )
            self._emit(
                self._active_stage,
                "Preparing isolated AI repository snapshot.",
            )
            self._analysis_workspace.open(source.files)
        runtime = (
            self._analysis_workspace.runtime(role)
            if self._analysis_workspace.workspace is not None
            else self._base_runtime_factory(role, root)
        )
        return _ObservedRuntime(
            ReusableAgentRuntime(runtime, self.agent_sessions, slot="primary"),
            lambda event: self._emit_activity(event),
            stage=self._active_stage,
            percent=STAGE_PERCENT.get(self._active_stage, 1),
            cancel_event=self.cancel_event,
        )

    def _emit_activity(self, event: dict[str, object]) -> None:
        payload = {**event, "updated_at": utc_now()}
        self.store.append_progress(payload)
        if self._callback is not None:
            self._callback(payload)

    def _emit(
        self,
        stage: str,
        message: str,
        *,
        activity_kind: str = "stage",
    ) -> None:
        payload = {
            "record_type": "progress",
            "phase": stage,
            "stage": stage,
            "percent": min(99, STAGE_PERCENT.get(stage, 1)),
            "message": message,
            "activity_kind": activity_kind,
            "host_owned": True,
            "updated_at": utc_now(),
            "counts": self._counts(),
        }
        self.store.append_progress(payload)
        if self._callback is not None:
            self._callback(payload)

    def _counts(self) -> dict[str, int]:
        source = _attempt(self.source.load)
        ctags = _attempt(self.ctags.load)
        candidates = _attempt(self.candidates.load, [])
        groups = _attempt(self.overlaps.load, [])
        reconciliations = _attempt(self.reconciliations.load, [])
        components = _attempt(self.components.load)
        modules = _attempt(self.modules.load) if components is not None else None
        relationships = _attempt(
            lambda: self.store.read_jsonl(self.relationships.relationships_path), []
        )
        course_index = self.courses.index().get("targets", {})
        warning_count = len(self.store.active_diagnostics("warning"))
        return {
            "files": len(source.files) if source else 0,
            "raw_tags": int(ctags.metadata.get("raw_tag_count") or 0) if ctags else 0,
            "candidates": len(candidates),
            "overlap_groups": len(groups),
            "reconciliations": len(reconciliations),
            "dispositions": len(components.dispositions) if components else 0,
            "unresolved_files": (
                int(components.coverage.get("unresolved_count") or 0)
                if components
                else 0
            ),
            "components": len(components.components) if components else 0,
            "modules": len(modules.modules) if modules else 0,
            "relationships": len(relationships),
            "architecture_knowledge": int(self.architecture.load() is not None),
            "module_knowledge": len(self._loaded_module_knowledge()),
            "function_knowledge": len(list(self.functions.root_path.glob("*.jsonl"))),
            "courses": sum(
                1
                for item in (
                    course_index.values() if isinstance(course_index, Mapping) else []
                )
                if isinstance(item, Mapping) and item.get("status") == "ready"
            ),
            "warnings": warning_count,
        }

    def _warning(self, stage: str, message: str, *, suffix: str = "") -> None:
        identity = uuid4().hex[:12] if not suffix else _safe(suffix)
        self.store.save_diagnostic(
            {
                "schema_version": 1,
                "record_type": "diagnostic",
                "id": f"diagnostic:{stage}:{identity}",
                "severity": "warning",
                "code": f"{stage}-warning",
                "message": message,
                "active": True,
                "recorded_at": utc_now(),
            }
        )
        self._emit(
            stage,
            f"Warning: {message}",
            activity_kind="warning",
        )

    def _fail(self, revision: str, error: Exception) -> None:
        self.store.save_terminal_result(
            {
                "schema_version": 1,
                "repository_revision": revision,
                "status": "failed",
                "course_active": False,
                "warning_count": len(self.store.active_diagnostics("warning")),
                "diagnostic_ids": [
                    str(item["id"]) for item in self.store.active_diagnostics("warning")
                ],
                "failed_scope": self._active_stage,
                "recovery_action": (
                    "Resume initialization after correcting "
                    f"{self._active_stage}: {error}"
                ),
                "completed_at": utc_now(),
            }
        )
        self._emit(
            self._active_stage,
            f"Initialization failed: {error}",
            activity_kind="error",
        )

    def _all_module_knowledge_ready(self) -> bool:
        modules = self.modules.load()
        return bool(
            modules
            and all(
                self.module_knowledge.load(str(module["id"])) is not None
                for module in modules.modules
            )
        )

    def _loaded_module_knowledge(self):
        modules = self.modules.load()
        if modules is None:
            return []
        return [
            value
            for module in modules.modules
            if (value := self.module_knowledge.load(str(module["id"]))) is not None
        ]

    def _required_courses_ready(self) -> bool:
        return (
            self.courses.target_status("course:architecture:architecture:current")
            == "ready"
        )

    def _required_courses_rendered(self) -> bool:
        return (
            self._required_courses_ready()
            and self.courses.markdown_path(
                "architecture", "architecture:current"
            ).is_file()
        )


class _ObservedRuntime(AgentRuntime):
    def __init__(
        self,
        runtime: AgentRuntime,
        callback: ProgressCallback,
        *,
        stage: str,
        percent: int,
        cancel_event: Event | None = None,
        heartbeat_interval: float = 5.0,
    ) -> None:
        self.runtime = runtime
        self.callback = callback
        self.reporter = AgentActivityReporter(callback, phase=stage, percent=percent)
        self.stage = stage
        self.percent = percent
        self.cancel_event = cancel_event
        self.heartbeat_interval = heartbeat_interval

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise Phase3InitializationCancelled(
                "Code Learner initialization was stopped."
            )
        previous_callback = invocation.event_callback
        reported_live_event = False
        last_live_event_at = perf_counter()

        def report(event: dict[str, object]) -> None:
            nonlocal last_live_event_at, reported_live_event
            reported_live_event = True
            last_live_event_at = perf_counter()
            self.reporter(event)
            if previous_callback is not None:
                previous_callback(event)

        def heartbeat_event() -> dict[str, object]:
            quiet_seconds = max(1, int(perf_counter() - last_live_event_at))
            return {
                "record_type": "activity",
                "activity": True,
                "activity_kind": "status",
                "phase": self.stage,
                "percent": self.percent,
                "scope_ids": [],
                "message": (
                    f"AI is still working on {self.stage.replace('_', ' ')}; "
                    f"last detailed update {quiet_seconds} seconds ago."
                ),
            }

        invocation.event_callback = report
        invocation.cancel_event = self.cancel_event
        with InvocationHeartbeat(
            self.callback,
            heartbeat_event,
            interval=self.heartbeat_interval,
        ):
            result = self.runtime.invoke(invocation)
        if self.cancel_event is not None and self.cancel_event.is_set():
            raise Phase3InitializationCancelled(
                "Code Learner initialization was stopped."
            )
        if not reported_live_event:
            for event in result.raw_events:
                self.reporter({"event": event})
        if result.changed_files or result.created_files:
            return AgentResult(
                False,
                result.final_message,
                error=(
                    "analysis runtime attempted direct repository/state writes: "
                    + ", ".join([*result.changed_files, *result.created_files])
                ),
                raw_events=result.raw_events,
            )
        return result


def phase3_initialization_ready(root: Path | str) -> bool:
    store = Phase3Store(root)
    generation = LearnerGenerationStore(root).load()
    if generation is None or generation.generation != "phase3":
        return False
    result = store.load_terminal_result()
    if result is None or result.get("status") not in {
        "complete",
        "complete_with_warnings",
    }:
        return False
    source = SourceManifestService(root).load()
    return bool(
        source
        and generation.repository_revision == source.revision
        and result.get("repository_revision") == source.revision
        and Phase3CourseService(root, store=store).target_status(
            "course:architecture:architecture:current"
        )
        == "ready"
    )


def _safe(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value)


def _attempt(operation: Callable[[], object], default=None):
    try:
        return operation()
    except (CodeLearnerError, OSError, ValueError):
        return default


def _runtime_factory(role: str, root: Path) -> AgentRuntime:
    return runtime_for_role(role, root, execution_root=root)
