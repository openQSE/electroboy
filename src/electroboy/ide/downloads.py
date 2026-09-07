"""Audited downloads shared by managed IDE artifacts."""

from __future__ import annotations

import hashlib
import time
import urllib.request
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO
from urllib.parse import urlsplit

from .domain import IDEError, IDEErrorCategory

OpenURL = Callable[..., BinaryIO]
DownloadProgress = Callable[[int, int], None]


class AuditedDownloadClient:
    """Download one pinned artifact while retaining payload-free metadata."""

    def __init__(
        self,
        *,
        open_url: OpenURL = urllib.request.urlopen,
        event_limit: int = 100,
    ) -> None:
        self.open_url = open_url
        self._events: deque[dict[str, object]] = deque(maxlen=max(1, event_limit))

    def download(
        self,
        *,
        artifact_id: str,
        url: str,
        destination: Path,
        sha256: str,
        size: int,
        progress: DownloadProgress | None = None,
    ) -> None:
        started = time.time()
        parsed = urlsplit(url)
        event: dict[str, object] = {
            "artifact_id": artifact_id,
            "source": f"{parsed.scheme}://{parsed.netloc}",
            "status": "started",
            "started_at": started,
        }
        self._events.append(event)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "ElectroBoy managed artifact installer"},
        )
        digest = hashlib.sha256()
        downloaded = 0
        try:
            with self.open_url(request, timeout=30) as response:
                with destination.open("wb") as output:
                    while chunk := response.read(1024 * 1024):
                        output.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
                        if progress is not None:
                            progress(downloaded, size)
            if downloaded != size:
                raise IDEError(
                    IDEErrorCategory.INSTALLATION_FAILED,
                    f"{artifact_id} size mismatch: expected {size}, got {downloaded}",
                )
            if digest.hexdigest() != sha256:
                raise IDEError(
                    IDEErrorCategory.INSTALLATION_FAILED,
                    f"{artifact_id} checksum does not match the pinned digest",
                )
        except Exception as error:
            event.update(
                status="failed",
                bytes=downloaded,
                duration_ms=int((time.time() - started) * 1000),
                error_category=(
                    error.category.value
                    if isinstance(error, IDEError)
                    else IDEErrorCategory.INSTALLATION_FAILED.value
                ),
            )
            if isinstance(error, IDEError):
                raise
            raise IDEError(
                IDEErrorCategory.INSTALLATION_FAILED,
                f"could not download {artifact_id}: {error}",
                recoverable=True,
            ) from error
        event.update(
            status="verified",
            bytes=downloaded,
            duration_ms=int((time.time() - started) * 1000),
        )

    def events(self) -> list[dict[str, object]]:
        return [dict(event) for event in self._events]
