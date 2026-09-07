"""Versioned file transport for the ElectroBoy IDE bridge extension."""

from __future__ import annotations

import json
import secrets
import threading
import uuid
from dataclasses import dataclass
from pathlib import Path

from .domain import (
    IDEEditorContext,
    IDEError,
    IDEErrorCategory,
    IDEInstance,
    IDELocation,
    IDEProfile,
    IDEWorkspace,
)

BRIDGE_PROTOCOL_VERSION = 1


@dataclass(frozen=True)
class IDEBridgeRegistration:
    protocol_version: int
    workspace_id: str
    instance_id: str
    secret: str
    directory: Path


class IDEBridge:
    """Exchange authenticated context and commands through an isolated profile."""

    def __init__(self, *, response_timeout: float = 10.0) -> None:
        self.response_timeout = max(0.1, response_timeout)
        self._registrations: dict[str, IDEBridgeRegistration] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._lock = threading.RLock()

    def prepare(
        self,
        profile: IDEProfile,
        workspace: IDEWorkspace,
        instance_id: str,
    ) -> IDEBridgeRegistration:
        directory = profile.root / "bridge"
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        registration = IDEBridgeRegistration(
            protocol_version=BRIDGE_PROTOCOL_VERSION,
            workspace_id=workspace.workspace_id,
            instance_id=instance_id,
            secret=secrets.token_urlsafe(32),
            directory=directory,
        )
        _write_json(
            directory / "registration.json",
            {
                "protocol_version": BRIDGE_PROTOCOL_VERSION,
                "workspace_id": workspace.workspace_id,
                "instance_id": instance_id,
                "project_root": str(workspace.project_root),
                "secret": registration.secret,
            },
        )
        for name in ("commands.jsonl", "responses.jsonl", "input-events.jsonl"):
            (directory / name).write_text("", encoding="utf-8")
            (directory / name).chmod(0o600)
        (directory / "context.json").unlink(missing_ok=True)
        with self._lock:
            self._registrations[instance_id] = registration
            self._locks.setdefault(instance_id, threading.Lock())
        return registration

    def settings(self, registration: IDEBridgeRegistration) -> dict[str, object]:
        return {
            "electroboy.bridge.directory": str(registration.directory),
        }

    def open_location(self, instance: IDEInstance, location: IDELocation) -> str:
        registration = self._registration(instance)
        request_id = uuid.uuid4().hex
        command = {
            **self._envelope(registration),
            "request_id": request_id,
            "command": "open_location",
            "location": {
                "path": location.path,
                "line": location.line,
                "column": location.column,
                "end_line": location.end_line,
                "end_column": location.end_column,
                "symbol": location.symbol,
            },
        }
        lock = self._locks[instance.instance_id]
        with lock:
            _append_jsonl(registration.directory / "commands.jsonl", command)
        return request_id

    def diagnostics(self, instance: IDEInstance) -> dict[str, object]:
        registration = self._registration(instance)
        commands = [
            record
            for record in _read_jsonl(registration.directory / "commands.jsonl")
            if self._authenticated(record, registration)
        ]
        responses = [
            record
            for record in _read_jsonl(registration.directory / "responses.jsonl")
            if self._authenticated(record, registration)
        ]
        completed = {
            str(response.get("request_id") or "") for response in responses
        }
        input_events = [
            _public_input_event(record)
            for record in _read_jsonl(
                registration.directory / "input-events.jsonl"
            )
            if self._authenticated(record, registration)
        ]
        return {
            "protocol_version": registration.protocol_version,
            "registered": True,
            "queued_command_count": len(commands),
            "completed_command_count": len(responses),
            "pending_command_count": sum(
                1
                for command in commands
                if str(command.get("request_id") or "") not in completed
            ),
            "recent_results": [
                {
                    "request_id": str(response.get("request_id") or ""),
                    "ok": bool(response.get("ok")),
                }
                for response in responses[-10:]
            ],
            "input_event_count": len(input_events),
            "recent_input_events": input_events[-100:],
        }

    def record_input_event(
        self,
        instance: IDEInstance,
        payload: dict[str, object],
    ) -> dict[str, object]:
        """Record sanitized browser-side input metadata for correlation."""

        registration = self._registration(instance)
        event = {
            **self._envelope(registration),
            **_sanitize_browser_input_event(payload),
        }
        lock = self._locks[instance.instance_id]
        with lock:
            _append_bounded_jsonl(
                registration.directory / "input-events.jsonl",
                event,
            )
        return _public_input_event(event)

    def context(self, instance: IDEInstance) -> IDEEditorContext | None:
        registration = self._registration(instance)
        payload = _read_json(registration.directory / "context.json")
        if not self._authenticated(payload, registration):
            return None
        cursor = (
            payload.get("cursor")
            if isinstance(payload.get("cursor"), dict)
            else {}
        )
        selection = (
            payload.get("selection")
            if isinstance(payload.get("selection"), dict)
            else {}
        )
        start = (
            selection.get("start")
            if isinstance(selection.get("start"), dict)
            else {}
        )
        end = selection.get("end") if isinstance(selection.get("end"), dict) else {}
        return IDEEditorContext(
            workspace_id=registration.workspace_id,
            path=_optional_text(payload.get("path")),
            language=_optional_text(payload.get("language")),
            cursor_line=_optional_int(cursor.get("line")),
            cursor_column=_optional_int(cursor.get("column")),
            selection_start_line=_optional_int(start.get("line")),
            selection_start_column=_optional_int(start.get("column")),
            selection_end_line=_optional_int(end.get("line")),
            selection_end_column=_optional_int(end.get("column")),
            dirty=bool(payload.get("dirty")),
            revision=max(0, _optional_int(payload.get("revision")) or 0),
        )

    def unregister(self, instance_id: str) -> None:
        with self._lock:
            self._registrations.pop(instance_id, None)
            self._locks.pop(instance_id, None)

    def _registration(self, instance: IDEInstance) -> IDEBridgeRegistration:
        with self._lock:
            registration = self._registrations.get(instance.instance_id)
        if registration is None:
            raise IDEError(
                IDEErrorCategory.NAVIGATION_FAILED,
                "the IDE bridge is not registered",
                recoverable=True,
            )
        if registration.workspace_id != instance.workspace.workspace_id:
            raise IDEError(
                IDEErrorCategory.WORKSPACE_CONFLICT,
                "the IDE bridge registration belongs to another workspace",
            )
        return registration

    @staticmethod
    def _envelope(registration: IDEBridgeRegistration) -> dict[str, object]:
        return {
            "protocol_version": registration.protocol_version,
            "workspace_id": registration.workspace_id,
            "instance_id": registration.instance_id,
            "auth": registration.secret,
        }

    @staticmethod
    def _authenticated(
        payload: dict[str, object],
        registration: IDEBridgeRegistration,
    ) -> bool:
        return (
            payload.get("protocol_version") == registration.protocol_version
            and payload.get("workspace_id") == registration.workspace_id
            and payload.get("instance_id") == registration.instance_id
            and secrets.compare_digest(
                str(payload.get("auth") or ""),
                registration.secret,
            )
        )


def _write_json(path: Path, payload: dict[str, object]) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(payload, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def _append_jsonl(path: Path, payload: dict[str, object]) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, separators=(",", ":")) + "\n")


def _append_bounded_jsonl(
    path: Path,
    payload: dict[str, object],
    *,
    maximum_records: int = 500,
) -> None:
    _append_jsonl(path, payload)
    if path.stat().st_size <= 500_000:
        return
    retained = _read_jsonl(path)[-maximum_records:]
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        "".join(
            f"{json.dumps(record, separators=(',', ':'))}\n"
            for record in retained
        ),
        encoding="utf-8",
    )
    temporary.chmod(0o600)
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    records: list[dict[str, object]] = []
    for line in lines:
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _sanitize_browser_input_event(payload: dict[str, object]) -> dict[str, object]:
    event_type = str(payload.get("event_type") or "unknown")
    if event_type not in {"frame-focus", "frame-blur", "keydown", "keyup", "pointerdown"}:
        event_type = "unknown"
    key_group = str(payload.get("key_group") or "")
    if key_group not in {"navigation", "editing", "modifier", "function", "printable", "other"}:
        key_group = ""
    named_key = str(payload.get("named_key") or "")
    if len(named_key) > 24 or len(named_key) == 1:
        named_key = ""
    modifiers = payload.get("modifiers")
    if not isinstance(modifiers, dict):
        modifiers = {}
    return {
        "source": "browser",
        "event_type": event_type,
        "sequence": max(0, _optional_int(payload.get("sequence")) or 0),
        "occurred_at": str(payload.get("occurred_at") or "")[:40],
        "editor_mode": (
            "neovim" if payload.get("editor_mode") == "neovim" else "standard"
        ),
        "key_group": key_group or None,
        "named_key": named_key or None,
        "vim_motion": bool(payload.get("vim_motion")),
        "repeat": bool(payload.get("repeat")),
        "default_prevented": bool(payload.get("default_prevented")),
        "frame_has_focus": bool(payload.get("frame_has_focus")),
        "target_kind": str(payload.get("target_kind") or "")[:24] or None,
        "modifiers": {
            name: bool(modifiers.get(name))
            for name in ("alt", "control", "meta", "shift")
        },
    }


def _public_input_event(payload: dict[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in payload.items()
        if key not in {"auth", "workspace_id", "instance_id", "protocol_version"}
    }


def _optional_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _optional_int(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
