from __future__ import annotations

import http.client
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.cli import build_parser  # noqa: E402
from electroboy.service import INDEX_HTML, create_server  # noqa: E402


class ServiceTests(unittest.TestCase):
    def test_health_endpoint_reports_connected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type = request(server, "/api/health")
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        payload = json.loads(body)
        self.assertEqual(payload["status"], "connected")
        self.assertEqual(payload["service"], "electroboy")
        self.assertEqual(payload["root"], str(root.resolve()))

    def test_index_page_fetches_health_and_prints_connected(self) -> None:
        self.assertIn('fetch("/api/health"', INDEX_HTML)
        self.assertIn('document.body.textContent = "connected";', INDEX_HTML)

    def test_serve_accepts_subcommand_root_argument(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["serve", "--root", "/tmp/example", "--port", "0"])

        self.assertEqual(args.command, "serve")
        self.assertEqual(args.root, "/tmp/example")
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 0)


def request(
    server: object,
    path: str,
) -> tuple[int, str, str]:
    host, port = server.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=2)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        content_type = response.getheader("Content-Type", "")
    finally:
        connection.close()
    return response.status, body, content_type


if __name__ == "__main__":
    unittest.main()
