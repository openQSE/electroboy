"""Shared WebSocket transport for browser event streams."""

from __future__ import annotations

import base64
import hashlib
import http.client
import json
import socket
import struct
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import BinaryIO
from urllib.parse import urlsplit

WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
MAX_WEBSOCKET_MESSAGE_BYTES = 1_048_576
MAX_SUBSCRIPTION_PATH_BYTES = 65_536


class WebSocketProtocolError(Exception):
    """Raised when a peer sends an invalid WebSocket frame."""


class WebSocketConnection:
    """Small RFC 6455 text-frame adapter for the local browser service."""

    def __init__(self, reader: BinaryIO, writer: BinaryIO) -> None:
        self._reader = reader
        self._writer = writer
        self._write_lock = threading.Lock()
        self._closed = False

    def send_json(self, payload: dict[str, object]) -> None:
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        self._send_frame(0x1, data)

    def receive_text(self) -> str | None:
        fragments = bytearray()
        text_message = False
        while not self._closed:
            fin, opcode, payload = self._read_frame()
            if opcode == 0x8:
                self.close(payload[:125])
                return None
            if opcode == 0x9:
                self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:
                continue
            if opcode == 0x1:
                if fragments:
                    raise WebSocketProtocolError("unexpected text frame")
                text_message = True
                fragments.extend(payload)
            elif opcode == 0x0 and text_message:
                fragments.extend(payload)
            else:
                raise WebSocketProtocolError("only text messages are supported")
            if len(fragments) > MAX_WEBSOCKET_MESSAGE_BYTES:
                raise WebSocketProtocolError("message is too large")
            if fin:
                try:
                    return fragments.decode("utf-8")
                except UnicodeDecodeError as error:
                    raise WebSocketProtocolError("message is not UTF-8") from error
        return None

    def close(self, payload: bytes = b"") -> None:
        if self._closed:
            return
        try:
            self._send_frame(0x8, payload)
        except OSError:
            pass
        self._closed = True

    def _read_frame(self) -> tuple[bool, int, bytes]:
        header = self._read_exact(2)
        first, second = header
        fin = bool(first & 0x80)
        opcode = first & 0x0F
        if first & 0x70:
            raise WebSocketProtocolError("reserved frame bits are set")
        if not second & 0x80:
            raise WebSocketProtocolError("client frames must be masked")
        length = second & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._read_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._read_exact(8))[0]
        if length > MAX_WEBSOCKET_MESSAGE_BYTES:
            raise WebSocketProtocolError("frame is too large")
        mask = self._read_exact(4)
        payload = bytearray(self._read_exact(length))
        for index in range(length):
            payload[index] ^= mask[index % 4]
        return fin, opcode, bytes(payload)

    def _read_exact(self, length: int) -> bytes:
        data = self._reader.read(length)
        if data is None or len(data) != length:
            raise ConnectionError("WebSocket connection closed")
        return data

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self._closed and opcode != 0x8:
            raise ConnectionError("WebSocket connection is closed")
        length = len(payload)
        if length < 126:
            header = bytes((0x80 | opcode, length))
        elif length <= 0xFFFF:
            header = bytes((0x80 | opcode, 126)) + struct.pack("!H", length)
        else:
            header = bytes((0x80 | opcode, 127)) + struct.pack("!Q", length)
        with self._write_lock:
            self._writer.write(header + payload)
            self._writer.flush()


@dataclass
class EventStreamRelay:
    """Relay one registered SSE route onto a shared WebSocket."""

    subscription_id: str
    path: str
    last_event_id: str
    server_address: tuple[str, int]
    send: Callable[[dict[str, object]], None] = field(repr=False)
    stopped: threading.Event = field(default_factory=threading.Event, repr=False)
    _connection: http.client.HTTPConnection | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _connection_lock: threading.Lock = field(
        default_factory=threading.Lock,
        init=False,
        repr=False,
    )
    _response: http.client.HTTPResponse | None = field(
        default=None,
        init=False,
        repr=False,
    )

    def run(self) -> None:
        retry_delay = 0.25
        while not self.stopped.is_set():
            try:
                self._stream_once()
                retry_delay = 0.25
            except (ConnectionError, OSError, http.client.HTTPException) as error:
                if self.stopped.is_set():
                    return
                self._notify_error(str(error) or error.__class__.__name__)
            finally:
                self._close_connection()
            if self.stopped.wait(retry_delay):
                return
            retry_delay = min(retry_delay * 2, 5.0)

    def stop(self) -> None:
        self.stopped.set()
        self._close_connection()

    def _stream_once(self) -> None:
        host, port = self.server_address
        connection = http.client.HTTPConnection(host, port, timeout=30)
        with self._connection_lock:
            if self.stopped.is_set():
                connection.close()
                return
            self._connection = connection
        headers = {"Accept": "text/event-stream"}
        if self.last_event_id:
            headers["Last-Event-ID"] = self.last_event_id
        connection.request("GET", self.path, headers=headers)
        response = connection.getresponse()
        with self._connection_lock:
            if self.stopped.is_set():
                response.close()
                return
            self._response = response
        if response.status != 200:
            body = response.read(512).decode("utf-8", errors="replace")
            self.send(
                {
                    "type": "error",
                    "subscription_id": self.subscription_id,
                    "status": response.status,
                    "message": body or response.reason,
                }
            )
            if 400 <= response.status < 500:
                self.stopped.set()
            return
        content_type = response.getheader("Content-Type", "")
        if "text/event-stream" not in content_type:
            raise ConnectionError("subscription did not return an event stream")
        self.send({"type": "open", "subscription_id": self.subscription_id})
        self._read_events(response)

    def _read_events(self, response: http.client.HTTPResponse) -> None:
        event_name = "message"
        data_lines: list[str] = []
        while not self.stopped.is_set():
            raw_line = response.readline()
            if not raw_line:
                raise ConnectionError("event stream closed")
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line:
                if data_lines:
                    self.send(
                        {
                            "type": "event",
                            "subscription_id": self.subscription_id,
                            "event": event_name,
                            "data": "\n".join(data_lines),
                            "last_event_id": self.last_event_id,
                        }
                    )
                event_name = "message"
                data_lines = []
                continue
            if line.startswith(":"):
                continue
            field_name, separator, value = line.partition(":")
            if separator and value.startswith(" "):
                value = value[1:]
            if field_name == "event":
                event_name = value or "message"
            elif field_name == "data":
                data_lines.append(value)
            elif field_name == "id" and "\x00" not in value:
                self.last_event_id = value

    def _notify_error(self, message: str) -> None:
        try:
            self.send(
                {
                    "type": "error",
                    "subscription_id": self.subscription_id,
                    "message": message,
                }
            )
        except (ConnectionError, OSError):
            self.stopped.set()

    def _close_connection(self) -> None:
        with self._connection_lock:
            connection = self._connection
            self._connection = None
            response = self._response
            self._response = None
        if response is not None:
            response.close()
        if connection is not None:
            connection.close()


def websocket_accept_value(key: str) -> str:
    """Return the RFC 6455 handshake value for a browser key."""

    digest = hashlib.sha1(f"{key}{WEBSOCKET_GUID}".encode()).digest()
    return base64.b64encode(digest).decode("ascii")


def valid_event_stream_path(
    value: object,
    route_exists: Callable[[str], bool],
) -> str | None:
    """Validate a same-service registered event-stream subscription path."""

    if not isinstance(value, str) or not value.startswith("/"):
        return None
    if len(value.encode("utf-8")) > MAX_SUBSCRIPTION_PATH_BYTES:
        return None
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        return None
    if not parsed.path.startswith("/api/") or not parsed.path.endswith("/events"):
        return None
    if not route_exists(parsed.path):
        return None
    return value


class LiveTransportSession:
    """Multiplex registered event streams over one WebSocket connection."""

    def __init__(
        self,
        websocket: WebSocketConnection,
        server_address: tuple[str, int],
        route_exists: Callable[[str], bool],
    ) -> None:
        self._websocket = websocket
        self._server_address = server_address
        self._route_exists = route_exists
        self._relays: dict[str, EventStreamRelay] = {}
        self._lock = threading.Lock()

    def run(self) -> None:
        try:
            while True:
                message = self._websocket.receive_text()
                if message is None:
                    return
                self._handle_message(message)
        except (ConnectionError, OSError, WebSocketProtocolError):
            return
        finally:
            self.close()

    def close(self) -> None:
        with self._lock:
            relays = list(self._relays.values())
            self._relays.clear()
        for relay in relays:
            relay.stop()
        self._websocket.close()

    def _handle_message(self, message: str) -> None:
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            self._send_error("", "message is not valid JSON")
            return
        if not isinstance(payload, dict):
            self._send_error("", "message must be an object")
            return
        message_type = payload.get("type")
        subscription_id = payload.get("subscription_id")
        if not isinstance(subscription_id, str) or not subscription_id:
            self._send_error("", "subscription_id is required")
            return
        if len(subscription_id) > 200:
            self._send_error("", "subscription_id is too long")
            return
        if message_type == "unsubscribe":
            self._unsubscribe(subscription_id)
            return
        if message_type != "subscribe":
            self._send_error(subscription_id, "unknown message type")
            return
        path = valid_event_stream_path(payload.get("path"), self._route_exists)
        if path is None:
            self._send_error(subscription_id, "invalid event stream path")
            return
        last_event_id = payload.get("last_event_id", "")
        if not isinstance(last_event_id, str) or len(last_event_id) > 16_384:
            self._send_error(subscription_id, "invalid last_event_id")
            return
        self._subscribe(subscription_id, path, last_event_id)

    def _subscribe(
        self,
        subscription_id: str,
        path: str,
        last_event_id: str,
    ) -> None:
        self._unsubscribe(subscription_id)
        relay = EventStreamRelay(
            subscription_id=subscription_id,
            path=path,
            last_event_id=last_event_id,
            server_address=self._server_address,
            send=self._websocket.send_json,
        )
        with self._lock:
            self._relays[subscription_id] = relay
        threading.Thread(
            target=self._run_relay,
            args=(relay,),
            daemon=True,
            name=f"live-event-{subscription_id[:24]}",
        ).start()

    def _run_relay(self, relay: EventStreamRelay) -> None:
        try:
            relay.run()
        finally:
            with self._lock:
                if self._relays.get(relay.subscription_id) is relay:
                    self._relays.pop(relay.subscription_id, None)

    def _unsubscribe(self, subscription_id: str) -> None:
        with self._lock:
            relay = self._relays.pop(subscription_id, None)
        if relay is not None:
            relay.stop()

    def _send_error(self, subscription_id: str, message: str) -> None:
        self._websocket.send_json(
            {
                "type": "error",
                "subscription_id": subscription_id,
                "message": message,
            }
        )


def websocket_server_address(address: tuple[object, ...]) -> tuple[str, int]:
    """Normalize a bound HTTP server address for an internal loopback relay."""

    host = str(address[0])
    if host in {"", "0.0.0.0", "::"}:
        host = "127.0.0.1"
    return host, int(address[1])


def websocket_upgrade_requested(headers: object) -> bool:
    """Return whether HTTP headers request an RFC 6455 upgrade."""

    get = getattr(headers, "get")
    upgrade = str(get("Upgrade", "")).lower()
    connection_tokens = {
        token.strip().lower() for token in str(get("Connection", "")).split(",")
    }
    return upgrade == "websocket" and "upgrade" in connection_tokens


def validate_websocket_origin(origin: str, host: str) -> bool:
    """Accept absent origins and same-host HTTP browser origins."""

    if not origin:
        return True
    parsed = urlsplit(origin)
    return parsed.scheme in {"http", "https"} and parsed.netloc == host


def configure_websocket_socket(connection: socket.socket) -> None:
    """Keep live connections responsive without imposing a read timeout."""

    connection.settimeout(None)
