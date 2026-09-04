from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.adapters.base import AgentResult  # noqa: E402
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
from electroboy.workflows.code_learner.planner import (  # noqa: E402
    code_learner_initialize_prompt,
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
            with mock.patch(
                "electroboy.workflows.code_learner.controller."
                "generate_code_learner_course_corpus_jsonl",
                return_value=self._sample_course_jsonl(),
            ) as planner:
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
        planner.assert_called_once_with(source_root)
        self.assertEqual(initialized["status"], "initialized")
        self.assertIn("analysis", initialized["code_learner"])
        self.assertIn("corpus", initialized["code_learner"])
        self.assertTrue(
            any(module["path"] == "module.sample" for module in modules["modules"])
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
            controller.initialize_from_jsonl(context_id, self._sample_course_jsonl())
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

    def test_initialize_prompt_requests_ai_inferred_jsonl_corpus(self) -> None:
        prompt = code_learner_initialize_prompt(Path("/repo"))

        self.assertIn("Return ONLY JSONL", prompt)
        self.assertIn('field name "record_type"', prompt)
        self.assertIn("precomputed module", prompt)
        self.assertIn("module boundaries must come from your understanding", prompt)
        self.assertIn('record_type: "module"', prompt)
        self.assertIn('record_type: "function_lesson"', prompt)

    def test_initialize_rejects_failed_ai_planner(self) -> None:
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

            with mock.patch(
                "electroboy.workflows.code_learner.planner.runtime_for_role"
            ) as runtime_for_role:
                runtime = mock.Mock()
                runtime.invoke.return_value = AgentResult(
                    ok=False,
                    final_message="",
                    error="planner failed",
                )
                runtime_for_role.return_value = runtime

                with self.assertRaisesRegex(Exception, "planner failed"):
                    controller.initialize(context_id)

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

    def _sample_course_jsonl(self) -> str:
        records = [
            {
                "record_type": "course_manifest",
                "schema_version": 1,
                "repository_name": "Sample",
                "repository_purpose": "Demonstrate orchestration.",
                "primary_languages": ["python"],
                "architecture_step_ids": ["architecture.purpose"],
                "module_ids": ["module.sample"],
                "function_index_count": 1,
                "confidence": 0.9,
            },
            {
                "record_type": "architecture_step",
                "id": "architecture.purpose",
                "title": "Project Purpose",
                "summary": "AI-generated architecture summary.",
                "body": "The repository exposes a helper-backed orchestration flow.",
                "source_refs": [
                    {
                        "path": "README.md",
                        "start_line": 1,
                        "end_line": 1,
                        "reason": "Project introduction.",
                    }
                ],
                "related_module_ids": ["module.sample"],
                "confidence": 0.9,
            },
            {
                "record_type": "module",
                "id": "module.sample",
                "name": "Sample Flow",
                "purpose": "Owns helper conversion and orchestration.",
                "responsibilities": ["convert values", "format outputs"],
                "primary_files": ["src/sample/main.py"],
                "public_interfaces": ["orchestrate"],
                "depends_on_module_ids": [],
                "used_by_module_ids": [],
                "source_refs": [
                    {
                        "path": "src/sample/main.py",
                        "start_line": 1,
                        "end_line": 6,
                        "reason": "Module implementation.",
                    }
                ],
                "confidence": 0.9,
            },
            {
                "record_type": "module_step",
                "module_id": "module.sample",
                "id": "module.sample.boundary",
                "title": "Boundary",
                "summary": "The module boundary centers on orchestration.",
                "body": "The file contains both helper and orchestrator behavior.",
                "source_refs": [
                    {
                        "path": "src/sample/main.py",
                        "start_line": 1,
                        "end_line": 6,
                        "reason": "Module boundary.",
                    }
                ],
                "related_function_symbols": ["helper", "orchestrate"],
                "confidence": 0.87,
            },
            {
                "record_type": "function_index_entry",
                "symbol": "orchestrate",
                "display_name": "orchestrate",
                "kind": "function",
                "module_id": "module.sample",
                "path": "src/sample/main.py",
                "start_line": 4,
                "end_line": 6,
                "purpose": "Coordinate helper output formatting.",
                "why_important": "It is the main behavior in the sample.",
                "known_callers": [],
                "known_callees": ["helper"],
                "source_refs": [
                    {
                        "path": "src/sample/main.py",
                        "start_line": 4,
                        "end_line": 6,
                        "symbol": "orchestrate",
                        "reason": "Function definition.",
                    }
                ],
                "confidence": 0.91,
            },
            {
                "record_type": "function_lesson",
                "symbol": "orchestrate",
                "display_name": "orchestrate",
                "title": "Purpose and Shape",
                "summary": "AI-generated function summary.",
                "body": "It converts the value with helper and uppercases the result.",
                "call_flow": "orchestrate calls helper, then upper.",
                "inputs": ["value"],
                "outputs": ["uppercase string"],
                "side_effects": [],
                "error_paths": [],
                "source_refs": [
                    {
                        "path": "src/sample/main.py",
                        "start_line": 4,
                        "end_line": 6,
                        "symbol": "orchestrate",
                        "reason": "Function implementation.",
                    }
                ],
                "related_symbols": ["helper"],
                "confidence": 0.9,
            },
        ]
        return "\n".join(json.dumps(record) for record in records)


if __name__ == "__main__":
    unittest.main()
