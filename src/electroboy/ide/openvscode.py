"""OpenVSCode Server process adapter."""

from __future__ import annotations

import os
import re
import secrets
import signal
import socket
import subprocess
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass
from pathlib import Path

from .domain import (
    IDEEndpoint,
    IDEError,
    IDEErrorCategory,
    IDEInstance,
    IDEInstanceStatus,
    IDELocation,
    IDEProfile,
    IDERuntime,
    IDEWorkspace,
)
from .processes import DirectIDEProcessLauncher, IDEProcessLaunch, IDEProcessLauncher
from .profile import configure_managed_profile

_QUERY_VALUE = re.compile(r"([?&][^=\s]+)=([^&\s]+)")


@dataclass
class _ProviderProcess:
    launch: IDEProcessLaunch
    token: str
    socket_path: Path
    output: deque[str]
    reader: threading.Thread
    stopped: bool = False


class OpenVSCodeProvider:
    """Run OpenVSCode behind a private Unix-domain socket."""

    provider_id = "openvscode"

    def __init__(
        self,
        *,
        diagnostic_limit: int = 200,
        process_launcher: IDEProcessLauncher | None = None,
    ) -> None:
        self.diagnostic_limit = max(10, diagnostic_limit)
        self.process_launcher = process_launcher or DirectIDEProcessLauncher()
        self._processes: dict[str, _ProviderProcess] = {}
        self._lock = threading.RLock()

    def start(
        self,
        workspace: IDEWorkspace,
        runtime: IDERuntime,
        profile: IDEProfile,
    ) -> IDEInstance:
        for path in (
            profile.root,
            profile.user_data,
            profile.extensions,
            profile.server_data,
            profile.logs,
        ):
            path.mkdir(parents=True, exist_ok=True)
        configure_managed_profile(profile)
        socket_path = profile.root / "openvscode.sock"
        socket_path.unlink(missing_ok=True)
        token = secrets.token_urlsafe(32)
        instance_id = f"ide-{uuid.uuid4().hex}"
        arguments = self.command(
            workspace,
            runtime,
            profile,
            socket_path=socket_path,
            token=token,
        )
        try:
            launch = self.process_launcher.launch(
                arguments,
                cwd=workspace.project_root,
                profile=profile,
            )
        except OSError as error:
            raise IDEError(
                IDEErrorCategory.START_FAILED,
                f"could not start {self.provider_id}: {error}",
                recoverable=True,
            ) from error
        output: deque[str] = deque(maxlen=self.diagnostic_limit)
        reader = threading.Thread(
            target=self._read_output,
            args=(launch, output, token),
            name=f"{instance_id}-output",
            daemon=True,
        )
        state = _ProviderProcess(launch, token, socket_path, output, reader)
        with self._lock:
            self._processes[instance_id] = state
        reader.start()
        return IDEInstance(
            instance_id=instance_id,
            provider=self.provider_id,
            workspace=workspace,
            runtime=runtime,
            profile=profile,
            status=IDEInstanceStatus.STARTING,
            endpoint=IDEEndpoint("unix", str(socket_path), token),
            process_id=launch.process.pid,
            started_at=time.time(),
        )

    def command(
        self,
        workspace: IDEWorkspace,
        runtime: IDERuntime,
        profile: IDEProfile,
        *,
        socket_path: Path,
        token: str,
    ) -> list[str]:
        return [
            str(runtime.executable),
            "--socket-path",
            str(socket_path),
            "--connection-token",
            token,
            "--telemetry-level",
            "off",
            "--user-data-dir",
            str(profile.user_data),
            "--extensions-dir",
            str(profile.extensions),
            "--server-data-dir",
            str(profile.server_data),
            str(workspace.project_root),
        ]

    def status(self, instance: IDEInstance) -> IDEInstanceStatus:
        state = self._state(instance)
        return_code = state.launch.process.poll()
        if return_code is not None:
            return (
                IDEInstanceStatus.STOPPED
                if state.stopped
                else IDEInstanceStatus.FAILED
            )
        if _socket_ready(state.socket_path):
            return IDEInstanceStatus.READY
        return IDEInstanceStatus.STARTING

    def wait_until_ready(
        self,
        instance: IDEInstance,
        timeout: float,
    ) -> IDEInstance:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.status(instance)
            if status is IDEInstanceStatus.READY:
                return instance.with_status(
                    IDEInstanceStatus.READY,
                    ready_at=time.time(),
                )
            if status is IDEInstanceStatus.FAILED:
                diagnostics = self.diagnostics(instance.instance_id)
                self._cleanup_process(instance.instance_id)
                detail = diagnostics[-1] if diagnostics else "process exited"
                raise IDEError(
                    IDEErrorCategory.START_FAILED,
                    f"{self.provider_id} failed during startup: {detail}",
                    recoverable=True,
                )
            time.sleep(0.05)
        self.stop(instance, "startup timeout")
        raise IDEError(
            IDEErrorCategory.READINESS_TIMEOUT,
            f"{self.provider_id} did not become ready within {timeout:g} seconds",
            recoverable=True,
        )

    def endpoint(self, instance: IDEInstance) -> IDEEndpoint:
        if instance.endpoint is None:
            raise IDEError(
                IDEErrorCategory.NOT_READY,
                "IDE instance has no provider endpoint",
            )
        return instance.endpoint

    def open_location(
        self,
        instance: IDEInstance,
        location: IDELocation,
    ) -> None:
        del instance, location
        raise IDEError(
            IDEErrorCategory.NAVIGATION_FAILED,
            "the IDE bridge is not connected",
            recoverable=True,
        )

    def stop(self, instance: IDEInstance, reason: str) -> IDEInstance:
        del reason
        with self._lock:
            state = self._processes.get(instance.instance_id)
        if state is None:
            return instance.with_status(
                IDEInstanceStatus.STOPPED,
                stopped_at=time.time(),
            )
        state.stopped = True
        process = state.launch.process
        if process.poll() is None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
                process.wait(timeout=3)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                if process.poll() is None:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    process.wait(timeout=2)
        self._cleanup_process(instance.instance_id)
        return instance.with_status(
            IDEInstanceStatus.STOPPED,
            stopped_at=time.time(),
        )

    def diagnostics(self, instance_id: str) -> list[str]:
        with self._lock:
            state = self._processes.get(instance_id)
            return list(state.output) if state is not None else []

    def enforcement(self, instance_id: str) -> dict[str, object]:
        with self._lock:
            state = self._processes.get(instance_id)
            return dict(state.launch.enforcement) if state is not None else {}

    def _state(self, instance: IDEInstance) -> _ProviderProcess:
        with self._lock:
            state = self._processes.get(instance.instance_id)
        if state is None:
            raise IDEError(
                IDEErrorCategory.NOT_READY,
                f"IDE process is not available: {instance.instance_id}",
            )
        return state

    def _cleanup_process(self, instance_id: str) -> None:
        with self._lock:
            state = self._processes.pop(instance_id, None)
        if state is None:
            return
        if state.launch.process.stdout is not None:
            state.launch.process.stdout.close()
        state.reader.join(timeout=1)
        state.launch.cleanup()
        state.socket_path.unlink(missing_ok=True)

    @staticmethod
    def _read_output(
        launch: IDEProcessLaunch,
        output: deque[str],
        token: str,
    ) -> None:
        process = launch.process
        if process.stdout is None:
            return
        for line in process.stdout:
            launch.line_observer(line)
            sanitized = line.strip().replace(token, "[REDACTED]")
            sanitized = _QUERY_VALUE.sub(r"\1=[REDACTED]", sanitized)
            if sanitized:
                output.append(sanitized[:1000])


def _socket_ready(path: Path) -> bool:
    if not path.exists():
        return False
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(0.2)
    try:
        client.connect(str(path))
        client.sendall(
            b"GET / HTTP/1.1\r\n"
            b"Host: localhost\r\n"
            b"Connection: close\r\n\r\n"
        )
        response = client.recv(64)
        return response.startswith(b"HTTP/")
    except OSError:
        return False
    finally:
        client.close()
