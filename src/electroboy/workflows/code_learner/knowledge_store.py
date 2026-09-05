"""Durable, repository-scoped storage for Code Learner Phase 2."""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Iterable, Mapping
from pathlib import Path
from uuid import uuid4

from electroboy.models import utc_now

from .contracts import (
    parse_jsonl,
    validate_course_records,
    validate_knowledge_records,
)
from .domain import CodeLearnerError, repository_revision

STATE_ROOT = Path(".electroboy") / "code-learner"
KNOWLEDGE_STREAMS = {
    "knowledge_manifest": "manifest.jsonl",
    "entity": "entities.jsonl",
    "relationship": "relationships.jsonl",
    "runtime_flow": "flows.jsonl",
    "diagnostic": "diagnostics.jsonl",
    "knowledge_request": "requests.jsonl",
}
KNOWLEDGE_ORDER = tuple(KNOWLEDGE_STREAMS)
SAFE_ID = re.compile(r"[^a-zA-Z0-9._-]+")


class KnowledgeStore:
    """Persistence boundary for knowledge, courses, and durable checkpoints."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.state_root = self.root / STATE_ROOT
        self.knowledge_root = self.state_root / "knowledge"
        self.courses_root = self.state_root / "courses"
        self.analysis_root = self.state_root / "analysis"
        self.symbol_evidence_path = self.analysis_root / "symbol-evidence.jsonl"
        self.progress_path = self.state_root / "progress.jsonl"
        self.checkpoint_path = self.state_root / "checkpoint.json"
        self.course_index_path = self.courses_root / "index.json"
        self.tutor_context_path = self.state_root / "tutor-context.json"
        self._lock = threading.RLock()

    def knowledge_path(self, record_type: str) -> Path:
        try:
            name = KNOWLEDGE_STREAMS[record_type]
        except KeyError as error:
            raise CodeLearnerError(
                f"unknown knowledge record type: {record_type}"
            ) from error
        return self.knowledge_root / name

    def load_knowledge(
        self, *, validate_sources: bool = True
    ) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for record_type in KNOWLEDGE_ORDER:
            path = self.knowledge_path(record_type)
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            if not text.strip():
                continue
            records.extend(
                parse_jsonl(
                    text,
                    artifact=path.relative_to(self.root).as_posix(),
                )
            )
        if not records:
            return []
        return validate_knowledge_records(
            records,
            root=self.root if validate_sources else None,
        )

    def save_knowledge(
        self,
        records: Iterable[Mapping[str, object]],
    ) -> list[dict[str, object]]:
        normalized = validate_knowledge_records(records, root=self.root)
        grouped = {
            record_type: [
                record
                for record in normalized
                if record.get("record_type") == record_type
            ]
            for record_type in KNOWLEDGE_ORDER
        }
        with self._lock:
            staged: list[tuple[Path, Path]] = []
            try:
                for record_type, stream in grouped.items():
                    path = self.knowledge_path(record_type)
                    temporary = _stage_jsonl(path, stream)
                    staged.append((temporary, path))
                for temporary, path in staged:
                    os.replace(temporary, path)
            finally:
                for temporary, _path in staged:
                    temporary.unlink(missing_ok=True)
        return normalized

    def merge_knowledge(
        self,
        changes: Iterable[Mapping[str, object]],
    ) -> list[dict[str, object]]:
        incoming = [dict(record) for record in changes]
        if not incoming:
            raise CodeLearnerError("knowledge merge is empty")
        current = self.load_knowledge()
        merged = {str(record["id"]): record for record in current}
        for record in incoming:
            record_id = str(record.get("id") or "")
            if not record_id:
                raise CodeLearnerError("knowledge merge record is missing id")
            existing = merged.get(record_id)
            if existing is not None and _record_identity(existing) != _record_identity(
                record
            ):
                raise CodeLearnerError(
                    f"incompatible knowledge record replacement: {record_id}"
                )
            merged[record_id] = record
        ordered = _knowledge_ordered(merged.values())
        _refresh_manifest_counts(ordered)
        return self.save_knowledge(ordered)

    def knowledge_ids(self) -> set[str]:
        return {str(record["id"]) for record in self.load_knowledge()}

    def get(self, record_id: str) -> dict[str, object]:
        requested = str(record_id or "").strip()
        for record in self.load_knowledge():
            if record.get("id") == requested:
                return record
        raise CodeLearnerError(f"unknown knowledge record: {requested}")

    def query(
        self,
        *,
        kind: str = "",
        module_id: str = "",
        source_path: str = "",
    ) -> list[dict[str, object]]:
        records = self.load_knowledge()
        selected: list[dict[str, object]] = []
        for record in records:
            if kind and record.get("kind") != kind:
                continue
            if module_id and not _belongs_to_module(record, module_id, records):
                continue
            if source_path and not _record_references_path(record, source_path):
                continue
            selected.append(record)
        return selected

    def neighborhood(self, record_id: str, *, hops: int = 1) -> list[dict[str, object]]:
        records = self.load_knowledge()
        by_id = {str(record["id"]): record for record in records}
        if record_id not in by_id:
            raise CodeLearnerError(f"unknown knowledge record: {record_id}")
        selected = {record_id}
        frontier = {record_id}
        for _hop in range(max(0, hops)):
            before = set(selected)
            adjacent: set[str] = set()
            for record in records:
                if record.get("record_type") != "relationship":
                    continue
                left = str(record.get("from_id") or "")
                right = str(record.get("to_id") or "")
                if left in frontier or right in frontier:
                    selected.update((str(record["id"]), left, right))
                    adjacent.update((left, right))
            frontier = adjacent - before
        return [record for record in records if record.get("id") in selected]

    def deprecate(
        self,
        record_id: str,
        *,
        reason: str,
        analysis_run_id: str,
        revision: str,
    ) -> dict[str, object]:
        record = self.get(record_id)
        if record.get("record_type") == "knowledge_manifest":
            raise CodeLearnerError("the knowledge manifest cannot be deprecated")
        deprecated = {
            **record,
            "status": "deprecated",
            "deprecation_reason": str(reason or "").strip(),
            "deprecated_at": utc_now(),
            "analysis_run_id": analysis_run_id,
            "repository_revision": revision,
        }
        if not deprecated["deprecation_reason"]:
            raise CodeLearnerError("deprecation reason is required")
        self.merge_knowledge([deprecated])
        return deprecated

    def freshness(self) -> dict[str, object]:
        records = self.load_knowledge(validate_sources=False)
        if not records:
            return {
                "fresh": False,
                "revision": repository_revision(self.root),
                "stale_ids": [],
            }
        current_revision = repository_revision(self.root)
        stale: set[str] = set()
        for record in records:
            record_id = str(record.get("id") or "")
            if record.get("repository_revision") != current_revision:
                stale.add(record_id)
                continue
            for source_ref in record.get("source_refs", []):
                if not isinstance(source_ref, dict):
                    stale.add(record_id)
                    break
                path = self.root / str(source_ref.get("path") or "")
                if not path.is_file():
                    stale.add(record_id)
                    break
                end_line = int(source_ref.get("end_line") or 0)
                line_count = (
                    len(path.read_text(encoding="utf-8", errors="replace").splitlines())
                    or 1
                )
                if end_line > line_count:
                    stale.add(record_id)
                    break
        return {
            "fresh": not stale,
            "revision": current_revision,
            "stale_ids": sorted(stale),
        }

    def import_v1_corpus(
        self,
        records: Iterable[Mapping[str, object]],
        *,
        analysis_run_id: str,
        revision: str,
    ) -> list[dict[str, object]]:
        converted = _convert_v1_records(
            records,
            analysis_run_id=analysis_run_id,
            revision=revision,
        )
        return self.save_knowledge(converted)

    def course_path(self, mode: str, scope_id: str) -> Path:
        normalized = str(mode or "").strip().lower()
        safe_scope = SAFE_ID.sub("-", str(scope_id or "").strip()).strip(".-")
        if not safe_scope:
            raise CodeLearnerError("course scope is required")
        if normalized == "architecture":
            return self.courses_root / "architecture.jsonl"
        if normalized == "module":
            return self.courses_root / "modules" / f"{safe_scope}.jsonl"
        if normalized == "function":
            return self.courses_root / "functions" / f"{safe_scope}.jsonl"
        raise CodeLearnerError(f"unknown course mode: {mode}")

    def course_markdown_path(self, mode: str, scope_id: str) -> Path:
        """Return the Markdown companion path for a course JSONL artifact."""

        return self.course_path(mode, scope_id).with_suffix(".md")

    def save_course(
        self,
        mode: str,
        scope_id: str,
        records: Iterable[Mapping[str, object]],
    ) -> Path:
        normalized = validate_course_records(
            records,
            knowledge_ids=self.knowledge_ids(),
            root=self.root,
        )
        document = next(
            record for record in normalized if record["record_type"] == "document"
        )
        if document.get("course_mode") != mode.lower():
            raise CodeLearnerError("course mode does not match its storage scope")
        if document.get("scope_id") != scope_id:
            raise CodeLearnerError(
                "course document scope does not match requested scope"
            )
        path = self.course_path(mode, scope_id)
        with self._lock:
            _write_jsonl(path, normalized)
        return path

    def load_course(self, mode: str, scope_id: str) -> list[dict[str, object]]:
        path = self.course_path(mode, scope_id)
        if not path.is_file():
            return []
        return validate_course_records(
            parse_jsonl(
                path.read_text(encoding="utf-8"),
                artifact=path.relative_to(self.root).as_posix(),
            ),
            knowledge_ids=self.knowledge_ids(),
            root=self.root,
        )

    def mark_courses_stale(self, knowledge_ids: Iterable[str]) -> list[Path]:
        """Mark persisted courses linked to changed knowledge as stale."""

        affected = set(knowledge_ids)
        changed: list[Path] = []
        if not affected or not self.courses_root.is_dir():
            return changed
        for path in sorted(self.courses_root.rglob("*.jsonl")):
            records = parse_jsonl(
                path.read_text(encoding="utf-8"),
                artifact=path.relative_to(self.root).as_posix(),
            )
            linked = any(
                affected
                & set(record.get("knowledge_entity_ids", []))
                | affected
                & set(record.get("relationship_ids", []))
                | affected
                & set(record.get("runtime_flow_ids", []))
                for record in records
                if record.get("record_type") == "section"
            )
            if not linked:
                continue
            for record in records:
                if record.get("record_type") == "document":
                    record["status"] = "stale"
                elif record.get("record_type") == "section":
                    record["status"] = "stale"
            validate_course_records(
                records,
                knowledge_ids=self.knowledge_ids(),
                root=self.root,
            )
            with self._lock:
                _write_jsonl(path, records)
            changed.append(path)
        return changed

    def load_course_index(self) -> dict[str, object]:
        """Load per-scope generation states for independently built courses."""

        if not self.course_index_path.is_file():
            return {"schema_version": 1, "courses": {}}
        try:
            value = json.loads(self.course_index_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CodeLearnerError(f"could not load course index: {error}") from error
        if not isinstance(value, dict) or not isinstance(value.get("courses"), dict):
            raise CodeLearnerError("course index must contain a courses object")
        return value

    def record_course_status(
        self,
        mode: str,
        scope_id: str,
        status: str,
        *,
        path: str = "",
        error: str = "",
    ) -> None:
        """Atomically update one course without disturbing sibling states."""

        with self._lock:
            index = self.load_course_index()
            courses = index["courses"]
            key = f"{mode.lower()}:{scope_id}"
            courses[key] = {
                "mode": mode.lower(),
                "scope_id": scope_id,
                "status": status,
                "path": path,
                "error": error,
                "updated_at": utc_now(),
            }
            _write_json(self.course_index_path, index)

    def append_progress(self, record: Mapping[str, object]) -> None:
        payload = json.dumps(dict(record), sort_keys=True) + "\n"
        with self._lock:
            self.progress_path.parent.mkdir(parents=True, exist_ok=True)
            with self.progress_path.open("a", encoding="utf-8") as stream:
                stream.write(payload)

    def save_checkpoint(self, checkpoint: Mapping[str, object]) -> None:
        with self._lock:
            _write_json(self.checkpoint_path, dict(checkpoint))

    def load_checkpoint(self) -> dict[str, object] | None:
        if not self.checkpoint_path.is_file():
            return None
        try:
            value = json.loads(self.checkpoint_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise CodeLearnerError(
                f"could not load learner checkpoint: {error}"
            ) from error
        if not isinstance(value, dict):
            raise CodeLearnerError("learner checkpoint must be an object")
        return value


def _knowledge_ordered(
    records: Iterable[Mapping[str, object]],
) -> list[dict[str, object]]:
    rank = {record_type: index for index, record_type in enumerate(KNOWLEDGE_ORDER)}
    return sorted(
        (dict(record) for record in records),
        key=lambda record: (
            rank.get(str(record.get("record_type")), len(rank)),
            str(record.get("id") or ""),
        ),
    )


def _record_identity(record: Mapping[str, object]) -> tuple[object, object]:
    return record.get("record_type"), record.get("kind")


def _record_references_path(record: Mapping[str, object], source_path: str) -> bool:
    return any(
        isinstance(reference, dict) and reference.get("path") == source_path
        for reference in record.get("source_refs", [])
    )


def _belongs_to_module(
    record: Mapping[str, object],
    module_id: str,
    records: list[dict[str, object]],
) -> bool:
    record_id = str(record.get("id") or "")
    if record_id == module_id or record.get("parent_id") == module_id:
        return True
    contained = {
        str(candidate.get("to_id"))
        for candidate in records
        if candidate.get("record_type") == "relationship"
        and candidate.get("kind") == "contains"
        and candidate.get("from_id") == module_id
    }
    if record_id in contained:
        return True
    return record.get("from_id") in contained | {module_id} or record.get(
        "to_id"
    ) in contained | {module_id}


def _convert_v1_records(
    records: Iterable[Mapping[str, object]],
    *,
    analysis_run_id: str,
    revision: str,
) -> list[dict[str, object]]:
    source = [dict(record) for record in records]
    manifest = next(
        (record for record in source if record.get("record_type") == "course_manifest"),
        {},
    )
    repository_ref = _first_v1_reference(source) or {
        "path": "README.md",
        "start_line": 1,
        "end_line": 1,
        "reason": "Legacy corpus repository evidence.",
    }
    common = {
        "schema_version": 1,
        "analysis_run_id": analysis_run_id,
        "repository_revision": revision,
    }
    converted: list[dict[str, object]] = [
        {
            **common,
            "record_type": "knowledge_manifest",
            "id": "knowledge.manifest",
            "repository_name": str(manifest.get("repository_name") or "Repository"),
            "scope_path": ".",
            "status": "imported-v1",
            "entity_count": 0,
            "relationship_count": 0,
            "flow_count": 0,
            "diagnostic_count": 1,
        },
        {
            **common,
            "record_type": "entity",
            "id": "repository.root",
            "kind": "repository",
            "name": str(manifest.get("repository_name") or "Repository"),
            "summary": str(
                manifest.get("repository_purpose") or "Imported v1 repository."
            ),
            "source_refs": [_canonical_v1_reference(repository_ref, revision)],
            "confidence": manifest.get("confidence", "medium"),
        },
    ]
    for record in source:
        record_type = record.get("record_type")
        if record_type == "module":
            module_id = str(record.get("id") or "")
            converted.append(
                {
                    **common,
                    "record_type": "entity",
                    "id": module_id,
                    "kind": "module",
                    "name": str(record.get("name") or module_id),
                    "summary": str(record.get("purpose") or "Imported v1 module."),
                    "parent_id": "repository.root",
                    "source_refs": _canonical_v1_references(record, revision),
                    "confidence": record.get("confidence", "medium"),
                    "attributes": {"imported_from": "v1-course-corpus"},
                }
            )
            converted.append(
                {
                    **common,
                    "record_type": "relationship",
                    "id": f"relationship.repository-contains-{module_id}",
                    "kind": "contains",
                    "from_id": "repository.root",
                    "to_id": module_id,
                    "summary": f"The repository contains {module_id}.",
                    "source_refs": _canonical_v1_references(record, revision),
                    "confidence": record.get("confidence", "medium"),
                }
            )
        elif record_type == "function_index_entry":
            symbol = str(record.get("symbol") or "")
            symbol_id = f"symbol.{SAFE_ID.sub('-', symbol)}"
            converted.append(
                {
                    **common,
                    "record_type": "entity",
                    "id": symbol_id,
                    "kind": "symbol",
                    "name": str(record.get("display_name") or symbol),
                    "summary": str(record.get("purpose") or "Imported v1 symbol."),
                    "parent_id": str(record.get("module_id") or "repository.root"),
                    "source_refs": _canonical_v1_references(record, revision),
                    "confidence": record.get("confidence", "medium"),
                    "attributes": {"qualified_name": symbol, "imported_from": "v1"},
                }
            )
    converted.append(
        {
            **common,
            "record_type": "diagnostic",
            "id": "diagnostic.v1-import",
            "severity": "info",
            "message": (
                "Imported useful v1 entities; relationship and flow enrichment "
                "is required."
            ),
            "source_refs": [_canonical_v1_reference(repository_ref, revision)],
        }
    )
    _refresh_manifest_counts(converted)
    return _knowledge_ordered(converted)


def _first_v1_reference(
    records: list[dict[str, object]],
) -> dict[str, object] | None:
    for record in records:
        references = record.get("source_refs")
        if isinstance(references, list):
            for reference in references:
                if isinstance(reference, dict):
                    return reference
    return None


def _canonical_v1_references(
    record: Mapping[str, object], revision: str
) -> list[dict[str, object]]:
    references = record.get("source_refs")
    result = [
        _canonical_v1_reference(reference, revision)
        for reference in (references if isinstance(references, list) else [])
        if isinstance(reference, dict)
    ]
    if not result:
        raise CodeLearnerError(
            f"v1 record has no source evidence: {record.get('record_type')}"
        )
    return result


def _canonical_v1_reference(
    reference: Mapping[str, object], revision: str
) -> dict[str, object]:
    return {
        "path": str(reference.get("path") or reference.get("file_path") or ""),
        "start_line": int(reference.get("start_line") or 1),
        "end_line": int(reference.get("end_line") or reference.get("start_line") or 1),
        "symbol": str(reference.get("symbol") or ""),
        "reason": str(reference.get("reason") or "Imported v1 source evidence."),
        "revision": revision,
    }


def _refresh_manifest_counts(records: list[dict[str, object]]) -> None:
    manifest = next(
        (
            record
            for record in records
            if record.get("record_type") == "knowledge_manifest"
        ),
        None,
    )
    if manifest is None:
        raise CodeLearnerError("knowledge merge requires a manifest")
    manifest.update(
        {
            "entity_count": _count(records, "entity"),
            "relationship_count": _count(records, "relationship"),
            "flow_count": _count(records, "runtime_flow"),
            "diagnostic_count": _count(records, "diagnostic"),
        }
    )


def _count(records: list[dict[str, object]], record_type: str) -> int:
    return sum(record.get("record_type") == record_type for record in records)


def _stage_jsonl(path: Path, records: Iterable[Mapping[str, object]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
    temporary.write_text(
        "".join(json.dumps(dict(record), sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )
    return temporary


def _write_jsonl(path: Path, records: Iterable[Mapping[str, object]]) -> None:
    temporary = _stage_jsonl(path, records)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.{uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(dict(value), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
