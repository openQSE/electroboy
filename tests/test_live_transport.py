from __future__ import annotations

import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.service import AgentSession, create_server  # noqa: E402
from electroboy.service.frontend import read_service_text_asset  # noqa: E402
from electroboy.service.live_transport import (  # noqa: E402
    valid_event_stream_path,
    websocket_accept_value,
)


def send_websocket_json(connection: socket.socket, payload: object) -> None:
    data = json.dumps(payload).encode("utf-8")
    mask = os.urandom(4)
    if len(data) < 126:
        header = bytes((0x81, 0x80 | len(data)))
    else:
        header = bytes((0x81, 0x80 | 126)) + struct.pack("!H", len(data))
    masked = bytes(value ^ mask[index % 4] for index, value in enumerate(data))
    connection.sendall(header + mask + masked)


def read_exact(connection: socket.socket, length: int) -> bytes:
    data = bytearray()
    while len(data) < length:
        chunk = connection.recv(length - len(data))
        if not chunk:
            raise ConnectionError("WebSocket closed")
        data.extend(chunk)
    return bytes(data)


def read_websocket_json(connection: socket.socket) -> dict[str, object]:
    first, second = read_exact(connection, 2)
    if first & 0x0F != 0x1:
        raise AssertionError(f"expected text frame, received opcode {first & 0x0F}")
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", read_exact(connection, 2))[0]
    elif length == 127:
        length = struct.unpack("!Q", read_exact(connection, 8))[0]
    return json.loads(read_exact(connection, length))


def open_websocket(server: object) -> socket.socket:
    host, port = server.server_address[:2]
    connection = socket.create_connection((host, port), timeout=2)
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    request = (
        "GET /api/live HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"Origin: http://{host}:{port}\r\n"
        "Upgrade: websocket\r\n"
        "Connection: keep-alive, Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\n"
        "Sec-WebSocket-Version: 13\r\n"
        "\r\n"
    )
    connection.sendall(request.encode("ascii"))
    response = bytearray()
    while b"\r\n\r\n" not in response:
        response.extend(connection.recv(4096))
    expected_accept = websocket_accept_value(key)
    headers = response.decode("ascii")
    if not headers.startswith("HTTP/1.1 101 Switching Protocols\r\n"):
        raise AssertionError(headers)
    if f"Sec-WebSocket-Accept: {expected_accept}\r\n" not in headers:
        raise AssertionError(headers)
    return connection


class LiveTransportTests(unittest.TestCase):
    def test_one_websocket_multiplexes_multiple_workspace_event_streams(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            workspaces = [
                server.service_state.create_context("connection-1"),
                server.service_state.create_context("connection-2"),
            ]
            for index, workspace in enumerate(workspaces, start=1):
                session = AgentSession(
                    [sys.executable, "-c", "pass"],
                    root,
                    session_id=f"session-{index}",
                )
                session._append_event({"type": "system", "text": f"message-{index}"})
                with server.service_state.lock:
                    context = server.service_state._context_locked(
                        str(workspace["workspace_id"])
                    )
                    context.ad_hoc_session = session
                    context.selected_session_id = session.session_id
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = open_websocket(server)

            try:
                for index, workspace in enumerate(workspaces, start=1):
                    path = "/api/sessions/events?" + urlencode(
                        {
                            "workspace_id": workspace["workspace_id"],
                            "connection_id": f"connection-{index}",
                            "lease_token": workspace["lease_token"],
                        }
                    )
                    send_websocket_json(
                        connection,
                        {
                            "type": "subscribe",
                            "subscription_id": f"subscription-{index}",
                            "path": path,
                        },
                    )
                messages = [read_websocket_json(connection) for _ in range(4)]
            finally:
                connection.close()
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        events = [message for message in messages if message["type"] == "event"]
        self.assertEqual(
            {message["subscription_id"] for message in events},
            {"subscription-1", "subscription-2"},
        )
        payloads = [json.loads(str(message["data"])) for message in events]
        self.assertEqual(
            {payload["session_id"] for payload in payloads},
            {"session-1", "session-2"},
        )

    def test_subscription_paths_are_limited_to_registered_event_routes(self) -> None:
        def registered(path: str) -> bool:
            return path == "/api/sessions/events"

        self.assertEqual(
            valid_event_stream_path(
                "/api/sessions/events?workspace_id=one",
                registered,
            ),
            "/api/sessions/events?workspace_id=one",
        )
        self.assertIsNone(
            valid_event_stream_path(
                "https://example.com/api/sessions/events",
                registered,
            )
        )
        self.assertIsNone(valid_event_stream_path("/api/health", registered))
        self.assertIsNone(valid_event_stream_path("/api/unknown/events", registered))

    def test_pages_load_the_shared_live_transport(self) -> None:
        index = read_service_text_asset("index.html")
        pane_window = read_service_text_asset("pane-window.html")
        runtime = read_service_text_asset("js/core/runtime.js")
        transport = read_service_text_asset("js/core/live-transport.js")
        worker = read_service_text_asset("js/core/live-transport-worker.js")

        self.assertIn("/assets/service/js/core/live-transport.js", index)
        self.assertIn("/assets/service/js/core/live-transport.js", pane_window)
        self.assertNotIn("new EventSource", runtime)
        self.assertNotIn("new EventSource", pane_window)
        self.assertIn("new SharedWorker", transport)
        self.assertIn("pageWebSocketManager", transport)
        self.assertIn("const subscriptions = new Map();", worker)
        self.assertIn("new WebSocket(socketUrl())", worker)

    @unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
    def test_shared_worker_uses_one_socket_for_two_browser_ports(self) -> None:
        worker_path = (
            ROOT / "src/electroboy/assets/service/js/core/live-transport-worker.js"
        )
        script = r"""
global.setInterval = () => 0;
global.self = { location: { protocol: "http:", host: "127.0.0.1:8765" } };
class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static instances = [];
  constructor(url) {
    this.url = url;
    this.readyState = FakeWebSocket.CONNECTING;
    this.listeners = {};
    this.sent = [];
    FakeWebSocket.instances.push(this);
  }
  addEventListener(type, listener) { this.listeners[type] = listener; }
  send(message) { this.sent.push(JSON.parse(message)); }
  emit(type, event = {}) { this.listeners[type]?.(event); }
  close() {}
}
global.WebSocket = FakeWebSocket;
require(process.argv[1]);
function subscribe(clientId, subscriptionId) {
  const port = { listeners: {}, messages: [] };
  port.addEventListener = (type, listener) => { port.listeners[type] = listener; };
  port.start = () => {};
  port.postMessage = (message) => port.messages.push(message);
  self.onconnect({ ports: [port] });
  port.listeners.message({ data: {
    type: "subscribe",
    client_id: clientId,
    subscription_id: subscriptionId,
    path: `/api/sessions/events?workspace_id=${clientId}`,
  } });
}
subscribe("tab-1", "subscription-1");
subscribe("tab-2", "subscription-2");
if (FakeWebSocket.instances.length !== 1) {
  throw new Error(`expected one socket, got ${FakeWebSocket.instances.length}`);
}
const socket = FakeWebSocket.instances[0];
socket.readyState = FakeWebSocket.OPEN;
socket.emit("open");
if (socket.sent.length !== 2) {
  throw new Error(`expected two subscriptions, got ${socket.sent.length}`);
}
"""

        completed = subprocess.run(
            [str(shutil.which("node")), "-e", script, str(worker_path)],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    unittest.main()
