"""Phase 3 module synthesis over the frozen canonical component manifest."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from electroboy.adapters.base import AgentInvocation, AgentRuntime
from electroboy.models import utc_now
from electroboy.runtime import runtime_for_role

from .agent_retry import RetryableAgentError, parse_agent_jsonl, require_agent_output
from .component_manifest import ComponentManifestService, ComponentManifestSnapshot
from .domain import CodeLearnerError
from .phase3_contracts import (
    parse_phase3_jsonl,
    validate_knowledge_requests,
    validate_manifest,
    validate_modules,
)
from .phase3_prompts import module_synthesis_prompt
from .phase3_store import Phase3Store
from .source_manifest import SourceManifestService

MODULE_ROLE = "code_learner_analysis"


class RuntimeFactory(Protocol):
    def __call__(self, role: str, root: Path) -> AgentRuntime: ...


TargetedDiscovery = Callable[
    [Sequence[Mapping[str, object]]], ComponentManifestSnapshot
]


@dataclass(frozen=True)
class ModuleManifestSnapshot:
    manifest: dict[str, object]
    modules: tuple[dict[str, object], ...]


class ModuleSynthesisService:
    """Validate AI module groupings and replace temporary IDs with opaque IDs."""

    def __init__(
        self,
        root: Path | str,
        *,
        store: Phase3Store | None = None,
        source: SourceManifestService | None = None,
        components: ComponentManifestService | None = None,
        runtime_factory: RuntimeFactory | None = None,
        max_attempts: int = 2,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = store or Phase3Store(self.root)
        self.source = source or SourceManifestService(self.root)
        self.components = components or ComponentManifestService(self.root)
        self.runtime_factory = runtime_factory or _runtime_factory
        self.max_attempts = max(1, max_attempts)
        self.modules_path = self.store.modules_root / "modules.jsonl"
        self.manifest_path = self.store.modules_root / "manifest.json"
        self.requests_path = self.store.modules_root / "requests.jsonl"
        self.attempts_root = self.store.attempts_root / "modules"

    def synthesize(
        self,
        *,
        analysis_run_id: str,
        targeted_discovery: TargetedDiscovery | None = None,
    ) -> ModuleManifestSnapshot:
        component_snapshot = self._component_snapshot()
        runtime = self.runtime_factory(MODULE_ROLE, self.root)
        affected: list[str] = []
        previous_error = ""
        discovery_used = False
        for attempt in range(1, self.max_attempts + 1):
            prompt = module_synthesis_prompt(
                self.root,
                analysis_run_id=analysis_run_id,
                repository_revision=str(
                    component_snapshot.manifest["repository_revision"]
                ),
                source_manifest_path=self.source.manifest_path,
                component_manifest_path=self.components.manifest_path,
                components_path=self.components.components_path,
                schema_path=Path(__file__).with_name("schemas") / "phase3.schema.json",
                affected_component_ids=affected,
                existing_modules_path=(
                    self.modules_path if self.modules_path.is_file() else None
                ),
            )
            if previous_error:
                prompt += (
                    "\n\nThe previous module output was rejected:\n- "
                    + previous_error
                    + "\nRepair only module synthesis output."
                )
            result = runtime.invoke(
                AgentInvocation(
                    role=MODULE_ROLE,
                    prompt=prompt,
                    context_paths=self._context_paths(),
                )
            )
            self._save_attempt(attempt, result.final_message, result.error or "")
            try:
                output = require_agent_output(result, operation="Module synthesis")
                records = parse_agent_jsonl(
                    output,
                    artifact="module synthesis",
                    parser=parse_phase3_jsonl,
                )
            except RetryableAgentError as error:
                previous_error = str(error)
                continue
            requests = [
                record
                for record in records
                if record.get("record_type") == "knowledge_request"
            ]
            modules = [
                record for record in records if record.get("record_type") == "module"
            ]
            if len(requests) + len(modules) != len(records):
                raise CodeLearnerError(
                    "module synthesis emitted a prohibited record type"
                )
            known_components = set(component_snapshot.manifest["component_ids"])
            for module in modules:
                unknown = sorted(
                    {
                        str(item)
                        for item in module.get("component_ids", [])
                        if item not in known_components
                    }
                )
                if not unknown:
                    continue
                source_refs = list(module.get("source_refs", []))
                if not source_refs:
                    raise CodeLearnerError(
                        "unknown component IDs require hard source references"
                    )
                requests.append(
                    {
                        "schema_version": 1,
                        "record_type": "knowledge_request",
                        "repository_revision": component_snapshot.manifest[
                            "repository_revision"
                        ],
                        "id": f"request:inline-module-{attempt}",
                        "request_type": "missing_component",
                        "status": "open",
                        "reason": (
                            "Module synthesis referenced missing components: "
                            + ", ".join(unknown)
                        ),
                        "missing_component_ids": unknown,
                        "source_refs": source_refs,
                    }
                )
            if requests:
                validate_knowledge_requests(
                    requests,
                    repository_revision=str(
                        component_snapshot.manifest["repository_revision"]
                    ),
                )
                if targeted_discovery is None or discovery_used:
                    raise CodeLearnerError(
                        "module synthesis has unresolved missing-component requests"
                    )
                self.store.write_jsonl(self.requests_path, requests)
                before = set(component_snapshot.manifest["component_ids"])
                component_snapshot = targeted_discovery(requests)
                after = set(component_snapshot.manifest["component_ids"])
                affected = sorted(str(item) for item in after - before)
                discovery_used = True
                previous_error = ""
                continue
            return self.ingest(
                modules,
                analysis_run_id=analysis_run_id,
                component_snapshot=component_snapshot,
            )
        raise CodeLearnerError(
            f"module synthesis failed after {self.max_attempts} attempts: "
            f"{previous_error}"
        )

    def ingest(
        self,
        records: Sequence[Mapping[str, object]],
        *,
        analysis_run_id: str,
        component_snapshot: ComponentManifestSnapshot | None = None,
    ) -> ModuleManifestSnapshot:
        """Validate one complete module set and atomically freeze it."""

        component_snapshot = component_snapshot or self._component_snapshot()
        revision = str(component_snapshot.manifest["repository_revision"])
        component_ids = {
            str(component["id"]) for component in component_snapshot.components
        }
        temporary = [dict(record) for record in records]
        temporary_ids = [str(record.get("id") or "") for record in temporary]
        if len(temporary_ids) != len(set(temporary_ids)):
            raise CodeLearnerError("module invocation-local IDs must be unique")
        validate_modules(
            temporary,
            repository_revision=revision,
            component_ids=component_ids,
        )
        self._validate_semantics(temporary, component_snapshot)
        canonical = self._canonicalize(temporary, revision=revision)
        validate_modules(
            canonical,
            repository_revision=revision,
            component_ids=component_ids,
        )
        primary = {}
        for module in canonical:
            for component_id in module.get("primary_for_component_ids", []):
                primary[str(component_id)] = str(module["id"])
        manifest = {
            "schema_version": 1,
            "record_type": "module_manifest",
            "id": "module_manifest:current",
            "learner_generation": "phase3",
            "analysis_run_id": analysis_run_id,
            "repository_revision": revision,
            "component_manifest_id": component_snapshot.manifest["id"],
            "module_ids": [str(module["id"]) for module in canonical],
            "module_count": len(canonical),
            "primary_module_by_component": primary,
            "status": "complete",
            "frozen": True,
            "generated_at": utc_now(),
        }
        validate_manifest(
            manifest,
            manifest_type="module_manifest",
            repository_revision=revision,
        )
        self.store.write_jsonl(self.modules_path, canonical)
        self.store.write_json(self.manifest_path, manifest)
        return ModuleManifestSnapshot(manifest, tuple(canonical))

    def load(self) -> ModuleManifestSnapshot | None:
        manifest = self.store.read_json(self.manifest_path)
        if manifest is None:
            return None
        component_snapshot = self._component_snapshot()
        revision = str(component_snapshot.manifest["repository_revision"])
        modules = self.store.read_jsonl(self.modules_path)
        validate_manifest(
            manifest,
            manifest_type="module_manifest",
            repository_revision=revision,
        )
        validate_modules(
            modules,
            repository_revision=revision,
            component_ids={
                str(component["id"]) for component in component_snapshot.components
            },
        )
        return ModuleManifestSnapshot(manifest, tuple(modules))

    def by_id(self, module_id: str) -> dict[str, object] | None:
        snapshot = self.load()
        if snapshot is None:
            return None
        return next(
            (dict(item) for item in snapshot.modules if item.get("id") == module_id),
            None,
        )

    def by_component(self, component_id: str) -> list[dict[str, object]]:
        snapshot = self.load()
        if snapshot is None:
            return []
        return [
            dict(item)
            for item in snapshot.modules
            if component_id in item.get("component_ids", [])
        ]

    def _validate_semantics(
        self,
        modules: Sequence[Mapping[str, object]],
        component_snapshot: ComponentManifestSnapshot,
    ) -> None:
        by_component = {
            str(component["id"]): component
            for component in component_snapshot.components
        }
        membership = Counter(
            str(component_id)
            for module in modules
            for component_id in module.get("component_ids", [])
        )
        missing = set(by_component) - set(membership)
        if missing:
            raise CodeLearnerError(
                "components are neither grouped nor intentionally ungrouped: "
                + ", ".join(sorted(missing))
            )
        primary = Counter(
            str(component_id)
            for module in modules
            for component_id in module.get("primary_for_component_ids", [])
        )
        if any(count > 1 for count in primary.values()):
            raise CodeLearnerError("a component has more than one primary module")
        for index, module in enumerate(modules):
            prefix = f"modules[{index}]"
            for field in ("responsibility", "grouping_rationale"):
                if not str(module.get(field) or "").strip():
                    raise CodeLearnerError(f"{prefix}.{field} is required")
            members = {str(item) for item in module.get("component_ids", [])}
            for field in (
                "primary_component_ids",
                "entry_component_ids",
                "primary_for_component_ids",
            ):
                values = {str(item) for item in module.get(field, [])}
                if values - members:
                    raise CodeLearnerError(f"{prefix}.{field} must be module members")
            repeated = {item for item in members if membership[item] > 1}
            rationales = module.get("repeated_component_rationales", {})
            if repeated and (
                not isinstance(rationales, Mapping)
                or any(not str(rationales.get(item) or "").strip() for item in repeated)
            ):
                raise CodeLearnerError(
                    f"{prefix}.repeated_component_rationales is incomplete"
                )
            allowed_files = {
                str(file_id)
                for component_id in members
                for file_id in by_component[component_id].get("file_ids", [])
            } | {
                str(reference.get("file_id") or "")
                for component_id in members
                for reference in by_component[component_id].get(
                    "supporting_source_refs", []
                )
                if isinstance(reference, Mapping)
            }
            for reference in module.get("source_refs", []):
                if (
                    not isinstance(reference, Mapping)
                    or str(reference.get("file_id") or "") not in allowed_files
                ):
                    raise CodeLearnerError(
                        f"{prefix}.source_refs cites source outside member components"
                    )
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
                    raise CodeLearnerError(
                        f"{prefix}.source_refs has an invalid source range"
                    )
                if not str(reference.get("reason") or "").strip():
                    raise CodeLearnerError(
                        f"{prefix}.source_refs needs a non-empty reason"
                    )

    def _canonicalize(
        self, modules: Sequence[Mapping[str, object]], *, revision: str
    ) -> list[dict[str, object]]:
        existing = {
            str(module.get("origin_module_id") or ""): str(module.get("id") or "")
            for module in self.store.read_jsonl(self.modules_path)
        }
        id_map = {
            str(module["id"]): existing.get(str(module["id"]))
            or f"module:{uuid4().hex}"
            for module in modules
        }
        result = []
        for module in modules:
            temporary_id = str(module["id"])
            parent = str(module.get("parent_module_id") or "")
            result.append(
                {
                    **dict(module),
                    "id": id_map[temporary_id],
                    "origin_module_id": temporary_id,
                    "repository_revision": revision,
                    "parent_module_id": id_map.get(parent) if parent else None,
                }
            )
        return result

    def _component_snapshot(self) -> ComponentManifestSnapshot:
        snapshot = self.components.load()
        if snapshot is None or snapshot.manifest.get("frozen") is not True:
            raise CodeLearnerError(
                "a frozen component manifest must precede module synthesis"
            )
        return snapshot

    def _save_attempt(self, attempt: int, output: str, error: str) -> None:
        self.store.write_json(
            self.attempts_root / f"attempt-{attempt}.json",
            {
                "attempt": attempt,
                "output": output,
                "error": error,
                "recorded_at": utc_now(),
            },
        )

    def _context_paths(self) -> list[str]:
        return [
            path.relative_to(self.root).as_posix()
            for path in (
                self.source.manifest_path,
                self.components.manifest_path,
                self.components.components_path,
                self.modules_path,
            )
            if path.is_file()
        ]


def _runtime_factory(role: str, root: Path) -> AgentRuntime:
    return runtime_for_role(role, root, execution_root=root)
