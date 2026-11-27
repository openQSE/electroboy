"""Workspace-scoped agent selection and heterogeneous process behavior."""

import json
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from electroboy.adapters.base import AgentInvocation
from electroboy.adapters.generic_cli import GenericCliRuntime
from electroboy.adapters.opencode_exec import OpenCodeExecRuntime
from electroboy.config import DEFAULT_CONFIG, RuntimeConfig
from electroboy.runtime import interactive_command, runtime_for_role
from electroboy.service.agent_backend import AgentBackend
from electroboy.service.app import ServiceState, create_server
from electroboy.service.sessions import (
    AgentSession,
    AgentSessionError,
    TmuxAgentSession,
)


def selection():
    return AgentBackend(threading.RLock(), lambda: [Path(".")])


def test_captured_selections_are_independent_of_later_default_changes(tmp_path):
    backend = AgentBackend(threading.RLock(), lambda: [tmp_path])
    with patch("shutil.which", side_effect=lambda name: f"/bin/{name}"):
        codex = backend.resolve("codex-fixture-alpha", tmp_path)
        opencode = backend.resolve("opencode", tmp_path)
        session = AgentSession(["codex", "resume", "example"], tmp_path)
        backend.prepare_selection(session, codex)
        factory = backend.selected_runtime_factory(opencode)
        backend.resolve("codex-fixture-beta", tmp_path)

    assert session.command[0] == "codex-fixture-alpha"
    assert session.metadata["provider_binary"] == "codex-fixture-alpha"
    assert session.environment["ELECTROBOY_AGENT_EXECUTABLE"] == "codex-fixture-alpha"
    assert factory("code_review", tmp_path).config.adapter == "opencode_exec"


def test_captured_selection_requires_available_executable(tmp_path):
    backend = selection()
    with patch("shutil.which", return_value=None):
        with pytest.raises(AgentSessionError, match="unavailable"):
            backend.resolve("codex-fixture-alpha", tmp_path)


def test_queued_runtime_retains_workspace_selection(tmp_path):
    from electroboy.service.services import build_service_services

    state = ServiceState(tmp_path)
    workspace = state.create_context(workflow_id="software")["context_id"]
    services = build_service_services(state, state.workflow_registry).sessions
    with patch("shutil.which", side_effect=lambda name: f"/bin/{name}"):
        services.set_workspace_backend(workspace, "codex-fixture-alpha")
        queued_factory = services.runtime_factory(workspace)
        services.set_workspace_backend(workspace, "opencode")
        later_factory = services.runtime_factory(workspace)
    assert queued_factory("code_review", tmp_path).config.command == "codex-fixture-alpha"
    assert later_factory("code_review", tmp_path).config.adapter == "opencode_exec"


def test_launch_retains_selection_when_default_changes_concurrently(tmp_path):
    from electroboy.service.services import build_service_services

    state = ServiceState(tmp_path)
    workspace = state.create_context(workflow_id="software")["context_id"]
    services = build_service_services(state, state.workflow_registry).sessions
    captured = threading.Event()
    changed = threading.Event()
    result = []

    def launch():
        selected = services.resolve_workspace_selection(workspace)
        captured.set()
        assert changed.wait(5)
        session = AgentSession([sys.executable], tmp_path, kind="ad-hoc")
        services.prepare(state.contexts[workspace], session, selected)
        result.append(session.metadata["provider_binary"])

    with patch("shutil.which", side_effect=lambda name: f"/bin/{name}"):
        services.set_workspace_backend(workspace, "codex-fixture-alpha")
        worker = threading.Thread(target=launch)
        worker.start()
        try:
            assert captured.wait(5)
            services.set_workspace_backend(workspace, "opencode")
        finally:
            changed.set()
            worker.join(5)
    assert not worker.is_alive()
    assert result == ["codex-fixture-alpha"]


def test_explicit_background_cancellation_is_isolated(tmp_path):
    script = tmp_path / "agent.py"
    script.write_text(
        "import sys,time\nfrom pathlib import Path\n"
        "Path(sys.argv[1]).write_text('started')\ntime.sleep(60)\n"
    )
    events = [threading.Event(), threading.Event()]
    markers = [tmp_path / "one", tmp_path / "two"]
    results = [None, None]
    workers = []
    for index in range(2):
        runtime = GenericCliRuntime(
            RuntimeConfig("fake", "generic_cli", sys.executable, [str(script), str(markers[index])]),
            tmp_path,
        )
        def invoke(i=index, agent=runtime):
            results[i] = agent.invoke(AgentInvocation("review", "hello", cancel_event=events[i]))
        worker = threading.Thread(target=invoke)
        worker.start()
        workers.append(worker)
    try:
        deadline = time.monotonic() + 5
        while not all(path.exists() for path in markers) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert all(path.exists() for path in markers)
        events[0].set()
        workers[0].join(3)
        assert not workers[0].is_alive() and workers[1].is_alive()
        assert results[0].error == "Agent invocation aborted."
    finally:
        events[1].set()
        for worker in workers:
            worker.join(3)


def test_workspace_default_change_keeps_mixed_agent_processes_running(tmp_path):
    from electroboy.service.services import build_service_services

    state = ServiceState(tmp_path)
    workspace = state.create_context(workflow_id="software")["context_id"]
    services = build_service_services(state, state.workflow_registry).sessions
    sessions = []
    try:
        with patch("shutil.which", return_value="/bin/true"):
            services.set_workspace_backend(workspace, "codex-fixture-alpha")
            for binary in ("codex-fixture-alpha", "opencode"):
                selected = services.resolve_workspace_selection(workspace, binary)
                session = AgentSession(
                    [sys.executable, "-c", "import time; time.sleep(60)"],
                    tmp_path, kind="ad-hoc",
                )
                services.prepare(state.contexts[workspace], session, selected)
                session.start()
                sessions.append(session)
            services.set_workspace_backend(workspace, "codex-fixture-beta")
        assert all(session.is_active() for session in sessions)
        assert [session.metadata["provider_binary"] for session in sessions] == [
            "codex-fixture-alpha", "opencode",
        ]
    finally:
        for session in sessions:
            session.terminate()


def test_discovered_provider_executables_run_concurrently(tmp_path, monkeypatch):
    from electroboy.service.services import build_service_services

    for binary in ("codex-fixture-alpha", "opencode"):
        executable = tmp_path / binary
        executable.write_text(
            f"#!{sys.executable}\n"
            "import os,time\nfrom pathlib import Path\n"
            "Path(os.path.basename(__file__) + '.started').write_text('running')\n"
            "time.sleep(60)\n"
        )
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    state = ServiceState(tmp_path)
    workspace = state.create_context(workflow_id="software")["context_id"]
    services = build_service_services(state, state.workflow_registry).sessions
    sessions = []
    try:
        for binary in ("codex-fixture-alpha", "opencode"):
            selected = services.resolve_workspace_selection(workspace, binary)
            session = AgentSession(
                interactive_command(tmp_path, "", backend=selected.provider),
                tmp_path, kind="ad-hoc",
            )
            services.prepare(state.contexts[workspace], session, selected)
            session.start()
            sessions.append(session)
        deadline = time.monotonic() + 5
        while not all((tmp_path / f"{name}.started").exists() for name in
                      ("codex-fixture-alpha", "opencode")) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert all((tmp_path / f"{name}.started").exists() for name in
                   ("codex-fixture-alpha", "opencode"))
        services.set_workspace_backend(workspace, "opencode")
        assert all(session.is_active() for session in sessions)
    finally:
        for session in sessions:
            session.terminate()


def test_provider_history_can_be_queried_independently_of_global_default(tmp_path):
    state = ServiceState(tmp_path)
    records = {"sessions": [
        {"session_id": "one", "kind": "ad-hoc", "cwd": str(tmp_path),
         "metadata": {"provider": "codex", "provider_session_id": "codex-id"}},
        {"session_id": "two", "kind": "ad-hoc", "cwd": str(tmp_path),
         "metadata": {"provider": "opencode", "provider_session_id": "open-id"}},
    ]}
    with patch("electroboy.service.app._load_service_session_records", return_value=records):
        entries = state.provider_history(tmp_path, "ad-hoc", provider="opencode")
    assert [entry["provider_session_id"] for entry in entries] == ["open-id"]


def test_creative_agents_capture_workspace_default_and_explicit_override(tmp_path):
    from electroboy.service.services import build_service_services

    service_root = tmp_path / "service"
    service_root.mkdir()
    state = ServiceState(service_root)
    workspace = state.create_context(workflow_id="creative-writing")["context_id"]
    state.create_creative_project(workspace, str(tmp_path / "story"))
    services = build_service_services(state, state.workflow_registry).sessions
    with (
        patch("shutil.which", side_effect=lambda name: f"/bin/{name}"),
        patch.object(AgentSession, "start"),
        patch("electroboy.workflows.creative_writing.controller.codex_session_paths", return_value=frozenset()),
        patch("electroboy.workflows.creative_writing.controller.start_creative_session_tracking"),
    ):
        services.set_workspace_backend(workspace, "codex-fixture-alpha")
        first, _ = state.start_creative_writing_agent(workspace)
        second, _ = state.start_creative_writing_agent(workspace, agent_binary="opencode")
        services.set_workspace_backend(workspace, "codex-fixture-beta")
    assert first.metadata["provider_binary"] == "codex-fixture-alpha"
    assert second.metadata["provider_binary"] == "opencode"
    assert first.metadata["provider"] == "codex"
    assert second.metadata["provider"] == "opencode"
    assert services.workspace_backend_payload(workspace)["backend"] == "codex-fixture-beta"


def test_software_agents_capture_workspace_default_and_explicit_override(tmp_path):
    from electroboy.service.services import build_service_services
    from electroboy.state_store import StateStore

    root = tmp_path / "project"
    root.mkdir()
    StateStore(root).init_run(run_id="test")
    service_root = tmp_path / "service"
    service_root.mkdir()
    state = ServiceState(service_root)
    workspace = state.create_context(workflow_id="software")["context_id"]
    state.open_project(workspace, str(root))
    services = build_service_services(state, state.workflow_registry).sessions
    controller = state.workflow_controller("software")
    with (
        patch("shutil.which", side_effect=lambda name: f"/bin/{name}"),
        patch.object(AgentSession, "start"),
        patch("electroboy.workflows.software.controller.codex_session_paths", return_value=frozenset()),
        patch("electroboy.workflows.software.controller.start_ad_hoc_session_tracking"),
    ):
        services.set_workspace_backend(workspace, "codex-fixture-alpha")
        first, _ = controller.start_ad_hoc_agent(workspace)
        second, _ = controller.start_ad_hoc_agent(workspace, agent_binary="opencode")
        services.set_workspace_backend(workspace, "codex-fixture-beta")
    assert first.metadata["provider_binary"] == "codex-fixture-alpha"
    assert second.metadata["provider_binary"] == "opencode"
    assert services.workspace_backend_payload(workspace)["backend"] == "codex-fixture-beta"


def test_software_stage_agent_captures_explicit_selection(tmp_path):
    from electroboy.state_store import StateStore

    root = tmp_path / "project"
    root.mkdir()
    StateStore(root).init_run(run_id="test")
    service_root = tmp_path / "service"
    service_root.mkdir()
    state = ServiceState(service_root)
    workspace = state.create_context(workflow_id="software")["context_id"]
    state.open_project(workspace, str(root))
    controller = state.workflow_controller("software")
    with (
        patch("shutil.which", return_value="/bin/true"),
        patch.object(AgentSession, "start"),
        patch.object(state.agent_backend, "resolve", wraps=state.agent_backend.resolve) as resolve,
    ):
        session, started = controller.start_requirements_agent(
            workspace, agent_binary="opencode",
        )
    assert resolve.call_count == 1
    assert started
    assert session.metadata["provider"] == "opencode"
    assert session.metadata["provider_binary"] == "opencode"
    assert session.metadata["provider_session_id"].startswith("ses_")


@pytest.mark.parametrize("workflow", ["software", "creative-writing"])
def test_resume_uses_original_provider_after_default_changes(tmp_path, workflow):
    from electroboy.service.services import build_service_services
    from electroboy.state_store import StateStore

    root = tmp_path / "project"
    root.mkdir()
    if workflow == "software":
        StateStore(root).init_run(run_id="test")
    service = tmp_path / "service"
    service.mkdir()
    state = ServiceState(service)
    workspace = state.create_context(workflow_id=workflow)["context_id"]
    if workflow == "software":
        state.open_project(workspace, str(root))
        start = state.workflow_controller(workflow).start_ad_hoc_agent
    else:
        state.open_creative_project(workspace, str(root))
        start = state.start_creative_writing_agent
    services = build_service_services(state, state.workflow_registry).sessions
    with patch("shutil.which", return_value="/bin/true"), patch.object(AgentSession, "start"):
        first, _ = start(workspace, agent_binary="opencode")
        provider_id = first.metadata["provider_session_id"]
        services.set_workspace_backend(workspace, "codex-fixture-alpha")
        resumed, created = start(workspace, provider_session_id=provider_id)
        assert created and resumed.metadata["provider_binary"] == "opencode"
        with pytest.raises(AgentSessionError, match="different executable"):
            start(workspace, provider_session_id=provider_id, agent_binary="codex-fixture-alpha")


def test_stage_resume_uses_original_provider_after_default_changes(tmp_path):
    from electroboy.service.services import build_service_services
    from electroboy.state_store import StateStore

    root = tmp_path / "project"
    root.mkdir()
    StateStore(root).init_run(run_id="test")
    service = tmp_path / "service"
    service.mkdir()
    state = ServiceState(service)
    workspace = state.create_context(workflow_id="software")["context_id"]
    state.open_project(workspace, str(root))
    services = build_service_services(state, state.workflow_registry).sessions
    controller = state.workflow_controller("software")
    with patch("shutil.which", return_value="/bin/true"), patch.object(AgentSession, "start"):
        first, _ = controller.start_requirements_agent(workspace, agent_binary="opencode")
        services.set_workspace_backend(workspace, "codex-fixture-alpha")
        resumed, created = controller.start_requirements_agent(
            workspace, session_id=first.session_id,
        )
    assert created and resumed.metadata["provider_binary"] == "opencode"


def test_stage_history_filters_codex_wrappers(tmp_path):
    from electroboy.service.services import build_service_services
    from electroboy.state_store import StateStore

    root = tmp_path / "project"
    root.mkdir()
    StateStore(root).init_run(run_id="test")
    service = tmp_path / "service"
    service.mkdir()
    state = ServiceState(service)
    workspace = state.create_context(workflow_id="software")["context_id"]
    state.open_project(workspace, str(root))
    services = build_service_services(state, state.workflow_registry).sessions
    history = [
        {"provider_session_id": "one", "provider_binary": "codex-fixture-alpha"},
        {"provider_session_id": "two", "provider_binary": "codex-fixture-beta"},
    ]
    with patch("shutil.which", return_value="/bin/true"), patch.object(state, "provider_history", return_value=history):
        services.set_workspace_backend(workspace, "codex-fixture-alpha")
        result = state.workflow_controller("software").stage_sessions(workspace, "requirements")
    assert [entry["provider_session_id"] for entry in result["sessions"]] == ["one"]




def test_missing_executable_does_not_stop_agent():
    session = AgentSession([sys.executable, "-c", "import time; time.sleep(60)"], ".")
    backend = selection()
    session.start()
    try:
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(AgentSessionError, match="unavailable"),
        ):
            backend.resolve("opencode", Path("."))
        assert session.is_active()
    finally:
        session.terminate()








def test_opencode_command_and_event_contract(tmp_path):
    runtime = OpenCodeExecRuntime(DEFAULT_CONFIG.runtimes["opencode"], tmp_path)
    command = runtime._command(
        AgentInvocation("review", "prompt", fork_provider_session_id="ses_parent")
    )
    assert command[:5] == ["opencode", "run", "--standalone", "--format", "json"]
    assert command[-3:] == ["--session", "ses_parent", "--fork"]
    payload = {
        "ok": False,
        "final_message": "Review failed",
        "issues": [{"message": "bug"}],
    }
    result = runtime._parse_stdout(
        json.dumps(
            {
                "type": "text",
                "sessionID": "ses_new",
                "part": {"text": json.dumps(payload)},
            }
        )
    )
    assert not result.ok
    assert result.structured_output
    assert result.provider_session_id == "ses_new"
    assert result.issues == payload["issues"]
    assert not runtime._parse_stdout('{"type":"step_start"}').ok
    assert not runtime._parse_stdout('{"type":"error","error":"bad model"}').ok
    command = interactive_command(
        tmp_path, "hello", backend="opencode", session_id="ses_new"
    )
    assert command[-4:] == ["--session", "ses_new", "--prompt", "hello"]
    assert "--no-alt-screen" not in command and "--cd" not in command


def test_selected_backend_overrides_project_roles_and_reaches_tmux(tmp_path):
    (tmp_path / "electroboy.toml").write_text('[roles]\ncode_review = "manual"\n')
    with patch.dict("os.environ", {"ELECTROBOY_AGENT_BACKEND": "opencode"}):
        assert (
            runtime_for_role("code_review", tmp_path).config.adapter == "opencode_exec"
        )
    session = AgentSession(["fake"], tmp_path)
    backend = selection()
    with patch("shutil.which", return_value="/bin/true"):
        backend.prepare_selection(session, backend.resolve("codex", tmp_path))
    converted = TmuxAgentSession.from_agent_session(session)
    assert converted.environment["ELECTROBOY_AGENT_BACKEND"] == "codex"
    assert converted.start_guard is session.start_guard


def test_server_api_and_shell_exclusion(tmp_path):
    import urllib.request
    import urllib.error

    server = create_server(tmp_path, port=0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_address[1]}/api/runtime/config"
    try:
        request = urllib.request.Request(
            url,
            data=json.dumps({"backend": "opencode", "revision": 0}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("workflow", ["software", "creative-writing"])
def test_workflow_launches_opencode_and_resumes_only_its_own_history(
    tmp_path, workflow
):
    from electroboy.state_store import StateStore

    service_root = tmp_path / "service"
    service_root.mkdir()
    root = tmp_path / "project"
    state = ServiceState(service_root)
    context_id = state.create_context()["context_id"]
    if workflow == "software":
        root.mkdir()
        StateStore(root).init_run(run_id="test")
        opened = state.open_project(context_id, str(root))
    else:
        opened = state.create_creative_project(context_id, str(root))
    context_id = opened.get("context_id", context_id)
    from electroboy.service.services import build_service_services
    services = build_service_services(state, state.workflow_registry).sessions
    controller = state.workflow_controller(workflow)
    start = (
        controller.start_ad_hoc_agent
        if workflow == "software"
        else state.start_creative_writing_agent
    )
    with patch("shutil.which", return_value="/bin/true"), patch.object(AgentSession, "start"):
        services.set_workspace_backend(context_id, "opencode")
        first, created = start(context_id)
        assert created and first.command[0] == "opencode"
        assert "--standalone" in first.command
        assert first.metadata["provider"] == "opencode"
        assert first.environment["ELECTROBOY_AGENT_BACKEND"] == "opencode"
        provider_id = first.metadata["provider_session_id"]
        resumed, created = start(context_id, provider_session_id=provider_id)
        assert resumed.metadata["resumed_session"]
        assert provider_id in resumed.command
        with pytest.raises(AgentSessionError, match="not found"):
            start(
                context_id, provider_session_id="00000000-0000-0000-0000-000000000000"
            )
    history = state.provider_history(root, first.kind, provider="opencode")
    assert any(entry["provider_session_id"] == provider_id for entry in history)


def test_switch_leaves_shell_running_and_changes_pipeline_child_environment(tmp_path):
    from electroboy.state_store import StateStore

    StateStore(tmp_path).init_run(run_id="test")
    state = ServiceState(tmp_path)
    context_id = state.create_context()["context_id"]
    opened = state.open_project(context_id, str(tmp_path))
    context_id = opened.get("context_id", context_id)
    context = state.contexts[context_id]
    shell = AgentSession(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        tmp_path,
        kind="project-shell",
    )
    context.project_shell_sessions[shell.session_id] = shell
    shell = state._prepare_session_locked(context, shell)
    shell.start()
    try:
        from electroboy.service.services import build_service_services
        services = build_service_services(state, state.workflow_registry).sessions
        with patch("shutil.which", return_value="/bin/true"), patch.object(AgentSession, "start"):
            services.set_workspace_backend(context_id, "opencode")
            assert shell.is_active()
            agent, started = state.start_requirements_agent(context_id)
        assert started
        assert agent.environment["ELECTROBOY_AGENT_BACKEND"] == "opencode"
    finally:
        shell.terminate()


def test_new_provider_does_not_resume_old_code_learner_slot(tmp_path):
    from electroboy.adapters.base import AgentResult
    from electroboy.workflows.code_learner.agent_sessions import (
        AgentSessionRegistry,
        ReusableAgentRuntime,
    )

    registry = AgentSessionRegistry(tmp_path)
    registry.prepare()
    registry.record(
        "analysis",
        AgentResult(
            ok=True,
            final_message="old",
            provider="codex",
            provider_session_id="old-codex",
        ),
    )
    runtime = OpenCodeExecRuntime(DEFAULT_CONFIG.runtimes["opencode"], tmp_path)
    with patch.object(
        runtime,
        "invoke",
        return_value=AgentResult(
            ok=True,
            final_message="new",
            provider="opencode",
            provider_session_id="ses_new",
        ),
    ) as invoke:
        ReusableAgentRuntime(runtime, registry, slot="analysis").invoke(
            AgentInvocation("analysis", "go")
        )
    assert invoke.call_args.args[0].provider_session_id is None




def test_backend_discovers_executable_codex_names_from_path(tmp_path, monkeypatch):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    for directory, name in (
        (first, "codex"),
        (first, "codex-lab"),
        (first, "codex-duplicate"),
        (second, "codex-duplicate"),
        (second, "codexpert"),
        (second, "codex-"),
        (second, "codex-linux-sandbox"),
        (second, "opencode"),
    ):
        executable = directory / name
        executable.touch()
        executable.chmod(0o755)
    (first / "codex-disabled").touch(mode=0o644)
    (first / "codex-directory").mkdir()
    (first / "codex-linked").symlink_to(first / "codex-lab")
    (first / "codex-broken").symlink_to(first / "missing")
    invalid_directory = tmp_path / "ordinary-file"
    invalid_directory.touch()
    monkeypatch.setenv("PATH", os.pathsep.join(map(str, (
        tmp_path / "missing", invalid_directory, first, second, first,
    ))))
    backend = AgentBackend(threading.RLock(), lambda: [tmp_path])
    payload = backend.payload()
    assert payload["backends"] == [
        "codex", "codex-duplicate", "codex-lab", "codex-linked", "opencode",
    ]
    assert payload["availability"] == {
        "codex": True, "codex-duplicate": True, "codex-lab": True,
        "codex-linked": True, "opencode": True,
    }

    # Refresh discovery when executables appear or disappear in existing PATH dirs.
    (first / "codex-lab").unlink()
    (second / "codex-new").write_text("new executable")
    (second / "codex-new").chmod(0o755)
    assert backend.payload()["backends"] == [
        "codex", "codex-duplicate", "codex-new", "opencode",
    ]


def test_backend_discovery_honors_empty_path_entries(tmp_path, monkeypatch):
    executable = tmp_path / "codex-local"
    executable.touch(mode=0o755)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", os.pathsep.join(("", str(tmp_path / "missing"))))
    backend = AgentBackend(threading.RLock(), lambda: [tmp_path])
    payload = backend.payload()
    assert payload["backends"] == ["codex", "codex-local"]
    assert payload["availability"]["codex-local"] is True
    monkeypatch.setenv("PATH", "")
    assert backend.payload()["backends"] == ["codex"]


def test_saved_codex_wrapper_remains_visible_after_removal(tmp_path, monkeypatch):
    executable = tmp_path / "codex-temporary"
    executable.touch(mode=0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    path = tmp_path / "state" / "backend.json"
    backend = AgentBackend(threading.RLock(), lambda: [tmp_path], path)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"binary": "codex-temporary"}))
    executable.unlink()

    restored = AgentBackend(threading.RLock(), lambda: [tmp_path], path)
    payload = restored.payload()
    assert payload["backend"] == "codex-temporary"
    assert payload["provider"] == "codex"
    assert payload["backends"] == ["codex-temporary"]
    assert payload["availability"]["codex-temporary"] is False


@pytest.mark.parametrize("binary", [
    "unrelated", "../codex-team", "codex-team/tool", "codex-", "codex-\0",
    "codex-linux-sandbox",
    ["codex-team"], {"name": "codex-team"}, None,
])
def test_invalid_saved_binary_falls_back_to_codex(tmp_path, binary):
    path = tmp_path / "backend.json"
    path.write_text(json.dumps({"binary": binary}))
    backend = AgentBackend(threading.RLock(), lambda: [tmp_path], path)
    assert backend.binary == "codex"
    with pytest.raises(ValueError, match="Unknown backend binary"):
        backend.resolve(binary, tmp_path)


@pytest.mark.parametrize("binary", ["codex-team-alpha", "codex-personal-test"])
def test_binary_selection_reaches_terminal_background_and_workflow_children(tmp_path, binary):
    from electroboy.runtime import backend_config

    backend = AgentBackend(threading.RLock(), lambda: [tmp_path])
    with patch("shutil.which", return_value="/bin/true"):
        chosen = backend.resolve(binary, tmp_path)
        payload = backend.payload(tmp_path, binary)
    assert payload["backend"] == binary
    assert payload["provider"] == "codex"
    original = backend_config("codex", tmp_path, interactive=True)
    terminal = AgentSession([original.command, "--no-alt-screen"], tmp_path)
    backend.prepare_selection(terminal, chosen)
    assert terminal.command == [binary, "--no-alt-screen"]
    assert terminal.metadata["provider"] == "codex"
    assert terminal.environment["ELECTROBOY_AGENT_EXECUTABLE"] == binary
    converted = TmuxAgentSession.from_agent_session(terminal)
    assert converted.command == terminal.command
    assert converted.environment == terminal.environment

    # A pipeline child launches ElectroBoy first, then resolves its own runtime.
    pipeline = AgentSession([sys.executable, "-m", "electroboy", "code"], tmp_path)
    backend.prepare_selection(pipeline, chosen)
    assert pipeline.command[0] == sys.executable
    with patch.dict("os.environ", pipeline.environment):
        runtime = runtime_for_role("code_review", tmp_path)
        assert runtime.config.command == binary
        assert runtime.config.args == DEFAULT_CONFIG.runtimes["codex"].args
        assert runtime.config.env == DEFAULT_CONFIG.runtimes["codex"].env
    runtime = backend.selected_runtime_factory(chosen)("design_author", tmp_path)
    assert runtime.config.command == binary
    assert runtime.config.adapter == "codex_interactive"
    runtime = backend.selected_runtime_factory(chosen)("code_review", tmp_path)
    assert runtime.config.command == binary
    assert runtime.config.adapter == "codex_exec"




def test_selected_binary_executes_independently_of_other_selections(tmp_path, monkeypatch):
    executable = tmp_path / "codex-team-alpha"
    marker = tmp_path / "started.txt"
    executable.write_text(
        f"#!{sys.executable}\n"
        "import os, time\nfrom pathlib import Path\n"
        "Path('started.txt').write_text(os.environ['ELECTROBOY_AGENT_BACKEND'])\n"
        "time.sleep(60)\n"
    )
    executable.chmod(0o755)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ["PATH"])
    sessions = []
    backend = AgentBackend(threading.RLock(), lambda: [tmp_path])
    assert "codex-team-alpha" in backend.payload()["backends"]
    chosen = backend.resolve("codex-team-alpha", tmp_path)
    session = AgentSession(interactive_command(tmp_path, "fixture"), tmp_path)
    backend.prepare_selection(session, chosen)
    sessions.append(session)
    session.start()
    try:
        deadline = time.monotonic() + 5
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert marker.read_text() == "codex"
        # The target may be absent; that must not stop the running wrapper.
        with patch("shutil.which", return_value=None):
            with pytest.raises(AgentSessionError, match="unavailable"):
                backend.resolve("codex-personal-test", tmp_path)
        assert session.is_active()
        with patch("shutil.which", return_value="/bin/true"):
            backend.resolve("codex-personal-test", tmp_path)
        assert session.is_active()
    finally:
        session.terminate()


@pytest.mark.parametrize("provider", ["codex", "opencode"])
def test_explicit_backend_ignores_inherited_wrapper(tmp_path, monkeypatch, provider):
    monkeypatch.setenv("ELECTROBOY_AGENT_BACKEND", "codex")
    monkeypatch.setenv("ELECTROBOY_AGENT_EXECUTABLE", "codex-team-alpha")
    backend = AgentBackend(threading.RLock(), lambda: [tmp_path])
    with patch("shutil.which", return_value="/bin/true"):
        chosen = backend.resolve(provider, tmp_path)

    runtime = runtime_for_role("code_review", tmp_path, backend=provider)
    assert runtime.config.command == DEFAULT_CONFIG.runtimes[provider].command
    runtime = backend.selected_runtime_factory(chosen)("code_review", tmp_path)
    assert runtime.config.command == DEFAULT_CONFIG.runtimes[provider].command

    # Workflow CLI children inherit os.environ plus the prepared session values.
    pipeline = AgentSession([sys.executable, "-m", "electroboy", "code"], tmp_path)
    backend.prepare_selection(pipeline, chosen)
    with patch.dict("os.environ", pipeline.environment):
        runtime = runtime_for_role("code_review", tmp_path)
        assert runtime.config.command == DEFAULT_CONFIG.runtimes[provider].command
    assert TmuxAgentSession.from_agent_session(pipeline).environment == pipeline.environment
