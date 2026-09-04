from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.service.app import ServiceState  # noqa: E402
from electroboy.service.recent_projects import recent_project_entries  # noqa: E402
from electroboy.service.registry import (  # noqa: E402
    build_module_registry,
    build_workflow_registry,
)
from electroboy.service.routes import build_route_dispatcher  # noqa: E402
from electroboy.workflows.code_learner.controller import (  # noqa: E402
    CodeLearnerWorkflowController,
    code_learner_agent_command,
)
from electroboy.workflows.code_learner.plugin import (  # noqa: E402
    workflow as code_learner_workflow,
)


class CodeLearnerServiceTests(unittest.TestCase):
    def test_plugin_registers_routes_and_controller(self) -> None:
        modules = build_module_registry()
        workflows = build_workflow_registry(
            modules,
            (code_learner_workflow(),),
        )
        dispatcher = build_route_dispatcher(modules, workflows)

        workflow = workflows.get("code-learner")

        self.assertEqual(workflow.label, "Code Learner")
        self.assertEqual(workflow.controller_factory, CodeLearnerWorkflowController)
        self.assertEqual(workflow.project_kinds, ("code-learner",))
        self.assertIsNotNone(
            dispatcher.match("POST", "/api/code-learner/project/open")
        )
        self.assertIsNotNone(
            dispatcher.match("POST", "/api/code-learner/question")
        )

    def test_controller_opens_repo_and_prepares_walkthrough_question(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            source_root = self._sample_repo(Path(tmp))
            state = ServiceState(
                service_root,
                workflow_registry=build_workflow_registry(
                    build_module_registry(),
                    (code_learner_workflow(),),
                ),
            )
            context_id = str(
                state.create_context(workflow_id="code-learner")["context_id"]
            )
            controller = state.workflow_controller("code-learner")

            opened = controller.open_project(context_id, str(source_root))
            initialized = controller.initialize(context_id)
            modules = controller.modules(context_id)
            symbols = controller.symbols(context_id, "orchestrate")
            course = controller.create_walkthrough(
                context_id,
                learning_mode="Function",
                target="orchestrate",
            )
            step_id = str(course["walkthrough"]["steps"][1]["id"])
            selected = controller.set_current_step(
                context_id,
                str(course["walkthrough"]["id"]),
                step_id,
            )
            question = controller.prepare_question(
                context_id,
                "What calls does this function make?",
                str(course["walkthrough"]["id"]),
                selected_start_line=4,
                selected_end_line=6,
            )
            recent = recent_project_entries(service_root)

        self.assertEqual(opened["workflow_id"], "code-learner")
        self.assertEqual(opened["project_mode"], "code-learner")
        self.assertEqual(
            recent[0]["kind"],
            "code-learner",
        )
        self.assertIn("analysis", initialized["code_learner"])
        self.assertTrue(
            any(module["path"] == "src/sample" for module in modules["modules"])
        )
        self.assertEqual(symbols["resolution"]["status"], "resolved")
        self.assertEqual(selected["walkthrough"]["current_step_id"], step_id)
        self.assertIn("src/sample/main.py:4-6", question["prompt"])
        self.assertEqual(question["walkthrough"]["qa_history"][0]["step_id"], step_id)

    def test_start_agent_uses_code_learner_session_bucket(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service_root = Path(tmp) / "service"
            source_root = self._sample_repo(Path(tmp))
            state = ServiceState(
                service_root,
                workflow_registry=build_workflow_registry(
                    build_module_registry(),
                    (code_learner_workflow(),),
                ),
            )
            context_id = str(
                state.create_context(workflow_id="code-learner")["context_id"]
            )
            controller = state.workflow_controller("code-learner")
            controller.open_project(context_id, str(source_root))
            course = controller.create_walkthrough(
                context_id,
                learning_mode="Architecture",
            )

            with mock.patch(
                "electroboy.service.sessions.AgentSession.start",
                autospec=True,
            ) as start:
                session, started = controller.start_agent(
                    context_id,
                    str(course["walkthrough"]["id"]),
                )

            payload = state.project_payload(context_id)

        self.assertTrue(started)
        start.assert_called_once_with(session)
        self.assertEqual(session.kind, "code-learner")
        self.assertIn(session.session_id, payload["selected_session_id"])
        self.assertEqual(payload["sessions"][0]["kind"], "code-learner")

    def test_agent_command_is_read_only_tutor_prompt(self) -> None:
        command = code_learner_agent_command(
            Path("/repo"),
            {
                "walkthrough_id": "walkthrough-1",
                "learning_mode": "function",
                "mode_target": "build",
                "step_position": "1/3",
                "step_title": "Purpose",
                "file_path": "src/app.py",
                "start_line": 10,
                "end_line": 20,
            },
        )

        self.assertIn("read-only", command)
        self.assertIn("Code Learner tutor", command[-1])
        self.assertIn("src/app.py:10-20", command[-1])

    def _sample_repo(self, parent: Path) -> Path:
        root = parent / "repo"
        package = root / "src" / "sample"
        package.mkdir(parents=True)
        (root / "README.md").write_text("# Sample\n", encoding="utf-8")
        (root / "pyproject.toml").write_text(
            "[project]\nname = 'sample'\n",
            encoding="utf-8",
        )
        (package / "__init__.py").write_text("", encoding="utf-8")
        (package / "main.py").write_text(
            "\n".join(
                [
                    "def helper(value):",
                    "    return str(value)",
                    "",
                    "def orchestrate(value):",
                    "    text = helper(value)",
                    "    return text.upper()",
                ]
            ),
            encoding="utf-8",
        )
        return root


if __name__ == "__main__":
    unittest.main()
