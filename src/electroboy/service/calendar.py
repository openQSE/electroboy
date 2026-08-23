"""Public provider contract for workflow-backed calendar views."""

from __future__ import annotations

import calendar as calendar_lib
from datetime import date, datetime
from typing import Protocol, runtime_checkable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from electroboy.state_store import StateError

CALENDAR_COLORS = (
    "#2563eb",
    "#16a34a",
    "#dc2626",
    "#7c3aed",
    "#ea580c",
    "#0891b2",
    "#be123c",
    "#4f46e5",
)


class CalendarProvider(Protocol):
    """Translate workflow-owned records into generic calendar snapshots."""

    provider_id: str

    def load_calendar(
        self,
        context_id: str,
        *,
        calendar_ids: list[str],
        calendar_ids_explicit: bool = False,
        visible_range: dict[str, str],
        connection_id: str = "",
    ) -> dict[str, object]: ...


@runtime_checkable
class CalendarWorkflowController(Protocol):
    """Structural controller capability consumed by the Calendar module."""

    def get_calendar_provider(self) -> CalendarProvider: ...


def _timezone(name: object) -> ZoneInfo:
    value = str(name or "UTC").strip() or "UTC"
    try:
        return ZoneInfo(value)
    except ZoneInfoNotFoundError as error:
        raise StateError(f"unknown calendar timezone: {value}") from error


def _timestamp(value: object, label: str) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as error:
        raise StateError(f"calendar event {label} must be an ISO timestamp") from error
    return text


def _date(value: object, label: str) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    text = str(value).strip()
    try:
        date.fromisoformat(text)
    except ValueError as error:
        raise StateError(f"calendar event {label} must be an ISO date") from error
    return text


def _event_start_date(event: dict[str, object], timezone: ZoneInfo) -> date:
    start_date = event.get("start_date")
    if start_date:
        return date.fromisoformat(str(start_date))
    start_at = event.get("start_at")
    if start_at:
        parsed = datetime.fromisoformat(str(start_at).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone)
        return parsed.astimezone(timezone).date()
    return date.max


def _event_end_date(event: dict[str, object], timezone: ZoneInfo) -> date:
    end_date = event.get("end_date")
    if end_date:
        return date.fromisoformat(str(end_date))
    end_at = event.get("end_at")
    if end_at:
        parsed = datetime.fromisoformat(str(end_at).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone)
        return parsed.astimezone(timezone).date()
    return _event_start_date(event, timezone)


def _range_date(value: object, fallback: date) -> date:
    if value is None or str(value).strip() == "":
        return fallback
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError as error:
        raise StateError("calendar visible range must use ISO dates") from error


def _normalize_calendar(entry: object, index: int) -> dict[str, object]:
    if not isinstance(entry, dict):
        raise StateError(f"calendar {index + 1} must be an object")
    calendar_id = str(entry.get("id") or "").strip()
    label = str(entry.get("label") or entry.get("summary") or calendar_id).strip()
    if not calendar_id:
        raise StateError(f"calendar {index + 1} id is required")
    if not label:
        raise StateError(f"calendar {index + 1} label is required")
    color = str(entry.get("color") or CALENDAR_COLORS[index % len(CALENDAR_COLORS)])
    return {
        **entry,
        "id": calendar_id,
        "label": label,
        "color": color,
        "selected": bool(entry.get("selected", True)),
    }


def _normalize_event(
    entry: object,
    index: int,
    calendar_ids: set[str],
) -> dict[str, object]:
    if not isinstance(entry, dict):
        raise StateError(f"calendar event {index + 1} must be an object")
    event_id = str(entry.get("id") or "").strip()
    calendar_id = str(entry.get("calendar_id") or "").strip()
    title = str(entry.get("title") or "Untitled event").strip() or "Untitled event"
    if not event_id:
        raise StateError(f"calendar event {index + 1} id is required")
    if calendar_id not in calendar_ids:
        raise StateError(f"calendar event {event_id} has an unknown calendar")
    start_at = _timestamp(entry.get("start_at"), "start_at")
    end_at = _timestamp(entry.get("end_at"), "end_at")
    start_date = _date(entry.get("start_date"), "start_date")
    end_date = _date(entry.get("end_date"), "end_date")
    if not start_at and not start_date:
        raise StateError(f"calendar event {event_id} needs a start time or date")
    return {
        **entry,
        "id": event_id,
        "calendar_id": calendar_id,
        "title": title,
        "start_at": start_at,
        "end_at": end_at,
        "start_date": start_date,
        "end_date": end_date,
        "all_day": bool(entry.get("all_day") or start_date),
        "status": str(entry.get("status") or "").strip(),
        "description": str(entry.get("description") or "").strip(),
        "location": str(entry.get("location") or "").strip(),
        "metadata": [
            dict(item)
            for item in entry.get("metadata", [])
            if isinstance(item, dict)
        ],
    }


def _inside_range(
    event: dict[str, object],
    *,
    timezone: ZoneInfo,
    range_start: date,
    range_end: date,
) -> bool:
    event_start = _event_start_date(event, timezone)
    event_end = _event_end_date(event, timezone)
    if event_end < event_start:
        event_end = event_start
    return event_start <= range_end and event_end >= range_start


def normalize_calendar_snapshot(
    payload: dict[str, object],
    *,
    provider_id: str,
    now: datetime | None = None,
) -> dict[str, object]:
    """Validate provider data and sort visible calendar events."""

    title = str(payload.get("title") or "").strip()
    if not title:
        raise StateError("calendar title is required")
    calendars_value = payload.get("calendars")
    events_value = payload.get("events")
    if not isinstance(calendars_value, list):
        raise StateError("calendars must be a list")
    if not isinstance(events_value, list):
        raise StateError("calendar events must be a list")
    timezone = _timezone(payload.get("timezone"))
    reference = now or datetime.now(timezone)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone)
    today = reference.astimezone(timezone).date()
    calendars = [
        _normalize_calendar(entry, index)
        for index, entry in enumerate(calendars_value)
    ]
    calendar_ids = {str(calendar["id"]) for calendar in calendars}
    raw_selected_ids = payload.get("selected_calendar_ids")
    if raw_selected_ids is None:
        selected_ids = {
            str(calendar["id"]) for calendar in calendars if calendar["selected"]
        }
    else:
        selected_ids = {
            str(value)
            for value in raw_selected_ids
            if str(value).strip()
        }
    for calendar in calendars:
        calendar["selected"] = str(calendar["id"]) in selected_ids
    normalized_events = [
        _normalize_event(entry, index, calendar_ids)
        for index, entry in enumerate(events_value)
    ]
    window_start = _range_date(
        payload.get("range_start"),
        date(today.year, today.month, 1),
    )
    window_end = _range_date(
        payload.get("range_end"),
        date(
            window_start.year,
            window_start.month,
            calendar_lib.monthrange(window_start.year, window_start.month)[1],
        ),
    )
    visible_events = [
        event
        for event in normalized_events
        if str(event["calendar_id"]) in selected_ids
        and _inside_range(
            event,
            timezone=timezone,
            range_start=window_start,
            range_end=window_end,
        )
    ]
    visible_events.sort(
        key=lambda event: (
            _event_start_date(event, timezone),
            str(event.get("start_at") or ""),
            str(event["title"]).casefold(),
            str(event["id"]),
        )
    )
    return {
        **payload,
        "schema_version": 1,
        "provider": provider_id,
        "title": title,
        "timezone": timezone.key,
        "reference_date": today.isoformat(),
        "range_start": window_start.isoformat(),
        "range_end": window_end.isoformat(),
        "calendars": calendars,
        "selected_calendar_ids": sorted(selected_ids),
        "events": visible_events,
        "capabilities": [str(value) for value in payload.get("capabilities", [])],
    }
