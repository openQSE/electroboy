"""Provider switching must cancel work before admitting another provider."""

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
from electroboy.service.agent_backend import AgentBackend, ManagedRuntime
from electroboy.service.app import ServiceState, create_server
from electroboy.service.sessions import (
    AgentSession,
    AgentSessionError,
    TmuxAgentSession,
)


def selection(sessions=()):
    return AgentBackend(threading.RLock(), lambda: sessions, lambda: [Path(".")])


def test_captured_selections_are_independent_of_later_default_changes(tmp_path):
    backend = AgentBackend(threading.RLock(), lambda: [], lambda: [tmp_path])
    with patch("shutil.which", side_effect=lambda name: f"/bin/{name}"):
        codex = backend.resolve("codex-atoz", tmp_path)
        opencode = backend.resolve("opencode", tmp_path)
        session = AgentSession(["codex", "resume", "example"], tmp_path)
        backend.prepare_selection(session, codex)
        factory = backend.selected_runtime_factory(opencode)
        backend.switch("codex-ornl", confirmed=True, revision=0)

    assert session.command[0] == "codex-atoz"
    assert session.metadata["provider_binary"] == "codex-atoz"
    assert session.environment["ELECTROBOY_AGENT_EXECUTABLE"] == "codex-atoz"
    assert not factory.cancel_event.is_set()
    assert factory("code_review", tmp_path).config.adapter == "opencode_exec"


def test_captured_selection_requires_available_executable(tmp_path):
    backend = selection()
    with patch("shutil.which", return_value=None):
        with pytest.raises(AgentSessionError, match="unavailable"):
            backend.resolve("codex-atoz", tmp_path)


def test_workspace_default_change_keeps_mixed_agent_processes_running(tmp_path):
    from electroboy.service.services import build_service_services

    state = ServiceState(tmp_path)
    workspace = state.create_context(workflow_id="software")["context_id"]
    services = build_service_services(state, state.workflow_registry).sessions
    sessions = []
    try:
        with patch("shutil.which", return_value="/bin/true"):
            services.set_workspace_backend(workspace, "codex-atoz")
            for binary in ("codex-atoz", "opencode"):
                selected = services.resolve_workspace_selection(workspace, binary)
                session = AgentSession(
                    [sys.executable, "-c", "import time; time.sleep(60)"],
                    tmp_path, kind="ad-hoc",
                )
                services.prepare(state.contexts[workspace], session, selected)
                session.start()
                sessions.append(session)
            services.set_workspace_backend(workspace, "codex-ornl")
        assert all(session.is_active() for session in sessions)
        assert [session.metadata["provider_binary"] for session in sessions] == [
            "codex-atoz", "opencode",
        ]
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
        services.set_workspace_backend(workspace, "codex-atoz")
        first, _ = state.start_creative_writing_agent(workspace)
        second, _ = state.start_creative_writing_agent(workspace, agent_binary="opencode")
        services.set_workspace_backend(workspace, "codex-ornl")
    assert first.metadata["provider_binary"] == "codex-atoz"
    assert second.metadata["provider_binary"] == "opencode"
    assert first.metadata["provider"] == "codex"
    assert second.metadata["provider"] == "opencode"
    assert services.workspace_backend_payload(workspace)["backend"] == "codex-ornl"


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
        services.set_workspace_backend(workspace, "codex-atoz")
        first, _ = controller.start_ad_hoc_agent(workspace)
        second, _ = controller.start_ad_hoc_agent(workspace, agent_binary="opencode")
        services.set_workspace_backend(workspace, "codex-ornl")
    assert first.metadata["provider_binary"] == "codex-atoz"
    assert second.metadata["provider_binary"] == "opencode"
    assert services.workspace_backend_payload(workspace)["backend"] == "codex-ornl"


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
    ):
        session, started = controller.start_requirements_agent(
            workspace, agent_binary="opencode",
        )
    assert started
    assert session.metadata["provider"] == "opencode"
    assert session.metadata["provider_binary"] == "opencode"
    assert session.metadata["provider_session_id"].startswith("ses_")


def test_defaults_confirmation_and_stale_revision():
    backend = selection()
    assert backend.payload()["backend"] == "codex"
    with pytest.raises(AgentSessionError, match="Confirm"):
        backend.switch("opencode", revision=0)
    with patch("shutil.which", return_value="/bin/true"):
        assert (
            backend.switch("opencode", confirmed=True, revision=0)["backend"]
            == "opencode"
        )
        with pytest.raises(AgentSessionError, match="changed"):
            backend.switch("codex", confirmed=True, revision=0)
        assert backend.switch("codex", confirmed=True, revision=1)["backend"] == "codex"
    with pytest.raises(ValueError):
        backend.switch("invalid", confirmed=True, revision=2)


def test_missing_executable_does_not_stop_agent():
    session = AgentSession([sys.executable, "-c", "import time; time.sleep(60)"], ".")
    backend = selection([session])
    session.start()
    try:
        with (
            patch("shutil.which", return_value=None),
            pytest.raises(AgentSessionError, match="unavailable"),
        ):
            backend.switch("opencode", confirmed=True, revision=0)
        assert session.is_active()
        assert backend.selected == "codex"
    finally:
        session.terminate()


def test_switch_stops_process_and_rejects_delayed_launch():
    running = AgentSession([sys.executable, "-c", "import time; time.sleep(60)"], ".")
    delayed = AgentSession([sys.executable, "-c", "pass"], ".")
    backend = selection([running, delayed])
    backend.prepare(running)
    backend.prepare(delayed)
    running.start()
    try:
        with patch("shutil.which", return_value="/bin/true"):
            backend.switch("opencode", confirmed=True, revision=0)
        assert not running.is_active()
        with pytest.raises(AgentSessionError, match="changed"):
            delayed.start()
        assert delayed.process is None
    finally:
        running.terminate()


def test_failed_termination_keeps_old_backend():
    session = AgentSession(["fake"], ".")
    backend = selection([session])
    with (
        patch.object(session, "is_active", return_value=True),
        patch.object(session, "terminate"),
        patch("shutil.which", return_value="/bin/true"),
    ):
        with pytest.raises(AgentSessionError, match="Could not stop"):
            backend.switch("opencode", confirmed=True, revision=0)
    assert backend.selected == "codex"
    assert not backend.switching


def test_background_process_is_cancelled_and_old_factory_invalidated(tmp_path):
    script = tmp_path / "agent.py"
    script.write_text("import sys,time\nsys.stdin.read()\ntime.sleep(60)\n")
    backend = selection()
    factory = backend.runtime_factory()
    runtime = GenericCliRuntime(
        RuntimeConfig("fake", "generic_cli", sys.executable, [str(script)]), tmp_path
    )
    managed = ManagedRuntime(backend, 0, runtime)
    errors = []

    def invoke():
        try:
            managed.invoke(AgentInvocation("review", "hello"))
        except AgentSessionError as error:
            errors.append(str(error))

    worker = threading.Thread(target=invoke)
    worker.start()
    deadline = time.monotonic() + 3
    while not backend.invocations and time.monotonic() < deadline:
        time.sleep(0.01)
    with patch("shutil.which", return_value="/bin/true"):
        backend.switch("opencode", confirmed=True, revision=0)
    worker.join(3)
    assert not worker.is_alive()
    assert errors
    with pytest.raises(AgentSessionError, match="changed"):
        factory("review", tmp_path)


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
    backend.prepare(session)
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
    with patch("shutil.which", return_value="/bin/true"):
        state.agent_backend.switch("opencode", confirmed=True, revision=0)
    controller = state.workflow_controller(workflow)
    start = (
        controller.start_ad_hoc_agent
        if workflow == "software"
        else state.start_creative_writing_agent
    )
    with patch.object(AgentSession, "start"):
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
    history = state.provider_history(root, first.kind)
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
        with patch("shutil.which", return_value="/bin/true"):
            state.agent_backend.switch("opencode", confirmed=True, revision=0)
        assert shell.is_active()
        with patch.object(AgentSession, "start"):
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


def test_tmux_switch_stops_session_and_propagates_provider(tmp_path):
    import shutil

    if shutil.which("tmux") is None:
        pytest.skip("tmux is not installed")
    output = tmp_path / "backend.txt"
    script = tmp_path / "agent.py"
    script.write_text(
        'import os,time\nfrom pathlib import Path\nPath("backend.txt").write_text(os.environ["ELECTROBOY_AGENT_BACKEND"])\ntime.sleep(60)\n'
    )
    session = TmuxAgentSession([sys.executable, str(script)], tmp_path)
    backend = selection([session])
    backend.prepare(session)
    session.start()
    try:
        deadline = time.monotonic() + 5
        while not output.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert output.read_text() == "codex"
        with patch("shutil.which", return_value="/bin/true"):
            backend.switch("opencode", confirmed=True, revision=0)
        assert not session.is_active()
        assert backend.selected == "opencode"
    finally:
        session.terminate()


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
    backend = AgentBackend(threading.RLock(), lambda: [], lambda: [tmp_path])
    payload = backend.payload()
    assert payload["backends"] == [
        "codex", "codex-duplicate", "codex-lab", "codex-linked", "opencode",
    ]
    assert payload["availability"] == {
        "codex": True, "codex-duplicate": True, "codex-lab": True,
        "codex-linked": True, "opencode": False,
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
    backend = AgentBackend(threading.RLock(), lambda: [], lambda: [tmp_path])
    payload = backend.payload()
    assert payload["backends"] == ["codex", "codex-local", "opencode"]
    assert payload["availability"]["codex-local"] is True
    monkeypatch.setenv("PATH", "")
    assert backend.payload()["backends"] == ["codex", "opencode"]


def test_saved_codex_wrapper_remains_visible_after_removal(tmp_path, monkeypatch):
    executable = tmp_path / "codex-temporary"
    executable.touch(mode=0o755)
    monkeypatch.setenv("PATH", str(tmp_path))
    path = tmp_path / "state" / "backend.json"
    backend = AgentBackend(threading.RLock(), lambda: [], lambda: [tmp_path], path)
    backend.switch("codex-temporary", confirmed=True, revision=0)
    executable.unlink()

    restored = AgentBackend(threading.RLock(), lambda: [], lambda: [tmp_path], path)
    payload = restored.payload()
    assert payload["backend"] == "codex-temporary"
    assert payload["provider"] == "codex"
    assert payload["backends"] == ["codex", "codex-temporary", "opencode"]
    assert payload["availability"]["codex-temporary"] is False


@pytest.mark.parametrize("binary", [
    "unrelated", "../codex-team", "codex-team/tool", "codex-", "codex-\0",
    "codex-linux-sandbox",
    ["codex-team"], {"name": "codex-team"}, None,
])
def test_invalid_saved_binary_falls_back_to_codex(tmp_path, binary):
    path = tmp_path / "backend.json"
    path.write_text(json.dumps({"binary": binary}))
    backend = AgentBackend(threading.RLock(), lambda: [], lambda: [tmp_path], path)
    assert backend.binary == backend.selected == "codex"
    with pytest.raises(ValueError, match="Unknown backend binary"):
        backend.switch(binary, confirmed=True, revision=0)


@pytest.mark.parametrize("binary", ["codex-team-alpha", "codex-personal-test"])
def test_binary_selection_reaches_terminal_background_and_workflow_children(tmp_path, binary):
    from electroboy.runtime import backend_config

    backend = AgentBackend(threading.RLock(), lambda: [], lambda: [tmp_path])
    with patch("shutil.which", return_value="/bin/true"):
        payload = backend.switch(binary, confirmed=True, revision=0)
    assert payload["backend"] == binary
    assert payload["provider"] == "codex"
    original = backend_config("codex", tmp_path, interactive=True)
    terminal = AgentSession([original.command, "--no-alt-screen"], tmp_path)
    backend.prepare(terminal)
    assert terminal.command == [binary, "--no-alt-screen"]
    assert terminal.metadata["provider"] == "codex"
    assert terminal.environment["ELECTROBOY_AGENT_EXECUTABLE"] == binary
    converted = TmuxAgentSession.from_agent_session(terminal)
    assert converted.command == terminal.command
    assert converted.environment == terminal.environment

    # A pipeline child launches ElectroBoy first, then resolves its own runtime.
    pipeline = AgentSession([sys.executable, "-m", "electroboy", "code"], tmp_path)
    backend.prepare(pipeline)
    assert pipeline.command[0] == sys.executable
    with patch.dict("os.environ", pipeline.environment):
        runtime = runtime_for_role("code_review", tmp_path)
        assert runtime.config.command == binary
        assert runtime.config.args == DEFAULT_CONFIG.runtimes["codex"].args
        assert runtime.config.env == DEFAULT_CONFIG.runtimes["codex"].env
    runtime = backend.runtime_factory()("design_author", tmp_path)
    assert runtime.config.command == binary
    assert runtime.config.adapter == "codex_interactive"
    runtime = backend.runtime_factory()("code_review", tmp_path)
    assert runtime.config.command == binary
    assert runtime.config.adapter == "codex_exec"


def test_binary_selection_persists_and_same_provider_switch_invalidates_jobs(tmp_path):
    path = tmp_path / "state" / "backend.json"
    backend = AgentBackend(threading.RLock(), lambda: [], lambda: [tmp_path], path)
    with patch("shutil.which", return_value="/bin/true"):
        backend.switch("codex-team-alpha", confirmed=True, revision=0)
        factory = backend.runtime_factory()
        backend.switch("codex-personal-test", confirmed=True, revision=1)
    assert factory.cancel_event.is_set()
    with pytest.raises(AgentSessionError, match="changed"):
        factory("code_review", tmp_path)
    restored = AgentBackend(threading.RLock(), lambda: [], lambda: [tmp_path], path)
    assert restored.binary == "codex-personal-test"
    assert restored.selected == "codex"
    with patch("shutil.which", return_value=None):
        assert restored.payload()["availability"]["codex-personal-test"] is False
        with pytest.raises(AgentSessionError, match="unavailable"):
            restored.switch("codex-team-alpha", confirmed=True, revision=0)
    assert restored.binary == "codex-personal-test"
    assert json.loads(path.read_text())["binary"] == "codex-personal-test"
    path.write_text("invalid json")
    assert AgentBackend(threading.RLock(), lambda: [], lambda: [tmp_path], path).binary == "codex"


def test_selected_binary_executes_and_same_provider_switch_stops_it(tmp_path, monkeypatch):
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
    backend = AgentBackend(threading.RLock(), lambda: sessions, lambda: [tmp_path])
    assert "codex-team-alpha" in backend.payload()["backends"]
    backend.switch("codex-team-alpha", confirmed=True, revision=0)
    session = AgentSession(interactive_command(tmp_path, "fixture"), tmp_path)
    backend.prepare(session)
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
                backend.switch("codex-personal-test", confirmed=True, revision=1)
        assert session.is_active()
        with patch("shutil.which", return_value="/bin/true"):
            backend.switch("codex-personal-test", confirmed=True, revision=1)
        assert not session.is_active()
    finally:
        session.terminate()


@pytest.mark.parametrize("provider", ["codex", "opencode"])
def test_explicit_backend_ignores_inherited_wrapper(tmp_path, monkeypatch, provider):
    monkeypatch.setenv("ELECTROBOY_AGENT_BACKEND", "codex")
    monkeypatch.setenv("ELECTROBOY_AGENT_EXECUTABLE", "codex-team-alpha")
    backend = AgentBackend(threading.RLock(), lambda: [], lambda: [tmp_path])
    with patch("shutil.which", return_value="/bin/true"):
        backend.switch(provider, confirmed=True, revision=0)

    runtime = runtime_for_role("code_review", tmp_path, backend=provider)
    assert runtime.config.command == DEFAULT_CONFIG.runtimes[provider].command
    runtime = backend.runtime_factory()("code_review", tmp_path)
    assert runtime.config.command == DEFAULT_CONFIG.runtimes[provider].command

    # Workflow CLI children inherit os.environ plus the prepared session values.
    pipeline = AgentSession([sys.executable, "-m", "electroboy", "code"], tmp_path)
    backend.prepare(pipeline)
    with patch.dict("os.environ", pipeline.environment):
        runtime = runtime_for_role("code_review", tmp_path)
        assert runtime.config.command == DEFAULT_CONFIG.runtimes[provider].command
    assert TmuxAgentSession.from_agent_session(pipeline).environment == pipeline.environment
