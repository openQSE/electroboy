from __future__ import annotations

import http.client
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.cli import build_parser  # noqa: E402
from electroboy.service import (  # noqa: E402
    INDEX_HTML,
    AgentSession,
    ServiceState,
    _agent_process_env,
    _clean_terminal_output,
    _requirements_command,
    _terminal_input_chunks_for_message,
    _terminal_input_for_message,
    browse_directories,
    create_server,
    workflow_payload,
)
from electroboy.state_store import StateError, StateStore  # noqa: E402


class ServiceTests(unittest.TestCase):
    def test_health_endpoint_reports_connected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            try:
                server = create_server(root, port=0)
            except PermissionError as error:
                self.skipTest(f"local socket creation is not permitted: {error}")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()

            try:
                status, body, content_type = request(server, "/api/health")
            finally:
                server.shutdown()
                thread.join(timeout=2)
                server.server_close()

        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/json; charset=utf-8")
        payload = json.loads(body)
        self.assertEqual(payload["status"], "connected")
        self.assertEqual(payload["service"], "electroboy")
        self.assertEqual(payload["root"], str(root.resolve()))

    def test_index_page_fetches_health_and_prints_connected(self) -> None:
        self.assertIn('fetch("/api/health"', INDEX_HTML)
        self.assertIn('connection.textContent = activeProjectRoot', INDEX_HTML)
        self.assertIn('class="stage-scroll"', INDEX_HTML)
        self.assertIn('const workflowPane = document.querySelector(".workflow-pane");', INDEX_HTML)
        self.assertIn('const stageScroll = document.querySelector(".stage-scroll");', INDEX_HTML)
        self.assertIn("overflow: visible;", INDEX_HTML)
        self.assertIn("z-index: 30;", INDEX_HTML)
        self.assertIn("z-index: 0;", INDEX_HTML)
        self.assertIn('data-stage="project"', INDEX_HTML)
        self.assertIn('data-stage="requirements"', INDEX_HTML)
        self.assertIn('id="projectMenu"', INDEX_HTML)
        self.assertIn("openProject.disabled = hasActiveProject", INDEX_HTML)
        self.assertIn("newProject.disabled = hasActiveProject", INDEX_HTML)
        self.assertIn("deactivateProject.disabled = !hasActiveProject", INDEX_HTML)
        self.assertIn("if (activeProjectRoot)", INDEX_HTML)
        self.assertIn('id="projectPanel"', INDEX_HTML)
        self.assertIn('id="projectPath"', INDEX_HTML)
        self.assertIn('id="fileBrowser"', INDEX_HTML)
        self.assertIn('id="browserPath"', INDEX_HTML)
        self.assertIn('id="selectDirectory"', INDEX_HTML)
        self.assertIn('id="closeBrowser"', INDEX_HTML)
        self.assertIn('id="deactivateProject"', INDEX_HTML)
        self.assertIn('id="requirementsMenu"', INDEX_HTML)
        self.assertIn('id="agentOutput"', INDEX_HTML)
        self.assertIn('id="agentInput"', INDEX_HTML)
        self.assertIn('id="interruptAgent"', INDEX_HTML)
        self.assertIn("xterm@5.3.0", INDEX_HTML)
        self.assertIn("xterm-addon-fit@0.8.0", INDEX_HTML)
        self.assertIn("new window.Terminal", INDEX_HTML)
        self.assertIn("disableStdin: true", INDEX_HTML)
        self.assertIn('fetch("/api/contexts"', INDEX_HTML)
        self.assertIn('let contextId = "";', INDEX_HTML)
        self.assertIn("function contextUrl(path)", INDEX_HTML)
        self.assertIn('contextUrl("/api/project")', INDEX_HTML)
        self.assertIn('"/api/project/open"', INDEX_HTML)
        self.assertIn('"/api/project/new"', INDEX_HTML)
        self.assertIn('contextUrl("/api/project/deactivate")', INDEX_HTML)
        self.assertIn("/api/files/browse?path=", INDEX_HTML)
        self.assertIn("function selectCurrentDirectory()", INDEX_HTML)
        self.assertIn("activating:", INDEX_HTML)
        self.assertIn("activation request failed:", INDEX_HTML)
        self.assertIn("choose a project directory first", INDEX_HTML)
        self.assertIn("projectPanel.hidden = true;", INDEX_HTML)
        self.assertIn(
            'EventSource(contextUrl("/api/agents/requirements/events"))',
            INDEX_HTML,
        )
        self.assertIn('contextUrl("/api/agents/requirements/start")', INDEX_HTML)
        self.assertIn('contextUrl("/api/agents/requirements/message")', INDEX_HTML)
        self.assertIn('contextUrl("/api/agents/requirements/interrupt")', INDEX_HTML)
        self.assertIn('contextUrl("/api/agents/requirements/resize")', INDEX_HTML)
        self.assertIn("payload.terminal || payload.text", INDEX_HTML)
        self.assertIn("function clearAgentOutput()", INDEX_HTML)
        self.assertIn("terminal.clear();", INDEX_HTML)
        self.assertIn("agentInput.value = \"\";", INDEX_HTML)
        self.assertIn("function positionStageMenu(menu, stage)", INDEX_HTML)
        self.assertIn(
            "toggleStageMenu(requirementsMenu, requirementsStage, projectMenu)",
            INDEX_HTML,
        )
        self.assertIn("stageScroll.addEventListener(\"scroll\", repositionOpenStageMenu)", INDEX_HTML)
        self.assertIn('event.code === "NumpadEnter"', INDEX_HTML)
        self.assertIn("isEnter && event.shiftKey", INDEX_HTML)

    def test_workflow_payload_exposes_project_operations_before_activation(
        self,
    ) -> None:
        payload = workflow_payload()
        stages = payload["stages"]
        self.assertIsInstance(stages, list)
        operations = {
            str(stage["id"]): stage["operations"]
            for stage in stages
            if isinstance(stage, dict)
        }

        self.assertEqual(operations["project"], ["Open", "Create"])
        self.assertEqual(operations["requirements"], [])
        for stage, stage_operations in operations.items():
            if stage not in {"project", "requirements"}:
                self.assertEqual(stage_operations, [])

    def test_workflow_payload_exposes_requirements_start_after_activation(
        self,
    ) -> None:
        payload = workflow_payload(ROOT)
        operations = {
            str(stage["id"]): stage["operations"]
            for stage in payload["stages"]
            if isinstance(stage, dict)
        }

        self.assertEqual(operations["project"], ["Open", "Create", "Deactivate"])
        self.assertEqual(operations["requirements"], ["Start"])

    def test_service_state_opens_existing_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            payload = state.open_project(context_id, str(project_root))

        self.assertEqual(payload["status"], "opened")
        self.assertEqual(payload["context_id"], context_id)
        self.assertEqual(payload["active_project_root"], str(project_root.resolve()))
        self.assertEqual(
            payload["activate_command"],
            f"source {project_root.resolve() / '.electroboy' / 'bin' / 'activate'}",
        )

    def test_new_context_starts_without_active_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            StateStore(root).init_run(run_id="run-1")

            state = ServiceState(root)
            payload = state.create_context()

        self.assertIsNone(payload["active_project_root"])
        self.assertEqual(payload["service_root"], str(root.resolve()))

    def test_service_state_keeps_project_activation_per_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            first_project = Path(tmp) / "first"
            second_project = Path(tmp) / "second"
            service_root.mkdir()
            first_project.mkdir()
            second_project.mkdir()
            StateStore(first_project).init_run(run_id="run-1")
            StateStore(second_project).init_run(run_id="run-2")

            state = ServiceState(service_root)
            first_context = str(state.create_context()["context_id"])
            second_context = str(state.create_context()["context_id"])

            state.open_project(first_context, str(first_project))

            self.assertEqual(
                state.project_payload(first_context)["active_project_root"],
                str(first_project.resolve()),
            )
            self.assertIsNone(
                state.project_payload(second_context)["active_project_root"]
            )

            state.open_project(second_context, str(second_project))

            self.assertEqual(
                state.project_payload(first_context)["active_project_root"],
                str(first_project.resolve()),
            )
            self.assertEqual(
                state.project_payload(second_context)["active_project_root"],
                str(second_project.resolve()),
            )

    def test_project_deactivation_is_scoped_to_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            first_project = Path(tmp) / "first"
            second_project = Path(tmp) / "second"
            service_root.mkdir()
            first_project.mkdir()
            second_project.mkdir()
            StateStore(first_project).init_run(run_id="run-1")
            StateStore(second_project).init_run(run_id="run-2")

            state = ServiceState(service_root)
            first_context = str(state.create_context()["context_id"])
            second_context = str(state.create_context()["context_id"])
            state.open_project(first_context, str(first_project))
            state.open_project(second_context, str(second_project))

            payload = state.deactivate_project(first_context)

            self.assertEqual(payload["status"], "deactivated")
            self.assertIsNone(
                state.project_payload(first_context)["active_project_root"]
            )
            self.assertEqual(
                state.project_payload(second_context)["active_project_root"],
                str(second_project.resolve()),
            )

    def test_project_deactivation_terminates_running_requirements_agent(self) -> None:
        class FakeSession:
            def __init__(self) -> None:
                self.terminated = False

            def is_active(self) -> bool:
                return not self.terminated

            def terminate(self) -> None:
                self.terminated = True

        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            project_root = Path(tmp) / "project"
            service_root.mkdir()
            project_root.mkdir()
            StateStore(project_root).init_run(run_id="run-1")

            state = ServiceState(service_root)
            context_id = str(state.create_context()["context_id"])
            state.open_project(context_id, str(project_root))
            session = FakeSession()
            with state.lock:
                state.contexts[context_id].requirements_session = session  # type: ignore[assignment]

            payload = state.deactivate_project(context_id)

        self.assertTrue(session.terminated)
        self.assertEqual(payload["status"], "deactivated")
        self.assertIsNone(payload["active_project_root"])
        self.assertIsNone(state.current_requirements_session(context_id))

    def test_service_state_rejects_unknown_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = ServiceState(Path(tmp))

            with self.assertRaisesRegex(StateError, "unknown browser context"):
                state.project_payload("missing")

    def test_browse_directories_lists_child_directories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "alpha").mkdir()
            (root / "file.txt").write_text("ignored\n", encoding="utf-8")

            payload = browse_directories(root)

        self.assertEqual(payload["path"], str(root.resolve()))
        self.assertIn(
            {"name": "alpha", "path": str((root / "alpha").resolve())},
            payload["entries"],
        )

    def test_agent_session_streams_output_and_accepts_messages(self) -> None:
        script = (
            "import sys\n"
            "print('ready', flush=True)\n"
            "line = sys.stdin.readline()\n"
            "print('got:' + line.strip(), flush=True)\n"
        )
        session = AgentSession([sys.executable, "-c", script], ROOT)
        try:
            try:
                session.start()
            except PermissionError as error:
                self.skipTest(f"pseudo-terminal creation is not permitted: {error}")
            self.assertIn("ready", wait_for_output(self, session, "ready"))

            session.send("hello agent")

            output = wait_for_output(self, session, "got:hello agent")
            self.assertIn("got:hello agent", output)
            wait_for_exit(self, session)
            self.assertFalse(session.is_active())
        finally:
            if session.is_active() and session.process is not None:
                session.process.terminate()

    def test_agent_session_submits_raw_terminal_input(self) -> None:
        script = (
            "import sys\n"
            "import termios\n"
            "import tty\n"
            "print('ready', flush=True)\n"
            "fd = sys.stdin.fileno()\n"
            "old = termios.tcgetattr(fd)\n"
            "chars = []\n"
            "try:\n"
            "    tty.setraw(fd)\n"
            "    while True:\n"
            "        ch = sys.stdin.read(1)\n"
            "        if ch in {'\\r', '\\n'}:\n"
            "            break\n"
            "        chars.append(ch)\n"
            "finally:\n"
            "    termios.tcsetattr(fd, termios.TCSANOW, old)\n"
            "print('raw:' + ''.join(chars), flush=True)\n"
            "print('submit:' + repr(ch), flush=True)\n"
        )
        session = AgentSession([sys.executable, "-c", script], ROOT)
        try:
            try:
                session.start()
            except PermissionError as error:
                self.skipTest(f"pseudo-terminal creation is not permitted: {error}")
            self.assertIn("ready", wait_for_output(self, session, "ready"))

            session.send("hello agent")

            self.assertIn("raw:hello agent", wait_for_output(self, session, "raw:"))
            self.assertIn("submit:'\\r'", wait_for_output(self, session, "submit:"))
            wait_for_exit(self, session)
            self.assertFalse(session.is_active())
        finally:
            if session.is_active() and session.process is not None:
                session.process.terminate()

    def test_agent_session_interrupts_running_process(self) -> None:
        script = (
            "import os\n"
            "import sys\n"
            "import termios\n"
            "import tty\n"
            "print('ready', flush=True)\n"
            "fd = sys.stdin.fileno()\n"
            "old = termios.tcgetattr(fd)\n"
            "try:\n"
            "    tty.setraw(fd)\n"
            "    key = sys.stdin.read(1)\n"
            "finally:\n"
            "    termios.tcsetattr(fd, termios.TCSANOW, old)\n"
            "if key == '\\x1b':\n"
            "    print('interrupted', flush=True)\n"
            "    os._exit(0)\n"
            "os._exit(1)\n"
        )
        session = AgentSession([sys.executable, "-c", script], ROOT)
        try:
            try:
                session.start()
            except PermissionError as error:
                self.skipTest(f"pseudo-terminal creation is not permitted: {error}")
            self.assertIn("ready", wait_for_output(self, session, "ready"))

            session.interrupt()

            self.assertIn(
                "interrupted",
                wait_for_output(self, session, "interrupted"),
            )
            wait_for_exit(self, session)
            self.assertFalse(session.is_active())
        finally:
            if session.is_active() and session.process is not None:
                session.process.terminate()

    def test_agent_session_terminate_stops_running_process(self) -> None:
        script = (
            "import time\n"
            "print('ready', flush=True)\n"
            "time.sleep(30)\n"
        )
        session = AgentSession([sys.executable, "-c", script], ROOT)
        try:
            try:
                session.start()
            except PermissionError as error:
                self.skipTest(f"pseudo-terminal creation is not permitted: {error}")
            self.assertIn("ready", wait_for_output(self, session, "ready"))

            session.terminate()

            self.assertFalse(session.is_active())
            self.assertIsNotNone(session.returncode)
            self.assertNotEqual(session.returncode, 0)
        finally:
            if session.is_active():
                session.terminate()

    def test_agent_session_preserves_raw_terminal_output(self) -> None:
        script = (
            "import sys\n"
            "sys.stdout.write('\\x1b[31mred\\x1b[0m\\n')\n"
            "sys.stdout.flush()\n"
        )
        session = AgentSession([sys.executable, "-c", script], ROOT)
        try:
            try:
                session.start()
            except PermissionError as error:
                self.skipTest(f"pseudo-terminal creation is not permitted: {error}")
            self.assertIn("red", wait_for_output(self, session, "red"))
            wait_for_exit(self, session)
        finally:
            if session.is_active() and session.process is not None:
                session.process.terminate()

        output_events = [
            event for event in session.events_after(0)
            if event.get("type") == "output"
        ]
        self.assertTrue(output_events)
        terminal_output = "".join(
            str(event.get("terminal", "")) for event in output_events
        )
        text_output = "".join(str(event.get("text", "")) for event in output_events)
        self.assertIn("\x1b[31m", terminal_output)
        self.assertNotIn("\x1b[31m", text_output)

    def test_agent_process_env_prepends_absolute_module_path(self) -> None:
        original_pythonpath = os.environ.get("PYTHONPATH")
        os.environ["PYTHONPATH"] = "src"
        try:
            env = _agent_process_env()
        finally:
            if original_pythonpath is None:
                os.environ.pop("PYTHONPATH", None)
            else:
                os.environ["PYTHONPATH"] = original_pythonpath

        entries = env["PYTHONPATH"].split(os.pathsep)
        self.assertEqual(entries[0], str((ROOT / "src").resolve()))
        self.assertIn("src", entries)
        self.assertEqual(env["TERM"], "xterm-256color")
        self.assertEqual(env["COLORTERM"], "truecolor")
        self.assertNotIn("NO_COLOR", env)
        self.assertNotIn("CLICOLOR", env)
        self.assertNotIn("FORCE_COLOR", env)

    def test_terminal_output_cleaner_strips_ansi_screen_updates(self) -> None:
        raw = (
            "7 \x1b[1B\x1b[1G\x1b[K\x1b[1B\x1b[1G\x1b[K"
            " 8 \x1b[39;49m\x1b[K   \x1b[38;5;6;49mq"
            "\x1b[39m\x1b[49m\x1b[0m\n"
            "\x1b[39;49m\x1b[K \x1b[39m\x1b[49m\x1b[0m\n"
            "\x1b[?25l\x1b[?2026l\x1b]0;QFw\x1b\\\x1b[?2026h"
        )

        cleaned, pending = _clean_terminal_output(raw)

        self.assertEqual(pending, "")
        self.assertNotIn("\x1b", cleaned)
        self.assertIn("q", cleaned)
        self.assertNotIn("[1B", cleaned)
        self.assertNotIn("[39;49m", cleaned)
        self.assertNotIn("]0;QFw", cleaned)

    def test_terminal_output_cleaner_buffers_split_escape_sequences(self) -> None:
        cleaned, pending = _clean_terminal_output("plain \x1b[38;")
        self.assertEqual(cleaned, "plain ")
        self.assertEqual(pending, "\x1b[38;")

        cleaned, pending = _clean_terminal_output("5;6mgreen\x1b[0m", pending)

        self.assertEqual(cleaned, "green")
        self.assertEqual(pending, "")

    def test_terminal_output_cleaner_normalizes_carriage_returns(self) -> None:
        cleaned, pending = _clean_terminal_output("first\rsecond\r\nthird\b")

        self.assertEqual(pending, "")
        self.assertEqual(cleaned, "first\nsecond\nthir")

    def test_terminal_input_uses_enter_key_for_single_line_submit(self) -> None:
        self.assertEqual(_terminal_input_for_message("hello"), "hello\r")
        self.assertEqual(_terminal_input_chunks_for_message("hello"), ["hello", "\r"])

    def test_terminal_input_uses_bracketed_paste_for_multiline_submit(self) -> None:
        self.assertEqual(
            _terminal_input_for_message("line one\nline two\n"),
            "\x1b[200~line one\nline two\x1b[201~\r",
        )
        self.assertEqual(
            _terminal_input_chunks_for_message("line one\nline two\n"),
            ["\x1b[200~line one\nline two\x1b[201~", "\r"],
        )

    def test_requirements_command_sources_project_activation_when_available(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            activate = root / ".electroboy" / "bin" / "activate"
            activate.parent.mkdir(parents=True)
            activate.write_text("export ELECTROBOY_PROJECT_ROOT=x\n", encoding="utf-8")

            command = _requirements_command(root)

        self.assertEqual(command[:2], ["/bin/sh", "-c"])
        self.assertIn(". ", command[2])
        self.assertIn("electroboy requirements", command[2])

    def test_serve_accepts_subcommand_root_argument(self) -> None:
        parser = build_parser()

        args = parser.parse_args(["serve", "--root", "/tmp/example", "--port", "0"])

        self.assertEqual(args.command, "serve")
        self.assertEqual(args.root, "/tmp/example")
        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 0)


def request(
    server: object,
    path: str,
) -> tuple[int, str, str]:
    host, port = server.server_address[:2]
    connection = http.client.HTTPConnection(host, port, timeout=2)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read().decode("utf-8")
        content_type = response.getheader("Content-Type", "")
    finally:
        connection.close()
    return response.status, body, content_type


def wait_for_output(
    test_case: unittest.TestCase,
    session: AgentSession,
    expected: str,
    timeout: float = 3,
) -> str:
    deadline = time.time() + timeout
    while time.time() < deadline:
        output = "".join(
            str(event.get("text", ""))
            for event in session.events_after(0)
            if event.get("type") == "output"
        )
        if expected in output:
            return output
        time.sleep(0.05)
    test_case.fail(f"timed out waiting for {expected!r}")


def wait_for_exit(
    test_case: unittest.TestCase,
    session: AgentSession,
    timeout: float = 3,
) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not session.is_active():
            return
        time.sleep(0.05)
    test_case.fail("timed out waiting for agent session to exit")


if __name__ == "__main__":
    unittest.main()
