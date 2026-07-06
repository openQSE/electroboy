from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.adapters.base import AgentInvocation  # noqa: E402
from electroboy.config import load_pipeline_config, parse_pipeline_config  # noqa: E402
from electroboy.runtime import runtime_for_role  # noqa: E402


class RuntimeConfigTests(unittest.TestCase):
    def test_default_config_uses_interactive_codex_for_authoring(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config = load_pipeline_config(Path(tmp))

        self.assertEqual(
            config.runtime_for_role("design_author").adapter,
            "codex_interactive",
        )
        self.assertEqual(config.runtime_for_role("design_review").adapter, "codex_exec")

    def test_parse_runtime_config_selects_role_runtime(self) -> None:
        config = parse_pipeline_config(
            """
            [runtime]
            default = "manual"

            [runtimes.manual-review]
            adapter = "manual"
            command = "manual"
            env = ["PATH", "TOKEN"]
            response_file = "response.md"

            [roles]
            design_review = "manual-review"
            """
        )

        runtime = config.runtime_for_role("design_review")

        self.assertEqual(runtime.adapter, "manual")
        self.assertEqual(runtime.env, ["PATH", "TOKEN"])
        self.assertEqual(runtime.options["response_file"], "response.md")

    def test_manual_runtime_reads_configured_response_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "response.md").write_text("accepted\n", encoding="utf-8")
            (root / "electroboy.toml").write_text(
                """
                [runtime]
                default = "manual"

                [runtimes.manual]
                adapter = "manual"
                command = "manual"
                response_file = "response.md"
                """,
                encoding="utf-8",
            )

            runtime = runtime_for_role("design_review", root)
            result = runtime.invoke(
                AgentInvocation(role="design_review", prompt="review"),
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.final_message, "accepted\n")

    def test_project_config_path_supports_environment_section(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / ".electroboy"
            config_dir.mkdir()
            (config_dir / "project.toml").write_text(
                """
                [runtime]
                default = "manual"

                [runtimes.manual]
                adapter = "manual"
                command = "manual"

                [roles]
                design_author = "manual"

                [environment]
                activate_python = false
                python_activate = ".venv/bin/activate"
                """,
                encoding="utf-8",
            )

            config = load_pipeline_config(root)

        self.assertEqual(config.default_runtime, "manual")
        self.assertEqual(config.runtime_for_role("design_author").adapter, "manual")
        self.assertEqual(config.environment["activate_python"], "false")


if __name__ == "__main__":
    unittest.main()
