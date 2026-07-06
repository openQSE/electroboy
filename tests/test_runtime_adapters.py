from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.adapters.base import AgentInvocation  # noqa: E402
from electroboy.config import RuntimeConfig  # noqa: E402
from electroboy.adapters.codex_exec import CodexExecRuntime  # noqa: E402
from electroboy.adapters.generic_cli import GenericCliRuntime  # noqa: E402


class RuntimeAdapterTests(unittest.TestCase):
    def test_generic_cli_parses_json_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime = GenericCliRuntime(
                RuntimeConfig(
                    name="test",
                    adapter="generic_cli",
                    command=sys.executable,
                    args=[
                        "-c",
                        "import json; print(json.dumps({'final_message': 'ok'}))",
                    ],
                ),
                tmp,
            )

            result = runtime.invoke(AgentInvocation(role="review", prompt="prompt"))

        self.assertTrue(result.ok)
        self.assertEqual(result.final_message, "ok")

    def test_codex_exec_parses_jsonl_final_message(self) -> None:
        runtime = CodexExecRuntime(
            RuntimeConfig(
                name="codex",
                adapter="codex_exec",
                command="codex",
                args=["exec", "--json"],
            )
        )

        result = runtime._parse_stdout('{"type": "turn.completed", "message": "done"}\n')

        self.assertTrue(result.ok)
        self.assertEqual(result.final_message, "done")
        self.assertEqual(result.raw_events[0]["type"], "turn.completed")

    def test_generic_cli_runtime_errors_return_agent_result(self) -> None:
        runtime = GenericCliRuntime(
            RuntimeConfig(
                name="missing",
                adapter="generic_cli",
                command="missing-agent-cli",
            )
        )

        result = runtime.invoke(AgentInvocation(role="review", prompt="prompt"))

        self.assertFalse(result.ok)
        self.assertIsNotNone(result.error)

    def test_codex_exec_adds_role_sandbox(self) -> None:
        runtime = CodexExecRuntime(
            RuntimeConfig(
                name="codex",
                adapter="codex_exec",
                command="codex",
                args=["exec", "--json"],
            )
        )

        review = runtime._command(AgentInvocation(role="code_review", prompt="p"))
        coding = runtime._command(AgentInvocation(role="coding", prompt="p"))

        self.assertEqual(review[-2:], ["--sandbox", "read-only"])
        self.assertEqual(coding[-2:], ["--sandbox", "workspace-write"])

    def test_codex_exec_extracts_structured_issues(self) -> None:
        runtime = CodexExecRuntime(
            RuntimeConfig(
                name="codex",
                adapter="codex_exec",
                command="codex",
                args=["exec", "--json"],
            )
        )

        result = runtime._parse_stdout(
            '{"message": "done", "issues": [{"issue_id": "CR-1"}]}\n'
        )

        self.assertEqual(result.issues[0]["issue_id"], "CR-1")

    def test_codex_exec_honors_structured_failure(self) -> None:
        runtime = CodexExecRuntime(
            RuntimeConfig(
                name="codex",
                adapter="codex_exec",
                command="codex",
                args=["exec", "--json"],
            )
        )

        result = runtime._parse_stdout(
            '{"message": "{\\"ok\\": false, \\"final_message\\": '
            '\\"blocked\\", \\"error\\": \\"review failed\\"}"}\n'
        )

        self.assertFalse(result.ok)
        self.assertEqual(result.final_message, "blocked")
        self.assertEqual(result.error, "review failed")

    def test_generic_cli_uses_configured_environment_allowlist(self) -> None:
        os.environ["ELECTROBOY_ALLOWED_TEST"] = "allowed"
        os.environ["ELECTROBOY_BLOCKED_TEST"] = "blocked"
        with tempfile.TemporaryDirectory() as tmp:
            runtime = GenericCliRuntime(
                RuntimeConfig(
                    name="test",
                    adapter="generic_cli",
                    command=sys.executable,
                    args=[
                        "-c",
                        "import os; print(os.getenv('ELECTROBOY_ALLOWED_TEST', '')"
                        " + ':' + os.getenv('ELECTROBOY_BLOCKED_TEST', ''))",
                    ],
                    env=["PATH", "ELECTROBOY_ALLOWED_TEST"],
                ),
                tmp,
            )

            result = runtime.invoke(AgentInvocation(role="review", prompt="prompt"))

        self.assertTrue(result.ok)
        self.assertEqual(result.final_message.strip(), "allowed:")


if __name__ == "__main__":
    unittest.main()
