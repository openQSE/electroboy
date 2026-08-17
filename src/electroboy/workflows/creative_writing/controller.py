"""Creative-writing browser workflow controller."""

from __future__ import annotations

from pathlib import Path

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
)
from electroboy.service.recent_projects import (
    remember_recent_project as _remember_recent_project,
)
from electroboy.service.sessions import AgentSession, AgentSessionError
from electroboy.service.services import ServiceServices
from electroboy.service.workflow_controller import BoundWorkflowController
from electroboy.state_store import StateError

from .corkboard_provider import CreativeWritingCorkboardProvider


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

    def open_creative_project(self, context_id: str, path: str) -> dict[str, object]:
        project_root = _existing_creative_project_root(path)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            self.services.contexts.require_no_active_agent(context)
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
        _remember_recent_project(self.services.files.state_root, project_root, "creative")
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "opened",
        }

    def create_creative_project(self, context_id: str, path: str) -> dict[str, object]:
        project_root = _resolve_project_path(path)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            self.services.contexts.require_no_active_agent(context)
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
        _remember_recent_project(self.services.files.state_root, project_root, "creative")
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

    def start_creative_writing_agent(
        self,
        context_id: str,
        *,
        active_document: str | None = None,
        active_target: dict[str, object] | None = None,
    ) -> tuple[AgentSession, bool]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if (
                context.creative_session is not None
                and context.creative_session.is_active()
            ):
                context.selected_session_id = context.creative_session.session_id
                return context.creative_session, False
            document_path = ""
            if active_document:
                document_path = _document_target_path(project_root, active_document)[0]
            target = _creative_agent_target(
                project_root,
                active_target=active_target,
                active_document=document_path or None,
            )
            session = AgentSession(
                command=_creative_writing_command(project_root, target),
                cwd=project_root,
                label="creative writing agent",
                kind="creative-writing",
                interactive=True,
            )
            session = self.services.sessions.prepare(context, session)
            context.creative_session = session
            context.selected_session_id = session.session_id
        try:
            session.start()
        except Exception:
            with self.services.contexts.lock:
                context = self.services.contexts.require(context_id)
                if context.creative_session is session:
                    context.creative_session = None
                    context.selected_session_id = None
            raise
        return session, True
