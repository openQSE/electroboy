from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from electroboy.service import ServiceState
from electroboy.service.agent_backend import migrate_agent_selection, resume_agent_binary
from electroboy.service.agent_migration import migrate_session_catalog, preserve_unresolved_selection
from electroboy.adapters.codex_sessions import CodexSessionSummary
from electroboy.service.sessions import AgentSessionError


def test_selection_migration_keeps_unresolved_identities_explicit():
    known = migrate_agent_selection({
        "provider": "codex", "provider_executable": "/home/user/bin/codex-fixture-alpha",
    })
    assert known["provider_binary"] == "codex-fixture-alpha"
    assert known["selection_status"] == "resolved"
    unresolved = migrate_agent_selection({"provider": "codex"})
    assert unresolved["provider_binary"] == ""
    assert unresolved["selection_status"] == "unresolved"
    assert migrate_agent_selection(unresolved) == unresolved
    listed = preserve_unresolved_selection(unresolved, {
        "provider": "codex", "provider_binary": "codex-fixture-alpha",
        "provider_executable": "/bin/codex-fixture-alpha", "selection_status": "resolved",
    })
    assert listed["selection_status"] == "unresolved"
    assert listed["provider_binary"] == ""
    assert "provider_executable" not in listed
    with pytest.raises(AgentSessionError, match="Select the executable"):
        resume_agent_binary([unresolved], "")
    assert resume_agent_binary([unresolved], "codex-fixture-alpha") == "codex-fixture-alpha"
    with pytest.raises(AgentSessionError, match="different provider"):
        resume_agent_binary([unresolved], "opencode")
    assert resume_agent_binary([known], "") == "codex-fixture-alpha"
    with pytest.raises(AgentSessionError, match="different executable"):
        resume_agent_binary([known], "opencode")


def test_catalog_upgrade_is_scoped_atomic_and_idempotent(tmp_path: Path):
    project = tmp_path / "project"
    other = tmp_path / "other"
    project.mkdir()
    other.mkdir()
    path = tmp_path / "catalog.json"
    original = {"schema_version": 1, "sessions": [
        {"project_root": str(project), "provider": "codex",
         "provider_executable": "/bin/codex-fixture-alpha", "provider_session_id": "first"},
        {"project_root": str(project), "provider": "codex", "provider_session_id": "unknown"},
        {"project_root": str(other), "provider": "codex", "provider_session_id": "other"},
    ]}
    path.write_text(json.dumps(original))
    with mock.patch("electroboy.service.agent_migration.os.replace", side_effect=OSError("disk")):
        with pytest.raises(OSError):
            migrate_session_catalog(path, project)
    assert json.loads(path.read_text()) == original
    migrate_session_catalog(path, project)
    upgraded = json.loads(path.read_text())
    assert upgraded["sessions"][0]["provider_binary"] == "codex-fixture-alpha"
    assert upgraded["sessions"][1]["selection_status"] == "unresolved"
    assert upgraded["sessions"][2] == original["sessions"][2]
    with mock.patch("electroboy.service.agent_migration.write_json_atomic") as write:
        migrate_session_catalog(path, project)
    write.assert_not_called()


def test_open_creative_workspace_upgrades_catalog_and_session_records(tmp_path: Path):
    service_root = tmp_path / "service"
    service_root.mkdir()
    project = tmp_path / "story"
    project.mkdir()
    state = ServiceState(service_root)
    workspace = state.create_context(workflow_id="creative-writing")["context_id"]
    store = service_root / ".electroboy" / "service"
    store.mkdir(parents=True, exist_ok=True)
    catalog = store / "creative-agent-sessions.json"
    catalog.write_text(json.dumps({"schema_version": 1, "sessions": [{
        "project_root": str(project), "provider": "codex",
        "provider_executable": "/bin/codex-fixture-alpha", "provider_session_id": "first",
    }]}))
    records = store / "sessions.json"
    records.write_text(json.dumps({"schema_version": 1, "sessions": [{
        "workspace_id": workspace, "active_project_root": str(project),
        "kind": "creative-writing", "session_id": "one",
        "metadata": {"provider": "codex", "provider_executable": "/bin/codex-fixture-alpha"},
    }]}))
    state.open_creative_project(workspace, str(project))
    assert json.loads(catalog.read_text())["sessions"][0]["provider_binary"] == "codex-fixture-alpha"
    assert json.loads(records.read_text())["sessions"][0]["metadata"]["provider_binary"] == "codex-fixture-alpha"
    assert state.contexts[workspace].module("agent_backend")["history_version"] == 1
    state.workspace_registry.set_agent_default(workspace, "opencode")
    with mock.patch("electroboy.service.app.migrate_workspace_sessions", side_effect=AssertionError("repeated")):
        state.project_payload(workspace)
        restored = ServiceState(service_root)
        restored.project_payload(workspace)
    assert restored.contexts[workspace].module("agent_backend")["binary"] == "opencode"


def test_open_software_workspace_upgrades_its_ad_hoc_catalog(tmp_path: Path):
    from electroboy.state_store import StateStore

    service_root = tmp_path / "service"
    service_root.mkdir()
    project = tmp_path / "project"
    project.mkdir()
    StateStore(project).init_run(run_id="test")
    state = ServiceState(service_root)
    workspace = state.create_context(workflow_id="software")["context_id"]
    store = service_root / ".electroboy" / "service"
    store.mkdir(parents=True, exist_ok=True)
    catalog = store / "ad-hoc-sessions.json"
    catalog.write_text(json.dumps({"sessions": [{
        "project_root": str(project), "provider": "codex",
        "provider_executable": "/bin/codex-fixture-beta", "provider_session_id": "first",
    }]}))
    state.open_project(workspace, str(project))
    assert json.loads(catalog.read_text())["sessions"][0]["provider_binary"] == "codex-fixture-beta"


def test_failed_catalog_upgrade_preserves_history_and_retries(tmp_path: Path):
    service_root = tmp_path / "service"
    service_root.mkdir()
    project = tmp_path / "story"
    project.mkdir()
    state = ServiceState(service_root)
    workspace = state.create_context(workflow_id="creative-writing")["context_id"]
    store = service_root / ".electroboy" / "service"
    store.mkdir(parents=True, exist_ok=True)
    catalog = store / "creative-agent-sessions.json"
    catalog.write_text("{invalid")
    with pytest.raises(json.JSONDecodeError):
        state.open_creative_project(workspace, str(project))
    assert catalog.read_text() == "{invalid"
    assert "history_version" not in state.contexts[workspace].module("agent_backend")
    catalog.write_text(json.dumps({"sessions": [{"project_root": str(project),
        "provider": "codex", "provider_session_id": "kept"}]}))
    state.project_payload(workspace)
    record = json.loads(catalog.read_text())["sessions"][0]
    assert record["provider_session_id"] == "kept"
    assert record["selection_status"] == "unresolved"
    assert state.contexts[workspace].module("agent_backend")["history_version"] == 1


@pytest.mark.parametrize("workflow", ["creative", "software"])
def test_listing_legacy_history_does_not_guess_its_executable(tmp_path: Path, workflow: str):
    from electroboy.workflows.creative_writing import sessions as creative
    from electroboy.workflows.software import ad_hoc

    project = tmp_path / "project"
    project.mkdir()
    service = tmp_path / "service"
    store = service / ".electroboy" / "service"
    store.mkdir(parents=True)
    module = creative if workflow == "creative" else ad_hoc
    path = store / ("creative-agent-sessions.json" if workflow == "creative" else "ad-hoc-sessions.json")
    record = {"project_root": str(project), "provider": "codex",
              "provider_session_id": "old-id", "selection_status": "unresolved",
              "provider_binary": "", "scope_key": "general"}
    path.write_text(json.dumps({"sessions": [record]}))
    summary = CodexSessionSummary("old-id", project, "created", "updated", (),
                                  tmp_path / "rollout.jsonl", "/bin/codex-fixture-alpha")
    with mock.patch.object(module, "_indexed_session", return_value=summary):
        if workflow == "creative":
            result = module.creative_session_history(service, project, scope="general",
                                                     scope_key="general", executable="codex-fixture-alpha")
        else:
            result = module.ad_hoc_session_history(service, project, executable="codex-fixture-alpha")
    assert result[0]["selection_status"] == "unresolved"
    saved = json.loads(path.read_text())["sessions"][0]
    assert saved["provider_binary"] == ""
    assert "provider_executable" not in saved


@pytest.mark.parametrize("workflow", ["creative", "software"])
def test_codex_history_filters_by_captured_executable(tmp_path: Path, workflow: str):
    from electroboy.workflows.creative_writing import sessions as creative
    from electroboy.workflows.software import ad_hoc

    project = tmp_path / "project"
    project.mkdir()
    service = tmp_path / "service"
    store = service / ".electroboy" / "service"
    store.mkdir(parents=True)
    module = creative if workflow == "creative" else ad_hoc
    path = store / ("creative-agent-sessions.json" if workflow == "creative" else "ad-hoc-sessions.json")
    entries = [{"project_root": str(project), "provider": "codex", "scope_key": "general",
                "provider_session_id": binary, "provider_binary": binary,
                "selection_status": "resolved"}
               for binary in ("codex-fixture-alpha", "codex-fixture-beta")]
    path.write_text(json.dumps({"sessions": entries}))
    summary = CodexSessionSummary("codex-fixture-alpha", project, "created", "updated", (),
                                  tmp_path / "rollout.jsonl", "/bin/codex-fixture-alpha")
    with mock.patch.object(module, "_indexed_session", return_value=summary):
        if workflow == "creative":
            result = module.creative_session_history(service, project, scope="general",
                scope_key="general", executable="codex-fixture-alpha", agent_binary="codex-fixture-alpha")
        else:
            result = module.ad_hoc_session_history(service, project,
                executable="codex-fixture-alpha", agent_binary="codex-fixture-alpha")
    assert [entry["provider_session_id"] for entry in result] == ["codex-fixture-alpha"]
    assert len(json.loads(path.read_text())["sessions"]) == 2
