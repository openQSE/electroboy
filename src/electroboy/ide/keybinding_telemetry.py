"""Managed OpenVSCode keybinding-resolution telemetry."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from .domain import IDERuntime, IDERuntimeOrigin

RESOLUTION_EVENT = "electroboy-keybinding-resolution"

_BUNDLE_PATH = Path("out/vs/code/browser/workbench/workbench.js")
_HTML_PATH = Path("out/vs/code/browser/workbench/workbench.html")
_MARKER_NAME = ".electroboy-keybinding-telemetry.json"
_SCHEMA_VERSION = 2
_CACHE_KEY = "electroboy-keybinding-telemetry=2"
_ANCHOR = (
    "const r=this.s.getContext(e),a=s.getLabel(),"
    "l=this.z().resolve(r,o,n);switch(l.kind){"
)
_REPLACEMENT = (
    "const r=this.s.getContext(e),a=s.getLabel(),"
    "l=this.z().resolve(r,o,n),"
    "$ebValue=e=>{try{return r.getValue(e)}catch{return void 0}},"
    '$ebExclusions=$ebValue("neovim.editorLangIdExclusions");'
    f'window.dispatchEvent(new CustomEvent("{RESOLUTION_EVENT}",{{detail:{{'
    "key_label:a,dispatch_chord:n,resolution_kind:l.kind,"
    "resolved_command:l.kind===2?l.commandId:null,"
    "context:{"
    'editor_text_focus:$ebValue("editorTextFocus"),'
    'neovim_init:$ebValue("neovim.init"),'
    'neovim_mode:$ebValue("neovim.mode"),'
    'editor_language:$ebValue("editorLangId"),'
    'neovim_recording:$ebValue("neovim.recording"),'
    "editor_language_exclusions:Array.isArray($ebExclusions)"
    "?$ebExclusions.slice(0,32):$ebExclusions"
    "}}}));switch(l.kind){"
)
_HTML_ANCHOR = (
    'src="{{WORKBENCH_WEB_BASE_URL}}/out/vs/code/browser/workbench/workbench.js"'
)
_HTML_REPLACEMENT = (
    'src="{{WORKBENCH_WEB_BASE_URL}}/out/vs/code/browser/workbench/workbench.js?'
    f'{_CACHE_KEY}"'
)

_LOCK = threading.Lock()


def instrument_keybinding_resolver(runtime: IDERuntime) -> bool:
    """Instrument a pinned managed runtime before its browser process starts."""

    if runtime.origin is not IDERuntimeOrigin.MANAGED:
        return False
    root = runtime.executable.parent.parent
    bundle = root / _BUNDLE_PATH
    html = root / _HTML_PATH
    marker = root / _MARKER_NAME
    with _LOCK:
        source = bundle.read_text(encoding="utf-8")
        if RESOLUTION_EVENT not in source:
            count = source.count(_ANCHOR)
            if count != 1:
                raise ValueError(
                    "OpenVSCode keybinding telemetry contract mismatch: "
                    f"expected one resolver anchor, found {count}"
                )
            bundle.write_text(
                source.replace(_ANCHOR, _REPLACEMENT, 1), encoding="utf-8"
            )
        html_source = html.read_text(encoding="utf-8")
        if _CACHE_KEY not in html_source:
            count = html_source.count(_HTML_ANCHOR)
            if count != 1:
                raise ValueError(
                    "OpenVSCode keybinding telemetry contract mismatch: "
                    f"expected one workbench HTML anchor, found {count}"
                )
            html.write_text(
                html_source.replace(_HTML_ANCHOR, _HTML_REPLACEMENT, 1),
                encoding="utf-8",
            )
        marker.write_text(
            json.dumps(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "event": RESOLUTION_EVENT,
                    "runtime_version": runtime.version,
                    "cache_key": _CACHE_KEY,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return True
