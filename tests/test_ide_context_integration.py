from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from electroboy.ide import IDEEditorContext, IDERuntimeMode
from electroboy.ide.service import IDEConfiguration, IDEService
from electroboy.service.app import ServiceState
from electroboy.workflows.software.agent_rules import SOFTWARE_AGENT_RULES


class IDEContextIntegrationTests(unittest.TestCase):
    def test_service_context_and_project_file_track_editor_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            project = root / "project"
            project.mkdir()
            state = ServiceState(root, state_root=root / "state")
            payload = state.create_context()
            context_id = str(payload["context_id"])
            with state.lock:
                state.contexts[context_id].reset_project(
                    workflow_id="software",
                    project_mode="project",
                    activation_root=project,
                    active_project_root=project,
                )
            editor = IDEEditorContext(
                workspace_id=context_id,
                path="src/main.py",
                language="python",
                cursor_line=7,
                cursor_column=3,
                dirty=True,
                revision=4,
            )

            state._record_ide_context(context_id, editor)

            context_file = project / ".electroboy/ide/editor-context.json"
            stored = json.loads(context_file.read_text())
            self.assertEqual(stored["path"], "src/main.py")
            self.assertEqual(stored["cursor"], {"line": 7, "column": 3})
            self.assertEqual(
                state.project_payload(context_id)["editor_context"]["revision"],
                4,
            )

            state._record_ide_context(context_id, None)
            self.assertFalse(context_file.exists())
            self.assertIsNone(state.project_payload(context_id)["editor_context"])
            state.ide_service.close()

    def test_context_updates_are_rate_limited_by_bridge_revision(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            events: list[tuple[str, IDEEditorContext | None]] = []
            service = IDEService(
                IDEConfiguration(
                    data_root=Path(temporary),
                    runtime_mode=IDERuntimeMode.DISABLED,
                ),
                context_callback=lambda workspace_id, context: events.append(
                    (workspace_id, context)
                ),
            )
            try:
                service._accept_context(
                    IDEEditorContext("workspace-1", path="one.py", revision=1)
                )
                service._accept_context(
                    IDEEditorContext("workspace-1", path="duplicate.py", revision=1)
                )
                service._accept_context(
                    IDEEditorContext("workspace-1", path="two.py", revision=2)
                )
            finally:
                service.close()

        self.assertEqual([item[1].path for item in events if item[1]], ["one.py", "two.py"])

    def test_software_agent_rules_reference_context_file_not_source(self) -> None:
        rule = next(
            item for item in SOFTWARE_AGENT_RULES if item.id == "software.editor-context"
        )

        self.assertIn(".electroboy/ide/editor-context.json", rule.content)
        self.assertIn("inspect the repository", rule.content)


if __name__ == "__main__":
    unittest.main()
