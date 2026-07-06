"""Command-line interface for the AI agent pipeline."""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from .artifacts import ArtifactError, ArtifactManager
from .gates import GateEngine
from .models import (
    ActivityEvent,
    ApprovalRecord,
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
    GATE_VALIDATION_TESTING,
    NEXT_STAGE,
    STAGES,
    PhaseStatus,
    ReviewIssue,
    STAGE_COMPLETE,
    STAGE_DESIGN,
    STAGE_DESIGN_ACCEPTANCE,
    STAGE_DESIGN_REVIEW,
    STAGE_DOCS_REVIEW,
    STAGE_IMPLEMENTATION,
    STAGE_PLAN,
    STAGE_REQUIREMENTS,
    STAGE_VALIDATION,
    utc_now,
)
from .planning import has_traceability, planned_phases, traceability_errors
from .adapters.base import AgentInvocation, AgentResult
from .runtime import runtime_for_role
from .state_store import StateError, StateStore


STAGE_REQUIRED_FILES = {
    STAGE_REQUIREMENTS: "docs/requirements.md",
    STAGE_DESIGN: "docs/detailed-design.md",
    STAGE_DESIGN_REVIEW: "docs/detailed-design.md",
    STAGE_PLAN: "docs/implementation-plan.md",
}

STAGE_COMPLETED_GATES = {
    STAGE_REQUIREMENTS: GATE_REQUIREMENTS,
    STAGE_DESIGN_REVIEW: GATE_DESIGN,
    STAGE_DESIGN_ACCEPTANCE: GATE_HUMAN_DESIGN_ACCEPTANCE,
    STAGE_PLAN: GATE_IMPLEMENTATION,
}

STAGE_SNAPSHOT_ARTIFACTS = {
    STAGE_REQUIREMENTS: "docs/requirements.md",
    STAGE_DESIGN_REVIEW: "docs/detailed-design.md",
    STAGE_DESIGN_ACCEPTANCE: "docs/detailed-design.md",
    STAGE_PLAN: "docs/implementation-plan.md",
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

DOCUMENTATION_REVIEW_FILES = [
    "docs/requirements.md",
    "docs/detailed-design.md",
    "README.md",
    "docs/api.md",
]

CHANGE_BASELINE_INVALIDATED_GATES = {
    "requirements": [
        GATE_REQUIREMENTS,
        GATE_DESIGN,
        GATE_HUMAN_DESIGN_ACCEPTANCE,
        GATE_IMPLEMENTATION,
        GATE_VALIDATION_TESTING,
        GATE_DOCUMENTATION,
    ],
    "design": [
        GATE_DESIGN,
        GATE_HUMAN_DESIGN_ACCEPTANCE,
        GATE_IMPLEMENTATION,
        GATE_VALIDATION_TESTING,
        GATE_DOCUMENTATION,
    ],
    "plan": [
        GATE_IMPLEMENTATION,
        GATE_VALIDATION_TESTING,
        GATE_DOCUMENTATION,
    ],
    "implementation": [
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

    subparsers.add_parser("status", help="show current pipeline status")
    subparsers.add_parser("deactivate", help="leave an activated pipeline project")

    requirements = subparsers.add_parser(
        "requirements",
        help="author or resume requirements definition",
    )
    requirements.add_argument("--reason", help="reason for reopening requirements")
    subparsers.add_parser("requirements-approve", help="approve requirements")

    design = subparsers.add_parser("design", help="author or resume design")
    design.add_argument("--reason", help="reason for reopening design")
    subparsers.add_parser("design-review", help="run design review")
    subparsers.add_parser("design-approve", help="approve reviewed design")

    implementation_plan = subparsers.add_parser(
        "implementation-plan",
        help="author or resume implementation planning",
    )
    implementation_plan.add_argument(
        "--reason",
        help="reason for reopening implementation planning",
    )
    subparsers.add_parser("plan-approve", help="approve implementation plan")

    code = subparsers.add_parser("code", help="start or resume implementation")
    code.add_argument("--reason", help="reason for reopening implementation")
    code.add_argument(
        "--phased",
        action="store_true",
        help="run one phase and leave commit recording to the operator",
    )
    document = subparsers.add_parser(
        "document",
        help="start or resume documentation review",
    )
    document.add_argument("--reason", help="reason for reopening documentation")
    subparsers.add_parser("code-approve", help="approve completed pipeline")

    report = subparsers.add_parser("report", help="generate pipeline reports")
    report_subparsers = report.add_subparsers(dest="report_command", required=True)
    report_summary = report_subparsers.add_parser("summary", help="summarize run")
    report_summary.add_argument("--output", help="write report to this path")
    report_trace = report_subparsers.add_parser("trace", help="show activity trace")
    report_trace.add_argument("--output", help="write report to this path")

    stage = subparsers.add_parser("stage", help="force the active stage")
    stage.add_argument(
        "stage",
        choices=STAGES,
    )
    stage.add_argument(
        "--force",
        action="store_true",
        help="required to set the active stage directly",
    )
    stage.add_argument("--reason", help="reason for forcing the active stage")

    phase = subparsers.add_parser("phase", help="record manual phase commits")
    phase_subparsers = phase.add_subparsers(dest="phase_command", required=True)
    phase_commit = phase_subparsers.add_parser("commit", help="record phase commit")
    phase_commit.add_argument("phase", type=int)
    phase_commit.add_argument("--sha", default="")

    validate = subparsers.add_parser("validate", help="run validation testing")
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

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = StateStore(args.root)
    engine = GateEngine(args.root)

    try:
        if args.command == "new":
            return _cmd_new(args)
        if args.command == "status":
            return _cmd_status(store, engine)
        if args.command == "deactivate":
            return _cmd_deactivate(store)
        if args.command == "requirements":
            return _cmd_authoring_stage(store, engine, args, STAGE_REQUIREMENTS)
        if args.command == "requirements-approve":
            return _cmd_stage(
                store,
                engine,
                _stage_args(STAGE_REQUIREMENTS, human=True, author=True),
            )
        if args.command == "design":
            return _cmd_authoring_stage(store, engine, args, STAGE_DESIGN)
        if args.command == "design-review":
            return _cmd_design_review(store, engine)
        if args.command == "design-approve":
            return _cmd_stage(
                store,
                engine,
                _stage_args(STAGE_DESIGN_ACCEPTANCE, human=True),
            )
        if args.command == "implementation-plan":
            return _cmd_authoring_stage(store, engine, args, STAGE_PLAN)
        if args.command == "plan-approve":
            return _cmd_stage(
                store,
                engine,
                _stage_args(STAGE_PLAN, human=True, author=True),
            )
        if args.command == "code":
            return _cmd_code(store, engine, args)
        if args.command == "document":
            return _cmd_document(store, engine, args)
        if args.command == "code-approve":
            return _cmd_code_approve(store, engine)
        if args.command == "report":
            return _cmd_report(store, engine, args)
        if args.command == "stage":
            return _cmd_set_stage(store, args)
        if args.command == "phase":
            return _cmd_phase(store, engine, args)
        if args.command == "validate":
            return _cmd_validate(store, args)
    except StateError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except ArtifactError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    parser.print_help(sys.stderr)
    return 2


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
    print(f"activate: source {project_root / 'bin' / 'activate'}")
    return 0


def _cmd_status(store: StateStore, engine: GateEngine) -> int:
    manifest = store.load_current_manifest()
    print(f"run id: {manifest.run_id}")
    print(f"active stage: {manifest.active_stage}")
    print(f"next-stage: {NEXT_STAGE.get(manifest.active_stage, 'none')}")
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

    ArtifactManager(store.root).init_templates()
    artifact = STAGE_REQUIRED_FILES.get(stage)
    reason = getattr(args, "reason", None)
    prompt = f"Work with the operator on the {stage} artifact."
    result, event_id, _issue_file = _invoke_agent_role(
        store,
        role="design_author",
        prompt=prompt,
        context_paths=_authoring_inputs(stage),
    )
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
            inputs=_authoring_inputs(stage),
            outputs=[artifact] if artifact else [],
            message_ref=f"messages/{event_id}-response.md",
        )
    )
    print(f"authoring stage: {stage}")
    if artifact:
        print(f"artifact: {artifact}")
    print("next: review the artifact, then run the approval command")
    return 0


def _cmd_design_review(store: StateStore, engine: GateEngine) -> int:
    manifest = store.load_current_manifest()
    if manifest.active_stage == STAGE_DESIGN:
        code = _cmd_stage(
            store,
            engine,
            _stage_args(STAGE_DESIGN, human=True),
        )
        if code != 0:
            return code
    result, _event_id, _issue_file = _invoke_agent_role(
        store,
        role="design_review",
        prompt="Review docs/detailed-design.md against docs/requirements.md.",
        context_paths=["docs/requirements.md", "docs/detailed-design.md"],
    )
    if not result.ok:
        print(result.final_message, end="" if result.final_message.endswith("\n") else "\n")
        return 1
    return _cmd_stage(store, engine, _stage_args(STAGE_DESIGN_REVIEW))


def _cmd_code(
    store: StateStore,
    engine: GateEngine,
    args: argparse.Namespace,
) -> int:
    manifest = store.load_current_manifest()
    if _maybe_reopen_from_public_command(
        store,
        manifest,
        STAGE_IMPLEMENTATION,
        getattr(args, "reason", None),
    ):
        manifest = store.load_current_manifest()
    if manifest.active_stage == STAGE_VALIDATION:
        _print_progress("validation", "implementation phases are complete")
        print("next: run validation commands or use `electroboy document` after validation")
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

    if getattr(args, "phased", False):
        return _cmd_code_phased(store, engine, args)
    return _cmd_code_automated(store, engine, args)


def _cmd_code_phased(
    store: StateStore,
    engine: GateEngine,
    args: argparse.Namespace,
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
        code = _run_phase_agent_loop(store, phase)
        print("next: commit the phase after reviewing repository changes")
        return code

    next_phase = _next_uncommitted_phase(store)
    if next_phase is None:
        _print_progress("implementation", "all planned phases are committed")
        return _cmd_stage(store, engine, _stage_args(STAGE_IMPLEMENTATION))

    phase_status.active_phase = next_phase
    phase = phase_status.phases.setdefault(str(next_phase), {})
    phase.update(
        {
            "status": "active",
            "objective": _phase_objective(store.root, next_phase),
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
    code = _run_phase_agent_loop(store, next_phase)
    print(f"active phase: {next_phase}")
    print("next: commit the phase after reviewing repository changes")
    if getattr(args, "reason", None):
        print(f"reason: {args.reason}")
    return code


def _cmd_code_automated(
    store: StateStore,
    engine: GateEngine,
    args: argparse.Namespace,
) -> int:
    printed_reason = False
    while True:
        phase_status = store.load_phase_status()
        if phase_status.active_phase is None:
            next_phase = _next_uncommitted_phase(store)
            if next_phase is None:
                _print_progress("implementation", "all planned phases are committed")
                return _cmd_stage(store, engine, _stage_args(STAGE_IMPLEMENTATION))
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
        code = _run_phase_agent_loop(store, phase)
        if code != 0:
            return code
        commit_code = _commit_active_phase_automatically(store, engine, phase)
        if commit_code != 0:
            return commit_code


def _start_code_phase(store: StateStore, phase_number: int) -> None:
    phase_status = store.load_phase_status()
    phase_status.active_phase = phase_number
    phase = phase_status.phases.setdefault(str(phase_number), {})
    phase.update(
        {
            "status": "active",
            "objective": _phase_objective(store.root, phase_number),
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


def _run_phase_agent_loop(store: StateStore, phase_number: int) -> int:
    status = store.load_phase_status()
    phase = status.phases.setdefault(str(phase_number), {})
    coding_result, coding_event, _coding_issue_file = _invoke_agent_role(
        store,
        role="coding",
        prompt=f"Implement phase {phase_number} from docs/implementation-plan.md.",
        context_paths=[
            "docs/requirements.md",
            "docs/detailed-design.md",
            "docs/implementation-plan.md",
        ],
    )
    phase["coding_event"] = coding_event
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
        prompt=f"Review implementation phase {phase_number}.",
        context_paths=[
            "docs/requirements.md",
            "docs/detailed-design.md",
            "docs/implementation-plan.md",
        ],
    )
    if not review_result.ok:
        print(
            review_result.final_message,
            end="" if review_result.final_message.endswith("\n") else "\n",
        )
        return 1
    if review_issue_file and _blocking_issues(store, review_issue_file):
        _print_gate_failure([f"blocking review issues remain in {review_issue_file}"])
        return 1
    status = store.load_phase_status()
    phase = status.phases.setdefault(str(phase_number), {})
    phase["code_review"] = "passed"
    phase["code_review_event"] = review_event
    store.save_phase_status(status)

    test_result, test_event, test_issue_file = _invoke_agent_role(
        store,
        role="test_review",
        prompt=f"Review tests for implementation phase {phase_number}.",
        context_paths=[
            "docs/requirements.md",
            "docs/detailed-design.md",
            "docs/implementation-plan.md",
        ],
    )
    if not test_result.ok:
        print(
            test_result.final_message,
            end="" if test_result.final_message.endswith("\n") else "\n",
        )
        return 1
    if test_issue_file and _blocking_issues(store, test_issue_file):
        _print_gate_failure([f"blocking review issues remain in {test_issue_file}"])
        return 1
    status = store.load_phase_status()
    phase = status.phases.setdefault(str(phase_number), {})
    phase["test_review"] = "passed"
    phase["test_review_event"] = test_event
    phase["test_commands"] = list(test_result.commands)
    store.save_phase_status(status)
    return 0


def _commit_active_phase_automatically(
    store: StateStore,
    engine: GateEngine,
    phase_number: int,
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
    commit_sha, error = _create_phase_commit(store.root, phase_number, phase)
    if error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    if commit_sha is None:
        print("error: phase commit was not created", file=sys.stderr)
        return 1
    validation_error = _phase_commit_validation_error(
        store.root,
        commit_sha,
        phase_number,
        phase,
    )
    if validation_error:
        print(f"error: {validation_error}", file=sys.stderr)
        return 1

    _record_phase_commit(store, manifest, phase_number, commit_sha)
    print(f"committed phase: {phase_number}")
    print(f"commit: {commit_sha}")
    return 0


def _cmd_document(
    store: StateStore,
    engine: GateEngine,
    args: argparse.Namespace,
) -> int:
    manifest = store.load_current_manifest()
    reason = getattr(args, "reason", None)
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
        prompt="Review final documentation against the completed codebase.",
        context_paths=[
            "docs/requirements.md",
            "docs/detailed-design.md",
            "docs/implementation-plan.md",
            "README.md",
            "docs/api.md",
        ],
    )
    if not result.ok:
        print(result.final_message, end="" if result.final_message.endswith("\n") else "\n")
        return 1
    _print_progress("documentation", "running documentation review")
    return _cmd_docs_review(store, engine)


def _cmd_code_approve(store: StateStore, engine: GateEngine) -> int:
    manifest = store.load_current_manifest()
    result = engine.evaluate(GATE_DOCUMENTATION, manifest)
    if not result.passed or manifest.active_stage != STAGE_COMPLETE:
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
) -> argparse.Namespace:
    return argparse.Namespace(
        stage=stage,
        human_approved=human,
        author_confirmed=author,
    )


def _authoring_inputs(stage: str) -> list[str]:
    if stage == STAGE_REQUIREMENTS:
        return []
    if stage == STAGE_DESIGN:
        return ["docs/requirements.md"]
    if stage == STAGE_PLAN:
        return ["docs/requirements.md", "docs/detailed-design.md"]
    return []


PUBLIC_STAGE_BASELINES = {
    STAGE_REQUIREMENTS: "requirements",
    STAGE_DESIGN: "design",
    STAGE_PLAN: "plan",
    STAGE_IMPLEMENTATION: "implementation",
    STAGE_DOCS_REVIEW: "documentation",
}


PUBLIC_STAGE_ORDER = [
    STAGE_REQUIREMENTS,
    STAGE_DESIGN,
    STAGE_DESIGN_REVIEW,
    STAGE_DESIGN_ACCEPTANCE,
    STAGE_PLAN,
    STAGE_IMPLEMENTATION,
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
    baseline = PUBLIC_STAGE_BASELINES[target_stage]
    request_id = f"CR-{len(store.read_change_requests()) + 1:04d}"
    request = ChangeRequest(
        request_id=request_id,
        run_id=manifest.run_id,
        baseline=baseline,
        reason=reason,
        status="reopened",
        event="reopened",
        human_approved=True,
        reopened_stage=target_stage,
        invalidated_gates=list(CHANGE_BASELINE_INVALIDATED_GATES[baseline]),
    )
    store.append_change_request(request)
    invalidated = CHANGE_BASELINE_INVALIDATED_GATES[baseline]
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
            invalidated_gates=list(invalidated),
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
            actor="human-operator",
            stage=target_stage,
            action="public-stage-reopened",
            summary=f"Reopened {baseline} through public stage command.",
            outputs=["change-requests.jsonl", "baseline-invalidations.jsonl"],
        )
    )
    print(f"reopened baseline: {baseline}")
    print(f"active stage: {target_stage}")
    return True


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
    reason = (args.reason or "").strip()
    if not reason:
        raise StateError("stage changes require --reason")

    manifest = store.load_current_manifest()
    previous_stage = manifest.active_stage
    manifest.set_active_stage(args.stage)
    store.save_manifest(manifest)

    decision_id = f"STAGE-{len(store.read_decisions()) + 1:04d}"
    store.append_decision(
        DecisionRecord(
            decision_id=decision_id,
            stage=args.stage,
            summary=f"Forced active stage from {previous_stage} to {args.stage}",
            rationale=reason,
        )
    )
    store.append_activity(
        ActivityEvent(
            actor="human-operator",
            stage=args.stage,
            action="forced-stage-change",
            summary=f"Forced active stage from {previous_stage} to {args.stage}.",
            inputs=[reason],
            outputs=[
                f".electroboy/shared/runs/{manifest.run_id}/manifest.json",
                "decisions.jsonl",
            ],
        )
    )

    print(f"previous stage: {previous_stage}")
    print(f"active stage: {manifest.active_stage}")
    print(f"decision: {decision_id}")
    return 0


def _cmd_stage(
    store: StateStore,
    engine: GateEngine,
    args: argparse.Namespace,
) -> int:
    stage = args.stage
    manifest = store.load_current_manifest()
    order = engine.stage_order(stage, manifest)
    if not order.passed:
        _print_gate_failure(order.messages)
        return 1

    required_file = STAGE_REQUIRED_FILES.get(stage)
    if required_file:
        file_result = engine.require_file(required_file)
        if not file_result.passed:
            _print_gate_failure(file_result.messages)
            return 1
    approval_errors = _record_stage_approvals(store, stage, args)
    if approval_errors:
        _print_gate_failure(approval_errors)
        return 1
    if stage == STAGE_PLAN and not has_traceability(store.root):
        _print_gate_failure(traceability_errors(store.root))
        return 1
    if stage == STAGE_IMPLEMENTATION:
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

    completed_gate = STAGE_COMPLETED_GATES.get(stage)
    if stage == STAGE_DESIGN_REVIEW:
        blocking = _blocking_issues(store, "design-review.jsonl")
        if blocking:
            _print_gate_failure(["blocking design review issues remain"])
            return 1
    if completed_gate:
        manifest.complete_gate(completed_gate)

    next_stage = NEXT_STAGE.get(stage)
    if next_stage:
        manifest.set_active_stage(next_stage)
    store.save_manifest(manifest)
    snapshot_artifact = STAGE_SNAPSHOT_ARTIFACTS.get(stage)
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
            store.root,
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


def _cmd_validate(store: StateStore, args: argparse.Namespace) -> int:
    manifest = store.load_current_manifest()
    if manifest.active_stage != STAGE_VALIDATION:
        print("error: active stage is not validation", file=sys.stderr)
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

    commands = _validation_commands(store.root, args)
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
                artifact="validation-report.md",
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
    manifest.set_active_stage(STAGE_DOCS_REVIEW)
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
    return 0


def _cmd_docs_review(store: StateStore, engine: GateEngine) -> int:
    manifest = store.load_current_manifest()
    order = engine.stage_order(STAGE_DOCS_REVIEW, manifest)
    if not order.passed:
        _print_gate_failure(order.messages)
        return 1

    missing = [
        relative_path
        for relative_path in DOCUMENTATION_REVIEW_FILES
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
    for relative_path in DOCUMENTATION_REVIEW_FILES:
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
) -> tuple[AgentResult, str, str | None]:
    manifest = store.load_current_manifest()
    event_id = f"agent-{len(store.read_activity()) + 1:05d}"
    invocation = AgentInvocation(
        role=role,
        prompt=prompt,
        context_paths=context_paths,
    )
    try:
        runtime = runtime_for_role(role, store.root)
        result = runtime.invoke(invocation)
    except Exception as error:
        result = _failed_agent_result(str(error))
    store.write_message(f"{event_id}-prompt", invocation.prompt)
    store.write_message(f"{event_id}-response", result.final_message)
    store.write_raw_event(event_id, result.raw_events)
    issue_file = _agent_issue_file(role, store)
    linked_issue_ids: list[str] = []
    if issue_file:
        linked_issue_ids = _store_agent_issues(
            store,
            issue_file,
            role,
            result.issues,
        )
    store.append_activity(
        ActivityEvent(
            actor=role,
            stage=manifest.active_stage,
            action="agent-invoked",
            summary=f"Invoked agent role {role}.",
            status="pass" if result.ok else "blocked",
            linked_issue_ids=linked_issue_ids,
            inputs=list(invocation.context_paths),
            outputs=[issue_file] if issue_file and linked_issue_ids else [],
            commands=list(result.commands),
            message_ref=f"messages/{event_id}-response.md",
        )
    )
    return result, event_id, issue_file


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
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """[runtime]
default = "codex"

[runtimes.codex]
adapter = "codex_exec"
command = "codex"
args = ["exec", "--json"]
env = ["PATH", "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR", "CODEX_HOME", "OPENAI_API_KEY"]
structured_output = "json_schema"

[roles]
design_author = "codex"
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


def _write_project_gitignore(project_root: Path) -> None:
    path = project_root / ".gitignore"
    lines = []
    if path.exists():
        lines = path.read_text(encoding="utf-8").splitlines()
    required = ".electroboy/local/"
    if required in lines:
        return
    if lines and lines[-1] != "":
        lines.append("")
    lines.extend(
        [
            "# ElectroBoy local runtime state",
            required,
        ]
    )
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_project_bin(project_root: Path) -> None:
    bin_dir = project_root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    activate = bin_dir / "activate"
    activate.write_text(_activation_script(project_root), encoding="utf-8")
    activate.chmod(0o755)
    for name in ("electroboy", "ai-pipeline"):
        path = bin_dir / name
        path.write_text(_project_entrypoint_script(), encoding="utf-8")
        path.chmod(0o755)


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
    return f"""# ElectroBoy project activation script.
# Source this file from a POSIX-compatible shell.

_ELECTROBOY_ACTIVATED_ROOT={quoted_root}
_ELECTROBOY_PREVIOUS_PATH="${{PATH:-}}"
_ELECTROBOY_PREVIOUS_PROJECT_ROOT="${{ELECTROBOY_PROJECT_ROOT:-}}"
_ELECTROBOY_PREVIOUS_AI_PIPELINE_ROOT="${{AI_PIPELINE_PROJECT_ROOT:-}}"
_ELECTROBOY_PREVIOUS_VIRTUAL_ENV="${{VIRTUAL_ENV:-}}"
export _ELECTROBOY_ACTIVATED_ROOT
export _ELECTROBOY_PREVIOUS_PATH
export _ELECTROBOY_PREVIOUS_PROJECT_ROOT
export _ELECTROBOY_PREVIOUS_AI_PIPELINE_ROOT
export _ELECTROBOY_PREVIOUS_VIRTUAL_ENV

ELECTROBOY_PROJECT_ROOT="$_ELECTROBOY_ACTIVATED_ROOT"
PATH="$ELECTROBOY_PROJECT_ROOT/bin:$PATH"
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
        export PATH
        unset _ELECTROBOY_ACTIVATED_ROOT
        unset _ELECTROBOY_PREVIOUS_PATH
        unset _ELECTROBOY_PREVIOUS_PROJECT_ROOT
        unset _ELECTROBOY_PREVIOUS_AI_PIPELINE_ROOT
        unset _ELECTROBOY_PREVIOUS_VIRTUAL_ENV
        unset _ELECTROBOY_OWNS_PYTHON_ENV
        unset -f electroboy
        unset -f ai-pipeline
        return 0
    fi
    command electroboy --root "$ELECTROBOY_PROJECT_ROOT" "$@"
}}

ai-pipeline() {{
    electroboy "$@"
}}

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
    PROJECT_ROOT=$(CDPATH= cd -- "$SCRIPT_DIR/.." && pwd)
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
        f"Active stage: {manifest.active_stage}",
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
        if issue.get("status") in BLOCKING_ISSUE_STATUSES
        and issue.get("severity") in {"blocker", "major"}
    ]


def _record_stage_approvals(
    store: StateStore,
    stage: str,
    args: argparse.Namespace,
) -> list[str]:
    requirements = STAGE_APPROVAL_REQUIREMENTS.get(stage, [])
    errors: list[str] = []
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
        if approval_type == "author-confirmation" and not _has_successful_agent_event(
            store,
            "design_author",
            stage,
        ):
            errors.append(f"agent confirmation is missing: {stage} design_author")
            continue
        approval = ApprovalRecord(
            approval_id=f"APP-{len(store.read_approvals()) + 1:04d}",
            stage=stage,
            actor=actor,
            approval_type=approval_type,
            artifact_path=STAGE_REQUIRED_FILES.get(stage),
            summary=f"{actor} recorded {approval_type} for {stage}.",
        )
        store.append_approval(approval)
        store.append_activity(
            ActivityEvent(
                actor=actor,
                stage=stage,
                action="approval-recorded",
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
    root: Path,
    args: argparse.Namespace,
) -> list[tuple[list[str] | str, bool, str]]:
    commands: list[tuple[list[str] | str, bool, str]] = []
    artifact_commands = _artifact_validation_commands(root)
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


def _artifact_validation_commands(root: Path) -> list[str]:
    commands: list[str] = []
    for relative_path in ["docs/requirements.md", "docs/detailed-design.md"]:
        path = root / relative_path
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
    planned = planned_phases(store.root)
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


def _phase_objective(root: Path, phase_number: int) -> str:
    for phase in planned_phases(root):
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


def _create_phase_commit(
    root: Path,
    phase_number: int,
    phase: dict[str, object],
) -> tuple[str | None, str | None]:
    if not _is_git_worktree(root):
        return None, "repository is not a git worktree"
    changed_paths = _git_worktree_changed_paths(root)
    if not changed_paths:
        return None, "phase produced no repository changes to commit"
    scope_error = _phase_paths_scope_error(root, phase_number, changed_paths)
    if scope_error:
        return None, scope_error
    stage_paths = _phase_stage_paths(root, phase_number, changed_paths)
    add_error = _git_add_paths(root, stage_paths)
    if add_error:
        return None, add_error
    if _git_staged_diff_is_empty(root):
        return None, "phase produced no staged changes to commit"
    message = _phase_commit_message(phase_number, phase)
    completed = subprocess.run(
        ["git", "-C", str(root), "commit", "-m", message[0], "-m", message[1]],
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


def _git_worktree_changed_paths(root: Path) -> list[str]:
    commands = [
        ["git", "-C", str(root), "diff", "--name-only"],
        ["git", "-C", str(root), "diff", "--name-only", "--cached"],
        ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
    ]
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


def _phase_stage_paths(
    root: Path,
    phase_number: int,
    changed_paths: list[str],
) -> list[str]:
    planned_phase = next(
        (phase for phase in planned_phases(root) if phase.number == phase_number),
        None,
    )
    if planned_phase is None:
        return changed_paths
    allowed_paths = [_normalize_repo_path(path) for path in planned_phase.paths]
    if "*" in allowed_paths or "." in allowed_paths:
        return changed_paths
    return allowed_paths


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


def _git_staged_diff_is_empty(root: Path) -> bool:
    completed = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--quiet"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return completed.returncode == 0


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


def _phase_commit_message(
    phase_number: int,
    phase: dict[str, object],
) -> tuple[str, str]:
    objective = _phase_commit_objective(phase_number, phase)
    return (
        f"phase {phase_number}: {objective}",
        f"Automated phase {phase_number} commit created by electroboy code.",
    )


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
    root: Path,
    sha: str,
    phase_number: int,
    phase: dict[str, object],
) -> str | None:
    if not _git_commit_exists(root, sha):
        return f"commit does not exist: {sha}"
    if not _git_commit_reachable_from_head(root, sha):
        return f"commit is not reachable from HEAD: {sha}"
    message_error = _phase_commit_message_error(root, sha, phase_number, phase)
    if message_error:
        return message_error
    return _phase_commit_scope_error(root, sha, phase_number)


def _record_phase_commit(
    store: StateStore,
    manifest,
    phase_number: int,
    sha: str,
) -> None:
    status = store.load_phase_status()
    phase = status.phases.setdefault(str(phase_number), {})
    phase["status"] = "committed"
    phase["commit"] = sha
    phase["commit_gate"] = "passed"
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


def _phase_commit_scope_error(root: Path, sha: str, phase_number: int) -> str | None:
    return _phase_paths_scope_error(
        root,
        phase_number,
        _git_commit_changed_paths(root, sha),
    )


def _phase_paths_scope_error(
    root: Path,
    phase_number: int,
    changed_paths: list[str],
) -> str | None:
    planned_phase = next(
        (phase for phase in planned_phases(root) if phase.number == phase_number),
        None,
    )
    if planned_phase is None:
        return None
    if not planned_phase.paths:
        return f"phase {phase_number} has no Paths line for commit scope validation"
    allowed_paths = [_normalize_repo_path(path) for path in planned_phase.paths]
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
    planned = [phase.number for phase in planned_phases(store.root)]
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
        GATE_REQUIREMENTS: "docs/requirements.md",
        GATE_DESIGN: "docs/detailed-design.md",
        GATE_HUMAN_DESIGN_ACCEPTANCE: "docs/detailed-design.md",
        GATE_IMPLEMENTATION: "docs/implementation-plan.md",
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
    report_path = (
        store.run_dir(manifest.run_id) / "artifacts" / "validation-report.md"
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
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
    report_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return report_path


def _validation_source_lines(results: list[dict[str, object]]) -> list[str]:
    sources = {str(result.get("source", "unknown")) for result in results}
    lines: list[str] = []
    if "artifact" in sources:
        lines.append("artifact validation commands from requirements or design")
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
