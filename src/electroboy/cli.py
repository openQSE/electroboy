"""Command-line interface for the AI agent pipeline."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import difflib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterator, Sequence

from .artifacts import ARTIFACT_TEMPLATES, ArtifactError, ArtifactManager
from .feature_artifacts import (
    DEFAULT_ARTIFACT_PATHS,
    DEFAULT_PATH_KEYS,
    artifact_paths_for_run,
    feature_artifact_paths,
    read_feature_record,
    resolve_artifact_path,
)
from .gates import GateEngine
from .models import (
    ActivityEvent,
    ApprovalRecord,
    ArtifactSnapshot,
    BaselineInvalidation,
    ChangeRequest,
    DecisionRecord,
    GATE_CHANGE_CONTROL,
    GATE_COMMIT,
    GATE_DOCUMENTATION,
    GATE_DESIGN,
    GATE_HUMAN_DESIGN_ACCEPTANCE,
    GATE_IMPLEMENTATION,
    GATE_PLAN_CURRENCY,
    GATE_REQUIREMENTS,
    GATE_STAGE_ORDER,
    GATE_TEST_PLAN,
    GATE_VALIDATION_TESTING,
    NEXT_STAGE,
    STAGES,
    PhaseStatus,
    ReviewIssue,
    RunManifest,
    STAGE_COMPLETE,
    STAGE_DESIGN,
    STAGE_DESIGN_ACCEPTANCE,
    STAGE_DESIGN_REVIEW,
    STAGE_DOCS_REVIEW,
    STAGE_IMPLEMENTATION,
    STAGE_PLAN,
    STAGE_REQUIREMENTS,
    STAGE_TEST_PLAN,
    STAGE_VALIDATION,
    utc_now,
)
from .planning import planned_phases
from .adapters.base import AgentInvocation, AgentResult
from .runtime import runtime_for_role
from .state_store import StateError, StateStore


STAGE_REQUIRED_FILES = {
    STAGE_REQUIREMENTS: "docs/requirements.md",
    STAGE_DESIGN: "docs/detailed-design.md",
    STAGE_DESIGN_REVIEW: "docs/detailed-design.md",
    STAGE_PLAN: "docs/implementation-plan.md",
    STAGE_TEST_PLAN: "docs/test-plan.md",
}

STAGE_COMPLETED_GATES = {
    STAGE_REQUIREMENTS: GATE_REQUIREMENTS,
    STAGE_DESIGN_REVIEW: GATE_DESIGN,
    STAGE_DESIGN_ACCEPTANCE: GATE_HUMAN_DESIGN_ACCEPTANCE,
    STAGE_PLAN: GATE_IMPLEMENTATION,
    STAGE_TEST_PLAN: GATE_TEST_PLAN,
}

FORCE_STAGE_COMPLETED_GATES = {
    **STAGE_COMPLETED_GATES,
    STAGE_VALIDATION: GATE_VALIDATION_TESTING,
    STAGE_DOCS_REVIEW: GATE_DOCUMENTATION,
}

STAGE_SNAPSHOT_ARTIFACTS = {
    STAGE_REQUIREMENTS: "docs/requirements.md",
    STAGE_DESIGN_REVIEW: "docs/detailed-design.md",
    STAGE_DESIGN_ACCEPTANCE: "docs/detailed-design.md",
    STAGE_PLAN: "docs/implementation-plan.md",
    STAGE_TEST_PLAN: "docs/test-plan.md",
}

DESIGN_REVIEW_SUMMARY_PATH = "docs/design-review.md"
DESIGN_REVIEW_UPDATES_PATH = "docs/design-review-updates.md"
DESIGN_REVIEW_MAX_PASSES = 3
DESIGN_REVIEW_CONTEXT_PATHS = [
    "docs/requirements.md",
    "docs/detailed-design.md",
]
IMPLEMENTATION_LOG_PATH = "docs/implementation-log.md"
IMPLEMENTATION_REPORT_PATH = "docs/implementation-report.md"
CODE_REVIEW_SUMMARY_PATH = "docs/code-review.md"
RANGE_CODE_REVIEW_ISSUE_PREFIX = "range-code-review"
TEST_REVIEW_SUMMARY_PATH = "docs/test-review.md"
TEST_PLAN_PATH = "docs/test-plan.md"
VALIDATION_REPORT_PATH = "docs/validation-report.md"
IMPLEMENTATION_REVIEW_MAX_ATTEMPTS = 5
META_REGISTRY_PATH = "repositories.json"
META_MANAGEMENT_COMMANDS = {"add", "start"}
ROOT_LOCAL_COMMANDS = {"completion", "deactivate", "new"}
PROJECTLESS_COMMANDS = {
    "add",
    "completion",
    "deactivate",
    "feature",
    "meta",
    "new",
    "start",
}
ACTIVATIONLESS_COMMANDS = {
    "completion",
    "feature",
    "meta",
    "new",
}

APPROVAL_BASELINE_ARTIFACTS = {
    STAGE_REQUIREMENTS: ["docs/requirements.md"],
    STAGE_DESIGN_ACCEPTANCE: [
        "docs/detailed-design.md",
        DESIGN_REVIEW_SUMMARY_PATH,
        DESIGN_REVIEW_UPDATES_PATH,
    ],
    STAGE_PLAN: ["docs/implementation-plan.md"],
    STAGE_TEST_PLAN: [TEST_PLAN_PATH],
    STAGE_VALIDATION: [
        IMPLEMENTATION_LOG_PATH,
        IMPLEMENTATION_REPORT_PATH,
        VALIDATION_REPORT_PATH,
    ],
}

STAGE_APPROVAL_REQUIREMENTS = {
    STAGE_REQUIREMENTS: [
        ("human-approval", "human-operator"),
        ("author-confirmation", "design-author-agent"),
    ],
    STAGE_DESIGN: [
        ("human-approval", "human-operator"),
    ],
    STAGE_DESIGN_ACCEPTANCE: [
        ("human-approval", "human-operator"),
    ],
    STAGE_PLAN: [
        ("human-approval", "human-operator"),
        ("author-confirmation", "design-author-agent"),
    ],
    STAGE_TEST_PLAN: [
        ("human-approval", "human-operator"),
    ],
}

BLOCKING_ISSUE_STATUSES = {"open", "accepted", "fixed", "escalated"}

AGENT_ISSUE_FILES = {
    "design_review": "design-review.jsonl",
    "design-review": "design-review.jsonl",
    "validation": "validation-review.jsonl",
    "validation_review": "validation-review.jsonl",
    "validation-review": "validation-review.jsonl",
    "documentation": "documentation-review.jsonl",
    "documentation_review": "documentation-review.jsonl",
    "documentation-review": "documentation-review.jsonl",
}

AGENT_PROGRESS_IDLE_TIMEOUT_SECONDS = 300.0

AGENT_PROGRESS_ROLES = {
    "design_review",
    "design-review",
    "design_author_update",
    "design-author-update",
    "coding",
    "code_review",
    "code-review",
    "range_code_review",
    "range-code-review",
    "range_code_fix",
    "range-code-fix",
    "test_review",
    "test-review",
    "validation",
    "validation_review",
    "validation-review",
    "documentation",
    "documentation_review",
    "documentation-review",
}

MUTATING_AGENT_ROLES = {
    "design_author",
    "design-author",
    "design_author_update",
    "design-author-update",
    "coding",
    "range_code_fix",
    "range-code-fix",
    "documentation",
}

REVIEW_OUTPUT_CONTRACT_ROLES = {
    "design_review",
    "design-review",
    "code_review",
    "code-review",
    "range_code_review",
    "range-code-review",
    "test_review",
    "test-review",
    "validation",
    "validation_review",
    "validation-review",
    "documentation_review",
    "documentation-review",
}

REVIEW_OUTPUT_SEVERITIES = {"blocker", "major", "minor"}
REVIEW_OUTPUT_STATUSES = {
    "open",
    "accepted",
    "fixed",
    "verified",
    "rejected",
    "deferred",
    "escalated",
}

REVIEW_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["ok", "final_message", "issues"],
    "properties": {
        "ok": {"type": "boolean"},
        "final_message": {"type": "string"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["issue_id", "severity", "status", "summary"],
                "properties": {
                    "issue_id": {"type": "string"},
                    "severity": {"enum": sorted(REVIEW_OUTPUT_SEVERITIES)},
                    "status": {"enum": sorted(REVIEW_OUTPUT_STATUSES)},
                    "summary": {"type": "string"},
                    "artifact": {"type": "string"},
                    "commit": {"type": "string"},
                    "location": {"type": "string"},
                    "rationale": {"type": "string"},
                    "requested_change": {"type": "string"},
                },
            },
        },
    },
}

DOCUMENTATION_REVIEW_FILES = [
    "docs/requirements.md",
    "docs/detailed-design.md",
    "README.md",
    "docs/api.md",
]

AUTHORING_ARTIFACT_STAGES = {
    "docs/requirements.md": STAGE_REQUIREMENTS,
    "docs/detailed-design.md": STAGE_DESIGN,
    "docs/implementation-plan.md": STAGE_PLAN,
    TEST_PLAN_PATH: STAGE_TEST_PLAN,
}

AUTHORING_APPROVAL_COMMANDS = {
    STAGE_REQUIREMENTS: "electroboy requirements-approve",
    STAGE_DESIGN: "electroboy design-review",
    STAGE_PLAN: "electroboy plan-approve",
    STAGE_TEST_PLAN: "electroboy test-plan-approve",
}

CHANGE_BASELINE_INVALIDATED_GATES = {
    "requirements": [
        GATE_REQUIREMENTS,
        GATE_DESIGN,
        GATE_HUMAN_DESIGN_ACCEPTANCE,
        GATE_IMPLEMENTATION,
        GATE_TEST_PLAN,
        GATE_VALIDATION_TESTING,
        GATE_DOCUMENTATION,
    ],
    "design": [
        GATE_DESIGN,
        GATE_HUMAN_DESIGN_ACCEPTANCE,
        GATE_IMPLEMENTATION,
        GATE_TEST_PLAN,
        GATE_VALIDATION_TESTING,
        GATE_DOCUMENTATION,
    ],
    "plan": [
        GATE_IMPLEMENTATION,
        GATE_TEST_PLAN,
        GATE_VALIDATION_TESTING,
        GATE_DOCUMENTATION,
    ],
    "implementation": [
        GATE_TEST_PLAN,
        GATE_VALIDATION_TESTING,
        GATE_DOCUMENTATION,
    ],
    "test-plan": [
        GATE_TEST_PLAN,
        GATE_VALIDATION_TESTING,
        GATE_DOCUMENTATION,
    ],
    "validation": [
        GATE_VALIDATION_TESTING,
        GATE_DOCUMENTATION,
    ],
    "documentation": [
        GATE_DOCUMENTATION,
    ],
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="electroboy")
    parser.add_argument(
        "--root",
        default=".",
        help="repository root containing pipeline artifacts",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    new = subparsers.add_parser("new", help="create a pipeline project")
    new.add_argument("path", help="project directory to create or initialize")
    new.add_argument("--run-id", help="explicit run id for deterministic tests")
    new.add_argument("--force", action="store_true", help="replace current run")

    meta = subparsers.add_parser("meta", help="manage meta-projects")
    meta_subparsers = meta.add_subparsers(dest="meta_command", required=True)
    meta_init = meta_subparsers.add_parser(
        "init",
        help="initialize a meta-project registry",
    )
    meta_init.add_argument("path", help="meta-project directory to initialize")

    add = subparsers.add_parser(
        "add",
        help="register a repository in a meta-project",
    )
    add.add_argument("paths", nargs="+", help="repository paths to register")

    start = subparsers.add_parser(
        "start",
        help="switch the active target repository in a meta-project",
    )
    start.add_argument("repository", help="registered name or repository path")

    subparsers.add_parser("status", help="show current pipeline status")
    _add_progress_parser(subparsers, "progress", help_text="show agent progress")
    _add_progress_parser(
        subparsers,
        "monitor",
        help_text="alias for `progress`",
    )
    subparsers.add_parser("deactivate", help="leave an activated pipeline project")

    feature = subparsers.add_parser("feature", help="feature development workflow")
    feature_subparsers = feature.add_subparsers(
        dest="feature_command",
        required=True,
    )
    feature_start = feature_subparsers.add_parser(
        "start",
        help="start feature development through the standard pipeline",
    )
    feature_start.add_argument("title_or_issue_url", help="feature title or issue URL")
    feature_start.add_argument(
        "--name",
        "--feature-name",
        dest="feature_name",
        help="feature artifact name; prompted when omitted in an interactive shell",
    )
    feature_start.add_argument(
        "--amend",
        action="store_true",
        help="reuse existing feature artifacts without an interactive warning",
    )
    feature_start.add_argument(
        "--branch",
        nargs="?",
        const="",
        metavar="NAME",
        help=(
            "create or switch to a focused feature branch; derive the name when "
            "NAME is omitted"
        ),
    )

    requirements = subparsers.add_parser(
        "requirements",
        help="author or resume requirements definition",
    )
    requirements.add_argument("--reason", help="reason for reopening requirements")
    _add_force_option(requirements)
    requirements.add_argument(
        "--session-id",
        help="provider session id to record and resume for requirements authoring",
    )
    _add_approval_parser(subparsers, "requirements-approve", "approve requirements")

    design = subparsers.add_parser("design", help="author or resume design")
    design.add_argument("--reason", help="reason for reopening design")
    _add_force_option(design)
    design.add_argument(
        "--session-id",
        help="provider session id to record and resume for design authoring",
    )
    design_review = subparsers.add_parser("design-review", help="run design review")
    design_review.add_argument("--reason", help="reason for forcing design review")
    _add_force_option(design_review)
    _add_approval_parser(subparsers, "design-approve", "approve reviewed design")

    implementation_plan = subparsers.add_parser(
        "implementation-plan",
        help="author or resume implementation planning",
    )
    implementation_plan.add_argument(
        "--reason",
        help="reason for reopening implementation planning",
    )
    _add_force_option(implementation_plan)
    implementation_plan.add_argument(
        "--session-id",
        help="provider session id to record and resume for plan authoring",
    )
    _add_approval_parser(subparsers, "plan-approve", "approve implementation plan")

    test_plan = subparsers.add_parser(
        "test-plan",
        help="author or resume system test planning",
    )
    test_plan.add_argument("--reason", help="reason for reopening test planning")
    _add_force_option(test_plan)
    test_plan.add_argument(
        "--session-id",
        help="provider session id to record and resume for test-plan authoring",
    )
    _add_approval_parser(
        subparsers,
        "test-plan-approve",
        "approve system test plan",
    )

    code = subparsers.add_parser("code", help="start or resume implementation")
    code.add_argument("--reason", help="reason for reopening implementation")
    _add_force_option(code)
    code.add_argument(
        "--phased",
        action="store_true",
        help="run one phase and leave commit recording to the operator",
    )
    code.add_argument(
        "--msg",
        action="append",
        default=[],
        help="append an instruction to coding-agent prompts for this run",
    )
    code_review = subparsers.add_parser(
        "code-review",
        help="review an inclusive commit range against approved artifacts",
    )
    code_review.add_argument(
        "range",
        metavar="SHA1..SHA2",
        help="inclusive commit range to review",
    )
    code_review_fix = code_review.add_mutually_exclusive_group()
    code_review_fix.add_argument(
        "--fix-in-place",
        action="store_true",
        help="rewrite the current HEAD range to address blocker/major findings",
    )
    code_review_fix.add_argument(
        "--fix-followup",
        action="store_true",
        help="create follow-up commits at HEAD for blocker/major findings",
    )
    code_review.add_argument(
        "--msg",
        action="append",
        default=[],
        help="append an instruction to range review and fix prompts",
    )
    document = subparsers.add_parser(
        "document",
        help="start or resume documentation review",
    )
    document.add_argument("--reason", help="reason for reopening documentation")
    _add_force_option(document)
    code_approve = subparsers.add_parser(
        "code-approve",
        help="approve completed pipeline",
    )
    _add_force_option(code_approve)

    report = subparsers.add_parser("report", help="generate pipeline reports")
    report_subparsers = report.add_subparsers(dest="report_command", required=True)
    report_summary = report_subparsers.add_parser("summary", help="summarize run")
    report_summary.add_argument("--output", help="write report to this path")
    report_trace = report_subparsers.add_parser("trace", help="show activity trace")
    report_trace.add_argument("--output", help="write report to this path")

    stage = subparsers.add_parser("stage", help="force-reset to a stage")
    stage.add_argument(
        "stage",
        choices=STAGES,
    )
    stage.add_argument(
        "--force",
        action="store_true",
        help="required to reset to the named stage",
    )
    stage.add_argument("--reason", help="reason for forcing the stage reset")

    phase = subparsers.add_parser("phase", help="record manual phase commits")
    phase_subparsers = phase.add_subparsers(dest="phase_command", required=True)
    phase_commit = phase_subparsers.add_parser("commit", help="record phase commit")
    phase_commit.add_argument("phase", type=int)
    phase_commit.add_argument("--sha", default="")

    validate = subparsers.add_parser("validate", help="run validation testing")
    _add_force_option(validate)
    validate.add_argument(
        "--command",
        action="append",
        default=[],
        dest="validation_commands",
        help="quoted validation command; may be provided more than once",
    )
    validate.add_argument(
        "--shell-command",
        action="append",
        default=[],
        dest="validation_shell_commands",
        help="explicit shell validation command; may be provided more than once",
    )
    validation_approve = subparsers.add_parser(
        "validation-approve",
        help="approve validation and commit implementation handoff reports",
    )
    validation_approve.add_argument(
        "--reason",
        help="reason for forcing validation approval",
    )
    _add_force_option(validation_approve)
    completion = subparsers.add_parser(
        "completion",
        help="generate shell completion script",
    )
    completion.add_argument("shell", choices=["bash"])

    return parser


def _add_progress_parser(
    subparsers: argparse._SubParsersAction,
    name: str,
    help_text: str,
) -> None:
    progress = subparsers.add_parser(name, help=help_text)
    follow = progress.add_mutually_exclusive_group()
    follow.add_argument(
        "--follow",
        action="store_true",
        dest="follow",
        default=None,
        help="keep streaming progress updates",
    )
    follow.add_argument(
        "--once",
        action="store_false",
        dest="follow",
        help="print the current progress snapshot and exit",
    )
    progress.add_argument(
        "--interval",
        type=float,
        default=1.0,
        help="seconds between progress file checks while following",
    )


def _add_approval_parser(
    subparsers: argparse._SubParsersAction,
    name: str,
    help_text: str,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(name, help=help_text)
    _add_force_option(parser)
    parser.add_argument(
        "--reason",
        help="reason for forced approval; recorded when --force is used",
    )
    return parser


def _add_force_option(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--force",
        action="store_true",
        help="expert override: reset prior gates so this command can run",
    )


def main(argv: Sequence[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    root_explicit = _root_argument_explicit(raw_argv)
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "completion":
        return _cmd_completion(args)

    try:
        root_store = StateStore(args.root)
        _require_project_activation_for_command(
            root_store,
            args.command,
            root_explicit,
        )
        if args.command == "meta":
            return _cmd_meta(args)
        if args.command == "add":
            return _cmd_meta_add(root_store, args)
        if args.command == "start":
            return _cmd_meta_start(root_store, args)
        if args.command == "status" and _is_meta_project(root_store.root):
            return _cmd_meta_status(root_store)

        store = _store_for_command(root_store, args.command)
        _require_active_project_for_command(store, args.command)
        engine = GateEngine(store.root)

        if args.command == "new":
            return _cmd_new(args)
        if args.command == "status":
            return _cmd_status(store, engine)
        if args.command in {"progress", "monitor"}:
            return _cmd_progress(store, args)
        if args.command == "deactivate":
            return _cmd_deactivate(store)
        if args.command == "feature":
            return _cmd_feature(store, args)
        if args.command == "requirements":
            return _cmd_authoring_stage(store, engine, args, STAGE_REQUIREMENTS)
        if args.command == "requirements-approve":
            return _cmd_stage(
                store,
                engine,
                _stage_args(
                    STAGE_REQUIREMENTS,
                    human=True,
                    author=True,
                    force=args.force,
                    reason=args.reason,
                ),
            )
        if args.command == "design":
            return _cmd_authoring_stage(store, engine, args, STAGE_DESIGN)
        if args.command == "design-review":
            return _cmd_design_review(store, engine, args)
        if args.command == "design-approve":
            return _cmd_stage(
                store,
                engine,
                _stage_args(
                    STAGE_DESIGN_ACCEPTANCE,
                    human=True,
                    force=args.force,
                    reason=args.reason,
                ),
            )
        if args.command == "implementation-plan":
            return _cmd_authoring_stage(store, engine, args, STAGE_PLAN)
        if args.command == "plan-approve":
            return _cmd_stage(
                store,
                engine,
                _stage_args(
                    STAGE_PLAN,
                    human=True,
                    author=True,
                    force=args.force,
                    reason=args.reason,
                ),
            )
        if args.command == "test-plan":
            return _cmd_test_plan(store, engine, args)
        if args.command == "test-plan-approve":
            return _cmd_stage(
                store,
                engine,
                _stage_args(
                    STAGE_TEST_PLAN,
                    human=True,
                    force=args.force,
                    reason=args.reason,
                ),
            )
        if args.command == "code":
            return _cmd_code(store, engine, args)
        if args.command == "code-review":
            return _cmd_code_review(store, args)
        if args.command == "document":
            return _cmd_document(store, engine, args)
        if args.command == "code-approve":
            return _cmd_code_approve(store, engine, args)
        if args.command == "report":
            return _cmd_report(store, engine, args)
        if args.command == "stage":
            return _cmd_set_stage(store, args)
        if args.command == "phase":
            return _cmd_phase(store, engine, args)
        if args.command == "validate":
            return _cmd_validate(store, engine, args)
        if args.command == "validation-approve":
            return _cmd_validation_approve(store, args)
    except StateError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except ArtifactError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    parser.print_help(sys.stderr)
    return 2


def _cmd_meta(args: argparse.Namespace) -> int:
    if args.meta_command == "init":
        return _cmd_meta_init(args)
    return 2


def _cmd_meta_init(args: argparse.Namespace) -> int:
    meta_root = Path(args.path).expanduser().resolve()
    meta_root.mkdir(parents=True, exist_ok=True)
    _write_meta_environment(meta_root)
    registry_exists = _meta_registry_file(meta_root).exists()
    registry = _read_meta_registry(meta_root)
    if not registry_exists:
        _write_meta_registry(meta_root, registry)

    print(f"meta-project: {meta_root}")
    print(f"registry: {_meta_registry_file(meta_root)}")
    print(f"initialized: {'already' if registry_exists else 'yes'}")
    print(f"active repo: {registry.get('active') or 'none'}")
    print(f"registered repos: {len(_meta_repositories(registry))}")
    print(f"activate: source {_project_bin_dir(meta_root) / 'activate'}")
    return 0


def _cmd_meta_add(store: StateStore, args: argparse.Namespace) -> int:
    registry = _require_meta_registry(store.root)
    repo_paths = [
        _resolve_existing_repo_path(store.root, path)
        for path in args.paths
    ]
    records: list[dict[str, object]] = []
    for repo_path in repo_paths:
        registry, record = _register_meta_repository(store.root, repo_path, registry)
        records.append(record)
    print(f"meta-project: {store.root}")
    for record in records:
        print(f"registered repo: {record['name']}")
        print(f"repo path: {record['path']}")
    print(f"active repo: {registry.get('active') or 'none'}")
    return 0


def _cmd_meta_start(store: StateStore, args: argparse.Namespace) -> int:
    registry = _require_meta_registry(store.root)
    repo_path, record = _resolve_meta_repository(
        store.root,
        registry,
        args.repository,
    )
    registry, record = _register_meta_repository(store.root, repo_path, registry)
    registry["active"] = record["name"]
    _write_meta_registry(store.root, registry)

    target_store = _target_store_from_record(store.root, registry, record)
    manifest = _ensure_target_pipeline_project(target_store.root)
    target_store = _target_store_from_record(store.root, registry, record)
    print(f"meta-project: {store.root}")
    print(f"active repo: {record['name']}")
    print(f"repo path: {target_store.root}")
    print(f"run id: {manifest.run_id}")
    print(f"active stage: {manifest.active_stage}")
    print(f"next: {_stage_command(manifest.active_stage)}")
    print(f"artifact root: {target_store.root}")
    return 0


def _cmd_meta_status(store: StateStore) -> int:
    registry = _read_meta_registry(store.root)
    active_name = str(registry.get("active") or "")
    print(f"meta-project: {store.root}")
    if not active_name:
        print("active repo: none")
        _print_meta_repositories(registry)
        return 0

    record = _meta_repository_by_name(registry, active_name)
    if record is None:
        print(f"active repo: {active_name}")
        print("repo path: missing")
        _print_meta_repositories(registry)
        return 0

    target_store = _target_store_from_record(store.root, registry, record)
    print(f"active repo: {record['name']}")
    print(f"repo path: {target_store.root}")
    if target_store.current_run_id():
        _cmd_status(target_store, GateEngine(target_store.root))
    else:
        print("run id: none")
    _print_meta_repositories(registry)
    return 0


def _store_for_command(root_store: StateStore, command: str) -> StateStore:
    if command in ROOT_LOCAL_COMMANDS or not _is_meta_project(root_store.root):
        return root_store
    if command in META_MANAGEMENT_COMMANDS:
        return root_store
    registry = _read_meta_registry(root_store.root)
    active_name = str(registry.get("active") or "")
    if not active_name:
        raise StateError("no active target repo; run `electroboy start <repo>` first")
    record = _meta_repository_by_name(registry, active_name)
    if record is None:
        raise StateError(f"active target repo is not registered: {active_name}")
    return _target_store_from_record(root_store.root, registry, record)


def _root_argument_explicit(argv: Sequence[str]) -> bool:
    return any(arg == "--root" or arg.startswith("--root=") for arg in argv)


def _require_project_activation_for_command(
    root_store: StateStore,
    command: str,
    root_explicit: bool,
) -> None:
    if command in ACTIVATIONLESS_COMMANDS or root_explicit:
        return
    activated_root = _activated_project_root()
    if activated_root is None:
        raise StateError(
            "no active ElectroBoy shell; source "
            "`<project>/.electroboy/bin/activate` or use explicit `--root`"
        )
    if activated_root != root_store.root:
        raise StateError(
            "active ElectroBoy shell points at "
            f"{activated_root}, but command root is {root_store.root}"
        )


def _activated_project_root() -> Path | None:
    root = os.environ.get("ELECTROBOY_PROJECT_ROOT") or os.environ.get(
        "AI_PIPELINE_PROJECT_ROOT"
    )
    if not root:
        return None
    return Path(root).expanduser().resolve()


def _require_active_project_for_command(store: StateStore, command: str) -> None:
    if command in PROJECTLESS_COMMANDS:
        return
    if store.current_run_id():
        return
    raise StateError(
        "no active ElectroBoy project; run `electroboy new <path>`, "
        "source `<project>/.electroboy/bin/activate`, or in a meta-project "
        "run `electroboy start <repo>` first"
    )


def _is_meta_project(root: Path) -> bool:
    return _meta_registry_file(root).exists()


def _require_meta_registry(root: Path) -> dict[str, object]:
    if not _is_meta_project(root):
        raise StateError(
            "meta-project is not initialized; run "
            "`electroboy meta init <path>` first"
        )
    return _read_meta_registry(root)


def _read_meta_registry(root: Path) -> dict[str, object]:
    path = _meta_registry_file(root)
    if not path.exists():
        return {
            "schema_version": 1,
            "active": None,
            "repositories": [],
            "created_at": utc_now(),
            "updated_at": utc_now(),
        }
    return json.loads(path.read_text(encoding="utf-8"))


def _write_meta_registry(root: Path, registry: dict[str, object]) -> None:
    registry["schema_version"] = 1
    registry["updated_at"] = utc_now()
    path = _meta_registry_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(f"{path.suffix}.tmp")
    temp.write_text(
        json.dumps(registry, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp.replace(path)


def _meta_registry_file(root: Path) -> Path:
    return root / ".electroboy" / "shared" / META_REGISTRY_PATH


def _write_meta_environment(meta_root: Path) -> None:
    _write_project_config(meta_root)
    _write_project_gitignore(meta_root)
    _write_project_runtime(meta_root)
    _write_project_bin(meta_root)


def _register_meta_repository(
    meta_root: Path,
    repo_path: Path,
    registry: dict[str, object] | None = None,
    activate_if_empty: bool = False,
) -> tuple[dict[str, object], dict[str, object]]:
    registry = registry or _read_meta_registry(meta_root)
    repo_path = repo_path.resolve()
    repositories = _meta_repositories(registry)
    existing = _meta_repository_by_path(registry, repo_path)
    if existing is not None:
        return registry, existing

    name = repo_path.name
    conflicting = _meta_repository_by_name(registry, name)
    if conflicting is not None:
        raise StateError(
            f"repository name already registered for another path: {name}"
        )

    record: dict[str, object] = {
        "name": name,
        "path": str(repo_path),
        "added_at": utc_now(),
    }
    repositories.append(record)
    registry["repositories"] = repositories
    if activate_if_empty and not registry.get("active"):
        registry["active"] = name
    _write_meta_registry(meta_root, registry)
    return registry, record


def _resolve_meta_repository(
    meta_root: Path,
    registry: dict[str, object],
    reference: str,
) -> tuple[Path, dict[str, object]]:
    by_name = _meta_repository_by_name(registry, reference)
    if by_name is not None:
        path = Path(str(by_name["path"])).resolve()
        if not path.exists():
            raise StateError(f"registered repository path does not exist: {path}")
        if not path.is_dir():
            raise StateError(f"registered repository path is not a directory: {path}")
        return path, by_name

    path = _candidate_repo_path(meta_root, reference)
    if not path.exists():
        raise StateError(f"repository does not exist: {path}")
    if not path.is_dir():
        raise StateError(f"repository path is not a directory: {path}")
    existing = _meta_repository_by_path(registry, path)
    if existing is not None:
        return path, existing
    return path, {"name": path.name, "path": str(path)}


def _resolve_existing_repo_path(meta_root: Path, reference: str) -> Path:
    path = _candidate_repo_path(meta_root, reference)
    if not path.exists():
        raise StateError(f"repository does not exist: {path}")
    if not path.is_dir():
        raise StateError(f"repository path is not a directory: {path}")
    return path


def _candidate_repo_path(meta_root: Path, reference: str) -> Path:
    path = Path(reference).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (meta_root / path).resolve()


def _meta_repositories(registry: dict[str, object]) -> list[dict[str, object]]:
    repositories = registry.get("repositories", [])
    if not isinstance(repositories, list):
        return []
    return [
        repo
        for repo in repositories
        if isinstance(repo, dict)
    ]


def _meta_repository_by_name(
    registry: dict[str, object],
    name: str,
) -> dict[str, object] | None:
    for repo in _meta_repositories(registry):
        if repo.get("name") == name:
            return repo
    return None


def _meta_repository_by_path(
    registry: dict[str, object],
    path: Path,
) -> dict[str, object] | None:
    resolved = path.resolve()
    for repo in _meta_repositories(registry):
        if Path(str(repo.get("path", ""))).resolve() == resolved:
            return repo
    return None


def _target_store_from_record(
    meta_root: Path,
    registry: dict[str, object],
    record: dict[str, object],
) -> StateStore:
    return StateStore(
        Path(str(record["path"])),
        execution_root=meta_root,
        meta_project_root=meta_root,
        target_name=str(record["name"]),
        registered_repositories=_meta_repositories(registry),
    )


def _ensure_target_pipeline_project(project_root: Path) -> RunManifest:
    project_root.mkdir(parents=True, exist_ok=True)
    _init_git_repository(project_root)
    ArtifactManager(project_root).init_templates()
    _write_project_config(project_root)
    _write_project_gitignore(project_root)
    _write_project_runtime(project_root)
    _write_project_bin(project_root)

    store = StateStore(project_root)
    if store.current_run_id():
        return store.load_current_manifest()
    return store.init_run()


def _print_meta_repositories(registry: dict[str, object]) -> None:
    repositories = _meta_repositories(registry)
    print("registered repos:")
    if not repositories:
        print("  - none")
        return
    for repo in repositories:
        print(f"  - {repo.get('name')}: {repo.get('path')}")


def _cmd_completion(args: argparse.Namespace) -> int:
    if args.shell == "bash":
        print(_bash_completion_script(), end="")
        return 0
    print(f"error: unsupported completion shell: {args.shell}", file=sys.stderr)
    return 2


def _bash_completion_script() -> str:
    parser = build_parser()
    subparsers = _subparser_action(parser)
    command_parsers = subparsers.choices if subparsers else {}
    nested_subcommands: dict[str, list[str]] = {}
    nested_options: dict[str, list[str]] = {}

    for command, command_parser in command_parsers.items():
        nested = _subparser_action(command_parser)
        if not nested:
            continue
        nested_subcommands[command] = sorted(nested.choices)
        for subcommand, subcommand_parser in nested.choices.items():
            nested_options[f"{command}:{subcommand}"] = _option_strings(
                subcommand_parser
            )

    command_options = {
        command: _option_strings(command_parser)
        for command, command_parser in command_parsers.items()
    }
    value_options = sorted(
        set(
            _options_requiring_value(parser)
            + [
                option
                for command_parser in command_parsers.values()
                for option in _options_requiring_value(command_parser)
            ]
            + [
                option
                for command_parser in command_parsers.values()
                for nested in [_subparser_action(command_parser)]
                if nested
                for subcommand_parser in nested.choices.values()
                for option in _options_requiring_value(subcommand_parser)
            ]
        )
    )

    replacements = {
        "__COMMANDS__": _shell_words(sorted(command_parsers)),
        "__GLOBAL_OPTIONS__": _shell_words(_option_strings(parser)),
        "__STAGE_CHOICES__": _shell_words(STAGES),
        "__COMPLETION_SHELLS__": "bash",
        "__COMMAND_OPTIONS_CASES__": _bash_case_entries(command_options),
        "__SUBCOMMAND_CASES__": _bash_case_entries(nested_subcommands),
        "__NESTED_OPTIONS_CASES__": _bash_case_entries(nested_options),
        "__VALUE_OPTION_CASE__": _bash_case_pattern(value_options),
    }
    script = _BASH_COMPLETION_TEMPLATE
    for placeholder, value in replacements.items():
        script = script.replace(placeholder, value)
    return script


def _subparser_action(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction | None:
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return action
    return None


def _option_strings(parser: argparse.ArgumentParser) -> list[str]:
    options: list[str] = []
    for action in parser._actions:
        options.extend(action.option_strings)
    return sorted(options)


def _options_requiring_value(parser: argparse.ArgumentParser) -> list[str]:
    options: list[str] = []
    for action in parser._actions:
        if not action.option_strings:
            continue
        if isinstance(action, (argparse._HelpAction, argparse._StoreTrueAction)):
            continue
        if action.nargs == 0:
            continue
        options.extend(action.option_strings)
    return options


def _shell_words(words: Sequence[str]) -> str:
    return " ".join(shlex.quote(word) for word in words)


def _bash_case_entries(mapping: dict[str, list[str]]) -> str:
    lines: list[str] = []
    for key, words in sorted(mapping.items()):
        lines.append(
            f"        {shlex.quote(key)}) printf '%s\\n' "
            f"{shlex.quote(_shell_words(words))} ;;"
        )
    return "\n".join(lines)


def _bash_case_pattern(words: Sequence[str]) -> str:
    if not words:
        return "__electroboy_no_value_options__"
    return "|".join(shlex.quote(word) for word in words)


_BASH_COMPLETION_TEMPLATE = """# bash completion for ElectroBoy.

__electroboy_commands='__COMMANDS__'
__electroboy_global_options='__GLOBAL_OPTIONS__'
__electroboy_stage_choices='__STAGE_CHOICES__'
__electroboy_completion_shells='__COMPLETION_SHELLS__'

__electroboy_command_options() {
    case "$1" in
__COMMAND_OPTIONS_CASES__
        *) printf '%s\\n' "" ;;
    esac
}

__electroboy_subcommands() {
    case "$1" in
__SUBCOMMAND_CASES__
        *) printf '%s\\n' "" ;;
    esac
}

__electroboy_nested_options() {
    case "$1:$2" in
__NESTED_OPTIONS_CASES__
        *) printf '%s\\n' "" ;;
    esac
}

__electroboy_option_expects_value() {
    case "$1" in
        __VALUE_OPTION_CASE__) return 0 ;;
        *) return 1 ;;
    esac
}

__electroboy_complete() {
    local cur prev command subcommand word options subcommands
    local command_index i have_stage

    COMPREPLY=()
    cur="${COMP_WORDS[COMP_CWORD]}"
    prev="${COMP_WORDS[COMP_CWORD-1]}"

    if [ "$prev" = "--root" ]; then
        COMPREPLY=( $(compgen -d -- "$cur") )
        return 0
    fi
    if __electroboy_option_expects_value "$prev"; then
        return 0
    fi

    command=""
    subcommand=""
    command_index=0
    for ((i = 1; i < COMP_CWORD; i++)); do
        word="${COMP_WORDS[i]}"
        if __electroboy_option_expects_value "$word"; then
            ((i++))
            continue
        fi
        if [[ "$word" == -* ]]; then
            continue
        fi
        if [ -z "$command" ]; then
            command="$word"
            command_index="$i"
            continue
        fi
        if [ -z "$subcommand" ]; then
            subcommands="$(__electroboy_subcommands "$command")"
            case " $subcommands " in
                *" $word "*) subcommand="$word" ;;
            esac
        fi
    done

    if [ -z "$command" ]; then
        if [[ "$cur" == -* ]]; then
            COMPREPLY=( $(compgen -W "$__electroboy_global_options" -- "$cur") )
        else
            COMPREPLY=( $(compgen -W "$__electroboy_commands $__electroboy_global_options" -- "$cur") )
        fi
        return 0
    fi

    subcommands="$(__electroboy_subcommands "$command")"
    if [ -n "$subcommands" ] && [ -z "$subcommand" ]; then
        if [[ "$cur" == -* ]]; then
            options="$(__electroboy_command_options "$command")"
            COMPREPLY=( $(compgen -W "$options" -- "$cur") )
        else
            COMPREPLY=( $(compgen -W "$subcommands" -- "$cur") )
        fi
        return 0
    fi

    if [ -n "$subcommand" ]; then
        options="$(__electroboy_nested_options "$command" "$subcommand")"
        if [[ "$cur" == -* ]]; then
            COMPREPLY=( $(compgen -W "$options" -- "$cur") )
        fi
        return 0
    fi

    if [ "$command" = "stage" ]; then
        have_stage=0
        for ((i = command_index + 1; i < COMP_CWORD; i++)); do
            word="${COMP_WORDS[i]}"
            if __electroboy_option_expects_value "$word"; then
                ((i++))
                continue
            fi
            if [[ "$word" == -* ]]; then
                continue
            fi
            have_stage=1
        done
        if [ "$have_stage" = "0" ] && [[ "$cur" != -* ]]; then
            COMPREPLY=( $(compgen -W "$__electroboy_stage_choices" -- "$cur") )
            return 0
        fi
    fi

    if [ "$command" = "completion" ] && [[ "$cur" != -* ]]; then
        COMPREPLY=( $(compgen -W "$__electroboy_completion_shells" -- "$cur") )
        return 0
    fi

    options="$(__electroboy_command_options "$command")"
    if [[ "$cur" == -* ]]; then
        COMPREPLY=( $(compgen -W "$options" -- "$cur") )
    fi
    return 0
}

if [ -n "${BASH_VERSION:-}" ] && command -v complete >/dev/null 2>&1; then
    complete -o default -F __electroboy_complete electroboy ai-pipeline ./electroboy ./ai-pipeline
fi
"""


def _cmd_new(args: argparse.Namespace) -> int:
    project_root = Path(args.path).resolve()
    project_root.mkdir(parents=True, exist_ok=True)
    _init_git_repository(project_root)
    ArtifactManager(project_root).init_templates()
    _write_project_config(project_root)
    _write_project_gitignore(project_root)
    _write_project_runtime(project_root)
    _write_project_bin(project_root)

    store = StateStore(project_root)
    manifest = store.init_run(run_id=args.run_id, force=args.force)
    print(f"project: {project_root}")
    print(f"created run: {manifest.run_id}")
    print(f"active stage: {manifest.active_stage}")
    print(f"activate: source {_project_bin_dir(project_root) / 'activate'}")
    return 0


def _cmd_feature(store: StateStore, args: argparse.Namespace) -> int:
    if args.feature_command == "start":
        return _cmd_feature_start(store, args)
    print("error: unknown feature command", file=sys.stderr)
    return 2


def _cmd_feature_start(store: StateStore, args: argparse.Namespace) -> int:
    project_root = store.root
    project_root.mkdir(parents=True, exist_ok=True)
    _init_git_repository(project_root)

    feature_name, feature_slug = _select_feature_identity(args)
    feature_artifacts = feature_artifact_paths(feature_slug)
    existing_artifacts = _existing_feature_artifacts(project_root, feature_artifacts)
    if existing_artifacts and not _confirm_feature_amend(
        feature_name,
        existing_artifacts,
        getattr(args, "amend", False),
    ):
        return 1

    branch_name: str | None = None
    if args.branch is not None:
        branch_name = args.branch or _feature_branch_name(args.title_or_issue_url)
        branch_error = _switch_feature_branch(project_root, branch_name)
        if branch_error:
            print(f"error: {branch_error}", file=sys.stderr)
            return 1

    _init_feature_templates(project_root, feature_artifacts)
    _write_project_config(project_root)
    _write_project_gitignore(project_root)
    _write_project_runtime(project_root)
    _write_project_bin(project_root)

    created_run = False
    if store.current_run_id():
        manifest = store.load_current_manifest()
    else:
        manifest = store.init_run()
        created_run = True

    feature_record = _write_feature_record(
        store,
        args.title_or_issue_url,
        feature_name,
        feature_slug,
        feature_artifacts,
        branch_name,
        bool(existing_artifacts),
    )
    store.append_activity(
        ActivityEvent(
            actor="orchestrator",
            stage=manifest.active_stage,
            action="feature-started",
            summary=f"Started feature workflow for {feature_record['title']}.",
            outputs=[f".electroboy/shared/runs/{manifest.run_id}/feature.json"],
        )
    )

    print(f"feature: {feature_record['title']}")
    print(f"feature name: {feature_record['name']}")
    print(f"artifact tag: {feature_record['slug']}")
    if feature_record.get("source_issue_url"):
        print(f"source issue: {feature_record['source_issue_url']}")
    if branch_name:
        print(f"branch: {branch_name}")
    for key in ["requirements", "design", "implementation_plan", "test_plan"]:
        print(f"artifact {key}: {feature_artifacts[key]}")
    print(f"run id: {manifest.run_id}")
    if created_run:
        print("created run: yes")
    print(f"active stage: {manifest.active_stage}")
    print(f"activate: source {_project_bin_dir(project_root) / 'activate'}")
    print(f"next: {_stage_command(manifest.active_stage)}")
    return 0


def _write_feature_record(
    store: StateStore,
    title_or_issue_url: str,
    feature_name: str,
    feature_slug: str,
    artifacts: dict[str, str],
    branch_name: str | None,
    amending_existing: bool,
) -> dict[str, object]:
    manifest = store.load_current_manifest()
    title = _feature_title(title_or_issue_url)
    previous = read_feature_record(store.root, manifest.run_id) or {}
    record: dict[str, object] = {
        "schema_version": 1,
        "title": title,
        "name": feature_name,
        "slug": feature_slug,
        "input": title_or_issue_url,
        "source_issue_url": (
            title_or_issue_url
            if _looks_like_url(title_or_issue_url)
            else None
        ),
        "artifacts": artifacts,
        "branch": branch_name,
        "amending_existing": amending_existing,
        "run_id": manifest.run_id,
        "started_at": previous.get("started_at", utc_now()),
        "updated_at": utc_now(),
        "workflow": [
            "requirements",
            "requirements-approve",
            "design",
            "design-review",
            "design-approve",
            "implementation-plan",
            "plan-approve",
            "test-plan",
            "code",
            "test-plan",
            "test-plan-approve",
            "validate",
            "validation-approve",
            "document",
            "code-approve",
        ],
    }
    path = store.run_dir(manifest.run_id) / "feature.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(record, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return record


def _select_feature_identity(args: argparse.Namespace) -> tuple[str, str]:
    default_name = _feature_title(args.title_or_issue_url)
    default_slug = _slugify(default_name)
    supplied_name = getattr(args, "feature_name", None)
    if supplied_name is not None and supplied_name.strip():
        feature_name = supplied_name.strip()
    elif sys.stdin.isatty():
        entered = input(f"Feature name [{default_slug}]: ").strip()
        feature_name = entered or default_slug
    else:
        feature_name = default_slug
    feature_slug = _slugify(feature_name)
    return feature_name, feature_slug


def _existing_feature_artifacts(
    root: Path,
    artifacts: dict[str, str],
) -> list[str]:
    return [
        relative_path
        for relative_path in artifacts.values()
        if (root / relative_path).exists()
    ]


def _confirm_feature_amend(
    feature_name: str,
    existing_artifacts: list[str],
    amend: bool,
) -> bool:
    if amend:
        return True
    print(
        f"warning: feature artifacts already exist for {feature_name}: "
        + ", ".join(existing_artifacts),
        file=sys.stderr,
    )
    if not sys.stdin.isatty():
        print(
            "error: rerun with --amend to continue an existing feature",
            file=sys.stderr,
        )
        return False
    answer = input("Amend existing feature artifacts? [y/N]: ").strip().lower()
    return answer in {"y", "yes"}


def _init_feature_templates(root: Path, artifacts: dict[str, str]) -> list[str]:
    template_keys = {
        "requirements": "docs/requirements.md",
        "design": "docs/detailed-design.md",
        "implementation_plan": "docs/implementation-plan.md",
        "test_plan": "docs/test-plan.md",
        "api": "docs/api.md",
    }
    written: list[str] = []
    for key, template_path in template_keys.items():
        relative_path = artifacts.get(key, template_path)
        path = root / relative_path
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        template = ARTIFACT_TEMPLATES[template_path]
        for default_path in DEFAULT_ARTIFACT_PATHS.values():
            template = template.replace(
                default_path,
                resolve_artifact_path(artifacts, default_path),
            )
        path.write_text(template, encoding="utf-8")
        written.append(relative_path)
    return written


def _init_run_templates(store: StateStore) -> list[str]:
    manifest = store.load_current_manifest()
    if read_feature_record(store.root, manifest.run_id):
        return _init_feature_templates(store.root, _run_artifact_paths(store))
    return ArtifactManager(store.root).init_templates()


def _feature_title(title_or_issue_url: str) -> str:
    value = title_or_issue_url.strip()
    if not _looks_like_url(value):
        return value
    parts = [part for part in value.rstrip("/").split("/") if part]
    if len(parts) >= 2 and parts[-2] in {"issues", "pull"}:
        item_type = "issue" if parts[-2] == "issues" else "pull request"
        return f"Feature from {item_type} {parts[-1]}"
    return parts[-1] if parts else value


def _looks_like_url(value: str) -> bool:
    return value.startswith("http://") or value.startswith("https://")


def _feature_branch_name(title_or_issue_url: str) -> str:
    value = title_or_issue_url.strip()
    if _looks_like_url(value):
        parts = [part for part in value.rstrip("/").split("/") if part]
        if len(parts) >= 2 and parts[-2] in {"issues", "pull"}:
            return f"feature/{parts[-1]}"
        value = parts[-1] if parts else value
    return f"feature/{_slugify(value)}"


def _slugify(value: str) -> str:
    chars: list[str] = []
    previous_dash = False
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
            previous_dash = False
            continue
        if not previous_dash:
            chars.append("-")
            previous_dash = True
    slug = "".join(chars).strip("-")
    return slug or "work"


def _switch_feature_branch(root: Path, branch_name: str) -> str | None:
    changed_paths = _git_worktree_changed_paths(root, include_untracked=False)
    if changed_paths:
        return (
            "cannot create feature branch with uncommitted changes: "
            + ", ".join(changed_paths)
        )
    current_branch = _git_current_branch(root)
    if current_branch == branch_name:
        return None
    if _git_branch_exists(root, branch_name):
        command = ["git", "-C", str(root), "switch", branch_name]
    else:
        command = ["git", "-C", str(root), "switch", "-c", branch_name]
    completed = subprocess.run(
        command,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode == 0:
        return None
    return completed.stderr.strip() or completed.stdout.strip() or "git switch failed"


def _git_current_branch(root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "branch", "--show-current"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return None
    branch = completed.stdout.strip()
    return branch or None


def _git_branch_exists(root: Path, branch_name: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(root), "show-ref", "--verify", f"refs/heads/{branch_name}"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return completed.returncode == 0


def _run_artifact_paths(store: StateStore) -> dict[str, str]:
    manifest = store.load_current_manifest()
    return artifact_paths_for_run(store.root, manifest.run_id)


def _artifact_path(store: StateStore, relative_path: str) -> str:
    return resolve_artifact_path(_run_artifact_paths(store), relative_path)


def _artifact_paths(store: StateStore, relative_paths: list[str]) -> list[str]:
    return [
        _artifact_path(store, relative_path)
        for relative_path in relative_paths
    ]


def _stage_required_file(store: StateStore, stage: str) -> str | None:
    required_file = STAGE_REQUIRED_FILES.get(stage)
    if required_file is None:
        return None
    return _artifact_path(store, required_file)


def _stage_snapshot_artifact(store: StateStore, stage: str) -> str | None:
    snapshot_artifact = STAGE_SNAPSHOT_ARTIFACTS.get(stage)
    if snapshot_artifact is None:
        return None
    return _artifact_path(store, snapshot_artifact)


def _approval_baseline_artifacts(store: StateStore, stage: str) -> list[str] | None:
    baseline_paths = APPROVAL_BASELINE_ARTIFACTS.get(stage)
    if baseline_paths is None:
        return None
    return _artifact_paths(store, baseline_paths)


def _documentation_review_files(store: StateStore) -> list[str]:
    return _artifact_paths(store, DOCUMENTATION_REVIEW_FILES)


def _stage_command(stage: str) -> str:
    commands = {
        STAGE_REQUIREMENTS: "electroboy requirements",
        STAGE_DESIGN: "electroboy design",
        STAGE_DESIGN_REVIEW: "electroboy design-review",
        STAGE_DESIGN_ACCEPTANCE: "electroboy design-approve",
        STAGE_PLAN: "electroboy implementation-plan",
        STAGE_IMPLEMENTATION: "electroboy code",
        STAGE_TEST_PLAN: "electroboy test-plan",
        STAGE_VALIDATION: "electroboy validate",
        STAGE_DOCS_REVIEW: "electroboy document",
        STAGE_COMPLETE: "electroboy code-approve",
    }
    return commands.get(stage, "electroboy status")


def _stage_display_name(stage: str | None) -> str:
    if stage is None:
        return "none"
    command = _stage_command(stage)
    prefix = "electroboy "
    if command.startswith(prefix):
        return command[len(prefix):]
    return stage


def _cmd_status(store: StateStore, engine: GateEngine) -> int:
    manifest = store.load_current_manifest()
    print(f"run id: {manifest.run_id}")
    print(f"active stage: {_stage_display_name(manifest.active_stage)}")
    print(f"  stage command: {_stage_command(manifest.active_stage)}")
    print(f"next stage: {_stage_display_name(NEXT_STAGE.get(manifest.active_stage))}")
    phase_status = store.load_phase_status()
    if phase_status.active_phase is None:
        print("active phase: none")
    else:
        print(f"active phase: {phase_status.active_phase}")
    print("completed gates:")
    for gate in manifest.completed_gates:
        print(f"  - {gate}")
    if not manifest.completed_gates:
        print("  - none")
    _print_list("invalidated gates", manifest.invalidated_gates)
    _print_count("open change requests", _open_change_requests(store))
    _print_count("open review issues", _open_review_issues(store))
    blocked = _blocked_gate_lines(store, engine)
    _print_list("blocked gates", blocked)
    return 0


def _cmd_progress(store: StateStore, args: argparse.Namespace) -> int:
    if args.interval <= 0:
        raise StateError("progress --interval must be greater than zero")
    follow = args.follow if args.follow is not None else sys.stdout.isatty()
    progress_dir = _progress_directory(store)
    files = _progress_files(progress_dir)
    if not files:
        print("progress: none")
        return 0

    positions = _print_progress_snapshot(store, files)
    if not follow:
        return 0

    try:
        while True:
            current_files = _progress_files(progress_dir)
            for path in current_files:
                if path not in positions:
                    positions[path] = 0
                    _print_progress_file_header(store, path)
                positions[path] = _print_progress_file_update(
                    path,
                    positions[path],
                )
            sys.stdout.flush()
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print()
        return 130


def _progress_directory(store: StateStore) -> Path:
    manifest = store.load_current_manifest()
    return store.run_dir(manifest.run_id) / "progress"


def _progress_files(progress_dir: Path) -> list[Path]:
    if not progress_dir.exists():
        return []
    return sorted(
        (path for path in progress_dir.glob("*.md") if path.is_file()),
        key=lambda path: (_progress_sort_mtime(path), path.name),
    )


def _progress_sort_mtime(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def _print_progress_snapshot(
    store: StateStore,
    files: list[Path],
) -> dict[Path, int]:
    positions: dict[Path, int] = {}
    for index, path in enumerate(files):
        if index:
            print()
        _print_progress_file_header(store, path)
        positions[path] = _print_progress_file_update(path, 0)
    return positions


def _print_progress_file_header(store: StateStore, path: Path) -> None:
    print(f"== {_progress_display_path(store, path)} ==")


def _progress_display_path(store: StateStore, path: Path) -> str:
    try:
        relative = path.relative_to(store.root).as_posix()
    except ValueError:
        return str(path)
    return _execution_context_paths(store, [relative])[0]


def _print_progress_file_update(path: Path, position: int) -> int:
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return position
    if size < position:
        position = 0
    with path.open("r", encoding="utf-8") as stream:
        stream.seek(position)
        text = stream.read()
        position = stream.tell()
    if text:
        print(text, end="" if text.endswith("\n") else "\n")
    return position


def _cmd_deactivate(store: StateStore) -> int:
    if store.current_run_id():
        manifest = store.load_current_manifest()
        store.append_activity(
            ActivityEvent(
                actor="orchestrator",
                stage=manifest.active_stage,
                action="project-deactivated",
                summary="Left activated pipeline project environment.",
            )
        )
    print("pipeline project deactivated")
    return 0


def _cmd_authoring_stage(
    store: StateStore,
    engine: GateEngine,
    args: argparse.Namespace,
    stage: str,
) -> int:
    manifest = store.load_current_manifest()
    if getattr(args, "force", False):
        _force_reset_to_stage(store, stage, getattr(args, "reason", None))
        manifest = store.load_current_manifest()
    else:
        if _maybe_reopen_from_public_command(
            store,
            manifest,
            stage,
            getattr(args, "reason", None),
        ):
            manifest = store.load_current_manifest()
    order = engine.stage_order(stage, manifest)
    if not order.passed:
        _print_gate_failure(order.messages)
        return 1

    return _run_authoring_session(store, args, stage)


def _cmd_test_plan(
    store: StateStore,
    engine: GateEngine,
    args: argparse.Namespace,
) -> int:
    manifest = store.load_current_manifest()
    if getattr(args, "force", False):
        _force_reset_to_stage(store, STAGE_TEST_PLAN, getattr(args, "reason", None))
        manifest = store.load_current_manifest()
    else:
        if _maybe_reopen_from_public_command(
            store,
            manifest,
            STAGE_TEST_PLAN,
            getattr(args, "reason", None),
        ):
            manifest = store.load_current_manifest()

    if manifest.active_stage == STAGE_TEST_PLAN:
        order = engine.stage_order(STAGE_TEST_PLAN, manifest)
        if not order.passed:
            _print_gate_failure(order.messages)
            return 1
    else:
        readiness_errors = _test_plan_authoring_errors(store, engine)
        if readiness_errors:
            _print_gate_failure(readiness_errors)
            return 1

    return _run_authoring_session(
        store,
        args,
        STAGE_TEST_PLAN,
        out_of_band=manifest.active_stage != STAGE_TEST_PLAN,
    )


def _test_plan_authoring_errors(
    store: StateStore,
    engine: GateEngine,
) -> list[str]:
    messages: list[str] = []
    change_control = engine.change_control()
    messages.extend(change_control.messages)
    requirements = engine.require_file(
        _artifact_path(store, "docs/requirements.md")
    )
    messages.extend(requirements.messages)
    return messages


def _run_authoring_session(
    store: StateStore,
    args: argparse.Namespace,
    stage: str,
    out_of_band: bool = False,
) -> int:
    _init_run_templates(store)
    artifact = _stage_required_file(store, stage)
    reason = getattr(args, "reason", None)
    artifact_snapshot = _authoring_artifact_snapshot(store)
    result, event_id, _issue_file = _invoke_agent_role(
        store,
        role="design_author",
        prompt=_authoring_prompt(store, stage),
        context_paths=_authoring_inputs(store, stage),
        session_stage=stage,
        session_artifact=artifact,
        explicit_session_id=getattr(args, "session_id", None),
    )
    changed_artifacts = _changed_authoring_artifacts(store, artifact_snapshot)
    if not result.ok:
        print(result.final_message, end="" if result.final_message.endswith("\n") else "\n")
        return 1
    summary = f"Started or resumed {stage} authoring."
    if reason:
        summary = f"{summary} Reason: {reason}"
    store.append_activity(
        ActivityEvent(
            actor="design-author-agent",
            stage=stage,
            action="authoring-session-recorded",
            summary=summary,
            inputs=_authoring_inputs(store, stage),
            outputs=[artifact] if artifact else [],
            artifact_changes=changed_artifacts,
            message_ref=f"messages/{event_id}-response.md",
        )
    )
    print(f"authoring stage: {stage}")
    if artifact:
        print(f"artifact: {artifact}")
    if _reopen_earliest_upstream_authoring_stage(store, stage, changed_artifacts):
        return 0
    if stage == STAGE_TEST_PLAN:
        active_stage = store.load_current_manifest().active_stage
        if out_of_band:
            print(f"active stage: {active_stage}")
            print(
                "next: continue the active stage; approve the test plan "
                "after code completes"
            )
            return 0
        print(f"next: review {artifact}, then run `electroboy test-plan-approve`")
        return 0
    print("next: review the artifact, then run the approval command")
    return 0


def _cmd_design_review(
    store: StateStore,
    engine: GateEngine,
    args: argparse.Namespace,
) -> int:
    manifest = store.load_current_manifest()
    if getattr(args, "force", False):
        _force_reset_to_stage(
            store,
            STAGE_DESIGN_REVIEW,
            getattr(args, "reason", None),
        )
        manifest = store.load_current_manifest()
    if manifest.active_stage == STAGE_DESIGN:
        with _progress_step("design-review", "recording design baseline"):
            code = _cmd_stage(
                store,
                engine,
                _stage_args(STAGE_DESIGN, human=True),
            )
        if code != 0:
            return code

    manifest = store.load_current_manifest()
    readiness_errors = _stage_readiness_errors(
        engine,
        manifest,
        STAGE_DESIGN_REVIEW,
    )
    if readiness_errors:
        _print_gate_failure(readiness_errors)
        return 1

    update_log_path = _init_design_review_update_log(store)
    for pass_number in range(1, DESIGN_REVIEW_MAX_PASSES + 1):
        with _progress_step(
            "design-review",
            f"running design review agent pass {pass_number}",
        ):
            result, event_id, issue_file = _invoke_agent_role(
                store,
                role="design_review",
                prompt=_design_review_prompt(store, pass_number),
                context_paths=_design_review_context_paths(store),
            )
        _print_progress(
            "design-review",
            f"agent completed with {len(result.issues)} reported issue(s)",
        )

        issue_file = issue_file or "design-review.jsonl"
        _sync_design_review_narrative_issues(store, issue_file, result, event_id)
        blocking = _blocking_issues(store, issue_file)
        outcome = _design_review_outcome(result, blocking)
        with _progress_step("design-review", "writing review summary"):
            summary_path = _write_design_review_summary(
                store,
                result,
                event_id,
                issue_file,
                outcome,
            )
        print(f"summary: {summary_path}")
        print(f"updates: {update_log_path}")

        if not result.ok:
            print(
                result.final_message,
                end="" if result.final_message.endswith("\n") else "\n",
            )
            return 1
        if not blocking:
            with _progress_step("design-review", "completing design-review gate"):
                code = _cmd_stage(store, engine, _stage_args(STAGE_DESIGN_REVIEW))
            if code == 0:
                print(
                    "next: run `electroboy design-approve` to commit the "
                    "design baseline"
                )
            return code

        if pass_number == DESIGN_REVIEW_MAX_PASSES:
            _print_gate_failure(["blocking design review issues remain"])
            return 1

        update_code = _run_design_review_update(
            store,
            pass_number,
            event_id,
            issue_file,
            summary_path,
            blocking,
        )
        if update_code != 0:
            return update_code

    _print_gate_failure(["blocking design review issues remain"])
    return 1


def _cmd_code(
    store: StateStore,
    engine: GateEngine,
    args: argparse.Namespace,
) -> int:
    manifest = store.load_current_manifest()
    if getattr(args, "force", False):
        _force_reset_to_stage(
            store,
            STAGE_IMPLEMENTATION,
            getattr(args, "reason", None),
        )
        manifest = store.load_current_manifest()
    else:
        if _maybe_reopen_from_public_command(
            store,
            manifest,
            STAGE_IMPLEMENTATION,
            getattr(args, "reason", None),
        ):
            manifest = store.load_current_manifest()
    if manifest.active_stage == STAGE_VALIDATION:
        _print_progress("validation", "implementation phases are complete")
        print("next: run validation commands, then `electroboy validation-approve`")
        return 0
    if manifest.active_stage == STAGE_TEST_PLAN:
        _print_progress("test-plan", "implementation phases are complete")
        print("next: run `electroboy test-plan`, then `electroboy test-plan-approve`")
        return 0
    if manifest.active_stage == STAGE_DOCS_REVIEW:
        _print_progress("documentation", "validation has passed")
        print("next: electroboy document")
        return 0
    if manifest.active_stage == STAGE_COMPLETE:
        _print_progress("complete", "pipeline implementation is complete")
        print("next: electroboy code-approve")
        return 0
    if manifest.active_stage != STAGE_IMPLEMENTATION:
        order = engine.stage_order(STAGE_IMPLEMENTATION, manifest)
        _print_gate_failure(order.messages or ["implementation stage is not active"])
        return 1
    if not manifest.has_gate(GATE_IMPLEMENTATION):
        _print_gate_failure(["implementation gate has not passed"])
        return 1

    operator_messages = _code_operator_messages(args)
    if getattr(args, "phased", False):
        return _cmd_code_phased(store, engine, args, operator_messages)
    return _cmd_code_automated(store, engine, args, operator_messages)


def _code_operator_messages(args: argparse.Namespace) -> list[str]:
    return [
        str(message).strip()
        for message in getattr(args, "msg", []) or []
        if str(message).strip()
    ]


def _cmd_code_review(store: StateStore, args: argparse.Namespace) -> int:
    start_rev, end_rev = _parse_commit_range_spec(args.range)
    start_sha = _git_resolve_commit(store.root, start_rev)
    end_sha = _git_resolve_commit(store.root, end_rev)
    if start_sha is None:
        raise StateError(f"unknown start commit: {start_rev}")
    if end_sha is None:
        raise StateError(f"unknown end commit: {end_rev}")
    if not _git_is_ancestor(store.root, start_sha, end_sha):
        raise StateError(f"range start is not an ancestor of range end: {args.range}")

    base_sha = _git_first_parent(store.root, start_sha)
    commits = _git_inclusive_commit_range(store.root, start_sha, end_sha)
    if not commits:
        raise StateError(f"commit range is empty: {args.range}")

    fix_mode = _range_code_review_fix_mode(args)
    if fix_mode in {"in-place", "followup"}:
        _validate_fix_range_at_head(store, end_sha, fix_mode)

    issue_file = _range_code_review_issue_file(start_sha, end_sha)
    operator_messages = _code_operator_messages(args)
    current_end = end_sha
    current_commits = commits
    for attempt in range(1, IMPLEMENTATION_REVIEW_MAX_ATTEMPTS + 1):
        result, event_id, review_issue_file = _invoke_agent_role(
            store,
            role="range_code_review",
            prompt=_range_code_review_prompt(
                store,
                start_sha,
                current_end,
                current_commits,
                attempt,
                fix_mode,
                operator_messages,
            ),
            context_paths=_range_code_review_context_paths(store),
            issue_file_override=issue_file,
        )
        review_issue_file = review_issue_file or issue_file
        _verify_unreported_blocking_issues(
            store,
            review_issue_file,
            result.issues,
            event_id,
            "range code review",
        )
        summary_path = _write_range_code_review_summary(
            store,
            range_spec=args.range,
            start_sha=start_sha,
            end_sha=current_end,
            commits=current_commits,
            issue_file=review_issue_file,
            attempt=attempt,
            fix_mode=fix_mode,
        )
        blocking = _blocking_issues(store, review_issue_file)
        print(f"code review: {summary_path}")
        print(f"issue file: {review_issue_file}")
        print(f"commits reviewed: {len(current_commits)}")
        print(f"blocker/major findings: {len(blocking)}")
        if not result.ok:
            print(
                result.final_message,
                end="" if result.final_message.endswith("\n") else "\n",
            )
            return 1
        if fix_mode == "none" or not blocking:
            return 0
        if attempt == IMPLEMENTATION_REVIEW_MAX_ATTEMPTS:
            _print_gate_failure(
                [
                    (
                        "blocking range code review issues remain after "
                        f"{IMPLEMENTATION_REVIEW_MAX_ATTEMPTS} attempts"
                    ),
                    f"review summary: {summary_path}",
                ]
            )
            return 1

        fix_code = _run_range_code_fix(
            store,
            base_sha,
            current_end,
            current_commits,
            review_issue_file,
            summary_path,
            attempt,
            fix_mode,
            operator_messages,
        )
        if fix_code != 0:
            return fix_code
        previous_end = current_end
        previous_commits = list(current_commits)
        current_end = _git_current_head(store.root) or current_end
        current_commits = _git_commits_after_base(store.root, base_sha, current_end)
        mode_error = _range_fix_mode_error(
            fix_mode,
            previous_end,
            previous_commits,
            current_end,
            current_commits,
        )
        if mode_error:
            print(mode_error, file=sys.stderr)
            return 1
    return 1


def _range_code_review_fix_mode(args: argparse.Namespace) -> str:
    if bool(getattr(args, "fix_in_place", False)):
        return "in-place"
    if bool(getattr(args, "fix_followup", False)):
        return "followup"
    return "none"


def _range_fix_mode_error(
    fix_mode: str,
    previous_end: str,
    previous_commits: list[str],
    current_end: str,
    current_commits: list[str],
) -> str | None:
    if fix_mode == "in-place":
        if len(current_commits) != len(previous_commits):
            return (
                "--fix-in-place changed the range commit count; fixes must be "
                "folded into the existing commits instead of added as "
                "follow-up commits"
            )
        return None
    if fix_mode == "followup":
        if current_end == previous_end:
            return "--fix-followup did not create a follow-up commit"
        if len(current_commits) <= len(previous_commits):
            return (
                "--fix-followup rewrote existing commits; fixes must be added "
                "as follow-up commits at HEAD"
            )
        if current_commits[: len(previous_commits)] != previous_commits:
            return (
                "--fix-followup changed commits in the reviewed range; fixes "
                "must preserve the reviewed commits and append follow-up commits"
            )
    return None


def _run_range_code_fix(
    store: StateStore,
    base_sha: str | None,
    end_sha: str,
    commits: list[str],
    issue_file: str,
    summary_path: str,
    attempt: int,
    fix_mode: str,
    operator_messages: list[str],
) -> int:
    result, _event_id, _issue_file = _invoke_agent_role(
        store,
        role="range_code_fix",
        prompt=_range_code_fix_prompt(
            store,
            base_sha,
            end_sha,
            commits,
            issue_file,
            summary_path,
            attempt,
            fix_mode,
            operator_messages,
        ),
        context_paths=[
            *_range_code_review_context_paths(store),
            summary_path,
        ],
    )
    if not result.ok:
        print(
            result.final_message,
            end="" if result.final_message.endswith("\n") else "\n",
        )
        return 1
    changed_paths = _non_review_tracked_changes(store)
    if changed_paths:
        print(
            f"error: --fix-{fix_mode} left uncommitted tracked changes: "
            + ", ".join(changed_paths),
            file=sys.stderr,
        )
        return 1
    return 0


def _cmd_code_phased(
    store: StateStore,
    engine: GateEngine,
    args: argparse.Namespace,
    operator_messages: list[str],
) -> int:
    phase_status = store.load_phase_status()
    if phase_status.active_phase is not None:
        phase = phase_status.active_phase
        _print_progress("implementation", f"resuming phase {phase}")
        store.append_activity(
            ActivityEvent(
                actor="orchestrator",
                stage=STAGE_IMPLEMENTATION,
                phase=phase,
                action="code-resumed",
                summary=f"Resumed implementation phase {phase}.",
            )
        )
        print(f"active phase: {phase}")
        code = _run_phase_agent_loop(store, phase, operator_messages)
        print("next: commit the phase after reviewing repository changes")
        return code

    next_phase = _next_uncommitted_phase(store)
    if next_phase is None:
        _print_progress("implementation", "all planned phases are committed")
        return _complete_implementation_stage(store, engine)

    phase_status.active_phase = next_phase
    phase = phase_status.phases.setdefault(str(next_phase), {})
    phase.update(
        {
            "status": "active",
            "objective": _phase_objective(store, next_phase),
            "plan_current": True,
        }
    )
    store.save_phase_status(phase_status)
    store.append_activity(
        ActivityEvent(
            actor="orchestrator",
            stage=STAGE_IMPLEMENTATION,
            phase=next_phase,
            action="code-phase-started",
            summary=f"Started implementation phase {next_phase}.",
        )
    )
    _print_progress("implementation", f"started phase {next_phase}")
    code = _run_phase_agent_loop(store, next_phase, operator_messages)
    print(f"active phase: {next_phase}")
    print("next: commit the phase after reviewing repository changes")
    if getattr(args, "reason", None):
        print(f"reason: {args.reason}")
    return code


def _cmd_code_automated(
    store: StateStore,
    engine: GateEngine,
    args: argparse.Namespace,
    operator_messages: list[str],
) -> int:
    printed_reason = False
    while True:
        phase_status = store.load_phase_status()
        if phase_status.active_phase is None:
            next_phase = _next_uncommitted_phase(store)
            if next_phase is None:
                _print_progress("implementation", "all planned phases are committed")
                return _complete_implementation_stage(store, engine)
            _start_code_phase(store, next_phase)
            phase = next_phase
            _print_progress("implementation", f"started phase {phase}")
        else:
            phase = phase_status.active_phase
            _print_progress("implementation", f"resuming phase {phase}")
            store.append_activity(
                ActivityEvent(
                    actor="orchestrator",
                    stage=STAGE_IMPLEMENTATION,
                    phase=phase,
                    action="code-resumed",
                    summary=f"Resumed implementation phase {phase}.",
                )
            )

        if getattr(args, "reason", None) and not printed_reason:
            print(f"reason: {args.reason}")
            printed_reason = True
        code = _run_phase_agent_loop(store, phase, operator_messages)
        if code != 0:
            return code
        commit_code = _commit_active_phase_with_agent(
            store,
            engine,
            phase,
            operator_messages,
        )
        if commit_code != 0:
            return commit_code


def _start_code_phase(store: StateStore, phase_number: int) -> None:
    phase_status = store.load_phase_status()
    phase_status.active_phase = phase_number
    phase = phase_status.phases.setdefault(str(phase_number), {})
    phase.update(
        {
            "status": "active",
            "objective": _phase_objective(store, phase_number),
            "plan_current": True,
        }
    )
    store.save_phase_status(phase_status)
    store.append_activity(
        ActivityEvent(
            actor="orchestrator",
            stage=STAGE_IMPLEMENTATION,
            phase=phase_number,
            action="code-phase-started",
            summary=f"Started implementation phase {phase_number}.",
        )
    )


def _run_phase_agent_loop(
    store: StateStore,
    phase_number: int,
    operator_messages: list[str],
) -> int:
    code_review_code = _run_code_review_cycle(store, phase_number, operator_messages)
    if code_review_code != 0:
        return code_review_code
    test_review_code = _run_test_review_cycle(store, phase_number, operator_messages)
    if test_review_code != 0:
        return test_review_code
    return 0


def _run_code_review_cycle(
    store: StateStore,
    phase_number: int,
    operator_messages: list[str],
) -> int:
    issue_file = f"phase-{phase_number}-code-review.jsonl"
    summary_path = _phase_review_summary_path(store, "code_review")
    for attempt in range(1, IMPLEMENTATION_REVIEW_MAX_ATTEMPTS + 1):
        needs_review_context = attempt > 1 or bool(_blocking_issues(store, issue_file))
        coding_result, coding_event = _run_coding_pass(
            store,
            phase_number,
            attempt=attempt,
            review_kind="code_review",
            issue_file=issue_file if needs_review_context else None,
            summary_path=summary_path if needs_review_context else None,
            operator_messages=operator_messages,
        )
        status = store.load_phase_status()
        phase = status.phases.setdefault(str(phase_number), {})
        phase["coding_event"] = coding_event
        phase["coding_attempts"] = attempt
        store.save_phase_status(status)
        if not coding_result.ok:
            print(
                coding_result.final_message,
                end="" if coding_result.final_message.endswith("\n") else "\n",
            )
            return 1

        review_result, review_event, review_issue_file = _invoke_agent_role(
            store,
            role="code_review",
            prompt=_code_review_prompt(store, phase_number, attempt),
            context_paths=_implementation_context_paths(store),
        )
        review_issue_file = review_issue_file or issue_file
        _verify_unreported_blocking_issues(
            store,
            review_issue_file,
            review_result.issues,
            review_event,
            "code review",
        )
        summary_path = _write_phase_review_summary(
            store,
            review_kind="code_review",
            current_phase=phase_number,
            attempt=attempt,
        )
        print(f"code review: {summary_path}")
        status = store.load_phase_status()
        phase = status.phases.setdefault(str(phase_number), {})
        phase["code_review_event"] = review_event
        phase["code_review_attempts"] = attempt
        store.save_phase_status(status)
        if not review_result.ok and not review_result.issues:
            print(
                review_result.final_message,
                end="" if review_result.final_message.endswith("\n") else "\n",
            )
            return 1
        blocking = _blocking_issues(store, review_issue_file)
        if not blocking:
            status = store.load_phase_status()
            phase = status.phases.setdefault(str(phase_number), {})
            phase["code_review"] = "passed"
            store.save_phase_status(status)
            return 0
        if attempt == IMPLEMENTATION_REVIEW_MAX_ATTEMPTS:
            _print_gate_failure(
                [
                    (
                        "blocking review issues remain in "
                        f"{review_issue_file} after "
                        f"{IMPLEMENTATION_REVIEW_MAX_ATTEMPTS} attempts"
                    ),
                    f"review summary: {summary_path}",
                ]
            )
            return 1
        _print_progress(
            "code-review",
            (
                f"{len(blocking)} blocker/major issue(s) remain; "
                f"starting fix pass {attempt + 1}"
            ),
        )
    return 1


def _run_test_review_cycle(
    store: StateStore,
    phase_number: int,
    operator_messages: list[str],
) -> int:
    issue_file = f"phase-{phase_number}-test-review.jsonl"
    summary_path = _phase_review_summary_path(store, "test_review")
    for attempt in range(1, IMPLEMENTATION_REVIEW_MAX_ATTEMPTS + 1):
        needs_fix_pass = attempt > 1 or bool(_blocking_issues(store, issue_file))
        if needs_fix_pass:
            coding_result, coding_event = _run_coding_pass(
                store,
                phase_number,
                attempt=attempt,
                review_kind="test_review",
                issue_file=issue_file,
                summary_path=summary_path,
                operator_messages=operator_messages,
            )
            status = store.load_phase_status()
            phase = status.phases.setdefault(str(phase_number), {})
            phase["coding_event"] = coding_event
            phase["test_fix_attempts"] = int(phase.get("test_fix_attempts", 0)) + 1
            store.save_phase_status(status)
            if not coding_result.ok:
                print(
                    coding_result.final_message,
                    end="" if coding_result.final_message.endswith("\n") else "\n",
                )
                return 1

        test_result, test_event, test_issue_file = _invoke_agent_role(
            store,
            role="test_review",
            prompt=_test_review_prompt(store, phase_number, attempt),
            context_paths=_implementation_context_paths(store),
        )
        test_issue_file = test_issue_file or issue_file
        _verify_unreported_blocking_issues(
            store,
            test_issue_file,
            test_result.issues,
            test_event,
            "test review",
        )
        summary_path = _write_phase_review_summary(
            store,
            review_kind="test_review",
            current_phase=phase_number,
            attempt=attempt,
        )
        print(f"test review: {summary_path}")
        status = store.load_phase_status()
        phase = status.phases.setdefault(str(phase_number), {})
        phase["test_review_event"] = test_event
        phase["test_review_attempts"] = attempt
        phase["test_commands"] = list(test_result.commands)
        store.save_phase_status(status)
        if not test_result.ok and not test_result.issues:
            print(
                test_result.final_message,
                end="" if test_result.final_message.endswith("\n") else "\n",
            )
            return 1
        blocking = _blocking_issues(store, test_issue_file)
        if not blocking:
            status = store.load_phase_status()
            phase = status.phases.setdefault(str(phase_number), {})
            phase["test_review"] = "passed"
            store.save_phase_status(status)
            return 0
        if attempt == IMPLEMENTATION_REVIEW_MAX_ATTEMPTS:
            _print_gate_failure(
                [
                    (
                        "blocking review issues remain in "
                        f"{test_issue_file} after "
                        f"{IMPLEMENTATION_REVIEW_MAX_ATTEMPTS} attempts"
                    ),
                    f"review summary: {summary_path}",
                ]
            )
            return 1
        _print_progress(
            "test-review",
            (
                f"{len(blocking)} blocker/major issue(s) remain; "
                f"starting fix pass {attempt + 1}"
            ),
        )
    return 1


def _run_coding_pass(
    store: StateStore,
    phase_number: int,
    attempt: int,
    review_kind: str,
    issue_file: str | None = None,
    summary_path: str | None = None,
    operator_messages: list[str] | None = None,
) -> tuple[AgentResult, str]:
    context_paths = _implementation_context_paths(store)
    if summary_path and (store.root / summary_path).exists():
        context_paths.append(summary_path)
    before_heads = _git_repository_heads(store.root)
    coding_result, coding_event, _coding_issue_file = _invoke_agent_role(
        store,
        role="coding",
        prompt=_coding_prompt(
            store,
            phase_number,
            attempt=attempt,
            review_kind=review_kind,
            issue_file=issue_file,
            summary_path=summary_path,
            operator_messages=operator_messages or [],
        ),
        context_paths=context_paths,
    )
    head_error = _coding_pass_head_change_error(store.root, before_heads)
    if head_error:
        coding_result = _failed_agent_result(head_error)
    return coding_result, coding_event


def _verify_unreported_blocking_issues(
    store: StateStore,
    issue_file: str,
    reported_issues: list[dict[str, object]],
    review_event: str,
    review_label: str,
) -> None:
    reported_blocking_ids = {
        str(issue.get("issue_id") or issue.get("id") or "")
        for issue in reported_issues
        if _issue_is_blocking(issue)
    }
    for issue in store.read_review_issues(issue_file):
        issue_id = str(issue.get("issue_id") or "")
        if not issue_id or issue_id in reported_blocking_ids:
            continue
        if not _issue_is_blocking(issue):
            continue
        _transition_issue(
            store,
            issue_file,
            issue_id,
            status="verified",
            response=(
                f"Later {review_label} pass {review_event} did not report "
                "this blocker/major issue."
            ),
            verification="No longer reported as blocker or major.",
        )


def _phase_review_summary_path(store: StateStore, review_kind: str) -> str:
    if review_kind == "test_review":
        return _artifact_path(store, TEST_REVIEW_SUMMARY_PATH)
    return _artifact_path(store, CODE_REVIEW_SUMMARY_PATH)


def _write_phase_review_summary(
    store: StateStore,
    review_kind: str,
    current_phase: int,
    attempt: int,
) -> str:
    relative_path = _phase_review_summary_path(store, review_kind)
    path = store.root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    title = "Test Review" if review_kind == "test_review" else "Code Review"
    issue_suffix = "test-review" if review_kind == "test_review" else "code-review"
    lines = [
        f"# {title}",
        "",
        f"Generated: {utc_now()}",
        f"Current phase: {current_phase}",
        f"Latest review attempt: {attempt}",
        f"Maximum review attempts: {IMPLEMENTATION_REVIEW_MAX_ATTEMPTS}",
        "",
        "Blocker and major issues stop the phase after the retry limit.",
        "Minor issues are recorded for follow-up and do not block progress.",
        "",
    ]
    phase_status = store.load_phase_status()
    phase_numbers = sorted(
        {int(number) for number in phase_status.phases if str(number).isdigit()}
        | {current_phase}
    )
    for phase_number in phase_numbers:
        issue_file = f"phase-{phase_number}-{issue_suffix}.jsonl"
        issues = store.read_review_issues(issue_file)
        lines.extend([f"## Phase {phase_number}", ""])
        if not issues:
            lines.extend(["- none", ""])
            continue
        for issue in issues:
            lines.extend(_review_issue_detail_lines(issue, issue_file))
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    store.append_activity(
        ActivityEvent(
            actor="orchestrator",
            stage=STAGE_IMPLEMENTATION,
            phase=current_phase,
            action="review-summary-written",
            summary=f"Wrote {relative_path}.",
            outputs=[relative_path],
            artifact_changes=[relative_path],
        )
    )
    return relative_path


def _write_range_code_review_summary(
    store: StateStore,
    range_spec: str,
    start_sha: str,
    end_sha: str,
    commits: list[str],
    issue_file: str,
    attempt: int,
    fix_mode: str,
) -> str:
    relative_path = _artifact_path(store, CODE_REVIEW_SUMMARY_PATH)
    path = store.root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    issues = store.read_review_issues(issue_file)
    blocking = [
        issue
        for issue in issues
        if _issue_is_blocking(issue)
    ]
    lines = [
        "# Code Review",
        "",
        f"Generated: {utc_now()}",
        "Mode: commit range review",
        f"Range: {range_spec}",
        f"Start commit: {start_sha}",
        f"End commit: {end_sha}",
        f"Attempt: {attempt}",
        f"Fix mode: {_range_fix_mode_label(fix_mode)}",
        f"Fix in place: {'yes' if fix_mode == 'in-place' else 'no'}",
        f"Fix follow-up: {'yes' if fix_mode == 'followup' else 'no'}",
        f"Commits reviewed: {len(commits)}",
        f"Blocker/major findings: {len(blocking)}",
        "",
        "## Review Order",
        "",
        *_markdown_list(_commit_review_lines(store.root, commits)),
        "",
        "## Findings",
        "",
    ]
    if not issues:
        lines.extend(["- none", ""])
    else:
        for issue in issues:
            lines.extend(_review_issue_detail_lines(issue, issue_file))
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    store.append_activity(
        ActivityEvent(
            actor="orchestrator",
            stage=STAGE_IMPLEMENTATION,
            action="range-code-review-summary-written",
            summary=f"Wrote {relative_path}.",
            outputs=[relative_path],
            artifact_changes=[relative_path],
        )
    )
    return relative_path


def _range_fix_mode_label(fix_mode: str) -> str:
    labels = {
        "none": "review-only",
        "in-place": "in-place",
        "followup": "follow-up",
    }
    return labels.get(fix_mode, fix_mode)


def _review_issue_detail_lines(issue: dict[str, object], issue_file: str) -> list[str]:
    issue_id = issue.get("issue_id", "unknown")
    severity = issue.get("severity", "unknown")
    status = issue.get("status", "unknown")
    summary = issue.get("summary", "")
    lines = [
        f"### {issue_id}: {summary}",
        "",
        f"- Source: {issue_file}",
        f"- Severity: {severity}",
        f"- Status: {status}",
    ]
    for label, key in [
        ("Commit", "commit"),
        ("Artifact", "artifact"),
        ("Location", "location"),
        ("Requested change", "requested_change"),
        ("Rationale", "rationale"),
        ("Response", "response"),
        ("Verification", "verification"),
    ]:
        value = str(issue.get(key) or "").strip()
        if value:
            lines.append(f"- {label}: {value}")
    lines.append("")
    return lines


def _issue_is_blocking(issue: dict[str, object]) -> bool:
    return (
        issue.get("status") in BLOCKING_ISSUE_STATUSES
        and issue.get("severity") in {"blocker", "major"}
    )


def _phase_review_artifact_paths(store: StateStore) -> list[str]:
    return [
        _normalize_repo_path(_phase_review_summary_path(store, "code_review")),
        _normalize_repo_path(_phase_review_summary_path(store, "test_review")),
    ]


def _commit_active_phase_with_agent(
    store: StateStore,
    engine: GateEngine,
    phase_number: int,
    operator_messages: list[str],
) -> int:
    manifest = store.load_current_manifest()
    result = engine.evaluate(GATE_COMMIT, manifest)
    if not result.passed:
        _print_gate_failure(result.messages)
        return 1

    status = store.load_phase_status()
    if status.active_phase != phase_number:
        print("error: requested phase is not active", file=sys.stderr)
        return 1
    phase = status.phases.setdefault(str(phase_number), {})
    before_head = _git_current_head(store.root)
    _print_progress("implementation", f"asking coding agent to commit phase {phase_number}")
    commit_result, commit_event, _issue_file = _invoke_agent_role(
        store,
        role="coding",
        prompt=_coding_commit_prompt(
            store,
            phase_number,
            phase,
            operator_messages,
        ),
        context_paths=_phase_commit_context_paths(store),
    )
    status = store.load_phase_status()
    phase = status.phases.setdefault(str(phase_number), {})
    phase["commit_event"] = commit_event
    store.save_phase_status(status)
    if not commit_result.ok:
        print(
            commit_result.final_message,
            end="" if commit_result.final_message.endswith("\n") else "\n",
        )
        return 1
    commit_sha = _git_current_head(store.root)
    if commit_sha is None:
        print("error: coding agent did not create a readable commit", file=sys.stderr)
        return 1
    if commit_sha == before_head:
        print("error: coding agent did not create a new phase commit", file=sys.stderr)
        return 1
    validation_error = _phase_commit_validation_error(
        store,
        commit_sha,
        phase_number,
        phase,
    )
    if validation_error:
        print(f"error: {validation_error}", file=sys.stderr)
        return 1

    _record_phase_commit(
        store,
        manifest,
        phase_number,
        commit_sha,
        commit_event=commit_event,
    )
    store.append_activity(
        ActivityEvent(
            actor="orchestrator",
            stage=manifest.active_stage,
            phase=phase_number,
            action="agent-phase-commit-recorded",
            summary=f"Recorded coding-agent commit for phase {phase_number}.",
            inputs=[commit_event],
            commit=commit_sha,
        )
    )
    print(f"committed phase: {phase_number}")
    print(f"commit: {commit_sha}")
    return 0


def _phase_commit_context_paths(store: StateStore) -> list[str]:
    return [
        *_implementation_context_paths(store),
        _phase_review_summary_path(store, "code_review"),
        _phase_review_summary_path(store, "test_review"),
    ]


def _cmd_document(
    store: StateStore,
    engine: GateEngine,
    args: argparse.Namespace,
) -> int:
    manifest = store.load_current_manifest()
    reason = getattr(args, "reason", None)
    if getattr(args, "force", False):
        _force_reset_to_stage(store, STAGE_DOCS_REVIEW, reason)
        manifest = store.load_current_manifest()
    else:
        if _maybe_reopen_from_public_command(
            store,
            manifest,
            STAGE_DOCS_REVIEW,
            reason,
        ):
            manifest = store.load_current_manifest()
    if reason:
        store.append_activity(
            ActivityEvent(
                actor="human-operator",
                stage=manifest.active_stage,
                action="documentation-iteration-requested",
                summary=reason,
            )
        )
    result, _event_id, _issue_file = _invoke_agent_role(
        store,
        role="documentation",
        prompt=_documentation_prompt(store),
        context_paths=[
            *_implementation_context_paths(store),
            "README.md",
            "docs/api.md",
        ],
    )
    if not result.ok:
        print(result.final_message, end="" if result.final_message.endswith("\n") else "\n")
        return 1
    _print_progress("documentation", "running documentation review")
    return _cmd_docs_review(store, engine)


def _cmd_code_approve(
    store: StateStore,
    engine: GateEngine,
    args: argparse.Namespace,
) -> int:
    forced = getattr(args, "force", False)
    if forced:
        _force_reset_to_stage(store, STAGE_COMPLETE, None)
    manifest = store.load_current_manifest()
    result = engine.evaluate(GATE_DOCUMENTATION, manifest)
    if (not forced and not result.passed) or manifest.active_stage != STAGE_COMPLETE:
        messages = result.messages or ["documentation review has not completed"]
        _print_gate_failure(messages)
        return 1
    if not _has_approval(store, STAGE_COMPLETE, "human-completion-approval"):
        approval = ApprovalRecord(
            approval_id=f"APP-{len(store.read_approvals()) + 1:04d}",
            stage=STAGE_COMPLETE,
            actor="human-operator",
            approval_type="human-completion-approval",
            artifact_path=None,
            summary="Human operator approved completed pipeline output.",
        )
        store.append_approval(approval)
        store.append_activity(
            ActivityEvent(
                actor="human-operator",
                stage=STAGE_COMPLETE,
                gate=GATE_DOCUMENTATION,
                action="completion-approved",
                status="pass",
                summary=approval.summary,
                outputs=["approvals.jsonl"],
            )
        )
    print("completion approval: recorded")
    return 0


def _stage_args(
    stage: str,
    human: bool = False,
    author: bool = False,
    force: bool = False,
    reason: str | None = None,
) -> argparse.Namespace:
    return argparse.Namespace(
        stage=stage,
        human_approved=human,
        author_confirmed=author,
        force=force,
        reason=reason,
    )


def _force_reset_to_stage(
    store: StateStore,
    target_stage: str,
    reason: str | None,
) -> str:
    if target_stage not in PUBLIC_STAGE_ORDER:
        raise StateError(f"cannot force unknown public stage: {target_stage}")

    manifest = store.load_current_manifest()
    previous_stage = manifest.active_stage
    decision_id = _record_forced_stage_reset_decision(
        store,
        target_stage,
        reason,
        previous_stage,
    )
    backfill_stages = _force_backfill_stages_for_target(target_stage)
    if (
        STAGE_DESIGN_ACCEPTANCE in backfill_stages
        or target_stage == STAGE_DESIGN_ACCEPTANCE
    ):
        _ensure_forced_approval_artifacts(store, STAGE_DESIGN_ACCEPTANCE)
    backfilled_gates = _backfill_forced_stages(
        store,
        manifest,
        target_stage,
        backfill_stages,
        reason,
    )
    manifest.set_active_stage(target_stage)
    store.save_manifest(manifest)

    print("forced stage reset: yes")
    print(f"previous stage: {previous_stage}")
    print(f"active stage: {target_stage}")
    print(f"decision: {decision_id}")
    if backfilled_gates:
        _print_list("backfilled gates", backfilled_gates)
    return decision_id


def _force_backfill_stages_for_target(target_stage: str) -> list[str]:
    try:
        target_index = PUBLIC_STAGE_ORDER.index(target_stage)
    except ValueError:
        raise StateError(f"cannot force unknown public stage: {target_stage}") from None
    return PUBLIC_STAGE_ORDER[:target_index]


def _record_forced_stage_reset_decision(
    store: StateStore,
    target_stage: str,
    reason: str | None,
    previous_stage: str,
) -> str:
    decision_id = f"STAGE-{len(store.read_decisions()) + 1:04d}"
    rationale = (reason or "").strip() or (
        f"Expert forced state reset from {previous_stage} to {target_stage}."
    )
    store.append_decision(
        DecisionRecord(
            decision_id=decision_id,
            stage=target_stage,
            summary=f"Forced state reset to {target_stage}",
            rationale=rationale,
        )
    )
    store.append_activity(
        ActivityEvent(
            actor="human-operator",
            stage=target_stage,
            action="forced-stage-reset",
            summary=(
                f"Forced state reset from {previous_stage} to {target_stage}."
            ),
            inputs=[rationale],
            outputs=["decisions.jsonl"],
        )
    )
    return decision_id


def _backfill_forced_stages(
    store: StateStore,
    manifest,
    target_stage: str,
    backfill_stages: list[str],
    reason: str | None,
) -> list[str]:
    completed: list[str] = []
    for backfill_stage in backfill_stages:
        backfill_args = _stage_args(
            backfill_stage,
            human=True,
            author=True,
            force=True,
            reason=reason,
        )
        _record_stage_approvals(store, backfill_stage, backfill_args)
        completed_gate = FORCE_STAGE_COMPLETED_GATES.get(backfill_stage)
        if completed_gate and not manifest.has_gate(completed_gate):
            manifest.complete_gate(completed_gate)
            completed.append(completed_gate)
        _snapshot_forced_stage_artifact(store, manifest, backfill_stage)
    if completed:
        store.append_activity(
            ActivityEvent(
                actor="orchestrator",
                stage=target_stage,
                action="forced-predecessor-gates-completed",
                summary=(
                    "Completed skipped predecessor gates for forced stage reset."
                ),
                status="pass",
                outputs=completed,
            )
        )
    return completed


def _snapshot_forced_stage_artifact(
    store: StateStore,
    manifest,
    stage: str,
) -> None:
    snapshot_artifact = _stage_snapshot_artifact(store, stage)
    if not snapshot_artifact:
        return
    event_id = f"{stage}-force-reset"
    if (store.root / snapshot_artifact).exists():
        snapshot = ArtifactManager(store.root).snapshot(
            manifest.run_id,
            snapshot_artifact,
            event_id,
        )
    else:
        snapshot = _write_force_bypass_snapshot(
            store,
            manifest,
            snapshot_artifact,
            event_id,
        )
    store.append_artifact_snapshot(snapshot)
    store.append_activity(
        ActivityEvent(
            actor="orchestrator",
            stage=stage,
            action="artifact-snapshotted",
            summary=f"Snapshotted {snapshot_artifact} for forced stage reset.",
            artifact_snapshot_refs=[snapshot.snapshot_path],
            outputs=[snapshot.snapshot_path],
        )
    )


def _write_force_bypass_snapshot(
    store: StateStore,
    manifest,
    artifact_path: str,
    event_id: str,
) -> ArtifactSnapshot:
    snapshot_root = (
        store.root
        / ".electroboy"
        / "shared"
        / "runs"
        / manifest.run_id
        / "artifacts"
        / event_id
    )
    snapshot_path = snapshot_root / artifact_path
    index = 2
    while snapshot_path.exists():
        snapshot_path = (
            snapshot_root.parent / f"{event_id}-{index}" / artifact_path
        )
        index += 1
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        "\n".join(
            [
                f"# Forced Stage Reset Placeholder: {artifact_path}",
                "",
                "The source artifact did not exist when an expert operator",
                "forced the pipeline state forward. This snapshot records the",
                "intentional bypass without creating a working-tree document.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return ArtifactSnapshot(
        artifact_path=artifact_path,
        snapshot_path=str(snapshot_path.relative_to(store.root)),
        checksum=ArtifactManager(store.root).checksum(snapshot_path),
        event_id=event_id,
    )


def _ensure_forced_approval_artifacts(store: StateStore, stage: str) -> None:
    if stage != STAGE_DESIGN_ACCEPTANCE:
        return
    summary_path = _artifact_path(store, DESIGN_REVIEW_SUMMARY_PATH)
    updates_path = _artifact_path(store, DESIGN_REVIEW_UPDATES_PATH)
    summary = store.root / summary_path
    updates = store.root / updates_path
    if not summary.exists():
        summary.parent.mkdir(parents=True, exist_ok=True)
        summary.write_text(
            "\n".join(
                [
                    "# Design Review",
                    "",
                    f"Run ID: {store.load_current_manifest().run_id}",
                    "Stage result: forced approval",
                    "",
                    "Design review was bypassed by an expert operator.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
    if not updates.exists():
        updates.parent.mkdir(parents=True, exist_ok=True)
        updates.write_text(
            "\n".join(
                [
                    "# Design Review Updates",
                    "",
                    "No coordinated design-review updates were recorded.",
                    "",
                ]
            ),
            encoding="utf-8",
        )


def _authoring_inputs(store: StateStore, stage: str) -> list[str]:
    if stage == STAGE_REQUIREMENTS:
        return [_artifact_path(store, "docs/requirements.md")]
    if stage == STAGE_DESIGN:
        return _artifact_paths(
            store,
            ["docs/requirements.md", "docs/detailed-design.md"],
        )
    if stage == STAGE_PLAN:
        return _artifact_paths(
            store,
            [
                "docs/requirements.md",
                "docs/detailed-design.md",
                "docs/implementation-plan.md",
            ],
        )
    if stage == STAGE_TEST_PLAN:
        return _artifact_paths(
            store,
            [
                "docs/requirements.md",
                "docs/detailed-design.md",
                "docs/implementation-plan.md",
                TEST_PLAN_PATH,
            ],
        )
    return []


def _authoring_prompt(store: StateStore, stage: str) -> str:
    requirements_path = _artifact_path(store, "docs/requirements.md")
    design_path = _artifact_path(store, "docs/detailed-design.md")
    plan_path = _artifact_path(store, "docs/implementation-plan.md")
    test_plan_path = _artifact_path(store, TEST_PLAN_PATH)
    prompts = {
        STAGE_REQUIREMENTS: [
            "Work with the operator on the requirements artifact.",
            "",
            f"Target file: {requirements_path}.",
            f"Read only {requirements_path} if it exists.",
            "Do not explore the working directory or inspect source code unless",
            "the operator explicitly asks you to.",
            f"Update only {requirements_path} unless the operator explicitly",
            "asks for another change.",
            "If the operator asks you to update another artifact, do it and",
            "report which files changed and why.",
        ],
        STAGE_DESIGN: [
            "Work with the operator on the design artifact.",
            "",
            f"Target file: {design_path}.",
            f"Read only {requirements_path} and {design_path} if they exist.",
            "Do not explore the working directory or inspect source code unless",
            "the operator explicitly asks you to.",
            f"Update only {design_path} unless the operator explicitly",
            "asks for another change.",
            "If the operator asks you to update another artifact, do it and",
            "report which files changed and why.",
        ],
        STAGE_PLAN: [
            "Work with the operator on the implementation plan artifact.",
            "",
            f"Target file: {plan_path}.",
            f"Read only {requirements_path}, {design_path}, and",
            f"{plan_path} if they exist.",
            "Do not explore the working directory or inspect source code unless",
            "the operator explicitly asks you to.",
            f"Update only {plan_path} unless the operator",
            "explicitly asks for another change.",
            "If the operator asks you to update another artifact, do it and",
            "report which files changed and why.",
        ],
        STAGE_TEST_PLAN: [
            "Work with the operator on the system test plan artifact.",
            "",
            f"Target file: {test_plan_path}.",
            f"Read {requirements_path}, {design_path}, {plan_path}, and",
            f"{test_plan_path} if they exist.",
            "Do not explore the working directory or inspect source code unless",
            "the operator explicitly asks you to.",
            "Focus on system tests, workflow checks, manual validation,",
            "environment assumptions, and acceptance criteria.",
            f"Update only {test_plan_path} unless the operator explicitly asks",
            "for another change.",
            "If the operator asks you to update another artifact, do it and",
            "report which files changed and why.",
        ],
    }
    return "\n".join(prompts.get(stage, [f"Work with the operator on {stage}."]))


def _authoring_artifact_stages(store: StateStore) -> dict[str, str]:
    paths = _run_artifact_paths(store)
    return {
        paths.get(key, default_path): stage
        for default_path, stage in AUTHORING_ARTIFACT_STAGES.items()
        for key in [DEFAULT_PATH_KEYS.get(default_path)]
        if key is not None
    }


def _authoring_artifact_snapshot(store: StateStore) -> dict[str, bytes | None]:
    return {
        relative_path: _read_optional_bytes(store.root / relative_path)
        for relative_path in _authoring_artifact_stages(store)
    }


def _read_optional_bytes(path: Path) -> bytes | None:
    if not path.exists():
        return None
    return path.read_bytes()


def _changed_authoring_artifacts(
    store: StateStore,
    before: dict[str, bytes | None],
) -> list[str]:
    changed: list[str] = []
    for relative_path in sorted(_authoring_artifact_stages(store)):
        if _read_optional_bytes(store.root / relative_path) != before.get(relative_path):
            changed.append(relative_path)
    return changed


def _reopen_earliest_upstream_authoring_stage(
    store: StateStore,
    source_stage: str,
    changed_paths: list[str],
) -> bool:
    artifact_stages = _authoring_artifact_stages(store)
    target_stage = _earliest_upstream_authoring_stage(
        source_stage,
        changed_paths,
        artifact_stages,
    )
    if target_stage is None:
        return False

    upstream_paths = [
        path
        for path in changed_paths
        if artifact_stages.get(path) == target_stage
        or _is_stage_before(artifact_stages.get(path), source_stage)
    ]
    reason = (
        f"Authoring session for {source_stage} changed upstream artifact(s): "
        f"{', '.join(upstream_paths)}."
    )
    manifest = store.load_current_manifest()
    baseline, invalidated = _record_stage_reopen(
        store=store,
        manifest=manifest,
        target_stage=target_stage,
        reason=reason,
        actor="orchestrator",
        action="authoring-upstream-artifacts-reopened",
        summary="Reopened the earliest stage affected by authoring changes.",
    )
    print(f"reopened baseline: {baseline}")
    _print_list("upstream artifact changes", upstream_paths)
    _print_list("invalidated gates", invalidated)
    print(f"active stage: {target_stage}")
    target_artifact = _stage_required_file(store, target_stage)
    next_command = AUTHORING_APPROVAL_COMMANDS.get(target_stage)
    if target_artifact and next_command:
        print(f"next: review {target_artifact}, then run `{next_command}`")
    return True


def _earliest_upstream_authoring_stage(
    source_stage: str,
    changed_paths: list[str],
    artifact_stages: dict[str, str],
) -> str | None:
    candidates = [
        owner_stage
        for path in changed_paths
        for owner_stage in [artifact_stages.get(path)]
        if _is_stage_before(owner_stage, source_stage)
    ]
    if not candidates:
        return None
    return min(candidates, key=PUBLIC_STAGE_ORDER.index)


def _is_stage_before(stage: str | None, reference_stage: str) -> bool:
    if stage is None:
        return False
    try:
        return PUBLIC_STAGE_ORDER.index(stage) < PUBLIC_STAGE_ORDER.index(reference_stage)
    except ValueError:
        return False


PUBLIC_STAGE_BASELINES = {
    STAGE_REQUIREMENTS: "requirements",
    STAGE_DESIGN: "design",
    STAGE_PLAN: "plan",
    STAGE_IMPLEMENTATION: "implementation",
    STAGE_TEST_PLAN: "test-plan",
    STAGE_DOCS_REVIEW: "documentation",
}


PUBLIC_STAGE_ORDER = [
    STAGE_REQUIREMENTS,
    STAGE_DESIGN,
    STAGE_DESIGN_REVIEW,
    STAGE_DESIGN_ACCEPTANCE,
    STAGE_PLAN,
    STAGE_IMPLEMENTATION,
    STAGE_TEST_PLAN,
    STAGE_VALIDATION,
    STAGE_DOCS_REVIEW,
    STAGE_COMPLETE,
]


def _maybe_reopen_from_public_command(
    store: StateStore,
    manifest,
    target_stage: str,
    reason: str | None,
) -> bool:
    if not _is_backward_stage_request(manifest.active_stage, target_stage):
        return False
    if not reason:
        raise StateError("reopen reason is required")
    baseline, _invalidated = _record_stage_reopen(
        store=store,
        manifest=manifest,
        target_stage=target_stage,
        reason=reason,
        actor="human-operator",
        action="public-stage-reopened",
        summary=f"Reopened {PUBLIC_STAGE_BASELINES[target_stage]} through public stage command.",
    )
    print(f"reopened baseline: {baseline}")
    print(f"active stage: {target_stage}")
    return True


def _record_stage_reopen(
    store: StateStore,
    manifest,
    target_stage: str,
    reason: str,
    actor: str,
    action: str,
    summary: str,
) -> tuple[str, list[str]]:
    baseline = PUBLIC_STAGE_BASELINES[target_stage]
    request_id = f"CR-{len(store.read_change_requests()) + 1:04d}"
    invalidated = list(CHANGE_BASELINE_INVALIDATED_GATES[baseline])
    request = ChangeRequest(
        request_id=request_id,
        run_id=manifest.run_id,
        baseline=baseline,
        reason=reason,
        status="reopened",
        event="reopened",
        human_approved=True,
        reopened_stage=target_stage,
        invalidated_gates=invalidated,
    )
    store.append_change_request(request)
    for gate in invalidated:
        if gate not in manifest.invalidated_gates:
            manifest.invalidated_gates.append(gate)
    manifest.set_active_stage(target_stage)
    store.save_manifest(manifest)
    invalidated_snapshots = _invalidated_snapshot_refs(store, invalidated)
    store.append_baseline_invalidation(
        BaselineInvalidation(
            invalidation_id=f"INV-{len(store.read_baseline_invalidations()) + 1:04d}",
            change_request_id=request_id,
            baseline=baseline,
            invalidated_gates=invalidated,
            invalidated_snapshot_refs=invalidated_snapshots,
        )
    )
    store.append_decision(
        DecisionRecord(
            decision_id=f"CHANGE-{len(store.read_decisions()) + 1:04d}",
            stage=target_stage,
            summary=f"Reopened {baseline} baseline",
            rationale=reason,
        )
    )
    store.append_activity(
        ActivityEvent(
            actor=actor,
            stage=target_stage,
            action=action,
            summary=summary,
            outputs=["change-requests.jsonl", "baseline-invalidations.jsonl"],
        )
    )
    return baseline, invalidated


def _is_backward_stage_request(active_stage: str, target_stage: str) -> bool:
    try:
        active_index = PUBLIC_STAGE_ORDER.index(active_stage)
        target_index = PUBLIC_STAGE_ORDER.index(target_stage)
    except ValueError:
        return False
    return target_index < active_index


def _print_progress(label: str, message: str) -> None:
    try:
        from rich.console import Console
    except Exception:
        print(f"{label}: {message}")
        return
    Console().print(f"[bold]{label}[/bold]: {message}")


@contextmanager
def _progress_step(label: str, message: str) -> Iterator[None]:
    try:
        from rich.console import Console
    except Exception:
        print(f"{label}: {message}")
        yield
        return

    console = Console()
    if not console.is_terminal:
        console.print(f"[bold]{label}[/bold]: {message}")
        yield
        return

    with console.status(f"[bold]{label}[/bold]: {message}", spinner="dots"):
        yield


def _cmd_report(
    store: StateStore,
    engine: GateEngine,
    args: argparse.Namespace,
) -> int:
    if args.report_command == "summary":
        text = _format_run_summary(store, engine)
        return _write_or_print_report(store.root, text, args.output)

    if args.report_command == "trace":
        text = _format_activity_trace(store)
        return _write_or_print_report(store.root, text, args.output)

    return 2


def _cmd_set_stage(store: StateStore, args: argparse.Namespace) -> int:
    if not args.force:
        raise StateError("stage changes require --force")
    _force_reset_to_stage(store, args.stage, args.reason)
    return 0


def _cmd_stage(
    store: StateStore,
    engine: GateEngine,
    args: argparse.Namespace,
) -> int:
    stage = args.stage
    forced = getattr(args, "force", False)
    manifest = store.load_current_manifest()
    if forced:
        _force_reset_to_stage(store, stage, getattr(args, "reason", None))
        manifest = store.load_current_manifest()
        print("forced approval: yes")
    else:
        order = engine.stage_order(stage, manifest)
        if not order.passed:
            _print_gate_failure(order.messages)
            return 1

    required_file = _stage_required_file(store, stage)
    if required_file:
        file_result = engine.require_file(required_file)
        if not file_result.passed:
            _print_gate_failure(file_result.messages)
            return 1
    approval_errors = _record_stage_approvals(store, stage, args)
    if approval_errors:
        _print_gate_failure(approval_errors)
        return 1
    if not forced and stage == STAGE_IMPLEMENTATION:
        phase_status = store.load_phase_status()
        if phase_status.active_phase is not None:
            _print_gate_failure(["active implementation phase is not committed"])
            return 1
        missing_phases = _uncommitted_planned_phases(store)
        if missing_phases:
            _print_gate_failure(
                [
                    "planned phases are not committed: "
                    + ", ".join(str(phase) for phase in missing_phases)
                ]
            )
            return 1

    baseline_paths = _approval_baseline_artifacts(store, stage)
    if baseline_paths:
        with _progress_step(stage, "committing approved baseline artifacts"):
            commit_sha, commit_error = _commit_approval_baseline(
                store,
                stage,
                baseline_paths,
            )
        if commit_error:
            print(f"error: {commit_error}", file=sys.stderr)
            return 1
        print(f"baseline commit: {commit_sha}")

    completed_gate = STAGE_COMPLETED_GATES.get(stage)
    if stage == STAGE_DESIGN_REVIEW:
        blocking = _blocking_issues(store, "design-review.jsonl")
        if blocking and not forced:
            _print_gate_failure(["blocking design review issues remain"])
            return 1
    if completed_gate:
        manifest.complete_gate(completed_gate)

    next_stage = NEXT_STAGE.get(stage)
    if next_stage:
        manifest.set_active_stage(next_stage)
    store.save_manifest(manifest)
    snapshot_artifact = _stage_snapshot_artifact(store, stage)
    if snapshot_artifact:
        snapshot = ArtifactManager(store.root).snapshot(
            manifest.run_id,
            snapshot_artifact,
            f"{stage}-approved",
        )
        store.append_artifact_snapshot(snapshot)
        store.append_activity(
            ActivityEvent(
                actor="orchestrator",
                stage=stage,
                action="artifact-snapshotted",
                summary=f"Snapshotted {snapshot_artifact}.",
                artifact_snapshot_refs=[snapshot.snapshot_path],
                outputs=[snapshot.snapshot_path],
            )
        )
    store.append_activity(
        ActivityEvent(
            actor="orchestrator",
            stage=stage,
            gate=completed_gate,
            action="stage-completed",
            summary=f"Completed stage {stage}.",
            status="pass",
        )
    )
    print(f"completed stage: {stage}")
    print(f"active stage: {manifest.active_stage}")
    return 0


def _stage_readiness_errors(
    engine: GateEngine,
    manifest,
    stage: str,
) -> list[str]:
    order = engine.stage_order(stage, manifest)
    if not order.passed:
        return order.messages
    required_file = _stage_required_file(engine.store, stage)
    if required_file:
        file_result = engine.require_file(required_file)
        if not file_result.passed:
            return file_result.messages
    return []


def _cmd_phase(
    store: StateStore,
    engine: GateEngine,
    args: argparse.Namespace,
) -> int:
    if args.phase_command == "commit":
        manifest = store.load_current_manifest()
        status = store.load_phase_status()
        if status.active_phase != args.phase:
            print("error: requested phase is not active", file=sys.stderr)
            return 1
        result = engine.evaluate(GATE_COMMIT, manifest)
        if not result.passed:
            _print_gate_failure(result.messages)
            return 1
        if not args.sha:
            print("error: --sha is required", file=sys.stderr)
            return 1
        phase = status.phases.setdefault(str(args.phase), {})
        error = _phase_commit_validation_error(
            store,
            args.sha,
            args.phase,
            phase,
        )
        if error:
            print(f"error: {error}", file=sys.stderr)
            return 1
        _record_phase_commit(store, manifest, args.phase, args.sha)
        print(f"committed phase: {args.phase}")
        return 0

    return 2


def _cmd_validate(
    store: StateStore,
    engine: GateEngine,
    args: argparse.Namespace,
) -> int:
    manifest = store.load_current_manifest()
    forced = getattr(args, "force", False)
    if forced:
        _force_reset_to_stage(store, STAGE_VALIDATION, None)
        manifest = store.load_current_manifest()
    if manifest.active_stage != STAGE_VALIDATION:
        print("error: active stage is not validation", file=sys.stderr)
        return 1
    order = engine.stage_order(STAGE_VALIDATION, manifest)
    if not order.passed:
        _print_gate_failure(order.messages)
        return 1
    missing_phases = _uncommitted_planned_phases(store)
    if missing_phases and not forced:
        _print_gate_failure(
            [
                "planned phases are not committed: "
                + ", ".join(str(phase) for phase in missing_phases)
            ]
        )
        return 1

    commands = _validation_commands(store, args)
    results = [
        _run_validation_command(store.root, command, shell=shell)
        for command, shell, _source in commands
    ]
    for result, (_command, _shell, source) in zip(results, commands, strict=True):
        result["source"] = source
    report_path = _write_validation_report(store, results)
    store.write_raw_event("validation-results", results)

    failures = [result for result in results if result["returncode"] != 0]
    if failures:
        existing = store.read_review_issues("validation-review.jsonl")
        for offset, result in enumerate(failures, start=1):
            issue = ReviewIssue(
                issue_id=f"VAL-{len(existing) + offset:04d}",
                source="validation-testing",
                severity="blocker",
                status="open",
                summary=f"Validation command failed: {result['command']}",
                stage=STAGE_VALIDATION,
                artifact=_artifact_path(store, VALIDATION_REPORT_PATH),
                requested_change="Fix the failing validation command.",
            )
            store.append_review_issue("validation-review.jsonl", issue)
        store.append_activity(
            ActivityEvent(
                actor="test-review-agent",
                stage=STAGE_VALIDATION,
                action="validation-failed",
                summary=f"Validation failed; report written to {report_path}.",
                status="blocked",
                outputs=["validation-review.jsonl", str(report_path)],
                commands=[str(result["command"]) for result in results],
            )
        )
        print("validation: failed")
        print(f"report: {report_path}")
        _open_validation_fix_phase(store, manifest)
        return 1

    if _blocking_issues(store, "validation-review.jsonl"):
        _print_gate_failure(["blocking validation review issues remain"])
        return 1

    manifest.complete_gate(GATE_VALIDATION_TESTING)
    store.save_manifest(manifest)
    store.append_activity(
        ActivityEvent(
            actor="test-review-agent",
            stage=STAGE_VALIDATION,
            gate=GATE_VALIDATION_TESTING,
            action="validation-passed",
            summary=f"Validation passed; report written to {report_path}.",
            status="pass",
            outputs=[str(report_path)],
            commands=[str(result["command"]) for result in results],
        )
    )
    print("validation: passed")
    print(f"active stage: {manifest.active_stage}")
    print(f"report: {report_path}")
    print("next: run `electroboy validation-approve`")
    return 0


def _cmd_validation_approve(store: StateStore, args: argparse.Namespace) -> int:
    manifest = store.load_current_manifest()
    forced = getattr(args, "force", False)
    if forced:
        _force_reset_to_stage(
            store,
            STAGE_VALIDATION,
            getattr(args, "reason", None),
        )
        manifest = store.load_current_manifest()
        manifest.complete_gate(GATE_VALIDATION_TESTING)
        store.save_manifest(manifest)
    if manifest.active_stage != STAGE_VALIDATION:
        print("error: active stage is not validation", file=sys.stderr)
        return 1
    if not manifest.has_gate(GATE_VALIDATION_TESTING):
        _print_gate_failure(["validation testing has not passed"])
        return 1
    blocking = _blocking_issues(store, "validation-review.jsonl")
    if blocking and not forced:
        _print_gate_failure(["blocking validation review issues remain"])
        return 1

    baseline_paths = _approval_baseline_artifacts(store, STAGE_VALIDATION) or []
    with _progress_step("validation", "committing validation reports"):
        commit_sha, commit_error = _commit_approval_baseline(
            store,
            STAGE_VALIDATION,
            baseline_paths,
        )
    if commit_error:
        print(f"error: {commit_error}", file=sys.stderr)
        return 1

    manifest.set_active_stage(STAGE_DOCS_REVIEW)
    store.save_manifest(manifest)
    store.append_activity(
        ActivityEvent(
            actor="human-operator",
            stage=STAGE_VALIDATION,
            gate=GATE_VALIDATION_TESTING,
            action="validation-approved",
            summary="Human operator approved validation handoff artifacts.",
            status="pass",
            outputs=baseline_paths,
            commit=commit_sha,
        )
    )
    print("validation approved")
    print(f"baseline commit: {commit_sha}")
    print(f"active stage: {manifest.active_stage}")
    return 0


def _cmd_docs_review(store: StateStore, engine: GateEngine) -> int:
    manifest = store.load_current_manifest()
    order = engine.stage_order(STAGE_DOCS_REVIEW, manifest)
    if not order.passed:
        _print_gate_failure(order.messages)
        return 1

    documentation_files = _documentation_review_files(store)
    missing = [
        relative_path
        for relative_path in documentation_files
        if not (store.root / relative_path).exists()
    ]
    _verify_restored_documentation_files(store, missing)
    if missing:
        _append_missing_documentation_issues(store, missing)
        store.append_activity(
            ActivityEvent(
                actor="documentation-agent",
                stage=STAGE_DOCS_REVIEW,
                action="documentation-review-failed",
                summary="Documentation review failed because files are missing.",
                status="blocked",
                outputs=["documentation-review.jsonl"],
            )
        )
        print("documentation review: failed")
        for relative_path in missing:
            print(f"missing: {relative_path}")
        return 1

    blocking = _blocking_issues(store, "documentation-review.jsonl")
    if blocking:
        _print_gate_failure(["blocking documentation review issues remain"])
        return 1
    semantic_errors = _documentation_semantic_errors(store.root)
    if semantic_errors:
        _append_documentation_content_issues(store, semantic_errors)
        _print_gate_failure(semantic_errors)
        return 1

    manager = ArtifactManager(store.root)
    event_id = f"documentation-review-{len(manifest.completed_gates) + 1}"
    snapshot_refs: list[str] = []
    for relative_path in documentation_files:
        snapshot = manager.snapshot(manifest.run_id, relative_path, event_id)
        store.append_artifact_snapshot(snapshot)
        snapshot_refs.append(snapshot.snapshot_path)

    manifest.complete_gate(GATE_DOCUMENTATION)
    manifest.set_active_stage(STAGE_COMPLETE)
    store.save_manifest(manifest)
    store.append_activity(
        ActivityEvent(
            actor="documentation-agent",
            stage=STAGE_DOCS_REVIEW,
            gate=GATE_DOCUMENTATION,
            action="documentation-review-passed",
            summary="Documentation review passed and final docs were snapshotted.",
            status="pass",
            artifact_snapshot_refs=snapshot_refs,
        )
    )
    print("documentation review: passed")
    print(f"active stage: {manifest.active_stage}")
    return 0


def _invoke_agent_role(
    store: StateStore,
    role: str,
    prompt: str,
    context_paths: list[str],
    session_stage: str | None = None,
    session_artifact: str | None = None,
    explicit_session_id: str | None = None,
    issue_file_override: str | None = None,
) -> tuple[AgentResult, str, str | None]:
    manifest = store.load_current_manifest()
    event_id = f"agent-{len(store.read_activity()) + 1:05d}"
    session_record = (
        store.read_session_record(session_stage, role) if session_stage else None
    )
    provider_session_id = _explicit_session_id(explicit_session_id)
    if session_stage and provider_session_id:
        _write_attached_agent_session_record(
            store,
            session_stage,
            role,
            session_artifact,
            event_id,
            provider_session_id,
        )
    if provider_session_id is None:
        provider_session_id = _session_provider_session_id(session_record)
    if session_stage and session_record and not provider_session_id:
        prompt = _prompt_with_session_recovery(
            store,
            prompt,
            session_stage,
            role,
            session_artifact,
            session_record,
        )
    prompt = _prompt_with_feature_branch_guard(store, role, prompt)
    output_schema = _agent_output_schema(role)
    if output_schema is not None:
        prompt = _prompt_with_output_contract(prompt)
    progress_path = _agent_progress_file(role, store)
    progress_context_path: str | None = None
    if progress_path:
        _init_agent_progress_file(store, role, progress_path, event_id)
        progress_context_path = _execution_context_paths(store, [progress_path])[0]
        print(f"progress: {progress_context_path}")
        prompt = _prompt_with_agent_progress(prompt, progress_context_path)
    execution_context_paths = _execution_context_paths(store, context_paths)
    prompt = _prompt_with_meta_context(store, prompt, execution_context_paths)
    invocation = AgentInvocation(
        role=role,
        prompt=prompt,
        context_paths=execution_context_paths,
        output_schema=output_schema,
        provider_session_id=provider_session_id,
        progress_path=progress_context_path,
        progress_idle_timeout=(
            AGENT_PROGRESS_IDLE_TIMEOUT_SECONDS if progress_context_path else None
        ),
    )
    try:
        runtime = runtime_for_role(
            role,
            store.root,
            execution_root=store.execution_root,
        )
        result = runtime.invoke(invocation)
        if output_schema is not None and _runtime_enforces_output_contract(runtime):
            result = _enforce_agent_output_contract(role, result)
    except Exception as error:
        result = _failed_agent_result(str(error))
    if session_stage:
        _write_agent_session_record(
            store,
            session_stage,
            role,
            session_artifact,
            event_id,
            invocation,
            result,
            session_record,
        )
    store.write_message(f"{event_id}-prompt", invocation.prompt)
    store.write_message(f"{event_id}-response", result.final_message)
    store.write_raw_event(event_id, result.raw_events)
    issue_file = issue_file_override or _agent_issue_file(role, store)
    linked_issue_ids: list[str] = []
    if issue_file:
        linked_issue_ids = _store_agent_issues(
            store,
            issue_file,
            role,
            result.issues,
        )
    outputs = [progress_path] if progress_path else []
    if issue_file and linked_issue_ids:
        outputs.append(issue_file)
    store.append_activity(
        ActivityEvent(
            actor=role,
            stage=manifest.active_stage,
            action="agent-invoked",
            summary=f"Invoked agent role {role}.",
            status="pass" if result.ok else "blocked",
            linked_issue_ids=linked_issue_ids,
            inputs=list(invocation.context_paths),
            outputs=outputs,
            artifact_changes=_agent_reported_files(result),
            commands=list(result.commands),
            message_ref=f"messages/{event_id}-response.md",
        )
    )
    return result, event_id, issue_file


def _prompt_with_feature_branch_guard(
    store: StateStore,
    role: str,
    prompt: str,
) -> str:
    if role not in MUTATING_AGENT_ROLES:
        return prompt
    branch = _active_feature_branch(store)
    if not branch:
        return prompt
    lines = [
        "Feature branch guard:",
        "",
        f"- Active feature branch: {branch}",
        "- Before modifying files in any git repository, verify that",
        "  repository's current branch.",
        "- This applies to the active target repository and to nested",
        "  repositories you edit, such as subdirectories with their own .git",
        "  directory.",
        f"- If the branch exists, switch with: git switch {branch}",
        f"- If the branch does not exist, create it with: git switch -c {branch}",
        "- Do not use force checkout or discard tracked changes. If switching",
        "  would overwrite tracked work, stop and report the repository path and",
        "  branch mismatch.",
        "- Untracked files alone do not block switching.",
        "",
        prompt,
    ]
    return "\n".join(lines)


def _active_feature_branch(store: StateStore) -> str | None:
    run_id = store.current_run_id()
    if not run_id:
        return None
    record = read_feature_record(store.root, run_id)
    if not record:
        return None
    branch = record.get("branch")
    if not isinstance(branch, str) or not branch.strip():
        return None
    return branch.strip()


def _prompt_with_meta_context(
    store: StateStore,
    prompt: str,
    context_paths: list[str],
) -> str:
    if store.meta_project_root is None:
        return prompt
    target_prefix = _path_from_execution_root(store, store.root)
    lines = [
        "Meta-project context:",
        "",
        f"- Meta-project root: {store.meta_project_root}",
        f"- Agent working directory: {store.execution_root}",
        f"- Active target repository: {store.target_name or store.root.name}",
        f"- Target repository path: {store.root}",
        f"- Target repository from working directory: {target_prefix}",
        "",
        "Stage artifacts belong to the active target repository. When a stage",
        "instruction mentions docs/... or another relative path, interpret it",
        f"relative to {target_prefix} unless the operator says otherwise.",
        "",
        "Registered repositories:",
        *_markdown_list(_registered_repository_lines(store)),
        "",
        "Context paths from the agent working directory:",
        *_markdown_list(context_paths),
        "",
        prompt,
    ]
    return "\n".join(lines)


def _execution_context_paths(
    store: StateStore,
    context_paths: list[str],
) -> list[str]:
    if store.meta_project_root is None:
        return context_paths
    target_prefix = _path_from_execution_root(store, store.root)
    return [
        _join_context_path(target_prefix, path)
        for path in context_paths
    ]


def _join_context_path(prefix: str, path: str) -> str:
    if Path(path).is_absolute() or prefix == ".":
        return path
    return f"{prefix.rstrip('/')}/{path}"


def _prompt_with_agent_progress(prompt: str, progress_path: str) -> str:
    lines = [
        prompt.rstrip(),
        "",
        "Progress reporting:",
        f"Progress file: {progress_path}",
        "- Append one concise Markdown line to the progress file before each",
        "  meaningful step.",
        "- Keep progress updates factual and short; do not include detailed",
        "  reasoning.",
        "- Update the progress file at least every few minutes while running.",
        "- Do not overwrite the progress file.",
        "- If this role otherwise says not to modify files, the progress file is",
        "  the only extra file you may modify.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _agent_output_schema(role: str) -> dict[str, object] | None:
    if role in REVIEW_OUTPUT_CONTRACT_ROLES:
        return REVIEW_OUTPUT_SCHEMA
    return None


def _prompt_with_output_contract(prompt: str) -> str:
    lines = [
        prompt.rstrip(),
        "",
        "Structured output contract:",
        "- Your final response must be exactly one JSON object.",
        "- Do not wrap the JSON in Markdown fences or add prose outside it.",
        "- Use this shape:",
        "{",
        '  "ok": true,',
        '  "final_message": "short human-readable review summary",',
        '  "issues": [',
        "    {",
        '      "issue_id": "DR-001",',
        '      "severity": "major",',
        '      "status": "open",',
        '      "summary": "Design omits admission hold semantics.",',
        '      "commit": "optional commit SHA for range reviews",',
        '      "artifact": "docs/detailed-design.md",',
        '      "location": "docs/detailed-design.md:1060",',
        '      "rationale": "Why this blocks safe implementation.",',
        '      "requested_change": "Specify the consume/return/record sequence."',
        "    }",
        "  ]",
        "}",
        "- Use an empty issues array when there are no findings.",
        "- Valid severities are blocker, major, and minor.",
        "- Valid statuses are open, accepted, fixed, verified, rejected,",
        "  deferred, and escalated.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _runtime_enforces_output_contract(runtime: object) -> bool:
    config = getattr(runtime, "config", None)
    adapter = getattr(config, "adapter", None)
    return adapter != "manual"


def _enforce_agent_output_contract(
    role: str,
    result: AgentResult,
) -> AgentResult:
    errors = _review_output_contract_errors(result)
    if not errors:
        return _normalized_review_contract_result(result)
    message = (
        f"Agent output contract failed for {role}: "
        + "; ".join(errors)
        + "\n\nRaw response:\n"
        + (result.final_message or "")
    )
    return AgentResult(
        ok=False,
        final_message=message,
        issues=[],
        raw_events=[
            *result.raw_events,
            {
                "error": "review output contract failed",
                "messages": errors,
                "structured_payload": result.structured_payload,
                "raw_final_message": result.final_message,
            },
        ],
        changed_files=result.changed_files,
        created_files=result.created_files,
        commands=result.commands,
        commit_message=result.commit_message,
        error="review output contract failed",
        provider=result.provider,
        provider_session_id=result.provider_session_id,
        resumed_session=result.resumed_session,
        structured_output=result.structured_output,
        structured_payload=result.structured_payload,
    )


def _review_output_contract_errors(result: AgentResult) -> list[str]:
    payload = result.structured_payload
    if not result.structured_output or payload is None:
        return ["final response was not a structured JSON object"]
    errors: list[str] = []
    if not isinstance(payload.get("ok"), bool):
        errors.append("ok must be a boolean")
    final_message = payload.get("final_message")
    if not isinstance(final_message, str) or not final_message.strip():
        errors.append("final_message must be a non-empty string")
    issues = payload.get("issues")
    if not isinstance(issues, list):
        errors.append("issues must be an array")
        return errors
    for index, issue in enumerate(issues, start=1):
        errors.extend(_review_issue_contract_errors(issue, index))
    return errors


def _review_issue_contract_errors(issue: object, index: int) -> list[str]:
    if not isinstance(issue, dict):
        return [f"issues[{index}] must be an object"]
    errors: list[str] = []
    for key in ("issue_id", "severity", "status", "summary"):
        value = issue.get(key)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"issues[{index}].{key} must be a non-empty string")
    severity = issue.get("severity")
    if isinstance(severity, str) and severity not in REVIEW_OUTPUT_SEVERITIES:
        errors.append(
            f"issues[{index}].severity must be one of "
            f"{', '.join(sorted(REVIEW_OUTPUT_SEVERITIES))}"
        )
    status = issue.get("status")
    if isinstance(status, str) and status not in REVIEW_OUTPUT_STATUSES:
        errors.append(
            f"issues[{index}].status must be one of "
            f"{', '.join(sorted(REVIEW_OUTPUT_STATUSES))}"
        )
    for key in ("artifact", "commit", "location", "rationale", "requested_change"):
        value = issue.get(key)
        if value is not None and not isinstance(value, str):
            errors.append(f"issues[{index}].{key} must be a string when present")
    return errors


def _normalized_review_contract_result(result: AgentResult) -> AgentResult:
    payload = result.structured_payload or {}
    issues = payload.get("issues")
    normalized_issues = [
        dict(issue)
        for issue in issues
        if isinstance(issue, dict)
    ] if isinstance(issues, list) else []
    result.ok = bool(payload.get("ok"))
    result.final_message = str(payload.get("final_message", ""))
    result.issues = normalized_issues
    return result


def _path_from_execution_root(store: StateStore, path: Path) -> str:
    try:
        relative = os.path.relpath(path, store.execution_root)
    except ValueError:
        return str(path)
    if relative == ".":
        return "."
    if relative == ".." or relative.startswith(f"..{os.sep}"):
        return str(path)
    return Path(relative).as_posix()


def _registered_repository_lines(store: StateStore) -> list[str]:
    return [
        f"{repo.get('name')}: {repo.get('path')}"
        for repo in store.registered_repositories
    ]


def _explicit_session_id(session_id: str | None) -> str | None:
    if session_id is None:
        return None
    session_id = session_id.strip()
    return session_id or None


def _session_provider_session_id(record: dict[str, object] | None) -> str | None:
    if not record:
        return None
    value = record.get("session_id") or record.get("provider_session_id")
    return value if isinstance(value, str) and value else None


def _prompt_with_session_recovery(
    store: StateStore,
    prompt: str,
    stage: str,
    role: str,
    artifact: str | None,
    session_record: dict[str, object] | None,
) -> str:
    lines = [prompt.rstrip(), "", "Session recovery context:"]
    summary = store.read_session_summary(stage, role)
    if summary:
        lines.extend(["", "Last shared session summary:", summary.strip()])
    if session_record:
        lines.extend(
            [
                "",
                "Previous local session record:",
                f"- status: {session_record.get('status', 'unknown')}",
                f"- last seen: {session_record.get('last_seen_at', 'unknown')}",
                f"- last event: {session_record.get('last_event_id', 'unknown')}",
            ]
        )
    artifact_text = _session_recovery_artifact_text(store.root, artifact)
    if artifact_text:
        lines.extend(["", f"Current {artifact}:", artifact_text])
    lines.extend(
        [
            "",
            "Continue the authoring work from this context. Promote any",
            "project-relevant decisions into the target artifact before asking",
            "for approval.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _session_recovery_artifact_text(root: Path, artifact: str | None) -> str:
    if not artifact:
        return ""
    path = root / artifact
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8").strip()
    if len(text) > 4000:
        return f"{text[:4000]}\n[truncated]"
    return text


def _write_agent_session_record(
    store: StateStore,
    stage: str,
    role: str,
    artifact: str | None,
    event_id: str,
    invocation: AgentInvocation,
    result: AgentResult,
    previous: dict[str, object] | None,
) -> None:
    now = utc_now()
    session_id = result.provider_session_id or invocation.provider_session_id
    provider = result.provider
    if provider is None and previous:
        previous_provider = previous.get("provider")
        provider = previous_provider if isinstance(previous_provider, str) else None
    started_at = now
    if previous and previous.get("session_id") == session_id:
        previous_started = previous.get("started_at")
        if isinstance(previous_started, str):
            started_at = previous_started
    manifest = store.load_current_manifest()
    store.write_session_record(
        stage,
        role,
        {
            "provider": provider,
            "session_id": session_id,
            "stage": stage,
            "role": role,
            "run_id": manifest.run_id,
            "status": "completed" if result.ok else "interrupted",
            "started_at": started_at,
            "last_seen_at": now,
            "cwd": str(store.root),
            "artifact": artifact,
            "last_event_id": event_id,
            "message_ref": f"messages/{event_id}-response.md",
            "resumed_session": (
                result.resumed_session or invocation.provider_session_id is not None
            ),
        },
    )


def _write_attached_agent_session_record(
    store: StateStore,
    stage: str,
    role: str,
    artifact: str | None,
    event_id: str,
    session_id: str,
) -> None:
    now = utc_now()
    manifest = store.load_current_manifest()
    store.write_session_record(
        stage,
        role,
        {
            "provider": None,
            "session_id": session_id,
            "stage": stage,
            "role": role,
            "run_id": manifest.run_id,
            "status": "attached",
            "started_at": now,
            "last_seen_at": now,
            "cwd": str(store.root),
            "artifact": artifact,
            "last_event_id": event_id,
            "message_ref": f"messages/{event_id}-response.md",
            "resumed_session": True,
        },
    )


def _design_review_context_paths(store: StateStore) -> list[str]:
    return _artifact_paths(
        store,
        [
            *DESIGN_REVIEW_CONTEXT_PATHS,
            DESIGN_REVIEW_SUMMARY_PATH,
            DESIGN_REVIEW_UPDATES_PATH,
        ],
    )


def _design_review_prompt(store: StateStore, pass_number: int) -> str:
    requirements_path = _artifact_path(store, "docs/requirements.md")
    design_path = _artifact_path(store, "docs/detailed-design.md")
    summary_path = _artifact_path(store, DESIGN_REVIEW_SUMMARY_PATH)
    updates_path = _artifact_path(store, DESIGN_REVIEW_UPDATES_PATH)
    return "\n".join(
        [
            f"Review {design_path} against {requirements_path} and the current",
            "codebase.",
            "",
            f"Read {requirements_path} and {design_path}.",
            f"Read {summary_path} and {updates_path} when they exist so you can",
            "verify prior design-review updates.",
            "Inspect source code as needed to verify the design matches the current",
            "implementation context, especially for feature work and bug fixes.",
            "Do not modify files.",
            "Report blocker and major findings as structured review issues.",
            "For previously reported findings that are now resolved, report a",
            "structured issue with the original issue_id and status verified.",
            "If files need to change, report the requested change as an issue.",
            f"This is design review pass {pass_number}.",
        ]
    )


def _design_review_update_prompt(
    store: StateStore,
    issue_file: str,
    summary_path: str,
    blocking: list[dict[str, object]],
    pass_number: int,
) -> str:
    requirements_path = _artifact_path(store, "docs/requirements.md")
    design_path = _artifact_path(store, "docs/detailed-design.md")
    updates_path = _artifact_path(store, DESIGN_REVIEW_UPDATES_PATH)
    lines = [
        f"Update {design_path} to address blocking design-review findings.",
        "",
        f"Use {requirements_path}, {design_path}, {summary_path}, and",
        f"{updates_path} as context.",
        "Inspect source code as needed to keep the design aligned with the",
        "current implementation context.",
        f"Modify only {design_path}.",
        f"Do not edit {summary_path}, {updates_path}, or {issue_file}.",
        "ElectroBoy will update the review-update log after this turn.",
        "",
        "Blocking findings to address:",
        "",
        *_markdown_list(_design_review_issue_lines(blocking)),
        "",
        "Report the design changes made and why. If your runtime supports",
        "structured output, include changed_files.",
        f"This update follows design review pass {pass_number}.",
    ]
    return "\n".join(lines)


def _implementation_context_paths(store: StateStore) -> list[str]:
    return _artifact_paths(
        store,
        [
            "docs/requirements.md",
            "docs/detailed-design.md",
            "docs/implementation-plan.md",
            TEST_PLAN_PATH,
        ],
    )


def _coding_prompt(
    store: StateStore,
    phase_number: int,
    attempt: int = 1,
    review_kind: str | None = None,
    issue_file: str | None = None,
    summary_path: str | None = None,
    operator_messages: list[str] | None = None,
) -> str:
    requirements_path, design_path, plan_path, test_plan_path = (
        _implementation_context_paths(store)
    )
    lines = [
        f"Implement phase {phase_number} from {plan_path}.",
        "",
        f"Use {requirements_path}, {design_path}, {plan_path}, and",
        f"{test_plan_path} when present as the approved context.",
        "Continue from the current working tree. If an earlier run stopped in",
        "the middle, inspect the current state and continue the implementation",
        "instead of restarting from scratch.",
    ]
    if issue_file and summary_path:
        review_label = "test review" if review_kind == "test_review" else "code review"
        lines.extend(
            [
                "",
                f"This is implementation pass {attempt} with {review_label} context.",
                f"Use {summary_path} and internal issue file {issue_file} to",
                "address remaining blocker and major findings.",
                "Minor findings are non-blocking follow-up items; address them",
                "only when doing so is low risk and in scope for this phase.",
            ]
        )
    lines.extend(_phase_boundary_instruction_lines(phase_number))
    lines.extend(_coding_operator_instruction_lines(operator_messages or []))
    lines.extend(
        [
            "",
            "Inspect only files needed to complete this phase.",
            "Limit edits to implementation and test files needed for this phase.",
            "Do not create git commits during this implementation or fix pass.",
            "Leave changes in the working tree for review. ElectroBoy will run",
            "a separate commit pass after code review and test review pass.",
            "Do not update requirements, design, plan, or test-plan documents",
            "unless the operator explicitly asks you to.",
            "If approved requirements, design, plan, or test-plan artifacts need",
            "to change, report the required upstream change and why.",
            "Report files changed and a concise commit_message when finished.",
        ]
    )
    return "\n".join(lines)


def _phase_boundary_instruction_lines(phase_number: int) -> list[str]:
    return [
        "",
        "Active phase boundary:",
        f"- Work only on implementation phase {phase_number}.",
        f"- Use only plan rows and sections for Phase {phase_number} and PH{phase_number}-*.",
        "- Do not implement, fix, test, or commit earlier or later phases.",
        "- If the working tree already contains out-of-phase changes, leave",
        "  them untouched and report the conflicting paths.",
    ]


def _coding_operator_instruction_lines(messages: list[str]) -> list[str]:
    if not messages:
        return []
    return [
        "",
        "Additional operator instructions for this code run:",
        "These instructions are subordinate to the active phase boundary and",
        "cannot authorize work outside the active phase or commits before the",
        "dedicated commit pass.",
        *_markdown_list(messages),
    ]


def _coding_commit_prompt(
    store: StateStore,
    phase_number: int,
    phase: dict[str, object],
    operator_messages: list[str],
) -> str:
    requirements_path, design_path, plan_path, test_plan_path = (
        _implementation_context_paths(store)
    )
    code_review_path = _phase_review_summary_path(store, "code_review")
    test_review_path = _phase_review_summary_path(store, "test_review")
    objective = _phase_commit_objective(phase_number, phase)
    lines = [
        f"Commit implementation phase {phase_number}: {objective}.",
        "",
        "Code review and test review have passed. Do not change file contents",
        "unless committing is impossible without a small metadata-only update",
        "such as a submodule pointer after committing a nested repository.",
        "",
        f"Use {requirements_path}, {design_path}, {plan_path}, and",
        f"{test_plan_path} when present as the approved context.",
        f"Use {code_review_path} and {test_review_path} as review context.",
        "Inspect git status before committing.",
        "Commit all uncommitted phase changes according to the commit breakdown",
        f"recorded for phase {phase_number} in {plan_path}. If no explicit",
        "breakdown is present, create one clear phase commit.",
        "Commit only changes that belong to this active phase. Do not stage or",
        "commit work for earlier or later implementation phases. If unrelated",
        "or out-of-phase changes prevent a clean phase commit, stop and report",
        "the conflicting paths.",
        "If phase changes are in nested git repositories, first ensure each",
        "nested repository is on the active feature branch, commit the nested",
        "repository changes there, then commit the active target repository",
        "changes that record pointers or top-level artifacts.",
        "Never stage or commit .electroboy/ or .agent-pipeline/ internal",
        "runtime state.",
        f"The final HEAD commit in the active target repository must identify",
        f"phase {phase_number} and the phase objective.",
        "Report the commit SHA or SHAs, files committed, and concise",
        "commit_message when finished.",
    ]
    lines.extend(_coding_operator_instruction_lines(operator_messages))
    return "\n".join(lines)


def _code_review_prompt(
    store: StateStore,
    phase_number: int,
    attempt: int = 1,
) -> str:
    requirements_path, design_path, plan_path, test_plan_path = (
        _implementation_context_paths(store)
    )
    return "\n".join(
        [
            f"Review implementation phase {phase_number}, attempt {attempt}.",
            "",
            f"Use {requirements_path}, {design_path}, {plan_path}, and",
            f"{test_plan_path} when present as the approved context.",
            "Review only the changes relevant to this phase.",
            "Treat implemented or committed work for another implementation",
            "phase as a blocker finding.",
            "Do not modify files.",
            "Classify every finding as blocker, major, or minor.",
            "Blocker and major findings are blocking. Minor findings are",
            "non-blocking follow-up items.",
            "Report every finding, including minor findings, as structured",
            "review issues.",
            "If a previously reported issue is fixed, report the same issue_id",
            "with status verified.",
            "Set ok to true when the review completes successfully, even when",
            "you report findings. Set ok to false only when the review itself",
            "cannot be completed.",
        ]
    )


def _test_review_prompt(
    store: StateStore,
    phase_number: int,
    attempt: int = 1,
) -> str:
    requirements_path, design_path, plan_path, test_plan_path = (
        _implementation_context_paths(store)
    )
    return "\n".join(
        [
            f"Review tests for implementation phase {phase_number}, attempt {attempt}.",
            "",
            f"Use {requirements_path}, {design_path}, {plan_path}, and",
            f"{test_plan_path} when present as the approved context.",
            "Inspect tests and test results relevant to this phase.",
            "Treat tests or implementation changes for another implementation",
            "phase as a blocker finding.",
            "Do not modify files.",
            "Classify every finding as blocker, major, or minor.",
            "Blocker and major findings are blocking. Minor findings are",
            "non-blocking follow-up items.",
            "Report missing, failing, or weak coverage as structured review",
            "issues.",
            "If a previously reported issue is fixed, report the same issue_id",
            "with status verified.",
            "Set ok to true when the review completes successfully, even when",
            "you report findings. Set ok to false only when the review itself",
            "cannot be completed.",
        ]
    )


def _range_code_review_context_paths(store: StateStore) -> list[str]:
    return _implementation_context_paths(store)


def _range_code_review_prompt(
    store: StateStore,
    start_sha: str,
    end_sha: str,
    commits: list[str],
    attempt: int,
    fix_mode: str,
    operator_messages: list[str],
) -> str:
    requirements_path, design_path, plan_path, test_plan_path = (
        _implementation_context_paths(store)
    )
    lines = [
        f"Review commit range {start_sha}..{end_sha} inclusively.",
        f"This is range code-review attempt {attempt}.",
        f"Fix mode: {_range_fix_mode_label(fix_mode)}.",
        "",
        f"Use {requirements_path}, {design_path}, {plan_path}, and",
        f"{test_plan_path} when present as the approved context.",
        "First inspect the final tree at the range end commit to understand",
        "the final architecture and behavior. Then review each commit in",
        "range order using that final-tree context.",
        "Evaluate whether each commit is coherent, reviewable, and aligned",
        "with the approved requirements, detailed design, implementation plan,",
        "and test plan.",
        "Do not modify files.",
        "Classify every finding as blocker, major, or minor.",
        "Blocker and major findings are blocking. Minor findings are",
        "non-blocking follow-up items.",
        "Report every finding, including minor findings, as structured review",
        "issues.",
        "For each issue, set commit to the SHA of the commit that should be",
        "changed. Use stable issue IDs that include the short commit SHA when",
        "possible, for example RCR-ab12cd34-001.",
        "If a previously reported issue is fixed, report the same issue_id",
        "with status verified.",
        "Set ok to true when the review completes successfully, even when",
        "you report findings. Set ok to false only when the review itself",
        "cannot be completed.",
        "",
        "Commits to review in order:",
        *_markdown_list(_commit_review_lines(store.root, commits)),
    ]
    if fix_mode != "none":
        lines.extend(
            [
                "",
                "Fix mode is enabled. Review first; ElectroBoy will launch a",
                "separate fix agent if blocker or major findings remain.",
            ]
        )
    lines.extend(_range_operator_instruction_lines(operator_messages))
    return "\n".join(lines)


def _range_code_fix_prompt(
    store: StateStore,
    base_sha: str | None,
    end_sha: str,
    commits: list[str],
    issue_file: str,
    summary_path: str,
    attempt: int,
    fix_mode: str,
    operator_messages: list[str],
) -> str:
    requirements_path, design_path, plan_path, test_plan_path = (
        _implementation_context_paths(store)
    )
    base_text = base_sha or "root commit has no parent"
    if fix_mode == "followup":
        mode_lines = [
            "Fix code-review findings as follow-up commits for the current HEAD range.",
            "Address blocker and major findings by creating one or more new",
            "commits after the current range end.",
            "Do not amend, rebase, squash, or otherwise rewrite commits in the",
            "reviewed range.",
            "Keep follow-up commits focused on the recorded blocker and major",
            "findings.",
        ]
    else:
        mode_lines = [
            "Fix code-review findings in place for the current HEAD commit range.",
            "Address blocker and major findings by modifying the specific commit",
            "identified on each issue. Use an in-place history rewrite such as",
            "interactive rebase, fixup, or amend so the fixes land in the",
            "offending commits.",
            "Do not create follow-up fix commits at the end of the range.",
        ]
    lines = [
        *mode_lines,
        f"This is range fix attempt {attempt}.",
        f"Fix mode: {_range_fix_mode_label(fix_mode)}.",
        "",
        f"Range base parent: {base_text}",
        f"Current range end before fixes: {end_sha}",
        "",
        f"Use {requirements_path}, {design_path}, {plan_path}, and",
        f"{test_plan_path} when present as the approved context.",
        f"Use {summary_path} and internal issue file {issue_file} as review",
        "context.",
        "Do not modify commits before the range base parent.",
        "Do not rewrite unrelated commits outside the listed range.",
        "If a conflict or unsafe rewrite occurs, stop and report the exact",
        "repository state. Do not resolve conflicts by guessing.",
        "Leave the working tree clean when finished.",
        "",
        "Commits in the range before fixes:",
        *_markdown_list(_commit_review_lines(store.root, commits)),
    ]
    lines.extend(_range_operator_instruction_lines(operator_messages))
    return "\n".join(lines)


def _range_operator_instruction_lines(messages: list[str]) -> list[str]:
    if not messages:
        return []
    return [
        "",
        "Additional operator instructions for this range review:",
        *_markdown_list(messages),
    ]


def _documentation_prompt(store: StateStore) -> str:
    requirements_path, design_path, plan_path, test_plan_path = (
        _implementation_context_paths(store)
    )
    return "\n".join(
        [
            "Review final documentation against the completed codebase.",
            "",
            f"Use {requirements_path}, {design_path}, {plan_path},",
            f"{test_plan_path}, README.md, and docs/api.md as context.",
            "Limit documentation edits to README.md and docs/api.md unless the",
            "operator explicitly asks for another change.",
            "If requirements, design, plan, or test-plan artifacts need to",
            "change, report the required upstream change and why.",
            "Report files changed and a concise commit_message when finished.",
        ]
    )


def _design_review_outcome(
    result: AgentResult,
    blocking: list[dict[str, object]],
) -> str:
    if not result.ok:
        return "failed"
    if blocking:
        return "blocked"
    return "passed"


def _write_design_review_summary(
    store: StateStore,
    result: AgentResult,
    event_id: str,
    issue_file: str,
    outcome: str,
) -> str:
    manifest = store.load_current_manifest()
    issues = store.read_review_issues(issue_file)
    blocking = _blocking_issues(store, issue_file)
    reported_files = _agent_reported_files(result)
    summary = result.final_message.strip() or "No narrative review summary returned."
    reviewed_artifacts = _artifact_paths(store, DESIGN_REVIEW_CONTEXT_PATHS)
    summary_path = _artifact_path(store, DESIGN_REVIEW_SUMMARY_PATH)
    updates_path = _artifact_path(store, DESIGN_REVIEW_UPDATES_PATH)
    lines = [
        "# Design Review",
        "",
        f"Run ID: {manifest.run_id}",
        f"Review event: {event_id}",
        f"Review issue file: {issue_file}",
        f"Stage result: {outcome}",
        f"Active stage when written: {manifest.active_stage}",
        "",
        "## Reviewed Artifacts",
        "",
        *_markdown_list(reviewed_artifacts),
        "",
        "## Summary",
        "",
        *summary.splitlines(),
        "",
        "## Review Findings",
        "",
        *_markdown_list(_design_review_issue_lines(issues)),
        "",
        "## Changes Made",
        "",
        *_markdown_list(_design_review_change_lines(reported_files)),
        "",
        "## Orchestrator Artifacts",
        "",
        f"- {summary_path}",
        f"- {updates_path}",
        "",
        "## Open Issues",
        "",
        *_markdown_list(_design_review_issue_lines(blocking)),
        "",
        "## Approval State",
        "",
        _design_review_approval_state(outcome),
    ]
    path = store.root / summary_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    store.append_activity(
        ActivityEvent(
            actor="orchestrator",
            stage=STAGE_DESIGN_REVIEW,
            action="design-review-summary-written",
            summary=f"Wrote {summary_path}.",
            outputs=[summary_path],
            artifact_changes=[summary_path],
            message_ref=f"messages/{event_id}-response.md",
        )
    )
    return summary_path


def _design_review_issue_lines(issues: list[dict[str, object]]) -> list[str]:
    return [
        (
            f"{issue.get('issue_id')}: {issue.get('severity')} "
            f"{issue.get('status')} - {issue.get('summary')}"
        )
        for issue in issues
    ]


def _design_review_change_lines(paths: list[str]) -> list[str]:
    if not paths:
        return ["No agent-reported file changes."]
    return paths


def _design_review_approval_state(outcome: str) -> str:
    if outcome == "passed":
        return "Design review has no blocking findings and may complete."
    if outcome == "blocked":
        return "Design review is blocked by open blocker or major findings."
    return "Design review did not complete because the review agent failed."


def _sync_design_review_narrative_issues(
    store: StateStore,
    issue_file: str,
    result: AgentResult,
    event_id: str,
) -> None:
    if not result.ok:
        return
    if result.issues:
        return
    findings = _design_review_narrative_findings(result.final_message)
    if findings:
        _append_design_review_narrative_issues(store, issue_file, findings, event_id)
        return
    if result.ok:
        _verify_design_review_narrative_issues(store, issue_file)


def _append_design_review_narrative_issues(
    store: StateStore,
    issue_file: str,
    findings: list[dict[str, str]],
    event_id: str,
) -> None:
    event_suffix = "".join(char for char in event_id if char.isdigit()) or "0"
    for offset, finding in enumerate(findings, start=1):
        issue = ReviewIssue(
            issue_id=f"DREV-{event_suffix}-{offset:02d}",
            source="design-review-agent:narrative",
            severity=finding["severity"],
            status="open",
            summary=finding["summary"],
            stage=STAGE_DESIGN_REVIEW,
            artifact=_artifact_path(store, "docs/detailed-design.md"),
            rationale=finding["body"],
            requested_change=finding["requested_change"] or None,
        )
        store.append_review_issue(issue_file, issue)
    store.append_activity(
        ActivityEvent(
            actor="orchestrator",
            stage=STAGE_DESIGN_REVIEW,
            action="design-review-narrative-issues-recorded",
            summary=(
                "Recorded narrative design-review blocker/major findings as "
                "structured issues."
            ),
            inputs=[event_id],
            outputs=[issue_file],
            linked_issue_ids=[
                f"DREV-{event_suffix}-{offset:02d}"
                for offset in range(1, len(findings) + 1)
            ],
        )
    )


def _verify_design_review_narrative_issues(
    store: StateStore,
    issue_file: str,
) -> None:
    open_issues = [
        issue
        for issue in store.read_review_issues(issue_file)
        if issue.get("source") == "design-review-agent:narrative"
        and issue.get("status") in BLOCKING_ISSUE_STATUSES
        and issue.get("severity") in {"blocker", "major"}
    ]
    if not open_issues:
        return
    verified_ids: list[str] = []
    for issue in open_issues:
        data = dict(issue)
        data["status"] = "verified"
        data["verification"] = (
            "A later design-review pass reported no narrative blocker or "
            "major findings."
        )
        data["updated_at"] = utc_now()
        store.append_review_issue(issue_file, ReviewIssue.from_dict(data))
        verified_ids.append(str(issue.get("issue_id")))
    store.append_activity(
        ActivityEvent(
            actor="orchestrator",
            stage=STAGE_DESIGN_REVIEW,
            action="design-review-narrative-issues-verified",
            summary=(
                "Verified prior narrative design-review issues after a clean "
                "review pass."
            ),
            outputs=[issue_file],
            linked_issue_ids=verified_ids,
        )
    )


def _design_review_narrative_findings(text: str) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    section: str | None = None
    current: list[str] = []

    def flush() -> None:
        nonlocal current
        if section is None or not current:
            current = []
            return
        finding = _design_review_narrative_finding(section, current)
        if finding:
            findings.append(finding)
        current = []

    for line in text.splitlines():
        heading = _design_review_narrative_heading(line)
        if heading is not None:
            flush()
            section = heading
            continue
        if section is not None and _design_review_narrative_other_heading(line):
            flush()
            section = None
            continue
        if section is None:
            continue
        if _design_review_narrative_no_findings(line):
            continue
        if _design_review_narrative_item_start(line):
            flush()
            current = [line]
            continue
        if current:
            current.append(line)
    flush()
    return findings


def _design_review_narrative_heading(line: str) -> str | None:
    normalized = line.strip().strip("#").strip().strip("*").strip().lower()
    if normalized in {"blockers", "blocker findings"}:
        return "blocker"
    if normalized in {"major findings", "majors"}:
        return "major"
    return None


def _design_review_narrative_other_heading(line: str) -> bool:
    stripped = line.strip()
    if stripped.startswith("#"):
        return True
    return stripped.startswith("**") and stripped.endswith("**")


def _design_review_narrative_no_findings(line: str) -> bool:
    normalized = line.strip().lower()
    return normalized.startswith("no blocker") or normalized.startswith("no major")


def _design_review_narrative_item_start(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped:
        return False
    if stripped[0] in {"-", "*"}:
        return True
    parts = stripped.split(maxsplit=1)
    return bool(parts and parts[0].rstrip(".)").isdigit())


def _design_review_narrative_finding(
    severity: str,
    lines: list[str],
) -> dict[str, str] | None:
    body = "\n".join(line.rstrip() for line in lines).strip()
    if not body:
        return None
    first = lines[0].strip()
    if first.startswith(("-", "*")):
        first = first[1:].strip()
    else:
        parts = first.split(maxsplit=1)
        if parts and parts[0].rstrip(".)").isdigit():
            first = parts[1].strip() if len(parts) > 1 else ""
    summary = _strip_markdown(first)
    lower_prefix = f"{severity}:"
    if summary.lower().startswith(lower_prefix):
        summary = summary[len(lower_prefix):].strip()
    requested_change = _design_review_requested_change(body)
    return {
        "severity": severity,
        "summary": summary or f"{severity.title()} design-review finding",
        "body": body,
        "requested_change": requested_change,
    }


def _strip_markdown(text: str) -> str:
    value = text.replace("**", "").replace("__", "").strip()
    return value.rstrip(".").strip()


def _design_review_requested_change(body: str) -> str:
    marker = "Requested change:"
    if marker not in body:
        return ""
    requested = body.split(marker, 1)[1].strip()
    return requested.splitlines()[0].strip()


def _init_design_review_update_log(store: StateStore) -> str:
    manifest = store.load_current_manifest()
    design_path = _artifact_path(store, "docs/detailed-design.md")
    summary_path = _artifact_path(store, DESIGN_REVIEW_SUMMARY_PATH)
    updates_path = _artifact_path(store, DESIGN_REVIEW_UPDATES_PATH)
    path = store.root / updates_path
    if path.exists():
        return updates_path
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Design Review Updates",
        "",
        f"Run ID: {manifest.run_id}",
        f"Design artifact: {design_path}",
        f"Design review summary: {summary_path}",
        "",
        "This log is maintained by the ElectroBoy orchestrator. It records",
        "detailed-design changes made by the design author in response to",
        "design-review findings.",
        "",
        "## Update Entries",
        "",
        "No coordinated design-review updates have been made yet.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
    store.append_activity(
        ActivityEvent(
            actor="orchestrator",
            stage=STAGE_DESIGN_REVIEW,
            action="design-review-update-log-initialized",
            summary=f"Initialized {updates_path}.",
            outputs=[updates_path],
            artifact_changes=[updates_path],
        )
    )
    return updates_path


def _run_design_review_update(
    store: StateStore,
    pass_number: int,
    review_event_id: str,
    issue_file: str,
    summary_path: str,
    blocking: list[dict[str, object]],
) -> int:
    design_path = _artifact_path(store, "docs/detailed-design.md")
    before = _read_design_review_update_text(store, design_path)
    with _progress_step(
        "design-review",
        f"running design author update after pass {pass_number}",
    ):
        result, author_event_id, _issue_file = _invoke_agent_role(
            store,
            role="design_author_update",
            prompt=_design_review_update_prompt(
                store,
                issue_file,
                summary_path,
                blocking,
                pass_number,
            ),
            context_paths=_design_review_context_paths(store),
        )
    after = _read_design_review_update_text(store, design_path)
    changed = before != after
    changed_paths = _design_review_update_changed_paths(
        design_path,
        changed,
        result,
    )
    _append_design_review_update_log(
        store,
        pass_number,
        review_event_id,
        author_event_id,
        issue_file,
        blocking,
        result,
        before,
        after,
        changed_paths,
    )
    if not result.ok:
        print(
            result.final_message,
            end="" if result.final_message.endswith("\n") else "\n",
        )
        return 1
    if not changed:
        _print_gate_failure(
            [
                "blocking design review issues remain",
                f"design author did not modify {design_path}",
            ]
        )
        return 1
    _print_progress(
        "design-review",
        f"design author updated {design_path}; rerunning review",
    )
    return 0


def _read_design_review_update_text(store: StateStore, relative_path: str) -> str:
    path = store.root / relative_path
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _design_review_update_changed_paths(
    design_path: str,
    design_changed: bool,
    result: AgentResult,
) -> list[str]:
    paths = set(_agent_reported_files(result))
    if design_changed:
        paths.add(design_path)
    return sorted(paths)


def _append_design_review_update_log(
    store: StateStore,
    pass_number: int,
    review_event_id: str,
    author_event_id: str,
    issue_file: str,
    blocking: list[dict[str, object]],
    result: AgentResult,
    before: str,
    after: str,
    changed_paths: list[str],
) -> str:
    updates_path = _artifact_path(store, DESIGN_REVIEW_UPDATES_PATH)
    design_path = _artifact_path(store, "docs/detailed-design.md")
    path = store.root / updates_path
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if "No coordinated design-review updates have been made yet." in existing:
        existing = existing.replace(
            "No coordinated design-review updates have been made yet.\n\n",
            "",
        )
    diff_lines = _design_review_update_diff(design_path, before, after)
    entry = [
        f"### Update After Review Pass {pass_number}",
        "",
        f"Recorded: {utc_now()}",
        f"Review event: {review_event_id}",
        f"Design author event: {author_event_id}",
        f"Review issue file: {issue_file}",
        "",
        "#### Blocking Findings",
        "",
        *_markdown_list(_design_review_issue_lines(blocking)),
        "",
        "#### Changed Files",
        "",
        *_markdown_list(changed_paths),
        "",
        "#### Design Author Summary",
        "",
        *(result.final_message.strip() or "No design author summary returned.").splitlines(),
        "",
        "#### Detailed Design Diff",
        "",
        "```diff",
        *diff_lines,
        "```",
        "",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(existing.rstrip() + "\n\n" + "\n".join(entry), encoding="utf-8")
    store.append_activity(
        ActivityEvent(
            actor="orchestrator",
            stage=STAGE_DESIGN_REVIEW,
            action="design-review-update-logged",
            summary=f"Logged design-review update in {updates_path}.",
            inputs=[review_event_id, author_event_id],
            outputs=[updates_path],
            artifact_changes=[updates_path],
            message_ref=f"messages/{author_event_id}-response.md",
        )
    )
    return updates_path


def _design_review_update_diff(
    design_path: str,
    before: str,
    after: str,
) -> list[str]:
    if before == after:
        return ["# No detailed-design changes detected."]
    return list(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=f"a/{design_path}",
            tofile=f"b/{design_path}",
            lineterm="",
        )
    )


def _agent_reported_files(result: AgentResult) -> list[str]:
    paths = [
        *result.changed_files,
        *result.created_files,
    ]
    normalized = {
        _normalize_repo_path(str(path))
        for path in paths
        if str(path).strip()
    }
    return sorted(
        path
        for path in normalized
        if path != "." and not _is_pipeline_internal_path(path)
    )


def _commit_approval_baseline(
    store: StateStore,
    stage: str,
    paths: list[str],
) -> tuple[str | None, str | None]:
    missing = [
        path
        for path in paths
        if not (store.root / path).exists()
    ]
    if missing:
        return None, "approval baseline artifacts are missing: " + ", ".join(missing)
    if not _is_git_worktree(store.root):
        return None, "repository is not a git worktree"

    message = _approval_commit_message(stage)
    commit_sha, error = _create_artifact_commit(store.root, paths, message)
    if error:
        return None, error
    if commit_sha is None:
        commit_sha = _git_current_head(store.root)
        if commit_sha is None:
            return None, "approval baseline artifacts are not committed"
        untracked = _git_paths_missing_from_head(store.root, paths)
        if untracked:
            return (
                None,
                "approval baseline artifacts are not committed: "
                + ", ".join(untracked),
            )

    store.append_activity(
        ActivityEvent(
            actor="orchestrator",
            stage=stage,
            action="approval-baseline-committed",
            summary=f"Committed approved baseline artifacts for {stage}.",
            outputs=paths,
            commit=commit_sha,
        )
    )
    return commit_sha, None


def _approval_commit_message(stage: str) -> str:
    subjects = {
        STAGE_REQUIREMENTS: "requirements: approve baseline",
        STAGE_DESIGN_ACCEPTANCE: "design: approve baseline",
        STAGE_PLAN: "plan: approve implementation baseline",
        STAGE_TEST_PLAN: "test-plan: approve validation baseline",
        STAGE_VALIDATION: "validation: approve implementation reports",
    }
    subject = subjects.get(stage, f"{stage}: approve baseline")
    return "\n".join(
        [
            subject,
            "",
            f"Record approved {stage} artifacts created by ElectroBoy.",
        ]
    )


def _complete_implementation_stage(store: StateStore, engine: GateEngine) -> int:
    with _progress_step("implementation", "writing implementation reports"):
        paths = _write_implementation_artifacts(store)
    for path in paths:
        print(f"artifact: {path}")
    return _cmd_stage(store, engine, _stage_args(STAGE_IMPLEMENTATION))


def _write_implementation_artifacts(store: StateStore) -> list[str]:
    log_relative_path = _artifact_path(store, IMPLEMENTATION_LOG_PATH)
    report_relative_path = _artifact_path(store, IMPLEMENTATION_REPORT_PATH)
    log_path = store.root / log_relative_path
    report_path = store.root / report_relative_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(_format_implementation_log(store), encoding="utf-8")
    report_path.write_text(_format_implementation_report(store), encoding="utf-8")
    outputs = [log_relative_path, report_relative_path]
    store.append_activity(
        ActivityEvent(
            actor="orchestrator",
            stage=STAGE_IMPLEMENTATION,
            action="implementation-reports-written",
            summary="Wrote implementation log and report.",
            outputs=outputs,
            artifact_changes=outputs,
        )
    )
    return outputs


def _format_implementation_log(store: StateStore) -> str:
    manifest = store.load_current_manifest()
    phase_status = store.load_phase_status()
    lines = [
        "# Implementation Log",
        "",
        f"Run ID: {manifest.run_id}",
        f"Generated: {utc_now()}",
        "",
        "## Phase Timeline",
        "",
    ]
    phase_numbers = sorted(phase_status.phases, key=int)
    if not phase_numbers:
        lines.append("- none")
    for phase_number in phase_numbers:
        phase = phase_status.phases[phase_number]
        lines.extend(
            [
                f"### Phase {phase_number}",
                "",
                f"- Status: {phase.get('status', 'unknown')}",
                f"- Objective: {phase.get('objective', 'unknown')}",
                f"- Coding event: {phase.get('coding_event', 'none')}",
                f"- Code review event: {phase.get('code_review_event', 'none')}",
                f"- Test review event: {phase.get('test_review_event', 'none')}",
                f"- Commit event: {phase.get('commit_event', 'none')}",
                f"- Commit: {phase.get('commit', 'none')}",
                "",
                "Code review findings:",
                "",
                *_markdown_list(
                    _review_issue_summary_lines(
                        store,
                        f"phase-{phase_number}-code-review.jsonl",
                    )
                ),
                "",
                "Test review findings:",
                "",
                *_markdown_list(
                    _review_issue_summary_lines(
                        store,
                        f"phase-{phase_number}-test-review.jsonl",
                    )
                ),
                "",
            ]
        )
    lines.extend(
        [
            "## Implementation Activity",
            "",
            *_markdown_list(_implementation_activity_lines(store)),
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def _format_implementation_report(store: StateStore) -> str:
    manifest = store.load_current_manifest()
    phase_status = store.load_phase_status()
    phase_numbers = sorted(phase_status.phases, key=int)
    commits = _phase_commit_lines(phase_status)
    open_issues: list[str] = []
    for phase_number in phase_numbers:
        open_issues.extend(
            _review_issue_summary_lines(
                store,
                f"phase-{phase_number}-code-review.jsonl",
                blocking_only=True,
            )
        )
        open_issues.extend(
            _review_issue_summary_lines(
                store,
                f"phase-{phase_number}-test-review.jsonl",
                blocking_only=True,
            )
        )
    lines = [
        "# Implementation Report",
        "",
        f"Run ID: {manifest.run_id}",
        f"Generated: {utc_now()}",
        "",
        "## Current Implementation State",
        "",
        "Implementation phases are complete and ready for validation.",
        "",
        "## Completed Phases",
        "",
        *_markdown_list(commits),
        "",
        "## Notable Review Notes",
        "",
        *_markdown_list(_implementation_review_note_lines(store)),
        "",
        "## Open Implementation Issues",
        "",
        *_markdown_list(open_issues),
        "",
        "## Validation",
        "",
        "Validation results are recorded separately in "
        f"{_artifact_path(store, VALIDATION_REPORT_PATH)}.",
    ]
    return "\n".join(lines).rstrip() + "\n"


def _implementation_activity_lines(store: StateStore) -> list[str]:
    lines: list[str] = []
    for event in store.read_activity():
        if event.get("stage") != STAGE_IMPLEMENTATION:
            continue
        action = event.get("action", "unknown")
        summary = event.get("summary", "")
        event_id = event.get("id", "unknown")
        phase = event.get("phase")
        phase_text = f" phase {phase}" if phase is not None else ""
        lines.append(f"{event_id}:{phase_text} {action} - {summary}")
    return lines


def _implementation_review_note_lines(store: StateStore) -> list[str]:
    notes: list[str] = []
    phase_status = store.load_phase_status()
    for phase_number in sorted(phase_status.phases, key=int):
        for issue_file in [
            f"phase-{phase_number}-code-review.jsonl",
            f"phase-{phase_number}-test-review.jsonl",
        ]:
            notes.extend(_review_issue_summary_lines(store, issue_file))
    return notes


def _review_issue_summary_lines(
    store: StateStore,
    issue_file: str,
    blocking_only: bool = False,
) -> list[str]:
    issues = store.read_review_issues(issue_file)
    if blocking_only:
        issues = [
            issue
            for issue in issues
            if _issue_is_blocking(issue)
        ]
    return [
        (
            f"{issue_file}: {issue.get('issue_id')} "
            f"{issue.get('severity')} {issue.get('status')} - "
            f"{issue.get('summary')}"
        )
        for issue in issues
    ]


def _init_git_repository(project_root: Path) -> None:
    if _is_git_worktree(project_root):
        return
    result = subprocess.run(
        ["git", "init", "-b", "main"],
        cwd=project_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode == 0:
        return
    fallback = subprocess.run(
        ["git", "init"],
        cwd=project_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if fallback.returncode != 0:
        detail = fallback.stderr.strip() or result.stderr.strip()
        raise StateError(f"git repository initialization failed: {detail}")


def _is_git_worktree(project_root: Path) -> bool:
    result = subprocess.run(
        ["git", "-C", str(project_root), "rev-parse", "--is-inside-work-tree"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _write_project_config(project_root: Path) -> None:
    path = project_root / ".electroboy" / "project.toml"
    if path.exists():
        _update_project_config_defaults(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """[runtime]
default = "codex"

[runtimes.codex]
adapter = "codex_exec"
command = "codex"
args = ["exec", "--json"]
env = ["PATH", "HOME", "LANG", "LC_ALL", "TERM", "COLORTERM", "TMPDIR", "CODEX_HOME", "OPENAI_API_KEY"]
structured_output = "json_schema"

[runtimes.codex-interactive]
adapter = "codex_interactive"
command = "codex"
env = ["PATH", "HOME", "LANG", "LC_ALL", "TERM", "COLORTERM", "TMPDIR", "CODEX_HOME", "OPENAI_API_KEY"]

[roles]
design_author = "codex-interactive"
design_author_update = "codex"
design_review = "codex"
coding = "codex"
code_review = "codex"
test_review = "codex"
documentation = "codex"

[environment]
activate_python = false
python_activate = ".venv/bin/activate"
python_managed_by_pipeline = false
""",
        encoding="utf-8",
    )


def _update_project_config_defaults(path: Path) -> None:
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines()
    updated: list[str] = []
    section: str | None = None
    roles_update_seen = False

    def finish_section() -> None:
        nonlocal roles_update_seen
        if section == "roles" and not roles_update_seen:
            updated.append('design_author_update = "codex"')
        roles_update_seen = False

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            finish_section()
            section = stripped[1:-1].strip()
            updated.append(line)
            continue
        if section in {"runtimes.codex", "runtimes.codex-interactive"}:
            line = _project_config_env_with_colorterm(line)
        if section == "roles" and stripped.startswith("design_author_update"):
            roles_update_seen = True
        updated.append(line)
    finish_section()

    text = "\n".join(updated).rstrip() + "\n"
    if text != original:
        path.write_text(text, encoding="utf-8")


def _project_config_env_with_colorterm(line: str) -> str:
    if not line.strip().startswith("env = ["):
        return line
    if '"COLORTERM"' in line:
        return line
    if '"TERM"' in line:
        return line.replace('"TERM"', '"TERM", "COLORTERM"', 1)
    if line.rstrip().endswith("]"):
        return line.rstrip()[:-1].rstrip() + ', "COLORTERM"]'
    return line


def _write_project_gitignore(project_root: Path) -> None:
    path = project_root / ".gitignore"
    lines = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    required = [
        ".electroboy/local/",
        ".electroboy/shared/runs/*/progress/",
    ]
    missing = [line for line in required if line not in lines]
    if not missing:
        return
    if lines and lines[-1] != "":
        lines.append("")
    if "# ElectroBoy local runtime state" not in lines:
        lines.append("# ElectroBoy local runtime state")
    lines.extend(missing)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_project_bin(project_root: Path) -> None:
    bin_dir = _project_bin_dir(project_root)
    bin_dir.mkdir(parents=True, exist_ok=True)
    activate = bin_dir / "activate"
    activate.write_text(_activation_script(project_root), encoding="utf-8")
    activate.chmod(0o755)
    for name in ("electroboy", "ai-pipeline"):
        path = bin_dir / name
        path.write_text(_project_entrypoint_script(), encoding="utf-8")
        path.chmod(0o755)


def _project_bin_dir(project_root: Path) -> Path:
    return project_root / ".electroboy" / "bin"


def _write_project_runtime(project_root: Path) -> None:
    source = _module_search_path() / "electroboy"
    target = project_root / ".electroboy" / "local" / "runtime" / "src"
    package_target = target / "electroboy"
    if package_target.exists():
        shutil.rmtree(package_target)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        source,
        package_target,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )


def _activation_script(project_root: Path) -> str:
    quoted_root = shlex.quote(str(project_root))
    quoted_project_name = shlex.quote(project_root.name)
    return f"""# ElectroBoy project activation script.
# Source this file from a POSIX-compatible shell.

_ELECTROBOY_ACTIVATED_ROOT={quoted_root}
_ELECTROBOY_PROJECT_PROMPT={quoted_project_name}
_ELECTROBOY_PREVIOUS_PATH="${{PATH:-}}"
_ELECTROBOY_PREVIOUS_PROJECT_ROOT="${{ELECTROBOY_PROJECT_ROOT:-}}"
_ELECTROBOY_PREVIOUS_AI_PIPELINE_ROOT="${{AI_PIPELINE_PROJECT_ROOT:-}}"
_ELECTROBOY_PREVIOUS_VIRTUAL_ENV="${{VIRTUAL_ENV:-}}"
_ELECTROBOY_PREVIOUS_PS1="${{PS1-}}"
if [ "${{PS1+x}}" = "x" ]; then
    _ELECTROBOY_HAD_PS1=1
else
    _ELECTROBOY_HAD_PS1=0
fi
export _ELECTROBOY_ACTIVATED_ROOT
export _ELECTROBOY_PROJECT_PROMPT
export _ELECTROBOY_PREVIOUS_PATH
export _ELECTROBOY_PREVIOUS_PROJECT_ROOT
export _ELECTROBOY_PREVIOUS_AI_PIPELINE_ROOT
export _ELECTROBOY_PREVIOUS_VIRTUAL_ENV
export _ELECTROBOY_PREVIOUS_PS1
export _ELECTROBOY_HAD_PS1

ELECTROBOY_PROJECT_ROOT="$_ELECTROBOY_ACTIVATED_ROOT"
PATH="$ELECTROBOY_PROJECT_ROOT/.electroboy/bin:$PATH"
export ELECTROBOY_PROJECT_ROOT
export PATH

_ELECTROBOY_PROJECT_CONFIG="$ELECTROBOY_PROJECT_ROOT/.electroboy/project.toml"
if [ ! -f "$_ELECTROBOY_PROJECT_CONFIG" ] && \\
    [ -f "$ELECTROBOY_PROJECT_ROOT/.agent-pipeline/project.toml" ]; then
    _ELECTROBOY_PROJECT_CONFIG="$ELECTROBOY_PROJECT_ROOT/.agent-pipeline/project.toml"
fi
if [ -f "$_ELECTROBOY_PROJECT_CONFIG" ] && \\
    grep -Eq '^[[:space:]]*activate_python[[:space:]]*=[[:space:]]*true' \\
        "$_ELECTROBOY_PROJECT_CONFIG"; then
    _ELECTROBOY_PYTHON_ACTIVATE=$(sed -n \\
        's/^[[:space:]]*python_activate[[:space:]]*=[[:space:]]*"\\(.*\\)".*/\\1/p' \\
        "$_ELECTROBOY_PROJECT_CONFIG" | tail -n 1)
    if [ -z "$_ELECTROBOY_PYTHON_ACTIVATE" ]; then
        _ELECTROBOY_PYTHON_ACTIVATE=".venv/bin/activate"
    fi
    if [ -f "$ELECTROBOY_PROJECT_ROOT/$_ELECTROBOY_PYTHON_ACTIVATE" ]; then
        . "$ELECTROBOY_PROJECT_ROOT/$_ELECTROBOY_PYTHON_ACTIVATE"
        if [ -z "$_ELECTROBOY_PREVIOUS_VIRTUAL_ENV" ] && [ -n "${{VIRTUAL_ENV:-}}" ]; then
            _ELECTROBOY_OWNS_PYTHON_ENV=1
            export _ELECTROBOY_OWNS_PYTHON_ENV
        fi
    fi
fi

if [ -n "${{PS1:-}}" ]; then
    PS1="($_ELECTROBOY_PROJECT_PROMPT) $PS1"
fi

electroboy() {{
    if [ "${{1:-}}" = "deactivate" ]; then
        command electroboy --root "$ELECTROBOY_PROJECT_ROOT" deactivate
        if [ "${{_ELECTROBOY_OWNS_PYTHON_ENV:-0}}" = "1" ] && \\
            command -v deactivate >/dev/null 2>&1; then
            deactivate
        fi
        PATH="${{_ELECTROBOY_PREVIOUS_PATH:-$PATH}}"
        if [ -n "${{_ELECTROBOY_PREVIOUS_PROJECT_ROOT:-}}" ]; then
            ELECTROBOY_PROJECT_ROOT="$_ELECTROBOY_PREVIOUS_PROJECT_ROOT"
            export ELECTROBOY_PROJECT_ROOT
        else
            unset ELECTROBOY_PROJECT_ROOT
        fi
        if [ -n "${{_ELECTROBOY_PREVIOUS_AI_PIPELINE_ROOT:-}}" ]; then
            AI_PIPELINE_PROJECT_ROOT="$_ELECTROBOY_PREVIOUS_AI_PIPELINE_ROOT"
            export AI_PIPELINE_PROJECT_ROOT
        else
            unset AI_PIPELINE_PROJECT_ROOT
        fi
        if [ "${{_ELECTROBOY_HAD_PS1:-0}}" = "1" ]; then
            PS1="$_ELECTROBOY_PREVIOUS_PS1"
        else
            unset PS1
        fi
        export PATH
        if [ -n "${{BASH_VERSION:-}}" ] && \\
            command -v complete >/dev/null 2>&1; then
            complete -r electroboy ai-pipeline ./electroboy ./ai-pipeline 2>/dev/null || true
        fi
        unset -f __electroboy_complete 2>/dev/null || true
        unset -f __electroboy_command_options 2>/dev/null || true
        unset -f __electroboy_subcommands 2>/dev/null || true
        unset -f __electroboy_nested_options 2>/dev/null || true
        unset -f __electroboy_option_expects_value 2>/dev/null || true
        unset _ELECTROBOY_ACTIVATED_ROOT
        unset _ELECTROBOY_PROJECT_PROMPT
        unset _ELECTROBOY_PREVIOUS_PATH
        unset _ELECTROBOY_PREVIOUS_PROJECT_ROOT
        unset _ELECTROBOY_PREVIOUS_AI_PIPELINE_ROOT
        unset _ELECTROBOY_PREVIOUS_VIRTUAL_ENV
        unset _ELECTROBOY_PREVIOUS_PS1
        unset _ELECTROBOY_HAD_PS1
        unset _ELECTROBOY_OWNS_PYTHON_ENV
        unset -f electroboy
        return 0
    fi
    command electroboy --root "$ELECTROBOY_PROJECT_ROOT" "$@"
}}

if [ -n "${{BASH_VERSION:-}}" ]; then
    _ELECTROBOY_COMPLETION_SCRIPT=$(command electroboy \\
        --root "$ELECTROBOY_PROJECT_ROOT" completion bash 2>/dev/null)
    if [ -n "$_ELECTROBOY_COMPLETION_SCRIPT" ]; then
        eval "$_ELECTROBOY_COMPLETION_SCRIPT"
    fi
    unset _ELECTROBOY_COMPLETION_SCRIPT
fi

electroboy status
"""


def _module_search_path() -> Path:
    return Path(__file__).resolve().parents[1]


def _project_entrypoint_script() -> str:
    return f"""#!/usr/bin/env sh
set -eu

if [ -n "${{ELECTROBOY_PROJECT_ROOT:-}}" ]; then
    PROJECT_ROOT="$ELECTROBOY_PROJECT_ROOT"
elif [ -n "${{AI_PIPELINE_PROJECT_ROOT:-}}" ]; then
    PROJECT_ROOT="$AI_PIPELINE_PROJECT_ROOT"
else
    SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
    PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/../.." && pwd)
fi

RUNTIME_SRC="$PROJECT_ROOT/.electroboy/local/runtime/src"
if [ ! -d "$RUNTIME_SRC" ] && [ -d "$PROJECT_ROOT/.agent-pipeline/local/runtime/src" ]; then
    RUNTIME_SRC="$PROJECT_ROOT/.agent-pipeline/local/runtime/src"
fi
if [ -d "$RUNTIME_SRC/electroboy" ]; then
    PYTHONPATH="$RUNTIME_SRC${{PYTHONPATH:+:$PYTHONPATH}}"
    export PYTHONPATH
fi

exec python3 -m electroboy --root "$PROJECT_ROOT" "$@"
"""


def _format_run_summary(store: StateStore, engine: GateEngine) -> str:
    manifest = store.load_current_manifest()
    phase_status = store.load_phase_status()
    open_changes = _open_change_requests(store)
    open_issues = _open_review_issues(store)
    blocked = _blocked_gate_lines(store, engine)
    snapshots = store.read_artifact_snapshots()
    activity = store.read_activity()
    decisions = store.read_decisions()
    invalidations = store.read_baseline_invalidations()
    active_phase = (
        str(phase_status.active_phase)
        if phase_status.active_phase is not None
        else "none"
    )
    lines = [
        "# Run Summary",
        "",
        f"Run ID: {manifest.run_id}",
        f"Active stage: {_stage_display_name(manifest.active_stage)}",
        f"Stage command: {_stage_command(manifest.active_stage)}",
        f"Next stage: {_stage_display_name(NEXT_STAGE.get(manifest.active_stage))}",
        f"Active phase: {active_phase}",
        "",
        "## Completed Gates",
        "",
        *_markdown_list(manifest.completed_gates),
        "",
        "## Invalidated Gates",
        "",
        *_markdown_list(manifest.invalidated_gates),
        "",
        "## Open Change Requests",
        "",
        *_markdown_list(_change_request_lines(open_changes)),
        "",
        "## Open Review Issues",
        "",
        *_markdown_list(_review_issue_lines(open_issues)),
        "",
        "## Blocked Gates",
        "",
        *_markdown_list(blocked),
        "",
        "## Run Counts",
        "",
        f"- Activity events: {len(activity)}",
        f"- Artifact snapshots: {len(snapshots)}",
        f"- Decisions: {len(decisions)}",
        f"- Baseline invalidations: {len(invalidations)}",
        "",
        "## Phase Commits",
        "",
        *_markdown_list(_phase_commit_lines(phase_status)),
        "",
        "## Decisions",
        "",
        *_markdown_list(_decision_lines(decisions)),
        "",
        "## Artifact Snapshots",
        "",
        *_markdown_list(_snapshot_lines(snapshots)),
        "",
        "## Baseline Invalidations",
        "",
        *_markdown_list(_invalidation_lines(invalidations)),
    ]
    return "\n".join(lines).rstrip() + "\n"


def _format_activity_trace(store: StateStore) -> str:
    activity = store.read_activity()
    lines = ["# Activity Trace", ""]
    if not activity:
        lines.append("- none")
        return "\n".join(lines) + "\n"
    for event in activity:
        timestamp = event.get("timestamp", "")
        actor = event.get("actor", "")
        action = event.get("action", "")
        stage = event.get("stage", "")
        summary = event.get("summary", "")
        lines.append(f"- {timestamp} {actor} {action} [{stage}] {summary}")
    decisions = store.read_decisions()
    if decisions:
        lines.extend(["", "## Decisions", ""])
        lines.extend(_markdown_list(_decision_lines(decisions)))
    invalidations = store.read_baseline_invalidations()
    if invalidations:
        lines.extend(["", "## Baseline Invalidations", ""])
        lines.extend(_markdown_list(_invalidation_lines(invalidations)))
    return "\n".join(lines) + "\n"


def _write_or_print_report(root: Path, text: str, output: str | None) -> int:
    if output:
        path = root / output
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"report written: {path}")
        return 0
    print(text, end="")
    return 0


def _blocked_gate_lines(store: StateStore, engine: GateEngine) -> list[str]:
    manifest = store.load_current_manifest()
    gates = [GATE_STAGE_ORDER, GATE_CHANGE_CONTROL, GATE_PLAN_CURRENCY]
    active_gate = STAGE_COMPLETED_GATES.get(manifest.active_stage)
    if active_gate:
        gates.append(active_gate)
    phase_status = store.load_phase_status()
    if phase_status.active_phase is not None:
        gates.append(GATE_COMMIT)
    if manifest.active_stage == STAGE_VALIDATION:
        gates.append(GATE_VALIDATION_TESTING)
    if manifest.active_stage == STAGE_DOCS_REVIEW:
        gates.append(GATE_DOCUMENTATION)

    lines: list[str] = []
    for gate in gates:
        result = engine.evaluate(gate, manifest)
        if result.passed:
            continue
        if result.messages:
            for message in result.messages:
                lines.append(f"{gate}: {message}")
        else:
            lines.append(gate)
    return lines


def _open_change_requests(store: StateStore) -> list[dict[str, object]]:
    return [
        request
        for request in store.read_change_requests()
        if request.get("status") in {"open", "classified"}
    ]


def _open_review_issues(store: StateStore) -> list[tuple[str, dict[str, object]]]:
    issue_files = [
        "design-review.jsonl",
        "validation-review.jsonl",
        "documentation-review.jsonl",
    ]
    phase_status = store.load_phase_status()
    for phase in sorted(phase_status.phases):
        issue_files.extend(
            [
                f"phase-{phase}-code-review.jsonl",
                f"phase-{phase}-test-review.jsonl",
            ]
        )
    run_id = store.current_run_id()
    if run_id:
        issue_files.extend(
            path.name
            for path in store.run_dir(run_id).glob(
                f"{RANGE_CODE_REVIEW_ISSUE_PREFIX}-*.jsonl"
            )
        )

    issues: list[tuple[str, dict[str, object]]] = []
    for issue_file in issue_files:
        for issue in store.read_review_issues(issue_file):
            if issue.get("status") in BLOCKING_ISSUE_STATUSES:
                issues.append((issue_file, issue))
    return issues


def _change_request_lines(requests: list[dict[str, object]]) -> list[str]:
    return [
        f"{request.get('id')}: {request.get('status')} {request.get('baseline')}"
        for request in requests
    ]


def _review_issue_lines(
    issues: list[tuple[str, dict[str, object]]],
) -> list[str]:
    return [
        (
            f"{issue_file}: {issue.get('issue_id')} "
            f"{issue.get('severity')} {issue.get('summary')}"
        )
        for issue_file, issue in issues
    ]


def _phase_commit_lines(phase_status: PhaseStatus) -> list[str]:
    lines: list[str] = []
    for phase_number in sorted(phase_status.phases, key=int):
        phase = phase_status.phases[phase_number]
        commit = phase.get("commit", "none")
        status = phase.get("status", "unknown")
        lines.append(f"phase {phase_number}: {status} {commit}")
    return lines


def _decision_lines(decisions: list[dict[str, object]]) -> list[str]:
    return [
        f"{decision.get('decision_id')}: {decision.get('summary')}"
        for decision in decisions
    ]


def _snapshot_lines(snapshots: list[dict[str, object]]) -> list[str]:
    return [
        f"{snapshot.get('artifact_path')} -> {snapshot.get('snapshot_path')}"
        for snapshot in snapshots
    ]


def _invalidation_lines(invalidations: list[dict[str, object]]) -> list[str]:
    return [
        (
            f"{invalidation.get('invalidation_id')}: "
            f"{invalidation.get('baseline')} "
            f"{', '.join(invalidation.get('invalidated_gates', []))}"
        )
        for invalidation in invalidations
    ]


def _markdown_list(items: list[str]) -> list[str]:
    if not items:
        return ["- none"]
    return [f"- {item}" for item in items]


def _print_list(label: str, items: list[str]) -> None:
    print(f"{label}:")
    for item in items:
        print(f"  - {item}")
    if not items:
        print("  - none")


def _print_count(label: str, items: list[object]) -> None:
    print(f"{label}: {len(items)}")


def _print_gate_failure(messages: list[str]) -> None:
    print("blocked:", file=sys.stderr)
    for message in messages:
        print(f"  - {message}", file=sys.stderr)


def _blocking_issues(store: StateStore, file_name: str) -> list[dict[str, object]]:
    return [
        issue
        for issue in store.read_review_issues(file_name)
        if _issue_is_blocking(issue)
    ]


def _record_stage_approvals(
    store: StateStore,
    stage: str,
    args: argparse.Namespace,
) -> list[str]:
    requirements = STAGE_APPROVAL_REQUIREMENTS.get(stage, [])
    errors: list[str] = []
    forced = getattr(args, "force", False)
    for approval_type, actor in requirements:
        if _has_approval(store, stage, approval_type):
            continue
        flag_set = (
            approval_type == "human-approval"
            and getattr(args, "human_approved", False)
        ) or (
            approval_type == "author-confirmation"
            and getattr(args, "author_confirmed", False)
        )
        if not flag_set:
            errors.append(f"approval is missing: {stage} {approval_type}")
            continue
        if (
            approval_type == "author-confirmation"
            and not forced
            and not _has_successful_agent_event(
                store,
                "design_author",
                stage,
            )
        ):
            errors.append(f"agent confirmation is missing: {stage} design_author")
            continue
        summary = f"{actor} recorded {approval_type} for {stage}."
        action = "approval-recorded"
        if forced:
            summary = f"{actor} force-recorded {approval_type} for {stage}."
            action = "forced-approval-recorded"
        approval = ApprovalRecord(
            approval_id=f"APP-{len(store.read_approvals()) + 1:04d}",
            stage=stage,
            actor=actor,
            approval_type=approval_type,
            artifact_path=_stage_required_file(store, stage),
            summary=summary,
        )
        store.append_approval(approval)
        store.append_activity(
            ActivityEvent(
                actor=actor,
                stage=stage,
                action=action,
                summary=approval.summary,
                outputs=["approvals.jsonl"],
            )
        )
    return errors


def _has_successful_agent_event(store: StateStore, role: str, stage: str) -> bool:
    return any(
        event.get("actor") == role
        and event.get("stage") == stage
        and event.get("action") == "agent-invoked"
        and event.get("status") == "pass"
        for event in store.read_activity()
    )


def _has_approval(store: StateStore, stage: str, approval_type: str) -> bool:
    return any(
        approval.get("stage") == stage
        and approval.get("approval_type") == approval_type
        for approval in store.read_approvals()
    )


def _transition_issue(
    store: StateStore,
    file_name: str,
    issue_id: str,
    status: str,
    response: str | None,
    verification: str | None,
) -> bool:
    issue = _find_issue(store, file_name, issue_id)
    if issue is None:
        print(f"error: issue not found: {issue_id}", file=sys.stderr)
        return False
    updated = dict(issue)
    updated.update(
        {
            "status": status,
            "response": response if response is not None else issue.get("response"),
            "verification": (
                verification
                if verification is not None
                else issue.get("verification")
            ),
            "updated_at": utc_now(),
        }
    )
    store.append_review_issue(file_name, ReviewIssue.from_dict(updated))
    store.append_activity(
        ActivityEvent(
            actor="orchestrator",
            action="issue-transitioned",
            summary=f"Transitioned issue {issue_id} to {status}.",
            phase=updated.get("phase"),
            linked_issue_ids=[issue_id],
            outputs=[file_name],
        )
    )
    return True


def _find_issue(
    store: StateStore,
    file_name: str,
    issue_id: str,
) -> dict[str, object] | None:
    for issue in store.read_review_issues(file_name):
        if issue.get("issue_id") == issue_id:
            return issue
    return None


def _append_missing_documentation_issues(
    store: StateStore,
    missing: list[str],
) -> None:
    existing = store.read_review_issues("documentation-review.jsonl")
    open_summaries = {
        str(issue.get("summary"))
        for issue in existing
        if issue.get("status") in BLOCKING_ISSUE_STATUSES
    }
    next_index = len(existing) + 1
    for relative_path in missing:
        summary = f"Required documentation file is missing: {relative_path}"
        if summary in open_summaries:
            continue
        issue = ReviewIssue(
            issue_id=f"DOC-{next_index:04d}",
            source="documentation-agent",
            severity="blocker",
            status="open",
            summary=summary,
            stage=STAGE_DOCS_REVIEW,
            artifact=relative_path,
            requested_change=f"Create {relative_path}.",
        )
        store.append_review_issue("documentation-review.jsonl", issue)
        next_index += 1


def _verify_restored_documentation_files(
    store: StateStore,
    missing: list[str],
) -> None:
    missing_set = set(missing)
    for issue in store.read_review_issues("documentation-review.jsonl"):
        artifact = str(issue.get("artifact") or "")
        if not artifact or artifact in missing_set:
            continue
        if not (store.root / artifact).exists():
            continue
        summary = str(issue.get("summary", ""))
        if not summary.startswith("Required documentation file is missing:"):
            continue
        if issue.get("status") not in BLOCKING_ISSUE_STATUSES:
            continue
        _transition_issue(
            store,
            "documentation-review.jsonl",
            str(issue["issue_id"]),
            status="verified",
            response="Documentation file restored.",
            verification=f"{artifact} exists.",
        )


def _append_documentation_content_issues(
    store: StateStore,
    errors: list[str],
) -> None:
    existing = store.read_review_issues("documentation-review.jsonl")
    existing_summaries = {str(issue.get("summary")) for issue in existing}
    next_index = len(existing) + 1
    for error in errors:
        if error in existing_summaries:
            continue
        issue = ReviewIssue(
            issue_id=f"DOC-{next_index:04d}",
            source="documentation-agent",
            severity="major",
            status="open",
            summary=error,
            stage=STAGE_DOCS_REVIEW,
            requested_change="Update documentation to match public behavior.",
        )
        store.append_review_issue("documentation-review.jsonl", issue)
        next_index += 1


def _documentation_semantic_errors(root: Path) -> list[str]:
    errors: list[str] = []
    readme = (root / "README.md").read_text(encoding="utf-8")
    api = (root / "docs" / "api.md").read_text(encoding="utf-8")
    for command in _top_level_cli_commands():
        if command not in api:
            errors.append(f"docs/api.md does not document `{command}`")
    if "PYTHONPATH=src" not in readme and "pip install -e ." not in readme:
        errors.append("README.md does not describe how to run the CLI")
    if "test" not in readme.lower():
        errors.append("README.md does not describe how to run tests")
    return errors


def _top_level_cli_commands() -> list[str]:
    parser = build_parser()
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            return sorted(action.choices)
    return []


def _validation_commands(
    store: StateStore,
    args: argparse.Namespace,
) -> list[tuple[list[str] | str, bool, str]]:
    commands: list[tuple[list[str] | str, bool, str]] = []
    artifact_commands = _artifact_validation_commands(store)
    for command in artifact_commands:
        commands.append((shlex.split(command), False, "artifact"))
    if not artifact_commands:
        commands.append(
            (
                ["validation-specification-missing"],
                False,
                "missing-specification",
            )
        )
    for command in args.validation_commands:
        commands.append((shlex.split(command), False, "operator"))
    for command in args.validation_shell_commands:
        commands.append((command, True, "operator-shell"))
    commands.append(
        (
            [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
            False,
            "test-suite",
        )
    )
    return commands


def _artifact_validation_commands(store: StateStore) -> list[str]:
    commands: list[str] = []
    for relative_path in _artifact_paths(
        store,
        [
            "docs/requirements.md",
            "docs/detailed-design.md",
            TEST_PLAN_PATH,
        ],
    ):
        path = store.root / relative_path
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped.startswith("Validation:"):
                continue
            command = stripped.split(":", 1)[1].strip()
            if command:
                commands.append(command)
    return commands


def _run_validation_command(
    root: Path,
    command: list[str] | str,
    shell: bool,
) -> dict[str, object]:
    env = os.environ.copy()
    src_path = str(root / "src")
    if env.get("PYTHONPATH"):
        env["PYTHONPATH"] = f"{src_path}{os.pathsep}{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = src_path
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            env=env,
            shell=shell,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError as error:
        return {
            "command": command if isinstance(command, str) else " ".join(command),
            "shell": shell,
            "returncode": 127,
            "stdout": "",
            "stderr": str(error),
        }
    return {
        "command": command if isinstance(command, str) else " ".join(command),
        "shell": shell,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
    }


def _uncommitted_planned_phases(store: StateStore) -> list[int]:
    planned = planned_phases(
        store.root,
        _artifact_path(store, "docs/implementation-plan.md"),
    )
    if not planned:
        return []
    status = store.load_phase_status()
    missing: list[int] = []
    for phase in planned:
        state = status.phases.get(str(phase.number), {})
        if state.get("status") != "committed":
            missing.append(phase.number)
            continue
        commit = state.get("commit")
        if not isinstance(commit, str) or not _git_commit_exists(store.root, commit):
            missing.append(phase.number)
    return missing


def _next_uncommitted_phase(store: StateStore) -> int | None:
    phases = _uncommitted_planned_phases(store)
    if not phases:
        return None
    return min(phases)


def _phase_objective(store: StateStore, phase_number: int) -> str:
    for phase in planned_phases(
        store.root,
        _artifact_path(store, "docs/implementation-plan.md"),
    ):
        if phase.number == phase_number:
            return phase.heading
    return f"Phase {phase_number}"


def _git_commit_exists(root: Path, sha: str) -> bool:
    if not _is_git_worktree(root):
        return False
    completed = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-e", f"{sha}^{{commit}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return completed.returncode == 0


def _create_artifact_commit(
    root: Path,
    paths: list[str],
    message: str,
) -> tuple[str | None, str | None]:
    allowed_paths = sorted(
        {
            _normalize_repo_path(path)
            for path in paths
            if path.strip() and not _is_pipeline_internal_path(path)
        }
    )
    if not allowed_paths:
        return None, None

    changed_paths = _git_worktree_changed_paths(root)
    stage_paths = [
        path
        for path in allowed_paths
        if path in changed_paths
    ]
    staged_paths = _git_staged_changed_paths(root)
    outside_staged = [
        path
        for path in staged_paths
        if path not in allowed_paths
    ]
    if outside_staged:
        return (
            None,
            "staged changes are outside the artifact commit: "
            + ", ".join(outside_staged),
        )
    if not stage_paths and not staged_paths:
        return None, None

    if stage_paths:
        add_error = _git_add_paths(root, stage_paths)
        if add_error:
            return None, add_error
    staged_paths = _git_staged_changed_paths(root)
    outside_staged = [
        path
        for path in staged_paths
        if path not in allowed_paths
    ]
    if outside_staged:
        return (
            None,
            "staged changes are outside the artifact commit: "
            + ", ".join(outside_staged),
        )
    if not any(path in staged_paths for path in allowed_paths):
        return None, None

    subject, body = _commit_message_parts(message)
    completed = subprocess.run(
        ["git", "-C", str(root), "commit", "-m", subject, "-m", body],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        return None, f"git commit failed: {detail}"
    sha = _git_current_head(root)
    if sha is None:
        return None, "git commit succeeded but HEAD could not be read"
    return sha, None


def _commit_message_parts(message: str) -> tuple[str, str]:
    lines = [line.rstrip() for line in message.strip().splitlines()]
    subject = next((line for line in lines if line.strip()), "")
    if not subject:
        subject = "artifacts: record generated output"
    subject_index = lines.index(subject) if subject in lines else 0
    body = "\n".join(lines[subject_index + 1 :]).strip()
    if not body:
        body = "Automated artifact commit created by ElectroBoy."
    return subject, body


def _git_worktree_changed_paths(
    root: Path,
    include_untracked: bool = True,
) -> list[str]:
    commands = [
        ["git", "-C", str(root), "diff", "--name-only"],
        ["git", "-C", str(root), "diff", "--name-only", "--cached"],
    ]
    if include_untracked:
        commands.append(
            ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"]
        )
    paths: set[str] = set()
    for command in commands:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            continue
        for path in completed.stdout.splitlines():
            normalized = _normalize_repo_path(path)
            if not _is_pipeline_internal_path(normalized):
                paths.add(normalized)
    return sorted(paths)


def _git_staged_changed_paths(root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", "--cached"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return []
    return [
        _normalize_repo_path(path)
        for path in completed.stdout.splitlines()
        if path.strip()
    ]


def _git_add_paths(root: Path, paths: list[str]) -> str | None:
    if not paths:
        return "phase produced no repository changes to stage"
    completed = subprocess.run(
        ["git", "-C", str(root), "add", "-A", "--", *paths],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode == 0:
        return None
    return completed.stderr.strip() or completed.stdout.strip() or "git add failed"


def _git_current_head(root: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _parse_commit_range_spec(spec: str) -> tuple[str, str]:
    if "..." in spec or spec.count("..") != 1:
        raise StateError("commit range must use the form <sha1>..<sha2>")
    start, end = [part.strip() for part in spec.split("..", 1)]
    if not start or not end:
        raise StateError("commit range must include both <sha1> and <sha2>")
    return start, end


def _git_resolve_commit(root: Path, revision: str) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", f"{revision}^{{commit}}"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()


def _git_is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", ancestor, descendant],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return completed.returncode == 0


def _git_inclusive_commit_range(root: Path, start_sha: str, end_sha: str) -> list[str]:
    if start_sha == end_sha:
        return [start_sha]
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "rev-list",
            "--reverse",
            "--ancestry-path",
            f"{start_sha}..{end_sha}",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return []
    commits = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    return [start_sha, *commits]


def _git_commits_after_base(
    root: Path,
    base_sha: str | None,
    end_sha: str,
) -> list[str]:
    revision = f"{base_sha}..{end_sha}" if base_sha else end_sha
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-list", "--reverse", revision],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return []
    return [line.strip() for line in completed.stdout.splitlines() if line.strip()]


def _git_first_parent(root: Path, sha: str) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "rev-list", "--parents", "-n", "1", sha],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return None
    parts = completed.stdout.split()
    if len(parts) < 2:
        return None
    return parts[1]


def _validate_fix_range_at_head(
    store: StateStore,
    end_sha: str,
    fix_mode: str,
) -> None:
    head = _git_current_head(store.root)
    if head != end_sha:
        raise StateError(
            f"--fix-{fix_mode} requires <sha2> to be the current HEAD commit"
        )
    changed_paths = _non_review_tracked_changes(store)
    if changed_paths:
        raise StateError(
            f"--fix-{fix_mode} requires a clean tracked worktree: "
            + ", ".join(changed_paths)
        )


def _non_review_tracked_changes(store: StateStore) -> list[str]:
    allowed = {
        _normalize_repo_path(_artifact_path(store, CODE_REVIEW_SUMMARY_PATH)),
    }
    return [
        path
        for path in _git_worktree_changed_paths(store.root, include_untracked=False)
        if path not in allowed
    ]


def _range_code_review_issue_file(start_sha: str, end_sha: str) -> str:
    return (
        f"{RANGE_CODE_REVIEW_ISSUE_PREFIX}-"
        f"{_short_sha(start_sha)}-{_short_sha(end_sha)}.jsonl"
    )


def _commit_review_lines(root: Path, commits: list[str]) -> list[str]:
    return [
        f"{_short_sha(commit)} {commit} {_git_commit_subject(root, commit)}"
        for commit in commits
    ]


def _git_commit_subject(root: Path, commit: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), "show", "-s", "--format=%s", commit],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _short_sha(sha: str) -> str:
    return sha[:12]


def _git_repository_heads(root: Path) -> dict[str, str]:
    heads: dict[str, str] = {}
    for repo in _git_repository_roots(root):
        head = _git_current_head(repo)
        if head:
            heads[_normalize_repo_path(str(repo.relative_to(root)))] = head
    return heads


def _git_repository_roots(root: Path) -> list[Path]:
    repos: list[Path] = []
    if _is_git_worktree(root):
        repos.append(root)
    for dirpath, dirnames, filenames in os.walk(root):
        current = Path(dirpath)
        relative = _normalize_repo_path(str(current.relative_to(root)))
        has_git_entry = ".git" in dirnames or ".git" in filenames
        dirnames[:] = [
            name
            for name in dirnames
            if not _is_pruned_git_scan_dir(relative, name)
        ]
        if current == root:
            continue
        if has_git_entry:
            repos.append(current)
            dirnames[:] = []
    return repos


def _is_pruned_git_scan_dir(relative: str, name: str) -> bool:
    if name in {".git", ".electroboy", ".agent-pipeline"}:
        return True
    path = _normalize_repo_path(f"{relative}/{name}" if relative != "." else name)
    return _is_pipeline_internal_path(path)


def _coding_pass_head_change_error(
    root: Path,
    before_heads: dict[str, str],
) -> str | None:
    after_heads = _git_repository_heads(root)
    changed = [
        repo
        for repo, before_head in before_heads.items()
        if after_heads.get(repo) and after_heads[repo] != before_head
    ]
    created = [repo for repo in after_heads if repo not in before_heads]
    if not changed and not created:
        return None
    repos = sorted(changed + created)
    return (
        "coding agent created git commits during an implementation/fix pass; "
        "commits are only allowed in the dedicated phase commit pass: "
        + ", ".join(repos)
    )


def _git_paths_missing_from_head(root: Path, paths: list[str]) -> list[str]:
    missing: list[str] = []
    for path in paths:
        completed = subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"HEAD:{path}"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if completed.returncode != 0:
            missing.append(path)
    return missing


def _phase_commit_objective(
    phase_number: int,
    phase: dict[str, object],
) -> str:
    objective = str(phase.get("objective") or "").strip()
    if not objective:
        return f"Phase {phase_number}"
    prefix = f"Phase {phase_number}"
    if objective.lower().startswith(prefix.lower()):
        detail = objective[len(prefix):].strip(" .:-")
        return detail or prefix
    return objective


def _phase_commit_validation_error(
    store: StateStore,
    sha: str,
    phase_number: int,
    phase: dict[str, object],
) -> str | None:
    root = store.root
    if not _git_commit_exists(root, sha):
        return f"commit does not exist: {sha}"
    if not _git_commit_reachable_from_head(root, sha):
        return f"commit is not reachable from HEAD: {sha}"
    message_error = _phase_commit_message_error(root, sha, phase_number, phase)
    if message_error:
        return message_error
    return _phase_commit_scope_error(store, sha, phase_number)


def _record_phase_commit(
    store: StateStore,
    manifest,
    phase_number: int,
    sha: str,
    commit_event: str | None = None,
) -> None:
    status = store.load_phase_status()
    phase = status.phases.setdefault(str(phase_number), {})
    phase["status"] = "committed"
    phase["commit"] = sha
    phase["commit_gate"] = "passed"
    if commit_event:
        phase["commit_event"] = commit_event
    status.active_phase = None
    store.save_phase_status(status)
    store.append_activity(
        ActivityEvent(
            actor="coding-agent",
            stage=manifest.active_stage,
            phase=phase_number,
            gate=GATE_COMMIT,
            action="phase-committed",
            status="pass",
            summary=f"Committed implementation phase {phase_number}.",
            commit=sha,
        )
    )


def _git_commit_reachable_from_head(root: Path, sha: str) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", sha, "HEAD"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return completed.returncode == 0


def _phase_commit_message_error(
    root: Path,
    sha: str,
    phase_number: int,
    phase: dict[str, object],
) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(root), "log", "-1", "--format=%B", sha],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return "commit message could not be read"
    message = completed.stdout.lower()
    if f"phase {phase_number}" not in message and f"phase-{phase_number}" not in message:
        return f"commit message must identify phase {phase_number}"
    objective = str(phase.get("objective") or "").strip().lower()
    if objective and not _message_mentions_objective(message, objective, phase_number):
        return "commit message must identify the active phase objective"
    return None


def _message_mentions_objective(
    message: str,
    objective: str,
    phase_number: int,
) -> bool:
    prefix = f"phase {phase_number}"
    detail = objective
    if detail.startswith(prefix):
        detail = detail[len(prefix):].strip(" .:-")
    if not detail:
        return True
    return detail in message


def _phase_commit_scope_error(
    store: StateStore,
    sha: str,
    phase_number: int,
) -> str | None:
    changed_paths = _git_commit_changed_paths(store.root, sha)
    internal_paths = [
        path for path in changed_paths if _is_pipeline_internal_path(path)
    ]
    if internal_paths:
        return (
            "phase commit includes ElectroBoy internal state: "
            + ", ".join(internal_paths)
        )
    return _phase_paths_scope_error(
        store,
        phase_number,
        changed_paths,
    )


def _phase_paths_scope_error(
    store: StateStore,
    phase_number: int,
    changed_paths: list[str],
) -> str | None:
    planned_phase = next(
        (
            phase
            for phase in planned_phases(
                store.root,
                _artifact_path(store, "docs/implementation-plan.md"),
            )
            if phase.number == phase_number
        ),
        None,
    )
    if planned_phase is None:
        return None
    if not planned_phase.paths:
        return None
    allowed_paths = [_normalize_repo_path(path) for path in planned_phase.paths]
    allowed_paths.extend(_phase_review_artifact_paths(store))
    if "*" in allowed_paths or "." in allowed_paths:
        return None
    if not changed_paths:
        return "phase produced no repository changes"
    out_of_scope = [
        path
        for path in changed_paths
        if not any(_path_is_within(path, allowed) for allowed in allowed_paths)
    ]
    if out_of_scope:
        return (
            f"commit changes are outside phase {phase_number} scope: "
            + ", ".join(out_of_scope)
        )
    return None


def _is_pipeline_internal_path(path: str) -> bool:
    return (
        path == ".electroboy"
        or path.startswith(".electroboy/")
        or path == ".agent-pipeline"
        or path.startswith(".agent-pipeline/")
    )


def _git_commit_changed_paths(root: Path, sha: str) -> list[str]:
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "diff-tree",
            "--root",
            "--no-commit-id",
            "--name-only",
            "-r",
            sha,
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        return []
    return [
        _normalize_repo_path(path)
        for path in completed.stdout.splitlines()
        if path.strip()
    ]


def _normalize_repo_path(path: str) -> str:
    return path.strip().strip("/").strip("`") or "."


def _path_is_within(path: str, allowed: str) -> bool:
    return path == allowed or path.startswith(f"{allowed}/")


def _open_validation_fix_phase(store: StateStore, manifest) -> None:
    status = store.load_phase_status()
    existing = [int(phase) for phase in status.phases if str(phase).isdigit()]
    planned = [
        phase.number
        for phase in planned_phases(
            store.root,
            _artifact_path(store, "docs/implementation-plan.md"),
        )
    ]
    phase_number = max(existing + planned + [0]) + 1
    status.active_phase = phase_number
    phase = status.phases.setdefault(str(phase_number), {})
    phase.update(
        {
            "status": "active",
            "objective": "Address validation findings",
            "plan_current": True,
            "validation_fix": True,
        }
    )
    store.save_phase_status(status)
    manifest.set_active_stage(STAGE_IMPLEMENTATION)
    store.save_manifest(manifest)
    store.append_activity(
        ActivityEvent(
            actor="orchestrator",
            stage=STAGE_IMPLEMENTATION,
            phase=phase_number,
            action="validation-fix-phase-started",
            summary=f"Started validation-fix phase {phase_number}.",
        )
    )


def _failed_agent_result(error: str) -> AgentResult:
    return AgentResult(
        ok=False,
        final_message=f"Agent invocation failed: {error}",
        raw_events=[{"error": error}],
        error=error,
    )


def _agent_issue_file(role: str, store: StateStore) -> str | None:
    if role in AGENT_ISSUE_FILES:
        return AGENT_ISSUE_FILES[role]
    phase_status = store.load_phase_status()
    if phase_status.active_phase is None:
        return None
    if role in {"code_review", "code-review"}:
        return f"phase-{phase_status.active_phase}-code-review.jsonl"
    if role in {"test_review", "test-review"}:
        return f"phase-{phase_status.active_phase}-test-review.jsonl"
    return None


def _agent_progress_file(role: str, store: StateStore) -> str | None:
    if role not in AGENT_PROGRESS_ROLES:
        return None
    manifest = store.load_current_manifest()
    file_name = _agent_progress_file_name(role, store)
    return f".electroboy/shared/runs/{manifest.run_id}/progress/{file_name}"


def _agent_progress_file_name(role: str, store: StateStore) -> str:
    phase_status = store.load_phase_status()
    active_phase = phase_status.active_phase
    normalized_role = role.replace("-", "_")
    if normalized_role == "design_review":
        return "design-review-progress.md"
    if normalized_role == "design_author_update":
        return "design-review-update-progress.md"
    if normalized_role == "coding":
        if active_phase is not None:
            return f"phase-{active_phase}-code-progress.md"
        return "code-progress.md"
    if normalized_role == "code_review":
        if active_phase is not None:
            return f"phase-{active_phase}-code-review-progress.md"
        return "code-review-progress.md"
    if normalized_role == "test_review":
        if active_phase is not None:
            return f"phase-{active_phase}-test-review-progress.md"
        return "test-review-progress.md"
    if normalized_role == "validation_review":
        return "validation-review-progress.md"
    if normalized_role == "documentation_review":
        return "documentation-review-progress.md"
    return f"{normalized_role.replace('_', '-')}-progress.md"


def _init_agent_progress_file(
    store: StateStore,
    role: str,
    progress_file: str,
    event_id: str,
) -> None:
    path = store.root / progress_file
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"{utc_now()} orchestrator started {role} ({event_id})\n")


def _store_agent_issues(
    store: StateStore,
    issue_file: str,
    role: str,
    issues: list[dict[str, object]],
) -> list[str]:
    linked: list[str] = []
    existing = store.read_review_issues(issue_file)
    next_index = len(existing) + 1
    for raw_issue in issues:
        issue_id = str(raw_issue.get("issue_id") or raw_issue.get("id") or "")
        if not issue_id:
            issue_id = f"AGENT-{next_index:04d}"
            next_index += 1
        data = {
            **raw_issue,
            "issue_id": issue_id,
            "source": raw_issue.get("source", role),
            "severity": raw_issue.get("severity", "major"),
            "status": raw_issue.get("status", "open"),
            "summary": raw_issue.get("summary", ""),
        }
        store.append_review_issue(issue_file, ReviewIssue.from_dict(data))
        linked.append(issue_id)
    return linked


def _invalidated_snapshot_refs(
    store: StateStore,
    invalidated_gates: list[str],
) -> list[str]:
    gate_artifacts = {
        GATE_REQUIREMENTS: _artifact_path(store, "docs/requirements.md"),
        GATE_DESIGN: _artifact_path(store, "docs/detailed-design.md"),
        GATE_HUMAN_DESIGN_ACCEPTANCE: _artifact_path(
            store,
            "docs/detailed-design.md",
        ),
        GATE_IMPLEMENTATION: _artifact_path(store, "docs/implementation-plan.md"),
        GATE_TEST_PLAN: _artifact_path(store, TEST_PLAN_PATH),
        GATE_DOCUMENTATION: "docs/api.md",
    }
    artifacts = {
        gate_artifacts[gate]
        for gate in invalidated_gates
        if gate in gate_artifacts
    }
    return [
        str(snapshot.get("snapshot_path"))
        for snapshot in store.read_artifact_snapshots()
        if snapshot.get("artifact_path") in artifacts
    ]


def _write_validation_report(
    store: StateStore,
    results: list[dict[str, object]],
) -> Path:
    manifest = store.load_current_manifest()
    report_relative_path = _artifact_path(store, VALIDATION_REPORT_PATH)
    report_path = store.root / report_relative_path
    artifact_report_path = (
        store.run_dir(manifest.run_id) / "artifacts" / report_relative_path
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_report_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Validation Report",
        "",
        f"Run: {manifest.run_id}",
        f"Generated: {utc_now()}",
        "",
        "Validation sources:",
        "",
        *_markdown_list(_validation_source_lines(results)),
        "",
        "## Commands",
        "",
    ]
    for index, result in enumerate(results, start=1):
        status = "pass" if result["returncode"] == 0 else "fail"
        lines.extend(
            [
                f"### Command {index}: {status}",
                "",
                "```bash",
                str(result["command"]),
                "```",
                "",
                f"Source: {result.get('source', 'unknown')}",
                "",
                f"Exit code: {result['returncode']}",
                "",
            ]
        )
        if result["stdout"]:
            lines.extend(
                [
                    "Stdout:",
                    "",
                    "```text",
                    str(result["stdout"]).rstrip(),
                    "```",
                    "",
                ]
            )
        if result["stderr"]:
            lines.extend(
                [
                    "Stderr:",
                    "",
                    "```text",
                    str(result["stderr"]).rstrip(),
                    "```",
                    "",
                ]
            )
    text = "\n".join(lines).rstrip() + "\n"
    report_path.write_text(text, encoding="utf-8")
    artifact_report_path.write_text(text, encoding="utf-8")
    return report_path


def _validation_source_lines(results: list[dict[str, object]]) -> list[str]:
    sources = {str(result.get("source", "unknown")) for result in results}
    lines: list[str] = []
    if "artifact" in sources:
        lines.append(
            "artifact validation commands from requirements, design, or test plan"
        )
    if "operator" in sources:
        lines.append("operator supplied validation command")
    if "operator-shell" in sources:
        lines.append("operator supplied shell validation command")
    if "missing-specification" in sources:
        lines.append("missing artifact validation specification")
    if "test-suite" in sources:
        lines.append("configured full test-suite command")
    return lines


if __name__ == "__main__":
    raise SystemExit(main())
