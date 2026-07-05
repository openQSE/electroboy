"""Command-line interface for the AI agent pipeline."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .artifacts import ArtifactError, ArtifactManager
from .gates import GateEngine
from .models import (
    ActivityEvent,
    DecisionRecord,
    GATE_DESIGN,
    GATE_HUMAN_DESIGN_ACCEPTANCE,
    GATE_IMPLEMENTATION,
    GATE_REQUIREMENTS,
    NEXT_STAGE,
    ReviewIssue,
    STAGE_DESIGN,
    STAGE_DESIGN_ACCEPTANCE,
    STAGE_DESIGN_REVIEW,
    STAGE_PLAN,
    STAGE_REQUIREMENTS,
    utc_now,
)
from .adapters.base import AgentInvocation
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ai-pipeline")
    parser.add_argument(
        "--root",
        default=".",
        help="repository root containing pipeline artifacts",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init", help="initialize a pipeline run")
    init.add_argument("--run-id", help="explicit run id for deterministic tests")
    init.add_argument("--force", action="store_true", help="replace current run")

    subparsers.add_parser("status", help="show current pipeline status")
    subparsers.add_parser("resume", help="show the stage to resume")

    stage = subparsers.add_parser("stage", help="complete the active stage")
    stage.add_argument(
        "stage",
        choices=[
            STAGE_REQUIREMENTS,
            STAGE_DESIGN,
            STAGE_DESIGN_REVIEW,
            STAGE_DESIGN_ACCEPTANCE,
            STAGE_PLAN,
        ],
    )

    gate = subparsers.add_parser("gate", help="evaluate a named gate")
    gate.add_argument("gate")

    plan = subparsers.add_parser("plan", help="manage implementation plan")
    plan_subparsers = plan.add_subparsers(dest="plan_command", required=True)
    plan_subparsers.add_parser("check", help="check plan traceability")
    plan_update = plan_subparsers.add_parser("update", help="record plan update")
    plan_update.add_argument("--reason", required=True)

    issues = subparsers.add_parser("issues", help="manage review issues")
    issue_subparsers = issues.add_subparsers(dest="issue_command", required=True)
    issue_add = issue_subparsers.add_parser("add", help="add a review issue")
    issue_add.add_argument("file")
    issue_add.add_argument("--id", required=True)
    issue_add.add_argument("--source", required=True)
    issue_add.add_argument("--severity", required=True)
    issue_add.add_argument("--summary", required=True)
    issue_add.add_argument("--phase", type=int)
    issue_add.add_argument("--owner")
    issue_subparsers.add_parser("list", help="list review issues").add_argument("file")
    issue_resolve = issue_subparsers.add_parser("resolve", help="resolve issue")
    issue_resolve.add_argument("file")
    issue_resolve.add_argument("id")

    agent = subparsers.add_parser("agent", help="invoke configured agent runtimes")
    agent_subparsers = agent.add_subparsers(dest="agent_command", required=True)
    agent_run = agent_subparsers.add_parser("run", help="run an agent role")
    agent_run.add_argument("role")
    agent_run.add_argument("--prompt", required=True)
    agent_run.add_argument("--context", action="append", default=[])

    artifacts = subparsers.add_parser("artifacts", help="manage artifacts")
    artifact_subparsers = artifacts.add_subparsers(
        dest="artifact_command",
        required=True,
    )
    artifact_init = artifact_subparsers.add_parser(
        "init",
        help="create missing artifact templates",
    )
    artifact_init.add_argument(
        "--overwrite",
        action="store_true",
        help="overwrite existing artifact files",
    )
    snapshot = artifact_subparsers.add_parser(
        "snapshot",
        help="snapshot one artifact or all artifacts",
    )
    snapshot.add_argument("path", nargs="?", help="artifact path to snapshot")
    snapshot.add_argument("--all", action="store_true", help="snapshot all artifacts")

    change = subparsers.add_parser("change", help="manage change-control state")
    change_subparsers = change.add_subparsers(dest="change_command", required=True)
    change_subparsers.add_parser("status", help="list change-control requests")
    change_open = change_subparsers.add_parser("open", help="open a request")
    change_open.add_argument("--baseline", required=True)
    change_open.add_argument("--reason", required=True)
    change_classify = change_subparsers.add_parser("classify", help="classify request")
    change_classify.add_argument("id")
    change_reopen = change_subparsers.add_parser("reopen", help="reopen request")
    change_reopen.add_argument("id")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = StateStore(args.root)
    engine = GateEngine(args.root)

    try:
        if args.command == "init":
            return _cmd_init(store, args)
        if args.command == "status":
            return _cmd_status(store)
        if args.command == "resume":
            return _cmd_resume(store)
        if args.command == "stage":
            return _cmd_stage(store, engine, args.stage)
        if args.command == "gate":
            return _cmd_gate(store, engine, args.gate)
        if args.command == "plan":
            return _cmd_plan(store, args)
        if args.command == "issues":
            return _cmd_issues(store, args)
        if args.command == "agent":
            return _cmd_agent(store, args)
        if args.command == "artifacts":
            return _cmd_artifacts(store, args)
        if args.command == "change":
            return _cmd_change(store, args)
    except StateError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    except ArtifactError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2

    parser.print_help(sys.stderr)
    return 2


def _cmd_init(store: StateStore, args: argparse.Namespace) -> int:
    manifest = store.init_run(run_id=args.run_id, force=args.force)
    print(f"created run: {manifest.run_id}")
    print(f"active stage: {manifest.active_stage}")
    return 0


def _cmd_status(store: StateStore) -> int:
    manifest = store.load_current_manifest()
    print(f"run id: {manifest.run_id}")
    print(f"active stage: {manifest.active_stage}")
    print("completed gates:")
    for gate in manifest.completed_gates:
        print(f"  - {gate}")
    if not manifest.completed_gates:
        print("  - none")
    return 0


def _cmd_resume(store: StateStore) -> int:
    manifest = store.load_current_manifest()
    print(f"resume stage: {manifest.active_stage}")
    return 0


def _cmd_stage(store: StateStore, engine: GateEngine, stage: str) -> int:
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
    if stage == STAGE_PLAN and not _plan_has_traceability(store.root):
        _print_gate_failure(["implementation plan lacks requirements traceability"])
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
            gate=completed_gate,
            action="stage-completed",
            summary=f"Completed stage {stage}.",
        )
    )
    print(f"completed stage: {stage}")
    print(f"active stage: {manifest.active_stage}")
    return 0


def _cmd_gate(store: StateStore, engine: GateEngine, gate: str) -> int:
    manifest = store.load_current_manifest()
    result = engine.evaluate(gate, manifest)
    print(f"{result.name}: {result.status}")
    for message in result.messages:
        print(f"  - {message}")
    return 0 if result.passed else 1


def _cmd_plan(store: StateStore, args: argparse.Namespace) -> int:
    if args.plan_command == "check":
        if _plan_has_traceability(store.root):
            print("implementation plan traceability: pass")
            return 0
        print("implementation plan traceability: blocked")
        return 1

    if args.plan_command == "update":
        manifest = store.load_current_manifest()
        phase_status = store.load_phase_status()
        if phase_status.active_phase is not None:
            phase = phase_status.phases.setdefault(str(phase_status.active_phase), {})
            phase["plan_current"] = True
            store.save_phase_status(phase_status)
        decision = DecisionRecord(
            decision_id=f"PLAN-{len(store.read_decisions()) + 1:04d}",
            stage=manifest.active_stage,
            summary="Implementation plan updated",
            rationale=args.reason,
        )
        store.append_decision(decision)
        snapshot = ArtifactManager(store.root).snapshot(
            manifest.run_id,
            "docs/implementation-plan.md",
            "plan-updated",
        )
        store.append_artifact_snapshot(snapshot)
        store.append_activity(
            ActivityEvent(
                actor="orchestrator",
                stage=manifest.active_stage,
                action="plan-updated",
                summary=f"{args.reason} Decision: {decision.decision_id}.",
                artifact_snapshot_refs=[snapshot.snapshot_path],
                outputs=[
                    "docs/implementation-plan.md",
                    "decisions.jsonl",
                    snapshot.snapshot_path,
                ],
            )
        )
        print("recorded implementation plan update")
        return 0

    return 2


def _cmd_issues(store: StateStore, args: argparse.Namespace) -> int:
    if args.issue_command == "add":
        issue = ReviewIssue(
            issue_id=args.id,
            source=args.source,
            severity=args.severity,
            status="open",
            summary=args.summary,
            phase=args.phase,
            owner=args.owner,
        )
        store.append_review_issue(args.file, issue)
        print(f"added issue: {args.id}")
        return 0

    if args.issue_command == "list":
        issues = store.read_review_issues(args.file)
        print(f"issues: {len(issues)}")
        for issue in issues:
            print(f"  - {issue['issue_id']}: {issue['status']} {issue['summary']}")
        return 0

    if args.issue_command == "resolve":
        issues = store.read_review_issues(args.file)
        found = False
        for issue in issues:
            if issue.get("issue_id") == args.id:
                issue["status"] = "resolved"
                found = True
        if not found:
            print(f"error: issue not found: {args.id}", file=sys.stderr)
            return 1
        store.replace_review_issues(args.file, issues)
        print(f"resolved issue: {args.id}")
        return 0

    return 2


def _cmd_agent(store: StateStore, args: argparse.Namespace) -> int:
    if args.agent_command == "run":
        result, _event_id, _issue_file = _invoke_agent_role(
            store,
            role=args.role,
            prompt=args.prompt,
            context_paths=list(args.context),
        )
        print(result.final_message, end="" if result.final_message.endswith("\n") else "\n")
        return 0 if result.ok else 1
    return 2


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


def _cmd_artifacts(store: StateStore, args: argparse.Namespace) -> int:
    manager = ArtifactManager(store.root)
    if args.artifact_command == "init":
        written = manager.init_templates(overwrite=args.overwrite)
        if written:
            for path in written:
                print(f"created artifact template: {path}")
        else:
            print("artifact templates already exist")
        return 0

    if args.artifact_command == "snapshot":
        manifest = store.load_current_manifest()
        event_id = f"snapshot-{len(manifest.completed_gates) + 1}"
        if args.all:
            snapshots = manager.snapshot_all(manifest.run_id, event_id)
        elif args.path:
            snapshots = [manager.snapshot(manifest.run_id, args.path, event_id)]
        else:
            print("error: provide an artifact path or --all", file=sys.stderr)
            return 2
        for snapshot in snapshots:
            store.append_artifact_snapshot(snapshot)
            print(f"snapshot: {snapshot.artifact_path} -> {snapshot.snapshot_path}")
        return 0

    return 2


def _cmd_change(store: StateStore, args: argparse.Namespace) -> int:
    if args.change_command == "status":
        requests = store.read_change_requests()
        print(f"change requests: {len(requests)}")
        for request in requests:
            print(f"  - {request['id']}: {request['baseline']}")
        return 0

    if args.change_command == "open":
        manifest = store.load_current_manifest()
        request = {
            "schema_version": 1,
            "id": f"CR-{len(store.read_change_requests()) + 1:04d}",
            "run_id": manifest.run_id,
            "baseline": args.baseline,
            "reason": args.reason,
            "status": "open",
            "created_at": utc_now(),
        }
        store.append_change_request(request)
        store.append_activity(
            ActivityEvent(
                actor="orchestrator",
                stage=manifest.active_stage,
                action="change-request-opened",
                summary=f"Opened change request {request['id']}.",
            )
        )
        print(f"opened change request: {request['id']}")
        return 0

    print("error: change command is not implemented yet", file=sys.stderr)
    return 2


def _print_gate_failure(messages: list[str]) -> None:
    print("blocked:", file=sys.stderr)
    for message in messages:
        print(f"  - {message}", file=sys.stderr)


def _blocking_issues(store: StateStore, file_name: str) -> list[dict[str, object]]:
    return [
        issue
        for issue in store.read_review_issues(file_name)
        if issue.get("status") in {"open", "accepted"}
        and issue.get("severity") in {"blocker", "major"}
    ]


def _plan_has_traceability(root: Path) -> bool:
    plan = root / "docs" / "implementation-plan.md"
    if not plan.exists():
        return False
    text = plan.read_text(encoding="utf-8").lower()
    return "phase" in text and "requirement" in text


if __name__ == "__main__":
    raise SystemExit(main())
