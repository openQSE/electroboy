"""Review report capability module declaration."""

from __future__ import annotations

import html
from http import HTTPStatus

from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest

from .common import route


def _view(request: RouteRequest) -> None:
    try:
        root = request.state.active_project_root(request.context_id)
        page, status = request.operation("design_review_document_html", root)
    except Exception as error:
        request.send_text(
            f"<p>{html.escape(str(error))}</p>",
            "text/html; charset=utf-8",
            status=HTTPStatus.CONFLICT,
        )
        return
    request.send_text(page, "text/html; charset=utf-8", status=status)


def module() -> ServiceModule:
    return ServiceModule(
        id="review_reports",
        label="Review Reports",
        routes=(route("GET", "/artifacts/design-review", "review_reports", "view"),),
        handlers={"view": _view},
        capabilities=frozenset({"review-summary", "issue-metadata"}),
        state_namespace="review_reports",
    )
