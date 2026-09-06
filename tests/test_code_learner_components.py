from __future__ import annotations

import json
from pathlib import Path

from electroboy.workflows.code_learner.components import ComponentCandidateService
from electroboy.workflows.code_learner.ctags_evidence import LocatorResolution
from electroboy.workflows.code_learner.source_manifest import SourceManifestService


class FakeResolver:
    def resolve(self, value):
        name = str(value.get("name") or "")
        if name == "missing":
            return LocatorResolution(
                "unresolved", dict(value), "", "repository-search", message="not found"
            )
        return LocatorResolution(
            "exact",
            dict(value),
            f"key:{value.get('file_id')}:{name}:{value.get('start_line')}",
            "universal-ctags",
        )


def _setup(root: Path) -> SourceManifestService:
    (root / "app.py").write_text("def main():\n    return 1\n", encoding="utf-8")
    (root / "helper.py").write_text("def helper():\n    return 2\n", encoding="utf-8")
    source = SourceManifestService(root)
    source.generate()
    return source


def _candidate(revision: str, *, name: str = "main") -> dict[str, object]:
    return {
        "schema_version": 1,
        "record_type": "component_candidate",
        "analysis_run_id": "run-1",
        "repository_revision": revision,
        "candidate_id": f"candidate-{name}",
        "name": "Application",
        "name_origin": "source_defined",
        "kind": "service",
        "responsibility": "Runs the application.",
        "file_ids": ["file:app.py"],
        "symbols": [
            {
                "file_id": "file:app.py",
                "name": name,
                "kind": "function",
                "start_line": 1,
                "end_line": 2,
            }
        ],
        "owned_source_refs": [
            {
                "file_id": "file:app.py",
                "start_line": 1,
                "end_line": 2,
                "reason": "Defines the application entry point.",
            }
        ],
        "supporting_source_refs": [],
        "confidence": "high",
        "limitations": [],
    }


def test_candidate_service_promotes_resolved_candidate_and_retains_attempt(
    tmp_path: Path,
) -> None:
    source = _setup(tmp_path)
    service = ComponentCandidateService(
        tmp_path, resolver=FakeResolver(), source=source
    )
    candidate = _candidate(source.load().revision)

    result = service.ingest(json.dumps(candidate), attempt_id="attempt-1")

    assert result.complete is True
    assert result.accepted[0]["symbols"][0]["canonical_key"].startswith("key:")
    assert service.load()[0]["name"] == "Application"
    assert (service.store.attempts_root / "components/attempt-1.jsonl").is_file()
    assert (service.validation_root / "attempt-1.json").is_file()


def test_candidate_service_isolates_invalid_records_and_builds_bounded_repair(
    tmp_path: Path,
) -> None:
    source = _setup(tmp_path)
    service = ComponentCandidateService(
        tmp_path, resolver=FakeResolver(), source=source
    )
    accepted = _candidate(source.load().revision)
    rejected = _candidate(source.load().revision, name="missing")

    result = service.ingest(
        "\n".join(json.dumps(item) for item in (accepted, rejected)),
        attempt_id="attempt-2",
    )

    assert [item["candidate_id"] for item in result.accepted] == ["candidate-main"]
    assert len(result.rejected) == 1
    assert [item["candidate_id"] for item in service.load()] == ["candidate-main"]
    prompt = service.repair_prompt(
        result.rejected[0], schema_path="phase3.schema.json"
    )
    assert "candidate-missing" in prompt
    assert "not found" in prompt
    assert "Do not emit or modify any other candidate" in prompt
    assert "Use `reason`, never `role`" in prompt
    assert "Do not use a numeric score" in prompt
    assert "verified" in prompt and "unknown" in prompt


def test_candidate_service_rejects_mixed_types_stale_and_bad_ranges(
    tmp_path: Path,
) -> None:
    source = _setup(tmp_path)
    service = ComponentCandidateService(
        tmp_path, resolver=FakeResolver(), source=source
    )
    stale = _candidate("stale")
    stale["owned_source_refs"][0]["end_line"] = 20
    module = {"schema_version": 1, "record_type": "module"}

    result = service.ingest(
        "\n".join(json.dumps(item) for item in (stale, module)),
        attempt_id="attempt-3",
    )

    assert not result.accepted
    assert len(result.rejected) == 2
    errors = " ".join(error for item in result.rejected for error in item.errors)
    assert "revision does not match" in errors
    assert "must be component_candidate" in errors


def test_candidate_service_corrects_ranges_beyond_verified_file_length(
    tmp_path: Path,
) -> None:
    source = _setup(tmp_path)
    service = ComponentCandidateService(
        tmp_path, resolver=FakeResolver(), source=source
    )
    candidate = _candidate(source.load().revision)
    candidate["symbols"][0]["end_line"] = 200
    candidate["owned_source_refs"][0]["end_line"] = 100

    result = service.ingest(json.dumps(candidate), attempt_id="range-correction")

    assert result.complete is True
    assert len(result.corrections) == 2
    assert {item.field for item in result.corrections} == {
        "symbols[0].end_line",
        "owned_source_refs[0].end_line",
    }
    assert all(item.corrected_value == 2 for item in result.corrections)
    assert result.accepted[0]["owned_source_refs"][0]["end_line"] == 2
    report = service.store.read_json(
        service.validation_root / "range-correction.json"
    )
    assert report is not None
    assert report["corrections"][0]["reason"] == (
        "clamped to the verified repository file length"
    )


def test_candidate_service_does_not_correct_a_range_starting_past_eof(
    tmp_path: Path,
) -> None:
    source = _setup(tmp_path)
    service = ComponentCandidateService(
        tmp_path, resolver=FakeResolver(), source=source
    )
    candidate = _candidate(source.load().revision)
    candidate["owned_source_refs"][0].update({"start_line": 20, "end_line": 30})

    result = service.ingest(json.dumps(candidate), attempt_id="invalid-start")

    assert result.complete is False
    assert result.corrections == ()


def test_candidate_service_preserves_semantic_fields_without_rewriting(
    tmp_path: Path,
) -> None:
    source = _setup(tmp_path)
    service = ComponentCandidateService(
        tmp_path, resolver=FakeResolver(), source=source
    )
    candidate = _candidate(source.load().revision)
    candidate["name"] = "Source Authored Name"
    candidate["responsibility"] = "Exact AI-authored responsibility."

    service.ingest(json.dumps(candidate), attempt_id="attempt-4")
    stored = service.load()[0]

    assert stored["name"] == "Source Authored Name"
    assert stored["responsibility"] == "Exact AI-authored responsibility."


def test_complete_discovery_replaces_the_previous_candidate_snapshot(
    tmp_path: Path,
) -> None:
    source = _setup(tmp_path)
    service = ComponentCandidateService(
        tmp_path, resolver=FakeResolver(), source=source
    )
    old = _candidate(source.load().revision, name="old")
    current = _candidate(source.load().revision, name="current")
    service.ingest(json.dumps(old), attempt_id="old-discovery")

    service.ingest(
        json.dumps(current),
        attempt_id="current-discovery",
        replace_existing=True,
    )

    assert [item["candidate_id"] for item in service.load()] == [
        "candidate-current"
    ]


def test_candidate_repair_merges_into_the_current_snapshot(tmp_path: Path) -> None:
    source = _setup(tmp_path)
    service = ComponentCandidateService(
        tmp_path, resolver=FakeResolver(), source=source
    )
    current = _candidate(source.load().revision, name="current")
    repaired = _candidate(source.load().revision, name="repaired")
    service.ingest(
        json.dumps(current),
        attempt_id="current-discovery",
        replace_existing=True,
    )

    service.ingest(json.dumps(repaired), attempt_id="repair")

    assert [item["candidate_id"] for item in service.load()] == [
        "candidate-current",
        "candidate-repaired",
    ]
