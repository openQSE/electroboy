"""Linux network sandboxing and redacted IDE egress observation."""

from __future__ import annotations

import ipaddress
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from urllib.parse import urlsplit

from .domain import IDEError, IDEErrorCategory, IDEProfile
from .processes import IDEProcessLaunch, IDEProcessLauncher

_CONNECT = re.compile(
    r"(?:\[pid\s+(?P<pid>\d+)(?:<(?P<process>[^>]+)>)?\]\s+)?"
    r"connect\([^,]+,\s+\{sa_family=AF_INET,\s+sin_port=htons\((?P<port>\d+)\),"
    r'\s+sin_addr=inet_addr\("(?P<address>[^"\s]+)"\)'
)
_SENDTO = re.compile(
    r"(?:\[pid\s+(?P<pid>\d+)(?:<(?P<process>[^>]+)>)?\]\s+)?"
    r"sendto\([^,]+,.*?,\s*\d+,\s*[^,]+,\s*"
    r"\{sa_family=AF_INET,\s+sin_port=htons\((?P<port>\d+)\),"
    r'\s+sin_addr=inet_addr\("(?P<address>[^"\s]+)"\)'
)
_CSP_INLINE_SCRIPT_AUTHORIZER = re.compile(
    r"^'(?:nonce-[A-Za-z0-9+/_=-]+|sha(?:256|384|512)-[A-Za-z0-9+/=]+)'$"
)


class IDEEgressMode(str, Enum):
    """Network behavior for the complete IDE process tree."""

    DENY = "deny"
    ALLOWLIST = "allowlist"
    AUDIT = "audit"


@dataclass(frozen=True)
class IDEEgressRule:
    """One workspace-approved destination and port set."""

    destination: str
    ports: tuple[int, ...]
    protocols: tuple[str, ...] = ("tcp",)

    def __post_init__(self) -> None:
        if not self.destination.strip():
            raise ValueError("egress destination is required")
        if not self.ports or any(port < 1 or port > 65535 for port in self.ports):
            raise ValueError("egress ports must be between 1 and 65535")
        if any(protocol not in ("tcp", "udp") for protocol in self.protocols):
            raise ValueError("egress protocols must be tcp or udp")


@dataclass(frozen=True)
class IDEEgressPolicy:
    """Workspace-scoped egress policy supplied to the Linux adapter."""

    mode: IDEEgressMode = IDEEgressMode.DENY
    rules: tuple[IDEEgressRule, ...] = ()
    audit_acknowledged: bool = False

    def __post_init__(self) -> None:
        if self.mode is IDEEgressMode.AUDIT and not self.audit_acknowledged:
            raise IDEError(
                IDEErrorCategory.POLICY_UNAVAILABLE,
                "audit mode requires explicit acknowledgement of unrestricted egress",
                recoverable=True,
            )


@dataclass(frozen=True)
class IDEEgressEvent:
    """A bounded, payload-free record of an outbound connection attempt."""

    timestamp: float
    process_id: int | None
    process: str | None
    protocol: str
    destination: str
    port: int
    rule: str | None
    disposition: str

    def payload(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "process_id": self.process_id,
            "process": self.process,
            "protocol": self.protocol,
            "dns": self.port == 53,
            "destination": self.destination,
            "port": self.port,
            "rule": self.rule,
            "disposition": self.disposition,
        }


class CSPViolationStore:
    """Keep bounded browser policy reports without URL payload details."""

    def __init__(self, limit: int = 100) -> None:
        self._events: deque[dict[str, object]] = deque(maxlen=max(10, limit))
        self._lock = threading.Lock()

    def record(
        self,
        payload: object,
        *,
        workspace_id: str = "",
    ) -> dict[str, object] | None:
        if not isinstance(payload, dict):
            return None
        report = payload.get("csp-report", payload)
        if not isinstance(report, dict):
            return None
        event = {
            "timestamp": time.time(),
            "workspace_id": workspace_id,
            "effective_directive": _bounded_text(
                report.get("effective-directive")
                or report.get("effectiveDirective")
            ),
            "disposition": _bounded_text(report.get("disposition")),
            "blocked_origin": _origin(report.get("blocked-uri")),
            "document_origin": _origin(report.get("document-uri")),
            "status_code": _integer_or_none(report.get("status-code")),
        }
        with self._lock:
            self._events.append(event)
        return event

    def events(self, workspace_id: str | None = None) -> list[dict[str, object]]:
        with self._lock:
            events = list(self._events)
        if workspace_id is None:
            return events
        return [
            event for event in events if event.get("workspace_id") == workspace_id
        ]

    def clear(self, workspace_id: str | None = None) -> None:
        with self._lock:
            if workspace_id is None:
                self._events.clear()
                return
            retained = [
                event
                for event in self._events
                if event.get("workspace_id") != workspace_id
            ]
            self._events.clear()
            self._events.extend(retained)


class LinuxNetworkSandbox:
    """Launch an IDE tree in a kernel network namespace."""

    def __init__(
        self,
        policy: IDEEgressPolicy | None = None,
        *,
        event_limit: int = 200,
    ) -> None:
        self.policy = policy or IDEEgressPolicy()
        self.event_limit = max(10, event_limit)
        self._events: deque[IDEEgressEvent] = deque(maxlen=self.event_limit)
        self._events_lock = threading.Lock()
        self._resolved_rules: dict[tuple[str, int, str], str] = {}

    def availability(self) -> dict[str, object]:
        required = ["unshare", "bwrap", "strace"]
        if self.policy.mode is not IDEEgressMode.DENY:
            required.extend(("slirp4netns", "nsenter"))
        if self.policy.mode is IDEEgressMode.ALLOWLIST:
            required.append("nft")
        missing = [name for name in required if shutil.which(name) is None]
        return {
            "mode": self.policy.mode.value,
            "enforced": not missing,
            "implementation": "linux-user-network-namespace",
            "missing_tools": missing,
            "warning": (
                "Audit mode permits external traffic and records destinations."
                if self.policy.mode is IDEEgressMode.AUDIT
                else None
            ),
        }

    def launch(
        self,
        arguments: list[str],
        *,
        cwd: Path,
        profile: IDEProfile,
    ) -> IDEProcessLaunch:
        availability = self.availability()
        if not availability["enforced"]:
            names = ", ".join(availability["missing_tools"])
            raise IDEError(
                IDEErrorCategory.POLICY_UNAVAILABLE,
                f"IDE network policy cannot be enforced; missing tools: {names}",
            )
        sandbox_root = profile.root / "network-sandbox"
        sandbox_root.mkdir(parents=True, exist_ok=True)
        temporary, runtime, cache, state = _prepare_runtime_directories(sandbox_root)
        ready = sandbox_root / "namespace.ready"
        go = sandbox_root / "namespace.go"
        ready.unlink(missing_ok=True)
        go.unlink(missing_ok=True)
        resolv_conf = sandbox_root / "resolv.conf"
        resolv_conf.write_text("nameserver 10.0.2.3\n", encoding="utf-8")
        wrapped = self._command(
            arguments,
            cwd,
            profile,
            ready,
            go,
            resolv_conf,
            temporary,
            runtime,
            cache,
            state,
        )
        try:
            process = subprocess.Popen(
                wrapped,
                cwd=cwd,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
            )
        except OSError as error:
            raise IDEError(
                IDEErrorCategory.POLICY_UNAVAILABLE,
                f"could not start IDE network sandbox: {error}",
            ) from error
        helpers: list[subprocess.Popen[bytes]] = []
        try:
            if self.policy.mode is not IDEEgressMode.DENY:
                _wait_for_path(ready, process, 5)
                helpers.append(self._start_slirp(process.pid))
                self._wait_for_interface(process.pid)
                if self.policy.mode is IDEEgressMode.ALLOWLIST:
                    self._install_allowlist(process.pid)
                go.touch()
        except Exception:
            process.terminate()
            process.wait(timeout=2)
            for helper in helpers:
                helper.terminate()
                helper.wait(timeout=2)
            raise

        def cleanup() -> None:
            for helper in helpers:
                if helper.poll() is None:
                    helper.terminate()
                    try:
                        helper.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        helper.kill()
                        helper.wait(timeout=2)
            ready.unlink(missing_ok=True)
            go.unlink(missing_ok=True)
            shutil.rmtree(temporary, ignore_errors=True)
            shutil.rmtree(runtime, ignore_errors=True)

        return IDEProcessLaunch(
            process,
            line_observer=self.observe_line,
            cleanup=cleanup,
            enforcement=availability,
        )

    def events(self) -> list[dict[str, object]]:
        with self._events_lock:
            return [event.payload() for event in self._events]

    def clear_events(self) -> None:
        with self._events_lock:
            self._events.clear()


    def observe_line(self, line: str) -> None:
        match = _CONNECT.search(line)
        protocol = "tcp"
        if match is None:
            match = _SENDTO.search(line)
            protocol = "udp"
        if match is None:
            return
        address = match.group("address")
        port = int(match.group("port"))
        rule = self._resolved_rules.get((address, port, protocol))
        if self.policy.mode is IDEEgressMode.DENY:
            disposition = "blocked"
        elif self.policy.mode is IDEEgressMode.AUDIT:
            disposition = "allowed"
        else:
            disposition = "allowed" if rule else "blocked"
        event = IDEEgressEvent(
            timestamp=time.time(),
            process_id=(int(match.group("pid")) if match.group("pid") else None),
            process=match.group("process"),
            protocol=protocol,
            destination=address,
            port=port,
            rule=rule,
            disposition=disposition,
        )
        with self._events_lock:
            self._events.append(event)

    def _command(
        self,
        arguments: list[str],
        cwd: Path,
        profile: IDEProfile,
        ready: Path,
        go: Path,
        resolv_conf: Path,
        temporary: Path,
        runtime: Path,
        cache: Path,
        state: Path,
    ) -> list[str]:
        runtime_mount = f"/run/user/{os.getuid()}"
        trace = [
            "strace",
            "-f",
            "-e",
            "trace=network",
            "-s",
            "0",
            "-Y",
            "--",
            *arguments,
        ]
        command = [
            "unshare",
            "--user",
            "--map-root-user",
            "--net",
            "--fork",
            "--kill-child=SIGKILL",
            "bwrap",
            "--die-with-parent",
            "--ro-bind",
            "/",
            "/",
            "--bind",
            str(temporary),
            "/tmp",
            "--bind",
            str(cwd),
            str(cwd),
            "--bind",
            str(profile.root),
            str(profile.root),
            "--bind",
            str(runtime),
            runtime_mount,
            "--dev",
            "/dev",
            "--proc",
            "/proc",
            "--setenv",
            "TMPDIR",
            "/tmp",
            "--setenv",
            "XDG_RUNTIME_DIR",
            runtime_mount,
            "--setenv",
            "XDG_CACHE_HOME",
            str(cache),
            "--setenv",
            "XDG_STATE_HOME",
            str(state),
        ]
        if self.policy.mode is IDEEgressMode.DENY:
            return [*command, "--", *trace]
        return [
            *command,
            "--ro-bind",
            str(resolv_conf),
            "/etc/resolv.conf",
            "--",
            "sh",
            "-c",
            'ready=$1; go=$2; shift 2; : > "$ready"; '
            'while [ ! -e "$go" ]; do sleep 0.05; done; exec "$@"',
            "electroboy-ide-sandbox",
            str(ready),
            str(go),
            *trace,
        ]

    @staticmethod
    def _start_slirp(namespace_pid: int) -> subprocess.Popen[bytes]:
        return subprocess.Popen(
            [
                "slirp4netns",
                "--configure",
                "--disable-host-loopback",
                "--enable-sandbox",
                "--enable-seccomp",
                str(namespace_pid),
                "tap0",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @staticmethod
    def _wait_for_interface(namespace_pid: int) -> None:
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            completed = _namespace_command(
                namespace_pid,
                ["ip", "address", "show", "tap0"],
                check=False,
            )
            if completed.returncode == 0:
                return
            time.sleep(0.05)
        raise IDEError(
            IDEErrorCategory.POLICY_UNAVAILABLE,
            "IDE egress broker did not configure its namespace interface",
        )

    def _install_allowlist(self, namespace_pid: int) -> None:
        commands = [
            ["nft", "add", "table", "inet", "electroboy"],
            [
                "nft",
                "add",
                "chain",
                "inet",
                "electroboy",
                "output",
                "{ type filter hook output priority 0; policy drop; }",
            ],
            [
                "nft",
                "add",
                "rule",
                "inet",
                "electroboy",
                "output",
                "oifname",
                "lo",
                "accept",
            ],
            [
                "nft",
                "add",
                "rule",
                "inet",
                "electroboy",
                "output",
                "ip",
                "daddr",
                "10.0.2.3",
                "udp",
                "dport",
                "53",
                "accept",
            ],
        ]
        for rule_number, rule in enumerate(self.policy.rules, start=1):
            for address in _resolve_ipv4(rule.destination):
                for protocol in rule.protocols:
                    for port in rule.ports:
                        name = f"rule-{rule_number}"
                        self._resolved_rules[(address, port, protocol)] = name
                        commands.append(
                            [
                                "nft",
                                "add",
                                "rule",
                                "inet",
                                "electroboy",
                                "output",
                                "ip",
                                "daddr",
                                address,
                                protocol,
                                "dport",
                                str(port),
                                "accept",
                            ]
                        )
        for command in commands:
            _namespace_command(namespace_pid, command)


def _prepare_runtime_directories(
    sandbox_root: Path,
) -> tuple[Path, Path, Path, Path]:
    temporary = sandbox_root / "tmp"
    runtime = sandbox_root / "runtime"
    cache = sandbox_root / "cache"
    state = sandbox_root / "state"
    for directory in (temporary, runtime):
        shutil.rmtree(directory, ignore_errors=True)
    for directory in (temporary, runtime, cache, state):
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
    return temporary, runtime, cache, state


class WorkspaceNetworkSandbox(IDEProcessLauncher):
    """Route launches and diagnostics through one sandbox per IDE profile."""

    def __init__(self, default_policy: IDEEgressPolicy | None = None) -> None:
        self.default_policy = default_policy or IDEEgressPolicy()
        self._sandboxes: dict[Path, LinuxNetworkSandbox] = {}
        self._workspaces: dict[Path, str] = {}
        self._lock = threading.RLock()

    def configure(
        self,
        workspace_id: str,
        profile: IDEProfile,
        policy: IDEEgressPolicy,
    ) -> LinuxNetworkSandbox:
        key = profile.root.resolve()
        with self._lock:
            sandbox = LinuxNetworkSandbox(policy)
            self._sandboxes[key] = sandbox
            self._workspaces[key] = workspace_id
            return sandbox

    def launch(
        self,
        arguments: list[str],
        *,
        cwd: Path,
        profile: IDEProfile,
    ) -> IDEProcessLaunch:
        return self._sandbox(profile).launch(arguments, cwd=cwd, profile=profile)

    def availability(self, profile: IDEProfile | None = None) -> dict[str, object]:
        if profile is None:
            return LinuxNetworkSandbox(self.default_policy).availability()
        return self._sandbox(profile).availability()

    def events(self, profile: IDEProfile | None = None) -> list[dict[str, object]]:
        if profile is not None:
            key = profile.root.resolve()
            sandbox = self._sandbox(profile)
            workspace_id = self._workspace_id(key)
            return [
                {**event, "workspace_id": workspace_id}
                for event in sandbox.events()
            ]
        with self._lock:
            entries = tuple(self._sandboxes.items())
            workspaces = dict(self._workspaces)
        events = [
            {**event, "workspace_id": workspaces.get(key, "")}
            for key, sandbox in entries
            for event in sandbox.events()
        ]
        return sorted(events, key=lambda event: float(event["timestamp"]))

    def clear_events(self, profile: IDEProfile | None = None) -> None:
        if profile is not None:
            self._sandbox(profile).clear_events()
            return
        with self._lock:
            sandboxes = tuple(self._sandboxes.values())
        for sandbox in sandboxes:
            sandbox.clear_events()

    def remove(self, profile: IDEProfile) -> None:
        key = profile.root.resolve()
        with self._lock:
            self._sandboxes.pop(key, None)
            self._workspaces.pop(key, None)

    def _sandbox(self, profile: IDEProfile) -> LinuxNetworkSandbox:
        key = profile.root.resolve()
        with self._lock:
            return self._sandboxes.setdefault(
                key,
                LinuxNetworkSandbox(self.default_policy),
            )

    def _workspace_id(self, key: Path) -> str:
        with self._lock:
            return self._workspaces.get(key, "")


def _resolve_ipv4(destination: str) -> tuple[str, ...]:
    try:
        address = ipaddress.ip_address(destination)
    except ValueError:
        return tuple(
            sorted(
                {
                    row[4][0]
                    for row in socket.getaddrinfo(
                        destination,
                        None,
                        family=socket.AF_INET,
                    )
                }
            )
        )
    if address.version != 4:
        raise IDEError(
            IDEErrorCategory.POLICY_UNAVAILABLE,
            "the initial Linux IDE allowlist supports IPv4 destinations only",
        )
    return (str(address),)


def _namespace_command(
    namespace_pid: int,
    command: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "nsenter",
            "-t",
            str(namespace_pid),
            "-U",
            "-n",
            "--preserve-credentials",
            *command,
        ],
        check=check,
        capture_output=True,
        text=True,
        timeout=5,
    )


def _wait_for_path(path: Path, process: subprocess.Popen[str], timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists():
            return
        if process.poll() is not None:
            raise IDEError(
                IDEErrorCategory.POLICY_UNAVAILABLE,
                "IDE sandbox exited before namespace setup",
            )
        time.sleep(0.05)
    raise IDEError(
        IDEErrorCategory.POLICY_UNAVAILABLE,
        "IDE sandbox namespace setup timed out",
    )


def ide_content_security_policy(
    mode: IDEEgressMode,
    *,
    report_uri: str = "",
    provider_policy: str = "",
) -> tuple[str, str]:
    """Return the enforced or report-only CSP header for proxied IDE pages."""

    script_authorizers = _csp_inline_script_authorizers(provider_policy)
    directives = [
        "default-src 'self'",
        "connect-src 'self'",
        "frame-src 'self' blob:",
        "worker-src 'self' blob:",
        " ".join(
            ["script-src", "'self'", "'unsafe-eval'", "blob:", *script_authorizers]
        ),
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "font-src 'self' data:",
        "object-src 'none'",
        "base-uri 'self'",
    ]
    if report_uri:
        directives.append(f"report-uri {report_uri}")
    value = "; ".join(directives)
    header = (
        "Content-Security-Policy-Report-Only"
        if mode is IDEEgressMode.AUDIT
        else "Content-Security-Policy"
    )
    return header, value


def _csp_inline_script_authorizers(policy: str) -> tuple[str, ...]:
    authorizers: list[str] = []
    for directive in str(policy or "").split(";"):
        tokens = directive.strip().split()
        if not tokens or tokens[0].lower() != "script-src":
            continue
        for token in tokens[1:]:
            if (
                len(authorizers) < 64
                and len(token) <= 256
                and _CSP_INLINE_SCRIPT_AUTHORIZER.fullmatch(token)
                and token not in authorizers
            ):
                authorizers.append(token)
    return tuple(authorizers)


def _bounded_text(value: object, limit: int = 100) -> str | None:
    text = str(value or "").strip()
    return text[:limit] if text else None


def _origin(value: object) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = urlsplit(text)
    if parsed.scheme in ("http", "https", "ws", "wss") and parsed.hostname:
        port = f":{parsed.port}" if parsed.port else ""
        return f"{parsed.scheme}://{parsed.hostname}{port}"
    return parsed.scheme or "opaque"


def _integer_or_none(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
