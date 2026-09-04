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
    analysis_from_course_corpus,
    build_learner_context,
    create_walkthrough,
    learner_prompt,
    parse_course_corpus_jsonl,
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
            CodeLearnerStore(root).save_corpus_jsonl(self._sample_course_jsonl())

            architecture = create_walkthrough(root, learning_mode="Architecture")
            module = create_walkthrough(
                root,
                learning_mode="Module",
                target="module.sample",
            )
            function = create_walkthrough(
                root,
                learning_mode="Function",
                target="orchestrate",
            )

        self.assertEqual(architecture.learning_mode, "architecture")
        self.assertGreaterEqual(len(architecture.steps), 3)
        self.assertEqual(module.learning_mode, "module")
        self.assertEqual(module.mode_target, "module.sample")
        self.assertEqual(function.learning_mode, "function")
        self.assertEqual(function.mode_target, "orchestrate")
        self.assertTrue(
            any(step.title == "Call Tree" for step in function.steps),
        )
        self.assertIn("AI explains the architecture", architecture.steps[0].explanation)

    def test_course_corpus_jsonl_drives_ai_inferred_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self._sample_repo(Path(tmp))
            records = parse_course_corpus_jsonl(self._sample_course_jsonl())

            analysis = analysis_from_course_corpus(root, records)

        self.assertTrue(
            any(module["path"] == "module.sample" for module in analysis.modules)
        )
        self.assertEqual(analysis.symbols[0].qualified_name, "orchestrate")
        self.assertIn("python", analysis.language_counts)

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
            CodeLearnerStore(root).save_corpus_jsonl(self._sample_course_jsonl())
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
            CodeLearnerStore(root).save_corpus_jsonl(self._sample_course_jsonl())
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

    def _sample_course_jsonl(self) -> str:
        records = [
            {
                "record_type": "course_manifest",
                "schema_version": 1,
                "repository_name": "Sample",
                "repository_purpose": "Demonstrate orchestration.",
                "primary_languages": ["python", "markdown", "toml"],
                "architecture_step_ids": [
                    "architecture.purpose",
                    "architecture.runtime",
                    "architecture.api",
                ],
                "module_ids": ["module.sample"],
                "function_index_count": 1,
                "confidence": 0.9,
            },
            {
                "record_type": "architecture_step",
                "id": "architecture.purpose",
                "title": "Project Purpose",
                "summary": "AI explains the architecture from the README.",
                "body": "The sample project exists to demonstrate a helper-backed flow.",
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
                "record_type": "architecture_step",
                "id": "architecture.runtime",
                "title": "Runtime Flow",
                "summary": "The orchestrate function owns the visible runtime flow.",
                "body": "It delegates conversion to helper and applies output formatting.",
                "source_refs": [
                    {
                        "path": "src/sample/main.py",
                        "start_line": 4,
                        "end_line": 6,
                        "symbol": "orchestrate",
                        "reason": "Runtime flow.",
                    }
                ],
                "related_module_ids": ["module.sample"],
                "confidence": 0.88,
            },
            {
                "record_type": "architecture_step",
                "id": "architecture.api",
                "title": "Public API",
                "summary": "The package exposes a small Python surface.",
                "body": "The tutorial should begin with orchestrate and then trace helper.",
                "source_refs": [
                    {
                        "path": "src/sample/main.py",
                        "start_line": 1,
                        "end_line": 6,
                        "reason": "Public callable surface.",
                    }
                ],
                "related_module_ids": ["module.sample"],
                "confidence": 0.86,
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
                "summary": "This module keeps the orchestration path compact.",
                "body": "The main file contains both helper and orchestrator.",
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
                "summary": "AI explains why orchestrate is the main flow.",
                "body": "It receives a value, converts it through helper, and uppercases it.",
                "call_flow": "Call Tree: orchestrate calls helper before upper.",
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
