"""Agent session and terminal helpers for the browser service."""

from __future__ import annotations

import errno
import fcntl
import json
import os
import pty
import re
import shlex
import shutil
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from electroboy.models import utc_now

TERMINAL_SUBMIT_DELAY_SECONDS = 0.08
MIN_TERMINAL_COLUMNS = 20
MAX_TERMINAL_COLUMNS = 1000
MIN_TERMINAL_ROWS = 5
MAX_TERMINAL_ROWS = 120
SESSION_BACKEND_ENV = "ELECTROBOY_SESSION_BACKEND"
SESSION_BACKEND_PTY = "pty"
SESSION_BACKEND_TMUX = "tmux"
_CONTROL_CHARS_TO_DROP = frozenset(
    chr(code)
    for code in [*range(0x00, 0x08), *range(0x0B, 0x0D), *range(0x0E, 0x20), 0x7F]
)

class AgentSessionError(RuntimeError):
    """Raised when an agent session cannot accept an operation."""


class AgentSession:
    """One browser-mediated child process attached through a pseudo-terminal."""

    def __init__(
        self,
        command: list[str],
        cwd: Path | str,
        columns: int = 120,
        rows: int = 32,
        label: str = "agent",
        kind: str = "agent",
        interactive: bool = True,
        lock_names: frozenset[str] | set[str] | None = None,
        on_completed: Callable[[int], None] | None = None,
        echo_input: bool = False,
        metadata: dict[str, object] | None = None,
        context_id: str | None = None,
        transcript_path: Path | str | None = None,
        backend: str = "pty",
        on_status_changed: Callable[["AgentSession"], None] | None = None,
        session_id: str | None = None,
    ) -> None:
        self.session_id = session_id or uuid4().hex
        self.command = command
        self.cwd = Path(cwd).resolve()
        self.columns = _clamp_terminal_columns(columns)
        self.rows = _clamp_terminal_rows(rows)
        self.label = label
        self.kind = kind
        self.interactive = interactive
        self.echo_input = echo_input
        self.lock_names = frozenset(lock_names or ())
        self.created_at = utc_now()
        self.on_completed = on_completed
        self.on_status_changed = on_status_changed
        self.metadata = dict(metadata or {})
        self.context_id = context_id
        self.transcript_path = (
            Path(transcript_path).expanduser().resolve() if transcript_path else None
        )
        self.backend = backend
        self.process: subprocess.Popen[bytes] | None = None
        self.status = "created"
        self.returncode: int | None = None
        self._master_fd: int | None = None
        self._events: list[dict[str, object]] = []
        self._next_event_id = 1
        self._terminal_pending = ""
        self._condition = threading.Condition()
        self._reader_thread: threading.Thread | None = None
        self._waiter_thread: threading.Thread | None = None

    def payload(self, selected: bool = False) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "kind": self.kind,
            "label": self.label,
            "status": "running" if self.is_active() else self.status,
            "returncode": self.returncode,
            "interactive": self.interactive,
            "locks": sorted(self.lock_names),
            "selected": selected,
            "created_at": self.created_at,
            "command": list(self.command),
            "metadata": dict(self.metadata),
            "context_id": self.context_id,
            "backend": self.backend,
            "transcript_path": (
                str(self.transcript_path) if self.transcript_path is not None else None
            ),
        }

    def persist_to(
        self,
        *,
        context_id: str,
        transcript_path: Path,
        on_status_changed: Callable[["AgentSession"], None] | None = None,
    ) -> None:
        self.context_id = context_id
        self.transcript_path = transcript_path.expanduser().resolve()
        if on_status_changed is not None:
            self.on_status_changed = on_status_changed

    def start(self) -> None:
        if self.process is not None:
            return
        master_fd, slave_fd = pty.openpty()
        env = _agent_process_env()
        env["ELECTROBOY_PROJECT_ROOT"] = str(self.cwd)
        env["AI_PIPELINE_PROJECT_ROOT"] = str(self.cwd)
        if not self.echo_input:
            _disable_terminal_echo(slave_fd)
        _set_terminal_size(slave_fd, self.columns, self.rows)
        popen_kwargs: dict[str, Any] = {
            "args": self.command,
            "cwd": self.cwd,
            "stdin": slave_fd,
            "stdout": slave_fd,
            "stderr": slave_fd,
            "env": env,
            "close_fds": True,
        }
        if sys.version_info >= (3, 11):
            popen_kwargs["process_group"] = 0
        else:
            popen_kwargs["start_new_session"] = True
        try:
            self.process = subprocess.Popen(**popen_kwargs)
        except Exception:
            os.close(master_fd)
            os.close(slave_fd)
            raise
        os.close(slave_fd)
        self._master_fd = master_fd
        self.status = "running"
        self._notify_status_changed()
        self._append_event(
            {
                "type": "system",
                "text": f"started: {' '.join(self.command)}",
            }
        )
        self._reader_thread = threading.Thread(
            target=self._read_output,
            name="electroboy-agent-output",
            daemon=True,
        )
        self._waiter_thread = threading.Thread(
            target=self._wait_for_exit,
            name="electroboy-agent-wait",
            daemon=True,
        )
        self._reader_thread.start()
        self._waiter_thread.start()

    def send(self, message: str) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        if self._master_fd is None:
            raise AgentSessionError(f"{self.label} input is not available")
        try:
            for index, text in enumerate(_terminal_input_chunks_for_message(message)):
                if index > 0:
                    time.sleep(TERMINAL_SUBMIT_DELAY_SECONDS)
                os.write(self._master_fd, text.encode("utf-8"))
        except OSError as error:
            raise AgentSessionError(f"could not write to {self.label}: {error}")

    def send_key(self, key: str) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        if self._master_fd is None:
            raise AgentSessionError(f"{self.label} input is not available")
        try:
            os.write(self._master_fd, _terminal_input_for_key(key).encode("utf-8"))
        except OSError as error:
            raise AgentSessionError(f"could not write to {self.label}: {error}")

    def send_raw(self, data: str) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        if self._master_fd is None:
            raise AgentSessionError(f"{self.label} input is not available")
        try:
            os.write(self._master_fd, data.encode("utf-8", errors="ignore"))
        except OSError as error:
            raise AgentSessionError(f"could not write to {self.label}: {error}")

    def interrupt(self) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        fd = self._master_fd
        if fd is not None:
            try:
                os.write(fd, b"\x1b")
            except OSError as error:
                raise AgentSessionError(
                    f"could not interrupt {self.label}: {error}"
                )

    def terminate(self, timeout: float = 2.0) -> None:
        process = self.process
        if process is None:
            self._close_master()
            return
        if process.poll() is not None:
            self._close_master()
            return
        _terminate_process_tree(process, timeout=timeout)
        self.returncode = process.returncode
        self.status = "terminated"
        self._notify_status_changed()
        self._close_master()

    def resize(self, columns: int, rows: int) -> None:
        self.columns = _clamp_terminal_columns(columns)
        self.rows = _clamp_terminal_rows(rows)
        fd = self._master_fd
        if fd is None:
            return
        _set_terminal_size(fd, self.columns, self.rows)
        process = self.process
        if process is None or process.poll() is not None:
            return
        try:
            os.killpg(process.pid, signal.SIGWINCH)
        except ProcessLookupError:
            return
        except OSError:
            return

    def events_after(self, event_id: int) -> list[dict[str, object]]:
        with self._condition:
            return [
                event.copy()
                for event in self._events
                if int(event.get("id", 0)) > event_id
            ]

    def events(self) -> list[dict[str, object]]:
        transcript_events = self._read_transcript_events()
        if transcript_events:
            return transcript_events
        with self._condition:
            return [event.copy() for event in self._events]

    def wait_for_events_after(
        self,
        event_id: int,
        timeout: float,
    ) -> list[dict[str, object]]:
        with self._condition:
            if (
                not any(int(event.get("id", 0)) > event_id for event in self._events)
                and self.is_active()
            ):
                self._condition.wait(timeout=timeout)
            return [
                event.copy()
                for event in self._events
                if int(event.get("id", 0)) > event_id
            ]

    def is_active(self) -> bool:
        process = self.process
        return process is not None and process.poll() is None

    def _append_event(self, payload: dict[str, object]) -> None:
        with self._condition:
            payload["id"] = self._next_event_id
            self._next_event_id += 1
            self._events.append(payload)
            self._append_transcript_event(payload)
            self._condition.notify_all()

    def _read_output(self) -> None:
        fd = self._master_fd
        if fd is None:
            return
        while True:
            try:
                chunk = os.read(fd, 4096)
            except OSError as error:
                if error.errno in {errno.EBADF, errno.EIO}:
                    break
                self._append_event(
                    {
                        "type": "error",
                        "text": f"agent output stream failed: {error}",
                    }
                )
                break
            if not chunk:
                break
            terminal_text = chunk.decode("utf-8", errors="replace")
            text, self._terminal_pending = _clean_terminal_output(
                terminal_text,
                self._terminal_pending,
            )
            if not text and not terminal_text:
                continue
            self._append_event(
                {
                    "type": "output",
                    "text": text,
                    "terminal": terminal_text,
                }
            )

    def _wait_for_exit(self) -> None:
        process = self.process
        if process is None:
            return
        returncode = process.wait()
        time.sleep(0.05)
        self.returncode = returncode
        self.status = "completed"
        self._notify_status_changed()
        if self.on_completed is not None:
            try:
                self.on_completed(returncode)
            except Exception as error:
                self._append_event(
                    {
                        "type": "error",
                        "text": f"completion hook failed: {error}",
                    }
                )
        self._append_event(
            {
                "type": "completed",
                "returncode": returncode,
            }
        )
        self._close_master()

    def _append_transcript_event(self, payload: dict[str, object]) -> None:
        path = self.transcript_path
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, sort_keys=True) + "\n")
        except OSError:
            return

    def _read_transcript_events(self) -> list[dict[str, object]]:
        path = self.transcript_path
        if path is None or not path.exists():
            return []
        events: list[dict[str, object]] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                payload = json.loads(line)
                if isinstance(payload, dict):
                    events.append(payload)
        except (OSError, json.JSONDecodeError):
            return []
        return events

    def _notify_status_changed(self) -> None:
        if self.on_status_changed is None:
            return
        try:
            self.on_status_changed(self)
        except Exception:
            return

    def _close_master(self) -> None:
        fd = self._master_fd
        if fd is None:
            return
        self._master_fd = None
        try:
            os.close(fd)
        except OSError:
            return


class TmuxAgentSession(AgentSession):
    """Agent session backed by a named tmux session."""

    def __init__(
        self,
        command: list[str],
        cwd: Path | str,
        columns: int = 120,
        rows: int = 32,
        label: str = "agent",
        kind: str = "agent",
        interactive: bool = True,
        lock_names: frozenset[str] | set[str] | None = None,
        on_completed: Callable[[int], None] | None = None,
        echo_input: bool = False,
        metadata: dict[str, object] | None = None,
        context_id: str | None = None,
        transcript_path: Path | str | None = None,
        on_status_changed: Callable[["AgentSession"], None] | None = None,
        session_id: str | None = None,
        tmux_name: str | None = None,
    ) -> None:
        super().__init__(
            command,
            cwd,
            columns=columns,
            rows=rows,
            label=label,
            kind=kind,
            interactive=interactive,
            lock_names=lock_names,
            on_completed=on_completed,
            echo_input=echo_input,
            metadata=metadata,
            context_id=context_id,
            transcript_path=transcript_path,
            backend=SESSION_BACKEND_TMUX,
            on_status_changed=on_status_changed,
            session_id=session_id,
        )
        self.tmux_name = tmux_name or _tmux_session_name(self.session_id)
        self._last_capture = ""

    @classmethod
    def from_agent_session(cls, session: AgentSession) -> "TmuxAgentSession":
        return cls(
            session.command,
            session.cwd,
            columns=session.columns,
            rows=session.rows,
            label=session.label,
            kind=session.kind,
            interactive=session.interactive,
            lock_names=session.lock_names,
            on_completed=session.on_completed,
            echo_input=session.echo_input,
            metadata=session.metadata,
            context_id=session.context_id,
            transcript_path=session.transcript_path,
            on_status_changed=session.on_status_changed,
            session_id=session.session_id,
        )

    def payload(self, selected: bool = False) -> dict[str, object]:
        payload = super().payload(selected=selected)
        payload["tmux_session"] = self.tmux_name
        return payload

    def start(self) -> None:
        if shutil.which("tmux") is None:
            raise AgentSessionError("tmux session backend requires tmux in PATH")
        if _tmux_has_session(self.tmux_name):
            raise AgentSessionError(f"tmux session already exists: {self.tmux_name}")
        command = [
            "tmux",
            "new-session",
            "-d",
            "-s",
            self.tmux_name,
            "-c",
            str(self.cwd),
            _tmux_shell_command(self.command, self.cwd),
        ]
        try:
            subprocess.run(
                command,
                check=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except subprocess.CalledProcessError as error:
            stderr = error.stderr.decode("utf-8", errors="replace").strip()
            raise AgentSessionError(
                stderr or f"could not start tmux session {self.tmux_name}"
            ) from error
        self.status = "running"
        self._notify_status_changed()
        self._append_event(
            {
                "type": "system",
                "text": f"started tmux session: {self.tmux_name}",
            }
        )
        self.resize(self.columns, self.rows)
        self._reader_thread = threading.Thread(
            target=self._read_output,
            name="electroboy-tmux-output",
            daemon=True,
        )
        self._waiter_thread = threading.Thread(
            target=self._wait_for_exit,
            name="electroboy-tmux-wait",
            daemon=True,
        )
        self._reader_thread.start()
        self._waiter_thread.start()

    def attach_existing(self) -> None:
        if not _tmux_has_session(self.tmux_name):
            self.status = "completed"
            self.returncode = 0
            return
        self.status = "running"
        self._notify_status_changed()
        self._append_event(
            {
                "type": "system",
                "text": f"reattached tmux session: {self.tmux_name}",
            }
        )
        self._reader_thread = threading.Thread(
            target=self._read_output,
            name="electroboy-tmux-output",
            daemon=True,
        )
        self._waiter_thread = threading.Thread(
            target=self._wait_for_exit,
            name="electroboy-tmux-wait",
            daemon=True,
        )
        self._reader_thread.start()
        self._waiter_thread.start()

    def send(self, message: str) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        for index, text in enumerate(_terminal_input_chunks_for_message(message)):
            if index > 0:
                time.sleep(TERMINAL_SUBMIT_DELAY_SECONDS)
            self.send_raw(text)

    def send_key(self, key: str) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        tmux_key = _tmux_key_name(key)
        if tmux_key is None:
            self.send_raw(_terminal_input_for_key(key))
            return
        _tmux_run(["send-keys", "-t", self.tmux_name, tmux_key])

    def send_raw(self, data: str) -> None:
        if not self.is_active():
            raise AgentSessionError(f"{self.label} is not running")
        if not data:
            return
        buffer_name = f"electroboy-{self.session_id}"
        encoded = data.encode("utf-8", errors="ignore")
        _tmux_run(["load-buffer", "-b", buffer_name, "-"], input_bytes=encoded)
        _tmux_run(["paste-buffer", "-d", "-b", buffer_name, "-t", self.tmux_name])

    def interrupt(self) -> None:
        self.send_key("escape")

    def terminate(self, timeout: float = 2.0) -> None:
        if self.is_active():
            _tmux_run(["kill-session", "-t", self.tmux_name], check=False)
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline and self.is_active():
                time.sleep(0.05)
        self.returncode = 0
        self.status = "terminated"
        self._notify_status_changed()

    def resize(self, columns: int, rows: int) -> None:
        self.columns = _clamp_terminal_columns(columns)
        self.rows = _clamp_terminal_rows(rows)
        if self.is_active():
            _tmux_run(
                [
                    "resize-window",
                    "-t",
                    self.tmux_name,
                    "-x",
                    str(self.columns),
                    "-y",
                    str(self.rows),
                ],
                check=False,
            )

    def is_active(self) -> bool:
        return _tmux_has_session(self.tmux_name)

    def _read_output(self) -> None:
        while self.is_active():
            capture = _tmux_capture_pane(self.tmux_name)
            if capture and capture != self._last_capture:
                text = _tmux_capture_delta(self._last_capture, capture)
                self._last_capture = capture
                if text:
                    self._append_event(
                        {
                            "type": "output",
                            "text": text,
                            "terminal": text,
                        }
                    )
            time.sleep(1)

    def _wait_for_exit(self) -> None:
        while self.is_active():
            time.sleep(0.5)
        self.returncode = 0 if self.returncode is None else self.returncode
        completed = self.status == "running"
        if completed:
            self.status = "completed"
        self._notify_status_changed()
        if self.on_completed is not None and completed:
            try:
                self.on_completed(self.returncode or 0)
            except Exception as error:
                self._append_event(
                    {
                        "type": "error",
                        "text": f"completion hook failed: {error}",
                    }
                )
        self._append_event(
            {
                "type": "completed",
                "returncode": self.returncode,
            }
        )


def _terminate_process_tree(
    process: subprocess.Popen[bytes],
    timeout: float,
) -> None:
    root_pid = process.pid
    pids = [root_pid, *_descendant_process_ids(root_pid)]
    _signal_process_ids(root_pid, pids, signal.SIGTERM)
    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _signal_process_ids(root_pid, pids, signal.SIGKILL)
        process.wait(timeout=1)
        return

    survivors = [pid for pid in pids if pid != root_pid and _process_exists(pid)]
    if survivors:
        _signal_process_ids(root_pid, survivors, signal.SIGKILL)


def _signal_process_ids(root_pid: int, pids: list[int], sig: int) -> None:
    try:
        os.killpg(root_pid, sig)
    except ProcessLookupError:
        pass
    except OSError:
        pass
    for pid in reversed(pids):
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            continue
        except OSError:
            continue


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def _descendant_process_ids(root_pid: int) -> list[int]:
    parent_map = _process_parent_map()
    if not parent_map:
        return []
    children_by_parent: dict[int, list[int]] = {}
    for pid, parent_pid in parent_map.items():
        children_by_parent.setdefault(parent_pid, []).append(pid)

    descendants: list[int] = []
    stack = list(children_by_parent.get(root_pid, []))
    while stack:
        pid = stack.pop()
        descendants.append(pid)
        stack.extend(children_by_parent.get(pid, []))
    return descendants


def _process_parent_map() -> dict[int, int]:
    proc = Path("/proc")
    if not proc.exists():
        return {}
    parent_map: dict[int, int] = {}
    for entry in proc.iterdir():
        if not entry.name.isdigit():
            continue
        try:
            stat = (entry / "stat").read_text(encoding="utf-8")
            pid = int(entry.name)
            close_paren = stat.rfind(")")
            fields = stat[close_paren + 2 :].split()
            parent_map[pid] = int(fields[1])
        except (IndexError, OSError, ValueError):
            continue
    return parent_map


def _subprocess_output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _download_name_part(value: object) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip())
    text = text.strip(".-")
    return text or "export"


def _terminal_input_for_message(message: str) -> str:
    return "".join(_terminal_input_chunks_for_message(message))


def _terminal_input_for_key(key: str) -> str:
    if re.fullmatch(r"[0-9]", key):
        return key
    keys = {
        "enter": "\r",
        "escape": "\x1b",
        "tab": "\t",
        "backspace": "\x7f",
        "delete": "\x1b[3~",
        "up": "\x1b[A",
        "down": "\x1b[B",
        "right": "\x1b[C",
        "left": "\x1b[D",
    }
    try:
        return keys[key]
    except KeyError:
        choices = ", ".join(sorted(keys))
        raise AgentSessionError(
            f"unknown terminal key {key!r}; choose one of: {choices}, 0-9"
        )


def _terminal_input_chunks_for_message(message: str) -> list[str]:
    text = message.replace("\r\n", "\n").replace("\r", "\n")
    text = text.rstrip("\n")
    if "\n" in text:
        return [f"\x1b[200~{text}\x1b[201~", "\r"]
    return [text, "\r"]


def _normalize_session_backend(value: str | None) -> str:
    backend = str(value or SESSION_BACKEND_PTY).strip().lower()
    if backend in {"", SESSION_BACKEND_PTY}:
        return SESSION_BACKEND_PTY
    if backend == SESSION_BACKEND_TMUX:
        return SESSION_BACKEND_TMUX
    raise StateError(f"unknown session backend: {value}")


def _session_backend_from_env() -> str:
    return _normalize_session_backend(os.environ.get(SESSION_BACKEND_ENV))


def _tmux_session_name(session_id: str) -> str:
    safe_session_id = _download_name_part(session_id)
    return f"electroboy-{safe_session_id[:32]}"


def _tmux_run(
    args: list[str],
    *,
    input_bytes: bytes | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    command = ["tmux", *args]
    result = subprocess.run(
        command,
        input=input_bytes,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise AgentSessionError(stderr or f"tmux command failed: {shlex.join(command)}")
    return result


def _tmux_has_session(tmux_name: str) -> bool:
    if shutil.which("tmux") is None:
        return False
    result = subprocess.run(
        ["tmux", "has-session", "-t", tmux_name],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _tmux_shell_command(command: list[str], cwd: Path | str) -> str:
    root = Path(cwd).expanduser().resolve()
    env = _agent_process_env()
    env["ELECTROBOY_PROJECT_ROOT"] = str(root)
    env["AI_PIPELINE_PROJECT_ROOT"] = str(root)
    env_args = [f"{key}={value}" for key, value in sorted(env.items())]
    return "exec " + shlex.join(["env", *env_args, *command])


def _tmux_key_name(key: str) -> str | None:
    normalized = key.strip().lower()
    mapping = {
        "enter": "Enter",
        "escape": "Escape",
        "up": "Up",
        "down": "Down",
        "left": "Left",
        "right": "Right",
        "backspace": "BSpace",
        "delete": "DC",
    }
    if normalized in mapping:
        return mapping[normalized]
    if re.fullmatch(r"[0-9]", normalized):
        return None
    return None


def _tmux_capture_pane(tmux_name: str) -> str:
    result = _tmux_run(
        ["capture-pane", "-p", "-e", "-J", "-t", tmux_name, "-S", "-2000"],
        check=False,
    )
    if result.returncode != 0:
        return ""
    return result.stdout.decode("utf-8", errors="replace")


def _tmux_capture_delta(previous: str, current: str) -> str:
    if not previous:
        return current
    if current.startswith(previous):
        return current[len(previous) :]
    previous_lines = previous.splitlines()
    current_lines = current.splitlines()
    for count in range(min(len(previous_lines), len(current_lines)), 0, -1):
        if previous_lines[-count:] == current_lines[:count]:
            suffix = "\n".join(current_lines[count:])
            return suffix + ("\n" if suffix and current.endswith("\n") else "")
    return current


def _disable_terminal_echo(slave_fd: int) -> None:
    try:
        attributes = termios.tcgetattr(slave_fd)
        attributes[3] &= ~(
            termios.ECHO
            | termios.ECHOE
            | termios.ECHOK
            | termios.ECHONL
        )
        termios.tcsetattr(slave_fd, termios.TCSANOW, attributes)
    except termios.error:
        return


def _clamp_terminal_columns(columns: int) -> int:
    return max(MIN_TERMINAL_COLUMNS, min(columns, MAX_TERMINAL_COLUMNS))


def _clamp_terminal_rows(rows: int) -> int:
    return max(MIN_TERMINAL_ROWS, min(rows, MAX_TERMINAL_ROWS))


def _set_terminal_size(fd: int, columns: int, rows: int) -> None:
    columns = _clamp_terminal_columns(columns)
    rows = _clamp_terminal_rows(rows)
    packed_size = struct.pack("HHHH", rows, columns, 0, 0)
    try:
        fcntl.ioctl(fd, termios.TIOCSWINSZ, packed_size)
    except OSError:
        return


def _agent_process_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    env["TERM"] = "xterm-256color"
    env["COLORTERM"] = "truecolor"
    env["ELECTROBOY_DISABLE_SESSION_RESUME"] = "1"
    env.pop("NO_COLOR", None)
    env.pop("CLICOLOR", None)
    env.pop("FORCE_COLOR", None)
    module_path = str(_module_search_path())
    existing_pythonpath = env.get("PYTHONPATH", "")
    entries = [module_path]
    entries.extend(
        entry
        for entry in existing_pythonpath.split(os.pathsep)
        if entry and entry != module_path
    )
    env["PYTHONPATH"] = os.pathsep.join(entries)
    return env


def _module_search_path() -> Path:
    return Path(__file__).resolve().parents[2]


def _clean_terminal_output(
    text: str,
    pending: str = "",
) -> tuple[str, str]:
    combined = f"{pending}{text}"
    output: list[str] = []
    index = 0
    while index < len(combined):
        char = combined[index]
        if char == "\x1b":
            consumed, incomplete = _terminal_escape_length(combined, index)
            if incomplete:
                return _normalize_terminal_text("".join(output)), combined[index:]
            index += consumed
            continue
        if char == "\r":
            if index + 1 < len(combined) and combined[index + 1] == "\n":
                output.append("\n")
                index += 2
            else:
                output.append("\n")
                index += 1
            continue
        if char == "\b":
            if output and output[-1] != "\n":
                output.pop()
            index += 1
            continue
        if char in _CONTROL_CHARS_TO_DROP:
            index += 1
            continue
        output.append(char)
        index += 1
    return _normalize_terminal_text("".join(output)), ""


def _terminal_escape_length(text: str, index: int) -> tuple[int, bool]:
    if index + 1 >= len(text):
        return len(text) - index, True
    introducer = text[index + 1]
    if introducer == "[":
        return _consume_until_final_byte(text, index, 2)
    if introducer == "]":
        return _consume_string_control(text, index)
    if introducer in {"P", "^", "_", "X"}:
        return _consume_string_control(text, index)
    if introducer in {"(", ")", "*", "+", "-", ".", "/"}:
        if index + 2 >= len(text):
            return len(text) - index, True
        return 3, False
    if "@" <= introducer <= "_":
        return 2, False
    return 1, False


def _consume_until_final_byte(
    text: str,
    index: int,
    offset: int,
) -> tuple[int, bool]:
    cursor = index + offset
    while cursor < len(text):
        if "@" <= text[cursor] <= "~":
            return cursor - index + 1, False
        cursor += 1
    return len(text) - index, True


def _consume_string_control(text: str, index: int) -> tuple[int, bool]:
    cursor = index + 2
    while cursor < len(text):
        char = text[cursor]
        if char == "\x07":
            return cursor - index + 1, False
        if char == "\x1b":
            if cursor + 1 < len(text) and text[cursor + 1] == "\\":
                return cursor - index + 2, False
            return cursor - index, False
        cursor += 1
    return len(text) - index, True


def _normalize_terminal_text(text: str) -> str:
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    return text

