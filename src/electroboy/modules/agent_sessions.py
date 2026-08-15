"""Agent session capability module declaration."""

from __future__ import annotations

from electroboy.service.registry import ServiceModule

from .common import route


def module() -> ServiceModule:
    return ServiceModule(
        id="agent_sessions",
        label="Agent Sessions",
        routes=(
            route("GET", "/api/sessions", "agent_sessions", "list_sessions"),
            route("GET", "/api/session-registry", "agent_sessions", "session_registry"),
            route("POST", "/api/sessions/attach", "agent_sessions", "attach"),
            route("POST", "/api/sessions/message", "agent_sessions", "message"),
            route("POST", "/api/sessions/key", "agent_sessions", "key"),
            route("POST", "/api/sessions/raw", "agent_sessions", "raw"),
            route("POST", "/api/sessions/interrupt", "agent_sessions", "interrupt"),
            route("POST", "/api/sessions/resize", "agent_sessions", "resize"),
            route("GET", "/api/sessions/events", "agent_sessions", "events"),
            route("GET", "/api/sessions/export", "agent_sessions", "export"),
        ),
        capabilities=frozenset({"terminal", "sse", "transcript-export"}),
        state_namespace="sessions",
    )

