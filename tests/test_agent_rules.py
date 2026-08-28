from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.service.agent_rules import (  # noqa: E402
    PROJECT_AGENT_RULES_PATH,
    materialize_workflow_agent_rules,
    resolve_agent_rules,
)
from electroboy.service.registry import (  # noqa: E402
    AgentRuleDefinition,
    ServiceModule,
    build_module_registry,
    build_workflow_registry,
)


class AgentRulesTests(unittest.TestCase):
    def test_registry_rejects_empty_agent_rule_content(self) -> None:
        contribution = ServiceModule(
            id="sample",
            label="Sample",
            agent_rules=(AgentRuleDefinition("sample.empty", "Empty", "  "),),
        )

        with self.assertRaisesRegex(ValueError, "empty agent rule content"):
            build_module_registry((contribution,))

    def test_software_rules_compose_module_and_workflow_contributions(self) -> None:
        modules = build_module_registry()
        workflow = build_workflow_registry(modules).get("software")

        rules = resolve_agent_rules(modules, workflow)

        self.assertEqual(
            [rule.id for rule in rules],
            [
                "markdown-documents.naming",
                "structured-documents.source-of-truth",
                "software.structured-artifacts",
                "software.general-documents",
            ],
        )

    def test_materialized_rules_include_project_rules_and_remain_stable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_rules = root / PROJECT_AGENT_RULES_PATH
            project_rules.parent.mkdir(parents=True)
            project_rules.write_text(
                "Use `docs/decisions/` for decision records.\n",
                encoding="utf-8",
            )

            relative_path = materialize_workflow_agent_rules(root, "software")
            generated = root / relative_path
            first_timestamp = generated.stat().st_mtime_ns
            second_path = materialize_workflow_agent_rules(root, "software")
            second_timestamp = generated.stat().st_mtime_ns
            content = generated.read_text(encoding="utf-8")

        self.assertEqual(relative_path, second_path)
        self.assertEqual(first_timestamp, second_timestamp)
        self.assertIn("Structured Document Sources", content)
        self.assertIn("Software Workflow Artifacts", content)
        self.assertIn("docs/requirements.jsonl", content)
        self.assertIn("docs/recipes/<lowercase-kebab-case>.md", content)
        self.assertIn("Use `docs/decisions/` for decision records.", content)


if __name__ == "__main__":
    unittest.main()
