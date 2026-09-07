"""Workspace-scoped IDE egress configuration."""

from __future__ import annotations

import threading
from dataclasses import dataclass

from .sandbox import IDEEgressMode, IDEEgressPolicy, IDEEgressRule


@dataclass(frozen=True)
class IDEWorkspaceEgress:
    """Configured and temporary rules for one active workspace."""

    mode: IDEEgressMode
    rules: tuple[IDEEgressRule, ...] = ()
    temporary_rules: tuple[IDEEgressRule, ...] = ()

    def policy(self) -> IDEEgressPolicy:
        return IDEEgressPolicy(
            self.mode,
            (*self.rules, *self.temporary_rules),
            audit_acknowledged=self.mode is IDEEgressMode.AUDIT,
        )

    def payload(self) -> dict[str, object]:
        return {
            "mode": self.mode.value,
            "rules": [_rule_payload(rule) for rule in self.rules],
            "temporary_rules": [
                _rule_payload(rule) for rule in self.temporary_rules
            ],
        }


class IDEEgressPolicyRegistry:
    """Own mutable egress settings outside process-launching code."""

    def __init__(self, default_mode: IDEEgressMode = IDEEgressMode.DENY) -> None:
        self.default_mode = default_mode
        self._entries: dict[str, IDEWorkspaceEgress] = {}
        self._lock = threading.RLock()

    def get(self, workspace_id: str) -> IDEWorkspaceEgress:
        with self._lock:
            return self._entries.get(
                workspace_id,
                IDEWorkspaceEgress(self.default_mode),
            )

    def configure(
        self,
        workspace_id: str,
        *,
        mode: str,
        rules: object,
        temporary_rules: object,
        audit_acknowledged: bool,
    ) -> IDEWorkspaceEgress:
        selected = IDEEgressMode(str(mode).strip().lower())
        if selected is IDEEgressMode.AUDIT and not audit_acknowledged:
            IDEEgressPolicy(selected)
        entry = IDEWorkspaceEgress(
            selected,
            _parse_rules(rules),
            _parse_rules(temporary_rules),
        )
        entry.policy()
        with self._lock:
            self._entries[workspace_id] = entry
        return entry

    def clear(self, workspace_id: str) -> None:
        with self._lock:
            self._entries.pop(workspace_id, None)


def _parse_rules(value: object) -> tuple[IDEEgressRule, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError("egress rules must be an array")
    rules: list[IDEEgressRule] = []
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("each egress rule must be an object")
        ports = row.get("ports", ())
        protocols = row.get("protocols", ("tcp",))
        if not isinstance(ports, list) or not isinstance(protocols, list):
            raise ValueError("egress rule ports and protocols must be arrays")
        rules.append(
            IDEEgressRule(
                destination=str(row.get("destination") or ""),
                ports=tuple(int(port) for port in ports),
                protocols=tuple(str(protocol).lower() for protocol in protocols),
            )
        )
    return tuple(rules)


def _rule_payload(rule: IDEEgressRule) -> dict[str, object]:
    return {
        "destination": rule.destination,
        "ports": list(rule.ports),
        "protocols": list(rule.protocols),
    }
