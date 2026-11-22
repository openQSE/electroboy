"""Projects create content when its workflow stage or editor first needs it."""

import json
from unittest.mock import patch

import pytest

from electroboy.adapters.base import AgentResult
from electroboy.cli import main
from electroboy.models import (
    STAGE_DESIGN,
    STAGE_PLAN,
    STAGE_REQUIREMENTS,
    STAGE_TEST_PLAN,
)
from electroboy.service.app import ServiceState
from electroboy.state_store import StateStore
from electroboy.workflows.software.domain import ensure_stage_artifact


@pytest.mark.parametrize("stage,stem", [
    (STAGE_REQUIREMENTS, "requirements"),
    (STAGE_DESIGN, "detailed-design"),
    (STAGE_PLAN, "implementation-plan"),
    (STAGE_TEST_PLAN, "test-plan"),
])
def test_stage_entry_creates_only_its_own_artifacts(tmp_path, stage, stem):
    StateStore(tmp_path).init_run()
    ensure_stage_artifact(tmp_path, stage)
    expected = {f"{stem}.md", f"{stem}.jsonl"}
    assert {path.name for path in (tmp_path / "docs").iterdir()} == expected
    before = {path: path.read_bytes() for path in (tmp_path / "docs").iterdir()}
    assert ensure_stage_artifact(tmp_path, stage) == []
    assert all(path.read_bytes() == content for path, content in before.items())


@pytest.mark.parametrize("feature", [False, True])
def test_cli_creation_defers_artifacts_until_authoring(tmp_path, feature):
    root = tmp_path / "project"
    command = (
        ["--root", str(root), "feature", "start", "Export", "--name", "export"]
        if feature else ["new", str(root)]
    )
    assert main(command) == 0
    assert not (root / "docs").exists()
    assert main(["--root", str(root), "status"]) == 0
    assert not (root / "docs").exists()
    with patch(
        "electroboy.workflows.software.cli._invoke_agent_role",
        return_value=(AgentResult(ok=True, final_message="Ready"), "test-event", None),
    ):
        assert main(["--root", str(root), "requirements"]) == 0
    stem = "requirements-export" if feature else "requirements"
    assert {path.name for path in (root / "docs").iterdir()} == {
        f"{stem}.md", f"{stem}.jsonl",
    }


def test_blocked_stage_command_does_not_create_content(tmp_path):
    StateStore(tmp_path).init_run()
    assert main(["--root", str(tmp_path), "design"]) == 1
    assert not (tmp_path / "docs").exists()


def test_gui_stage_selection_is_lazy_and_preserves_authored_content(tmp_path):
    root = tmp_path / "project"
    state = ServiceState(tmp_path / "service")
    context_id = state.create_context()["context_id"]
    state.create_project(context_id, str(root))
    assert not (root / "docs").exists()
    state.select_workflow_stage(context_id, "requirements")
    assert {path.name for path in (root / "docs").iterdir()} == {
        "requirements.md", "requirements.jsonl",
    }
    (root / "docs" / "requirements.md").write_text("# Existing requirements\n")
    state.select_workflow_stage(context_id, "design")
    assert (root / "docs" / "requirements.md").read_text() == "# Existing requirements\n"
    assert (root / "docs" / "detailed-design.jsonl").exists()
    assert not (root / "docs" / "implementation-plan.md").exists()
    assert not (root / "docs" / "test-plan.md").exists()


def test_stage_entry_recovers_markdown_from_existing_source(tmp_path):
    StateStore(tmp_path).init_run()
    docs = tmp_path / "docs"
    docs.mkdir()
    source = docs / "requirements.jsonl"
    source.write_text(json.dumps({
        "schema_version": 1, "artifact_type": "requirements",
        "record_type": "document", "id": "REQ-DOC", "order": 0,
        "title": "Existing requirements", "body": "Preserve this content.",
    }) + "\n")
    original = source.read_bytes()
    ensure_stage_artifact(tmp_path, STAGE_REQUIREMENTS)
    assert source.read_bytes() == original
    assert "Preserve this content." in (docs / "requirements.md").read_text()
    assert not (docs / "detailed-design.md").exists()


def test_creative_content_is_created_only_by_create_or_save(tmp_path):
    root = tmp_path / "story"
    state = ServiceState(tmp_path / "service")
    context_id = state.create_context()["context_id"]
    state.create_creative_project(context_id, str(root))
    assert {path.name for path in root.iterdir()} == {".electroboy"}
    assert state.initialize_creative_workspace(context_id)["entries"] == []
    assert state.creative_scratchpad(context_id)["markdown"] == ""
    state.save_creative_scratchpad(context_id, " \n")
    assert not (root / "scratchpad").exists()

    state.create_creative_document(context_id, "chapters/opening.md")
    state.create_creative_corkboard(context_id, "corkboard/plot.corkboard.json")
    assert (root / "chapters" / "opening.md").exists()
    assert (root / "corkboard" / "plot.corkboard.json").exists()
    assert not (root / "characters").exists()
    state.save_creative_scratchpad(context_id, "An idea.")
    assert state.creative_scratchpad(context_id)["markdown"].strip() == "An idea."
    state.save_creative_scratchpad(context_id, "")
    assert state.creative_scratchpad(context_id)["markdown"].strip() == ""

    # Reopening the project never fills it with starter content.
    reopened = ServiceState(tmp_path / "other-service")
    other_context = reopened.create_context()["context_id"]
    reopened.open_creative_project(other_context, str(root))
    assert not (root / "chapters" / "chapter-01.md").exists()
    assert not (root / "characters").exists()
