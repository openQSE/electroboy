"""Filesystem-backed pipeline state."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from uuid import uuid4

from .models import ActivityEvent, RunManifest, utc_now


class StateError(RuntimeError):
    """Raised when durable pipeline state is missing or invalid."""


class StateStore:
    """Read and write `.agent-pipeline` state for one repository."""

    def __init__(self, root: Path | str = ".") -> None:
        self.root = Path(root).resolve()
        self.state_dir = self.root / ".agent-pipeline"
        self.runs_dir = self.state_dir / "runs"
        self.current_run_file = self.state_dir / "current-run"

    def init_run(self, run_id: str | None = None, force: bool = False) -> RunManifest:
        if self.current_run_file.exists() and not force:
            raise StateError("pipeline run already exists; use --force to replace it")

        self.runs_dir.mkdir(parents=True, exist_ok=True)
        run_id = run_id or self._new_run_id()
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "artifacts").mkdir(exist_ok=True)
        (run_dir / "messages").mkdir(exist_ok=True)
        (run_dir / "raw").mkdir(exist_ok=True)

        manifest = RunManifest(run_id=run_id)
        self.save_manifest(manifest)
        self.current_run_file.write_text(f"{run_id}\n", encoding="utf-8")
        self.append_activity(
            ActivityEvent(
                actor="orchestrator",
                stage=manifest.active_stage,
                action="run-created",
                summary=f"Created pipeline run {run_id}.",
            )
        )
        return manifest

    def load_current_manifest(self) -> RunManifest:
        run_id = self.current_run_id()
        if not run_id:
            raise StateError("no pipeline run exists; run `ai-pipeline init` first")
        return self.load_manifest(run_id)

    def current_run_id(self) -> str | None:
        if not self.current_run_file.exists():
            return None
        run_id = self.current_run_file.read_text(encoding="utf-8").strip()
        return run_id or None

    def load_manifest(self, run_id: str) -> RunManifest:
        path = self.run_dir(run_id) / "manifest.json"
        if not path.exists():
            raise StateError(f"manifest not found for run {run_id}")
        return RunManifest.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save_manifest(self, manifest: RunManifest) -> None:
        manifest.updated_at = utc_now()
        run_dir = self.run_dir(manifest.run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(run_dir / "manifest.json", manifest.to_dict())

    def append_activity(self, event: ActivityEvent) -> None:
        manifest = self.load_current_manifest_for_append()
        self.append_jsonl(self.run_dir(manifest.run_id) / "activity-log.jsonl", event)

    def append_change_request(self, data: dict[str, object]) -> None:
        manifest = self.load_current_manifest()
        self.append_jsonl(self.run_dir(manifest.run_id) / "change-requests.jsonl", data)

    def read_change_requests(self) -> list[dict[str, object]]:
        manifest = self.load_current_manifest()
        path = self.run_dir(manifest.run_id) / "change-requests.jsonl"
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def append_jsonl(self, path: Path, record: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(self._to_jsonable(record), sort_keys=True))
            stream.write("\n")

    def run_dir(self, run_id: str) -> Path:
        return self.runs_dir / run_id

    def load_current_manifest_for_append(self) -> RunManifest:
        run_id = self.current_run_id()
        if run_id:
            return self.load_manifest(run_id)
        raise StateError("cannot append activity before a run exists")

    def _write_json(self, path: Path, data: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(f"{path.suffix}.tmp")
        temp.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp.replace(path)

    def _new_run_id(self) -> str:
        stamp = utc_now().replace(":", "").replace("+00:00", "Z")
        return f"{stamp}-{uuid4().hex[:8]}"

    def _to_jsonable(self, record: object) -> object:
        if isinstance(record, ActivityEvent):
            return record.to_dict()
        if is_dataclass(record):
            return asdict(record)
        return record
