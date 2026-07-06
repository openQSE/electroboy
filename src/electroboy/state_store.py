"""Filesystem-backed pipeline state."""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from uuid import uuid4

from .models import (
    ActivityEvent,
    ApprovalRecord,
    ArtifactSnapshot,
    BaselineInvalidation,
    ChangeRequest,
    DecisionRecord,
    PhaseStatus,
    ReviewIssue,
    RunManifest,
    utc_now,
)
from .redaction import redact_value


class StateError(RuntimeError):
    """Raised when durable pipeline state is missing or invalid."""


class StateStore:
    """Read and write `.electroboy` state for one repository."""

    def __init__(self, root: Path | str = ".") -> None:
        self.root = Path(root).resolve()
        self.state_dir = self.root / ".electroboy"
        self.legacy_state_dir = self.root / ".agent-pipeline"
        self.shared_dir = self.state_dir / "shared"
        self.local_dir = self.state_dir / "local"
        self.runs_dir = self.shared_dir / "runs"
        self.current_run_file = self.shared_dir / "current-run"

    def init_run(self, run_id: str | None = None, force: bool = False) -> RunManifest:
        if self.current_run_id() and not force:
            raise StateError("pipeline run already exists; use --force to replace it")

        self.runs_dir.mkdir(parents=True, exist_ok=True)
        self.local_dir.mkdir(parents=True, exist_ok=True)
        run_id = run_id or self._new_run_id()
        run_dir = self.run_dir(run_id)
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "artifacts").mkdir(exist_ok=True)
        (run_dir / "messages").mkdir(exist_ok=True)
        (self.local_dir / "raw" / run_id).mkdir(parents=True, exist_ok=True)

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
            raise StateError("no ElectroBoy run exists; run `electroboy init` first")
        return self.load_manifest(run_id)

    def current_run_id(self) -> str | None:
        candidates = [
            self.current_run_file,
            self.state_dir / "current-run",
            self.legacy_state_dir / "shared" / "current-run",
            self.legacy_state_dir / "current-run",
        ]
        current_run_file = next((path for path in candidates if path.exists()), None)
        if current_run_file is None:
            return None
        run_id = current_run_file.read_text(encoding="utf-8").strip()
        return run_id or None

    def _legacy_run_dirs(self, run_id: str) -> list[Path]:
        return [
            self.state_dir / "runs" / run_id,
            self.legacy_state_dir / "shared" / "runs" / run_id,
            self.legacy_state_dir / "runs" / run_id,
        ]

    def _resolve_run_dir(self, run_id: str) -> Path:
        run_dir = self.run_dir(run_id)
        if run_dir.exists():
            return run_dir
        for legacy_run_dir in self._legacy_run_dirs(run_id):
            if legacy_run_dir.exists():
                return legacy_run_dir
        return run_dir

    def _shared_path(self, relative_path: str) -> Path:
        path = self.shared_dir / relative_path
        candidates = [
            path,
            self.state_dir / relative_path,
            self.legacy_state_dir / "shared" / relative_path,
            self.legacy_state_dir / relative_path,
        ]
        return next((candidate for candidate in candidates if candidate.exists()), path)

    def _writable_shared_path(self, relative_path: str) -> Path:
        return self.shared_dir / relative_path

    def load_manifest(self, run_id: str) -> RunManifest:
        path = self._resolve_run_dir(run_id) / "manifest.json"
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
        if event.event_id is None:
            path = self.run_dir(manifest.run_id) / "activity-log.jsonl"
            event.event_id = f"EVT-{len(self.read_jsonl(path)) + 1:05d}"
        self.append_jsonl(self.run_dir(manifest.run_id) / "activity-log.jsonl", event)

    def read_activity(self) -> list[dict[str, object]]:
        manifest = self.load_current_manifest()
        path = self._resolve_run_dir(manifest.run_id) / "activity-log.jsonl"
        return self.read_jsonl(path)

    def append_change_request(self, data: ChangeRequest | dict[str, object]) -> None:
        manifest = self.load_current_manifest()
        self.append_jsonl(self.run_dir(manifest.run_id) / "change-requests.jsonl", data)

    def append_baseline_invalidation(
        self,
        invalidation: BaselineInvalidation,
    ) -> None:
        manifest = self.load_current_manifest()
        path = self.run_dir(manifest.run_id) / "baseline-invalidations.jsonl"
        self.append_jsonl(path, invalidation)

    def read_baseline_invalidations(self) -> list[dict[str, object]]:
        manifest = self.load_current_manifest()
        path = self._resolve_run_dir(manifest.run_id) / "baseline-invalidations.jsonl"
        return self.read_jsonl(path)

    def append_artifact_snapshot(self, snapshot: ArtifactSnapshot) -> None:
        manifest = self.load_current_manifest()
        path = self.run_dir(manifest.run_id) / "artifact-snapshots.jsonl"
        self.append_jsonl(path, snapshot)

    def read_artifact_snapshots(self) -> list[dict[str, object]]:
        manifest = self.load_current_manifest()
        path = self._resolve_run_dir(manifest.run_id) / "artifact-snapshots.jsonl"
        return self.read_jsonl(path)

    def append_review_issue(self, file_name: str, issue: ReviewIssue) -> None:
        manifest = self.load_current_manifest()
        self.append_jsonl(self.run_dir(manifest.run_id) / file_name, issue)

    def read_review_issues(self, file_name: str) -> list[dict[str, object]]:
        manifest = self.load_current_manifest()
        records = self.read_jsonl(self._resolve_run_dir(manifest.run_id) / file_name)
        latest: dict[str, dict[str, object]] = {}
        order: list[str] = []
        for record in records:
            issue_id = str(record.get("issue_id", ""))
            if not issue_id:
                continue
            if issue_id not in latest:
                order.append(issue_id)
            latest[issue_id] = record
        return [latest[issue_id] for issue_id in order]

    def read_review_issue_history(self, file_name: str) -> list[dict[str, object]]:
        manifest = self.load_current_manifest()
        return self.read_jsonl(self._resolve_run_dir(manifest.run_id) / file_name)

    def replace_review_issues(
        self,
        file_name: str,
        issues: list[dict[str, object]],
    ) -> None:
        manifest = self.load_current_manifest()
        path = self.run_dir(manifest.run_id) / file_name
        path.parent.mkdir(parents=True, exist_ok=True)
        text = "".join(
            json.dumps(self._to_jsonable(issue), sort_keys=True) + "\n"
            for issue in issues
        )
        path.write_text(text, encoding="utf-8")

    def append_decision(self, decision: DecisionRecord) -> None:
        self.append_jsonl(self._writable_shared_path("decisions.jsonl"), decision)

    def read_decisions(self) -> list[dict[str, object]]:
        return self.read_jsonl(self._shared_path("decisions.jsonl"))

    def append_approval(self, approval: ApprovalRecord) -> None:
        manifest = self.load_current_manifest()
        path = self.run_dir(manifest.run_id) / "approvals.jsonl"
        self.append_jsonl(path, approval)

    def read_approvals(self) -> list[dict[str, object]]:
        manifest = self.load_current_manifest()
        path = self._resolve_run_dir(manifest.run_id) / "approvals.jsonl"
        return self.read_jsonl(path)

    def load_phase_status(self) -> PhaseStatus:
        path = self._shared_path("phase-status.json")
        if not path.exists():
            return PhaseStatus()
        return PhaseStatus.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def save_phase_status(self, phase_status: PhaseStatus) -> None:
        phase_status.updated_at = utc_now()
        self._write_json(
            self._writable_shared_path("phase-status.json"),
            phase_status.to_dict(),
        )

    def write_message(self, event_id: str, content: str) -> Path:
        manifest = self.load_current_manifest()
        path = self.run_dir(manifest.run_id) / "messages" / f"{event_id}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(redact_value(content), encoding="utf-8")
        return path

    def write_raw_event(self, event_id: str, content: object) -> Path:
        manifest = self.load_current_manifest()
        path = self.local_dir / "raw" / manifest.run_id / f"{event_id}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            text = redact_value(content)
        else:
            text = json.dumps(self._to_jsonable(content), sort_keys=True)
        path.write_text(text.rstrip() + "\n", encoding="utf-8")
        return path

    def read_change_requests(self) -> list[dict[str, object]]:
        manifest = self.load_current_manifest()
        path = self._resolve_run_dir(manifest.run_id) / "change-requests.jsonl"
        records = self.read_jsonl(path)
        latest: dict[str, dict[str, object]] = {}
        order: list[str] = []
        for record in records:
            request_id = str(record.get("id", ""))
            if not request_id:
                continue
            if request_id not in latest:
                order.append(request_id)
            latest[request_id] = record
        return [latest[request_id] for request_id in order]

    def append_jsonl(self, path: Path, record: object) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(self._to_jsonable(record), sort_keys=True))
            stream.write("\n")

    def read_jsonl(self, path: Path) -> list[dict[str, object]]:
        if not path.exists():
            return []
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

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
            json.dumps(self._to_jsonable(data), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp.replace(path)

    def _new_run_id(self) -> str:
        stamp = utc_now().replace(":", "").replace("+00:00", "Z")
        return f"{stamp}-{uuid4().hex[:8]}"

    def _to_jsonable(self, record: object) -> object:
        if isinstance(record, ActivityEvent):
            return redact_value(record.to_dict())
        if isinstance(record, ApprovalRecord):
            return redact_value(record.to_dict())
        if isinstance(record, ArtifactSnapshot):
            return redact_value(record.to_dict())
        if isinstance(record, BaselineInvalidation):
            return redact_value(record.to_dict())
        if isinstance(record, ChangeRequest):
            return redact_value(record.to_dict())
        if isinstance(record, DecisionRecord):
            return redact_value(record.to_dict())
        if isinstance(record, PhaseStatus):
            return redact_value(record.to_dict())
        if isinstance(record, ReviewIssue):
            return redact_value(record.to_dict())
        if is_dataclass(record):
            return redact_value(asdict(record))
        return redact_value(record)
