from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ai_pipeline.artifacts import ArtifactManager  # noqa: E402
from ai_pipeline.state_store import StateStore  # noqa: E402


class ArtifactTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
