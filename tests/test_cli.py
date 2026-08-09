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

from electroboy.artifacts import ArtifactManager  # noqa: E402
from electroboy.cli import main  # noqa: E402
from electroboy.gates import GateEngine  # noqa: E402
from electroboy.models import (  # noqa: E402
    BaselineInvalidation,
    GATE_DESIGN,
    GATE_HUMAN_DESIGN_ACCEPTANCE,
    GATE_IMPLEMENTATION,
    GATE_REQUIREMENTS,
    STAGE_DESIGN,
    STAGE_IMPLEMENTATION,
    STAGE_PLAN,
    STAGE_TEST_PLAN,
    STAGE_VALIDATION,
)
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
        self.assertIn("  stage command: electroboy requirements", stdout)
        self.assertIn("next stage: requirements-approve", stdout)
        self.assertIn("completed gates:", stdout)

    def test_status_uses_command_aligned_stage_names(self) -> None:
        with temp_project() as root:
            store = StateStore(root)
            manifest = store.init_run(run_id="run-1")
            manifest.set_active_stage(STAGE_IMPLEMENTATION)
            store.save_manifest(manifest)

            code, stdout, stderr = self.run_cli(["--root", str(root), "status"])

        self.assertEqual(code, 0, stderr)
        self.assertIn("active stage: code", stdout)
        self.assertIn("  stage command: electroboy code", stdout)
        self.assertIn("next stage: test-plan", stdout)

    def test_project_command_requires_active_project(self) -> None:
        with temp_project() as root:
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")

            code, _stdout, stderr = self.run_cli(
                ["--root", str(root), "implementation-plan"]
            )

        self.assertEqual(code, 2)
        self.assertIn("no active ElectroBoy project", stderr)

    def test_progress_once_prints_run_progress_files(self) -> None:
        with temp_project() as root:
            store = StateStore(root)
            manifest = store.init_run(run_id="run-1")
            write_file(
                store.run_dir(manifest.run_id)
                / "progress"
                / "design-review-progress.md",
                "started design review\nchecking design\n",
            )

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "progress", "--once"]
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn(
            "== .electroboy/shared/runs/run-1/progress/"
            "design-review-progress.md ==",
            stdout,
        )
        self.assertIn("checking design", stdout)

    def test_monitor_alias_prints_run_progress_files(self) -> None:
        with temp_project() as root:
            store = StateStore(root)
            manifest = store.init_run(run_id="run-1")
            write_file(
                store.run_dir(manifest.run_id)
                / "progress"
                / "phase-1-code-progress.md",
                "implementing phase 1\n",
            )

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "monitor", "--once"]
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("phase-1-code-progress.md", stdout)
        self.assertIn("implementing phase 1", stdout)

    def test_progress_reports_none_when_no_progress_files_exist(self) -> None:
        with temp_project() as root:
            StateStore(root).init_run(run_id="run-1")

            code, stdout, stderr = self.run_cli(["--root", str(root), "progress"])

        self.assertEqual(code, 0, stderr)
        self.assertEqual(stdout, "progress: none\n")

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
        self.assertIn("  stage command: electroboy design", status_stdout)
        self.assertIn("next stage: design-review", status_stdout)
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

    def test_requirements_authoring_can_disable_implicit_session_resume(self) -> None:
        original = os.environ.get("ELECTROBOY_DISABLE_SESSION_RESUME")
        try:
            with temp_project() as root:
                store = StateStore(root)
                store.init_run(run_id="run-1")
                write_file(root / "docs" / "requirements.md", "# Requirements\n\nREQ-1\n")
                write_manual_runtime(root)
                self.assertEqual(
                    self.run_cli(["--root", str(root), "requirements"])[0],
                    0,
                )

                os.environ["ELECTROBOY_DISABLE_SESSION_RESUME"] = "1"
                code, _stdout, stderr = self.run_cli(
                    ["--root", str(root), "requirements"]
                )
                prompt_files = sorted(
                    (store.run_dir("run-1") / "messages").glob("*-prompt.md")
                )
                prompt = prompt_files[-1].read_text(encoding="utf-8")
        finally:
            if original is None:
                os.environ.pop("ELECTROBOY_DISABLE_SESSION_RESUME", None)
            else:
                os.environ["ELECTROBOY_DISABLE_SESSION_RESUME"] = original

        self.assertEqual(code, 0, stderr)
        self.assertNotIn("Session recovery context:", prompt)
        self.assertNotIn("Previous local session record:", prompt)

    def test_requirements_authoring_accepts_explicit_session_id(self) -> None:
        session_id = "019f3cb6-60c3-7320-896b-e5eb9a6a8dd2"
        with temp_project() as root:
            store = StateStore(root)
            store.init_run(run_id="run-1")
            write_manual_runtime(root)

            code, _stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "requirements",
                    "--session-id",
                    session_id,
                ]
            )
            session = store.read_session_record("requirements", "design_author")

        self.assertEqual(code, 0, stderr)
        self.assertIsNotNone(session)
        session = session or {}
        self.assertEqual(session["session_id"], session_id)
        self.assertTrue(session["resumed_session"])

    def test_requirements_session_id_overwrites_existing_record(self) -> None:
        stale_session_id = "019f3cb6-60c3-7320-896b-e5eb9a6a8dd2"
        new_session_id = "019f3cc1-8f78-70d3-83ff-29ef45e331b8"
        with temp_project() as root:
            store = StateStore(root)
            store.init_run(run_id="run-1")
            write_manual_runtime(root)
            store.write_session_record(
                "requirements",
                "design_author",
                {
                    "provider": "codex",
                    "session_id": stale_session_id,
                    "stage": "requirements",
                    "role": "design_author",
                    "run_id": "run-1",
                    "status": "interrupted",
                    "started_at": "old",
                    "last_seen_at": "old",
                    "cwd": str(root),
                    "artifact": "docs/requirements.md",
                },
            )

            code, _stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "requirements",
                    "--session-id",
                    new_session_id,
                ]
            )
            session = store.read_session_record("requirements", "design_author")

        self.assertEqual(code, 0, stderr)
        self.assertIsNotNone(session)
        session = session or {}
        self.assertEqual(session["session_id"], new_session_id)
        self.assertNotEqual(session["session_id"], stale_session_id)

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
        self.assertIn("active stage: design-approve", stdout)

    def test_force_design_approve_from_design_backfills_review_gate(self) -> None:
        with temp_project() as root:
            store = StateStore(root)
            manifest = store.init_run(run_id="run-1")
            manifest.set_active_stage(STAGE_DESIGN)
            store.save_manifest(manifest)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_manual_runtime(root)
            old_snapshot = ArtifactManager(root).snapshot(
                manifest.run_id,
                "docs/detailed-design.md",
                "old-design",
            )
            store.append_artifact_snapshot(old_snapshot)
            store.append_baseline_invalidation(
                BaselineInvalidation(
                    invalidation_id="INV-0001",
                    change_request_id="CR-0001",
                    baseline="design",
                    invalidated_gates=[
                        GATE_DESIGN,
                        GATE_HUMAN_DESIGN_ACCEPTANCE,
                    ],
                    invalidated_snapshot_refs=[old_snapshot.snapshot_path],
                )
            )

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "design-approve", "--force"]
            )
            plan_code, _plan_stdout, plan_stderr = self.run_cli(
                ["--root", str(root), "implementation-plan"]
            )
            manifest = store.load_current_manifest()
            committed_files = git_show_names(root)
            decisions = store.read_decisions()

        self.assertEqual(code, 0, stderr)
        self.assertEqual(plan_code, 0, plan_stderr)
        self.assertIn("forced approval: yes", stdout)
        self.assertIn("backfilled gates:", stdout)
        self.assertEqual(manifest.active_stage, STAGE_PLAN)
        self.assertTrue(manifest.has_gate(GATE_REQUIREMENTS))
        self.assertTrue(manifest.has_gate(GATE_DESIGN))
        self.assertTrue(manifest.has_gate(GATE_HUMAN_DESIGN_ACCEPTANCE))
        self.assertIn("docs/detailed-design.md", committed_files)
        self.assertIn("docs/design-review.md", committed_files)
        self.assertIn("docs/design-review-updates.md", committed_files)
        self.assertEqual(
            decisions[-1]["summary"],
            "Forced state reset to design-acceptance",
        )

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

    def test_force_implementation_plan_backfills_predecessor_gates(self) -> None:
        with temp_project() as root:
            store = StateStore(root)
            store.init_run(run_id="run-1")
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            write_manual_runtime(root)

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "implementation-plan", "--force"]
            )
            manifest = store.load_current_manifest()
            order = GateEngine(root).stage_order(STAGE_PLAN, manifest)

        self.assertEqual(code, 0, stderr)
        self.assertIn("forced stage reset: yes", stdout)
        self.assertIn("authoring stage: implementation-plan", stdout)
        self.assertEqual(manifest.active_stage, STAGE_PLAN)
        self.assertTrue(manifest.has_gate(GATE_REQUIREMENTS))
        self.assertTrue(manifest.has_gate(GATE_DESIGN))
        self.assertTrue(manifest.has_gate(GATE_HUMAN_DESIGN_ACCEPTANCE))
        self.assertTrue(order.passed, order.messages)

    def test_public_plan_approval_does_not_require_traceability_format(self) -> None:
        with temp_project() as root:
            write_file(root / "docs" / "requirements.md", "# Requirements\n\n- Do it.\n")
            write_file(root / "docs" / "detailed-design.md", "# Design\n")
            write_file(
                root / "docs" / "implementation-plan.md",
                "# Plan\n\n## Phase 1\n\nBuild the first slice.\n",
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

            status_code, status_stdout, status_stderr = self.run_cli(
                ["--root", str(root), "status"]
            )
            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "plan-approve"]
            )

        self.assertEqual(code, 0, stderr)
        self.assertEqual(status_code, 0, status_stderr)
        self.assertIn("active stage: implementation-plan", status_stdout)
        self.assertIn("next stage: plan-approve", status_stdout)
        self.assertIn("completed stage: implementation-plan", stdout)
        self.assertIn("active stage: code", stdout)

    def test_test_plan_authoring_can_run_during_design(self) -> None:
        with temp_project() as root:
            store = StateStore(root)
            manifest = store.init_run(run_id="run-1")
            manifest.complete_gate("requirements")
            manifest.set_active_stage("design")
            store.save_manifest(manifest)
            write_file(root / "docs" / "requirements.md", "# Requirements\n")
            write_manual_runtime(root)

            code, stdout, stderr = self.run_cli(["--root", str(root), "test-plan"])
            prompt_files = list((store.run_dir("run-1") / "messages").glob("*-prompt.md"))
            prompt = prompt_files[0].read_text(encoding="utf-8")
            manifest = store.load_current_manifest()

        self.assertEqual(code, 0, stderr)
        self.assertIn("authoring stage: test-plan", stdout)
        self.assertIn("artifact: docs/test-plan.md", stdout)
        self.assertIn("active stage: design", stdout)
        self.assertIn("approve the test plan after code completes", stdout)
        self.assertEqual(manifest.active_stage, "design")
        self.assertIn("Target file: docs/test-plan.md.", prompt)
        self.assertIn("Focus on system tests", prompt)

    def test_test_plan_approve_commits_and_advances_to_validation(self) -> None:
        with temp_project() as root:
            store = StateStore(root)
            manifest = store.init_run(run_id="run-1")
            manifest.complete_gate(GATE_IMPLEMENTATION)
            manifest.set_active_stage(STAGE_TEST_PLAN)
            store.save_manifest(manifest)
            write_file(root / "docs" / "implementation-plan.md", "# Plan\n")
            write_file(root / "docs" / "test-plan.md", "# Test Plan\n")
            snapshot = ArtifactManager(root).snapshot(
                manifest.run_id,
                "docs/implementation-plan.md",
                "plan-approved",
            )
            store.append_artifact_snapshot(snapshot)

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "test-plan-approve"]
            )
            manifest = store.load_current_manifest()
            committed_files = git_show_names(root)

        self.assertEqual(code, 0, stderr)
        self.assertIn("completed stage: test-plan", stdout)
        self.assertIn("active stage: validate", stdout)
        self.assertEqual(manifest.active_stage, STAGE_VALIDATION)
        self.assertIn("docs/test-plan.md", committed_files)

    def test_public_command_force_sets_active_stage(self) -> None:
        with temp_project() as root:
            store = StateStore(root)
            store.init_run(run_id="run-1")

            code, stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "code",
                    "--force",
                    "--reason",
                    "Adopting existing project.",
                ]
            )
            manifest = store.load_current_manifest()
            activity = store.read_activity()
            order = GateEngine(root).stage_order(STAGE_IMPLEMENTATION, manifest)

        self.assertEqual(code, 0, stderr)
        self.assertIn("previous stage: requirements", stdout)
        self.assertIn("active stage: code", stdout)
        self.assertEqual(manifest.active_stage, STAGE_IMPLEMENTATION)
        self.assertTrue(manifest.has_gate(GATE_IMPLEMENTATION))
        self.assertTrue(order.passed, order.messages)
        self.assertEqual(activity[-1]["action"], "forced-predecessor-gates-completed")

    def test_public_command_force_reason_is_optional(self) -> None:
        with temp_project() as root:
            store = StateStore(root)
            store.init_run(run_id="run-1")

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "code", "--force"]
            )
            manifest = store.load_current_manifest()

        self.assertEqual(code, 0, stderr)
        self.assertIn("forced stage reset: yes", stdout)
        self.assertEqual(manifest.active_stage, STAGE_IMPLEMENTATION)

    def test_feature_start_initializes_standard_pipeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "feature", "start", "Add dashboard"]
            )
            store = StateStore(root)
            manifest = store.load_current_manifest()
            feature = json.loads(
                (store.run_dir(manifest.run_id) / "feature.json").read_text(
                    encoding="utf-8"
                )
            )
            requirements_exists = (
                root / "docs" / "requirements-add-dashboard.md"
            ).exists()
            canonical_requirements_exists = (
                root / "docs" / "requirements.md"
            ).exists()
            activate_exists = (root / ".electroboy" / "bin" / "activate").exists()

        self.assertEqual(code, 0, stderr)
        self.assertIn("feature: Add dashboard", stdout)
        self.assertIn("next: electroboy requirements", stdout)
        self.assertEqual(manifest.active_stage, "requirements")
        self.assertEqual(feature["title"], "Add dashboard")
        self.assertEqual(feature["slug"], "add-dashboard")
        self.assertEqual(
            feature["artifacts"]["requirements"],
            "docs/requirements-add-dashboard.md",
        )
        self.assertEqual(
            feature["artifacts"]["design_review_updates"],
            "docs/design-review-updates-add-dashboard.md",
        )
        self.assertEqual(
            feature["artifacts"]["code_review"],
            "docs/code-review-add-dashboard.md",
        )
        self.assertEqual(
            feature["artifacts"]["test_review"],
            "docs/test-review-add-dashboard.md",
        )
        self.assertEqual(feature["workflow"][-1], "code-approve")
        self.assertTrue(requirements_exists)
        self.assertFalse(canonical_requirements_exists)
        self.assertTrue(activate_exists)

    def test_feature_start_accepts_explicit_feature_artifact_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"

            code, stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "feature",
                    "start",
                    "Add admission and scheduling to the QFw",
                    "--name",
                    "adm-sched-v01",
                ]
            )
            store = StateStore(root)
            manifest = store.load_current_manifest()
            feature = json.loads(
                (store.run_dir(manifest.run_id) / "feature.json").read_text(
                    encoding="utf-8"
                )
            )
            requirements_exists = (
                root / "docs" / "requirements-adm-sched-v01.md"
            ).exists()
            design_exists = (
                root / "docs" / "detailed-design-adm-sched-v01.md"
            ).exists()

        self.assertEqual(code, 0, stderr)
        self.assertIn("feature name: adm-sched-v01", stdout)
        self.assertIn("artifact tag: adm-sched-v01", stdout)
        self.assertIn(
            "artifact requirements: docs/requirements-adm-sched-v01.md",
            stdout,
        )
        self.assertEqual(feature["name"], "adm-sched-v01")
        self.assertEqual(feature["slug"], "adm-sched-v01")
        self.assertEqual(
            feature["artifacts"]["design"],
            "docs/detailed-design-adm-sched-v01.md",
        )
        self.assertTrue(requirements_exists)
        self.assertTrue(design_exists)

    def test_feature_start_warns_before_amending_existing_feature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            self.assertEqual(
                self.run_cli(
                    [
                        "--root",
                        str(root),
                        "feature",
                        "start",
                        "Add dashboard",
                        "--name",
                        "dashboard",
                    ]
                )[0],
                0,
            )

            blocked, _stdout, blocked_stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "feature",
                    "start",
                    "Add dashboard",
                    "--name",
                    "dashboard",
                ]
            )
            amended, amended_stdout, amended_stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "feature",
                    "start",
                    "Add dashboard",
                    "--name",
                    "dashboard",
                    "--amend",
                ]
            )

        self.assertEqual(blocked, 1)
        self.assertIn("warning: feature artifacts already exist", blocked_stderr)
        self.assertIn("rerun with --amend", blocked_stderr)
        self.assertEqual(amended, 0, amended_stderr)
        self.assertIn("feature name: dashboard", amended_stdout)

    def test_feature_requirements_uses_feature_specific_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "project"
            self.assertEqual(
                self.run_cli(
                    [
                        "--root",
                        str(root),
                        "feature",
                        "start",
                        "Add dashboard",
                        "--name",
                        "dashboard",
                    ]
                )[0],
                0,
            )
            write_manual_runtime(root)

            code, stdout, stderr = self.run_cli(["--root", str(root), "requirements"])
            store = StateStore(root)
            manifest = store.load_current_manifest()
            prompt_files = list(
                (store.run_dir(manifest.run_id) / "messages").glob("*-prompt.md")
            )
            prompt = prompt_files[-1].read_text(encoding="utf-8")
            canonical_requirements_exists = (
                root / "docs" / "requirements.md"
            ).exists()

        self.assertEqual(code, 0, stderr)
        self.assertIn("artifact: docs/requirements-dashboard.md", stdout)
        self.assertIn("Target file: docs/requirements-dashboard.md.", prompt)
        self.assertIn(
            "Read only docs/requirements-dashboard.md if it exists.",
            prompt,
        )
        self.assertFalse(canonical_requirements_exists)

    def test_feature_requirements_approval_commits_feature_artifact(self) -> None:
        with temp_project() as root:
            self.assertEqual(
                self.run_cli(
                    [
                        "--root",
                        str(root),
                        "feature",
                        "start",
                        "Add dashboard",
                        "--name",
                        "dashboard",
                    ]
                )[0],
                0,
            )
            write_manual_runtime(root)
            self.assertEqual(self.run_cli(["--root", str(root), "requirements"])[0], 0)

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "requirements-approve"]
            )
            store = StateStore(root)
            manifest = store.load_current_manifest()
            snapshots = store.read_artifact_snapshots()
            committed_files = git_show_names(root)

        self.assertEqual(code, 0, stderr)
        self.assertIn("active stage: design", stdout)
        self.assertTrue(manifest.has_gate("requirements"))
        self.assertTrue(
            any(
                snapshot.get("artifact_path") == "docs/requirements-dashboard.md"
                for snapshot in snapshots
            )
        )
        self.assertIn("docs/requirements-dashboard.md", committed_files)
        self.assertNotIn("docs/requirements.md", committed_files)

    def test_feature_start_can_create_feature_branch(self) -> None:
        with temp_project() as root:
            code, stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "feature",
                    "start",
                    "Add Dashboard",
                    "--branch",
                ]
            )
            completed = subprocess.run(
                ["git", "-C", str(root), "branch", "--show-current"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            store = StateStore(root)
            manifest = store.load_current_manifest()
            feature = json.loads(
                (store.run_dir(manifest.run_id) / "feature.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("branch: feature/add-dashboard", stdout)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "feature/add-dashboard")
        self.assertEqual(feature["branch"], "feature/add-dashboard")

    def test_feature_start_can_create_named_feature_branch(self) -> None:
        with temp_project() as root:
            code, stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "feature",
                    "start",
                    "Add admission and scheduling to the QFw",
                    "--branch",
                    "adm-sched-v01",
                ]
            )
            completed = subprocess.run(
                ["git", "-C", str(root), "branch", "--show-current"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            store = StateStore(root)
            manifest = store.load_current_manifest()
            feature = json.loads(
                (store.run_dir(manifest.run_id) / "feature.json").read_text(
                    encoding="utf-8"
                )
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("branch: adm-sched-v01", stdout)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "adm-sched-v01")
        self.assertEqual(feature["branch"], "adm-sched-v01")

    def test_feature_branch_guard_is_added_to_mutating_agent_prompts(self) -> None:
        with temp_project() as root:
            self.assertEqual(
                self.run_cli(
                    [
                        "--root",
                        str(root),
                        "feature",
                        "start",
                        "Add admission and scheduling to the QFw",
                        "--branch",
                        "adm-sched-v01",
                    ]
                )[0],
                0,
            )
            write_manual_runtime(root)

            code, _stdout, stderr = self.run_cli(["--root", str(root), "requirements"])
            store = StateStore(root)
            manifest = store.load_current_manifest()
            prompt_files = sorted(
                (store.run_dir(manifest.run_id) / "messages").glob("*-prompt.md")
            )
            prompt = prompt_files[-1].read_text(encoding="utf-8")

        self.assertEqual(code, 0, stderr)
        self.assertIn("Feature branch guard:", prompt)
        self.assertIn("Active feature branch: adm-sched-v01", prompt)
        self.assertIn("git switch adm-sched-v01", prompt)
        self.assertIn("git switch -c adm-sched-v01", prompt)
        self.assertIn("nested", prompt)

    def test_feature_start_branch_blocks_tracked_changes(self) -> None:
        with temp_project() as root:
            write_file(root / "tracked.txt", "initial\n")
            subprocess.run(
                ["git", "-C", str(root), "add", "tracked.txt"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            subprocess.run(
                ["git", "-C", str(root), "commit", "-m", "Add tracked file"],
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            write_file(root / "tracked.txt", "dirty\n")

            code, _stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "feature",
                    "start",
                    "Add dashboard",
                    "--branch",
                ]
            )

        self.assertEqual(code, 1)
        self.assertIn("cannot create feature branch", stderr)
        self.assertIn("tracked.txt", stderr)

    def test_feature_start_branch_allows_untracked_files(self) -> None:
        with temp_project() as root:
            write_file(root / "scratch.txt", "untracked\n")

            code, stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "feature",
                    "start",
                    "Add dashboard",
                    "--branch",
                ]
            )
            completed = subprocess.run(
                ["git", "-C", str(root), "branch", "--show-current"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("branch: feature/add-dashboard", stdout)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(completed.stdout.strip(), "feature/add-dashboard")

    def test_bug_start_creates_generic_bug_run_and_branch(self) -> None:
        with temp_project() as root:
            code, stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "bug",
                    "start",
                    "https://tracker.example.com/issues/123",
                    "--branch",
                ]
            )
            store = StateStore(root)
            manifest = store.load_current_manifest()
            bug = json.loads(
                (store.run_dir(manifest.run_id) / "bug.json").read_text(
                    encoding="utf-8"
                )
            )
            issue_exists = (root / "docs" / "bugs" / "123" / "issue.md").exists()
            current_branch = subprocess.run(
                ["git", "-C", str(root), "branch", "--show-current"],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )

        self.assertEqual(code, 0, stderr)
        self.assertIn("bug: Bug from issue 123", stdout)
        self.assertIn("provider: generic", stdout)
        self.assertIn("branch: fix/123", stdout)
        self.assertIn("next: electroboy bug investigate", stdout)
        self.assertEqual(current_branch.stdout.strip(), "fix/123")
        self.assertEqual(bug["workflow"], "bug")
        self.assertEqual(bug["issue"]["provider"], "generic")
        self.assertEqual(
            bug["artifacts"]["issue"],
            "docs/bugs/123/issue.md",
        )
        self.assertTrue(issue_exists)

    def test_bug_start_uses_command_upstream_provider(self) -> None:
        with temp_project() as root:
            provider = root / "fake-upstream.py"
            write_file(
                provider,
                """
import json
import sys

print(json.dumps({
    "number": 42,
    "title": "Crash on startup",
    "url": sys.argv[1],
    "labels": [{"name": "bug"}, {"name": "urgent"}],
    "body": "The app crashes before the first prompt.",
}))
""".lstrip(),
            )
            write_file(
                root / "electroboy.toml",
                f"""
[upstream]
default = "tracker"

[upstreams.tracker]
adapter = "command"
command = "{sys.executable}"
args = ["{provider}", "{{reference}}"]
domains = ["tracker.example.com"]
""".lstrip(),
            )

            code, stdout, stderr = self.run_cli(
                [
                    "--root",
                    str(root),
                    "bug",
                    "start",
                    "https://tracker.example.com/issues/42",
                    "--branch",
                ]
            )
            store = StateStore(root)
            manifest = store.load_current_manifest()
            bug = json.loads(
                (store.run_dir(manifest.run_id) / "bug.json").read_text(
                    encoding="utf-8"
                )
            )
            issue_text = (
                root / "docs" / "bugs" / "42-crash-on-startup" / "issue.md"
            ).read_text(encoding="utf-8")

        self.assertEqual(code, 0, stderr)
        self.assertIn("provider: tracker", stdout)
        self.assertIn("branch: fix/42-crash-on-startup", stdout)
        self.assertEqual(bug["issue"]["labels"], ["bug", "urgent"])
        self.assertIn("The app crashes before the first prompt.", issue_text)

    def test_bug_steps_write_artifacts_and_branch_guard(self) -> None:
        with temp_project() as root:
            self.assertEqual(
                self.run_cli(
                    [
                        "--root",
                        str(root),
                        "bug",
                        "start",
                        "https://tracker.example.com/issues/123",
                        "--branch",
                        "fix/bug-123",
                    ]
                )[0],
                0,
            )
            write_manual_runtime(root)

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "bug", "investigate"]
            )
            reproduce_code, _reproduce_stdout, reproduce_stderr = self.run_cli(
                ["--root", str(root), "bug", "reproduce"]
            )
            store = StateStore(root)
            manifest = store.load_current_manifest()
            bug = json.loads(
                (store.run_dir(manifest.run_id) / "bug.json").read_text(
                    encoding="utf-8"
                )
            )
            prompt_files = sorted(
                (store.run_dir(manifest.run_id) / "messages").glob("*-prompt.md")
            )
            prompt = prompt_files[-1].read_text(encoding="utf-8")
            investigation_exists = (
                root
                / "docs"
                / "bugs"
                / "123"
                / "investigation.md"
            ).exists()

        self.assertEqual(code, 0, stderr)
        self.assertIn("bug investigation:", stdout)
        self.assertIn("next: electroboy bug reproduce", stdout)
        self.assertEqual(reproduce_code, 0, reproduce_stderr)
        self.assertEqual(bug["steps"]["investigation"]["status"], "completed")
        self.assertTrue(investigation_exists)
        self.assertIn("Bug branch guard:", prompt)
        self.assertIn("Active bug branch: fix/bug-123", prompt)

    def test_bug_step_interactive_records_session(self) -> None:
        with temp_project() as root:
            self.assertEqual(
                self.run_cli(
                    [
                        "--root",
                        str(root),
                        "bug",
                        "start",
                        "https://tracker.example.com/issues/123",
                        "--branch",
                        "fix/bug-123",
                    ]
                )[0],
                0,
            )
            write_manual_runtime(root)

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "bug", "reproduce", "--interactive"]
            )

            store = StateStore(root)
            session = store.read_session_record(
                "bug-reproduction",
                "bug_reproduce_interactive",
            )
            prompt = sorted(
                (store.run_dir(store.current_run_id() or "") / "messages").glob(
                    "*-prompt.md"
                )
            )[-1].read_text(encoding="utf-8")

        self.assertEqual(code, 0, stderr)
        self.assertIn("interactive bug session:", stdout)
        self.assertIsNotNone(session)
        session = session or {}
        self.assertEqual(session["role"], "bug_reproduce_interactive")
        self.assertIn("Interactive mode:", prompt)
        self.assertIn("Bug branch guard:", prompt)
        self.assertIn("Active bug branch: fix/bug-123", prompt)

    def test_bug_validate_runs_operator_commands_and_summary(self) -> None:
        with temp_project() as root:
            self.assertEqual(
                self.run_cli(
                    [
                        "--root",
                        str(root),
                        "bug",
                        "start",
                        "https://tracker.example.com/issues/123",
                    ]
                )[0],
                0,
            )
            command = f"{sys.executable} -c \"print('bug validation ok')\""

            code, stdout, stderr = self.run_cli(
                ["--root", str(root), "bug", "validate", "--command", command]
            )
            summary_code, summary_stdout, summary_stderr = self.run_cli(
                ["--root", str(root), "bug", "summary"]
            )
            validation_text = (
                root
                / "docs"
                / "bugs"
                / "123"
                / "validation.md"
            ).read_text(encoding="utf-8")

        self.assertEqual(code, 0, stderr)
        self.assertIn("validation: passed", stdout)
        self.assertIn("bug validation ok", validation_text)
        self.assertEqual(summary_code, 0, summary_stderr)
        self.assertIn("bug summary:", summary_stdout)

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

    def test_completion_bash_does_not_offer_removed_stage_command(self) -> None:
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
                        "COMP_WORDS=(electroboy sta)\n"
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
        completions = completed.stdout.splitlines()
        self.assertIn("start", completions)
        self.assertIn("status", completions)
        self.assertNotIn("stage", completions)


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


def git_show_names(root: Path) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "show", "--name-only", "--format=", "HEAD"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.stdout


def write_manual_runtime(root: Path) -> None:
    write_file(root / "agent-response.md", "accepted\n")
    config = """
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
""".lstrip()
    write_file(root / "electroboy.toml", config)
    if (root / ".electroboy" / "project.toml").exists():
        write_file(root / ".electroboy" / "project.toml", config)


if __name__ == "__main__":
    unittest.main()
