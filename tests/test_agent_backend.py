"""Provider switching must cancel work before admitting another provider."""

import json
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
        assert json.load(urllib.request.urlopen(url))["backend"] == "codex"
        request = urllib.request.Request(
            url,
            data=json.dumps({"backend": "opencode", "revision": 0}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(request)
        assert error.value.code == 409
        request.data = json.dumps(
            {"backend": "opencode", "revision": 0, "confirmed": True}
        ).encode()
        with patch("shutil.which", return_value="/bin/true"):
            assert json.load(urllib.request.urlopen(request))["backend"] == "opencode"
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
