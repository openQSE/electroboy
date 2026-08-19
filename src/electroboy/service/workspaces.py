"""Durable ElectroBoy workspace registry and browser attachments."""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from .context import BrowserContext, ContextStore
from .sessions import AgentSession

WORKSPACE_RECORDS_RELATIVE_PATH = (
    Path(".electroboy") / "service" / "workspaces.json"
)
WORKSPACE_POLICY_EXCLUSIVE = "exclusive"
WORKSPACE_POLICY_SHARED_SINGLETON = "shared-singleton"
WORKSPACE_POLICIES = frozenset(
    {WORKSPACE_POLICY_EXCLUSIVE, WORKSPACE_POLICY_SHARED_SINGLETON}
)
WORKSPACE_LEASE_SECONDS = 20.0


def _now() -> float:
    return time.time()


def _json_value(value: object) -> object:
    if isinstance(value, AgentSession):
        raise TypeError("live agent sessions are not workspace metadata")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, set):
        return {
            "__electroboy_type__": "set",
            "items": [_json_value(v) for v in value],
        }
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, item in value.items():
            try:
                result[str(key)] = _json_value(item)
            except TypeError:
                continue
        return result
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            try:
                result.append(_json_value(item))
            except TypeError:
                continue
        return result
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    raise TypeError(f"unsupported workspace metadata: {type(value).__name__}")


def _restore_value(value: object) -> object:
    if isinstance(value, dict):
        if value.get("__electroboy_type__") == "set":
            items = value.get("items")
            return {
                _restore_value(item)
                for item in (items if isinstance(items, list) else [])
            }
        return {str(key): _restore_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_restore_value(item) for item in value]
    return value


@dataclass
class WorkspaceConnection:
    """One browser connection attached to a workspace."""

    connection_id: str
    lease_token: str
    heartbeat_at: float = field(default_factory=_now)
    state: dict[str, dict[str, object]] = field(default_factory=dict)

    def namespace(self, namespace: str) -> dict[str, object]:
        """Return state private to this browser connection and namespace."""

        return self.state.setdefault(namespace, {})

    def payload(self) -> dict[str, object]:
        return {
            "connection_id": self.connection_id,
            "lease_token": self.lease_token,
            "heartbeat_at": self.heartbeat_at,
        }


@dataclass
class WorkspaceRecord:
    """Persisted identity and attachment metadata for one workspace."""

    workspace_id: str
    name: str = ""
    workflow_id: str = ""
    project_kind: str = "none"
    project_identity: str = ""
    owner_key: str = ""
    attachment_policy: str = WORKSPACE_POLICY_EXCLUSIVE
    status: str = "draft"
    created_at: float = field(default_factory=_now)
    updated_at: float = field(default_factory=_now)
    last_attached_at: float = 0.0
    connections: dict[str, WorkspaceConnection] = field(default_factory=dict)

    def expire_connections(self, now: float, timeout: float) -> None:
        self.connections = {
            connection_id: connection
            for connection_id, connection in self.connections.items()
            if now - connection.heartbeat_at <= timeout
        }
        if self.status != "closed" and not self.connections:
            self.status = (
                "detached" if self.project_identity or self.owner_key else "draft"
            )

    def payload(self, context: BrowserContext | None = None) -> dict[str, object]:
        active_root = context.active_project_root if context is not None else None
        return {
            "workspace_id": self.workspace_id,
            "name": self.name,
            "workflow_id": self.workflow_id,
            "project_kind": self.project_kind,
            "project_identity": self.project_identity,
            "active_project_root": str(active_root) if active_root else None,
            "attachment_policy": self.attachment_policy,
            "status": self.status,
            "attached": bool(self.connections),
            "connection_count": len(self.connections),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_attached_at": self.last_attached_at,
        }


class WorkspaceRegistry:
    """Own durable workspace identity, persistence, and browser leases."""

    def __init__(
        self,
        state_root: Path | str,
        context_store: ContextStore,
        *,
        lease_seconds: float = WORKSPACE_LEASE_SECONDS,
    ) -> None:
        self.state_root = Path(state_root).expanduser().resolve()
        self.context_store = context_store
        self.lock: threading.RLock = context_store.lock
        self.lease_seconds = lease_seconds
        self.records: dict[str, WorkspaceRecord] = {}
        self._load()

    @property
    def path(self) -> Path:
        return self.state_root / WORKSPACE_RECORDS_RELATIVE_PATH

    def _load(self) -> None:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return
        entries = payload.get("workspaces", []) if isinstance(payload, dict) else []
        if not isinstance(entries, list):
            return
        with self.lock:
            for entry in entries:
                if not isinstance(entry, dict):
                    continue
                workspace_id = str(entry.get("workspace_id") or "").strip()
                if not workspace_id:
                    continue
                policy = str(
                    entry.get("attachment_policy")
                    or WORKSPACE_POLICY_EXCLUSIVE
                )
                if policy not in WORKSPACE_POLICIES:
                    policy = WORKSPACE_POLICY_EXCLUSIVE
                record = WorkspaceRecord(
                    workspace_id=workspace_id,
                    name=str(entry.get("name") or ""),
                    workflow_id=str(entry.get("workflow_id") or ""),
                    project_kind=str(entry.get("project_kind") or "none"),
                    project_identity=str(entry.get("project_identity") or ""),
                    owner_key=str(entry.get("owner_key") or ""),
                    attachment_policy=policy,
                    status="detached",
                    created_at=float(entry.get("created_at") or _now()),
                    updated_at=float(entry.get("updated_at") or _now()),
                    last_attached_at=float(entry.get("last_attached_at") or 0.0),
                )
                context = self.context_store.get_or_create(
                    workspace_id,
                    workflow_id=record.workflow_id,
                )
                context.workflow_id = record.workflow_id
                context.project_mode = str(entry.get("project_mode") or "none")
                activation_root = str(entry.get("activation_root") or "")
                active_root = str(entry.get("active_project_root") or "")
                context.activation_root = Path(activation_root) if activation_root else None
                context.active_project_root = Path(active_root) if active_root else None
                context.active_repository_name = (
                    str(entry.get("active_repository_name"))
                    if entry.get("active_repository_name")
                    else None
                )
                repositories = entry.get("registered_repositories")
                context.registered_repositories = (
                    list(repositories) if isinstance(repositories, list) else []
                )
                workflow_state = _restore_value(entry.get("workflow_state", {}))
                module_state = _restore_value(entry.get("module_state", {}))
                context.workflow_state = (
                    workflow_state if isinstance(workflow_state, dict) else {}
                )
                context.module_state = (
                    module_state if isinstance(module_state, dict) else {}
                )
                context.selected_session_id = (
                    str(entry.get("selected_session_id"))
                    if entry.get("selected_session_id")
                    else None
                )
                self.records[workspace_id] = record

    def _record_payload(self, record: WorkspaceRecord) -> dict[str, object]:
        context = self.context_store.get(record.workspace_id)
        payload = record.payload(context)
        payload.pop("attached", None)
        payload.pop("connection_count", None)
        if context is None:
            return payload
        payload.update(
            {
                "project_mode": context.project_mode,
                "activation_root": (
                    str(context.activation_root) if context.activation_root else None
                ),
                "active_project_root": (
                    str(context.active_project_root)
                    if context.active_project_root
                    else None
                ),
                "active_repository_name": context.active_repository_name,
                "registered_repositories": _json_value(
                    context.registered_repositories
                ),
                "selected_session_id": context.selected_session_id,
                "workflow_state": _json_value(context.workflow_state),
                "module_state": _json_value(context.module_state),
            }
        )
        return payload

    def _save_locked(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": 1,
            "workspaces": [
                self._record_payload(record)
                for record in self.records.values()
                if record.status != "draft"
            ],
        }
        temporary = self.path.with_suffix(f"{self.path.suffix}.{uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.path)

    def _expire_locked(self) -> None:
        now = _now()
        for record in self.records.values():
            record.expire_connections(now, self.lease_seconds)

    def create_draft(
        self,
        *,
        workflow_id: str,
        connection_id: str = "",
    ) -> tuple[BrowserContext, str]:
        with self.lock:
            context = self.context_store.create(workflow_id=workflow_id)
            record = WorkspaceRecord(
                workspace_id=context.context_id,
                workflow_id=workflow_id,
            )
            self.records[context.context_id] = record
            token = ""
            if connection_id:
                token = self._attach_locked(record, connection_id)
            return context, token

    def adopt_context(
        self,
        context: BrowserContext,
        *,
        name: str = "",
        project_identity: str = "",
    ) -> WorkspaceRecord:
        with self.lock:
            record = self.records.setdefault(
                context.context_id,
                WorkspaceRecord(
                    workspace_id=context.context_id,
                    workflow_id=context.workflow_id,
                ),
            )
            record.workflow_id = context.workflow_id
            if name:
                record.name = name
            if project_identity:
                record.project_identity = project_identity
                record.status = "detached" if not record.connections else "attached"
            record.updated_at = _now()
            self._save_locked()
            return record

    def reserve_project(
        self,
        current_workspace_id: str,
        *,
        workflow_id: str,
        project_kind: str,
        project_identity: str,
        name: str,
    ) -> tuple[BrowserContext, bool]:
        identity = str(Path(project_identity).expanduser().resolve())
        with self.lock:
            self._expire_locked()
            current = self.context_store.require(current_workspace_id)
            current_record = self.records.setdefault(
                current_workspace_id,
                WorkspaceRecord(
                    workspace_id=current_workspace_id,
                    workflow_id=workflow_id,
                ),
            )
            existing = next(
                (
                    record
                    for record in self.records.values()
                    if record.status != "closed"
                    and record.workflow_id == workflow_id
                    and record.project_identity == identity
                ),
                None,
            )
            if existing is not None and existing.workspace_id != current_workspace_id:
                if existing.connections:
                    raise ValueError(
                        f"workspace is already in use: {existing.name or name}"
                    )
                existing.connections = current_record.connections
                existing.status = "attached" if existing.connections else "detached"
                existing.last_attached_at = _now() if existing.connections else 0.0
                existing.updated_at = _now()
                self.records.pop(current_workspace_id, None)
                self.context_store.contexts.pop(current_workspace_id, None)
                self._save_locked()
                return self.context_store.require(existing.workspace_id), True
            current_record.name = name
            current_record.workflow_id = workflow_id
            current_record.project_kind = project_kind
            current_record.project_identity = identity
            current_record.attachment_policy = WORKSPACE_POLICY_EXCLUSIVE
            current_record.status = (
                "attached" if current_record.connections else "detached"
            )
            current_record.updated_at = _now()
            return current, False

    def resolve_shared_singleton(
        self,
        current_workspace_id: str,
        *,
        workflow_id: str,
        owner_key: str,
        name: str,
        connection_id: str,
    ) -> tuple[BrowserContext, str, bool]:
        if not owner_key:
            raise ValueError("workspace owner is required")
        with self.lock:
            self._expire_locked()
            current_record = self.records.get(current_workspace_id)
            existing = next(
                (
                    record
                    for record in self.records.values()
                    if record.status != "closed"
                    and record.workflow_id == workflow_id
                    and record.owner_key == owner_key
                    and record.attachment_policy == WORKSPACE_POLICY_SHARED_SINGLETON
                ),
                None,
            )
            created = existing is None
            if existing is None:
                context = self.context_store.get(current_workspace_id)
                if context is None:
                    context = self.context_store.create(workflow_id=workflow_id)
                existing = WorkspaceRecord(
                    workspace_id=context.context_id,
                    name=name,
                    workflow_id=workflow_id,
                    project_kind="singleton",
                    project_identity=f"{workflow_id}:{owner_key}",
                    owner_key=owner_key,
                    attachment_policy=WORKSPACE_POLICY_SHARED_SINGLETON,
                )
                self.records[context.context_id] = existing
            elif (
                current_record is not None
                and current_record.workspace_id != existing.workspace_id
            ):
                current_record.connections.pop(connection_id, None)
                if not current_record.connections and current_record.status == "draft":
                    self.records.pop(current_record.workspace_id, None)
                    self.context_store.contexts.pop(current_record.workspace_id, None)
            token = self._attach_locked(existing, connection_id)
            existing.name = name or existing.name
            existing.updated_at = _now()
            self._save_locked()
            return self.context_store.require(existing.workspace_id), token, created

    def _attach_locked(self, record: WorkspaceRecord, connection_id: str) -> str:
        if not connection_id:
            raise ValueError("browser connection id is required")
        self._expire_locked()
        if (
            record.attachment_policy == WORKSPACE_POLICY_EXCLUSIVE
            and record.connections
            and connection_id not in record.connections
        ):
            raise ValueError(
                f"workspace is already in use: {record.name or record.workspace_id}"
            )
        connection = record.connections.get(connection_id)
        if connection is None:
            connection = WorkspaceConnection(connection_id, uuid4().hex)
            record.connections[connection_id] = connection
        else:
            connection.heartbeat_at = _now()
        record.status = "attached"
        record.last_attached_at = _now()
        record.updated_at = _now()
        return connection.lease_token

    def attach(self, workspace_id: str, connection_id: str) -> dict[str, object]:
        with self.lock:
            record = self.require_record(workspace_id)
            token = self._attach_locked(record, connection_id)
            self._save_locked()
            return {
                **record.payload(self.context_store.get(workspace_id)),
                "lease_token": token,
            }

    def switch(
        self,
        current_workspace_id: str,
        target_workspace_id: str,
        connection_id: str,
        lease_token: str,
    ) -> dict[str, object]:
        with self.lock:
            target = self.require_record(target_workspace_id)
            if target.attachment_policy == WORKSPACE_POLICY_SHARED_SINGLETON:
                raise ValueError(
                    "shared workspace attachment requires workflow authentication"
                )
            current = self.records.get(current_workspace_id)
            if current is not None and current.workspace_id != target.workspace_id:
                connection = current.connections.get(connection_id)
                if connection is None or connection.lease_token != lease_token:
                    raise ValueError(
                        "current workspace is not attached to this browser connection"
                    )
            elif current is target and connection_id in target.connections:
                connection = target.connections[connection_id]
                if connection.lease_token != lease_token:
                    raise ValueError(
                        "workspace lease does not belong to this browser connection"
                    )
            token = self._attach_locked(target, connection_id)
            if current is not None and current.workspace_id != target.workspace_id:
                current.connections.pop(connection_id, None)
                current.expire_connections(_now(), self.lease_seconds)
                current.updated_at = _now()
            self._save_locked()
            return {
                **target.payload(self.context_store.get(target_workspace_id)),
                "lease_token": token,
            }

    def detach(
        self,
        workspace_id: str,
        connection_id: str,
        lease_token: str,
    ) -> dict[str, object]:
        with self.lock:
            record = self.require_record(workspace_id)
            connection = record.connections.get(connection_id)
            if connection is None or connection.lease_token != lease_token:
                raise ValueError(
                    "workspace is not attached to this browser connection"
                )
            record.connections.pop(connection_id, None)
            record.expire_connections(_now(), self.lease_seconds)
            record.updated_at = _now()
            self._save_locked()
            return record.payload(self.context_store.get(workspace_id))

    def heartbeat(
        self,
        workspace_id: str,
        connection_id: str,
        lease_token: str,
    ) -> dict[str, object]:
        with self.lock:
            record = self.require_record(workspace_id)
            connection = record.connections.get(connection_id)
            if connection is None or connection.lease_token != lease_token:
                raise ValueError("workspace is not attached to this browser connection")
            connection.heartbeat_at = _now()
            record.updated_at = _now()
            return record.payload(self.context_store.get(workspace_id))

    def validate(
        self,
        workspace_id: str,
        connection_id: str,
        lease_token: str,
    ) -> None:
        if not workspace_id:
            raise ValueError("workspace id is required")
        with self.lock:
            self._expire_locked()
            record = self.require_record(workspace_id)
            connection = record.connections.get(connection_id)
            if connection is None or connection.lease_token != lease_token:
                raise ValueError("workspace is not attached to this browser connection")

    def close(
        self,
        workspace_id: str,
        connection_id: str = "",
        lease_token: str = "",
    ) -> None:
        with self.lock:
            record = self.require_record(workspace_id)
            if connection_id:
                connection = record.connections.get(connection_id)
                if connection is None or connection.lease_token != lease_token:
                    raise ValueError(
                        "workspace is not attached to this browser connection"
                    )
            record.connections.clear()
            record.status = "closed"
            record.updated_at = _now()
            self._save_locked()

    def persist(self, workspace_id: str) -> None:
        with self.lock:
            record = self.records.get(workspace_id)
            if record is None:
                return
            record.updated_at = _now()
            self._save_locked()

    def save_client_state(
        self,
        workspace_id: str,
        state: dict[str, object],
    ) -> dict[str, object]:
        with self.lock:
            context = self.context_store.require(workspace_id)
            normalized = _json_value(state)
            if not isinstance(normalized, dict):
                raise ValueError("workspace client state must be an object")
            context.module("core")["client_state"] = normalized
            record = self.require_record(workspace_id)
            record.updated_at = _now()
            self._save_locked()
            return dict(normalized)

    def connection_state(
        self,
        workspace_id: str,
        connection_id: str,
        namespace: str,
    ) -> dict[str, object]:
        """Return mutable state isolated to one attached browser connection."""

        if not namespace:
            raise ValueError("connection-state namespace is required")
        with self.lock:
            record = self.require_record(workspace_id)
            connection = record.connections.get(connection_id)
            if connection is None:
                raise ValueError(
                    "workspace is not attached to this browser connection"
                )
            return connection.namespace(namespace)

    def client_state(self, workspace_id: str) -> dict[str, object]:
        with self.lock:
            context = self.context_store.require(workspace_id)
            state = context.module("core").get("client_state")
            return dict(state) if isinstance(state, dict) else {}

    def list_detached(
        self,
        *,
        workflow_id: str = "",
        owner_key: str = "",
    ) -> list[dict[str, object]]:
        with self.lock:
            self._expire_locked()
            rows = []
            for record in self.records.values():
                if record.status != "detached" or record.connections:
                    continue
                if record.attachment_policy != WORKSPACE_POLICY_EXCLUSIVE:
                    continue
                if workflow_id and record.workflow_id != workflow_id:
                    continue
                if owner_key and record.owner_key != owner_key:
                    continue
                rows.append(record.payload(self.context_store.get(record.workspace_id)))
            return sorted(
                rows,
                key=lambda row: float(row.get("updated_at") or 0.0),
                reverse=True,
            )

    def require_record(self, workspace_id: str) -> WorkspaceRecord:
        try:
            return self.records[workspace_id]
        except KeyError as error:
            raise KeyError(f"unknown workspace: {workspace_id}") from error

    def metadata(self, workspace_id: str) -> dict[str, object]:
        with self.lock:
            record = self.require_record(workspace_id)
            return record.payload(self.context_store.get(workspace_id))
