"""Secret redaction helpers."""

from __future__ import annotations


SECRET_MARKERS = ("KEY", "TOKEN", "SECRET", "PASSWORD")


def redact_environment(env: dict[str, str]) -> dict[str, str]:
    """Return an environment mapping with likely secrets redacted."""

    redacted: dict[str, str] = {}
    for name, value in env.items():
        if any(marker in name.upper() for marker in SECRET_MARKERS):
            redacted[name] = "<redacted>"
        else:
            redacted[name] = value
    return redacted
