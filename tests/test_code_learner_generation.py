from __future__ import annotations

import json
from pathlib import Path

import pytest

from electroboy.workflows.code_learner.domain import CodeLearnerError
from electroboy.workflows.code_learner.generation import LearnerGenerationStore


def test_generation_store_selects_and_loads_phase3(tmp_path: Path) -> None:
    store = LearnerGenerationStore(tmp_path)

    selected = store.select("phase3", "revision-1")

    assert selected.generation == "phase3"
    assert store.load() == selected


def test_generation_store_detects_unmarked_phase2_state(tmp_path: Path) -> None:
    manifest = tmp_path / ".electroboy" / "code-learner" / "knowledge"
    manifest.mkdir(parents=True)
    (manifest / "manifest.jsonl").write_text("{}\n", encoding="utf-8")

    selected = LearnerGenerationStore(tmp_path).load()

    assert selected is not None
    assert selected.generation == "phase2"
    assert (manifest / "manifest.jsonl").read_text(encoding="utf-8") == "{}\n"


def test_generation_store_rejects_implicit_cross_generation_writes(
    tmp_path: Path,
) -> None:
    store = LearnerGenerationStore(tmp_path)
    store.select("phase3", "revision-1")

    with pytest.raises(CodeLearnerError, match="explicitly migrate"):
        store.select("phase2", "revision-1")


def test_generation_store_rejects_malformed_metadata(tmp_path: Path) -> None:
    store = LearnerGenerationStore(tmp_path)
    store.path.parent.mkdir(parents=True)
    store.path.write_text(json.dumps({"generation": "phase3"}), encoding="utf-8")

    with pytest.raises(CodeLearnerError, match="metadata is invalid"):
        store.load()
