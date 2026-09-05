"""Phase 3 component candidate validation and durable promotion."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from electroboy.models import utc_now

from .component_contract import component_candidate_contract_text
from .ctags_evidence import LocatorResolution, SymbolLocatorResolver
from .domain import CodeLearnerError
from .phase3_contracts import (
    Phase3ContractError,
    parse_phase3_jsonl,
    validate_component_candidates,
)
from .phase3_store import Phase3Store
from .skills import skill_prompt_reference
from .source_manifest import SourceManifestService


class LocatorResolver(Protocol):
    def resolve(self, value: Mapping[str, object]) -> LocatorResolution: ...


@dataclass(frozen=True)
class RejectedCandidate:
    candidate: dict[str, object]
    errors: tuple[str, ...]


@dataclass(frozen=True)
class CandidateValidationResult:
    attempt_id: str
    accepted: tuple[dict[str, object], ...]
    rejected: tuple[RejectedCandidate, ...]

    @property
    def complete(self) -> bool:
        return not self.rejected


class ComponentCandidateService:
    """Validate AI candidates while preserving their semantic authorship."""

    def __init__(
        self,
        root: Path | str,
        *,
        resolver: LocatorResolver | None = None,
        store: Phase3Store | None = None,
        source: SourceManifestService | None = None,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = store or Phase3Store(self.root)
        self.source = source or SourceManifestService(self.root)
        self.resolver = resolver or SymbolLocatorResolver(self.root, source=self.source)
        self.candidates_path = self.store.components_root / "candidates.jsonl"
        self.validation_root = self.store.components_root / "validation"

    def ingest(
        self,
        text: str,
        *,
        attempt_id: str,
        replace_existing: bool = False,
    ) -> CandidateValidationResult:
        """Retain one raw attempt and atomically promote valid candidates."""

        attempt = str(attempt_id or "").strip()
        if not attempt:
            raise CodeLearnerError("component candidate attempt ID is required")
        attempt_path = self.store.attempts_root / "components" / f"{attempt}.jsonl"
        attempt_path.parent.mkdir(parents=True, exist_ok=True)
        attempt_path.write_text(text.rstrip() + "\n", encoding="utf-8")
        try:
            records = parse_phase3_jsonl(text, artifact=f"component attempt {attempt}")
        except Phase3ContractError as error:
            result = CandidateValidationResult(
                attempt,
                (),
                (RejectedCandidate({}, tuple(str(issue) for issue in error.issues)),),
            )
            self._save_validation(result)
            return result
        snapshot = self.source.load()
        if snapshot is None:
            raise CodeLearnerError("source manifest must precede component discovery")
        files = snapshot.by_id()
        accepted: list[dict[str, object]] = []
        rejected: list[RejectedCandidate] = []
        for record in records:
            candidate = dict(record)
            errors = self._validate_candidate(
                candidate,
                repository_revision=snapshot.revision,
                files=files,
            )
            if errors:
                rejected.append(RejectedCandidate(candidate, tuple(errors)))
            else:
                candidate["validated_at"] = utc_now()
                candidate["validation_attempt_id"] = attempt
                accepted.append(candidate)
        if accepted or replace_existing:
            self._promote(accepted, replace_existing=replace_existing)
        result = CandidateValidationResult(
            attempt,
            tuple(accepted),
            tuple(rejected),
        )
        self._save_validation(result)
        return result

    def load(self) -> list[dict[str, object]]:
        return self.store.read_jsonl(self.candidates_path)

    def repair_prompt(
        self, rejected: RejectedCandidate, *, schema_path: Path | str
    ) -> str:
        """Build a bounded repair request that cannot rewrite accepted records."""

        candidate = rejected.candidate
        file_ids = candidate.get("file_ids")
        example_file_id = (
            str(file_ids[0])
            if isinstance(file_ids, list) and file_ids
            else "file:replace-with-real-file-id"
        )

        return f"""Repair exactly one Phase 3 component candidate.

{skill_prompt_reference("codebase-analysis")}

Authoritative Phase 3 schema: {Path(schema_path).resolve()}

Rejected candidate:
{json.dumps(candidate, indent=2, sort_keys=True)}

Validation errors:
{chr(10).join(f"- {error}" for error in rejected.errors)}

{component_candidate_contract_text(
    analysis_run_id=str(candidate.get("analysis_run_id") or "run-required"),
    repository_revision=str(
        candidate.get("repository_revision") or "revision-required"
    ),
    example_file_id=example_file_id,
)}

Return one corrected component_candidate JSON object only. Preserve its
semantic name, kind, and responsibility unless an error explicitly concerns
that field. Do not emit or modify any other candidate, module, relationship,
diagram, course, repository file, or ElectroBoy state file.
""".strip()

    def _validate_candidate(
        self,
        candidate: dict[str, object],
        *,
        repository_revision: str,
        files: Mapping[str, Mapping[str, object]],
    ) -> list[str]:
        try:
            validate_component_candidates(
                [candidate],
                repository_revision=repository_revision,
                files=files,
            )
        except Phase3ContractError as error:
            return [str(issue) for issue in error.issues]
        member_files = set(str(item) for item in candidate.get("file_ids", []))
        resolved: list[dict[str, object]] = []
        errors: list[str] = []
        for index, raw_locator in enumerate(candidate.get("symbols", [])):
            if not isinstance(raw_locator, Mapping):
                errors.append(f"symbols[{index}]: must be an object")
                continue
            file_id = str(raw_locator.get("file_id") or "")
            if file_id not in member_files:
                errors.append(f"symbols[{index}].file_id: not a component member file")
                continue
            resolution = self.resolver.resolve(raw_locator)
            if resolution.status != "exact":
                errors.append(
                    f"symbols[{index}]: {resolution.message or resolution.status}"
                )
                continue
            resolved.append(
                {
                    **resolution.locator,
                    "canonical_key": resolution.canonical_key,
                    "validated_by": resolution.provenance,
                }
            )
        for field in ("owned_source_refs", "supporting_source_refs"):
            for index, reference in enumerate(candidate.get(field, [])):
                if not isinstance(reference, Mapping):
                    continue
                file_id = str(reference.get("file_id") or "")
                if field == "owned_source_refs" and file_id not in member_files:
                    errors.append(f"{field}[{index}].file_id: not a member file")
                file = files.get(file_id)
                if file is not None:
                    errors.extend(
                        self._range_errors(reference, file, f"{field}[{index}]")
                    )
        if not errors:
            candidate["symbols"] = resolved
        return errors

    def _range_errors(
        self,
        reference: Mapping[str, object],
        file: Mapping[str, object],
        prefix: str,
    ) -> list[str]:
        path = self.root / str(file.get("path") or "")
        if not path.is_file():
            return [f"{prefix}: source file is unavailable"]
        line_count = max(
            1, len(path.read_text(encoding="utf-8", errors="replace").splitlines())
        )
        end = int(reference.get("end_line") or reference.get("start_line") or 1)
        return [f"{prefix}.end_line: exceeds file length"] if end > line_count else []

    def _promote(
        self,
        accepted: Sequence[Mapping[str, object]],
        *,
        replace_existing: bool = False,
    ) -> None:
        current = {} if replace_existing else {
            str(record.get("candidate_id") or ""): record for record in self.load()
        }
        for record in accepted:
            current[str(record["candidate_id"])] = dict(record)
        self.store.write_jsonl(
            self.candidates_path,
            sorted(current.values(), key=lambda record: str(record["candidate_id"])),
        )

    def _save_validation(self, result: CandidateValidationResult) -> None:
        self.store.write_json(
            self.validation_root / f"{result.attempt_id}.json",
            {
                "schema_version": 1,
                "attempt_id": result.attempt_id,
                "accepted_candidate_ids": [
                    str(record.get("candidate_id") or "") for record in result.accepted
                ],
                "rejected": [
                    {"candidate": item.candidate, "errors": list(item.errors)}
                    for item in result.rejected
                ],
                "complete": result.complete,
                "validated_at": utc_now(),
            },
        )
