"""Service-wide agent provider selection and launch/cancellation boundary."""

from __future__ import annotations

import shutil
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from pathlib import Path
from dataclasses import replace

from electroboy.adapters.base import AgentInvocation, AgentResult, AgentRuntime
from electroboy.runtime import backend_config, runtime_for_role

from .sessions import AgentSession, AgentSessionError


class AgentBackend:
    """Coordinate terminal sessions and background invocations for one service."""

    def __init__(
        self,
        lock,
        sessions: Callable[[], Iterable[AgentSession]],
        roots: Callable[[], Iterable[Path]],
    ) -> None:
        self.lock = lock
        self.sessions = sessions
        self.roots = roots
        self.selected = "codex"
        self.revision = 0
        self.switching = False
        self.invocations: dict[object, tuple[threading.Event, threading.Event]] = {}
        self.cancel_epoch = threading.Event()

    def payload(self) -> dict[str, object]:
        with self.lock:
            active = [
                {
                    "session_id": s.session_id,
                    "label": s.label,
                    "workspace_id": s.context_id,
                }
                for s in self.sessions()
                if s.is_active()
            ]
            return {
                "backend": self.selected,
                "backends": ["codex", "opencode"],
                "revision": self.revision,
                "switching": self.switching,
                "active_agents": active,
                "background_agents": len(self.invocations),
            }

    def require_ready(self, revision: int | None = None) -> None:
        if self.switching or (revision is not None and revision != self.revision):
            raise AgentSessionError("Agent backend changed; retry the operation.")

    @contextmanager
    def launch(self, revision: int) -> Iterator[None]:
        with self.lock:
            self.require_ready(revision)
            yield

    def prepare(self, session: AgentSession) -> None:
        with self.lock:
            self.require_ready()
            provider = session.metadata.get("provider")
            if provider and provider != self.selected:
                raise AgentSessionError("Agent backend changed; retry the operation.")
            session.metadata["provider"] = self.selected
            session.environment["ELECTROBOY_AGENT_BACKEND"] = self.selected
            revision = self.revision
            session.start_guard = lambda: self.launch(revision)

    def runtime_factory(self):
        """Capture selection once per job, so queued work cannot cross a switch."""
        with self.lock:
            self.require_ready()
            backend, revision = self.selected, self.revision
            cancel_epoch = self.cancel_epoch

        def factory(role: str, root: Path) -> AgentRuntime:
            with self.lock:
                self.require_ready(revision)
            runtime = runtime_for_role(role, root, backend=backend)
            return ManagedRuntime(self, revision, runtime)

        factory.cancel_event = cancel_epoch
        return factory

    def switch(
        self, backend: str, *, confirmed: bool = False, revision: int | None = None
    ) -> dict[str, object]:
        if backend not in {"codex", "opencode"}:
            raise ValueError("Backend must be codex or opencode.")
        with self.lock:
            self.require_ready(revision)
            if backend == self.selected:
                return self.payload()
            if confirmed is not True:
                raise AgentSessionError(
                    "Confirm stopping all agents before switching backend."
                )
            for root in self.roots():
                for interactive in (False, True):
                    command = backend_config(
                        backend, root, interactive=interactive
                    ).command
                    if shutil.which(command) is None:
                        raise AgentSessionError(
                            f"Backend executable is unavailable: {command}"
                        )
            self.switching = True
            # Invalidate queued launches even if termination later fails.
            self.revision += 1
            self.cancel_epoch.set()
            self.cancel_epoch = threading.Event()
            sessions = list(self.sessions())
            invocations = list(self.invocations.values())
            for cancel, _done in invocations:
                cancel.set()
        try:
            failures = []
            for session in sessions:
                try:
                    if session.is_active():
                        session.terminate()
                    if session.is_active():
                        failures.append(session.label)
                except Exception as error:
                    failures.append(f"{session.label}: {error}")
            deadline = time.monotonic() + 10
            for _cancel, done in invocations:
                if not done.wait(max(0, deadline - time.monotonic())):
                    failures.append("background agent did not stop")
            if failures:
                raise AgentSessionError(
                    "Backend unchanged. Could not stop: " + "; ".join(failures)
                )
            with self.lock:
                self.selected = backend
        finally:
            with self.lock:
                self.switching = False
        return self.payload()


class CombinedCancellation:
    def __init__(self, *events):
        self.events = [event for event in events if event is not None]

    def is_set(self) -> bool:
        return any(event.is_set() for event in self.events)

    def wait(self, timeout: float | None = None) -> bool:
        deadline = None if timeout is None else time.monotonic() + timeout
        while not self.is_set():
            if deadline is not None and time.monotonic() >= deadline:
                return False
            time.sleep(0.01)
        return True


class ManagedRuntime(AgentRuntime):
    def __init__(self, selection: AgentBackend, revision: int, runtime: AgentRuntime):
        self.selection, self.revision, self.runtime = selection, revision, runtime
        self.config = runtime.config

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        cancel, done = threading.Event(), threading.Event()
        key = object()
        with self.selection.lock:
            self.selection.require_ready(self.revision)
            self.selection.invocations[key] = (cancel, done)
        try:
            result = self.runtime.invoke(
                replace(
                    invocation,
                    cancel_event=CombinedCancellation(cancel, invocation.cancel_event),
                )
            )
            if cancel.is_set():
                raise AgentSessionError("Agent stopped because the backend changed.")
            return result
        finally:
            with self.selection.lock:
                self.selection.invocations.pop(key, None)
                done.set()
