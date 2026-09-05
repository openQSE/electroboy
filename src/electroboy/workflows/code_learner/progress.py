"""Progress and heartbeat primitives for blocking Code Learner AI work."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from contextlib import AbstractContextManager

ProgressCallback = Callable[[dict[str, object]], None]


class InvocationHeartbeat(AbstractContextManager["InvocationHeartbeat"]):
    """Emit bounded status while an AI runtime is waiting on its final reply."""

    def __init__(
        self,
        callback: ProgressCallback | None,
        event: Mapping[str, object],
        *,
        interval: float = 5.0,
    ) -> None:
        self.callback = callback
        self.event = dict(event)
        self.interval = max(0.01, interval)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> InvocationHeartbeat:
        if self.callback is None:
            return self
        self._thread = threading.Thread(
            target=self._run,
            name="code-learner-progress-heartbeat",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 0.5)
        return None

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            if self.callback is not None:
                self.callback({**self.event, "heartbeat": True})
