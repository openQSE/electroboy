"""Canonical Phase 3 components, file coverage, and missing-file recovery."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from electroboy.models import utc_now

from .components import ComponentCandidateService
from .domain import CodeLearnerError
from .overlap import ComponentOverlapService
from .phase3_contracts import (
    parse_phase3_jsonl,
    validate_components,
    validate_coverage_report,
    validate_file_dispositions,
    validate_manifest,
)
from .phase3_prompts import missing_file_investigation_prompt
from .phase3_store import Phase3Store
from .reconciliation import ComponentReconciliationService
from .source_manifest import SourceManifestService

Investigator = Callable[[str], str]
_CATCH_ALL_TERMS = ("miscellaneous", "unclassified", "catch-all", "catch all")


@dataclass(frozen=True)
class ComponentManifestSnapshot:
    manifest: dict[str, object]
    components: tuple[dict[str, object], ...]
    dispositions: tuple[dict[str, object], ...]
    coverage: dict[str, object]


class ComponentManifestService:
    """Promote candidate partitions and account for every selected source file."""

    def __init__(
        self,
        root: Path | str,
        *,
        store: Phase3Store | None = None,
        source: SourceManifestService | None = None,
        candidates: ComponentCandidateService | None = None,
        overlaps: ComponentOverlapService | None = None,
        reconciliations: ComponentReconciliationService | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = store or Phase3Store(self.root)
        self.source = source or SourceManifestService(self.root)
        self.candidates = candidates or ComponentCandidateService(self.root)
        self.overlaps = overlaps or ComponentOverlapService(self.root, store=self.store)
        self.reconciliations = reconciliations or ComponentReconciliationService(
            self.root, store=self.store
        )
        self.components_path = self.store.components_root / "components.jsonl"
        self.dispositions_path = self.store.components_root / "file-dispositions.jsonl"
        self.coverage_path = self.store.components_root / "coverage.json"
        self.context_path = self.store.components_root / "investigation-context.json"
        self.manifest_path = self.store.components_root / "manifest.json"

    def build(
        self,
        *,
        analysis_run_id: str,
        investigator: Investigator | None = None,
    ) -> ComponentManifestSnapshot:
        """Build once, optionally investigate missing files once, then freeze."""

        snapshot = self._build_once(analysis_run_id=analysis_run_id)
        unresolved = list(snapshot.coverage.get("unresolved_file_ids", []))
        context = self._save_investigation_context(
            analysis_run_id=analysis_run_id,
            snapshot=snapshot,
            attempted=False,
        )
        if unresolved and investigator is not None and not context.get("attempted"):
            prompt = missing_file_investigation_prompt(
                self.root,
                analysis_run_id=analysis_run_id,
                repository_revision=str(
                    snapshot.manifest.get("repository_revision") or ""
                ),
                context_path=self.context_path,
                unresolved_file_ids=unresolved,
            )
            output = investigator(prompt)
            self._apply_investigation(
                output,
                analysis_run_id=analysis_run_id,
                unresolved_file_ids=set(unresolved),
            )
            snapshot = self._build_once(analysis_run_id=analysis_run_id)
            self._save_investigation_context(
                analysis_run_id=analysis_run_id,
                snapshot=snapshot,
                attempted=True,
            )
        self._record_warnings(snapshot)
        return snapshot

    def load(self) -> ComponentManifestSnapshot | None:
        manifest = self.store.read_json(self.manifest_path)
        coverage = self.store.read_json(self.coverage_path)
        if manifest is None or coverage is None:
            return None
        source = self.source.load()
        if source is None:
            raise CodeLearnerError("source manifest is unavailable")
        components = self.store.read_jsonl(self.components_path)
        dispositions = self.store.read_jsonl(self.dispositions_path)
        validate_manifest(
            manifest,
            manifest_type="component_manifest",
            repository_revision=source.revision,
        )
        validate_components(
            components,
            repository_revision=source.revision,
            files=source.by_id(),
        )
        validate_file_dispositions(
            dispositions,
            file_ids=set(source.by_id()),
            component_ids={str(item["id"]) for item in components},
        )
        validate_coverage_report(coverage, repository_revision=source.revision)
        return ComponentManifestSnapshot(
            manifest, tuple(components), tuple(dispositions), coverage
        )

    def query_components(
        self,
        *,
        component_id: str = "",
        candidate_id: str = "",
        file_id: str = "",
        canonical_key: str = "",
        name: str = "",
        alias: str = "",
    ) -> list[dict[str, object]]:
        snapshot = self.load()
        if snapshot is None:
            return []
        return [
            dict(item)
            for item in snapshot.components
            if (not component_id or item.get("id") == component_id)
            and (
                not candidate_id or candidate_id in item.get("origin_candidate_ids", [])
            )
            and (not file_id or file_id in item.get("file_ids", []))
            and (
                not canonical_key
                or any(
                    symbol.get("canonical_key") == canonical_key
                    for symbol in item.get("symbols", [])
                    if isinstance(symbol, Mapping)
                )
            )
            and (not name or item.get("name") == name)
            and (not alias or alias in item.get("aliases", []))
        ]

    def query_dispositions(self, disposition: str = "") -> list[dict[str, object]]:
        snapshot = self.load()
        if snapshot is None:
            return []
        return [
            dict(item)
            for item in snapshot.dispositions
            if not disposition or item.get("disposition") == disposition
        ]

    def _build_once(self, *, analysis_run_id: str) -> ComponentManifestSnapshot:
        source = self.source.load()
        if source is None:
            raise CodeLearnerError("source manifest must precede component manifest")
        candidates = self.candidates.load()
        groups = self.overlaps.load()
        reconciliations = {
            str(item.get("overlap_group_id") or ""): item
            for item in self.reconciliations.load()
            if item.get("candidate_revision")
            == next(
                (
                    group.get("candidate_revision")
                    for group in groups
                    if group.get("id") == item.get("overlap_group_id")
                ),
                None,
            )
        }
        unresolved_groups = [
            str(group.get("id") or "")
            for group in groups
            if str(group.get("id") or "") not in reconciliations
        ]
        quarantined = {
            str(candidate_id)
            for group in groups
            if str(group.get("id") or "") in unresolved_groups
            for candidate_id in group.get("candidate_ids", [])
        }
        grouped = {
            str(candidate_id)
            for group in groups
            for candidate_id in group.get("candidate_ids", [])
        }
        partitions: list[dict[str, object]] = []
        for candidate in candidates:
            candidate_id = str(candidate.get("candidate_id") or "")
            if candidate_id not in grouped and candidate_id not in quarantined:
                partitions.append(_candidate_partition(candidate))
        for reconciliation in reconciliations.values():
            partitions.extend(
                dict(item) for item in reconciliation.get("resolved_partitions", [])
            )
        components = self._allocate_components(
            partitions,
            repository_revision=source.revision,
        )
        validate_components(
            components,
            repository_revision=source.revision,
            files=source.by_id(),
        )
        explicit = self._explicit_dispositions()
        dispositions = _derive_dispositions(source.files, components, explicit)
        validate_file_dispositions(
            dispositions,
            file_ids=set(source.by_id()),
            component_ids={str(item["id"]) for item in components},
        )
        coverage = _coverage(source.revision, dispositions)
        validate_coverage_report(coverage, repository_revision=source.revision)
        warnings = len(unresolved_groups) + int(coverage["unresolved_count"])
        manifest = {
            "schema_version": 1,
            "record_type": "component_manifest",
            "id": "component_manifest:current",
            "learner_generation": "phase3",
            "analysis_run_id": analysis_run_id,
            "repository_revision": source.revision,
            "source_manifest_id": source.manifest["id"],
            "status": "complete_with_warnings" if warnings else "complete",
            "component_ids": [str(item["id"]) for item in components],
            "component_count": len(components),
            "unresolved_overlap_group_ids": unresolved_groups,
            "coverage_path": self.coverage_path.relative_to(self.root).as_posix(),
            "warning_count": warnings,
            "frozen": True,
            "generated_at": utc_now(),
        }
        validate_manifest(
            manifest,
            manifest_type="component_manifest",
            repository_revision=source.revision,
        )
        self.store.write_jsonl(self.components_path, components)
        self.store.write_jsonl(self.dispositions_path, dispositions)
        self.store.write_json(self.coverage_path, coverage)
        self.store.write_json(self.manifest_path, manifest)
        return ComponentManifestSnapshot(
            manifest, tuple(components), tuple(dispositions), coverage
        )

    def _allocate_components(
        self,
        partitions: Sequence[Mapping[str, object]],
        *,
        repository_revision: str,
    ) -> list[dict[str, object]]:
        existing = {
            tuple(
                sorted(str(item) for item in component.get("origin_candidate_ids", []))
            ): str(component.get("id") or "")
            for component in self.store.read_jsonl(self.components_path)
        }
        components = []
        for partition in sorted(
            partitions,
            key=lambda item: tuple(
                sorted(str(value) for value in item.get("origin_candidate_ids", []))
            ),
        ):
            origins = tuple(
                sorted(
                    str(value) for value in partition.get("origin_candidate_ids", [])
                )
            )
            component_id = existing.get(origins) or f"component:{uuid4().hex}"
            components.append(
                {
                    **dict(partition),
                    "schema_version": 1,
                    "record_type": "component",
                    "id": component_id,
                    "repository_revision": repository_revision,
                }
            )
        return components

    def _explicit_dispositions(self) -> dict[str, dict[str, object]]:
        path = self.store.components_root / "investigation-dispositions.jsonl"
        return {
            str(item.get("file_id") or ""): item for item in self.store.read_jsonl(path)
        }

    def _save_investigation_context(
        self,
        *,
        analysis_run_id: str,
        snapshot: ComponentManifestSnapshot,
        attempted: bool,
    ) -> dict[str, object]:
        existing = self.store.read_json(self.context_path) or {}
        same_run = existing.get("analysis_run_id") == analysis_run_id
        payload = {
            "schema_version": 1,
            "analysis_run_id": analysis_run_id,
            "repository_revision": snapshot.manifest["repository_revision"],
            "attempted": (bool(existing.get("attempted")) if same_run else False)
            or attempted,
            "unresolved_file_ids": snapshot.coverage["unresolved_file_ids"],
            "artifact_paths": {
                "source_manifest": (
                    ".electroboy/code-learner/phase3/source/manifest.json"
                ),
                "source_files": ".electroboy/code-learner/phase3/source/files.jsonl",
                "raw_ctags": (
                    ".electroboy/code-learner/phase3/source/universal-ctags.raw.jsonl"
                ),
                "ctags_invocation": (
                    ".electroboy/code-learner/phase3/source/"
                    "universal-ctags-invocation.json"
                ),
                "candidates": self.candidates.candidates_path.relative_to(
                    self.root
                ).as_posix(),
                "candidate_validation": self.candidates.validation_root.relative_to(
                    self.root
                ).as_posix(),
                "overlap_groups": self.overlaps.path.relative_to(self.root).as_posix(),
                "reconciliations": (
                    self.reconciliations.reconciliations_path.relative_to(
                        self.root
                    ).as_posix()
                ),
                "components": self.components_path.relative_to(self.root).as_posix(),
                "file_dispositions": self.dispositions_path.relative_to(
                    self.root
                ).as_posix(),
                "diagnostics": self.store.diagnostics_path.relative_to(
                    self.root
                ).as_posix(),
                "attempts": self.store.attempts_root.relative_to(self.root).as_posix(),
                "checkpoint": self.store.checkpoint_path.relative_to(
                    self.root
                ).as_posix(),
                "schema": str(
                    Path(__file__).with_name("schemas") / "phase3.schema.json"
                ),
            },
            "completed_scopes": {
                "component_ids": snapshot.manifest["component_ids"],
                "unresolved_overlap_group_ids": snapshot.manifest[
                    "unresolved_overlap_group_ids"
                ],
            },
            "updated_at": utc_now(),
        }
        self.store.write_json(self.context_path, payload)
        return payload

    def _apply_investigation(
        self,
        output: str,
        *,
        analysis_run_id: str,
        unresolved_file_ids: set[str],
    ) -> None:
        records = parse_phase3_jsonl(output, artifact="missing-file investigation")
        candidates = [
            record
            for record in records
            if record.get("record_type") == "component_candidate"
        ]
        dispositions = [
            record
            for record in records
            if record.get("record_type") == "file_disposition"
        ]
        if len(candidates) + len(dispositions) != len(records):
            raise CodeLearnerError(
                "missing-file investigation emitted a prohibited record type"
            )
        accepted_candidates = []
        for candidate in candidates:
            identity = " ".join(
                str(candidate.get(field) or "").lower()
                for field in ("name", "kind", "responsibility")
            )
            file_ids = {str(item) for item in candidate.get("file_ids", [])}
            if (
                any(term in identity for term in _CATCH_ALL_TERMS)
                and file_ids <= unresolved_file_ids
            ):
                self._diagnostic(
                    "catch-all-component-rejected",
                    "Rejected a catch-all component proposed only for file coverage.",
                )
                continue
            accepted_candidates.append(candidate)
        if accepted_candidates:
            text = "\n".join(json.dumps(item) for item in accepted_candidates)
            result = self.candidates.ingest(
                text, attempt_id=f"missing-files-{analysis_run_id}"
            )
            for rejected in result.rejected:
                candidate_id = rejected.candidate.get("candidate_id", "unknown")
                self._diagnostic(
                    f"missing-file-candidate-{candidate_id}",
                    "; ".join(rejected.errors),
                )
            self.overlaps.build(self.candidates.load())
            if self.reconciliations.pending_group_ids():
                self.reconciliations.reconcile_pending(analysis_run_id=analysis_run_id)
        accepted_dispositions = []
        for record in dispositions:
            file_id = str(record.get("file_id") or "")
            disposition = str(record.get("disposition") or "")
            reason = str(record.get("reason") or "")
            if (
                file_id not in unresolved_file_ids
                or disposition
                not in {"repository_infrastructure", "excluded", "unresolved"}
                or not reason
            ):
                self._diagnostic(
                    f"invalid-investigation-disposition-{file_id}",
                    f"Rejected invalid investigation disposition for {file_id}.",
                )
                continue
            accepted_dispositions.append(
                {
                    "schema_version": 1,
                    "record_type": "file_disposition",
                    "repository_revision": record.get("repository_revision", ""),
                    "file_id": file_id,
                    "disposition": disposition,
                    "component_ids": [],
                    "reason": reason,
                }
            )
        self.store.write_jsonl(
            self.store.components_root / "investigation-dispositions.jsonl",
            accepted_dispositions,
        )

    def _record_warnings(self, snapshot: ComponentManifestSnapshot) -> None:
        for group_id in snapshot.manifest.get("unresolved_overlap_group_ids", []):
            self._diagnostic(
                f"unresolved-overlap-{group_id}",
                f"Component overlap group remains unresolved: {group_id}",
            )
        for file_id in snapshot.coverage.get("unresolved_file_ids", []):
            self._diagnostic(
                f"unresolved-file-{file_id}",
                f"No accepted component or file classification covers {file_id}.",
            )

    def _diagnostic(self, code: str, message: str) -> None:
        self.store.save_diagnostic(
            {
                "schema_version": 1,
                "record_type": "diagnostic",
                "id": f"diagnostic:{code}",
                "severity": "warning",
                "code": code,
                "message": message,
                "active": True,
                "recorded_at": utc_now(),
            }
        )


def _candidate_partition(candidate: Mapping[str, object]) -> dict[str, object]:
    return {
        "name": candidate.get("name", ""),
        "aliases": list(candidate.get("aliases", [])),
        "kind": candidate.get("kind", ""),
        "responsibility": candidate.get("responsibility", ""),
        "file_ids": sorted(str(item) for item in candidate.get("file_ids", [])),
        "symbols": list(candidate.get("symbols", [])),
        "owned_source_refs": list(candidate.get("owned_source_refs", [])),
        "supporting_source_refs": list(candidate.get("supporting_source_refs", [])),
        "origin_candidate_ids": [str(candidate.get("candidate_id") or "")],
        "reconciliation_ids": [],
        "intentional_shared_symbol_keys": [],
        "confidence": candidate.get("confidence", "unknown"),
        "limitations": list(candidate.get("limitations", [])),
        "validation_provenance": {
            "attempt_id": candidate.get("validation_attempt_id", ""),
            "validated_at": candidate.get("validated_at", ""),
        },
    }


def _derive_dispositions(
    files: Sequence[Mapping[str, object]],
    components: Sequence[Mapping[str, object]],
    explicit: Mapping[str, Mapping[str, object]],
) -> list[dict[str, object]]:
    owned: dict[str, set[str]] = {}
    supporting: dict[str, set[str]] = {}
    revision = str(files[0].get("repository_revision") or "") if files else ""
    for component in components:
        component_id = str(component.get("id") or "")
        for file_id in component.get("file_ids", []):
            owned.setdefault(str(file_id), set()).add(component_id)
        for reference in component.get("owned_source_refs", []):
            if isinstance(reference, Mapping):
                owned.setdefault(str(reference.get("file_id") or ""), set()).add(
                    component_id
                )
        for reference in component.get("supporting_source_refs", []):
            if isinstance(reference, Mapping):
                supporting.setdefault(str(reference.get("file_id") or ""), set()).add(
                    component_id
                )
    records = []
    for file in files:
        file_id = str(file.get("id") or "")
        if owned.get(file_id):
            disposition = "owned"
            members = sorted(owned[file_id])
            reason = "Owned by one or more accepted components."
        elif supporting.get(file_id):
            disposition = "supporting"
            members = sorted(supporting[file_id])
            reason = "Supporting evidence for one or more accepted components."
        elif file_id in explicit:
            disposition = str(explicit[file_id].get("disposition") or "unresolved")
            members = []
            reason = str(explicit[file_id].get("reason") or "")
        else:
            disposition = "unresolved"
            members = []
            reason = "No accepted component or explicit classification covers the file."
        records.append(
            {
                "schema_version": 1,
                "record_type": "file_disposition",
                "repository_revision": revision,
                "file_id": file_id,
                "disposition": disposition,
                "component_ids": members,
                "reason": reason,
            }
        )
    return records


def _coverage(
    revision: str, dispositions: Sequence[Mapping[str, object]]
) -> dict[str, object]:
    counts = {
        disposition: sum(
            1 for item in dispositions if item.get("disposition") == disposition
        )
        for disposition in (
            "owned",
            "supporting",
            "repository_infrastructure",
            "excluded",
            "unresolved",
        )
    }
    return {
        "schema_version": 1,
        "record_type": "file_coverage",
        "repository_revision": revision,
        "in_scope_count": len(dispositions),
        **{f"{key}_count": value for key, value in counts.items()},
        "unresolved_file_ids": sorted(
            str(item.get("file_id") or "")
            for item in dispositions
            if item.get("disposition") == "unresolved"
        ),
        "generated_at": utc_now(),
    }
