from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from test_ide_lifecycle import RejectingInstaller, StaticResolver

from electroboy.ide import (
    CSPViolationStore,
    IDEEgressMode,
    IDEEgressPolicy,
    IDEEgressPolicyRegistry,
    IDEEgressRule,
    IDEError,
    IDEInstanceManager,
    IDERuntime,
    IDERuntimeMode,
    IDERuntimeOrigin,
    IDEWorkspace,
    LinuxNetworkSandbox,
    OpenVSCodeProvider,
    ide_content_security_policy,
)
from electroboy.ide.profile import MANAGED_IDE_SETTINGS


def network_probe_provider(path: Path) -> None:
    path.write_text(
        """#!/usr/bin/env python3
import argparse
import socket
import subprocess
import sys

parser = argparse.ArgumentParser(add_help=False)
parser.add_argument('--socket-path')
parser.add_argument('--connection-token')
parser.add_argument('--connection-token-file')
options, rest = parser.parse_known_args()
probe = '''import socket
s = socket.socket()
s.settimeout(.1)
print(s.connect_ex(("1.1.1.1", 443)))
'''
subprocess.run([sys.executable, '-c', probe], check=False)
server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
server.bind(options.socket_path)
server.listen()
while True:
    connection, _ = server.accept()
    connection.recv(4096)
    connection.sendall(b'HTTP/1.1 403 Forbidden\\r\\nContent-Length: 0\\r\\n\\r\\n')
    connection.close()
""",
        encoding="utf-8",
    )
    path.chmod(0o755)


class IDENetworkSandboxTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_default_policy_denies_egress(self) -> None:
        policy = IDEEgressPolicy()
        self.assertEqual(policy.mode, IDEEgressMode.DENY)

    def test_audit_mode_requires_explicit_acknowledgement(self) -> None:
        with self.assertRaisesRegex(IDEError, "explicit acknowledgement"):
            IDEEgressPolicy(IDEEgressMode.AUDIT)

        policy = IDEEgressPolicy(
            IDEEgressMode.AUDIT,
            audit_acknowledged=True,
        )
        self.assertEqual(policy.mode, IDEEgressMode.AUDIT)

    def test_workspace_registry_keeps_rules_isolated_and_temporary(self) -> None:
        registry = IDEEgressPolicyRegistry()
        configured = registry.configure(
            "workspace-a",
            mode="allowlist",
            rules=[
                {
                    "destination": "example.com",
                    "ports": [443],
                    "protocols": ["tcp"],
                }
            ],
            temporary_rules=[
                {
                    "destination": "192.0.2.10",
                    "ports": [22],
                    "protocols": ["tcp"],
                }
            ],
            audit_acknowledged=False,
        )

        self.assertEqual(configured.mode, IDEEgressMode.ALLOWLIST)
        self.assertEqual(len(configured.policy().rules), 2)
        self.assertEqual(registry.get("workspace-b").mode, IDEEgressMode.DENY)
        registry.clear("workspace-a")
        self.assertEqual(registry.get("workspace-a").mode, IDEEgressMode.DENY)

    def test_workspace_registry_rejects_unacknowledged_audit_mode(self) -> None:
        registry = IDEEgressPolicyRegistry()

        with self.assertRaisesRegex(IDEError, "explicit acknowledgement"):
            registry.configure(
                "workspace-a",
                mode="audit",
                rules=[],
                temporary_rules=[],
                audit_acknowledged=False,
            )

    def test_reports_missing_enforcement_tools(self) -> None:
        sandbox = LinuxNetworkSandbox()
        with mock.patch("electroboy.ide.sandbox.shutil.which", return_value=None):
            status = sandbox.availability()

        self.assertFalse(status["enforced"])
        self.assertEqual(status["missing_tools"], ["unshare", "bwrap", "strace"])

    def test_event_observation_is_payload_free_and_bounded(self) -> None:
        sandbox = LinuxNetworkSandbox(event_limit=10)
        for index in range(15):
            sandbox.observe_line(
                f'[pid {100 + index}<node>] connect(3, '
                '{sa_family=AF_INET, sin_port=htons(443), '
                'sin_addr=inet_addr("203.0.113.8")}, 16) = -1 ENETUNREACH'
            )

        events = sandbox.events()
        self.assertEqual(len(events), 10)
        self.assertEqual(events[-1]["process"], "node")
        self.assertEqual(events[-1]["disposition"], "blocked")
        self.assertNotIn("source", str(events))

    def test_allowlist_event_uses_resolved_rule_identity(self) -> None:
        sandbox = LinuxNetworkSandbox(
            IDEEgressPolicy(
                IDEEgressMode.ALLOWLIST,
                (IDEEgressRule("203.0.113.8", (443,)),),
            )
        )
        sandbox._resolved_rules[("203.0.113.8", 443, "tcp")] = "rule-1"
        sandbox.observe_line(
            'connect(3, {sa_family=AF_INET, sin_port=htons(443), '
            'sin_addr=inet_addr("203.0.113.8")}, 16) = 0'
        )

        self.assertEqual(sandbox.events()[0]["disposition"], "allowed")
        self.assertEqual(sandbox.events()[0]["rule"], "rule-1")

    def test_udp_dns_attempt_is_logged_without_payload(self) -> None:
        sandbox = LinuxNetworkSandbox()
        sandbox.observe_line(
            '[pid 420<node>] sendto(7, "redacted", 32, MSG_NOSIGNAL, '
            '{sa_family=AF_INET, sin_port=htons(53), '
            'sin_addr=inet_addr("1.1.1.1")}, 16) = -1 ENETUNREACH'
        )

        event = sandbox.events()[0]
        self.assertEqual(event["process_id"], 420)
        self.assertEqual(event["protocol"], "udp")
        self.assertTrue(event["dns"])
        self.assertEqual(event["destination"], "1.1.1.1")
        self.assertNotIn("redacted", str(event))

    def test_csp_is_enforced_except_in_explicit_audit_mode(self) -> None:
        deny_header, deny_value = ide_content_security_policy(
            IDEEgressMode.DENY,
            provider_policy=(
                "script-src 'self' 'nonce-bootstrap' 'sha256-dGVzdA==' "
                "'unsafe-inline' https://unsafe.example"
            ),
        )
        audit_header, _audit_value = ide_content_security_policy(
            IDEEgressMode.AUDIT
        )

        self.assertEqual(deny_header, "Content-Security-Policy")
        self.assertIn("connect-src 'self'", deny_value)
        self.assertIn("'nonce-bootstrap'", deny_value)
        self.assertIn("'sha256-dGVzdA=='", deny_value)
        self.assertNotIn("'unsafe-inline'", deny_value.split("; ")[4])
        self.assertNotIn("unsafe.example", deny_value)
        self.assertEqual(audit_header, "Content-Security-Policy-Report-Only")

    def test_csp_reports_drop_paths_queries_and_fragments(self) -> None:
        store = CSPViolationStore(limit=10)
        event = store.record(
            {
                "csp-report": {
                    "effective-directive": "connect-src",
                    "blocked-uri": "https://example.com/private/code?token=secret",
                    "document-uri": "http://127.0.0.1:9001/ide/workspace/file.py#L9",
                    "status-code": 200,
                }
            },
            workspace_id="workspace-a",
        )

        assert event is not None
        self.assertEqual(event["blocked_origin"], "https://example.com")
        self.assertEqual(event["document_origin"], "http://127.0.0.1:9001")
        self.assertEqual(event["workspace_id"], "workspace-a")
        self.assertEqual(store.events("workspace-b"), [])
        self.assertNotIn("private", str(event))
        self.assertNotIn("secret", str(event))

    def test_audit_and_allowlist_modes_start_and_cleanup(self) -> None:
        executable = self.root / "provider"
        from test_ide_lifecycle import fake_openvscode

        fake_openvscode(executable)
        runtime = IDERuntime(
            "openvscode",
            "test",
            "linux",
            "x86_64",
            executable,
            IDERuntimeOrigin.SYSTEM,
        )
        policies = (
            IDEEgressPolicy(IDEEgressMode.AUDIT, audit_acknowledged=True),
            IDEEgressPolicy(
                IDEEgressMode.ALLOWLIST,
                (IDEEgressRule("203.0.113.8", (443,)),),
            ),
        )
        for index, policy in enumerate(policies):
            sandbox = LinuxNetworkSandbox(policy)
            provider = OpenVSCodeProvider(process_launcher=sandbox)
            manager = IDEInstanceManager(
                provider,
                StaticResolver(runtime),
                RejectingInstaller(),
                self.root / f"data-{index}",
                startup_timeout=5,
            )
            instance, _started = manager.start(
                IDEWorkspace(f"workspace-{index}", self.root),
                mode=IDERuntimeMode.SYSTEM,
            )
            self.assertTrue(sandbox.availability()["enforced"])
            self.assertTrue(Path(instance.endpoint.address).exists())
            manager.stop_all()
            self.assertFalse(Path(instance.endpoint.address).exists())

    def test_deny_mode_blocks_spawned_child_and_keeps_unix_control(self) -> None:
        executable = self.root / "probe-provider"
        network_probe_provider(executable)
        runtime = IDERuntime(
            "openvscode",
            "test",
            "linux",
            "x86_64",
            executable,
            IDERuntimeOrigin.SYSTEM,
        )
        sandbox = LinuxNetworkSandbox()
        provider = OpenVSCodeProvider(process_launcher=sandbox)
        manager = IDEInstanceManager(
            provider,
            StaticResolver(runtime),
            RejectingInstaller(),
            self.root / "data",
            startup_timeout=5,
        )

        instance, started = manager.start(
            IDEWorkspace("workspace-1", self.root),
            mode=IDERuntimeMode.SYSTEM,
        )
        time.sleep(0.1)

        self.assertTrue(started)
        self.assertTrue(Path(instance.endpoint.address).exists())
        self.assertTrue(sandbox.availability()["enforced"])
        self.assertTrue(
            any(event["disposition"] == "blocked" for event in sandbox.events())
        )
        settings = (
            instance.profile.user_data / "User" / "settings.json"
        ).read_text(encoding="utf-8")
        for key in MANAGED_IDE_SETTINGS:
            self.assertIn(key, settings)
        manager.stop_all()


if __name__ == "__main__":
    unittest.main()
