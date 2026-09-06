"""Foreground trusted-output course generation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from uuid import uuid4

from electroboy.adapters.base import AgentInvocation, AgentResult, AgentRuntime
from electroboy.runtime import runtime_for_role

from .agent_sessions import AgentSessionRegistry, ReusableAgentRuntime
from .domain import CodeLearnerError
from .progress import AgentActivityReporter
from .prompts import (
    architecture_course_prompt,
    component_discovery_prompt,
    function_course_prompt,
    module_course_prompt,
    module_discovery_prompt,
)
from .store import LearnerStore

ProgressCallback = Callable[[dict[str, object]], None]
RuntimeFactory = Callable[[str, Path], AgentRuntime]


class CourseGenerationCancelled(CodeLearnerError):
    """Raised when the operator aborts an active generation turn."""


@dataclass(frozen=True)
class InitializationResult:
    """Usable foreground output produced by initialization."""

    status: str
    component_count: int
    module_count: int
    architecture_path: str


class CourseGenerationService:
    """Run component, module, and Architecture turns in one AI session."""

    def __init__(
        self,
        root: Path | str,
        *,
        runtime_factory: RuntimeFactory | None = None,
        cancel_event: Event | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = LearnerStore(self.root)
        self.sessions = AgentSessionRegistry(self.root, store=self.store)
        self.runtime_factory = runtime_factory or _runtime_factory
        self.cancel_event = cancel_event or Event()
        self._callback: ProgressCallback | None = None

    def run(
        self, progress_callback: ProgressCallback | None = None
    ) -> InitializationResult:
        self._callback = progress_callback
        self.store.initialize_layout()
        self.sessions.prepare(str(self.root))
        self._emit("setup", 2, "Prepared repository course and knowledge directories.")
        runtime = ReusableAgentRuntime(
            self.runtime_factory("code_learner_analysis", self.root),
            self.sessions,
            slot="primary",
        )
        try:
            if not self.store.components_path.is_file():
                self._invoke(
                    runtime,
                    "components",
                    10,
                    component_discovery_prompt(
                        self.root,
                        self.store.course_root,
                        self.store.raw_knowledge_root,
                        self.store.components_path,
                        str(uuid4()),
                    ),
                )
                self._require_file(self.store.components_path, "component array")
            self._emit("components", 30, "Component discovery output is available.")
            if not self.store.modules_path.is_file():
                self._invoke(
                    runtime,
                    "modules",
                    38,
                    module_discovery_prompt(
                        self.store.components_path,
                        self.store.modules_path,
                        self.store.raw_knowledge_root,
                        str(uuid4()),
                    ),
                )
                self._require_file(self.store.modules_path, "module array")
            self._emit("modules", 55, "Module discovery output is available.")
            if not self.store.course_ready("architecture"):
                self._invoke(
                    runtime,
                    "architecture",
                    65,
                    architecture_course_prompt(
                        self.store.components_path,
                        self.store.modules_path,
                        self.store.raw_knowledge_root,
                        self.store.architecture_root,
                        str(uuid4()),
                    ),
                    role="code_learner_course",
                )
            if not self.store.course_ready("architecture"):
                raise CodeLearnerError(
                    "AI did not produce a usable Architecture course"
                )
            self._emit("architecture", 99, "Architecture course is ready.")
            result = InitializationResult(
                status="complete",
                component_count=len(self.store.components()),
                module_count=len(self.store.modules()),
                architecture_path=self.store.relative(
                    self.store.course_index_path("architecture")
                ),
            )
            self.store.save_status(
                status="initialized",
                phase="complete",
                percent=100,
                completion_status="complete",
                message="Architecture course is ready.",
                error="",
            )
            return result
        finally:
            self._callback = None

    def _invoke(
        self,
        runtime: AgentRuntime,
        phase: str,
        percent: int,
        prompt: str,
        *,
        role: str = "code_learner_analysis",
    ) -> AgentResult:
        self._check_cancelled()
        self._emit(phase, percent, f"Starting AI {phase} turn.")
        reporter = AgentActivityReporter(
            self._record_activity,
            phase=phase,
            percent=percent,
        )
        result = runtime.invoke(
            AgentInvocation(
                role=role,
                prompt=prompt,
                progress_path=str(self.store.progress_path),
                event_callback=reporter,
                cancel_event=self.cancel_event,
            )
        )
        self._check_cancelled()
        if not result.ok:
            raise CodeLearnerError(result.error or result.final_message or "AI failed")
        return result

    def _record_activity(self, event: dict[str, object]) -> None:
        self.store.append_progress(event)
        if self._callback is not None:
            self._callback(event)

    def _emit(self, phase: str, percent: int, message: str) -> None:
        event = {
            "activity_kind": "stage",
            "phase": phase,
            "percent": percent,
            "message": message,
        }
        self.store.save_status(
            status="running",
            phase=phase,
            percent=percent,
            message=message,
        )
        self.store.append_progress(event)
        if self._callback is not None:
            self._callback(event)

    def _require_file(self, path: Path, label: str) -> None:
        if not path.is_file():
            raise CodeLearnerError(f"AI did not write the requested {label}: {path}")

    def _check_cancelled(self) -> None:
        if self.cancel_event.is_set():
            raise CourseGenerationCancelled("Code Learner initialization aborted")


def _runtime_factory(role: str, root: Path) -> AgentRuntime:
    return runtime_for_role(role, root)


class CourseWorkerService:
    """Generate one Module or Function course in an independent AI session."""

    def __init__(
        self,
        root: Path | str,
        *,
        runtime_factory: RuntimeFactory | None = None,
        cancel_event: Event | None = None,
        progress_callback: ProgressCallback | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = LearnerStore(self.root)
        self.runtime_factory = runtime_factory or _runtime_factory
        self.cancel_event = cancel_event or Event()
        self.progress_callback = progress_callback

    def generate_module(self, module_id: str) -> Path:
        output = self.store.course_directory("module", module_id)
        prompt = module_course_prompt(
            module_id,
            self.store.components_path,
            self.store.modules_path,
            self.store.raw_knowledge_root,
            output,
            str(uuid4()),
        )
        self._invoke("module_course", prompt, [module_id])
        if not self.store.course_ready("module", module_id):
            raise CodeLearnerError(f"AI did not produce Module course {module_id}")
        return self.store.course_index_path("module", module_id)

    def generate_function(self, symbol: str, scope_id: str) -> Path:
        output = self.store.course_directory("function", scope_id)
        prompt = function_course_prompt(
            symbol,
            self.store.components_path,
            self.store.modules_path,
            self.store.raw_knowledge_root,
            output,
            str(uuid4()),
        )
        self._invoke("function_course", prompt, [symbol])
        if not self.store.course_ready("function", scope_id):
            raise CodeLearnerError(f"AI did not produce Function course for {symbol}")
        return self.store.course_index_path("function", scope_id)

    def _invoke(self, phase: str, prompt: str, scope_ids: list[str]) -> None:
        reporter = AgentActivityReporter(
            self._record_activity,
            phase=phase,
            percent=100,
            scope_ids=scope_ids,
        )
        runtime = self.runtime_factory("code_learner_course", self.root)
        result = runtime.invoke(
            AgentInvocation(
                role="code_learner_course",
                prompt=prompt,
                progress_path=str(self.store.progress_path),
                event_callback=reporter,
                cancel_event=self.cancel_event,
            )
        )
        if self.cancel_event.is_set():
            raise CourseGenerationCancelled("Course generation aborted")
        if not result.ok:
            raise CodeLearnerError(result.error or result.final_message or "AI failed")

    def _record_activity(self, event: dict[str, object]) -> None:
        self.store.append_progress(event)
        if self.progress_callback is not None:
            self.progress_callback(event)
