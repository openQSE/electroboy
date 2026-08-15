"""Review report capability module declaration."""

from __future__ import annotations

import html
from http import HTTPStatus

from electroboy.service.http import HtmlResponse, JsonResponse
from electroboy.service.registry import ServiceModule
from electroboy.service.routes import RouteRequest

from .common import route
from .document_service import design_review_document_html
from .review_service import review_report_index, review_report_index_html


def _view(request: RouteRequest) -> HtmlResponse:
    try:
        root = request.state.active_project_root(request.context_id)
        page, status = design_review_document_html(root)
    except Exception as error:
        return HtmlResponse(
            f"<p>{html.escape(str(error))}</p>",
            status=HTTPStatus.CONFLICT,
        )
    return HtmlResponse(page, status=status)


def _index(request: RouteRequest) -> JsonResponse:
    root = request.state.active_project_root(request.context_id)
    return JsonResponse(review_report_index(root))


def _category(request: RouteRequest) -> HtmlResponse:
    root = request.state.active_project_root(request.context_id)
    category = request.path.removeprefix("/artifacts/").removesuffix("-reviews")
    return HtmlResponse(review_report_index_html(root, category))


def module() -> ServiceModule:
    return ServiceModule(
        id="review_reports",
        label="Review Reports",
        routes=(
            route("GET", "/artifacts/design-review", "review_reports", "view"),
            route("GET", "/api/reviews", "review_reports", "index"),
            route("GET", "/artifacts/code-reviews", "review_reports", "category"),
            route("GET", "/artifacts/test-reviews", "review_reports", "category"),
            route(
                "GET",
                "/artifacts/validation-reviews",
                "review_reports",
                "category",
            ),
        ),
        handlers={"view": _view, "index": _index, "category": _category},
        capabilities=frozenset({"review-summary", "issue-metadata"}),
        state_namespace="review_reports",
    )
