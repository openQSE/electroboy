"""Legacy Code Learner corpus migration into durable Phase 2 knowledge."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .domain import CodeLearnerError, CodeLearnerStore, repository_revision
from .knowledge_store import KnowledgeStore


@dataclass(frozen=True)
class LegacyMigrationResult:
    """Describe whether useful v1 records were imported."""

    status: str
    imported_record_count: int = 0
    message: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "imported_record_count": self.imported_record_count,
            "message": self.message,
        }


class LegacyCorpusMigrator:
    """Convert a v1 course corpus without treating it as initialized state."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.legacy_store = CodeLearnerStore(self.root)
        self.knowledge_store = KnowledgeStore(self.root)

    def status(self) -> LegacyMigrationResult:
        if self.knowledge_store.load_knowledge(validate_sources=False):
            return LegacyMigrationResult(
                "not_required",
                message="Phase 2 knowledge is present.",
            )
        if self.legacy_store.load_corpus_records():
            return LegacyMigrationResult(
                "required",
                message=(
                    "Legacy Code Learner material is available. Run Initialize "
                    "to migrate it and build the layered course."
                ),
            )
        return LegacyMigrationResult(
            "not_present",
            message="No legacy Code Learner material is present.",
        )

    def migrate(self) -> LegacyMigrationResult:
        current = self.status()
        if current.status != "required":
            return current
        records = self.legacy_store.load_corpus_records()
        try:
            imported = self.knowledge_store.import_v1_corpus(
                records,
                analysis_run_id=f"v1-migration-{uuid4().hex}",
                revision=repository_revision(self.root),
            )
        except (CodeLearnerError, OSError, ValueError) as error:
            raise CodeLearnerError(
                "Legacy Code Learner material could not be migrated. Correct "
                "stale source references and run Initialize again, or remove "
                f"{self.legacy_store.corpus_path.relative_to(self.root)} to "
                f"rebuild from source: {error}"
            ) from error
        return LegacyMigrationResult(
            "imported",
            imported_record_count=len(imported),
            message=(
                f"Imported {len(imported)} legacy records as provisional "
                "knowledge for staged analysis."
            ),
        )
