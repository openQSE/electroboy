"""Plugin-aware command-line entry point for ElectroBoy."""

from __future__ import annotations

import argparse
import importlib.util
from importlib import metadata
import sys
from typing import Protocol, Sequence

from . import core_cli


CLI_ENTRY_POINT_GROUP = "electroboy.cli"
CORE_COMMANDS = frozenset({"serve", "service"})


class CommandProvider(Protocol):
    """Command provider supplied by an installed workflow package."""

    id: str
    commands: frozenset[str]

    def build_parser(self) -> argparse.ArgumentParser: ...

    def run(self, argv: Sequence[str] | None = None) -> int: ...


def _entry_points() -> tuple[metadata.EntryPoint, ...]:
    discovered = metadata.entry_points()
    if hasattr(discovered, "select"):
        return tuple(discovered.select(group=CLI_ENTRY_POINT_GROUP))
    return tuple(discovered.get(CLI_ENTRY_POINT_GROUP, ()))


def command_providers() -> tuple[CommandProvider, ...]:
    """Load installed command providers without importing optional workflows."""

    providers: dict[str, CommandProvider] = {}
    for entry_point in _entry_points():
        provider = entry_point.load()()
        providers[provider.id] = provider
    if "software" not in providers and _source_software_provider_available():
        from .workflows.software.cli import command_provider

        provider = command_provider()
        providers[provider.id] = provider
    return tuple(providers.values())


def _source_software_provider_available() -> bool:
    try:
        return (
            importlib.util.find_spec("electroboy.workflows.software.cli")
            is not None
        )
    except ModuleNotFoundError:
        return False


def build_parser() -> argparse.ArgumentParser:
    """Build the standard parser from installed command contributions."""

    providers = command_providers()
    if providers:
        return providers[0].build_parser()
    return core_cli.build_parser()


def main(argv: Sequence[str] | None = None) -> int:
    """Dispatch a command to core or an installed workflow provider."""

    raw_argv = list(sys.argv[1:] if argv is None else argv)
    command = _command_name(raw_argv)
    if command in CORE_COMMANDS:
        return core_cli.main(raw_argv)
    providers = command_providers()
    provider = next(
        (candidate for candidate in providers if command in candidate.commands),
        providers[0] if command is None and providers else None,
    )
    if provider is not None:
        return provider.run(raw_argv)
    parser = core_cli.build_parser()
    parser.error(
        "the requested command requires an installed ElectroBoy workflow package"
    )
    return 2


def _command_name(argv: Sequence[str]) -> str | None:
    index = 0
    while index < len(argv):
        argument = argv[index]
        if argument == "--root":
            index += 2
            continue
        if argument.startswith("--root="):
            index += 1
            continue
        if argument.startswith("-"):
            index += 1
            continue
        return argument
    return None


if __name__ == "__main__":
    raise SystemExit(main())
