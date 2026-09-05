"""Source revision snapshots and scoped Code Learner invalidation."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from electroboy.models import utc_now
from electroboy.service.file_watch import file_signature

from .course_artifacts import render_saved_course
from .domain import (
    IGNORED_DIRECTORY_NAMES,
    SOURCE_EXTENSIONS,
    repository_revision,
)
from .knowledge_store import KnowledgeStore


@dataclass(frozen=True)
class InvalidationReport:
    """Knowledge and course scopes affected by a source revision change."""

    previous_revision: str
    current_revision: str
    changed_paths: tuple[str, ...]
    affected_record_ids: tuple[str, ...]
    stale_courses: tuple[str, ...]
    promoted_courses: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return self.previous_revision != self.current_revision

    def to_dict(self) -> dict[str, object]:
        return {
            "previous_revision": self.previous_revision,
            "current_revision": self.current_revision,
            "changed_paths": list(self.changed_paths),
            "affected_record_ids": list(self.affected_record_ids),
            "stale_courses": list(self.stale_courses),
            "promoted_courses": list(self.promoted_courses),
            "updated_at": utc_now(),
        }


class RevisionInvalidator:
    """Promote unchanged evidence and stale only affected downstream courses."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = KnowledgeStore(self.root)
        self.report_path = self.store.analysis_root / "invalidation.json"

    def run(self) -> InvalidationReport:
        checkpoint = self.store.load_checkpoint() or {}
        previous_revision = str(checkpoint.get("repository_revision") or "")
        current_revision = repository_revision(self.root)
        if not previous_revision or previous_revision == current_revision:
            return InvalidationReport(
                previous_revision,
                current_revision,
                (),
                (),
                (),
                (),
            )
        records = self.store.load_knowledge(validate_sources=False)
        prior_snapshot = checkpoint.get("source_snapshot")
        prior_snapshot = prior_snapshot if isinstance(prior_snapshot, dict) else {}
        current_snapshot = repository_source_snapshot(self.root)
        changed_paths = _changed_paths(prior_snapshot, current_snapshot)
        if not prior_snapshot:
            changed_paths = set(current_snapshot) | {
                str(reference.get("path") or "")
                for record in records
                for reference in record.get("source_refs", [])
                if isinstance(reference, dict)
            }
        affected = _affected_records(records, changed_paths)
        promoted = []
        for record in records:
            record_id = str(record.get("id") or "")
            if record_id in affected:
                attributes = record.get("attributes")
                record["attributes"] = {
                    **(attributes if isinstance(attributes, dict) else {}),
                    "stale": True,
                    "stale_since_revision": current_revision,
                }
                continue
            record["repository_revision"] = current_revision
            for reference in record.get("source_refs", []):
                if isinstance(reference, dict) and "revision" in reference:
                    reference["revision"] = current_revision
            promoted.append(record_id)
        if records:
            self.store.save_knowledge(records, validate_sources=False)
        courses = self.store.revise_courses(
            affected_ids=affected,
            changed_paths=changed_paths,
            revision=current_revision,
        )
        for path in courses["promoted"]:
            document = self.store.load_course(
                *_course_identity(self.root, path),
                validate_sources=True,
            )[0]
            render_saved_course(
                self.root,
                str(document["course_mode"]),
                str(document["scope_id"]),
            )
        report = InvalidationReport(
            previous_revision,
            current_revision,
            tuple(sorted(changed_paths)),
            tuple(sorted(affected)),
            tuple(
                path.relative_to(self.root).as_posix() for path in courses["stale"]
            ),
            tuple(
                path.relative_to(self.root).as_posix()
                for path in courses["promoted"]
            ),
        )
        self.report_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.report_path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, self.report_path)
        return report


def repository_source_snapshot(root: Path | str) -> dict[str, dict[str, int]]:
    """Capture stable signatures for repository files relevant to analysis."""

    repository = Path(root).expanduser().resolve()
    snapshot: dict[str, dict[str, int]] = {}
    for current, dirnames, filenames in os.walk(repository):
        dirnames[:] = sorted(
            name
            for name in dirnames
            if name not in IGNORED_DIRECTORY_NAMES and not name.startswith(".")
        )
        for name in sorted(filenames):
            path = Path(current) / name
            if path.suffix.lower() not in SOURCE_EXTENSIONS:
                continue
            signature = file_signature(path)
            snapshot[path.relative_to(repository).as_posix()] = {
                "mtime_ns": int(signature.get("mtime_ns") or 0),
                "size": int(signature.get("size") or 0),
            }
    return snapshot


def _changed_paths(
    previous: Mapping[str, object], current: Mapping[str, object]
) -> set[str]:
    paths = set(previous) | set(current)
    return {path for path in paths if previous.get(path) != current.get(path)}


def _affected_records(
    records: list[dict[str, object]], changed_paths: set[str]
) -> set[str]:
    affected = {
        str(record.get("id") or "")
        for record in records
        if any(
            isinstance(reference, dict)
            and str(reference.get("path") or "") in changed_paths
            for reference in record.get("source_refs", [])
        )
    }
    if changed_paths:
        affected.add("knowledge.manifest")
    changed = True
    while changed:
        before = set(affected)
        for record in records:
            record_id = str(record.get("id") or "")
            record_type = record.get("record_type")
            if record_type == "relationship" and {
                str(record.get("from_id") or ""),
                str(record.get("to_id") or ""),
            } & affected:
                affected.add(record_id)
            elif record_type == "runtime_flow" and (
                set(record.get("participant_ids", [])) & affected
                or any(
                    set(step.get("relationship_ids", [])) & affected
                    for step in record.get("steps", [])
                    if isinstance(step, dict)
                )
            ):
                affected.add(record_id)
            elif record_type == "entity" and record.get("parent_id") in affected:
                affected.add(record_id)
            elif record_type in {"diagnostic", "knowledge_request"}:
                attributes = record.get("attributes")
                related = (
                    set(attributes.get("related_record_ids", []))
                    if isinstance(attributes, dict)
                    else set(record.get("related_record_ids", []))
                )
                if related & affected:
                    affected.add(record_id)
        changed = affected != before
    affected.discard("")
    return affected


def _course_identity(root: Path, path: Path) -> tuple[str, str]:
    relative = path.relative_to(KnowledgeStore(root).courses_root)
    if relative.name == "architecture.jsonl":
        return "architecture", "repository.root"
    return relative.parent.name.rstrip("s"), relative.stem
