"""Review report capability module declaration."""

from __future__ import annotations

from electroboy.service.registry import ServiceModule

from .common import route


def module() -> ServiceModule:
    return ServiceModule(
        id="review_reports",
        label="Review Reports",
        routes=(route("GET", "/artifacts/design-review", "review_reports", "view"),),
        capabilities=frozenset({"review-summary", "issue-metadata"}),
        state_namespace="review_reports",
    )

