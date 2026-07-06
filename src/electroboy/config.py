"""Runtime configuration loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class RuntimeConfig:
    """Configured agent runtime command."""

    name: str
    adapter: str
    command: str
    args: list[str] = field(default_factory=list)
    env: list[str] = field(default_factory=list)
    options: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class PipelineConfig:
    """Pipeline runtime configuration."""

    default_runtime: str
    runtimes: dict[str, RuntimeConfig] = field(default_factory=dict)
    roles: dict[str, str] = field(default_factory=dict)
    environment: dict[str, str] = field(default_factory=dict)

    def runtime_for_role(self, role: str) -> RuntimeConfig:
        runtime_name = self.roles.get(role, self.default_runtime)
        try:
            return self.runtimes[runtime_name]
        except KeyError as error:
            raise ConfigError(f"unknown runtime for role {role}: {runtime_name}") from error


class ConfigError(RuntimeError):
    """Raised when runtime configuration is invalid."""


DEFAULT_CONFIG = PipelineConfig(
    default_runtime="codex",
    runtimes={
        "codex": RuntimeConfig(
            name="codex",
            adapter="codex_exec",
            command="codex",
            args=["exec", "--json"],
            env=[
                "PATH",
                "HOME",
                "LANG",
                "LC_ALL",
                "TERM",
                "TMPDIR",
                "CODEX_HOME",
                "OPENAI_API_KEY",
            ],
        ),
        "manual": RuntimeConfig(
            name="manual",
            adapter="manual",
            command="manual",
            env=["PATH"],
        ),
    },
    roles={},
)


def load_pipeline_config(root: Path | str = ".") -> PipelineConfig:
    """Load project runtime configuration or return the default config."""

    root_path = Path(root)
    candidates = [
        root_path / ".electroboy" / "project.toml",
        root_path / "electroboy.toml",
        root_path / ".agent-pipeline" / "project.toml",
        root_path / "agent-pipeline.toml",
    ]
    path = next((candidate for candidate in candidates if candidate.exists()), None)
    if path is None:
        return DEFAULT_CONFIG
    return parse_pipeline_config(path.read_text(encoding="utf-8"))


def parse_pipeline_config(text: str) -> PipelineConfig:
    """Parse the small TOML subset used by the pipeline config."""

    default_runtime = DEFAULT_CONFIG.default_runtime
    runtimes: dict[str, RuntimeConfig] = dict(DEFAULT_CONFIG.runtimes)
    roles: dict[str, str] = {}
    environment: dict[str, str] = {}
    section: str | None = None
    runtime_name: str | None = None
    runtime_data: dict[str, dict[str, object]] = {}

    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            runtime_name = None
            if section.startswith("runtimes."):
                runtime_name = section.split(".", 1)[1]
                runtime_data.setdefault(runtime_name, {})
            continue
        if "=" not in line:
            raise ConfigError(f"invalid config line: {raw_line}")
        key, value = [part.strip() for part in line.split("=", 1)]
        parsed = _parse_value(value)
        if section == "runtime" and key == "default":
            default_runtime = str(parsed)
        elif section == "roles":
            roles[key] = str(parsed)
        elif section == "environment":
            environment[key] = str(parsed).lower() if isinstance(parsed, bool) else str(parsed)
        elif section and section.startswith("runtimes.") and runtime_name:
            runtime_data.setdefault(runtime_name, {})[key] = parsed
        else:
            raise ConfigError(f"unsupported config setting: {raw_line}")

    for name, data in runtime_data.items():
        adapter = str(data.get("adapter", name))
        command = str(data.get("command", name))
        args = data.get("args", [])
        if not isinstance(args, list):
            raise ConfigError(f"runtime {name} args must be a list")
        env = data.get("env", [])
        if not isinstance(env, list):
            raise ConfigError(f"runtime {name} env must be a list")
        options = {
            key: str(value)
            for key, value in data.items()
            if key not in {"adapter", "command", "args", "env"}
        }
        runtimes[name] = RuntimeConfig(
            name=name,
            adapter=adapter,
            command=command,
            args=[str(arg) for arg in args],
            env=[str(env_name) for env_name in env],
            options=options,
        )

    if default_runtime not in runtimes:
        raise ConfigError(f"unknown default runtime: {default_runtime}")
    return PipelineConfig(default_runtime, runtimes, roles, environment)


def _parse_value(value: str) -> object:
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("[") and value.endswith("]"):
        body = value[1:-1].strip()
        if not body:
            return []
        return [_parse_value(part.strip()) for part in body.split(",")]
    return value
