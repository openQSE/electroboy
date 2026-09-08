"""Durable reusable AI sessions for Code Learner generation work."""

from __future__ import annotations

import threading
from dataclasses import replace
from pathlib import Path

from electroboy.adapters.base import AgentInvocation, AgentResult, AgentRuntime
from electroboy.models import utc_now

from .store import LearnerStore


class AgentSessionRegistry:
    """Persist provider session identities by repository and worker slot."""

    def __init__(
        self, root: Path | str, *, store: LearnerStore | None = None
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = store or LearnerStore(self.root)
        self.path = self.store.sessions_path
        self._lock = threading.RLock()
        self._slot_locks: dict[str, threading.Lock] = {}

    def prepare(self, repository_identity: str = "") -> None:
        with self._lock:
            state = self._load()
            identity = repository_identity or str(self.root)
            if state.get("repository_identity") == identity:
                return
            self._save(
                {
                    "schema_version": 1,
                    "repository_identity": identity,
                    "sessions": {},
                    "updated_at": utc_now(),
                }
            )

    def session_id(self, slot: str) -> str:
        with self._lock:
            sessions = self._load().get("sessions", {})
            value = sessions.get(slot, {}) if isinstance(sessions, dict) else {}
            return str(value.get("provider_session_id") or "")

    def record(self, slot: str, result: AgentResult, *, forked_from: str = "") -> None:
        provider_session_id = str(result.provider_session_id or "").strip()
        if not provider_session_id:
            return
        with self._lock:
            state = self._load()
            sessions = state.setdefault("sessions", {})
            sessions[slot] = {
                "provider": result.provider or "",
                "provider_session_id": provider_session_id,
                "forked_from": forked_from,
                "updated_at": utc_now(),
            }
            state["updated_at"] = utc_now()
            self._save(state)

    def slot_lock(self, slot: str) -> threading.Lock:
        with self._lock:
            return self._slot_locks.setdefault(slot, threading.Lock())

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return self._load()

    def _load(self) -> dict[str, object]:
        return self.store.read_object(self.path) or {
            "schema_version": 1,
            "repository_identity": "",
            "sessions": {},
        }

    def _save(self, state: dict[str, object]) -> None:
        self.store.write_state(self.path, state)


class ReusableAgentRuntime(AgentRuntime):
    """Decorate one runtime with durable resume-or-fork session semantics."""

    def __init__(
        self,
        runtime: AgentRuntime,
        registry: AgentSessionRegistry,
        *,
        slot: str,
        fork_from_slot: str = "",
    ) -> None:
        self.runtime = runtime
        self.registry = registry
        self.slot = slot
        self.fork_from_slot = fork_from_slot

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        with self.registry.slot_lock(self.slot):
            provider_session_id = self.registry.session_id(self.slot)
            fork_session_id = ""
            if not provider_session_id and self.fork_from_slot:
                fork_session_id = self.registry.session_id(self.fork_from_slot)
            effective_session_id = invocation.provider_session_id or provider_session_id
            prepared = replace(
                invocation,
                provider_session_id=effective_session_id or None,
                fork_provider_session_id=(
                    invocation.fork_provider_session_id
                    or (fork_session_id or None if not effective_session_id else None)
                ),
            )
            result = self.runtime.invoke(prepared)
            self.registry.record(
                self.slot,
                result,
                forked_from=fork_session_id,
            )
            return result
