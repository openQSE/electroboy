"""Core command-line interface for the ElectroBoy browser service."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys
from typing import Sequence

from .state_store import StateError


SERVICE_ROOT_ENV = "ELECTROBOY_SERVICE_ROOT"
SERVICE_STATE_ROOT_ENV = "ELECTROBOY_SERVICE_STATE_ROOT"
SERVICE_HOST_ENV = "ELECTROBOY_SERVICE_HOST"
SERVICE_PORT_ENV = "ELECTROBOY_SERVICE_PORT"
SERVICE_SESSION_BACKEND_ENV = "ELECTROBOY_SESSION_BACKEND"
SERVICE_SESSION_BACKEND_PTY = "pty"
SERVICE_SESSION_BACKEND_TMUX = "tmux"
SERVICE_DEFAULT_HOST = "127.0.0.1"
SERVICE_DEFAULT_PORT = 8765
SERVICE_NAME = "electroboy"


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI exposed by a core-only installation."""

    parser = argparse.ArgumentParser(prog="electroboy")
    parser.add_argument(
        "--root",
        default=".",
        help="initial directory exposed by the browser service",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    service = subparsers.add_parser(
        "service",
        help="install or manage the browser service",
    )
    service_subparsers = service.add_subparsers(
        dest="service_command",
        required=True,
    )
    service_install = service_subparsers.add_parser(
        "install",
        help="install systemd files for the browser service",
    )
    service_scope = service_install.add_mutually_exclusive_group()
    service_scope.add_argument(
        "--user",
        action="store_true",
        help="install as a systemd user service; this is the default",
    )
    service_scope.add_argument(
        "--system",
        action="store_true",
        help="install as a system service under /etc/systemd/system",
    )
    service_install.add_argument(
        "--browse-root",
        help="initial directory for the GUI picker; defaults to this directory",
    )
    service_install.add_argument(
        "--state-root",
        help=(
            "directory for service configuration and runtime state; defaults "
            "to the browse root"
        ),
    )
    service_install.add_argument("--host", default=SERVICE_DEFAULT_HOST)
    service_install.add_argument("--port", type=int, default=SERVICE_DEFAULT_PORT)
    service_install.add_argument(
        "--session-backend",
        choices=[SERVICE_SESSION_BACKEND_PTY, SERVICE_SESSION_BACKEND_TMUX],
        default=os.environ.get(
            SERVICE_SESSION_BACKEND_ENV,
            SERVICE_SESSION_BACKEND_PTY,
        ),
    )
    service_install.add_argument(
        "--path",
        dest="command_path",
        default=os.environ.get("PATH", ""),
    )
    service_install.add_argument("--service-user")
    service_install.add_argument("--force", action="store_true")
    service_install.add_argument(
        "--reload",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    service_install.add_argument("--enable", action="store_true")
    service_install.add_argument("--start", action="store_true")

    serve = subparsers.add_parser("serve", help="run the local browser service")
    serve.add_argument(
        "--root",
        default=argparse.SUPPRESS,
        help="initial directory exposed by the browser service",
    )
    serve.add_argument(
        "--state-root",
        help="directory for service configuration and runtime state",
    )
    serve.add_argument("--host")
    serve.add_argument("--port", type=int)
    serve.add_argument(
        "--session-backend",
        choices=[SERVICE_SESSION_BACKEND_PTY, SERVICE_SESSION_BACKEND_TMUX],
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run a core service command."""

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(raw_argv)
    try:
        if args.command == "serve":
            return _cmd_serve(args, root_explicit=_root_argument_explicit(raw_argv))
        if args.command == "service":
            return _cmd_service(args)
    except StateError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    parser.print_help(sys.stderr)
    return 2


def _cmd_serve(args: argparse.Namespace, root_explicit: bool = False) -> int:
    from .service import run_service

    root = _service_root(args, root_explicit=root_explicit)
    host = args.host or os.environ.get(SERVICE_HOST_ENV) or SERVICE_DEFAULT_HOST
    port = args.port if args.port is not None else _service_port_from_environment()
    kwargs: dict[str, object] = {"host": host, "port": port}
    state_root = args.state_root or os.environ.get(SERVICE_STATE_ROOT_ENV)
    if state_root:
        kwargs["state_root"] = state_root
    if args.session_backend:
        kwargs["session_backend"] = args.session_backend
    try:
        return run_service(root, **kwargs)
    except OSError as error:
        print(f"error: could not start ElectroBoy service: {error}", file=sys.stderr)
        return 2


def _cmd_service(args: argparse.Namespace) -> int:
    if args.service_command == "install":
        return _cmd_service_install(args)
    return 2


def _cmd_service_install(args: argparse.Namespace) -> int:
    scope = "system" if args.system else "user"
    browse_root = Path(args.browse_root or os.getcwd()).expanduser().resolve()
    state_root = Path(args.state_root or browse_root).expanduser().resolve()
    port = _validate_service_port(args.port, "port")
    command_path = args.command_path or "/usr/local/bin:/usr/bin:/bin"
    unit_path, env_path = _service_install_paths(scope)
    unit_text = _service_unit_text(
        scope=scope,
        service_user=_service_install_user(args),
    )
    env_text = _service_env_text(
        browse_root=browse_root,
        state_root=state_root,
        host=args.host,
        port=port,
        session_backend=args.session_backend,
        command_path=command_path,
    )

    _write_installed_service_file(unit_path, unit_text, force=args.force)
    _write_installed_service_file(env_path, env_text, force=args.force)
    print(f"installed service unit: {unit_path}")
    print(f"installed service env: {env_path}")
    print(f"browse root: {browse_root}")
    print(f"state root: {state_root}")
    print(f"bind: {args.host}:{port}")
    print(f"session backend: {args.session_backend}")
    if args.reload:
        _run_systemctl(scope, ["daemon-reload"], required=False)
    else:
        print("systemd reload: skipped")
    if args.enable:
        _run_systemctl(scope, ["enable", SERVICE_NAME], required=True)
    if args.start:
        _run_systemctl(scope, ["start", SERVICE_NAME], required=True)
    prefix = "systemctl --user" if scope == "user" else "sudo systemctl"
    if not args.start:
        print(f"start: {prefix} start {SERVICE_NAME}")
    print(f"status: {prefix} status {SERVICE_NAME}")
    return 0


def _service_install_paths(scope: str) -> tuple[Path, Path]:
    if scope == "system":
        return (
            Path("/etc/systemd/system") / f"{SERVICE_NAME}.service",
            Path("/etc/default") / SERVICE_NAME,
        )
    return (
        Path.home() / ".config" / "systemd" / "user" / f"{SERVICE_NAME}.service",
        Path.home() / ".config" / SERVICE_NAME / "service.env",
    )


def _service_unit_text(scope: str, service_user: str | None = None) -> str:
    user_line = f"User={service_user}\n" if scope == "system" and service_user else ""
    install_target = "multi-user.target" if scope == "system" else "default.target"
    return f"""# Generated by `electroboy service install`.
#
# ElectroBoy runs as the operator because agent, Git, and project credentials
# are user-scoped. Use the env files below to configure the service.

[Unit]
Description=ElectroBoy browser service
After=network.target

[Service]
Type=simple
{user_line}Environment=ELECTROBOY_SERVICE_ROOT=%h
Environment=ELECTROBOY_SERVICE_STATE_ROOT=%h
Environment=ELECTROBOY_SERVICE_HOST={SERVICE_DEFAULT_HOST}
Environment=ELECTROBOY_SERVICE_PORT={SERVICE_DEFAULT_PORT}
Environment=PATH=%h/.local/bin:/usr/local/bin:/usr/bin:/bin
EnvironmentFile=-/etc/default/{SERVICE_NAME}
EnvironmentFile=-%h/.config/{SERVICE_NAME}/service.env
ExecStart=/usr/bin/env electroboy serve
Restart=on-failure
RestartSec=3

[Install]
WantedBy={install_target}
"""


def _service_env_text(
    browse_root: Path,
    state_root: Path,
    host: str,
    port: int,
    session_backend: str,
    command_path: str,
) -> str:
    return "\n".join(
        [
            "# Generated by `electroboy service install`.",
            "# GUI browse/base directory; this does not activate a project.",
            _systemd_env_assignment(SERVICE_ROOT_ENV, str(browse_root)),
            _systemd_env_assignment(SERVICE_STATE_ROOT_ENV, str(state_root)),
            "",
            _systemd_env_assignment(SERVICE_HOST_ENV, host),
            _systemd_env_assignment(SERVICE_PORT_ENV, str(port)),
            _systemd_env_assignment(SERVICE_SESSION_BACKEND_ENV, session_backend),
            _systemd_env_assignment("PATH", command_path),
            "",
        ]
    )


def _service_install_user(args: argparse.Namespace) -> str | None:
    if not args.system:
        return None
    return args.service_user or os.environ.get("SUDO_USER") or os.environ.get("USER")


def _systemd_env_assignment(name: str, value: str) -> str:
    return f"{name}={_quote_systemd_env_value(value)}"


def _quote_systemd_env_value(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return f'"{escaped}"'


def _write_installed_service_file(path: Path, text: str, force: bool) -> None:
    if path.exists() and not force:
        raise StateError(f"{path} already exists; pass --force to overwrite")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        path.chmod(0o644)
    except OSError as error:
        raise StateError(f"could not write {path}: {error}") from error


def _run_systemctl(scope: str, action: list[str], required: bool) -> bool:
    command = ["systemctl"]
    if scope == "user":
        command.append("--user")
    command.extend(action)
    completed = subprocess.run(
        command,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode == 0:
        if completed.stdout.strip():
            print(completed.stdout.strip())
        return True
    message = " ".join(command) + " failed"
    if completed.stderr.strip():
        message += f": {completed.stderr.strip()}"
    if required:
        raise StateError(message)
    print(f"warning: {message}", file=sys.stderr)
    return False


def _service_root(args: argparse.Namespace, root_explicit: bool) -> str:
    if root_explicit:
        return str(args.root)
    return os.environ.get(SERVICE_ROOT_ENV) or str(args.root)


def _service_port_from_environment() -> int:
    value = os.environ.get(SERVICE_PORT_ENV)
    if not value:
        return SERVICE_DEFAULT_PORT
    return _validate_service_port(value, SERVICE_PORT_ENV)


def _validate_service_port(value: object, name: str) -> int:
    try:
        port = int(str(value))
    except ValueError as error:
        raise StateError(f"{name} must be an integer") from error
    if port < 0 or port > 65535:
        raise StateError(f"{name} must be between 0 and 65535")
    return port


def _root_argument_explicit(argv: Sequence[str]) -> bool:
    return "--root" in argv or any(arg.startswith("--root=") for arg in argv)
