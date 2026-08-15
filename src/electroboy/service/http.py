"""Typed HTTP responses returned by registered service routes."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from http import HTTPStatus


@dataclass(frozen=True)
class JsonResponse:
    payload: dict[str, object]
    status: HTTPStatus = HTTPStatus.OK


@dataclass(frozen=True)
class HtmlResponse:
    body: str
    status: HTTPStatus = HTTPStatus.OK


@dataclass(frozen=True)
class TextResponse:
    body: str
    status: HTTPStatus = HTTPStatus.OK
    content_type: str = "text/plain; charset=utf-8"


@dataclass(frozen=True)
class BinaryResponse:
    data: bytes
    content_type: str
    filename: str | None = None
    status: HTTPStatus = HTTPStatus.OK


@dataclass(frozen=True)
class StreamResponse:
    stream: Callable[[], None]


ServiceResponse = (
    JsonResponse | HtmlResponse | TextResponse | BinaryResponse | StreamResponse
)
