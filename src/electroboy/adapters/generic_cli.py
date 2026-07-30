"""Generic CLI runtime adapter placeholder."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from pathlib import Path
from typing import TextIO

from .base import AgentInvocation, AgentResult, AgentRuntime
from ..config import RuntimeConfig


class GenericCliRuntime(AgentRuntime):
    """Runtime for configured non-interactive agent CLI tools."""

    def __init__(self, config: RuntimeConfig, root: Path | str = ".") -> None:
        self.config = config
        self.root = Path(root).resolve()

    def invoke(self, invocation: AgentInvocation) -> AgentResult:
        command = self._command(invocation)
        prompt = self._build_prompt(invocation)
        if invocation.progress_path:
            return self._invoke_with_progress_monitor(command, prompt, invocation)
        try:
            run_kwargs: dict[str, object] = {
                "input": prompt,
                "text": True,
                "capture_output": True,
                "cwd": self.root,
                "env": self._runtime_env(),
                "check": False,
            }
            if "timeout" in self.config.options:
                run_kwargs["timeout"] = float(self.config.options["timeout"])
            completed = subprocess.run(
                command,
                **run_kwargs,
            )
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as error:
            return AgentResult(
                ok=False,
                final_message=f"Agent runtime failed: {error}",
                raw_events=[{"error": str(error)}],
                commands=[" ".join(command)],
                error=str(error),
            )
        return self._result_from_process(
            command,
            completed.returncode,
            completed.stdout,
            completed.stderr,
        )

    def _invoke_with_progress_monitor(
        self,
        command: list[str],
        prompt: str,
        invocation: AgentInvocation,
    ) -> AgentResult:
        stdout_chunks: list[str] = []
        stderr_chunks: list[str] = []
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=self.root,
                env=self._runtime_env(),
            )
        except (FileNotFoundError, OSError) as error:
            return AgentResult(
                ok=False,
                final_message=f"Agent runtime failed: {error}",
                raw_events=[{"error": str(error)}],
                commands=[" ".join(command)],
                error=str(error),
            )

        threads = self._start_io_threads(
            process,
            prompt,
            stdout_chunks,
            stderr_chunks,
        )
        progress_path = self._resolve_progress_path(invocation.progress_path)
        idle_timeout = self._progress_idle_timeout(invocation)
        last_mtime = self._progress_mtime(progress_path)
        last_update = time.monotonic()
        poll_interval = min(1.0, max(0.05, idle_timeout / 10.0))

        while process.poll() is None:
            current_mtime = self._progress_mtime(progress_path)
            if current_mtime is not None and current_mtime != last_mtime:
                last_mtime = current_mtime
                last_update = time.monotonic()
            if time.monotonic() - last_update > idle_timeout:
                return self._kill_for_idle_progress(
                    process,
                    threads,
                    command,
                    invocation.progress_path or str(progress_path),
                    idle_timeout,
                    stdout_chunks,
                    stderr_chunks,
                )
            time.sleep(poll_interval)

        for thread in threads:
            thread.join(timeout=1.0)
        return self._result_from_process(
            command,
            process.returncode or 0,
            "".join(stdout_chunks),
            "".join(stderr_chunks),
        )

    def _start_io_threads(
        self,
        process: subprocess.Popen[str],
        prompt: str,
        stdout_chunks: list[str],
        stderr_chunks: list[str],
    ) -> list[threading.Thread]:
        threads: list[threading.Thread] = []
        if process.stdout is not None:
            threads.append(
                threading.Thread(
                    target=self._collect_stream,
                    args=(process.stdout, stdout_chunks),
                    daemon=True,
                )
            )
        if process.stderr is not None:
            threads.append(
                threading.Thread(
                    target=self._collect_stream,
                    args=(process.stderr, stderr_chunks),
                    daemon=True,
                )
            )
        if process.stdin is not None:
            threads.append(
                threading.Thread(
                    target=self._write_stdin,
                    args=(process.stdin, prompt),
                    daemon=True,
                )
            )
        for thread in threads:
            thread.start()
        return threads

    def _collect_stream(self, stream: TextIO, chunks: list[str]) -> None:
        try:
            for chunk in iter(lambda: stream.read(4096), ""):
                if not chunk:
                    break
                chunks.append(chunk)
        finally:
            stream.close()

    def _write_stdin(self, stream: TextIO, prompt: str) -> None:
        try:
            stream.write(prompt)
            stream.close()
        except (BrokenPipeError, OSError, ValueError):
            return

    def _kill_for_idle_progress(
        self,
        process: subprocess.Popen[str],
        threads: list[threading.Thread],
        command: list[str],
        progress_path: str,
        idle_timeout: float,
        stdout_chunks: list[str],
        stderr_chunks: list[str],
    ) -> AgentResult:
        process.kill()
        try:
            process.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            process.terminate()
        for thread in threads:
            thread.join(timeout=0.5)
        message = (
            f"Agent runtime failed: progress file {progress_path} was not "
            f"updated for {idle_timeout:g} seconds"
        )
        raw_events: list[dict[str, object]] = [
            {
                "error": message,
                "progress_path": progress_path,
                "stdout": "".join(stdout_chunks),
                "stderr": "".join(stderr_chunks),
            }
        ]
        return AgentResult(
            ok=False,
            final_message=message,
            raw_events=raw_events,
            commands=[" ".join(command)],
            error=message,
        )

    def _result_from_process(
        self,
        command: list[str],
        returncode: int,
        stdout: str,
        stderr: str,
    ) -> AgentResult:
        result = self._parse_stdout(stdout)
        result.ok = result.ok and returncode == 0
        if returncode != 0:
            result.error = stderr.strip() or f"exit code {returncode}"
        if stderr.strip():
            result.raw_events.append({"stream": "stderr", "text": stderr})
        result.commands.append(" ".join(command))
        return result

    def _resolve_progress_path(self, progress_path: str | None) -> Path:
        if not progress_path:
            return self.root
        path = Path(progress_path)
        if path.is_absolute():
            return path
        return self.root / path

    def _progress_mtime(self, progress_path: Path) -> float | None:
        try:
            return progress_path.stat().st_mtime
        except FileNotFoundError:
            return None

    def _progress_idle_timeout(self, invocation: AgentInvocation) -> float:
        if invocation.progress_idle_timeout is not None:
            return invocation.progress_idle_timeout
        configured = self.config.options.get("progress_idle_timeout", "300")
        try:
            return float(configured)
        except ValueError:
            return 300.0

    def _command(self, invocation: AgentInvocation) -> list[str]:
        return [self.config.command, *self.config.args]

    def _runtime_env(self) -> dict[str, str]:
        allowlist = self.config.env or ["PATH"]
        return {
            name: os.environ[name]
            for name in allowlist
            if name in os.environ
        }

    def _build_prompt(self, invocation: AgentInvocation) -> str:
        context = "\n".join(f"- {path}" for path in invocation.context_paths)
        if context:
            return f"{invocation.prompt}\n\nContext paths:\n{context}\n"
        return invocation.prompt

    def _parse_stdout(self, stdout: str) -> AgentResult:
        text = stdout.strip()
        if not text:
            return AgentResult(ok=True, final_message="")
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return AgentResult(ok=True, final_message=stdout)
        if isinstance(parsed, dict):
            commit_message = parsed.get("commit_message")
            provider = parsed.get("provider")
            provider_session_id = parsed.get("provider_session_id")
            return AgentResult(
                ok=bool(parsed.get("ok", True)),
                final_message=str(parsed.get("final_message", parsed.get("message", ""))),
                issues=list(parsed.get("issues", [])),
                raw_events=[parsed],
                changed_files=list(parsed.get("changed_files", [])),
                created_files=list(parsed.get("created_files", [])),
                commands=list(parsed.get("commands", [])),
                commit_message=(
                    commit_message if isinstance(commit_message, str) else None
                ),
                error=parsed.get("error"),
                provider=provider if isinstance(provider, str) else None,
                provider_session_id=(
                    provider_session_id
                    if isinstance(provider_session_id, str)
                    else None
                ),
                resumed_session=bool(parsed.get("resumed_session", False)),
                structured_output=True,
                structured_payload=parsed,
            )
        return AgentResult(ok=True, final_message=stdout, raw_events=[{"value": parsed}])
