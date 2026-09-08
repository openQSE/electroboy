"""Cross-process initialization guard for Code Learner."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

from electroboy.models import utc_now

from .domain import CodeLearnerError
from .store import LearnerStore


class InitializationLease:
    """Hold a non-blocking repository lock for one initialization process."""

    def __init__(self, path: Path, stream: object) -> None:
        self.path = path
        self._stream = stream

    @classmethod
    def acquire(cls, root: Path | str, job_id: str) -> InitializationLease:
        store = LearnerStore(root)
        path = store.state_root / "initialize.lock"
        path.parent.mkdir(parents=True, exist_ok=True)
        stream = path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            stream.seek(0)
            owner = stream.read().strip() or "another process"
            stream.close()
            raise CodeLearnerError(
                f"Code Learner initialization is already running: {owner}"
            ) from error
        stream.seek(0)
        stream.truncate()
        stream.write(
            json.dumps(
                {"pid": os.getpid(), "job_id": job_id, "started_at": utc_now()},
                sort_keys=True,
            )
            + "\n"
        )
        stream.flush()
        return cls(path, stream)

    def release(self) -> None:
        if self._stream is None:
            return
        fcntl.flock(self._stream.fileno(), fcntl.LOCK_UN)
        self._stream.close()
        self._stream = None
