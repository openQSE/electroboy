from __future__ import annotations

import socket
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import urlencode

from electroboy.ide import IDEEndpoint
from electroboy.ide.proxy import IDEProxySessionStore, IDEUnixProxy
from electroboy.ide.sandbox import IDEEgressMode
from electroboy.service import create_server


class UnixProvider:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.requests: list[bytes] = []
        self.stop = threading.Event()
        self.socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.socket.bind(str(path))
        self.socket.listen()
        self.socket.settimeout(0.1)
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()

    def run(self) -> None:
        while not self.stop.is_set():
            try:
                connection, _address = self.socket.accept()
            except TimeoutError:
                continue
            with connection:
                request = read_until(connection, b"\r\n\r\n")
                self.requests.append(request)
                if b"Upgrade: websocket" in request:
                    connection.sendall(
                        b"HTTP/1.1 101 Switching Protocols\r\n"
                        b"Upgrade: websocket\r\n"
                        b"Connection: Upgrade\r\n\r\n"
                    )
                    data = connection.recv(4096)
                    if data:
                        connection.sendall(data)
                    continue
                body = b"<html><body>IDE</body></html>"
                connection.sendall(
                    b"HTTP/1.1 200 OK\r\n"
                    + f"Content-Length: {len(body)}\r\n".encode()
                    + b"Content-Type: text/html\r\n"
                    + b"Content-Security-Policy: connect-src https:; "
                    + b"script-src 'self' 'sha256-dGVzdA==' https://unsafe.example\r\n"
                    + b"Set-Cookie: provider_token=secret\r\n"
                    + b"Connection: close\r\n\r\n"
                    + body
                )

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=2)
        self.socket.close()


class ProxyIDEService:
    def __init__(self, endpoint: IDEEndpoint) -> None:
        self.endpoint = endpoint
        self.proxy_sessions = IDEProxySessionStore()
        self.proxy = IDEUnixProxy(IDEEgressMode.DENY)
        self.reports: list[object] = []

    def proxy_endpoint(self, workspace_id: str) -> IDEEndpoint:
        del workspace_id
        return self.endpoint

    def proxy_egress_mode(self, workspace_id: str) -> IDEEgressMode:
        del workspace_id
        return IDEEgressMode.DENY

    def record_csp_violation(
        self,
        payload: object,
        workspace_id: str = "",
    ) -> dict[str, object]:
        self.reports.append((workspace_id, payload))
        return {"status": "recorded"}

    def close(self) -> None:
        return


class IDEProxyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.provider = UnixProvider(self.root / "provider.sock")
        self.server = create_server(self.root, port=0, state_root=self.root / "state")
        assert self.server.service_state is not None
        self.state = self.server.service_state
        self.state.ide_service = ProxyIDEService(
            IDEEndpoint("unix", str(self.provider.path), "provider-secret")
        )
        context = self.state.create_context("tab-1", "software")
        self.workspace_id = str(context["workspace_id"])
        self.query = urlencode(
            {
                "workspace_id": self.workspace_id,
                "context_id": self.workspace_id,
                "connection_id": "tab-1",
                "lease_token": str(context["lease_token"]),
            }
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.thread.join(timeout=2)
        self.server.server_close()
        self.provider.close()
        self.temporary.cleanup()

    def test_initial_request_sets_private_session_and_strips_credentials(self) -> None:
        host, port = self.server.server_address[:2]
        client = socket.create_connection((host, port), timeout=3)
        with client:
            client.sendall(
                f"GET /ide/{self.workspace_id}/?{self.query} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\nConnection: close\r\n\r\n".encode()
            )
            response = read_all(client)

        self.assertIn(b"200 OK", response)
        self.assertIn(b"Set-Cookie: electroboy_ide_session=", response)
        self.assertIn(b"Content-Security-Policy: default-src 'self'", response)
        self.assertIn(b"'sha256-dGVzdA=='", response)
        self.assertNotIn(b"https://unsafe.example", response)
        self.assertIn(
            f"report-uri /ide/{self.workspace_id}/_electroboy/csp-report".encode(),
            response,
        )
        self.assertNotIn(b"provider_token", response)
        self.assertNotIn(b"provider-secret", response)
        backend_request = self.provider.requests[-1]
        self.assertIn(b"Cookie: vscode-tkn=provider-secret", backend_request)
        self.assertNotIn(b"tkn=provider-secret", backend_request.split(b"\r\n", 1)[0])
        self.assertNotIn(b"lease_token", backend_request)

    def test_session_cookie_authorizes_subresources_without_lease_query(self) -> None:
        first = self.http_request(f"/ide/{self.workspace_id}/?{self.query}")
        cookie = next(
            line.split(b";", 1)[0]
            for line in first.split(b"\r\n")
            if line.startswith(b"Set-Cookie: ")
        ).removeprefix(b"Set-Cookie: ")

        second = self.http_request(
            f"/ide/{self.workspace_id}/static/app.js",
            headers=[b"Cookie: " + cookie],
        )

        self.assertIn(b"200 OK", second)
        self.assertIn(b"/ide/", self.provider.requests[-1])

    def test_missing_lease_and_cookie_is_rejected(self) -> None:
        response = self.http_request(f"/ide/{self.workspace_id}/")
        self.assertIn(b"409 Conflict", response)
        self.assertNotIn(b"provider-secret", response)

    def test_authenticated_csp_reports_are_recorded_without_relay(self) -> None:
        first = self.http_request(f"/ide/{self.workspace_id}/?{self.query}")
        cookie = next(
            line.split(b";", 1)[0]
            for line in first.split(b"\r\n")
            if line.startswith(b"Set-Cookie: ")
        ).removeprefix(b"Set-Cookie: ")
        body = b'{"csp-report":{"blocked-uri":"https://example.com/private"}}'
        response = self.raw_request(
            "POST",
            f"/ide/{self.workspace_id}/_electroboy/csp-report",
            body=body,
            headers=[
                b"Cookie: " + cookie,
                b"Content-Type: application/csp-report",
            ],
        )

        self.assertIn(b"200 OK", response)
        service = self.state.ide_service
        self.assertEqual(len(service.reports), 1)
        self.assertEqual(len(self.provider.requests), 1)

    def test_websocket_upgrade_relays_bidirectionally(self) -> None:
        host, port = self.server.server_address[:2]
        client = socket.create_connection((host, port), timeout=3)
        with client:
            client.sendall(
                f"GET /ide/{self.workspace_id}/ws?{self.query} HTTP/1.1\r\n"
                f"Host: {host}:{port}\r\n"
                "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                "Sec-WebSocket-Key: dGVzdA==\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n".encode()
            )
            response = read_until(client, b"\r\n\r\n")
            self.assertIn(b"101 Switching Protocols", response)
            client.sendall(b"websocket-frame")
            self.assertEqual(client.recv(4096), b"websocket-frame")

    def http_request(self, path: str, headers: list[bytes] | None = None) -> bytes:
        return self.raw_request("GET", path, headers=headers)

    def raw_request(
        self,
        method: str,
        path: str,
        *,
        body: bytes = b"",
        headers: list[bytes] | None = None,
    ) -> bytes:
        host, port = self.server.server_address[:2]
        client = socket.create_connection((host, port), timeout=3)
        with client:
            lines = [
                f"{method} {path} HTTP/1.1".encode(),
                f"Host: {host}:{port}".encode(),
                *(headers or []),
                f"Content-Length: {len(body)}".encode(),
                b"Connection: close",
                b"",
                b"",
            ]
            client.sendall(b"\r\n".join(lines) + body)
            return read_all(client)


def read_until(stream: socket.socket, marker: bytes) -> bytes:
    data = bytearray()
    while marker not in data:
        chunk = stream.recv(4096)
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def read_all(stream: socket.socket) -> bytes:
    data = bytearray()
    while True:
        chunk = stream.recv(4096)
        if not chunk:
            return bytes(data)
        data.extend(chunk)


if __name__ == "__main__":
    unittest.main()
