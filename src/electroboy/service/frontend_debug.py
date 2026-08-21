"""Bounded frontend diagnostic logging."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path


FRONTEND_DEBUG_TOTAL_LOG_LIMIT_BYTES = 500_000_000
FRONTEND_DEBUG_LOG_SEGMENT_LIMIT_BYTES = (
    FRONTEND_DEBUG_TOTAL_LOG_LIMIT_BYTES // 2
)
FRONTEND_DEBUG_PAYLOAD_LIMIT_BYTES = 40_000
FRONTEND_DEBUG_LOG_NAME = "frontend-debug.jsonl"
FRONTEND_DEBUG_PREVIOUS_LOG_NAME = "frontend-debug.previous.jsonl"

_FRONTEND_DEBUG_LOG_LOCK = threading.Lock()


def frontend_debug_log_path(state_root: Path) -> Path:
    """Return the active frontend diagnostic log path."""

    return state_root / ".electroboy" / "service" / FRONTEND_DEBUG_LOG_NAME


def append_frontend_debug_payload(
    state_root: Path,
    payload: dict[str, object],
) -> None:
    """Append one entry while retaining at most two bounded log segments."""

    entry = {
        "received_at": time.time(),
        "payload": payload,
    }
    encoded = (json.dumps(entry, sort_keys=True, default=str) + "\n").encode(
        "utf-8"
    )
    log_path = frontend_debug_log_path(state_root)
    previous_path = log_path.with_name(FRONTEND_DEBUG_PREVIOUS_LOG_NAME)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with _FRONTEND_DEBUG_LOG_LOCK:
        current_size = log_path.stat().st_size if log_path.exists() else 0
        if current_size and (
            current_size + len(encoded) > FRONTEND_DEBUG_LOG_SEGMENT_LIMIT_BYTES
        ):
            previous_path.unlink(missing_ok=True)
            log_path.replace(previous_path)
        with log_path.open("ab") as handle:
            handle.write(encoded)
