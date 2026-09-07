"""Same-origin HTTP and WebSocket relay for private IDE Unix sockets."""

from __future__ import annotations

import secrets
import select
import socket
import time
from dataclasses import dataclass
from http.cookies import SimpleCookie
from pathlib import Path
from threading import RLock
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .domain import IDEEndpoint, IDEError, IDEErrorCategory
from .sandbox import IDEEgressMode, ide_content_security_policy

_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
_PRIVATE_QUERY_KEYS = {
    "context_id",
    "workspace_id",
    "connection_id",
    "lease_token",
    "telemetry_page_id",
    "telemetry_tab_id",
    "tkn",
}


@dataclass(frozen=True)
class IDEProxySession:
    token: str
    workspace_id: str
    expires_at: float


class IDEProxySessionStore:
    """Bounded browser sessions that never expose provider credentials."""

    cookie_name = "electroboy_ide_session"

    def __init__(self, *, limit: int = 32, ttl: float = 3600) -> None:
        self.limit = max(1, limit)
        self.ttl = max(60, ttl)
        self._sessions: dict[str, IDEProxySession] = {}
        self._lock = RLock()

    def create(self, workspace_id: str) -> IDEProxySession:
        now = time.time()
        with self._lock:
            self._remove_expired(now)
            while len(self._sessions) >= self.limit:
                oldest = min(self._sessions.values(), key=lambda row: row.expires_at)
                self._sessions.pop(oldest.token, None)
            session = IDEProxySession(
                token=secrets.token_urlsafe(32),
                workspace_id=workspace_id,
                expires_at=now + self.ttl,
            )
            self._sessions[session.token] = session
            return session

    def authorize(self, cookie_header: str, workspace_id: str) -> bool:
        cookie = SimpleCookie()
        try:
            cookie.load(cookie_header or "")
        except Exception:
            return False
        morsel = cookie.get(self.cookie_name)
        if morsel is None:
            return False
        now = time.time()
        with self._lock:
            self._remove_expired(now)
            session = self._sessions.get(morsel.value)
            return bool(session and session.workspace_id == workspace_id)

    def revoke_workspace(self, workspace_id: str) -> None:
        with self._lock:
            for token, session in list(self._sessions.items()):
                if session.workspace_id == workspace_id:
                    self._sessions.pop(token, None)

    def cookie(self, session: IDEProxySession, workspace_id: str) -> str:
        return (
            f"{self.cookie_name}={session.token}; Path=/ide/{workspace_id}/; "
            "HttpOnly; SameSite=Strict"
        )

    def _remove_expired(self, now: float) -> None:
        for token, session in list(self._sessions.items()):
            if session.expires_at <= now:
                self._sessions.pop(token, None)


class ProxyRequestHandler(Protocol):
    command: str
    path: str
    headers: object
    rfile: object
    wfile: object
    connection: socket.socket

    def send_response(self, code: int, message: str | None = None) -> None: ...

    def send_header(self, keyword: str, value: str) -> None: ...

    def end_headers(self) -> None: ...


class IDEUnixProxy:
    """Relay one browser request to a token-protected Unix endpoint."""

    def __init__(self, egress_mode: IDEEgressMode) -> None:
        self.egress_mode = egress_mode

    def relay(
        self,
        handler: ProxyRequestHandler,
        endpoint: IDEEndpoint,
        *,
        set_cookie: str | None = None,
        egress_mode: IDEEgressMode | None = None,
        report_uri: str = "",
    ) -> None:
        if endpoint.transport != "unix":
            raise IDEError(
                IDEErrorCategory.INTERNAL,
                f"unsupported IDE proxy transport: {endpoint.transport}",
            )
        backend = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        backend.settimeout(10)
        try:
            backend.connect(str(Path(endpoint.address)))
            upgrade = str(handler.headers.get("Upgrade", "")).lower() == "websocket"
            request = self._request_bytes(handler, endpoint, upgrade)
            backend.sendall(request)
            response_head, remainder = _read_response_head(backend)
            status, reason, headers = _parse_response_head(response_head)
            self._send_response_headers(
                handler,
                status,
                reason,
                headers,
                set_cookie=set_cookie,
                websocket=upgrade and status == 101,
                egress_mode=egress_mode,
                report_uri=report_uri,
            )
            if remainder:
                handler.wfile.write(remainder)
                handler.wfile.flush()
            if upgrade and status == 101:
                self._relay_websocket(handler.connection, backend)
            else:
                self._relay_body(handler, backend)
        finally:
            backend.close()

    def _request_bytes(
        self,
        handler: ProxyRequestHandler,
        endpoint: IDEEndpoint,
        websocket: bool,
    ) -> bytes:
        path = _provider_path(handler.path)
        lines = [f"{handler.command} {path} HTTP/1.1"]
        for name, value in handler.headers.items():
            lower = name.lower()
            if lower in {"host", "cookie"}:
                continue
            if not websocket and lower in _HOP_HEADERS:
                continue
            lines.append(f"{name}: {value}")
        lines.append("Host: localhost")
        lines.append(f"Cookie: vscode-tkn={endpoint.connection_token}")
        if not websocket:
            lines.append("Connection: close")
        lines.extend(("", ""))
        body = b""
        content_length = int(handler.headers.get("Content-Length", "0") or 0)
        if content_length:
            body = handler.rfile.read(content_length)
        return "\r\n".join(lines).encode("latin-1") + body

    def _send_response_headers(
        self,
        handler: ProxyRequestHandler,
        status: int,
        reason: str,
        headers: list[tuple[str, str]],
        *,
        set_cookie: str | None,
        websocket: bool,
        egress_mode: IDEEgressMode | None,
        report_uri: str,
    ) -> None:
        handler.send_response(status, reason)
        for name, value in headers:
            lower = name.lower()
            if lower in {
                "content-security-policy",
                "content-security-policy-report-only",
            }:
                continue
            if lower == "set-cookie":
                continue
            if not websocket and lower in _HOP_HEADERS - {"transfer-encoding"}:
                continue
            handler.send_header(name, value)
        csp_name, csp_value = ide_content_security_policy(
            egress_mode or self.egress_mode,
            report_uri=report_uri,
        )
        handler.send_header(csp_name, csp_value)
        if set_cookie:
            handler.send_header("Set-Cookie", set_cookie)
        handler.send_header("X-Content-Type-Options", "nosniff")
        handler.end_headers()

    @staticmethod
    def _relay_body(handler: ProxyRequestHandler, backend: socket.socket) -> None:
        while True:
            chunk = backend.recv(64 * 1024)
            if not chunk:
                return
            handler.wfile.write(chunk)
            handler.wfile.flush()

    @staticmethod
    def _relay_websocket(browser: socket.socket, backend: socket.socket) -> None:
        backend.settimeout(None)
        browser.settimeout(None)
        sockets = (browser, backend)
        while True:
            readable, _writable, exceptional = select.select(sockets, [], sockets, 30)
            if exceptional:
                return
            if not readable:
                continue
            for source in readable:
                data = source.recv(64 * 1024)
                if not data:
                    return
                target = backend if source is browser else browser
                target.sendall(data)


def _provider_path(path: str) -> str:
    parsed = urlsplit(path)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in _PRIVATE_QUERY_KEYS
    ]
    return urlunsplit(("", "", parsed.path, urlencode(query), ""))


def _read_response_head(backend: socket.socket) -> tuple[bytes, bytes]:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = backend.recv(16 * 1024)
        if not chunk:
            raise IDEError(
                IDEErrorCategory.START_FAILED,
                "IDE proxy received an incomplete provider response",
                recoverable=True,
            )
        data.extend(chunk)
        if len(data) > 1024 * 1024:
            raise IDEError(
                IDEErrorCategory.INTERNAL,
                "IDE provider response headers exceeded the proxy limit",
            )
    head, body = bytes(data).split(b"\r\n\r\n", 1)
    return head, body


def _parse_response_head(head: bytes) -> tuple[int, str, list[tuple[str, str]]]:
    lines = head.decode("latin-1").split("\r\n")
    status_parts = lines[0].split(" ", 2)
    if len(status_parts) < 2 or not status_parts[1].isdigit():
        raise IDEError(
            IDEErrorCategory.INTERNAL,
            "IDE provider returned an invalid HTTP status",
        )
    status = int(status_parts[1])
    reason = status_parts[2] if len(status_parts) > 2 else ""
    headers: list[tuple[str, str]] = []
    for line in lines[1:]:
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        headers.append((name.strip(), value.strip()))
    return status, reason, headers
