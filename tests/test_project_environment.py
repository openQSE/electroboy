from __future__ import annotations

import io
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


class ProjectEnvironmentTests(unittest.TestCase):
    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_new_creates_project_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"

            code, stdout, stderr = self.run_cli(
                ["new", str(root), "--run-id", "run-1"]
            )

            self.assertEqual(code, 0, stderr)
            self.assertIn("active stage: requirements", stdout)
            self.assertTrue((root / ".git").exists())
            bin_dir = root / ".electroboy" / "bin"
            self.assertTrue((bin_dir / "activate").exists())
            self.assertTrue((bin_dir / "ai-pipeline").exists())
            self.assertTrue((bin_dir / "electroboy").exists())
            self.assertFalse((root / "bin" / "activate").exists())
            self.assertTrue(
                (
                    root
                    / ".electroboy"
                    / "local"
                    / "runtime"
                    / "src"
                    / "electroboy"
                ).exists()
            )
            self.assertTrue((root / ".electroboy" / "project.toml").exists())
            project_config = (root / ".electroboy" / "project.toml").read_text(
                encoding="utf-8"
            )
            self.assertEqual(project_config.count('"COLORTERM"'), 2)
            self.assertNotIn('timeout = "900"', project_config)
            self.assertTrue(
                (root / ".electroboy" / "shared" / "current-run").exists()
            )
            self.assertTrue((root / "docs" / "requirements.md").exists())
            gitignore = (root / ".gitignore").read_text(encoding="utf-8")
            self.assertIn(".electroboy/local/", gitignore)
            self.assertIn(".electroboy/shared/runs/*/progress/", gitignore)

    def test_new_updates_existing_project_config_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            write_file(
                root / ".electroboy" / "project.toml",
                """
[runtime]
default = "codex"

[runtimes.codex]
adapter = "codex_exec"
command = "codex"
args = ["exec", "--json"]
env = ["PATH", "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR", "CODEX_HOME", "OPENAI_API_KEY"]
structured_output = "json_schema"

[runtimes.codex-interactive]
adapter = "codex_interactive"
command = "codex"
env = ["PATH", "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR", "CODEX_HOME", "OPENAI_API_KEY"]

[roles]
design_author = "codex-interactive"
design_review = "codex"
""".lstrip(),
            )

            code, _stdout, stderr = self.run_cli(
                ["new", str(root), "--run-id", "run-1"]
            )
            project_config = (root / ".electroboy" / "project.toml").read_text(
                encoding="utf-8"
            )

        self.assertEqual(code, 0, stderr)
        self.assertNotIn('timeout = "900"', project_config)
        self.assertIn('design_author_update = "codex"', project_config)
        self.assertEqual(project_config.count('"COLORTERM"'), 2)

    def test_generated_wrapper_runs_without_pythonpath(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            self.assertEqual(self.run_cli(["new", str(root)])[0], 0)
            env = os.environ.copy()
            env.pop("PYTHONPATH", None)

            completed = subprocess.run(
                [str(root / ".electroboy" / "bin" / "electroboy"), "--help"],
                cwd=root,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            wrapper = (root / ".electroboy" / "bin" / "electroboy").read_text(
                encoding="utf-8"
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertIn("usage: electroboy", completed.stdout)
        self.assertNotIn(str(ROOT), wrapper)

    def test_activation_sets_and_restores_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "test-proj"
            self.assertEqual(self.run_cli(["new", str(root)])[0], 0)
            env = os.environ.copy()
            env["ACTIVATE"] = str(root / ".electroboy" / "bin" / "activate")

            completed = subprocess.run(
                [
                    "bash",
                    "--noprofile",
                    "--norc",
                    "-c",
                    (
                        'PS1="#> "\n'
                        '. "$ACTIVATE" >/dev/null\n'
                        'printf "active=%s\\n" "$PS1"\n'
                        'electroboy deactivate >/dev/null\n'
                        'printf "restored=%s\\n" "$PS1"\n'
                    ),
                ],
                cwd=root,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(
            completed.stdout.splitlines(),
            ["active=(test-proj) #> ", "restored=#> "],
        )

    def test_activation_registers_bash_completion(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "test-proj"
            self.assertEqual(self.run_cli(["new", str(root)])[0], 0)
            env = os.environ.copy()
            env["ACTIVATE"] = str(root / ".electroboy" / "bin" / "activate")

            completed = subprocess.run(
                [
                    "bash",
                    "--noprofile",
                    "--norc",
                    "-c",
                    (
                        'PS1="#> "\n'
                        '. "$ACTIVATE" >/dev/null\n'
                        "COMP_WORDS=(electroboy imple)\n"
                        "COMP_CWORD=1\n"
                        "__electroboy_complete\n"
                        'printf "%s\\n" "${COMPREPLY[@]}"\n'
                    ),
                ],
                cwd=root,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.splitlines(), ["implementation-plan"])

    def test_new_does_not_touch_existing_project_bin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            existing_bin = root / "bin"
            existing_bin.mkdir(parents=True)
            existing_activate = existing_bin / "activate"
            existing_activate.write_text("project-owned\n", encoding="utf-8")

            code, stdout, stderr = self.run_cli(
                ["new", str(root), "--run-id", "run-1"]
            )

            self.assertEqual(code, 0, stderr)
            self.assertIn(
                f"activate: source {root / '.electroboy' / 'bin' / 'activate'}",
                stdout,
            )
            self.assertEqual(
                existing_activate.read_text(encoding="utf-8"), "project-owned\n"
            )
            self.assertTrue((root / ".electroboy" / "bin" / "activate").exists())

    def test_new_reuses_existing_git_worktree(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            project = repo / "nested"
            repo.mkdir()
            subprocess.run(
                ["git", "-C", str(repo), "init"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            code, stdout, stderr = self.run_cli(
                ["new", str(project), "--run-id", "run-1"]
            )

            self.assertEqual(code, 0, stderr)
            self.assertIn("active stage: requirements", stdout)
            self.assertFalse((project / ".git").exists())
            self.assertTrue((repo / ".git").exists())

    def test_deactivate_records_activity_when_run_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            StateStore(root).init_run(run_id="run-1")

            code, stdout, stderr = self.run_cli(["--root", str(root), "deactivate"])

            self.assertEqual(code, 0, stderr)
            self.assertIn("pipeline project deactivated", stdout)


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
