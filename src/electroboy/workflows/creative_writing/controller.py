"""Creative-writing browser workflow controller."""

from __future__ import annotations

from pathlib import Path

from electroboy.adapters.codex_sessions import CodexSessionSummary, codex_session_paths
from electroboy.modules.creative_workspace import (
    _create_creative_document,
    _create_creative_folder,
    _creative_agent_target,
    _creative_tree_payload,
    _creative_writing_command,
    _delete_creative_entry,
    _document_target_path,
    _ensure_creative_scratchpad,
    _ensure_creative_workspace,
    _existing_creative_project_root,
    _rename_creative_entry,
    _set_creative_folder_color,
)
from electroboy.service.recent_projects import (
    remember_recent_project as _remember_recent_project,
)
from electroboy.service.sessions import AgentSession, AgentSessionError
from electroboy.service.services import ServiceServices
from electroboy.service.workflow_controller import BoundWorkflowController
from electroboy.state_store import StateError

from .corkboard_provider import CreativeWritingCorkboardProvider
from .sessions import (
    CREATIVE_DOCUMENT_SCOPE,
    CREATIVE_GENERAL_SCOPE,
    CREATIVE_GENERAL_SCOPE_KEY,
    creative_document_scope_key,
    creative_session_history,
    remember_creative_session,
    resumable_creative_session,
    start_creative_session_tracking,
)


def _resolve_project_path(path: str) -> Path:
    return Path(path).expanduser().resolve()


class CreativeWritingWorkflowController(BoundWorkflowController):
    """Own creative project, binder, corkboard, and agent behavior."""

    workflow_id = "creative-writing"

    def __init__(self, services: ServiceServices) -> None:
        super().__init__(services)
        self.corkboard_provider = CreativeWritingCorkboardProvider(self.services)

    def get_corkboard_provider(self) -> CreativeWritingCorkboardProvider:
        return self.corkboard_provider

    def _reserve_project_workspace(
        self,
        context_id: str,
        project_root: Path,
    ) -> tuple[str, bool]:
        with self.services.contexts.lock:
            current = self.services.contexts.require(context_id)
            self.services.contexts.require_no_active_agent(current)
        workspace, resumed = self.services.workspaces.reserve_project(
            context_id,
            workflow_id=self.workflow_id,
            project_kind="creative-writing",
            project_identity=str(project_root),
            name=project_root.name,
        )
        return workspace.context_id, resumed

    def open_creative_project(self, context_id: str, path: str) -> dict[str, object]:
        project_root = _existing_creative_project_root(path)
        context_id, resumed = self._reserve_project_workspace(
            context_id,
            project_root,
        )
        if resumed:
            return {
                **self.services.contexts.project_payload(context_id),
                "status": "resumed",
            }
        _ensure_creative_workspace(project_root)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            context.reset_project(
                workflow_id=self.workflow_id,
                project_mode="creative",
                activation_root=project_root,
                active_project_root=project_root,
                workflow_stage="project",
            )
            self.services.workspaces.persist(context_id)
        _remember_recent_project(
            self.services.files.state_root,
            project_root,
            "creative",
        )
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "opened",
        }

    def create_creative_project(self, context_id: str, path: str) -> dict[str, object]:
        project_root = _resolve_project_path(path)
        context_id, resumed = self._reserve_project_workspace(
            context_id,
            project_root,
        )
        if resumed:
            return {
                **self.services.contexts.project_payload(context_id),
                "status": "resumed",
            }
        project_root.mkdir(parents=True, exist_ok=True)
        _ensure_creative_workspace(project_root)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            context.reset_project(
                workflow_id=self.workflow_id,
                project_mode="creative",
                activation_root=project_root,
                active_project_root=project_root,
                workflow_stage="project",
            )
            self.services.workspaces.persist(context_id)
        _remember_recent_project(
            self.services.files.state_root,
            project_root,
            "creative",
        )
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "created",
        }

    def initialize_creative_workspace(self, context_id: str) -> dict[str, object]:
        project_root = self.services.contexts.active_project_root(context_id)
        _ensure_creative_workspace(project_root)
        return self.creative_tree(context_id)

    def creative_tree(self, context_id: str) -> dict[str, object]:
        project_root = self.services.contexts.active_project_root(context_id)
        return _creative_tree_payload(project_root)

    def create_creative_folder(
        self,
        context_id: str,
        relative_path: str,
    ) -> dict[str, object]:
        project_root = self.services.contexts.active_project_root(context_id)
        path = _create_creative_folder(project_root, relative_path)
        return {
            "status": "created",
            "path": path,
        }

    def create_creative_document(
        self,
        context_id: str,
        relative_path: str,
    ) -> dict[str, object]:
        project_root = self.services.contexts.active_project_root(context_id)
        path = _create_creative_document(project_root, relative_path)
        return {
            "status": "created",
            "path": path,
        }

    def create_creative_corkboard(
        self,
        context_id: str,
        relative_path: str,
    ) -> dict[str, object]:
        return self.corkboard_provider.create_board(context_id, relative_path)

    def rename_creative_entry(
        self,
        context_id: str,
        relative_path: str,
        new_name: str,
    ) -> dict[str, object]:
        project_root = self.services.contexts.active_project_root(context_id)
        old_path, new_path = _rename_creative_entry(
            project_root,
            relative_path,
            new_name,
        )
        return {
            "status": "renamed",
            "old_path": old_path,
            "path": new_path,
        }

    def delete_creative_entry(
        self,
        context_id: str,
        relative_path: str,
    ) -> dict[str, object]:
        project_root = self.services.contexts.active_project_root(context_id)
        path = _delete_creative_entry(project_root, relative_path)
        return {
            "status": "deleted",
            "path": path,
        }

    def set_creative_folder_color(
        self,
        context_id: str,
        relative_path: str,
        color: str,
    ) -> dict[str, object]:
        project_root = self.services.contexts.active_project_root(context_id)
        path, color_id = _set_creative_folder_color(
            project_root,
            relative_path,
            color,
        )
        return {
            "status": "updated",
            "path": path,
            "color": color_id,
        }

    def creative_scratchpad(self, context_id: str) -> dict[str, object]:
        project_root = self.services.contexts.active_project_root(context_id)
        path = _ensure_creative_scratchpad(project_root)
        return {
            "path": path.relative_to(project_root).as_posix(),
            "markdown": path.read_text(encoding="utf-8"),
        }

    def save_creative_scratchpad(
        self,
        context_id: str,
        markdown: str,
    ) -> dict[str, object]:
        project_root = self.services.contexts.active_project_root(context_id)
        path = _ensure_creative_scratchpad(project_root)
        path.write_text(markdown, encoding="utf-8")
        return {
            "status": "saved",
            "path": path.relative_to(project_root).as_posix(),
        }

    def save_creative_corkboard(
        self,
        context_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        return self.corkboard_provider.apply_operation(context_id, payload)

    def _creative_agent_scope(
        self,
        project_root: Path,
        *,
        scope: str = "",
        active_document: str | None = None,
        active_target: dict[str, object] | None = None,
    ) -> tuple[str, str, str, dict[str, str] | None]:
        requested_scope = scope.strip()
        target = _creative_agent_target(
            project_root,
            active_target=active_target,
            active_document=active_document,
        )
        document_path = ""
        if requested_scope == CREATIVE_DOCUMENT_SCOPE or (
            target is not None and target.get("type") == "document"
        ):
            if target is not None and target.get("type") == "document":
                document_path = target.get("path", "")
            elif active_document:
                document_path = _document_target_path(project_root, active_document)[0]
            if not document_path:
                raise AgentSessionError("select a document first")
            return (
                CREATIVE_DOCUMENT_SCOPE,
                creative_document_scope_key(document_path),
                document_path,
                {"type": "document", "path": document_path},
            )
        return CREATIVE_GENERAL_SCOPE, CREATIVE_GENERAL_SCOPE_KEY, "", target

    def _creative_session_matches_scope(
        self,
        session: AgentSession,
        *,
        scope_key: str,
    ) -> bool:
        metadata = session.metadata or {}
        session_scope_key = str(
            metadata.get("creative_scope_key") or CREATIVE_GENERAL_SCOPE_KEY
        )
        return session_scope_key == scope_key

    def _creative_session_from_request(
        self,
        context_id: str,
        session_id: str,
        *,
        scope_key: str,
        match_service_id: bool = True,
        match_provider_id: bool = True,
        require_active_provider: bool = False,
    ) -> AgentSession | None:
        requested_id = session_id.strip()
        if not requested_id:
            return None
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            for session in context.creative_sessions.values():
                provider_session_id = str(
                    session.metadata.get("provider_session_id") or ""
                )
                if (
                    (
                        match_service_id
                        and session.session_id == requested_id
                    )
                    or (
                        match_provider_id
                        and provider_session_id.lower() == requested_id.lower()
                        and (
                            not require_active_provider
                            or session.is_active()
                        )
                    )
                ) and self._creative_session_matches_scope(
                    session,
                    scope_key=scope_key,
                ):
                    context.selected_session_id = session.session_id
                    self.services.sessions.record(context, session)
                    return session
        return None

    def _creative_session_payload(
        self,
        session: AgentSession,
        *,
        selected_session_id: str | None,
    ) -> dict[str, object]:
        payload = session.payload(selected=session.session_id == selected_session_id)
        metadata = dict(payload.get("metadata") or {})
        payload["electroboy_session_id"] = session.session_id
        payload["provider_session_id"] = str(metadata.get("provider_session_id") or "")
        payload["scope"] = str(metadata.get("creative_scope") or CREATIVE_GENERAL_SCOPE)
        payload["scope_key"] = str(
            metadata.get("creative_scope_key") or CREATIVE_GENERAL_SCOPE_KEY
        )
        payload["document_path"] = str(metadata.get("document_path") or "")
        payload["target_type"] = str(metadata.get("target_type") or "")
        payload["target_path"] = str(metadata.get("target_path") or "")
        payload["title"] = str(metadata.get("title") or session.label)
        payload["resumable"] = bool(metadata.get("provider_session_id"))
        return payload

    def creative_agent_sessions(
        self,
        context_id: str,
        *,
        scope: str = "",
        active_document: str | None = None,
        active_target: dict[str, object] | None = None,
    ) -> dict[str, object]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
        scope_name, scope_key, document_path, target = self._creative_agent_scope(
            project_root,
            scope=scope,
            active_document=active_document,
            active_target=active_target,
        )
        history = creative_session_history(
            self.services.files.state_root,
            project_root,
            scope=scope_name,
            scope_key=scope_key,
        )
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            selected_session_id = context.selected_session_id
            current = [
                self._creative_session_payload(
                    session,
                    selected_session_id=selected_session_id,
                )
                for session in context.creative_sessions.values()
                if self._creative_session_matches_scope(session, scope_key=scope_key)
            ]
        seen: set[tuple[str, str]] = set()
        sessions: list[dict[str, object]] = []
        for entry in [*current, *history]:
            provider_id = str(entry.get("provider_session_id") or "")
            electroboy_id = str(entry.get("electroboy_session_id") or "")
            key = (provider_id, electroboy_id)
            if key in seen:
                continue
            seen.add(key)
            sessions.append(entry)
        return {
            "project_root": str(project_root),
            "scope": scope_name,
            "scope_key": scope_key,
            "document_path": document_path,
            "target": target or {},
            "sessions": sessions,
        }

    def start_creative_writing_agent(
        self,
        context_id: str,
        *,
        active_document: str | None = None,
        active_target: dict[str, object] | None = None,
        scope: str = "",
        session_id: str | None = None,
        provider_session_id: str | None = None,
        start_new: bool = True,
    ) -> tuple[AgentSession, bool]:
        requested_session_id = str(session_id or "").strip()
        requested_provider_session_id = str(provider_session_id or "").strip()
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
        scope_name, scope_key, document_path, target = self._creative_agent_scope(
            project_root,
            scope=scope,
            active_document=active_document,
            active_target=active_target,
        )
        if requested_session_id:
            existing = self._creative_session_from_request(
                context_id,
                requested_session_id,
                scope_key=scope_key,
                require_active_provider=True,
            )
            if existing is not None:
                existing_provider_id = str(
                    existing.metadata.get("provider_session_id") or ""
                )
                if (
                    existing.session_id == requested_session_id
                    and existing_provider_id
                    and not existing.is_active()
                ):
                    requested_provider_session_id = existing_provider_id
                else:
                    return existing, False
            requested_provider_session_id = (
                requested_provider_session_id or requested_session_id
            )
        elif requested_provider_session_id:
            existing = self._creative_session_from_request(
                context_id,
                requested_provider_session_id,
                scope_key=scope_key,
                match_service_id=False,
                require_active_provider=True,
            )
            if existing is not None:
                return existing, False
        elif not start_new:
            with self.services.contexts.lock:
                context = self.services.contexts.require(context_id)
                for session in reversed(list(context.creative_sessions.values())):
                    if (
                        session.is_active()
                        and self._creative_session_matches_scope(
                            session,
                            scope_key=scope_key,
                        )
                    ):
                        context.selected_session_id = session.session_id
                        self.services.sessions.record(context, session)
                        return session, False

        provider_session = None
        provider_catalog_entry: dict[str, object] | None = None
        known_provider_paths: frozenset[Path] = frozenset()
        if requested_provider_session_id:
            provider_session = resumable_creative_session(
                self.services.files.state_root,
                requested_provider_session_id,
                project_root,
                scope_key=scope_key,
                allow_unscoped_codex=True,
            )
            if provider_session is None:
                raise AgentSessionError(
                    "Codex session was not found in ElectroBoy history or "
                    f"local Codex sessions: {requested_provider_session_id}"
                )
            provider_catalog_entry = remember_creative_session(
                self.services.files.state_root,
                provider_session,
                project_root=project_root,
                scope=scope_name,
                scope_key=scope_key,
                document_path=document_path,
                target_type=str((target or {}).get("type") or ""),
                target_path=str((target or {}).get("path") or ""),
            )
        else:
            known_provider_paths = codex_session_paths()

        metadata: dict[str, object] = {
            "provider": "codex",
            "creative_scope": scope_name,
            "creative_scope_key": scope_key,
            "document_path": document_path,
            "target_type": str((target or {}).get("type") or ""),
            "target_path": str((target or {}).get("path") or ""),
        }
        if provider_session is not None:
            metadata.update(
                {
                    "provider_session_id": provider_session.session_id,
                    "resumed_session": True,
                }
            )
            if provider_catalog_entry:
                metadata["title"] = str(
                    provider_catalog_entry.get("title") or "Creative session"
                )
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            if context.active_project_root != project_root:
                raise AgentSessionError("active project changed while starting agent")
            session = AgentSession(
                command=_creative_writing_command(
                    project_root,
                    target,
                    provider_session.session_id if provider_session else None,
                ),
                cwd=project_root,
                label="creative writing agent",
                kind="creative-writing",
                interactive=True,
                metadata=metadata,
            )
            session = self.services.sessions.prepare(context, session)
            context.creative_sessions[session.session_id] = session
            context.selected_session_id = session.session_id
            self.services.sessions.record(context, session)
        try:
            session.start()
        except Exception:
            with self.services.contexts.lock:
                context = self.services.contexts.require(context_id)
                context.creative_sessions.pop(session.session_id, None)
                if context.selected_session_id == session.session_id:
                    context.selected_session_id = None
            raise
        if provider_session is not None:
            remember_creative_session(
                self.services.files.state_root,
                provider_session,
                project_root=project_root,
                scope=scope_name,
                scope_key=scope_key,
                document_path=document_path,
                target_type=str((target or {}).get("type") or ""),
                target_path=str((target or {}).get("path") or ""),
                electroboy_session_id=session.session_id,
            )
        else:

            def registered(provider: CodexSessionSummary) -> None:
                provider_id = provider.session_id
                if provider_id:
                    session.metadata["provider_session_id"] = provider_id
                    session.metadata["resumed_session"] = False

            start_creative_session_tracking(
                self.services.files.state_root,
                project_root,
                session.session_id,
                known_provider_paths,
                session.is_active,
                scope=scope_name,
                scope_key=scope_key,
                document_path=document_path,
                target_type=str((target or {}).get("type") or ""),
                target_path=str((target or {}).get("path") or ""),
                on_registered=registered,
            )
        return session, True
