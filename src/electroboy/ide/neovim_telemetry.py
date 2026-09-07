"""Deterministic input tracing for the pinned VSCode Neovim extension."""

from __future__ import annotations

import json
from pathlib import Path

TRACE_PREFIX = "[ElectroBoy input trace]"

_PATCHES = (
    (
        "if(_e.debug(`Send for: ${t}`),this.main.cursorManager",
        "if(_e.info(`[ElectroBoy input trace] vscode-neovim.send invoked: "
        '${t.length>1?t:"<printable>"}`),this.main.cursorManager',
    ),
    (
        'this.pendingKeysAfterExit="",yield this.client.input(`${t}${n}`)}'
        "else this.isExitingInsertMode=!1,"
        "yield this.client.input(`${t}`)}",
        'this.pendingKeysAfterExit="",_e.info(`[ElectroBoy input trace] '
        'Neovim RPC request sent: ${t.length>1?t:"<printable>"}`),'
        "yield this.client.input(`${t}${n}`),"
        '_e.info("[ElectroBoy input trace] Neovim RPC input completed")}'
        "else this.isExitingInsertMode=!1,"
        "_e.info(`[ElectroBoy input trace] Neovim RPC request sent: "
        '${t.length>1?t:"<printable>"}`),yield this.client.input(`${t}`),'
        '_e.info("[ElectroBoy input trace] Neovim RPC input completed")}',
    ),
    (
        "A.debug(`Received cursor update from neovim, gridId: ${e}`);",
        "A.info(`[ElectroBoy input trace] Neovim cursor update received, "
        "gridId: ${e}`);",
    ),
    (
        "&&(t.selections=c),this.neovimCursorPosition.set(t,c[0])",
        "&&(t.selections=c),A.info(`[ElectroBoy input trace] "
        "Monaco cursor synchronized, line: ${c[0].active.line+1}, "
        "column: ${c[0].active.character+1}`),"
        "this.neovimCursorPosition.set(t,c[0])",
    ),
)


def instrument_neovim_extension(extension: Path) -> None:
    """Add sanitized stage telemetry to the exact pinned extension bundle."""

    bundle = extension / "dist" / "extension.js"
    source = bundle.read_text(encoding="utf-8")
    if TRACE_PREFIX in source:
        return
    instrumented = source
    for original, replacement in _PATCHES:
        count = instrumented.count(original)
        if count != 1:
            raise ValueError(
                "VSCode Neovim telemetry contract mismatch: "
                f"expected one bundle anchor, found {count}"
            )
        instrumented = instrumented.replace(original, replacement, 1)
    bundle.write_text(instrumented, encoding="utf-8")
    marker = extension / ".electroboy-input-telemetry.json"
    marker.write_text(
        json.dumps({"schema_version": 1, "trace_prefix": TRACE_PREFIX}, indent=2)
        + "\n",
        encoding="utf-8",
    )
