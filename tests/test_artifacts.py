from __future__ import annotations

import sys
import tempfile
import unittest
import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.artifacts import ArtifactManager  # noqa: E402
from electroboy.cli import main  # noqa: E402
from electroboy.state_store import StateStore  # noqa: E402


class ArtifactTests(unittest.TestCase):
    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_init_templates_does_not_overwrite_existing_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirements = root / "docs" / "requirements.md"
            requirements.parent.mkdir()
            requirements.write_text("custom\n", encoding="utf-8")

            written = ArtifactManager(root).init_templates()

            self.assertNotIn("docs/requirements.md", written)
            self.assertEqual(requirements.read_text(encoding="utf-8"), "custom\n")
            self.assertTrue((root / "docs" / "api.md").exists())

    def test_snapshot_copies_artifact_and_records_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = StateStore(root)
            manifest = store.init_run(run_id="run-1")
            artifact = root / "docs" / "requirements.md"
            artifact.parent.mkdir()
            artifact.write_text("# Requirements\n", encoding="utf-8")

            snapshot = ArtifactManager(root).snapshot(
                manifest.run_id,
                "docs/requirements.md",
                "EVT-1",
            )

            self.assertEqual(snapshot.artifact_path, "docs/requirements.md")
            self.assertTrue((root / snapshot.snapshot_path).exists())
            self.assertEqual(len(snapshot.checksum), 64)

    def test_manual_snapshot_records_activity_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = StateStore(root)
            store.init_run(run_id="run-1")
            artifact = root / "docs" / "requirements.md"
            artifact.parent.mkdir()
            artifact.write_text("# Requirements\n", encoding="utf-8")

            code, _stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "artifacts",
                    "snapshot",
                    "docs/requirements.md",
                ]
            )
            activity = store.read_activity()

            self.assertEqual(code, 0, stderr)
            self.assertEqual(activity[-1]["action"], "artifact-snapshotted")

    def test_gate_evaluation_records_activity_event(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            store = StateStore(root)
            store.init_run(run_id="run-1")

            code, _stdout, _stderr = self.run_cli(
                ["--root", str(root), "gate", "requirements"]
            )
            activity = store.read_activity()

            self.assertEqual(code, 1)
            self.assertEqual(activity[-1]["action"], "gate-evaluated")


if __name__ == "__main__":
    unittest.main()
