"""Focused AI reconciliation for exact component-symbol overlap groups."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from electroboy.adapters.base import AgentInvocation, AgentResult, AgentRuntime
from electroboy.models import utc_now
from electroboy.runtime import runtime_for_role

from .domain import CodeLearnerError
from .phase3_contracts import (
    Phase3ContractError,
    parse_phase3_jsonl,
    validate_reconciliations,
)
from .phase3_prompts import component_reconciliation_prompt
from .phase3_store import Phase3Store
from .skills import validate_packaged_skill

RECONCILIATION_ROLE = "code_learner_analysis"


class RuntimeFactory(Protocol):
    def __call__(self, role: str, root: Path) -> AgentRuntime: ...


@dataclass(frozen=True)
class ReconciliationResult:
    """One accepted overlap decision and its resolved component partitions."""

    record: dict[str, object]
    resolved_partitions: tuple[dict[str, object], ...]


class ComponentReconciliationService:
    """Reconcile overlap groups independently and preserve exact provenance."""

    def __init__(
        self,
        root: Path | str,
        *,
        store: Phase3Store | None = None,
        runtime_factory: RuntimeFactory | None = None,
        max_attempts: int = 2,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = store or Phase3Store(self.root)
        self.runtime_factory = runtime_factory or _runtime_factory
        self.max_attempts = max(1, max_attempts)
        self.candidates_path = self.store.components_root / "candidates.jsonl"
        self.groups_path = self.store.components_root / "overlap-groups.jsonl"
        self.reconciliations_path = self.store.components_root / "reconciliations.jsonl"
        self.result_root = self.store.components_root / "reconciliations"

    def pending_group_ids(self) -> list[str]:
        completed = {
            str(record.get("overlap_group_id") or "") for record in self.load()
        }
        return [
            str(group.get("id") or "")
            for group in self._groups()
            if str(group.get("id") or "") not in completed
        ]

    def reconcile_pending(self, *, analysis_run_id: str) -> list[dict[str, object]]:
        """Resume at the first unresolved group and isolate retries by group."""

        validate_packaged_skill("codebase-analysis")
        for group_id in self.pending_group_ids():
            self.reconcile_group(group_id, analysis_run_id=analysis_run_id)
        return self.load()

    def reconcile_group(
        self,
        group_id: str,
        *,
        analysis_run_id: str,
    ) -> ReconciliationResult:
        group, candidates = self._scope(group_id)
        runtime = self.runtime_factory(RECONCILIATION_ROLE, self.root)
        previous_error = ""
        for attempt in range(1, self.max_attempts + 1):
            prompt = component_reconciliation_prompt(
                self.root,
                analysis_run_id=analysis_run_id,
                group=group,
                candidates=candidates,
                source_manifest_path=self.root
                / ".electroboy/code-learner/phase3/source/manifest.json",
                files_path=self.root
                / ".electroboy/code-learner/phase3/source/files.jsonl",
                schema_path=Path(__file__).with_name("schemas") / "phase3.schema.json",
            )
            if previous_error:
                prompt = self.repair_prompt(group_id, previous_error, prompt)
            invocation = AgentInvocation(
                role=RECONCILIATION_ROLE,
                prompt=prompt,
                context_paths=self._context_paths(),
            )
            result = runtime.invoke(invocation)
            attempt_id = f"{_safe_id(group_id)}-{attempt}"
            if not result.ok:
                previous_error = (
                    result.error or result.final_message or "analysis runtime failed"
                )
                self._save_attempt(attempt_id, result, previous_error)
                continue
            try:
                accepted = self.ingest(
                    group_id,
                    result.final_message,
                    attempt_id=attempt_id,
                )
            except CodeLearnerError as error:
                previous_error = str(error)
                self._save_attempt(attempt_id, result, previous_error)
                continue
            return accepted
        raise CodeLearnerError(
            f"component overlap group {group_id} failed after "
            f"{self.max_attempts} attempts: {previous_error}"
        )

    def ingest(
        self,
        group_id: str,
        text: str,
        *,
        attempt_id: str,
    ) -> ReconciliationResult:
        """Validate and atomically persist one complete group decision."""

        group, candidates = self._scope(group_id)
        raw_path = self.store.attempts_root / "reconciliations" / f"{attempt_id}.jsonl"
        raw_path.parent.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(text.rstrip() + "\n", encoding="utf-8")
        records = parse_phase3_jsonl(text, artifact=f"reconciliation {group_id}")
        if len(records) != 1:
            raise CodeLearnerError("reconciliation must return exactly one record")
        try:
            record = validate_reconciliations(
                records,
                groups={group_id: group},
            )[0]
        except Phase3ContractError as error:
            raise CodeLearnerError(str(error)) from error
        self._validate_scope(record, candidates)
        record.update(
            {
                "id": f"reconciliation:{_safe_id(group_id)}",
                "repository_revision": group.get("repository_revision", ""),
                "candidate_revision": group.get("candidate_revision", ""),
                "analysis_run_id": str(record.get("analysis_run_id") or ""),
                "accepted_at": utc_now(),
                "attempt_id": attempt_id,
            }
        )
        resolved = self._resolve_partitions(record, candidates, group)
        record["resolved_partitions"] = resolved
        self.store.write_json(self.result_root / f"{_safe_id(group_id)}.json", record)
        current = {
            str(item.get("overlap_group_id") or ""): item for item in self.load()
        }
        current[group_id] = record
        self.store.write_jsonl(
            self.reconciliations_path,
            [current[key] for key in sorted(current)],
        )
        return ReconciliationResult(record, tuple(resolved))

    def load(self) -> list[dict[str, object]]:
        return self.store.read_jsonl(self.reconciliations_path)

    def repair_prompt(self, group_id: str, error: str, original: str) -> str:
        return f"""{original}

Your previous response for {group_id} was rejected:
- {error}

Repair only this overlap group's one component_reconciliation object. Keep
every candidate exactly once and do not modify prior groups or emit other
record types.
""".strip()

    def _scope(
        self, group_id: str
    ) -> tuple[dict[str, object], list[dict[str, object]]]:
        groups = {str(item.get("id") or ""): item for item in self._groups()}
        group = groups.get(group_id)
        if group is None:
            raise CodeLearnerError(f"unknown component overlap group: {group_id}")
        by_id = {
            str(item.get("candidate_id") or ""): item
            for item in self.store.read_jsonl(self.candidates_path)
        }
        candidates = []
        for candidate_id in group.get("candidate_ids", []):
            candidate = by_id.get(str(candidate_id))
            if candidate is None:
                raise CodeLearnerError(
                    f"overlap group references missing candidate: {candidate_id}"
                )
            candidates.append(candidate)
        return group, candidates

    def _groups(self) -> list[dict[str, object]]:
        return self.store.read_jsonl(self.groups_path)

    def _validate_scope(
        self,
        record: Mapping[str, object],
        candidates: Sequence[Mapping[str, object]],
    ) -> None:
        allowed_top = {
            "schema_version",
            "record_type",
            "repository_revision",
            "analysis_run_id",
            "overlap_group_id",
            "decision",
            "partitions",
            "reason",
            "limitations",
        }
        unknown = sorted(set(record) - allowed_top)
        if unknown:
            raise CodeLearnerError(
                f"reconciliation contains prohibited fields: {', '.join(unknown)}"
            )
        allowed_files = {
            str(file_id)
            for candidate in candidates
            for file_id in candidate.get("file_ids", [])
        }
        allowed_symbols = {
            str(symbol.get("canonical_key") or "")
            for candidate in candidates
            for symbol in candidate.get("symbols", [])
            if isinstance(symbol, Mapping)
        }
        allowed_partition = {
            "candidate_ids",
            "name",
            "aliases",
            "kind",
            "responsibility",
            "file_ids",
            "symbol_canonical_keys",
            "owned_source_refs",
            "supporting_source_refs",
            "reason",
            "limitations",
        }
        for index, partition in enumerate(record.get("partitions", [])):
            unknown = sorted(set(partition) - allowed_partition)
            if unknown:
                raise CodeLearnerError(
                    f"partitions[{index}] contains prohibited fields: "
                    f"{', '.join(unknown)}"
                )
            files = {str(item) for item in partition.get("file_ids", [])}
            if files - allowed_files:
                raise CodeLearnerError(
                    f"partitions[{index}] introduces external file IDs"
                )
            symbols = {str(item) for item in partition.get("symbol_canonical_keys", [])}
            if symbols - allowed_symbols:
                raise CodeLearnerError(
                    f"partitions[{index}] introduces external symbol keys"
                )
            for field in ("owned_source_refs", "supporting_source_refs"):
                for reference in partition.get(field, []):
                    if not isinstance(reference, Mapping):
                        raise CodeLearnerError(
                            f"partitions[{index}].{field} must contain objects"
                        )
                    if str(reference.get("file_id") or "") not in allowed_files:
                        raise CodeLearnerError(
                            f"partitions[{index}].{field} introduces an external file"
                        )

    def _resolve_partitions(
        self,
        record: Mapping[str, object],
        candidates: Sequence[Mapping[str, object]],
        group: Mapping[str, object],
    ) -> list[dict[str, object]]:
        by_id = {
            str(candidate.get("candidate_id") or ""): candidate
            for candidate in candidates
        }
        result = []
        for partition in record.get("partitions", []):
            ids = [str(item) for item in partition.get("candidate_ids", [])]
            members = [by_id[item] for item in ids]
            names = [str(item.get("name") or "") for item in members]
            aliases = {
                alias
                for item in members
                for alias in [str(item.get("name") or ""), *item.get("aliases", [])]
                if alias
            }
            chosen_name = str(partition.get("name") or names[0])
            aliases.update(str(item) for item in partition.get("aliases", []))
            aliases.discard(chosen_name)
            result.append(
                {
                    "name": chosen_name,
                    "aliases": sorted(aliases),
                    "kind": str(partition.get("kind") or members[0].get("kind") or ""),
                    "responsibility": str(
                        partition.get("responsibility")
                        or members[0].get("responsibility")
                        or ""
                    ),
                    "file_ids": _union_strings(members, "file_ids"),
                    "symbols": _union_objects(members, "symbols", "canonical_key"),
                    "owned_source_refs": _union_objects(
                        members, "owned_source_refs", ""
                    ),
                    "supporting_source_refs": _union_objects(
                        members, "supporting_source_refs", ""
                    ),
                    "origin_candidate_ids": sorted(ids),
                    "reconciliation_ids": [str(record.get("id") or "")],
                    "intentional_shared_symbol_keys": (
                        sorted(
                            {
                                str(edge.get("canonical_key") or "")
                                for edge in group.get("shared_symbol_edges", [])
                                if isinstance(edge, Mapping)
                                and set(ids)
                                & {str(item) for item in edge.get("candidate_ids", [])}
                            }
                        )
                        if len(record.get("partitions", [])) > 1
                        else []
                    ),
                    "reconciliation_reason": str(partition.get("reason") or ""),
                    "limitations": sorted(
                        {
                            str(value)
                            for member in members
                            for value in member.get("limitations", [])
                        }
                        | {str(value) for value in partition.get("limitations", [])}
                    ),
                }
            )
        return result

    def _save_attempt(self, attempt_id: str, result: AgentResult, error: str) -> None:
        self.store.write_json(
            self.store.attempts_root / "reconciliations" / f"{attempt_id}.json",
            {
                "attempt_id": attempt_id,
                "ok": result.ok,
                "output": result.final_message,
                "error": error,
                "recorded_at": utc_now(),
            },
        )

    def _context_paths(self) -> list[str]:
        return [
            path.relative_to(self.root).as_posix()
            for path in (
                self.groups_path,
                self.candidates_path,
                self.root / ".electroboy/code-learner/phase3/source/manifest.json",
                self.root / ".electroboy/code-learner/phase3/source/files.jsonl",
            )
            if path.is_file()
        ]


def _safe_id(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value)


def _union_strings(records: Sequence[Mapping[str, object]], field: str) -> list[str]:
    return sorted({str(value) for record in records for value in record.get(field, [])})


def _union_objects(
    records: Sequence[Mapping[str, object]], field: str, identity_field: str
) -> list[dict[str, object]]:
    values: dict[str, dict[str, object]] = {}
    for record in records:
        for value in record.get(field, []):
            if not isinstance(value, Mapping):
                continue
            payload = dict(value)
            key = (
                str(payload.get(identity_field) or "")
                if identity_field
                else json.dumps(payload, sort_keys=True)
            )
            values[key] = payload
    return [values[key] for key in sorted(values)]


def _runtime_factory(role: str, root: Path) -> AgentRuntime:
    return runtime_for_role(role, root, execution_root=root)
