from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.cli import main  # noqa: E402
from electroboy.state_store import StateStore  # noqa: E402


class MetaProjectTests(unittest.TestCase):
    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_meta_init_creates_empty_registry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = Path(tmp) / "openQSE"

            code, stdout, stderr = self.run_cli(["meta", "init", str(meta)])
            registry = json.loads(
                (meta / ".electroboy" / "shared" / "repositories.json").read_text(
                    encoding="utf-8"
                )
            )
            activate_exists = (meta / ".electroboy" / "bin" / "activate").exists()
            wrapper_exists = (meta / ".electroboy" / "bin" / "electroboy").exists()
            runtime_exists = (
                meta / ".electroboy" / "local" / "runtime" / "src" / "electroboy"
            ).exists()
            requirements_exists = (meta / "docs" / "requirements.md").exists()
            current_run_exists = (
                meta / ".electroboy" / "shared" / "current-run"
            ).exists()

        self.assertEqual(code, 0, stderr)
        self.assertIn("initialized: yes", stdout)
        self.assertIn(
            f"activate: source {meta / '.electroboy' / 'bin' / 'activate'}",
            stdout,
        )
        self.assertEqual(registry["active"], None)
        self.assertEqual(registry["repositories"], [])
        self.assertTrue(activate_exists)
        self.assertTrue(wrapper_exists)
        self.assertTrue(runtime_exists)
        self.assertFalse(requirements_exists)
        self.assertFalse(current_run_exists)

    def test_meta_activation_sets_meta_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = Path(tmp) / "openQSE"
            self.assertEqual(self.run_cli(["meta", "init", str(meta)])[0], 0)
            env = os.environ.copy()
            env["ACTIVATE"] = str(meta / ".electroboy" / "bin" / "activate")

            completed = subprocess.run(
                [
                    "bash",
                    "--noprofile",
                    "--norc",
                    "-c",
                    (
                        'PS1="#> "\n'
                        '. "$ACTIVATE" >/dev/null\n'
                        'printf "root=%s\\n" "$ELECTROBOY_PROJECT_ROOT"\n'
                        'printf "prompt=%s\\n" "$PS1"\n'
                        'electroboy deactivate >/dev/null\n'
                        'printf "restored=%s\\n" "$PS1"\n'
                    ),
                ],
                cwd=meta,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.splitlines(),
            [
                f"root={meta}",
                "prompt=(openQSE) #> ",
                "restored=#> ",
            ],
        )

    def test_add_requires_initialized_meta_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = Path(tmp) / "openQSE"
            repo = meta / "QFw"
            repo.mkdir(parents=True)

            code, _stdout, stderr = self.run_cli(
                ["--root", str(meta), "add", "QFw"]
            )

        self.assertEqual(code, 2)
        self.assertIn("meta-project is not initialized", stderr)

    def test_start_requires_initialized_meta_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = Path(tmp) / "openQSE"
            repo = meta / "QFw"
            repo.mkdir(parents=True)

            code, _stdout, stderr = self.run_cli(
                ["--root", str(meta), "start", "QFw"]
            )

        self.assertEqual(code, 2)
        self.assertIn("meta-project is not initialized", stderr)

    def test_add_registers_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = Path(tmp) / "openQSE"
            repo = meta / "QFw"
            repo.mkdir(parents=True)
            self.assertEqual(self.run_cli(["meta", "init", str(meta)])[0], 0)

            code, stdout, stderr = self.run_cli(
                ["--root", str(meta), "add", "QFw"]
            )
            registry = json.loads(
                (meta / ".electroboy" / "shared" / "repositories.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("registered repo: QFw", stdout)
        self.assertIn("active repo: none", stdout)
        self.assertIsNone(registry["active"])
        self.assertEqual(registry["repositories"][0]["name"], "QFw")
        self.assertEqual(registry["repositories"][0]["path"], str(repo))

    def test_project_command_requires_active_meta_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = Path(tmp) / "openQSE"
            repo = meta / "QFw"
            repo.mkdir(parents=True)
            self.assertEqual(self.run_cli(["meta", "init", str(meta)])[0], 0)
            self.assertEqual(self.run_cli(["--root", str(meta), "add", "QFw"])[0], 0)

            code, _stdout, stderr = self.run_cli(
                ["--root", str(meta), "requirements"]
            )

        self.assertEqual(code, 2)
        self.assertIn("no active target repo", stderr)

    def test_project_command_requires_activated_meta_shell(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = Path(tmp) / "openQSE"
            repo = meta / "QFw"
            repo.mkdir(parents=True)
            self.assertEqual(self.run_cli(["meta", "init", str(meta)])[0], 0)
            self.assertEqual(self.run_cli(["--root", str(meta), "start", "QFw"])[0], 0)

            previous_cwd = Path.cwd()
            previous_project_root = os.environ.pop("ELECTROBOY_PROJECT_ROOT", None)
            previous_legacy_root = os.environ.pop("AI_PIPELINE_PROJECT_ROOT", None)
            try:
                os.chdir(meta)
                code, _stdout, stderr = self.run_cli(["requirements"])
            finally:
                os.chdir(previous_cwd)
                if previous_project_root is not None:
                    os.environ["ELECTROBOY_PROJECT_ROOT"] = previous_project_root
                if previous_legacy_root is not None:
                    os.environ["AI_PIPELINE_PROJECT_ROOT"] = previous_legacy_root

        self.assertEqual(code, 2)
        self.assertIn("no active ElectroBoy shell", stderr)

    def test_add_registers_multiple_repositories(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = Path(tmp) / "openQSE"
            qfw = meta / "QFw"
            qhw = meta / "qhw-characterization"
            qfw.mkdir(parents=True)
            qhw.mkdir()
            self.assertEqual(self.run_cli(["meta", "init", str(meta)])[0], 0)

            code, stdout, stderr = self.run_cli(
                ["--root", str(meta), "add", "QFw", "qhw-characterization"]
            )
            registry = json.loads(
                (meta / ".electroboy" / "shared" / "repositories.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("registered repo: QFw", stdout)
        self.assertIn("registered repo: qhw-characterization", stdout)
        self.assertIn("active repo: none", stdout)
        self.assertIsNone(registry["active"])
        self.assertEqual(
            [record["name"] for record in registry["repositories"]],
            ["QFw", "qhw-characterization"],
        )
        self.assertEqual(
            [record["path"] for record in registry["repositories"]],
            [str(qfw), str(qhw)],
        )

    def test_start_switches_active_target_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = Path(tmp) / "openQSE"
            qfw = meta / "QFw"
            qhw = meta / "qhw-characterization"
            qfw.mkdir(parents=True)
            qhw.mkdir()
            self.assertEqual(self.run_cli(["meta", "init", str(meta)])[0], 0)

            first, first_stdout, first_stderr = self.run_cli(
                ["--root", str(meta), "start", "QFw"]
            )
            second, second_stdout, second_stderr = self.run_cli(
                ["--root", str(meta), "start", "qhw-characterization"]
            )
            status, status_stdout, status_stderr = self.run_cli(
                ["--root", str(meta), "status"]
            )
            registry = json.loads(
                (meta / ".electroboy" / "shared" / "repositories.json").read_text(
                    encoding="utf-8"
                )
            )
            qfw_requirements_exists = (qfw / "docs" / "requirements.md").exists()
            qhw_requirements_exists = (qhw / "docs" / "requirements.md").exists()

        self.assertEqual(first, 0, first_stderr)
        self.assertEqual(second, 0, second_stderr)
        self.assertEqual(status, 0, status_stderr)
        self.assertIn("active repo: QFw", first_stdout)
        self.assertIn("active repo: qhw-characterization", second_stdout)
        self.assertIn("active repo: qhw-characterization", status_stdout)
        self.assertIn("registered repos:", status_stdout)
        self.assertEqual(registry["active"], "qhw-characterization")
        self.assertTrue(qfw_requirements_exists)
        self.assertTrue(qhw_requirements_exists)

    def test_stage_command_uses_active_target_from_meta_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            meta = Path(tmp) / "openQSE"
            qfw = meta / "QFw"
            qfw.mkdir(parents=True)
            write_file(meta / "agent-response.md", "accepted\n")
            self.assertEqual(self.run_cli(["meta", "init", str(meta)])[0], 0)
            self.assertEqual(
                self.run_cli(["--root", str(meta), "start", "QFw"])[0],
                0,
            )
            write_manual_runtime(qfw)

            code, stdout, stderr = self.run_cli(
                ["--root", str(meta), "requirements"]
            )
            store = StateStore(qfw)
            prompt_files = sorted(
                (store.run_dir(store.current_run_id() or "") / "messages").glob(
                    "*-prompt.md"
                )
            )
            prompt = prompt_files[-1].read_text(encoding="utf-8")
            qfw_requirements_exists = (qfw / "docs" / "requirements.md").exists()
            meta_requirements_exists = (meta / "docs" / "requirements.md").exists()

        self.assertEqual(code, 0, stderr)
        self.assertIn("authoring stage: requirements", stdout)
        self.assertTrue(qfw_requirements_exists)
        self.assertFalse(meta_requirements_exists)
        self.assertIn("Meta-project context:", prompt)
        self.assertIn("Active target repository: QFw", prompt)
        self.assertIn("Target repository from working directory: QFw", prompt)
        self.assertIn("QFw/docs/requirements.md", prompt)


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_manual_runtime(root: Path) -> None:
    write_file(
        root / ".electroboy" / "project.toml",
        """
[runtime]
default = "manual"

[runtimes.manual]
adapter = "manual"
command = "manual"
response_file = "agent-response.md"

[roles]
design_author = "manual"
design_review = "manual"
coding = "manual"
code_review = "manual"
test_review = "manual"
documentation = "manual"
""".lstrip(),
    )


if __name__ == "__main__":
    unittest.main()
