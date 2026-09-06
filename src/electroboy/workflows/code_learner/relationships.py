"""Bounded Phase 3 relationships between frozen modules."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from electroboy.adapters.base import AgentInvocation, AgentRuntime
from electroboy.models import utc_now
from electroboy.runtime import runtime_for_role

from .component_manifest import ComponentManifestService
from .contracts import RELATIONSHIP_KINDS
from .domain import CodeLearnerError
from .modules import ModuleSynthesisService
from .phase3_contract_catalog import (
    EVIDENCE_CONFIDENCE_VALUES,
    RELATIONSHIP_DIRECTION_VALUES,
)
from .phase3_contracts import (
    parse_phase3_jsonl,
    validate_knowledge_requests,
    validate_module_relationships,
)
from .phase3_prompts import (
    module_relationship_prompt,
    relationship_conflict_prompt,
)
from .phase3_store import Phase3Store
from .source_manifest import SourceManifestService

RELATIONSHIP_ROLE = "code_learner_analysis"


class RuntimeFactory(Protocol):
    def __call__(self, role: str, root: Path) -> AgentRuntime: ...


ConflictResolver = Callable[
    [Mapping[str, object], Mapping[str, object], str], Mapping[str, object]
]


@dataclass(frozen=True)
class RelationshipScope:
    key: str
    module_id: str


class ModuleRelationshipService:
    """Generate, validate, and atomically persist one global module graph."""

    def __init__(
        self,
        root: Path | str,
        *,
        store: Phase3Store | None = None,
        source: SourceManifestService | None = None,
        components: ComponentManifestService | None = None,
        modules: ModuleSynthesisService | None = None,
        runtime_factory: RuntimeFactory | None = None,
        max_attempts: int = 2,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = store or Phase3Store(self.root)
        self.source = source or SourceManifestService(self.root)
        self.components = components or ComponentManifestService(self.root)
        self.modules = modules or ModuleSynthesisService(self.root)
        self.runtime_factory = runtime_factory or _runtime_factory
        self.max_attempts = max(1, max_attempts)
        self.relationships_path = self.store.modules_root / "relationships.jsonl"
        self.requests_path = self.store.modules_root / "relationship-requests.jsonl"
        self.scope_root = self.store.modules_root / "relationship-scopes"

    def scopes(self) -> list[RelationshipScope]:
        snapshot = self._module_snapshot()
        return [
            RelationshipScope(f"module:{index:04d}", str(module["id"]))
            for index, module in enumerate(snapshot.modules, start=1)
        ]

    def generate(
        self,
        *,
        analysis_run_id: str,
        conflict_resolver: ConflictResolver | None = None,
    ) -> list[dict[str, object]]:
        runtime = self.runtime_factory(RELATIONSHIP_ROLE, self.root)
        scope = RelationshipScope("global", "")
        last_error = ""
        for attempt in range(1, self.max_attempts + 1):
            prompt = self._prompt(analysis_run_id)
            if last_error:
                prompt += f"\n\nPrevious output error:\n- {last_error}"
            result = runtime.invoke(
                AgentInvocation(
                    role=RELATIONSHIP_ROLE,
                    prompt=prompt,
                    context_paths=self._context_paths(),
                )
            )
            self.store.write_json(
                self.store.attempts_root
                / "relationships"
                / f"global-{attempt}.json",
                {
                    "scope": "global",
                    "attempt": attempt,
                    "output": result.final_message,
                    "error": result.error or "",
                    "recorded_at": utc_now(),
                },
            )
            if not result.ok:
                last_error = result.error or "relationship runtime failed"
                continue
            try:
                return self.ingest_scope(
                    scope,
                    result.final_message,
                    conflict_resolver=conflict_resolver,
                )
            except CodeLearnerError as error:
                last_error = str(error)
        raise CodeLearnerError(
            "global relationship model failed after "
            f"{self.max_attempts} attempts: {last_error}"
        )

    def ingest_scope(
        self,
        scope: RelationshipScope,
        text: str,
        *,
        conflict_resolver: ConflictResolver | None = None,
    ) -> list[dict[str, object]]:
        records = (
            parse_phase3_jsonl(text, artifact=f"relationship scope {scope.key}")
            if text.strip()
            else []
        )
        relationships = [
            record
            for record in records
            if record.get("record_type") == "module_relationship"
        ]
        requests = [
            record
            for record in records
            if record.get("record_type") == "knowledge_request"
        ]
        if len(relationships) + len(requests) != len(records):
            raise CodeLearnerError(
                "relationship scope emitted a prohibited record type"
            )
        revision, modules, components, files = self._catalogs()
        grounded_relationships = []
        for record in relationships:
            endpoints = {
                str(record.get("from_module_id") or ""),
                str(record.get("to_module_id") or ""),
            }
            unknown = sorted(endpoints - set(modules))
            if not unknown:
                grounded_relationships.append(record)
                continue
            source_refs = list(record.get("source_refs", []))
            if not source_refs:
                raise CodeLearnerError(
                    "unknown relationship endpoints require hard source references"
                )
            request_identity = hashlib.sha256("\0".join(unknown).encode()).hexdigest()[
                :16
            ]
            requests.append(
                {
                    "schema_version": 1,
                    "record_type": "knowledge_request",
                    "repository_revision": revision,
                    "id": f"request:missing-endpoint:{request_identity}",
                    "request_type": "missing_endpoint",
                    "status": "open",
                    "reason": "Unknown module endpoints: " + ", ".join(unknown),
                    "unknown_endpoint_ids": unknown,
                    "source_refs": source_refs,
                }
            )
        relationships = grounded_relationships
        if requests:
            validate_knowledge_requests(requests, repository_revision=revision)
            existing = {
                str(item.get("id") or ""): item
                for item in self.store.read_jsonl(self.requests_path)
            }
            existing.update({str(item["id"]): item for item in requests})
            self.store.write_jsonl(
                self.requests_path, [existing[key] for key in sorted(existing)]
            )
        normalized = [dict(record) for record in relationships]
        if scope.module_id and any(
            scope.module_id
            not in {record.get("from_module_id"), record.get("to_module_id")}
            for record in normalized
        ):
            raise CodeLearnerError(
                "relationship does not touch its bounded module scope"
            )
        self._validate_details(normalized, modules, components, files, revision)
        normalized = self._deduplicate(normalized, conflict_resolver)
        for record in normalized:
            record["id"] = _relationship_id(record)
            record["repository_revision"] = revision
            record["scope_key"] = scope.key
        validate_module_relationships(
            normalized,
            repository_revision=revision,
            module_ids=set(modules),
            component_ids=set(components),
        )
        self.store.write_jsonl(
            self.scope_root / f"{_safe(scope.key)}.jsonl",
            sorted(normalized, key=lambda item: str(item["id"])),
        )
        if scope.key == "global":
            for path in self.scope_root.glob("*.jsonl"):
                if path.name != "global.jsonl":
                    path.unlink(missing_ok=True)
            self.store.write_jsonl(
                self.relationships_path,
                sorted(normalized, key=lambda item: str(item["id"])),
            )
        return normalized

    def rebuild(self) -> list[dict[str, object]]:
        records = []
        seen = set()
        for path in sorted(self.scope_root.glob("*.jsonl")):
            for record in self.store.read_jsonl(path):
                identity = str(record.get("id") or "")
                if identity not in seen:
                    records.append(record)
                    seen.add(identity)
        records.sort(key=lambda item: str(item.get("id") or ""))
        self.store.write_jsonl(self.relationships_path, records)
        return records

    def _validate_details(
        self,
        records: Sequence[Mapping[str, object]],
        modules: Mapping[str, Mapping[str, object]],
        components: Mapping[str, Mapping[str, object]],
        files: Mapping[str, Mapping[str, object]],
        revision: str,
    ) -> None:
        validate_module_relationships(
            records,
            repository_revision=revision,
            module_ids=set(modules),
            component_ids=set(components),
        )
        for index, record in enumerate(records):
            if record.get("kind") not in RELATIONSHIP_KINDS:
                raise CodeLearnerError(f"relationships[{index}].kind is unsupported")
            if record.get("direction") not in RELATIONSHIP_DIRECTION_VALUES:
                raise CodeLearnerError(f"relationships[{index}].direction is required")
            if record.get("confidence") not in EVIDENCE_CONFIDENCE_VALUES:
                raise CodeLearnerError(f"relationships[{index}].confidence is required")
            if "condition" not in record or "limitations" not in record:
                raise CodeLearnerError(
                    f"relationships[{index}] needs condition and limitations"
                )
            if not isinstance(record.get("condition"), str):
                raise CodeLearnerError(
                    f"relationships[{index}].condition must be a string"
                )
            limitations = record.get("limitations")
            if not isinstance(limitations, list) or any(
                not isinstance(item, str) for item in limitations
            ):
                raise CodeLearnerError(
                    f"relationships[{index}].limitations must be strings"
                )
            source_id = str(record.get("from_module_id") or "")
            target_id = str(record.get("to_module_id") or "")
            allowed_components = set(modules[source_id].get("component_ids", [])) | set(
                modules[target_id].get("component_ids", [])
            )
            supporting = set(record.get("supporting_component_ids", []))
            if not supporting or supporting - allowed_components:
                raise CodeLearnerError(
                    f"relationships[{index}] has invalid supporting components"
                )
            refs = record.get("source_refs", [])
            if not refs:
                raise CodeLearnerError(
                    f"relationships[{index}].source_refs must not be empty"
                )
            for reference in refs:
                if not isinstance(reference, Mapping):
                    raise CodeLearnerError("relationship source reference is invalid")
                file_id = str(reference.get("file_id") or "")
                if file_id not in files:
                    raise CodeLearnerError("relationship cites an unknown source file")
                start = reference.get("start_line")
                end = reference.get("end_line")
                if (
                    not isinstance(start, int)
                    or isinstance(start, bool)
                    or not isinstance(end, int)
                    or isinstance(end, bool)
                    or start < 1
                    or end < start
                ):
                    raise CodeLearnerError("relationship source range is invalid")
                if not str(reference.get("reason") or "").strip():
                    raise CodeLearnerError(
                        "relationship source reference needs a reason"
                    )
            if (
                source_id == target_id
                and not str(record.get("self_relationship_reason") or "").strip()
            ):
                raise CodeLearnerError("self relationship needs an explicit reason")

    def _deduplicate(
        self,
        records: Sequence[Mapping[str, object]],
        resolver: ConflictResolver | None,
    ) -> list[dict[str, object]]:
        accepted: dict[tuple[str, str, str, str], dict[str, object]] = {}
        for record in records:
            payload = dict(record)
            key = (
                str(payload.get("from_module_id") or ""),
                str(payload.get("to_module_id") or ""),
                str(payload.get("kind") or ""),
                str(payload.get("condition") or ""),
            )
            existing = accepted.get(key)
            if existing is None:
                accepted[key] = payload
                continue
            if _semantic_payload(existing) == _semantic_payload(payload):
                continue
            if resolver is None:
                raise CodeLearnerError(
                    "contradictory module edges require focused reconciliation"
                )
            prompt = relationship_conflict_prompt(
                left=existing,
                right=payload,
                schema_path=Path(__file__).with_name("schemas")
                / "phase3.schema.json",
            )
            resolved = dict(resolver(existing, payload, prompt))
            revision, modules, components, files = self._catalogs()
            self._validate_details([resolved], modules, components, files, revision)
            accepted[key] = resolved
        return [accepted[key] for key in sorted(accepted)]

    def _prompt(self, run_id: str) -> str:
        module_snapshot = self._module_snapshot()
        revision = str(module_snapshot.manifest["repository_revision"])
        return module_relationship_prompt(
            self.root,
            analysis_run_id=run_id,
            repository_revision=revision,
            source_manifest_path=self.source.manifest_path,
            component_manifest_path=self.components.manifest_path,
            components_path=self.components.components_path,
            module_manifest_path=self.modules.manifest_path,
            modules_path=self.modules.modules_path,
            relationship_kinds=sorted(RELATIONSHIP_KINDS),
            schema_path=Path(__file__).with_name("schemas") / "phase3.schema.json",
        )

    def _catalogs(self):
        source = self.source.load()
        component_snapshot = self.components.load()
        module_snapshot = self._module_snapshot()
        if source is None or component_snapshot is None:
            raise CodeLearnerError("relationship evidence manifests are missing")
        return (
            source.revision,
            {str(item["id"]): item for item in module_snapshot.modules},
            {str(item["id"]): item for item in component_snapshot.components},
            source.by_id(),
        )

    def _module_snapshot(self):
        snapshot = self.modules.load()
        if snapshot is None or snapshot.manifest.get("frozen") is not True:
            raise CodeLearnerError(
                "a frozen module manifest must precede relationship generation"
            )
        return snapshot

    def _context_paths(self) -> list[str]:
        return [
            path.relative_to(self.root).as_posix()
            for path in (
                self.source.manifest_path,
                self.components.manifest_path,
                self.components.components_path,
                self.modules.manifest_path,
                self.modules.modules_path,
            )
            if path.is_file()
        ]


def _relationship_id(record: Mapping[str, object]) -> str:
    identity = json.dumps(_semantic_payload(record), sort_keys=True)
    return f"relationship:{hashlib.sha256(identity.encode()).hexdigest()[:24]}"


def _semantic_payload(record: Mapping[str, object]) -> dict[str, object]:
    return {
        key: value
        for key, value in record.items()
        if key
        not in {
            "id",
            "scope_key",
            "accepted_at",
            "analysis_run_id",
        }
    }


def _safe(value: str) -> str:
    return "".join(character if character.isalnum() else "-" for character in value)


def _runtime_factory(role: str, root: Path) -> AgentRuntime:
    return runtime_for_role(role, root, execution_root=root)
