"""Executable-specific Codex history must survive service restarts and switches."""

import json
import os
import sys
import time
from pathlib import Path
from unittest import mock

import pytest

from electroboy.adapters.codex_sessions import (
    codex_session_by_id,
    codex_session_from_path,
    codex_session_paths,
    codex_sessions_directory,
)
from electroboy.adapters.interactive_cli import CodexInteractiveRuntime
from electroboy.config import RuntimeConfig
from electroboy.service import ServiceState
from electroboy.service.sessions import AgentSessionError
from electroboy.service.services import build_service_services
from electroboy.state_store import StateStore
from electroboy.workflows.creative_writing.sessions import (
    creative_session_history,
    remember_creative_session,
    resumable_creative_session,
    start_creative_session_tracking,
)
from electroboy.workflows.software.ad_hoc import (
    ad_hoc_session_history,
    remember_ad_hoc_session,
    resumable_ad_hoc_session,
    start_ad_hoc_session_tracking,
)

FIRST = "019f3cb6-60c3-7320-896b-e5eb9a6a8dd1"
SECOND = "019f3cb6-60c3-7320-896b-e5eb9a6a8dd2"
OTHER = "019f3cb6-60c3-7320-896b-e5eb9a6a8dd3"


def write_binary(path, home):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"#!{sys.executable}\n"
        "import json,sys\n"
        "from pathlib import Path\n"
        "assert sys.argv[1:] == ['app-server']\n"
        "request=json.loads(sys.stdin.readline())\n"
        "assert request['method'] == 'initialize'\n"
        f"counter=Path({str(path.with_suffix('.calls'))!r})\n"
        "with counter.open('a') as stream: stream.write('initialize\\n')\n"
        f"print(json.dumps({{'id':request['id'],'result':{{'codexHome':{str(home)!r}}}}}))\n"
    )
    path.chmod(0o755)
    return str(path)


def write_rollout(home, project, session_id, prompt=None):
    path = home / "sessions" / f"rollout-{session_id}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            json.dumps(record)
            for record in (
                {
                    "type": "session_meta",
                    "payload": {
                        "id": session_id,
                        "cwd": str(project),
                        "timestamp": "2026-11-22T23:11:02Z",
                    },
                },
                {
                    "type": "response_item",
                    "payload": {
                        "type": "message",
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
                                "text": prompt
                                or "You are an ad-hoc agent for this code base. Wait for the operator.",
                            }
                        ],
                    },
                },
            )
        )
        + "\n"
    )
    return path


def test_executable_reports_storage_and_discovery_is_cached(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "account data"
    executable = write_binary(tmp_path / "bin" / "codex-custom", home)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "wrong-home"))
    path = write_rollout(home, project, FIRST)

    assert (
        codex_sessions_directory(executable=executable, root=project)
        == home / "sessions"
    )
    assert codex_session_paths(executable=executable, root=project) == {path}
    assert (
        codex_session_by_id(FIRST, executable=executable, root=project).executable
        == executable
    )
    assert Path(executable).with_suffix(".calls").read_text().splitlines() == [
        "initialize"
    ]


def test_tracking_and_restart_read_the_launched_executable_storage(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "actual-data"
    executable = write_binary(tmp_path / "bin" / "codex-custom", home)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "wrong-home"))
    write_rollout(home, project, FIRST)
    known = codex_session_paths(executable=executable, root=project)
    write_rollout(Path(os.environ["CODEX_HOME"]), project, OTHER)
    write_rollout(home, project, SECOND)
    service = tmp_path / "service"

    tracker = start_ad_hoc_session_tracking(
        service,
        project,
        "electroboy-session",
        known,
        lambda: False,
        title="investigation",
        executable=executable,
    )
    tracker.join(timeout=2)
    assert not tracker.is_alive()
    history = ad_hoc_session_history(service, project, executable=executable)
    assert len(history) == 1
    assert history[0]["provider_session_id"] == SECOND
    assert history[0]["title"] == "investigation"
    assert history[0]["provider_executable"] == executable
    assert resumable_ad_hoc_session(service, SECOND, project, executable=executable)
    other_project = tmp_path / "other-project"
    other_project.mkdir()
    assert (
        resumable_ad_hoc_session(service, SECOND, other_project, executable=executable)
        is None
    )


def test_switching_executables_preserves_other_accounts_catalog_entries(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "unused"))
    first = write_binary(tmp_path / "one" / "codex-custom", tmp_path / "first-data")
    second = write_binary(tmp_path / "two" / "codex-custom", tmp_path / "second-data")
    write_rollout(tmp_path / "first-data", project, FIRST)
    write_rollout(tmp_path / "second-data", project, SECOND)
    service = tmp_path / "service"
    for executable, session_id in ((first, FIRST), (second, SECOND)):
        session = codex_session_by_id(session_id, executable=executable, root=project)
        remember_ad_hoc_session(service, session, title=session_id)
        remember_creative_session(
            service, session, scope="general", scope_key="general"
        )

    for executable, session_id in ((first, FIRST), (second, SECOND), (first, FIRST)):
        history = ad_hoc_session_history(service, project, executable=executable)
        assert [entry["provider_session_id"] for entry in history] == [session_id]
        creative = creative_session_history(
            service,
            project,
            scope="general",
            scope_key="general",
            executable=executable,
        )
        assert [entry["provider_session_id"] for entry in creative] == [session_id]
        assert resumable_creative_session(
            service,
            session_id,
            project,
            scope_key="general",
            executable=executable,
        )


def test_service_persists_discovered_uuid_and_resumes_after_restart(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    StateStore(project).init_run(run_id="run-1")
    home = tmp_path / "actual-data"
    binary = tmp_path / "bin" / "codex-custom"
    executable = write_binary(binary, home)
    monkeypatch.setenv(
        "PATH", str(binary.parent) + os.pathsep + os.environ.get("PATH", "")
    )
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "wrong-home"))
    service = tmp_path / "service"
    state = ServiceState(service)
    context_id = state.create_context()["context_id"]
    context_id = state.open_project(context_id, str(project))["context_id"]
    build_service_services(state, state.workflow_registry).sessions.set_workspace_backend(
        context_id, binary.name,
    )
    with mock.patch(
        "electroboy.service.AgentSession.start",
        side_effect=lambda: write_rollout(home, project, FIRST),
    ):
        session, started = state.workflow_controller("software").start_ad_hoc_agent(
            context_id,
            name="investigation",
        )
    assert started
    # Wait only for the actual asynchronous indexing callback to persist its result.
    records_path = service / ".electroboy/service/sessions.json"
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with state.lock:
            record = json.loads(records_path.read_text())["sessions"][0]
        if record["metadata"].get("provider_session_id") == FIRST:
            break
        time.sleep(0.02)
    assert record["metadata"]["provider_session_id"] == FIRST
    assert record["metadata"]["provider_executable"] == executable

    restarted = ServiceState(service)
    context_id = restarted.create_context()["context_id"]
    context_id = restarted.open_project(context_id, str(project))["context_id"]
    build_service_services(restarted, restarted.workflow_registry).sessions.set_workspace_backend(
        context_id, binary.name,
    )
    controller = restarted.workflow_controller("software")
    history = controller.ad_hoc_sessions(context_id)["sessions"]
    assert history[0]["title"] == "investigation"
    with mock.patch("electroboy.service.AgentSession.start"):
        resumed, started = controller.start_ad_hoc_agent(context_id, FIRST)
    assert started
    assert resumed.command[0] == binary.name
    assert resumed.metadata["provider_executable"] == executable
    assert "resume" in resumed.command and FIRST in resumed.command


@pytest.mark.parametrize("workflow", ["software", "creative-writing"])
def test_resume_uses_recorded_codex_wrapper_after_default_changes(tmp_path, monkeypatch, workflow):
    project = tmp_path / "project"
    project.mkdir()
    if workflow == "software":
        StateStore(project).init_run(run_id="test")
    first_home, second_home = tmp_path / "first-home", tmp_path / "second-home"
    first = write_binary(tmp_path / "bin" / "codex-fixture-alpha", first_home)
    second = write_binary(tmp_path / "bin" / "codex-fixture-beta", second_home)
    monkeypatch.setenv("PATH", str(tmp_path / "bin") + os.pathsep + os.environ.get("PATH", ""))
    rollout = write_rollout(first_home, project, FIRST)
    summary = codex_session_from_path(rollout, executable=first)
    service = tmp_path / "service"
    if workflow == "software":
        remember_ad_hoc_session(service, summary)
    else:
        remember_creative_session(service, summary, project_root=project,
                                  scope="general", scope_key="general")
    state = ServiceState(service)
    workspace = state.create_context(workflow_id=workflow)["context_id"]
    if workflow == "software":
        state.open_project(workspace, str(project))
        controller = state.workflow_controller(workflow)
        start = controller.start_ad_hoc_agent
        history = controller.ad_hoc_sessions
    else:
        state.open_creative_project(workspace, str(project))
        start = state.start_creative_writing_agent
        history = state.creative_agent_sessions
    services = build_service_services(state, state.workflow_registry).sessions
    services.set_workspace_backend(workspace, Path(second).name)
    assert not history(workspace)["sessions"]
    with mock.patch("electroboy.service.AgentSession.start"):
        resumed, started = start(workspace, provider_session_id=FIRST)
        assert started and resumed.metadata["provider_binary"] == Path(first).name
        assert resumed.command[0] == Path(first).name
        with pytest.raises(AgentSessionError, match="different executable"):
            start(workspace, provider_session_id=FIRST, agent_binary=Path(second).name)
    state.deactivate_project(workspace)
    restarted = ServiceState(service)
    workspace = restarted.create_context(workflow_id=workflow)["context_id"]
    if workflow == "software":
        restarted.open_project(workspace, str(project))
        start = restarted.workflow_controller(workflow).start_ad_hoc_agent
    else:
        restarted.open_creative_project(workspace, str(project))
        start = restarted.start_creative_writing_agent
    with mock.patch("electroboy.service.AgentSession.start"):
        resumed, started = start(workspace, provider_session_id=FIRST)
    assert started and resumed.metadata["provider_binary"] == Path(first).name


def test_creative_tracker_uses_the_wrapper_and_restores_its_named_history(
    tmp_path, monkeypatch
):
    project = tmp_path / "story"
    project.mkdir()
    home = tmp_path / "writing-data"
    executable = write_binary(tmp_path / "bin" / "codex-custom", home)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "wrong-home"))
    known = codex_session_paths(executable=executable, root=project)
    write_rollout(
        home,
        project,
        FIRST,
        prompt="Act as a creative writing collaborator inside this project.",
    )
    service = tmp_path / "service"
    tracker = start_creative_session_tracking(
        service,
        project,
        "creative-session",
        known,
        lambda: False,
        scope="general",
        scope_key="general",
        title="Story investigation",
        executable=executable,
    )
    tracker.join(timeout=2)
    assert not tracker.is_alive()
    history = creative_session_history(
        service,
        project,
        scope="general",
        scope_key="general",
        executable=executable,
    )
    assert history[0]["provider_session_id"] == FIRST
    assert history[0]["title"] == "Story investigation"
    assert history[0]["provider_executable"] == executable


def test_lookup_rejects_rollout_symlinks_outside_the_reported_store(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "account-data"
    executable = write_binary(tmp_path / "bin" / "codex-custom", home)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "wrong-home"))
    outside = write_rollout(tmp_path / "unrelated-data", project, FIRST)
    (home / "sessions").mkdir(parents=True)
    (home / "sessions" / outside.name).symlink_to(outside)
    assert not codex_session_paths(executable=executable, root=project)
    assert codex_session_by_id(FIRST, executable=executable, root=project) is None


def test_interactive_runtime_finds_the_launched_executables_uuid(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    home = tmp_path / "runtime-data"
    executable = write_binary(tmp_path / "bin" / "codex-custom", home)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "wrong-home"))
    write_rollout(home, project, FIRST)
    write_rollout(Path(os.environ["CODEX_HOME"]), project, SECOND)
    runtime = CodexInteractiveRuntime(
        RuntimeConfig(name="custom", adapter="codex_interactive", command=executable),
        project,
    )
    assert runtime._latest_codex_session_id(0) == FIRST
