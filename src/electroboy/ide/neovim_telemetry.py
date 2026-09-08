"""Deterministic input tracing for the pinned VSCode Neovim extension."""

from __future__ import annotations

import json
from pathlib import Path

TRACE_PREFIX = "[ElectroBoy input trace]"
_SCHEMA_VERSION = 2

_PATCHES = (
    (
        "vscode-neovim.send implementation entered",
        "if(_e.debug(`Send for: ${t}`),this.main.cursorManager",
        "if(_e.info(`[ElectroBoy input trace] "
        "vscode-neovim.send implementation entered: "
        '${t.length>1?t:"<printable>"}`),this.main.cursorManager',
    ),
    (
        "Neovim RPC request sent",
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
        "Neovim cursor update received",
        "A.debug(`Received cursor update from neovim, gridId: ${e}`);",
        "A.info(`[ElectroBoy input trace] Neovim cursor update received, "
        "gridId: ${e}`);",
    ),
    (
        "Monaco cursor synchronized",
        "&&(t.selections=c),this.neovimCursorPosition.set(t,c[0])",
        "&&(t.selections=c),A.info(`[ElectroBoy input trace] "
        "Monaco cursor synchronized, line: ${c[0].active.line+1}, "
        "column: ${c[0].active.character+1}`),"
        "this.neovimCursorPosition.set(t,c[0])",
    ),
    (
        "vscode-neovim.send handler entered",
        "const i=t=>n=>{if(n)return t.apply(this,[n]);{const t=",
        "const i=t=>n=>{if(_e.info(`[ElectroBoy input trace] "
        "vscode-neovim.send handler entered, argument: "
        '${typeof n==="string"?(n.length>1?n:"<printable>"):typeof n}`),n){'
        "const $ebResult=t.apply(this,[n]);return Promise.resolve($ebResult).then("
        '(e=>(_e.info("[ElectroBoy input trace] '
        'vscode-neovim.send handler completed"),e)),(e=>{throw _e.error('
        "`[ElectroBoy input trace] vscode-neovim.send handler rejected: "
        '${String(e).slice(0,240)}`),e}))}{_e.error("[ElectroBoy input trace] '
        'vscode-neovim.send handler rejected: missing argument");const t=',
    ),
)


def instrument_neovim_extension(extension: Path) -> None:
    """Add sanitized stage telemetry to the exact pinned extension bundle."""

    bundle = extension / "dist" / "extension.js"
    source = bundle.read_text(encoding="utf-8")
    instrumented = source.replace(
        "vscode-neovim.send invoked:",
        "vscode-neovim.send implementation entered:",
    )
    for marker, original, replacement in _PATCHES:
        if marker in instrumented:
            continue
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
        json.dumps(
            {"schema_version": _SCHEMA_VERSION, "trace_prefix": TRACE_PREFIX},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
