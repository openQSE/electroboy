"""Public provider contract for workflow-backed agendas."""

from __future__ import annotations

from datetime import date, datetime
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from electroboy.state_store import StateError

AGENDA_SECTION_IDS = (
    "needs-attention",
    "today",
    "tomorrow",
    "this-week",
    "later",
    "unscheduled",
)
AGENDA_SECTION_LABELS = {
    "needs-attention": "Needs Attention",
    "today": "Today",
    "tomorrow": "Tomorrow",
    "this-week": "This Week",
    "later": "Later",
    "unscheduled": "Unscheduled",
}


class AgendaProvider(Protocol):
    """Translate workflow-owned records into generic agenda operations."""

    provider_id: str

    def load_agenda(
        self,
        context_id: str,
        *,
        filters: dict[str, str],
        visible_range: dict[str, str],
        connection_id: str = "",
    ) -> dict[str, object]: ...

    def invoke_agenda_action(
        self,
        context_id: str,
        payload: dict[str, object],
        *,
        connection_id: str = "",
    ) -> dict[str, object]: ...

    def load_agenda_editor(
        self,
        context_id: str,
        payload: dict[str, object],
        *,
        connection_id: str = "",
    ) -> dict[str, object]: ...

    def submit_agenda_editor(
        self,
        context_id: str,
        payload: dict[str, object],
        *,
        connection_id: str = "",
    ) -> dict[str, object]: ...


@runtime_checkable
class AgendaWorkflowController(Protocol):
    """Structural controller capability consumed by the Agenda module."""

    def get_agenda_provider(self) -> AgendaProvider: ...


def _timezone(name: object) -> ZoneInfo:
    value = str(name or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise StateError(f"unknown agenda timezone: {value}") from error


def _timestamp(value: object, label: str) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise StateError(f"agenda item {label} must be an ISO timestamp") from error
    return text


def _records(value: object, label: str) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise StateError(f"agenda item {label} must be a list of objects")
    return [dict(item) for item in value]


def _actions(value: object) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise StateError("agenda item actions must be a list")
    actions: list[dict[str, object]] = []
    for action in value:
        if isinstance(action, str):
            action_id = action.strip()
            normalized = {"id": action_id, "label": action_id.replace("-", " ").title()}
        elif isinstance(action, dict):
            action_id = str(action.get("id") or "").strip()
            normalized = {
                **action,
                "id": action_id,
                "label": str(
                    action.get("label") or action_id.replace("-", " ").title()
                ),
            }
        else:
            raise StateError("agenda item action must be a string or object")
        if not action_id:
            raise StateError("agenda item action id is required")
        actions.append(normalized)
    return actions


def _normalize_item(item: object, index: int) -> dict[str, object]:
    if not isinstance(item, dict):
        raise StateError(f"agenda item {index + 1} must be an object")
    item_id = str(item.get("id") or "").strip()
    title = str(item.get("title") or "").strip()
    kind = str(item.get("kind") or "item").strip().lower()
    if not item_id:
        raise StateError(f"agenda item {index + 1} id is required")
    if not title:
        raise StateError(f"agenda item {index + 1} title is required")
    if not kind:
        raise StateError(f"agenda item {index + 1} kind is required")
    confidence = item.get("confidence")
    if confidence is not None:
        try:
            confidence = float(confidence)
        except (TypeError, ValueError) as error:
            raise StateError("agenda item confidence must be numeric") from error
        if not 0 <= confidence <= 1:
            raise StateError("agenda item confidence is out of range")
    filter_values = item.get("filter_values")
    if filter_values is None:
        filter_values = {}
    if not isinstance(filter_values, dict):
        raise StateError("agenda item filter values must be an object")
    return {
        **item,
        "id": item_id,
        "version": int(item.get("version") or 1),
        "kind": kind,
        "title": title,
        "status": str(item.get("status") or "open").strip().lower(),
        "start_at": _timestamp(item.get("start_at"), "start_at"),
        "end_at": _timestamp(item.get("end_at"), "end_at"),
        "due_at": _timestamp(item.get("due_at"), "due_at"),
        "date_only": bool(item.get("date_only", False)),
        "confidence": confidence,
        "participants": _records(item.get("participants"), "participants"),
        "assignees": _records(item.get("assignees"), "assignees"),
        "metadata": _records(item.get("metadata"), "metadata"),
        "badges": [str(value) for value in item.get("badges", [])],
        "actions": _actions(item.get("actions")),
        "filter_values": {
            str(key): [str(entry) for entry in value]
            if isinstance(value, list)
            else [str(value)]
            for key, value in filter_values.items()
        },
    }


def _normalize_filters(value: object) -> list[dict[str, object]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise StateError("agenda filters must be a list")
    filters: list[dict[str, object]] = []
    for entry in value:
        if not isinstance(entry, dict):
            raise StateError("agenda filter must be an object")
        filter_id = str(entry.get("id") or "").strip()
        options = entry.get("options")
        if not filter_id or not isinstance(options, list):
            raise StateError("agenda filter id and options are required")
        normalized_options = []
        for option in options:
            if not isinstance(option, dict):
                raise StateError("agenda filter option must be an object")
            option_value = str(option.get("value") or "").strip()
            if not option_value:
                raise StateError("agenda filter option value is required")
            normalized_options.append(
                {
                    **option,
                    "value": option_value,
                    "label": str(option.get("label") or option_value),
                }
            )
        selected = str(entry.get("value") or normalized_options[0]["value"]).strip()
        if selected not in {str(option["value"]) for option in normalized_options}:
            selected = str(normalized_options[0]["value"])
        filters.append(
            {
                **entry,
                "id": filter_id,
                "label": str(entry.get("label") or filter_id.replace("-", " ").title()),
                "value": selected,
                "options": normalized_options,
            }
        )
    return filters


def _item_datetime(item: dict[str, object], timezone: ZoneInfo) -> datetime | None:
    value = item.get("start_at") or item.get("due_at")
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _section_id(
    item: dict[str, object],
    *,
    today: date,
    timezone: ZoneInfo,
) -> str:
    status = str(item.get("status") or "")
    item_time = _item_datetime(item, timezone)
    needs_attention = bool(item.get("attention") or item.get("warning")) or status in {
        "needs_attention",
        "needs_review",
        "error",
        "overdue",
    }
    if item_time is not None and item_time.date() < today and status not in {
        "complete",
        "completed",
        "cancelled",
    }:
        needs_attention = True
    if needs_attention:
        return "needs-attention"
    if item_time is None:
        return "unscheduled"
    difference = (item_time.date() - today).days
    if difference == 0:
        return "today"
    if difference == 1:
        return "tomorrow"
    if difference <= 7:
        return "this-week"
    return "later"


def normalize_agenda_snapshot(
    payload: dict[str, object],
    *,
    provider_id: str,
    now: datetime | None = None,
) -> dict[str, object]:
    """Validate provider data and group each agenda item exactly once."""

    title = str(payload.get("title") or "").strip()
    if not title:
        raise StateError("agenda title is required")
    items = payload.get("items")
    if not isinstance(items, list):
        raise StateError("agenda items must be a list")
    timezone = _timezone(payload.get("timezone"))
    reference = now or datetime.now(timezone)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone)
    today = reference.astimezone(timezone).date()
    normalized_items = [
        _normalize_item(item, index) for index, item in enumerate(items)
    ]
    grouped: dict[str, list[dict[str, object]]] = {
        section_id: [] for section_id in AGENDA_SECTION_IDS
    }
    for item in normalized_items:
        grouped[_section_id(item, today=today, timezone=timezone)].append(item)
    for section_items in grouped.values():
        section_items.sort(
            key=lambda item: (
                _item_datetime(item, timezone) or datetime.max.replace(tzinfo=timezone),
                str(item["title"]).casefold(),
                str(item["id"]),
            )
        )
    return {
        **payload,
        "schema_version": 1,
        "provider": provider_id,
        "title": title,
        "timezone": timezone.key,
        "reference_date": today.isoformat(),
        "filters": _normalize_filters(payload.get("filters")),
        "items": normalized_items,
        "sections": [
            {
                "id": section_id,
                "label": AGENDA_SECTION_LABELS[section_id],
                "items": grouped[section_id],
            }
            for section_id in AGENDA_SECTION_IDS
            if grouped[section_id]
        ],
        "capabilities": [str(value) for value in payload.get("capabilities", [])],
    }
