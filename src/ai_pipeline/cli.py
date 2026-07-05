"""Command-line interface for the AI agent pipeline."""

from __future__ import annotations

import argparse
import sys
from typing import Sequence

from .artifacts import ArtifactError, ArtifactManager
from .gates import GateEngine
from .models import (
    ActivityEvent,
    GATE_DESIGN,
    GATE_HUMAN_DESIGN_ACCEPTANCE,
    GATE_IMPLEMENTATION,
    GATE_REQUIREMENTS,
    NEXT_STAGE,
    STAGE_DESIGN,
    STAGE_DESIGN_ACCEPTANCE,
    STAGE_DESIGN_REVIEW,
    STAGE_PLAN,
    STAGE_REQUIREMENTS,
    utc_now,
)
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

    completed_gate = STAGE_COMPLETED_GATES.get(stage)
    if completed_gate:
        manifest.complete_gate(completed_gate)

    next_stage = NEXT_STAGE.get(stage)
    if next_stage:
        manifest.set_active_stage(next_stage)
    store.save_manifest(manifest)
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


if __name__ == "__main__":
    raise SystemExit(main())
