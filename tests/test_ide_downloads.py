from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from pathlib import Path

from electroboy.ide import IDEError
from electroboy.ide.downloads import AuditedDownloadClient


class Response(io.BytesIO):
    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()


class IDEDownloadTests(unittest.TestCase):
    def test_verified_download_records_only_bounded_metadata(self) -> None:
        content = b"managed artifact"
        client = AuditedDownloadClient(
            open_url=lambda *_args, **_kwargs: Response(content)
        )
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "artifact"
            client.download(
                artifact_id="test-artifact",
                url="https://example.test/private/path?token=secret",
                destination=destination,
                sha256=hashlib.sha256(content).hexdigest(),
                size=len(content),
            )

        event = client.events()[0]
        self.assertEqual(event["source"], "https://example.test")
        self.assertEqual(event["status"], "verified")
        self.assertNotIn("token", json_text(event))
        self.assertNotIn("managed artifact", json_text(event))

    def test_bad_checksum_is_reported_without_sensitive_content(self) -> None:
        client = AuditedDownloadClient(
            open_url=lambda *_args, **_kwargs: Response(b"wrong")
        )
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(IDEError):
                client.download(
                    artifact_id="test-artifact",
                    url="https://example.test/file",
                    destination=Path(temporary) / "artifact",
                    sha256="0" * 64,
                    size=5,
                )

        self.assertEqual(client.events()[0]["status"], "failed")


def json_text(value: object) -> str:
    import json

    return json.dumps(value, sort_keys=True)


if __name__ == "__main__":
    unittest.main()
