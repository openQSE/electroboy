"""Cross-record completeness validation and targeted knowledge enrichment."""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from electroboy.adapters.base import AgentInvocation, AgentRuntime
from electroboy.models import utc_now
from electroboy.runtime import runtime_for_role

from .contracts import parse_jsonl, validate_knowledge_records
from .domain import CodeLearnerError, repository_revision
from .knowledge_store import KnowledgeStore
from .skills import skill_prompt_reference, validate_packaged_skill

ENRICHMENT_ROLE = "code_learner_analysis"
ProgressCallback = Callable[[dict[str, object]], None]


@dataclass(frozen=True)
class KnowledgeGap:
    """One actionable repository-knowledge completeness gap."""

    code: str
    scope_id: str
    missing_facts: str
    related_record_ids: tuple[str, ...]
    suggested_paths: tuple[str, ...] = ()
    blocks_course: bool = True

    @property
    def request_id(self) -> str:
        identity = f"{self.code}\0{self.scope_id}".encode()
        return f"request.{self.code}.{hashlib.sha1(identity).hexdigest()[:12]}"


@dataclass(frozen=True)
class KnowledgeValidationReport:
    """Deterministic completeness result after schema validation."""

    records: tuple[dict[str, object], ...]
    gaps: tuple[KnowledgeGap, ...]

    @property
    def complete(self) -> bool:
        return not any(gap.blocks_course for gap in self.gaps)

    def request_records(self) -> list[dict[str, object]]:
        manifest = next(
            record
            for record in self.records
            if record.get("record_type") == "knowledge_manifest"
        )
        common = {
            "schema_version": manifest["schema_version"],
            "analysis_run_id": manifest["analysis_run_id"],
            "repository_revision": manifest["repository_revision"],
        }
        existing = {
            str(record.get("id")): record
            for record in self.records
            if record.get("record_type") == "knowledge_request"
        }
        requests: list[dict[str, object]] = []
        for gap in self.gaps:
            prior = existing.get(gap.request_id, {})
            requests.append(
                {
                    **common,
                    "record_type": "knowledge_request",
                    "id": gap.request_id,
                    "scope_id": gap.scope_id,
                    "missing_facts": gap.missing_facts,
                    "related_record_ids": list(gap.related_record_ids),
                    "status": (
                        prior.get("status")
                        if prior.get("status") in {"open", "blocked"}
                        else "open"
                    ),
                    "attributes": {
                        **(
                            prior.get("attributes")
                            if isinstance(prior.get("attributes"), dict)
                            else {}
                        ),
                        "gap_code": gap.code,
                        "suggested_paths": list(gap.suggested_paths),
                        "blocks_course": gap.blocks_course,
                    },
                }
            )
        return requests


class RuntimeFactory(Protocol):
    def __call__(self, role: str, root: Path) -> AgentRuntime: ...


class KnowledgeValidator:
    """Validate graph-wide course readiness beyond JSON syntax."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()

    def audit(
        self, records: Iterable[Mapping[str, object]]
    ) -> KnowledgeValidationReport:
        normalized = validate_knowledge_records(records, root=self.root)
        by_id = {str(record["id"]): record for record in normalized}
        manifest = next(
            record
            for record in normalized
            if record.get("record_type") == "knowledge_manifest"
        )
        gaps: list[KnowledgeGap] = []
        current_revision = repository_revision(self.root)
        stale = tuple(
            record_id
            for record_id, record in by_id.items()
            if record.get("repository_revision") != current_revision
        )
        if stale:
            gaps.append(
                KnowledgeGap(
                    "stale-revision",
                    "repository.root",
                    "Reinspect records created for an earlier repository revision.",
                    stale,
                )
            )

        attributes = manifest.get("attributes")
        attributes = attributes if isinstance(attributes, dict) else {}
        module_catalog = attributes.get("module_catalog")
        major_modules = (
            module_catalog.get("major_module_ids", [])
            if isinstance(module_catalog, dict)
            else []
        )
        if not isinstance(module_catalog, dict):
            gaps.append(
                KnowledgeGap(
                    "module-catalog",
                    "repository.root",
                    "Discover and classify the repository's architectural modules.",
                    ("repository.root",),
                )
            )
        for module_id in major_modules if isinstance(major_modules, list) else []:
            module = by_id.get(str(module_id))
            if not module:
                continue
            details = module.get("attributes")
            details = details if isinstance(details, dict) else {}
            missing: list[str] = []
            if "interface_ids" not in details:
                missing.append("public and internal interfaces")
            if not isinstance(details.get("relationship_analysis"), dict):
                missing.append("incoming/outgoing relationships and lifecycle coverage")
            if not module.get("source_refs"):
                missing.append("source evidence")
            if missing:
                gaps.append(
                    KnowledgeGap(
                        "module-completeness",
                        str(module_id),
                        "Collect " + ", ".join(missing) + ".",
                        (str(module_id),),
                        _source_paths(module),
                    )
                )

        family_ids = (
            module_catalog.get("extension_family_ids", [])
            if isinstance(module_catalog, dict)
            else []
        )
        for family_id in family_ids if isinstance(family_ids, list) else []:
            family = by_id.get(str(family_id))
            details = family.get("attributes") if family else None
            implementations = (
                details.get("implementation_module_ids", [])
                if isinstance(details, dict)
                else []
            )
            exclusions = (
                details.get("excluded_implementations", [])
                if isinstance(details, dict)
                else []
            )
            if not isinstance(implementations, list) or not isinstance(
                exclusions, list
            ):
                gaps.append(
                    KnowledgeGap(
                        "extension-completeness",
                        str(family_id),
                        "Enumerate concrete implementations or explicit exclusions.",
                        (str(family_id),),
                        _source_paths(family or {}),
                    )
                )

        inventory = attributes.get("inventory")
        inventory_entries = (
            inventory.get("entry_point_ids", [])
            if isinstance(inventory, dict)
            else []
        )
        flow_catalog = attributes.get("flow_catalog")
        if inventory_entries and not isinstance(flow_catalog, dict):
            gaps.append(
                KnowledgeGap(
                    "entry-point-flow-coverage",
                    "repository.root",
                    "Trace every major entry point through at least one runtime flow.",
                    tuple(str(item) for item in inventory_entries),
                )
            )
        elif isinstance(flow_catalog, dict):
            covered = set(flow_catalog.get("covered_entry_point_ids", []))
            unresolved = {
                item.get("id")
                for item in flow_catalog.get("uncovered_entry_points", [])
                if isinstance(item, dict)
            }
            missing_entries = [
                str(item)
                for item in inventory_entries
                if item not in covered | unresolved
            ]
            if missing_entries:
                gaps.append(
                    KnowledgeGap(
                        "entry-point-flow-coverage",
                        "repository.root",
                        "Trace uncovered major entry points through runtime flows.",
                        tuple(missing_entries),
                    )
                )
        return KnowledgeValidationReport(tuple(normalized), tuple(gaps))

    def persist_requests(self, store: KnowledgeStore) -> KnowledgeValidationReport:
        report = self.audit(store.load_knowledge())
        requests = report.request_records()
        if requests:
            store.merge_knowledge(requests)
        return report


class EnrichmentController:
    """Run bounded, request-scoped analysis and revalidate after each merge."""

    def __init__(
        self,
        root: Path | str,
        *,
        runtime_factory: RuntimeFactory | None = None,
        max_attempts: int = 2,
        max_requests: int = 20,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        self.store = KnowledgeStore(self.root)
        self.validator = KnowledgeValidator(self.root)
        self.runtime_factory = runtime_factory or _default_runtime_factory
        self.max_attempts = max(1, max_attempts)
        self.max_requests = max(1, max_requests)

    def run(
        self, progress_callback: ProgressCallback | None = None
    ) -> KnowledgeValidationReport:
        validate_packaged_skill("codebase-analysis")
        report = self.validator.persist_requests(self.store)
        requests = report.request_records()[: self.max_requests]
        runtime = self.runtime_factory(ENRICHMENT_ROLE, self.root)
        for request in requests:
            if request.get("status") == "blocked":
                continue
            resolved = self._run_request(runtime, request, progress_callback)
            if not resolved:
                self._set_request_status(request, "blocked")
        return self.validator.audit(self.store.load_knowledge())

    def _run_request(
        self,
        runtime: AgentRuntime,
        request: dict[str, object],
        progress_callback: ProgressCallback | None,
    ) -> bool:
        before_ids = set(request.get("related_record_ids", []))
        for attempt in range(1, self.max_attempts + 1):
            self._progress(request, attempt, progress_callback)
            result = runtime.invoke(
                AgentInvocation(
                    role=ENRICHMENT_ROLE,
                    prompt=enrichment_prompt(self.root, self.store, request, attempt),
                    context_paths=_request_context_paths(self.store, request),
                )
            )
            if not result.ok or not result.final_message.strip():
                continue
            try:
                changes = parse_jsonl(
                    result.final_message, artifact=f"enrichment {request['id']}"
                )
                self.store.merge_knowledge(changes)
            except (CodeLearnerError, ValueError):
                continue
            report = self.validator.audit(self.store.load_knowledge())
            if not any(gap.request_id == request["id"] for gap in report.gaps):
                changed_ids = before_ids | {
                    str(record.get("id")) for record in changes
                }
                self.store.mark_courses_stale(changed_ids)
                self._set_request_status(request, "resolved", attempt=attempt)
                return True
        return False

    def _set_request_status(
        self, request: dict[str, object], status: str, *, attempt: int = 0
    ) -> None:
        current = self.store.get(str(request["id"]))
        attributes = current.get("attributes")
        self.store.merge_knowledge(
            [
                {
                    **current,
                    "status": status,
                    "attributes": {
                        **(attributes if isinstance(attributes, dict) else {}),
                        "attempts": attempt or self.max_attempts,
                        "resolved_at": utc_now() if status == "resolved" else "",
                    },
                }
            ]
        )

    def _progress(
        self,
        request: dict[str, object],
        attempt: int,
        callback: ProgressCallback | None,
    ) -> None:
        event = {
            "record_type": "progress",
            "phase": "knowledge_enrichment",
            "percent": 90,
            "scope_id": request.get("scope_id"),
            "request_id": request.get("id"),
            "attempt": attempt,
            "message": (
                f"Enriching {request.get('scope_id')} "
                f"({attempt}/{self.max_attempts})."
            ),
            "updated_at": utc_now(),
        }
        self.store.append_progress(event)
        if callback:
            callback(event)


def enrichment_prompt(
    root: Path,
    store: KnowledgeStore,
    request: Mapping[str, object],
    attempt: int,
) -> str:
    """Build a minimal request-scoped analysis prompt."""

    attributes = request.get("attributes")
    suggested = (
        attributes.get("suggested_paths", [])
        if isinstance(attributes, dict)
        else []
    )
    return f"""{skill_prompt_reference("codebase-analysis")}

Repository root: {root}
Knowledge request ID: {request.get("id")}
Scope ID: {request.get("scope_id")}
Attempt: {attempt}
Missing facts: {request.get("missing_facts")}
Related record IDs: {', '.join(request.get("related_record_ids", []))}
Suggested source paths: {', '.join(suggested)}
Canonical schema: {Path(__file__).with_name("schemas") / "knowledge.schema.json"}

Read only the named knowledge neighborhood and source needed to answer this
request. Return strict JSONL additions or stable-ID revisions only. Do not
write course prose, restart repository discovery, or modify tracked source.
""".strip()


def _request_context_paths(
    store: KnowledgeStore, request: Mapping[str, object]
) -> list[str]:
    paths = [
        path.relative_to(store.root).as_posix()
        for path in store.knowledge_root.glob("*.jsonl")
    ]
    attributes = request.get("attributes")
    suggested = (
        attributes.get("suggested_paths", [])
        if isinstance(attributes, dict)
        else []
    )
    paths.extend(str(path) for path in suggested)
    return sorted(set(paths))


def _source_paths(record: Mapping[str, object]) -> tuple[str, ...]:
    return tuple(
        str(reference.get("path"))
        for reference in record.get("source_refs", [])
        if isinstance(reference, dict) and reference.get("path")
    )


def _default_runtime_factory(role: str, root: Path) -> AgentRuntime:
    return runtime_for_role(role, root, execution_root=root)
