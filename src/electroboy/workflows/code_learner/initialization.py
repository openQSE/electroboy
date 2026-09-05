"""Staged Code Learner initialization, recovery, and process guard."""

from __future__ import annotations

import fcntl
import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from electroboy.models import utc_now

from .course_artifacts import render_saved_course
from .course_builder import CourseBuilder, CourseBuildResult
from .domain import CodeLearnerError, repository_revision
from .knowledge_store import KnowledgeStore
from .knowledge_validation import EnrichmentController, KnowledgeValidationReport
from .migration import LegacyCorpusMigrator, LegacyMigrationResult
from .orchestrator import AnalysisOrchestrator
from .revision import RevisionInvalidator

ProgressCallback = Callable[[dict[str, object]], None]

PIPELINE_PROGRESS = {
    "setup": 2,
    "inventory": 8,
    "modules": 24,
    "relationships": 42,
    "flows": 58,
    "symbols": 74,
    "validation": 84,
    "knowledge_validated": 86,
    "knowledge_needs_enrichment": 86,
    "knowledge_enrichment": 88,
    "architecture_course": 92,
    "architecture_ready": 93,
    "module_course": 94,
    "module_ready": 98,
    "rendering": 99,
    "activation": 99,
}


class AnalysisRunner(Protocol):
    def run(
        self, progress_callback: ProgressCallback | None = None
    ) -> list[dict[str, object]]: ...


class EnrichmentRunner(Protocol):
    def run(
        self, progress_callback: ProgressCallback | None = None
    ) -> KnowledgeValidationReport: ...


class CourseRunner(Protocol):
    selector: object

    def build_architecture(
        self, *, progress_callback: ProgressCallback | None = None
    ) -> CourseBuildResult: ...


class MigrationRunner(Protocol):
    def migrate(self) -> LegacyMigrationResult: ...

    def build_module(
        self,
        module_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
    ) -> CourseBuildResult: ...


@dataclass(frozen=True)
class InitializationResult:
    """Durable outputs required before host activation."""

    revision: str
    architecture: CourseBuildResult
    modules: tuple[CourseBuildResult, ...]


class InitializationLease:
    """Hold a non-blocking repository lock for one initialization process."""

    def __init__(self, path: Path, stream: object) -> None:
        self.path = path
        self._stream = stream

    @classmethod
    def acquire(cls, root: Path | str, job_id: str) -> InitializationLease:
        store = KnowledgeStore(root)
        path = store.state_root / "initialize.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        stream = path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            stream.seek(0)
            owner = stream.read().strip() or "another process"
            stream.close()
            raise CodeLearnerError(
                f"Code Learner initialization is already running: {owner}"
            ) from error
        stream.seek(0)
        stream.truncate()
        stream.write(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "job_id": job_id,
                    "started_at": utc_now(),
                },
                sort_keys=True,
            )
            + "\n"
        )
        stream.flush()
        return cls(path, stream)

    def release(self) -> None:
        if self._stream is None:
            return
        fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        self._stream.close()
        self._stream = None


class InitializationPipeline:
    """Coordinate independent knowledge, enrichment, and course components."""

    def __init__(
        self,
        root: Path | str,
        *,
        analysis_factory: Callable[[Path], AnalysisRunner] = AnalysisOrchestrator,
        enrichment_factory: Callable[[Path], EnrichmentRunner] = EnrichmentController,
        course_factory: Callable[[Path], CourseRunner] = CourseBuilder,
        migration_factory: Callable[[Path], MigrationRunner] = LegacyCorpusMigrator,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = KnowledgeStore(self.root)
        self.analysis_factory = analysis_factory
        self.enrichment_factory = enrichment_factory
        self.course_factory = course_factory
        self.migration_factory = migration_factory

    def run(
        self,
        progress_callback: ProgressCallback | None = None,
    ) -> InitializationResult:
        revision = repository_revision(self.root)
        self._emit(
            "setup",
            "Preparing staged repository analysis.",
            progress_callback,
        )
        migration = self.migration_factory(self.root).migrate()
        if migration.status == "imported":
            self._emit(
                "migration",
                migration.message,
                progress_callback,
                percent=3,
            )
        invalidation = RevisionInvalidator(self.root).run()
        if invalidation.changed:
            self._emit(
                "setup",
                (
                    f"Repository revision changed in "
                    f"{len(invalidation.changed_paths)} source paths; "
                    f"{len(invalidation.stale_courses)} course scopes are stale."
                ),
                progress_callback,
                scope_ids=list(invalidation.affected_record_ids),
            )
        self.analysis_factory(self.root).run(
            lambda event: self._forward(event, progress_callback)
        )
        report = self.enrichment_factory(self.root).run(
            lambda event: self._forward(event, progress_callback)
        )
        if not report.complete:
            blocked = [
                str(record.get("id"))
                for record in self.store.load_knowledge(validate_sources=False)
                if record.get("record_type") == "knowledge_request"
                and record.get("status") in {"open", "blocked"}
            ]
            raise CodeLearnerError(
                "knowledge enrichment did not resolve blocking gaps: "
                + ", ".join(blocked)
            )

        builder = self.course_factory(self.root)
        architecture = self._architecture(builder, revision, progress_callback)
        module_ids = tuple(builder.selector.module_ids())
        modules: list[CourseBuildResult] = []
        failures: dict[str, str] = {}
        for index, module_id in enumerate(module_ids, start=1):
            if cached := self._ready_course("module", module_id, revision):
                modules.append(cached)
                self._record_course_checkpoint("module", module_id, "completed")
                self._module_progress(
                    index,
                    len(module_ids),
                    module_id,
                    "Resumed validated Module course.",
                    progress_callback,
                )
                continue
            try:
                result = builder.build_module(
                    module_id,
                    progress_callback=lambda event, current=index: (
                        self._forward_module(
                            event,
                            current,
                            len(module_ids),
                            progress_callback,
                        )
                    ),
                )
            except CodeLearnerError as error:
                failures[module_id] = str(error)
                self._record_course_checkpoint(
                    "module", module_id, "failed", error=str(error)
                )
                continue
            modules.append(result)
            self._record_course_checkpoint("module", module_id, "completed")
        if failures:
            details = "; ".join(
                f"{module_id}: {message}"
                for module_id, message in sorted(failures.items())
            )
            raise CodeLearnerError(f"Module course generation failed: {details}")

        self._emit(
            "rendering",
            "All generated course artifacts are validated and rendered.",
            progress_callback,
        )
        self._update_pipeline_checkpoint("ready_for_activation", revision)
        return InitializationResult(revision, architecture, tuple(modules))

    def _architecture(
        self,
        builder: CourseRunner,
        revision: str,
        callback: ProgressCallback | None,
    ) -> CourseBuildResult:
        cached = self._ready_course("architecture", "repository.root", revision)
        if cached is not None:
            self._record_course_checkpoint(
                "architecture", "repository.root", "completed"
            )
            self._emit(
                "architecture_ready",
                "Resumed validated Architecture course.",
                callback,
                scope_ids=["repository.root"],
            )
            return cached
        result = builder.build_architecture(
            progress_callback=lambda event: self._forward(event, callback)
        )
        self._record_course_checkpoint(
            "architecture", "repository.root", "completed"
        )
        return result

    def _ready_course(
        self, mode: str, scope_id: str, revision: str
    ) -> CourseBuildResult | None:
        index = self.store.load_course_index().get("courses", {})
        item = index.get(f"{mode}:{scope_id}", {}) if isinstance(index, dict) else {}
        if not isinstance(item, dict) or item.get("status") != "ready":
            return None
        records = self.store.load_course(mode, scope_id)
        if not records or records[0].get("repository_revision") != revision:
            return None
        markdown = self.store.course_markdown_path(mode, scope_id)
        if not markdown.is_file():
            render_saved_course(self.root, mode, scope_id)
        return CourseBuildResult(
            mode,
            scope_id,
            self.store.course_path(mode, scope_id).relative_to(self.root).as_posix(),
            markdown.relative_to(self.root).as_posix(),
            len(records),
        )

    def _forward(
        self,
        event: Mapping[str, object],
        callback: ProgressCallback | None,
    ) -> None:
        if event.get("activity") is True:
            if callback is not None:
                callback(dict(event))
            return
        phase = str(event.get("phase") or "setup")
        self._emit(
            phase,
            str(event.get("message") or phase),
            callback,
            percent=PIPELINE_PROGRESS.get(phase, int(event.get("percent") or 0)),
            scope_ids=list(event.get("scope_ids", [])),
            heartbeat=bool(event.get("heartbeat")),
        )

    def _forward_module(
        self,
        event: Mapping[str, object],
        index: int,
        total: int,
        callback: ProgressCallback | None,
    ) -> None:
        if event.get("activity") is True:
            if callback is not None:
                callback(dict(event))
            return
        self._module_progress(
            index,
            total,
            str(next(iter(event.get("scope_ids", [])), "module")),
            str(event.get("message") or "Generating Module course."),
            callback,
            heartbeat=bool(event.get("heartbeat")),
        )

    def _module_progress(
        self,
        index: int,
        total: int,
        module_id: str,
        message: str,
        callback: ProgressCallback | None,
        *,
        heartbeat: bool = False,
    ) -> None:
        fraction = index / max(1, total)
        percent = min(98, 93 + max(1, round(5 * fraction)))
        self._emit(
            "module_course",
            message,
            callback,
            percent=percent,
            scope_ids=[module_id],
            heartbeat=heartbeat,
        )

    def _emit(
        self,
        phase: str,
        message: str,
        callback: ProgressCallback | None,
        *,
        percent: int | None = None,
        scope_ids: list[str] | None = None,
        heartbeat: bool = False,
    ) -> None:
        event = {
            "record_type": "progress",
            "phase": phase,
            "percent": min(99, percent or PIPELINE_PROGRESS.get(phase, 0)),
            "message": message,
            "scope_ids": scope_ids or [],
            "heartbeat": heartbeat,
            "host_owned": True,
            "updated_at": utc_now(),
            **self._telemetry(),
        }
        self.store.append_progress(event)
        if callback is not None:
            callback(event)

    def _telemetry(self) -> dict[str, object]:
        records = self.store.load_knowledge(validate_sources=False)
        counts: dict[str, int] = {}
        for record in records:
            kind = str(record.get("record_type") or "unknown")
            counts[kind] = counts.get(kind, 0) + 1
        checkpoint = self.store.load_checkpoint() or {}
        completed_scopes, remaining_scopes = _checkpoint_job_scopes(checkpoint)
        course_index = self.store.load_course_index().get("courses", {})
        module_states = {
            str(item.get("scope_id")): str(item.get("status") or "missing")
            for item in (
                course_index.values() if isinstance(course_index, dict) else []
            )
            if isinstance(item, dict) and item.get("mode") == "module"
        }
        manifest = next(
            (
                record
                for record in records
                if record.get("record_type") == "knowledge_manifest"
            ),
            {},
        )
        attributes = manifest.get("attributes")
        catalog = (
            attributes.get("module_catalog")
            if isinstance(attributes, dict)
            else None
        )
        expected_modules = {
            str(item)
            for item in (
                catalog.get("major_module_ids", [])
                if isinstance(catalog, dict)
                else []
            )
        }
        completed_modules = {
            key for key, value in module_states.items() if value == "ready"
        }
        return {
            "record_counts": counts,
            "completed_analysis_jobs": len(completed_scopes),
            "remaining_analysis_jobs": len(remaining_scopes),
            "completed_analysis_scopes": completed_scopes,
            "remaining_analysis_scopes": remaining_scopes,
            "completed_module_courses": sorted(completed_modules),
            "remaining_module_courses": sorted(
                (expected_modules | set(module_states)) - completed_modules
            ),
        }

    def _record_course_checkpoint(
        self,
        mode: str,
        scope_id: str,
        status: str,
        *,
        error: str = "",
    ) -> None:
        checkpoint = self.store.load_checkpoint() or {
            "schema_version": 1,
            "repository_revision": repository_revision(self.root),
        }
        courses = checkpoint.setdefault("courses", {})
        if not isinstance(courses, dict):
            raise CodeLearnerError("course checkpoint must be an object")
        courses[f"{mode}:{scope_id}"] = {
            "status": status,
            "error": error,
            "updated_at": utc_now(),
        }
        self.store.save_checkpoint(checkpoint)

    def _update_pipeline_checkpoint(self, status: str, revision: str) -> None:
        checkpoint = self.store.load_checkpoint() or {"schema_version": 1}
        checkpoint.update(
            {
                "repository_revision": revision,
                "pipeline_status": status,
                "pipeline_updated_at": utc_now(),
            }
        )
        self.store.save_checkpoint(checkpoint)


def initialization_ready(root: Path | str) -> bool:
    """Return true only after durable knowledge and every eager course are ready."""

    store = KnowledgeStore(root)
    checkpoint = store.load_checkpoint()
    if not checkpoint or checkpoint.get("pipeline_status") != "activated":
        return False
    current_revision = repository_revision(store.root)
    if checkpoint.get("repository_revision") != current_revision:
        return False
    index = store.load_course_index().get("courses", {})
    if not isinstance(index, dict):
        return False
    if not _stored_course_ready(
        store, index, "architecture", "repository.root", current_revision
    ):
        return False
    try:
        module_ids = CourseBuilder(store.root).selector.module_ids()
    except CodeLearnerError:
        return False
    return all(
        _stored_course_ready(store, index, "module", module_id, current_revision)
        for module_id in module_ids
    )


def mark_pipeline_activated(root: Path | str) -> None:
    store = KnowledgeStore(root)
    checkpoint = store.load_checkpoint()
    if not checkpoint:
        raise CodeLearnerError("initialization checkpoint is missing")
    checkpoint["pipeline_status"] = "activated"
    checkpoint["activated_at"] = utc_now()
    store.save_checkpoint(checkpoint)


def _checkpoint_job_scopes(
    checkpoint: Mapping[str, object],
) -> tuple[list[str], list[str]]:
    completed: list[str] = []
    remaining: list[str] = []
    passes = checkpoint.get("passes", {})
    if not isinstance(passes, Mapping):
        return completed, remaining
    for pass_name, state in passes.items():
        if not isinstance(state, Mapping):
            continue
        jobs = state.get("jobs")
        if isinstance(jobs, Mapping) and jobs:
            values = jobs.items()
        else:
            values = (("all", state),)
        for scope_name, job in values:
            scope = f"{pass_name}:{scope_name}"
            if isinstance(job, Mapping) and job.get("status") == "completed":
                completed.append(scope)
            else:
                remaining.append(scope)
    return sorted(completed), sorted(remaining)


def _stored_course_ready(
    store: KnowledgeStore,
    index: Mapping[str, object],
    mode: str,
    scope_id: str,
    revision: str,
) -> bool:
    item = index.get(f"{mode}:{scope_id}")
    if not isinstance(item, Mapping) or item.get("status") != "ready":
        return False
    try:
        records = store.load_course(mode, scope_id)
    except (CodeLearnerError, ValueError):
        return False
    return bool(
        records
        and records[0].get("repository_revision") == revision
        and store.course_markdown_path(mode, scope_id).is_file()
    )
