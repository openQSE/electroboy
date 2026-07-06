"""Secret redaction helpers."""

from __future__ import annotations

import re


SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD")
SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*\s*=\s*)\S+"
)


def redact_environment(env: dict[str, str]) -> dict[str, str]:
    """Return an environment mapping with likely secrets redacted."""

    redacted: dict[str, str] = {}
    for name, value in env.items():
        if any(marker in name.upper() for marker in SECRET_MARKERS):
            redacted[name] = "<redacted>"
        else:
            redacted[name] = value
    return redacted


def redact_value(value: object) -> object:
    """Redact likely secrets from nested JSON-compatible values."""

    if isinstance(value, dict):
        redacted: dict[object, object] = {}
        for key, item in value.items():
            key_text = str(key).upper()
            if any(marker in key_text for marker in SECRET_MARKERS):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_value(item)
        return redacted
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_value(item) for item in value)
    if isinstance(value, str):
        return SECRET_ASSIGNMENT.sub(r"\1<redacted>", value)
    return value
