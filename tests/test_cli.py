from __future__ import annotations

import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from electroboy.cli import main  # noqa: E402
from electroboy.models import STAGE_IMPLEMENTATION  # noqa: E402
from electroboy.state_store import StateStore  # noqa: E402


class CliTests(unittest.TestCase):
    def run_cli(self, args: list[str]) -> tuple[int, str, str]:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_new_and_status(self) -> None:
        with temp_project() as root:
            self.assertEqual(self.run_cli(["new", str(root), "--run-id", "run-1"])[0], 0)

            code, stdout, stderr = self.run_cli(["--root", str(root), "status"])

        self.assertEqual(code, 0, stderr)
        self.assertIn("active stage: requirements", stdout)
        self.assertIn("next-stage: design", stdout)
        self.assertIn("completed gates:", stdout)

    def test_rejects_design_before_requirements(self) -> None:
        with temp_project() as root:
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            StateStore(root).init_run(run_id="run-1")

            code, _stdout, stderr = self.run_cli(
                ["--root", str(root), "design"]
            )

        self.assertEqual(code, 1)
        self.assertIn("active stage is requirements", stderr)

    def test_requirements_stage_advances_to_design(self) -> None:
        with temp_project() as root:
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            StateStore(root).init_run(run_id="run-1")
            write_manual_runtime(root)
            self.assertEqual(self.run_cli(["--root", str(root), "requirements"])[0], 0)

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "requirements-approve"]
            )
            status_code, status_stdout, status_stderr = self.run_cli(
                ["--root", str(root), "status"]
            )
            manifest = StateStore(root).load_current_manifest()

        self.assertEqual(code, 0, stderr)
        self.assertIn("active stage: design", stdout)
        self.assertEqual(status_code, 0, status_stderr)
        self.assertIn("active stage: design", status_stdout)
        self.assertIn("next-stage: design-review", status_stdout)
        self.assertTrue(manifest.has_gate("requirements"))

    def test_public_requirements_command_records_authoring(self) -> None:
        with temp_project() as root:
            StateStore(root).init_run(run_id="run-1")
            write_manual_runtime(root)

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "requirements"]
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("authoring stage: requirements", stdout)
        self.assertIn("artifact: docs/requirements.md", stdout)

    def test_requirements_authoring_prompt_limits_startup_scope(self) -> None:
        with temp_project() as root:
            store = StateStore(root)
            store.init_run(run_id="run-1")
            write_manual_runtime(root)

            code, _stdout, stderr = self.run_cli(["--root", str(root), "requirements"])
            prompt_files = list((store.run_dir("run-1") / "messages").glob("*-prompt.md"))
            prompt = prompt_files[0].read_text(encoding="utf-8")

        self.assertEqual(code, 0, stderr)
        self.assertIn("Target file: docs/requirements.md.", prompt)
        self.assertIn("Read only docs/requirements.md if it exists.", prompt)
        self.assertIn("Do not explore the working directory", prompt)
        self.assertIn("Update only docs/requirements.md", prompt)

    def test_requirements_authoring_records_local_session(self) -> None:
        with temp_project() as root:
            store = StateStore(root)
            store.init_run(run_id="run-1")
            write_manual_runtime(root)

            code, _stdout, stderr = self.run_cli(["--root", str(root), "requirements"])
            session_path = (
                root
                / ".electroboy"
                / "local"
                / "sessions"
                / "run-1"
                / "requirements"
                / "design_author.json"
            )
            session = json.loads(session_path.read_text(encoding="utf-8"))

        self.assertEqual(code, 0, stderr)
        self.assertEqual(session["stage"], "requirements")
        self.assertEqual(session["role"], "design_author")
        self.assertEqual(session["run_id"], "run-1")
        self.assertEqual(session["status"], "completed")
        self.assertEqual(session["artifact"], "docs/requirements.md")

    def test_requirements_authoring_uses_recovery_context_without_session_id(
        self,
    ) -> None:
        with temp_project() as root:
            store = StateStore(root)
            store.init_run(run_id="run-1")
            write_file(root / "docs" / "requirements.md", "# Requirements\n\nREQ-1\n")
            write_manual_runtime(root)
            self.assertEqual(self.run_cli(["--root", str(root), "requirements"])[0], 0)

            code, _stdout, stderr = self.run_cli(["--root", str(root), "requirements"])
            prompt_files = sorted(
                (store.run_dir("run-1") / "messages").glob("*-prompt.md")
            )
            prompt = prompt_files[-1].read_text(encoding="utf-8")

        self.assertEqual(code, 0, stderr)
        self.assertIn("Session recovery context:", prompt)
        self.assertIn("Previous local session record:", prompt)
        self.assertIn("Current docs/requirements.md:", prompt)
        self.assertIn("REQ-1", prompt)

    def test_requirements_approval_requires_design_author_event(self) -> None:
        with temp_project() as root:
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            StateStore(root).init_run(run_id="run-1")

            code, _stdout, stderr = self.run_cli(
                ["--root", str(root), "requirements-approve"]
            )

        self.assertEqual(code, 1)
        self.assertIn("agent confirmation is missing", stderr)

    def test_public_design_review_advances_to_design_acceptance(self) -> None:
        with temp_project() as root:
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            StateStore(root).init_run(run_id="run-1")
            write_manual_runtime(root)
            self.assertEqual(self.run_cli(["--root", str(root), "requirements"])[0], 0)
            self.assertEqual(
                self.run_cli(
                    [
                        "--root",
                        str(root),
                        "requirements-approve",
                    ]
                )[0],
                0,
            )

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "design-review"]
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("completed stage: design-review", stdout)
        self.assertIn("active stage: design-acceptance", stdout)

    def test_rejects_plan_before_design_acceptance(self) -> None:
        with temp_project() as root:
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            StateStore(root).init_run(run_id="run-1")
            write_manual_runtime(root)
            self.assertEqual(self.run_cli(["--root", str(root), "requirements"])[0], 0)
            self.assertEqual(
                self.run_cli(["--root", str(root), "requirements-approve"])[0],
                0,
            )

            code, _stdout, stderr = self.run_cli(
                ["--root", str(root), "plan-approve"]
            )

        self.assertEqual(code, 1)
        self.assertIn("active stage is design", stderr)

    def test_public_plan_approval_uses_traceability_gate(self) -> None:
        with temp_project() as root:
            write_file(root / "docs" / "requirements.md", "# Requirements\n\nREQ-1\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(
                root / "docs" / "implementation-plan.md",
                "# Plan\n\n## Phase 1\n\nRequirements: REQ-1\n",
            )
            StateStore(root).init_run(run_id="run-1")
            write_manual_runtime(root)
            self.assertEqual(self.run_cli(["--root", str(root), "requirements"])[0], 0)
            self.assertEqual(
                self.run_cli(["--root", str(root), "requirements-approve"])[0],
                0,
            )
            self.assertEqual(
                self.run_cli(["--root", str(root), "design-review"])[0],
                0,
            )
            self.assertEqual(
                self.run_cli(["--root", str(root), "design-approve"])[0],
                0,
            )
            self.assertEqual(
                self.run_cli(["--root", str(root), "implementation-plan"])[0],
                0,
            )

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "plan-approve"]
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("active stage: implementation", stdout)

    def test_stage_force_sets_active_stage(self) -> None:
        with temp_project() as root:
            store = StateStore(root)
            store.init_run(run_id="run-1")

            code, stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "stage",
                    STAGE_IMPLEMENTATION,
                    "--force",
                    "--reason",
                    "Adopting existing project.",
                ]
            )
            manifest = store.load_current_manifest()
            activity = store.read_activity()

        self.assertEqual(code, 0, stderr)
        self.assertIn("previous stage: requirements", stdout)
        self.assertIn("active stage: implementation", stdout)
        self.assertEqual(manifest.active_stage, STAGE_IMPLEMENTATION)
        self.assertEqual(activity[-1]["action"], "forced-stage-change")

    def test_stage_force_requires_reason(self) -> None:
        with temp_project() as root:
            StateStore(root).init_run(run_id="run-1")

            code, _stdout, stderr = self.run_cli(
                ["--root", str(root), "stage", STAGE_IMPLEMENTATION, "--force"]
            )

        self.assertEqual(code, 2)
        self.assertIn("stage changes require --reason", stderr)

    def test_completion_bash_completes_commands(self) -> None:
        with temp_project() as root:
            code, script, stderr = self.run_cli(["completion", "bash"])
            script_path = root / "completion.bash"
            write_file(script_path, script)

            completed = subprocess.run(
                [
                    "bash",
                    "--noprofile",
                    "--norc",
                    "-c",
                    (
                        'source "$SCRIPT"\n'
                        "COMP_WORDS=(./electroboy imple)\n"
                        "COMP_CWORD=1\n"
                        "__electroboy_complete\n"
                        'printf "%s\\n" "${COMPREPLY[@]}"\n'
                    ),
                ],
                env={"SCRIPT": str(script_path), "PATH": "/usr/bin:/bin"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.splitlines(), ["implementation-plan"])

    def test_completion_bash_completes_stage_choices(self) -> None:
        with temp_project() as root:
            code, script, stderr = self.run_cli(["completion", "bash"])
            script_path = root / "completion.bash"
            write_file(script_path, script)

            completed = subprocess.run(
                [
                    "bash",
                    "--noprofile",
                    "--norc",
                    "-c",
                    (
                        'source "$SCRIPT"\n'
                        "COMP_WORDS=(electroboy stage imple)\n"
                        "COMP_CWORD=2\n"
                        "__electroboy_complete\n"
                        'printf "%s\\n" "${COMPREPLY[@]}"\n'
                    ),
                ],
                env={"SCRIPT": str(script_path), "PATH": "/usr/bin:/bin"},
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.splitlines(), ["implementation"])


class temp_project:
    def __enter__(self) -> Path:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        initialize_git_repo(self.root)
        return self.root

    def __exit__(self, *args: object) -> None:
        self._tmp.cleanup()


def write_file(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def initialize_git_repo(root: Path) -> None:
    subprocess.run(
        ["git", "-C", str(root), "init"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.email", "test@example.com"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    subprocess.run(
        ["git", "-C", str(root), "config", "user.name", "Test User"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def write_manual_runtime(root: Path) -> None:
    write_file(root / "agent-response.md", "accepted\n")
    write_file(
        root / "electroboy.toml",
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
