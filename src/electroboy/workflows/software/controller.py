"""Software-engineering browser workflow controller."""

from __future__ import annotations

import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from electroboy.adapters.codex_sessions import (
    CodexSessionSummary,
    codex_session_paths,
)
from electroboy.models import (
    GATE_DESIGN,
    STAGE_DESIGN_ACCEPTANCE,
    STAGE_DESIGN_REVIEW,
    STAGE_REQUIREMENTS,
)
from electroboy.modules.document_service import _ensure_document_target
from electroboy.modules.project_corkboard import ProjectCorkboardProvider
from electroboy.service.recent_projects import remember_recent_project
from electroboy.service.services import ServiceServices
from electroboy.service.sessions import AgentSession, AgentSessionError
from electroboy.service.workflow_controller import BoundWorkflowController
from electroboy.state_store import StateError, StateStore

from .ad_hoc import (
    ad_hoc_agent_command,
    ad_hoc_session_history,
    remember_ad_hoc_session,
    resumable_ad_hoc_session,
    start_ad_hoc_session_tracking,
)
from .domain import (
    APPROVAL_WORKFLOW_STAGES,
    SESSION_ARTIFACT_LOCKS,
    WORKFLOW_STAGES,
    WORKFLOW_STAGE_RESET_TARGETS,
    _active_workflow_stage,
    _bug_by_slug,
    _bug_record_label,
    _current_bug_record,
    _current_feature_record,
    _documentation_command,
    _ensure_collection_for_feature,
    _feature_by_slug,
    _feature_collection_by_id,
    _feature_record_label,
    _force_reset_workflow_stage,
    _generic_stage_command,
    _generic_stage_config,
    _add_meta_repository,
    _existing_meta_context,
    _existing_project_root,
    _is_meta_project_path,
    _load_work_item_registry,
    _meta_repository_payloads,
    _remove_meta_repository,
    _record_design_complete,
    _record_requirements_complete,
    _reopen_design_for_restart,
    _reopen_requirements_for_restart,
    _requirements_command,
    _run_bug_start_context,
    _run_electroboy_cli_command,
    _run_feature_start_context,
    _save_work_item_registry,
    _should_force_completed_requirements_approval,
    _start_meta_repository,
    _stage_command,
    _stage_display_label,
    _stage_has_approvals,
    _upsert_bug_record,
    _upsert_feature_collection,
    _upsert_feature_record,
    _visible_workflow_stage,
    _write_current_bug_record,
    initialize_meta_project,
    initialize_project,
    project_payload_extension,
    workflow_payload,
)


class SoftwareWorkflowController(BoundWorkflowController):
    """Own software-workflow actions and agent sequencing."""

    workflow_id = "software"

    def __init__(self, services: ServiceServices) -> None:
        super().__init__(services)
        self.corkboard_provider = ProjectCorkboardProvider(self.services)

    def get_corkboard_provider(self) -> ProjectCorkboardProvider:
        return self.corkboard_provider

    def project_payload_extension(self, context_id: str) -> dict[str, object]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            active_root = context.active_project_root
            return project_payload_extension(context, active_root)

    def workflow_payload(self, context_id: str) -> dict[str, object]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            active_root = context.active_project_root
        return workflow_payload(active_root)

    def _reserve_project_workspace(
        self,
        context_id: str,
        project_root: Path,
        project_kind: str,
    ) -> tuple[str, bool]:
        with self.services.contexts.lock:
            current = self.services.contexts.require(context_id)
            self.services.contexts.require_no_active_agent(current)
        workspace, resumed = self.services.workspaces.reserve_project(
            context_id,
            workflow_id=self.workflow_id,
            project_kind=project_kind,
            project_identity=str(project_root),
            name=project_root.name,
        )
        return workspace.context_id, resumed

    def open_project(self, context_id: str, path: str) -> dict[str, object]:
        if _is_meta_project_path(path):
            return self.open_meta_project(context_id, path)
        project_root = _existing_project_root(path)
        context_id, resumed = self._reserve_project_workspace(
            context_id,
            project_root,
            "project",
        )
        if resumed:
            return {
                **self.services.contexts.project_payload(context_id),
                "status": "resumed",
            }
        workflow_stage = _active_workflow_stage(project_root)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            context.reset_project(
                workflow_id=self.workflow_id,
                project_mode="project",
                activation_root=project_root,
                active_project_root=project_root,
                workflow_stage=workflow_stage,
            )
            self.services.workspaces.persist(context_id)
        remember_recent_project(
            self.services.files.state_root,
            project_root,
            "project",
        )
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "opened",
        }

    def create_project(self, context_id: str, path: str) -> dict[str, object]:
        project_root = Path(path).expanduser().resolve()
        context_id, resumed = self._reserve_project_workspace(
            context_id,
            project_root,
            "project",
        )
        if resumed:
            return {
                **self.services.contexts.project_payload(context_id),
                "status": "resumed",
            }
        manifest = initialize_project(project_root)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            context.reset_project(
                workflow_id=self.workflow_id,
                project_mode="project",
                activation_root=project_root,
                active_project_root=project_root,
                workflow_stage=_visible_workflow_stage(manifest.active_stage),
            )
            self.services.workspaces.persist(context_id)
        remember_recent_project(
            self.services.files.state_root,
            project_root,
            "project",
        )
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "created",
            "run_id": manifest.run_id,
        }

    def ad_hoc_sessions(self, context_id: str) -> dict[str, object]:
        """List resumable ad-hoc sessions for the active command root."""

        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            command_root = self.services.contexts.command_root(context)
            if command_root is None:
                raise AgentSessionError("activate a project first")
        return {
            "project_root": str(command_root),
            "sessions": ad_hoc_session_history(
                self.services.files.state_root,
                command_root,
            ),
        }

    def start_ad_hoc_agent(
        self,
        context_id: str,
        provider_session_id: str | None = None,
    ) -> tuple[AgentSession, bool]:
        """Start a workflow-neutral agent or resume a selected Codex UUID."""

        requested_session_id = str(provider_session_id or "").strip().lower()
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            command_root = self.services.contexts.command_root(context)
            if command_root is None:
                raise AgentSessionError("activate a project first")
            if (
                context.ad_hoc_session is not None
                and context.ad_hoc_session.is_active()
            ):
                context.selected_session_id = context.ad_hoc_session.session_id
                return context.ad_hoc_session, False

        provider_session = None
        known_provider_paths: frozenset[Path] = frozenset()
        if requested_session_id:
            provider_session = resumable_ad_hoc_session(
                self.services.files.state_root,
                requested_session_id,
                command_root,
            )
            if provider_session is None:
                raise AgentSessionError(
                    "Codex session was not found for the active project: "
                    f"{requested_session_id}"
                )
            remember_ad_hoc_session(
                self.services.files.state_root,
                provider_session,
            )
        else:
            known_provider_paths = codex_session_paths()

        metadata: dict[str, object] = {"provider": "codex"}
        if provider_session is not None:
            metadata.update(
                {
                    "provider_session_id": provider_session.session_id,
                    "resumed_session": True,
                }
            )
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            current_root = self.services.contexts.command_root(context)
            if current_root != command_root:
                raise AgentSessionError("active project changed while starting ad-hoc")
            if (
                context.ad_hoc_session is not None
                and context.ad_hoc_session.is_active()
            ):
                context.selected_session_id = context.ad_hoc_session.session_id
                return context.ad_hoc_session, False
            session = AgentSession(
                command=ad_hoc_agent_command(
                    command_root,
                    provider_session.session_id if provider_session else None,
                ),
                cwd=command_root,
                label="ad-hoc agent",
                kind="ad-hoc",
                interactive=True,
                metadata=metadata,
            )
            session = self.services.sessions.prepare(context, session)
            context.ad_hoc_session = session
            context.selected_session_id = session.session_id
        try:
            session.start()
        except Exception:
            with self.services.contexts.lock:
                context = self.services.contexts.require(context_id)
                if context.ad_hoc_session is session:
                    context.ad_hoc_session = None
                    if context.selected_session_id == session.session_id:
                        context.selected_session_id = None
            raise
        if provider_session is None:

            def registered(provider: CodexSessionSummary) -> None:
                provider_id = provider.session_id
                if provider_id:
                    session.metadata["provider_session_id"] = provider_id
                    session.metadata["resumed_session"] = False

            start_ad_hoc_session_tracking(
                self.services.files.state_root,
                command_root,
                session.session_id,
                known_provider_paths,
                session.is_active,
                registered,
            )
        return session, True

    def open_meta_project(self, context_id: str, path: str) -> dict[str, object]:
        meta_context = _existing_meta_context(path)
        meta_root = Path(str(meta_context["meta_root"]))
        context_id, resumed = self._reserve_project_workspace(
            context_id,
            meta_root,
            "meta-project",
        )
        if resumed:
            return {
                **self.services.contexts.project_payload(context_id),
                "status": "resumed",
            }
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            context.reset_project(
                workflow_id=self.workflow_id,
                project_mode="meta",
                activation_root=meta_context["meta_root"],
                active_project_root=meta_context["active_project_root"],
                active_repository_name=meta_context["active_repository_name"],
                registered_repositories=meta_context["registered_repositories"],
                workflow_stage=meta_context["workflow_stage"],
            )
            self.services.workspaces.persist(context_id)
        remember_recent_project(
            self.services.files.state_root,
            Path(str(meta_context["meta_root"])),
            "meta",
        )
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "opened",
        }

    def create_meta_project(self, context_id: str, path: str) -> dict[str, object]:
        requested_root = Path(path).expanduser().resolve()
        context_id, resumed = self._reserve_project_workspace(
            context_id,
            requested_root,
            "meta-project",
        )
        if resumed:
            return {
                **self.services.contexts.project_payload(context_id),
                "status": "resumed",
            }
        meta_root, registry = initialize_meta_project(path)
        repositories = _meta_repository_payloads(registry)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            context.reset_project(
                workflow_id=self.workflow_id,
                project_mode="meta",
                activation_root=meta_root,
                active_project_root=None,
                registered_repositories=repositories,
            )
            self.services.workspaces.persist(context_id)
        remember_recent_project(self.services.files.state_root, meta_root, "meta")
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "created",
        }

    def add_meta_repository(
        self,
        context_id: str,
        path: str,
    ) -> dict[str, object]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            self.services.contexts.require_no_active_agent(context)
            meta_root = context.activation_root
            if meta_root is None or context.project_mode != "meta":
                raise StateError("activate a meta-project first")
        meta_context = _add_meta_repository(meta_root, path)
        return self._apply_meta_context(context_id, meta_context, "registered")

    def start_meta_repository(
        self,
        context_id: str,
        repository: str,
    ) -> dict[str, object]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            self.services.contexts.require_no_active_agent(context)
            meta_root = context.activation_root
            if meta_root is None or context.project_mode != "meta":
                raise StateError("activate a meta-project first")
        meta_context = _start_meta_repository(meta_root, repository)
        return self._apply_meta_context(context_id, meta_context, "started")

    def remove_meta_repository(
        self,
        context_id: str,
        repository: str,
    ) -> dict[str, object]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            self.services.contexts.require_no_active_agent(context)
            meta_root = context.activation_root
            if meta_root is None or context.project_mode != "meta":
                raise StateError("activate a meta-project first")
        meta_context = _remove_meta_repository(meta_root, repository)
        return self._apply_meta_context(context_id, meta_context, "removed")

    def _apply_meta_context(
        self,
        context_id: str,
        meta_context: dict[str, object],
        status: str,
    ) -> dict[str, object]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            context.reset_project(
                workflow_id=self.workflow_id,
                project_mode="meta",
                activation_root=Path(str(meta_context["meta_root"])),
                active_project_root=meta_context["active_project_root"],
                active_repository_name=meta_context["active_repository_name"],
                registered_repositories=meta_context["registered_repositories"],
                workflow_stage=meta_context["workflow_stage"],
            )
            self.services.workspaces.persist(context_id)
        return {
            **self.services.contexts.project_payload(context_id),
            "status": status,
        }

    def create_feature_collection(
        self,
        context_id: str,
        name: str,
    ) -> dict[str, object]:
        collection_name = name.strip()
        if not collection_name:
            raise StateError("feature collection name is required")
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise StateError("activate a project first")
            self.services.contexts.require_no_active_agent(context)
        registry = _load_work_item_registry(project_root)
        collection = _upsert_feature_collection(registry, collection_name)
        registry["active_collection_id"] = collection["id"]
        _save_work_item_registry(project_root, registry)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "created collection",
            "label": collection["name"],
        }

    def switch_feature_collection(
        self,
        context_id: str,
        collection_id: str,
    ) -> dict[str, object]:
        collection_id = collection_id.strip()
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise StateError("activate a project first")
            self.services.contexts.require_no_active_agent(context)
        registry = _load_work_item_registry(project_root)
        collection = _feature_collection_by_id(registry, collection_id)
        if collection is None:
            raise StateError("unknown feature collection")
        registry["active_collection_id"] = collection["id"]
        _save_work_item_registry(project_root, registry)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "switched collection",
            "label": collection["name"],
        }

    def start_feature_work_item(
        self,
        context_id: str,
        *,
        title: str,
        feature_name: str | None = None,
        collection_id: str | None = None,
        parent_slug: str | None = None,
        branch: bool = False,
        stash_subrepo_changes: bool = False,
    ) -> dict[str, object]:
        title = title.strip()
        if not title:
            raise AgentSessionError("feature title is required")
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
        terminated_agent = self.services.sessions.terminate_workflow(context_id)
        output = _run_feature_start_context(
            project_root,
            title=title,
            feature_name=feature_name,
            amend=True,
            branch=branch,
            stash_subrepo_changes=stash_subrepo_changes,
        )
        registry = _load_work_item_registry(project_root)
        feature_record = _current_feature_record(project_root)
        if feature_record is not None:
            effective_collection_id = (
                collection_id if collection_id or parent_slug else "default"
            )
            collection = _ensure_collection_for_feature(
                registry,
                effective_collection_id,
                parent_slug=parent_slug,
            )
            _upsert_feature_record(
                registry,
                feature_record,
                collection_id=str(collection["id"]),
                parent_slug=parent_slug,
            )
            registry["active_collection_id"] = collection["id"]
            registry["active_feature_slug"] = feature_record.get("slug")
            registry["active_bug_slug"] = None
            _save_work_item_registry(project_root, registry)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            context.workflow_stage = _active_workflow_stage(project_root)
            project_root = context.active_project_root
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "started feature",
            "label": _feature_record_label(feature_record) if feature_record else title,
            "output": output,
            "terminated_agent": terminated_agent,
        }

    def switch_feature_work_item(
        self,
        context_id: str,
        slug: str,
    ) -> dict[str, object]:
        slug = slug.strip()
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
        registry = _load_work_item_registry(project_root)
        feature = _feature_by_slug(registry, slug)
        if feature is None:
            raise AgentSessionError("unknown feature")
        terminated_agent = self.services.sessions.terminate_workflow(context_id)
        output = _run_feature_start_context(
            project_root,
            title=str(feature.get("input") or feature.get("title") or slug),
            feature_name=str(feature.get("name") or slug),
            amend=True,
            branch=bool(feature.get("branch")),
            branch_name=(
                str(feature.get("branch"))
                if isinstance(feature.get("branch"), str)
                and str(feature.get("branch")).strip()
                else None
            ),
        )
        feature_record = _current_feature_record(project_root)
        if feature_record is not None:
            _upsert_feature_record(
                registry,
                feature_record,
                collection_id=str(feature.get("collection_id") or ""),
                parent_slug=(
                    str(feature.get("parent_slug"))
                    if feature.get("parent_slug")
                    else None
                ),
            )
        registry["active_feature_slug"] = slug
        registry["active_bug_slug"] = None
        if feature.get("collection_id"):
            registry["active_collection_id"] = feature.get("collection_id")
        _save_work_item_registry(project_root, registry)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            context.workflow_stage = _active_workflow_stage(project_root)
            project_root = context.active_project_root
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "switched feature",
            "label": _feature_record_label(feature),
            "output": output,
            "terminated_agent": terminated_agent,
        }

    def start_bug_work_item(
        self,
        context_id: str,
        *,
        issue_reference: str,
        branch: bool = False,
        stash_subrepo_changes: bool = False,
    ) -> dict[str, object]:
        issue_reference = issue_reference.strip()
        if not issue_reference:
            raise AgentSessionError("bug issue reference is required")
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
        terminated_agent = self.services.sessions.terminate_workflow(context_id)
        output = _run_bug_start_context(
            project_root,
            issue_reference=issue_reference,
            branch=branch,
            stash_subrepo_changes=stash_subrepo_changes,
        )
        registry = _load_work_item_registry(project_root)
        bug_record = _current_bug_record(project_root)
        if bug_record is not None:
            _upsert_bug_record(registry, bug_record)
            registry["active_bug_slug"] = bug_record.get("slug")
            registry["active_feature_slug"] = None
            _save_work_item_registry(project_root, registry)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "started bug resolution",
            "label": _bug_record_label(bug_record) if bug_record else issue_reference,
            "output": output,
            "terminated_agent": terminated_agent,
        }

    def switch_bug_work_item(
        self,
        context_id: str,
        slug: str,
    ) -> dict[str, object]:
        slug = slug.strip()
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
        registry = _load_work_item_registry(project_root)
        bug = _bug_by_slug(registry, slug)
        if bug is None:
            raise AgentSessionError("unknown bug")
        terminated_agent = self.services.sessions.terminate_workflow(context_id)
        _write_current_bug_record(project_root, bug)
        registry["active_bug_slug"] = slug
        registry["active_feature_slug"] = None
        _save_work_item_registry(project_root, registry)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "switched bug resolution",
            "label": _bug_record_label(bug),
            "terminated_agent": terminated_agent,
        }

    def select_workflow_stage(
        self,
        context_id: str,
        stage: str,
    ) -> dict[str, object]:
        stage = stage.strip()
        if stage in APPROVAL_WORKFLOW_STAGES:
            raise StateError(f"approval stage is not directly selectable: {stage}")
        if stage == "project" or stage not in WORKFLOW_STAGES:
            raise StateError(f"unknown workflow stage: {stage}")
        target_stage = WORKFLOW_STAGE_RESET_TARGETS.get(stage)
        if target_stage is None:
            raise StateError(f"stage cannot be set directly: {stage}")
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise StateError("activate a project first")
            previous_stage = context.workflow_stage
        terminated_agent = False
        if previous_stage != stage:
            terminated_agent = self.services.sessions.terminate_workflow(context_id)
        reset_decision = None
        reset_output = ""
        if previous_stage != stage:
            reset_decision, reset_output = _force_reset_workflow_stage(
                project_root,
                stage,
                target_stage,
            )
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            context.workflow_stage = stage
            project_root = context.active_project_root
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "selected",
            "previous_stage": previous_stage,
            "terminated_agent": terminated_agent,
            "reset_decision": reset_decision,
            "reset_output": reset_output,
        }

    def approve_requirements(
        self,
        context_id: str,
        *,
        skip_approval: bool = False,
    ) -> dict[str, object]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage not in {"requirements", "requirements-approve"}:
                raise AgentSessionError("requirements stage is not active")
            requirements_started = context.requirements_started
        self.services.sessions.terminate_kind(context_id, "requirements")
        _record_requirements_complete(project_root, skipped=skip_approval)
        from .cli import _cmd_stage, _stage_args
        from electroboy.gates import GateEngine

        stdout = io.StringIO()
        stderr = io.StringIO()
        store = StateStore(project_root)
        engine = GateEngine(project_root)
        previously_approved = _stage_has_approvals(
            project_root,
            STAGE_REQUIREMENTS,
            ["human-approval", "author-confirmation"],
        )
        if skip_approval:
            force_approval = True
            reason = (
                "Requirements approval was skipped from the GUI during an "
                "update after a previous requirements approval."
                if previously_approved
                else "WARNING: requirements approval was skipped from the GUI. "
                "The operator accepted the risk that requirements were not "
                "explicitly approved."
            )
        else:
            force_approval = _should_force_completed_requirements_approval(store)
            reason = (
                "Requirements authoring was completed from the GUI without "
                "agent confirmation; approval "
                "force-records the missing author confirmation."
                if force_approval
                else None
            )
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = _cmd_stage(
                store,
                engine,
                _stage_args(
                    STAGE_REQUIREMENTS,
                    human=True,
                    author=True,
                    force=force_approval,
                    reason=reason,
                ),
            )
        output = "\n".join(
            part.strip()
            for part in [stderr.getvalue(), stdout.getvalue()]
            if part.strip()
        )
        if code != 0:
            raise AgentSessionError(output or "requirements approval failed")
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            context.workflow_stage = "design"
            context.requirements_session = None
            context.requirements_started = requirements_started
            project_root = context.active_project_root
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "skipped" if skip_approval else "approved",
            "next_stage": "design",
            "output": output,
            "warning": (
                "WARNING: requirements approval was skipped; advancing to design "
                "with forced approval records."
                if skip_approval and not previously_approved
                else None
            ),
        }

    def start_requirements_agent(
        self,
        context_id: str,
        *,
        allow_stage_reopen: bool = False,
    ) -> tuple[AgentSession, bool]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            command_root = self.services.contexts.command_root(context)
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != "requirements" and not allow_stage_reopen:
                raise AgentSessionError("requirements stage is not active")
            if (
                context.requirements_session is not None
                and context.requirements_session.is_active()
            ):
                return context.requirements_session, False
            lock_names = SESSION_ARTIFACT_LOCKS["requirements"]
            self.services.sessions.require_locks_available(context, lock_names)
            session = AgentSession(
                command=_requirements_command(command_root),
                cwd=command_root,
                label="requirements agent",
                kind="requirements",
                interactive=True,
                lock_names=lock_names,
            )
            session = self.services.sessions.prepare(context, session)
            context.requirements_session = session
            context.selected_session_id = session.session_id
            context.workflow_stage = "requirements"
        try:
            session.start()
        except Exception:
            with self.services.contexts.lock:
                context = self.services.contexts.require(context_id)
                if context.requirements_session is session:
                    context.requirements_session = None
                    if context.selected_session_id == session.session_id:
                        context.selected_session_id = None
                    context.requirements_started = False
            raise
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            if context.requirements_session is session:
                context.requirements_started = True
        return session, True

    def restart_requirements_agent(
        self,
        context_id: str,
    ) -> tuple[AgentSession, bool]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if (
                context.workflow_stage == "requirements"
                and not context.requirements_started
            ):
                raise AgentSessionError("start requirements first")
        self.services.sessions.terminate_kind(context_id, "requirements")
        _reopen_requirements_for_restart(project_root)
        return self.start_requirements_agent(context_id, allow_stage_reopen=True)

    def complete_requirements_agent(self, context_id: str) -> dict[str, object]:
        return self.approve_requirements(context_id)

    def skip_requirements_agent(self, context_id: str) -> dict[str, object]:
        return self.approve_requirements(context_id, skip_approval=True)

    def start_design_agent(
        self,
        context_id: str,
        *,
        allow_stage_reopen: bool = False,
    ) -> tuple[AgentSession, bool]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            command_root = self.services.contexts.command_root(context)
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != "design" and not allow_stage_reopen:
                raise AgentSessionError("design stage is not active")
            if (
                context.design_session is not None
                and context.design_session.is_active()
            ):
                return context.design_session, False
            lock_names = SESSION_ARTIFACT_LOCKS["design"]
            self.services.sessions.require_locks_available(context, lock_names)
            session = AgentSession(
                command=_stage_command(command_root, "design"),
                cwd=command_root,
                label="design agent",
                kind="design",
                interactive=True,
                lock_names=lock_names,
            )
            session = self.services.sessions.prepare(context, session)
            context.design_session = session
            context.selected_session_id = session.session_id
            context.workflow_stage = "design"
        try:
            session.start()
        except Exception:
            with self.services.contexts.lock:
                context = self.services.contexts.require(context_id)
                if context.design_session is session:
                    context.design_session = None
                    if context.selected_session_id == session.session_id:
                        context.selected_session_id = None
                    context.design_started = False
            raise
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            if context.design_session is session:
                context.design_started = True
        return session, True

    def restart_design_agent(
        self,
        context_id: str,
    ) -> tuple[AgentSession, bool]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage == "design":
                raise AgentSessionError("design stage is already active")
        self.services.sessions.terminate_workflow(context_id)
        _reopen_design_for_restart(project_root)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            context.design_review_started = False
            context.design_review_interactive = False
        return self.start_design_agent(context_id, allow_stage_reopen=True)

    def complete_design_agent(self, context_id: str) -> dict[str, object]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != "design":
                raise AgentSessionError("design stage is not active")
            design_started = context.design_started
        self.services.sessions.terminate_kind(context_id, "design")
        _record_design_complete(project_root)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            context.workflow_stage = "design-review"
            context.design_session = None
            context.design_started = design_started
            context.design_review_session = None
            context.design_review_started = False
            context.design_review_interactive = False
            project_root = context.active_project_root
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "completed",
            "next_stage": "design-review",
        }

    def start_design_review_agent(
        self,
        context_id: str,
        *,
        force: bool = False,
        allow_stage_reopen: bool = False,
        interactive: bool = False,
    ) -> tuple[AgentSession, bool]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            command_root = self.services.contexts.command_root(context)
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != "design-review" and not allow_stage_reopen:
                raise AgentSessionError("design review stage is not active")
            if (
                context.design_review_session is not None
                and context.design_review_session.is_active()
            ):
                return context.design_review_session, False
            lock_names = SESSION_ARTIFACT_LOCKS["design-review"]
            self.services.sessions.require_locks_available(context, lock_names)
            session = AgentSession(
                command=_stage_command(
                    command_root,
                    "design-review",
                    force=force,
                    interactive=interactive,
                ),
                cwd=command_root,
                label=(
                    "interactive design-review agent"
                    if interactive
                    else "design-review agent"
                ),
                kind="design-review",
                interactive=interactive,
                lock_names=lock_names,
                on_completed=(
                    None
                    if interactive
                    else lambda returncode: self._mark_design_review_completed(
                        context_id,
                        returncode,
                    )
                ),
            )
            session = self.services.sessions.prepare(context, session)
            context.design_review_session = session
            context.selected_session_id = session.session_id
            context.design_review_interactive = interactive
            context.workflow_stage = "design-review"
        try:
            session.start()
        except Exception:
            with self.services.contexts.lock:
                context = self.services.contexts.require(context_id)
                if context.design_review_session is session:
                    context.design_review_session = None
                    if context.selected_session_id == session.session_id:
                        context.selected_session_id = None
                    context.design_review_started = False
                    context.design_review_interactive = False
            raise
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            if context.design_review_session is session:
                context.design_review_started = True
        return session, True

    def restart_design_review_agent(
        self,
        context_id: str,
    ) -> tuple[AgentSession, bool]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            force = context.workflow_stage != "design-review"
            if (
                context.workflow_stage == "design-review"
                and not context.design_review_started
            ):
                raise AgentSessionError("start design review first")
        self.services.sessions.terminate_workflow(context_id)
        return self.start_design_review_agent(
            context_id,
            force=force,
            allow_stage_reopen=True,
        )

    def start_documentation_agent(
        self,
        context_id: str,
        *,
        interactive: bool = True,
        target: str | None = None,
    ) -> tuple[AgentSession, bool]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            command_root = self.services.contexts.command_root(context)
            if project_root is None:
                raise AgentSessionError("activate a project first")
            target_path = (target or "").strip()
            if target_path:
                target_path = _ensure_document_target(project_root, target_path)
            session_key = target_path or "__default__"
            existing_session = context.documentation_sessions.get(session_key)
            if existing_session is not None and existing_session.is_active():
                context.selected_session_id = existing_session.session_id
                return existing_session, False
            lock_names = frozenset({f"documentation:{session_key}"})
            self.services.sessions.require_locks_available(context, lock_names)
            label_target = f" ({target_path})" if target_path else ""
            document_label = Path(target_path).name if target_path else "Documentation"
            session = AgentSession(
                command=_documentation_command(
                    command_root,
                    interactive=interactive,
                    target=target_path or None,
                ),
                cwd=command_root,
                label=(
                    f"interactive documentation agent{label_target}"
                    if interactive
                    else f"documentation agent{label_target}"
                ),
                kind="documentation",
                interactive=interactive,
                lock_names=lock_names,
                metadata={
                    "document_path": target_path,
                    "document_label": document_label,
                },
            )
            session = self.services.sessions.prepare(context, session)
            context.documentation_sessions[session_key] = session
            context.selected_session_id = session.session_id
        try:
            session.start()
        except Exception:
            with self.services.contexts.lock:
                context = self.services.contexts.require(context_id)
                if context.documentation_sessions.get(session_key) is session:
                    context.documentation_sessions.pop(session_key, None)
                    context.selected_session_id = None
            raise
        return session, True

    def stop_design_review_agent(self, context_id: str) -> dict[str, object]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != "design-review":
                raise AgentSessionError("design review stage is not active")
            session = context.design_review_session
            if session is None or not session.is_active():
                raise AgentSessionError("design review is not running")
        session.terminate()
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            if context.design_review_session is session:
                context.design_review_session = None
                context.design_review_interactive = False
            session_id = getattr(session, "session_id", None)
            if session_id is not None and context.selected_session_id == session_id:
                context.selected_session_id = None
            project_root = context.active_project_root
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "stopped",
        }

    def complete_design_review_agent(self, context_id: str) -> dict[str, object]:
        return self.approve_design(context_id)

    def approve_design(
        self,
        context_id: str,
        *,
        skip_approval: bool = False,
    ) -> dict[str, object]:
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage not in {"design-review", "design-approve"}:
                raise AgentSessionError("design review stage is not active")
            session = context.design_review_session
            design_review_started = context.design_review_started
            needs_design_review_completion = context.workflow_stage == "design-review"
        if session is not None and session.is_active():
            session.terminate()
        from .cli import _cmd_stage, _stage_args
        from electroboy.gates import GateEngine

        stdout = io.StringIO()
        stderr = io.StringIO()
        store = StateStore(project_root)
        engine = GateEngine(project_root)
        manifest = store.load_current_manifest()
        if needs_design_review_completion and not manifest.has_gate(GATE_DESIGN):
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = _cmd_stage(
                    store,
                    engine,
                    _stage_args(
                        STAGE_DESIGN_REVIEW,
                        force=True,
                        reason=(
                            "Design review was completed from the GUI approval "
                            "action."
                        ),
                    ),
                )
            if code != 0:
                output = "\n".join(
                    part.strip()
                    for part in [stderr.getvalue(), stdout.getvalue()]
                    if part.strip()
                )
                with self.services.contexts.lock:
                    context = self.services.contexts.require(context_id)
                    if context.design_review_session is session:
                        context.design_review_session = None
                        if (
                            session is not None
                            and context.selected_session_id
                            == getattr(session, "session_id", None)
                        ):
                            context.selected_session_id = None
                        context.design_review_interactive = False
                raise AgentSessionError(output or "design review completion failed")
            store = StateStore(project_root)
            engine = GateEngine(project_root)
        previously_approved = _stage_has_approvals(
            project_root,
            STAGE_DESIGN_ACCEPTANCE,
            ["human-approval"],
        )
        if skip_approval:
            reason = (
                "Design approval was skipped from the GUI during an update "
                "after a previous design approval."
                if previously_approved
                else "WARNING: design approval was skipped from the GUI. "
                "The operator accepted the risk that design was not "
                "explicitly approved."
            )
        else:
            reason = None
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = _cmd_stage(
                store,
                engine,
                _stage_args(
                    STAGE_DESIGN_ACCEPTANCE,
                    human=True,
                    force=skip_approval,
                    reason=reason,
                ),
            )
        output = "\n".join(
            part.strip()
            for part in [stderr.getvalue(), stdout.getvalue()]
            if part.strip()
        )
        if code != 0:
            raise AgentSessionError(output or "design approval failed")
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            context.workflow_stage = "implementation-plan"
            context.design_review_session = None
            context.design_review_interactive = False
            context.design_review_started = design_review_started
            project_root = context.active_project_root
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "skipped" if skip_approval else "approved",
            "next_stage": "implementation-plan",
            "output": output,
            "warning": (
                "WARNING: design approval was skipped; advancing to "
                "implementation planning with a forced approval record."
                if skip_approval and not previously_approved
                else None
            ),
        }

    def start_workflow_stage_agent(
        self,
        context_id: str,
        stage: str,
        *,
        interactive: bool | None = None,
        force: bool = False,
        allow_stage_reopen: bool = False,
    ) -> tuple[AgentSession, bool]:
        config = _generic_stage_config(stage)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            command_root = self.services.contexts.command_root(context)
            if project_root is None or command_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != stage and not allow_stage_reopen:
                raise AgentSessionError(f"{stage} stage is not active")
            existing = context.stage_sessions.get(stage)
            if existing is not None and existing.is_active():
                return existing, False
            lock_names = SESSION_ARTIFACT_LOCKS.get(stage, frozenset())
            self.services.sessions.require_locks_available(context, lock_names)
            accepts_input = (
                bool(config["interactive_default"])
                if interactive is None
                else interactive
            )
            session = AgentSession(
                command=_generic_stage_command(
                    command_root,
                    stage,
                    force=force,
                    reason=(
                        f"{_stage_display_label(stage)} restarted from the GUI."
                        if force and bool(config.get("reason_arg"))
                        else None
                    ),
                    interactive=accepts_input,
                ),
                cwd=command_root,
                label=(
                    f"interactive {_stage_display_label(stage)} agent"
                    if accepts_input
                    else f"{_stage_display_label(stage)} agent"
                ),
                kind=stage,
                interactive=accepts_input,
                lock_names=lock_names,
                on_completed=lambda returncode: self._mark_generic_stage_completed(
                    context_id,
                    stage,
                    returncode,
                ),
            )
            session = self.services.sessions.prepare(context, session)
            context.stage_sessions[stage] = session
            context.selected_session_id = session.session_id
            context.workflow_stage = stage
        try:
            session.start()
        except Exception:
            with self.services.contexts.lock:
                context = self.services.contexts.require(context_id)
                if context.stage_sessions.get(stage) is session:
                    context.stage_sessions.pop(stage, None)
                    if context.selected_session_id == session.session_id:
                        context.selected_session_id = None
                    context.stage_started.discard(stage)
            raise
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            if context.stage_sessions.get(stage) is session:
                context.stage_started.add(stage)
        return session, True

    def restart_workflow_stage_agent(
        self,
        context_id: str,
        stage: str,
        *,
        interactive: bool | None = None,
    ) -> tuple[AgentSession, bool]:
        _generic_stage_config(stage)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage == stage and stage not in context.stage_started:
                raise AgentSessionError(f"start {stage} first")
        self.services.sessions.terminate_workflow(context_id)
        return self.start_workflow_stage_agent(
            context_id,
            stage,
            interactive=interactive,
            force=True,
            allow_stage_reopen=True,
        )

    def stop_workflow_stage_agent(
        self,
        context_id: str,
        stage: str,
    ) -> dict[str, object]:
        _generic_stage_config(stage)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != stage:
                raise AgentSessionError(f"{stage} stage is not active")
            session = context.stage_sessions.get(stage)
            if session is None or not session.is_active():
                raise AgentSessionError(f"{stage} agent is not running")
        session.terminate()
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            if context.stage_sessions.get(stage) is session:
                context.stage_sessions.pop(stage, None)
            if context.selected_session_id == session.session_id:
                context.selected_session_id = None
            project_root = context.active_project_root
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "stopped",
        }

    def approve_workflow_stage(
        self,
        context_id: str,
        stage: str,
        *,
        skip_approval: bool = False,
    ) -> dict[str, object]:
        config = _generic_stage_config(stage)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            project_root = context.active_project_root
            if project_root is None:
                raise AgentSessionError("activate a project first")
            if context.workflow_stage != stage:
                raise AgentSessionError(f"{stage} stage is not active")
            session = context.stage_sessions.get(stage)
        if session is not None and session.is_active():
            session.terminate()
        command = [str(config["approval_command"])]
        warning = None
        if skip_approval:
            command.append("--force")
            if bool(config.get("approval_reason_arg", config.get("reason_arg"))):
                command.extend(
                    [
                        "--reason",
                        (
                            f"WARNING: {_stage_display_label(stage)} approval was "
                            "skipped from the GUI. The operator accepted the risk "
                            "that the stage was not explicitly approved."
                        ),
                    ]
                )
            warning = (
                f"WARNING: {_stage_display_label(stage)} approval was skipped; "
                "advancing with forced approval records."
            )
        output = _run_electroboy_cli_command(project_root, command)
        with self.services.contexts.lock:
            context = self.services.contexts.require(context_id)
            if context.stage_sessions.get(stage) is session:
                context.stage_sessions.pop(stage, None)
            context.stage_started.add(stage)
            context.workflow_stage = _active_workflow_stage(project_root)
            if (
                session is not None
                and context.selected_session_id == session.session_id
            ):
                context.selected_session_id = None
            project_root = context.active_project_root
        return {
            **self.services.contexts.project_payload(context_id),
            "status": "skipped" if skip_approval else "approved",
            "next_stage": context.workflow_stage,
            "output": output,
            "warning": warning,
        }

    def _mark_generic_stage_completed(
        self,
        context_id: str,
        stage: str,
        returncode: int,
    ) -> None:
        if returncode != 0:
            return
        with self.services.contexts.lock:
            try:
                context = self.services.contexts.require(context_id)
            except StateError:
                return
            context.stage_started.add(stage)
            project_root = context.active_project_root
            if project_root is not None:
                context.workflow_stage = _active_workflow_stage(project_root)

    def _mark_design_review_completed(
        self,
        context_id: str,
        returncode: int,
    ) -> None:
        if returncode != 0:
            return
        with self.services.contexts.lock:
            try:
                context = self.services.contexts.require(context_id)
            except StateError:
                return
            if context.workflow_stage == "design-review":
                context.design_review_started = True
