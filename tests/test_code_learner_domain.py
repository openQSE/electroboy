from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.workflows.code_learner.domain import (  # noqa: E402
    CodeLearnerError,
    CodeLearnerStore,
    SourceAdapter,
    analyze_repository,
    build_learner_context,
    create_walkthrough,
    learner_prompt,
    resolve_symbol,
)


class CodeLearnerDomainTests(unittest.TestCase):
    def test_source_adapter_rejects_paths_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            adapter = SourceAdapter(root)

            with self.assertRaisesRegex(CodeLearnerError, "escapes"):
                adapter.resolve("../outside.py")

    def test_repository_analysis_discovers_modules_and_python_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            package = root / "src" / "sample" / "app"
            package.mkdir(parents=True)
            (root / "README.md").write_text("# Sample\n", encoding="utf-8")
            (package / "__init__.py").write_text("", encoding="utf-8")
            (package / "main.py").write_text(
                "\n".join(
                    [
                        "def helper(value):",
                        "    return str(value)",
                        "",
                        "class Runner:",
                        "    def run(self, value):",
                        "        return helper(value)",
                    ]
                ),
                encoding="utf-8",
            )

            analysis = analyze_repository(root)

        self.assertIn("markdown", analysis.language_counts)
        self.assertTrue(
            any(module["path"] == "src/sample/app" for module in analysis.modules)
        )
        qualified = {symbol.qualified_name for symbol in analysis.symbols}
        self.assertIn("helper", qualified)
        self.assertIn("Runner.run", qualified)

    def test_create_walkthroughs_for_architecture_module_and_function(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._sample_repo(Path(tmp))

            architecture = create_walkthrough(root, learning_mode="Architecture")
            module = create_walkthrough(
                root,
                learning_mode="Module",
                target="src/sample",
            )
            function = create_walkthrough(
                root,
                learning_mode="Function",
                target="orchestrate",
            )

        self.assertEqual(architecture.learning_mode, "architecture")
        self.assertGreaterEqual(len(architecture.steps), 3)
        self.assertEqual(module.learning_mode, "module")
        self.assertEqual(module.mode_target, "src/sample")
        self.assertEqual(function.learning_mode, "function")
        self.assertEqual(function.mode_target, "orchestrate")
        self.assertTrue(
            any(step.title == "Call Tree" for step in function.steps),
        )

    def test_function_resolution_reports_ambiguous_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            first = root / "first"
            second = root / "second"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (first / "service.py").write_text(
                "def build():\n    return 1\n",
                encoding="utf-8",
            )
            (second / "service.py").write_text(
                "def build():\n    return 2\n",
                encoding="utf-8",
            )

            analysis = analyze_repository(root)
            resolution = resolve_symbol(analysis, "build")

        self.assertEqual(resolution.status, "ambiguous")
        self.assertEqual(len(resolution.candidates), 2)

    def test_learner_context_prefers_selected_source_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._sample_repo(Path(tmp))
            walkthrough = create_walkthrough(
                root,
                learning_mode="Function",
                target="orchestrate",
            )

            context = build_learner_context(
                root,
                walkthrough,
                selected_start_line=2,
                selected_end_line=3,
            )
            prompt = learner_prompt("Why this branch?", context)

        self.assertTrue(context["selection_active"])
        self.assertEqual(context["start_line"], 2)
        self.assertIn("src/sample/main.py:2-3", prompt)
        self.assertIn("Why this branch?", prompt)

    def test_store_persists_walkthrough_and_question_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._sample_repo(Path(tmp))
            walkthrough = create_walkthrough(root, learning_mode="Architecture")
            store = CodeLearnerStore(root)

            store.save_walkthrough(walkthrough)
            restored = CodeLearnerStore(root).current()
            self.assertIsNotNone(restored)
            assert restored is not None
            context = build_learner_context(root, restored)
            store.record_question(restored.id, "What am I looking at?", context)
            payload = json.loads(store.path.read_text(encoding="utf-8"))

        self.assertEqual(payload["current_walkthrough_id"], walkthrough.id)
        self.assertEqual(
            payload["walkthroughs"][0]["qa_history"][0]["question"],
            "What am I looking at?",
        )

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
