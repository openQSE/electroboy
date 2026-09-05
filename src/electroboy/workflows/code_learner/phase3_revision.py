"""Hash-based, dependency-aware invalidation for Code Learner Phase 3."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from electroboy.models import utc_now

from .phase3_store import Phase3Store
from .source_manifest import SourceManifestSnapshot


@dataclass(frozen=True)
class Phase3InvalidationReport:
    """The source delta and downstream scopes invalidated for one revision."""

    previous_revision: str
    current_revision: str
    changed_file_ids: tuple[str, ...]
    affected_candidate_ids: tuple[str, ...]
    affected_component_ids: tuple[str, ...]
    affected_module_ids: tuple[str, ...]
    preserved_component_ids: tuple[str, ...]
    preserved_module_ids: tuple[str, ...]
    stale_course_ids: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return self.previous_revision != self.current_revision

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "previous_revision": self.previous_revision,
            "current_revision": self.current_revision,
            "changed_file_ids": list(self.changed_file_ids),
            "affected_candidate_ids": list(self.affected_candidate_ids),
            "affected_component_ids": list(self.affected_component_ids),
            "affected_module_ids": list(self.affected_module_ids),
            "preserved_component_ids": list(self.preserved_component_ids),
            "preserved_module_ids": list(self.preserved_module_ids),
            "stale_course_ids": list(self.stale_course_ids),
            "updated_at": utc_now(),
        }


class Phase3RevisionInvalidator:
    """Invalidate only Phase 3 records downstream of changed source anchors."""

    def __init__(self, root: Path | str, *, store: Phase3Store | None = None) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = store or Phase3Store(self.root)
        self.report_path = self.store.state_root / "invalidation.json"

    def run(
        self,
        previous: SourceManifestSnapshot | None,
        current: SourceManifestSnapshot,
    ) -> Phase3InvalidationReport:
        if previous is None or previous.revision == current.revision:
            report = Phase3InvalidationReport(
                previous.revision if previous else "",
                current.revision,
                (),
                (),
                (),
                (),
                (),
                (),
                (),
            )
            self.store.write_json(self.report_path, report.to_dict())
            return report

        old_files = previous.by_id()
        new_files = current.by_id()
        changed_files = {
            file_id
            for file_id in set(old_files) | set(new_files)
            if _file_identity(old_files.get(file_id))
            != _file_identity(new_files.get(file_id))
        }
        changed_paths = {
            str(record.get("path") or "")
            for file_id in changed_files
            for record in (old_files.get(file_id), new_files.get(file_id))
            if record is not None
        }

        candidates = self.store.read_jsonl(
            self.store.components_root / "candidates.jsonl"
        )
        affected_candidates, retained_candidates = _partition_by_files(
            candidates, changed_files
        )
        retained_candidates, symbol_map = _promote_symbol_records(
            retained_candidates,
            previous_revision=previous.revision,
            current_revision=current.revision,
            current_files=new_files,
        )
        self.store.write_jsonl(
            self.store.components_root / "candidates.jsonl", retained_candidates
        )

        components = self.store.read_jsonl(
            self.store.components_root / "components.jsonl"
        )
        affected_components, retained_components = _partition_by_files(
            components, changed_files
        )
        retained_components, component_symbol_map = _promote_symbol_records(
            retained_components,
            previous_revision=previous.revision,
            current_revision=current.revision,
            current_files=new_files,
        )
        symbol_map.update(component_symbol_map)
        self.store.write_jsonl(
            self.store.components_root / "components.jsonl", retained_components
        )
        affected_component_ids = {
            str(item.get("id") or "") for item in affected_components
        }

        modules = self.store.read_jsonl(self.store.modules_root / "modules.jsonl")
        affected_modules = [
            item
            for item in modules
            if set(map(str, item.get("component_ids", []))) & affected_component_ids
        ]
        retained_modules = [item for item in modules if item not in affected_modules]
        retained_modules = [
            _promote(item, previous.revision, current.revision, symbol_map)
            for item in retained_modules
        ]
        self.store.write_jsonl(
            self.store.modules_root / "modules.jsonl", retained_modules
        )
        affected_module_ids = {str(item.get("id") or "") for item in affected_modules}

        relationships_path = self.store.modules_root / "relationships.jsonl"
        relationships = self.store.read_jsonl(relationships_path)
        retained_relationships = [
            _promote(item, previous.revision, current.revision, symbol_map)
            for item in relationships
            if not {
                str(item.get("from_module_id") or ""),
                str(item.get("to_module_id") or ""),
            }
            & affected_module_ids
        ]
        self.store.write_jsonl(relationships_path, retained_relationships)

        stale_courses = self._invalidate_knowledge_and_courses(
            affected_component_ids,
            affected_module_ids,
            previous_revision=previous.revision,
            current_revision=current.revision,
            symbol_map=symbol_map,
        )
        self._invalidate_catalogs(changed_paths)
        report = Phase3InvalidationReport(
            previous.revision,
            current.revision,
            tuple(sorted(changed_files)),
            tuple(
                sorted(
                    str(item.get("candidate_id") or "") for item in affected_candidates
                )
            ),
            tuple(sorted(affected_component_ids)),
            tuple(sorted(affected_module_ids)),
            tuple(sorted(str(item.get("id") or "") for item in retained_components)),
            tuple(sorted(str(item.get("id") or "") for item in retained_modules)),
            tuple(sorted(stale_courses)),
        )
        self.store.write_json(self.report_path, report.to_dict())
        return report

    def _invalidate_knowledge_and_courses(
        self,
        affected_component_ids: set[str],
        affected_module_ids: set[str],
        *,
        previous_revision: str,
        current_revision: str,
        symbol_map: Mapping[str, str],
    ) -> set[str]:
        stale = {"course:architecture:architecture:current"}
        _unlink(self.store.knowledge_root / "architecture.jsonl")
        _unlink(self.store.courses_root / "architecture.jsonl")
        _unlink(self.store.courses_root / "architecture.md")

        module_knowledge_root = self.store.knowledge_root / "modules"
        module_course_root = self.store.courses_root / "modules"
        index = self.store.read_json(self.store.courses_root / "index.json") or {
            "schema_version": 1,
            "targets": {},
        }
        targets = index.setdefault("targets", {})
        for target_id, target in list(targets.items()):
            if not isinstance(target, Mapping):
                continue
            mode = str(target.get("mode") or "")
            scope_id = str(target.get("scope_id") or "")
            if mode == "architecture":
                targets[target_id] = {
                    **target,
                    "status": "stale",
                    "updated_at": utc_now(),
                }
            elif mode == "module" and scope_id in affected_module_ids:
                stale.add(str(target_id))
                targets[target_id] = {
                    **target,
                    "status": "stale",
                    "updated_at": utc_now(),
                }
                _unlink(module_knowledge_root / f"{_safe(scope_id)}.jsonl")
                _unlink(module_course_root / f"{_safe(scope_id)}.jsonl")
                _unlink(module_course_root / f"{_safe(scope_id)}.md")

        for path in module_knowledge_root.glob("*.jsonl"):
            _promote_jsonl(path, previous_revision, current_revision, symbol_map)
        for path in module_course_root.glob("*.jsonl"):
            _promote_jsonl(path, previous_revision, current_revision, symbol_map)

        links_path = self.store.knowledge_root / "function-links.jsonl"
        retained_links = []
        for link in self.store.read_jsonl(links_path):
            old_key = str(link.get("canonical_key") or "")
            target_id = f"course:function:{old_key}"
            affected = bool(
                set(map(str, link.get("component_ids", []))) & affected_component_ids
                or set(map(str, link.get("module_ids", []))) & affected_module_ids
            )
            if affected:
                stale.add(target_id)
                target = targets.get(target_id)
                if isinstance(target, Mapping):
                    targets[target_id] = {
                        **target,
                        "status": "stale",
                        "updated_at": utc_now(),
                    }
                _unlink(self.root / str(link.get("function_path") or ""))
                continue
            retained_links.append(
                _promote(link, previous_revision, current_revision, symbol_map)
            )
        self.store.write_jsonl(links_path, retained_links)

        self.store.write_json(self.store.courses_root / "index.json", index)
        _unlink(self.store.result_path)
        _unlink(self.store.checkpoint_path)
        _unlink(self.store.progress_path)
        _unlink(self.store.tutor_context_path)
        self.store.write_jsonl(self.store.diagnostics_path, [])
        return stale

    def _invalidate_catalogs(self, changed_paths: set[str]) -> None:
        source_root = self.store.state_root / "source"
        _unlink(source_root / "universal-ctags-invocation.json")
        _unlink(source_root / "universal-ctags.raw.jsonl")
        targeted = source_root / "targeted"
        for path in changed_paths:
            digest = hashlib.sha256(path.encode()).hexdigest()[:16]
            _unlink(targeted / f"{digest}.jsonl")

        for path in (
            self.store.components_root / "overlap-groups.jsonl",
            self.store.components_root / "reconciliations.jsonl",
            self.store.components_root / "file-dispositions.jsonl",
            self.store.components_root / "coverage.json",
            self.store.components_root / "investigation-context.json",
            self.store.components_root / "investigation-dispositions.jsonl",
            self.store.components_root / "manifest.json",
            self.store.modules_root / "manifest.json",
            self.store.modules_root / "requests.jsonl",
            self.store.modules_root / "relationship-requests.jsonl",
        ):
            _unlink(path)
        shutil.rmtree(self.store.components_root / "reconciliation", ignore_errors=True)
        shutil.rmtree(
            self.store.modules_root / "relationship-scopes", ignore_errors=True
        )


def _partition_by_files(
    records: Sequence[Mapping[str, object]], changed_file_ids: set[str]
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    affected = []
    retained = []
    for record in records:
        file_ids = set(map(str, record.get("file_ids", [])))
        file_ids.update(
            str(item.get("file_id") or "")
            for field in ("symbols", "owned_source_refs", "supporting_source_refs")
            for item in record.get(field, [])
            if isinstance(item, Mapping)
        )
        (affected if file_ids & changed_file_ids else retained).append(dict(record))
    return affected, retained


def _promote_symbol_records(
    records: Sequence[Mapping[str, object]],
    *,
    previous_revision: str,
    current_revision: str,
    current_files: Mapping[str, Mapping[str, object]],
) -> tuple[list[dict[str, object]], dict[str, str]]:
    promoted = []
    symbol_map: dict[str, str] = {}
    for record in records:
        value = _promote(record, previous_revision, current_revision, {})
        symbols = []
        for symbol in value.get("symbols", []):
            if not isinstance(symbol, Mapping):
                continue
            item = dict(symbol)
            old_key = str(item.get("canonical_key") or "")
            file = current_files.get(str(item.get("file_id") or ""), {})
            new_key = _canonical_key(
                current_revision, str(file.get("path") or ""), item
            )
            if old_key:
                symbol_map[old_key] = new_key
            item["canonical_key"] = new_key
            symbols.append(item)
        value["symbols"] = symbols
        promoted.append(value)
    return promoted, symbol_map


def _canonical_key(revision: str, path: str, symbol: Mapping[str, object]) -> str:
    return "\x1f".join(
        (
            revision,
            path,
            str(symbol.get("language") or ""),
            str(symbol.get("kind") or "symbol"),
            str(symbol.get("scope") or ""),
            str(symbol.get("name") or ""),
            str(int(symbol.get("start_line") or 1)),
        )
    )


def _promote(
    value: object,
    previous_revision: str,
    current_revision: str,
    symbol_map: Mapping[str, str],
):
    if isinstance(value, Mapping):
        return {
            key: (
                current_revision
                if key in {"repository_revision", "revision"}
                and item == previous_revision
                else _promote(item, previous_revision, current_revision, symbol_map)
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _promote(item, previous_revision, current_revision, symbol_map)
            for item in value
        ]
    if isinstance(value, str):
        return symbol_map.get(value, value)
    return value


def _promote_jsonl(
    path: Path,
    previous_revision: str,
    current_revision: str,
    symbol_map: Mapping[str, str],
) -> None:
    if not path.is_file():
        return
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(
                _promote(
                    json.loads(line), previous_revision, current_revision, symbol_map
                )
            )
    temporary = path.with_suffix(f"{path.suffix}.tmp")
    temporary.write_text(
        "".join(json.dumps(item, sort_keys=True) + "\n" for item in records),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _file_identity(record: Mapping[str, object] | None) -> tuple[str, str] | None:
    if record is None:
        return None
    return str(record.get("path") or ""), str(record.get("content_hash") or "")


def _safe(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in "._-" else "-"
        for character in value
    ).strip(".-")


def _unlink(path: Path) -> None:
    path.unlink(missing_ok=True)
