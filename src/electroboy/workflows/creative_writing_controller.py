"""Creative-writing browser workflow controller."""

from __future__ import annotations

from electroboy.service import app as service_app
from electroboy.workflows.controller import BoundWorkflowController

AgentSession = service_app.AgentSession
AgentSessionError = service_app.AgentSessionError
StateError = service_app.StateError
_create_creative_corkboard = service_app._create_creative_corkboard
_create_creative_document = service_app._create_creative_document
_create_creative_folder = service_app._create_creative_folder
_creative_agent_target = service_app._creative_agent_target
_creative_tree_payload = service_app._creative_tree_payload
_creative_writing_command = service_app._creative_writing_command
_delete_creative_entry = service_app._delete_creative_entry
_delete_creative_freeform_corkboard_card = (
    service_app._delete_creative_freeform_corkboard_card
)
_document_target_path = service_app._document_target_path
_ensure_creative_scratchpad = service_app._ensure_creative_scratchpad
_ensure_creative_workspace = service_app._ensure_creative_workspace
_existing_creative_project_root = service_app._existing_creative_project_root
_remember_recent_project = service_app._remember_recent_project
_rename_creative_entry = service_app._rename_creative_entry
_resolve_project_path = service_app._resolve_project_path
_save_creative_folder_corkboard_card = service_app._save_creative_folder_corkboard_card
_save_creative_folder_corkboard_order = (
    service_app._save_creative_folder_corkboard_order
)
_save_creative_freeform_corkboard_card = (
    service_app._save_creative_freeform_corkboard_card
)
project_payload = service_app.project_payload


class CreativeWritingWorkflowController(BoundWorkflowController):
    """Own creative project, binder, corkboard, and agent behavior."""

    workflow_id = "creative-writing"

    def open_creative_project(self, context_id: str, path: str) -> dict[str, object]:
        project_root = _existing_creative_project_root(path)
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
        _ensure_creative_workspace(project_root)
        with self.lock:
            context = self._context_locked(context_id)
            context.activation_root = project_root
            context.project_mode = "creative"
            context.active_project_root = project_root
            context.active_repository_name = None
            context.registered_repositories = []
            context.requirements_session = None
            context.design_session = None
            context.design_review_session = None
            context.documentation_sessions = {}
            context.creative_session = None
            context.ad_hoc_session = None
            context.project_shell_session = None
            context.stage_sessions = {}
            context.selected_session_id = None
            context.workflow_stage = "project"
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
        _remember_recent_project(self.root, project_root, "creative")
        return {
            **project_payload(self.root, context, project_root),
            "status": "opened",
        }

    def create_creative_project(self, context_id: str, path: str) -> dict[str, object]:
        project_root = _resolve_project_path(path)
        with self.lock:
            context = self._context_locked(context_id)
            self._require_no_active_agent_locked(context)
        project_root.mkdir(parents=True, exist_ok=True)
        _ensure_creative_workspace(project_root)
        with self.lock:
            context = self._context_locked(context_id)
            context.activation_root = project_root
            context.project_mode = "creative"
            context.active_project_root = project_root
            context.active_repository_name = None
            context.registered_repositories = []
            context.requirements_session = None
            context.design_session = None
            context.design_review_session = None
            context.documentation_sessions = {}
            context.creative_session = None
            context.ad_hoc_session = None
            context.project_shell_session = None
            context.stage_sessions = {}
            context.selected_session_id = None
            context.workflow_stage = "project"
            context.requirements_started = False
            context.design_started = False
            context.design_review_started = False
            context.design_review_interactive = False
            context.stage_started = set()
        _remember_recent_project(self.root, project_root, "creative")
        return {
            **project_payload(self.root, context, project_root),
            "status": "created",
        }

    def initialize_creative_workspace(self, context_id: str) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        _ensure_creative_workspace(project_root)
        return self.creative_tree(context_id)

    def creative_tree(self, context_id: str) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
        return _creative_tree_payload(project_root)

    def create_creative_folder(
        self,
        context_id: str,
        relative_path: str,
    ) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
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
        project_root = self.active_project_root(context_id)
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
        project_root = self.active_project_root(context_id)
        path = _create_creative_corkboard(project_root, relative_path)
        return {
            "status": "created",
            "path": path,
        }

    def rename_creative_entry(
        self,
        context_id: str,
        relative_path: str,
        new_name: str,
    ) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
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
        project_root = self.active_project_root(context_id)
        path = _delete_creative_entry(project_root, relative_path)
        return {
            "status": "deleted",
            "path": path,
        }

    def creative_scratchpad(self, context_id: str) -> dict[str, object]:
        project_root = self.active_project_root(context_id)
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
        project_root = self.active_project_root(context_id)
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
        project_root = self.active_project_root(context_id)
        board_type = str(payload.get("board_type") or "folder")
        if board_type == "folder" and "order" in payload:
            order = payload.get("order")
            if not isinstance(order, list):
                raise StateError("folder corkboard order must be a list")
            saved_order = _save_creative_folder_corkboard_order(
                project_root,
                folder_path=str(payload.get("folder") or ""),
                order=[str(item) for item in order],
            )
            return {
                "status": "saved",
                "order": saved_order,
            }
        if board_type == "folder":
            card = _save_creative_folder_corkboard_card(
                project_root,
                folder_path=str(payload.get("folder") or ""),
                card_path=str(payload.get("path") or ""),
                note=str(payload.get("note") or ""),
                color=payload.get("color"),
            )
            return {
                "status": "saved",
                "card": card,
            }
        if board_type == "freeform":
            if str(payload.get("action") or "") == "delete":
                card_id = _delete_creative_freeform_corkboard_card(
                    project_root,
                    corkboard_path=str(payload.get("corkboard") or ""),
                    card_id=str(payload.get("card_id") or ""),
                )
                return {
                    "status": "deleted",
                    "card_id": card_id,
                }
            card_payload = payload.get("card")
            if not isinstance(card_payload, dict):
                raise StateError("freeform corkboard card is required")
            card = _save_creative_freeform_corkboard_card(
                project_root,
                corkboard_path=str(payload.get("corkboard") or ""),
                card_payload=card_payload,
            )
            return {
                "status": "saved",
                "card": card,
            }
        raise StateError(f"unknown corkboard type: {board_type}")

    def start_creative_writing_agent(
        self,
        context_id: str,
        *,
        active_document: str | None = None,
        active_target: dict[str, object] | None = None,
    ) -> tuple[AgentSession, bool]:
        with self.lock:
            context = self._context_locked(context_id)
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
            session = self._prepare_session_locked(context, session)
            context.creative_session = session
            context.selected_session_id = session.session_id
        try:
            session.start()
        except Exception:
            with self.lock:
                context = self._context_locked(context_id)
                if context.creative_session is session:
                    context.creative_session = None
                    context.selected_session_id = None
            raise
        return session, True
