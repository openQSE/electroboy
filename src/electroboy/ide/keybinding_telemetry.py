"""Managed OpenVSCode keybinding-resolution telemetry."""

from __future__ import annotations

import json
import threading
from pathlib import Path

from .domain import IDERuntime, IDERuntimeOrigin

RESOLUTION_EVENT = "electroboy-keybinding-resolution"
COMMAND_EVENT = "electroboy-keybinding-command"
ROUTE_EVENT = "electroboy-command-route"

_BUNDLE_PATH = Path("out/vs/code/browser/workbench/workbench.js")
_EXTENSION_HOST_PATH = Path("out/vs/workbench/api/node/extensionHostProcess.js")
_HTML_PATH = Path("out/vs/code/browser/workbench/workbench.html")
_MARKER_NAME = ".electroboy-keybinding-telemetry.json"
_SCHEMA_VERSION = 4
_CACHE_KEY = "electroboy-keybinding-telemetry=4"
_ANCHOR = (
    "const r=this.s.getContext(e),a=s.getLabel(),"
    "l=this.z().resolve(r,o,n);switch(l.kind){"
)
_REPLACEMENT = (
    "const r=this.s.getContext(e),a=s.getLabel(),"
    "l=this.z().resolve(r,o,n),"
    '$ebTraceId=l.kind===2?Date.now().toString(36)+"-"+'
    "Math.random().toString(36).slice(2,10):null,"
    "$ebValue=e=>{try{return r.getValue(e)}catch{return void 0}},"
    '$ebExclusions=$ebValue("neovim.editorLangIdExclusions");'
    "l.kind===2&&(window.__electroboyCommandTraceId=$ebTraceId);"
    f'window.dispatchEvent(new CustomEvent("{RESOLUTION_EVENT}",{{detail:{{'
    "trace_id:$ebTraceId,key_label:a,dispatch_chord:n,resolution_kind:l.kind,"
    "resolved_command:l.kind===2?l.commandId:null,"
    'command_args:l.kind===2&&l.commandId==="vscode-neovim.send"'
    "?l.commandArgs:null,"
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
_COMMAND_ANCHOR = (
    'typeof l.commandArgs>"u"?this.t.executeCommand(l.commandId)'
    ".then(void 0,c=>this.w.warn(c)):this.t.executeCommand("
    "l.commandId,l.commandArgs).then(void 0,c=>this.w.warn(c))"
)
_COMMAND_REPLACEMENT = (
    '(typeof l.commandArgs>"u"?this.t.executeCommand(l.commandId):'
    "this.t.executeCommand(l.commandId,l.commandArgs)).then("
    '()=>l.commandId==="vscode-neovim.send"&&window.dispatchEvent('
    f'new CustomEvent("{COMMAND_EVENT}",'
    "{detail:{trace_id:$ebTraceId,resolved_command:l.commandId,"
    "command_args:l.commandArgs,"
    'status:"completed"}})),c=>{l.commandId==="vscode-neovim.send"&&'
    f'window.dispatchEvent(new CustomEvent("{COMMAND_EVENT}",'
    "{detail:{trace_id:$ebTraceId,resolved_command:l.commandId,"
    "command_args:l.commandArgs,"
    'status:"rejected",error:String(c).slice(0,240)}}));this.w.warn(c)})'
)
_MAIN_THREAD_ANCHOR = (
    "$registerCommand(e){this.a.set(e,Fe.registerCommand(e,(t,...i)=>"
    "this.c.$executeContributedCommand(e,...i).then(n=>ko(n))))}"
)
_MAIN_THREAD_REPLACEMENT = (
    "$registerCommand(e){this.a.set(e,Fe.registerCommand(e,(t,...i)=>{"
    'const $ebTraceId=e==="vscode-neovim.send"?'
    "window.__electroboyCommandTraceId||null:null;"
    'e==="vscode-neovim.send"&&(window.__electroboyCommandTraceId=null,'
    f'window.dispatchEvent(new CustomEvent("{ROUTE_EVENT}",{{detail:{{'
    'stage:"main-thread-forward",trace_id:$ebTraceId,command:e,'
    "command_args:i[0]}})));"
    "return this.c.$executeContributedCommand(e,...i).then(n=>{"
    'e==="vscode-neovim.send"&&window.dispatchEvent('
    f'new CustomEvent("{ROUTE_EVENT}",{{detail:{{'
    'stage:"main-thread-completed",trace_id:$ebTraceId,command:e}}));'
    "return ko(n)},n=>{"
    'e==="vscode-neovim.send"&&window.dispatchEvent('
    f'new CustomEvent("{ROUTE_EVENT}",{{detail:{{'
    'stage:"main-thread-rejected",trace_id:$ebTraceId,command:e,'
    "error:String(n).slice(0,240)}}));throw n})}))}"
)
_EXTENSION_HOST_ANCHOR = (
    "$executeContributedCommand(t,...i){this.d.trace("
    '"ExtHostCommands#$executeContributedCommand",t);const s=this.b.get(t);'
    "return s?(i=i.map(r=>this.f.reduce((n,o)=>"
    "o.processArgument(n,s.extension),r)),this.h(t,i,!0)):"
    "Promise.reject(new Error(`Contributed command '${t}' does not exist.`))}"
)
_EXTENSION_HOST_REPLACEMENT = (
    "$executeContributedCommand(t,...i){this.d.trace("
    '"ExtHostCommands#$executeContributedCommand",t);'
    'const $ebTrace=t==="vscode-neovim.send";'
    '$ebTrace&&this.d.info("[ElectroBoy command route] '
    'extension-host-received",t);const s=this.b.get(t);'
    '$ebTrace&&this.d.info("[ElectroBoy command route] '
    'contributed-command-lookup",t,Boolean(s));return s?'
    "(i=i.map(r=>this.f.reduce((n,o)=>"
    "o.processArgument(n,s.extension),r)),"
    '$ebTrace&&this.d.info("[ElectroBoy command route] '
    'contributed-command-invoking",t),this.h(t,i,!0)):'
    "Promise.reject(new Error(`Contributed command '${t}' does not exist.`))}"
)
_HTML_ANCHOR = (
    'src="{{WORKBENCH_WEB_BASE_URL}}/out/vs/code/browser/workbench/workbench.js"'
)
_HTML_REPLACEMENT = (
    'src="{{WORKBENCH_WEB_BASE_URL}}/out/vs/code/browser/workbench/workbench.js?'
    f'{_CACHE_KEY}"'
)
_PRIOR_HTML_REPLACEMENTS = (
    _HTML_ANCHOR,
    _HTML_ANCHOR[:-1] + '?electroboy-keybinding-telemetry=2"',
    _HTML_ANCHOR[:-1] + '?electroboy-keybinding-telemetry=3"',
)

_LOCK = threading.Lock()


def instrument_keybinding_resolver(runtime: IDERuntime) -> bool:
    """Instrument a pinned managed runtime before its browser process starts."""

    if runtime.origin is not IDERuntimeOrigin.MANAGED:
        return False
    root = runtime.executable.parent.parent
    bundle = root / _BUNDLE_PATH
    extension_host = root / _EXTENSION_HOST_PATH
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
            source = bundle.read_text(encoding="utf-8")
        elif "command_args:" not in source:
            argument_anchor = "resolved_command:l.kind===2?l.commandId:null,context:{"
            count = source.count(argument_anchor)
            if count != 1:
                raise ValueError(
                    "OpenVSCode keybinding telemetry contract mismatch: "
                    f"expected one command-argument anchor, found {count}"
                )
            source = source.replace(
                argument_anchor,
                "resolved_command:l.kind===2?l.commandId:null,command_args:"
                'l.kind===2&&l.commandId==="vscode-neovim.send"'
                "?l.commandArgs:null,context:{",
                1,
            )
            bundle.write_text(source, encoding="utf-8")
        if "trace_id:$ebTraceId" not in source:
            source = _upgrade_trace_correlation(source)
            bundle.write_text(source, encoding="utf-8")
        if COMMAND_EVENT not in source:
            count = source.count(_COMMAND_ANCHOR)
            if count != 1:
                raise ValueError(
                    "OpenVSCode keybinding telemetry contract mismatch: "
                    f"expected one command-service anchor, found {count}"
                )
            source = source.replace(_COMMAND_ANCHOR, _COMMAND_REPLACEMENT, 1)
            bundle.write_text(source, encoding="utf-8")
        source = _repair_route_event_syntax(source)
        bundle.write_text(source, encoding="utf-8")
        if ROUTE_EVENT not in source:
            count = source.count(_MAIN_THREAD_ANCHOR)
            if count != 1:
                raise ValueError(
                    "OpenVSCode keybinding telemetry contract mismatch: "
                    f"expected one main-thread command anchor, found {count}"
                )
            source = source.replace(
                _MAIN_THREAD_ANCHOR,
                _MAIN_THREAD_REPLACEMENT,
                1,
            )
            bundle.write_text(source, encoding="utf-8")
        extension_host_source = extension_host.read_text(encoding="utf-8")
        if "[ElectroBoy command route] extension-host-received" not in (
            extension_host_source
        ):
            count = extension_host_source.count(_EXTENSION_HOST_ANCHOR)
            if count != 1:
                raise ValueError(
                    "OpenVSCode keybinding telemetry contract mismatch: "
                    f"expected one extension-host command anchor, found {count}"
                )
            extension_host.write_text(
                extension_host_source.replace(
                    _EXTENSION_HOST_ANCHOR,
                    _EXTENSION_HOST_REPLACEMENT,
                    1,
                ),
                encoding="utf-8",
            )
        html_source = html.read_text(encoding="utf-8")
        if _CACHE_KEY not in html_source:
            prior = next(
                (item for item in _PRIOR_HTML_REPLACEMENTS if item in html_source),
                None,
            )
            if prior is None:
                raise ValueError(
                    "OpenVSCode keybinding telemetry contract mismatch: "
                    "expected one workbench HTML anchor, found 0"
                )
            html.write_text(
                html_source.replace(prior, _HTML_REPLACEMENT, 1),
                encoding="utf-8",
            )
        marker.write_text(
            json.dumps(
                {
                    "schema_version": _SCHEMA_VERSION,
                    "event": RESOLUTION_EVENT,
                    "command_event": COMMAND_EVENT,
                    "route_event": ROUTE_EVENT,
                    "extension_host_trace": "[ElectroBoy command route]",
                    "runtime_version": runtime.version,
                    "cache_key": _CACHE_KEY,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return True


def _upgrade_trace_correlation(source: str) -> str:
    resolution_anchor = "l=this.z().resolve(r,o,n),$ebValue="
    resolution_replacement = (
        "l=this.z().resolve(r,o,n),"
        '$ebTraceId=l.kind===2?Date.now().toString(36)+"-"+'
        "Math.random().toString(36).slice(2,10):null,$ebValue="
    )
    dispatch_anchor = (
        '$ebExclusions=$ebValue("neovim.editorLangIdExclusions");'
        f'window.dispatchEvent(new CustomEvent("{RESOLUTION_EVENT}"'
    )
    dispatch_replacement = (
        '$ebExclusions=$ebValue("neovim.editorLangIdExclusions");'
        "l.kind===2&&(window.__electroboyCommandTraceId=$ebTraceId);"
        f'window.dispatchEvent(new CustomEvent("{RESOLUTION_EVENT}"'
    )
    detail_anchor = "{detail:{key_label:a,dispatch_chord:n"
    command_detail_anchor = "{detail:{resolved_command:l.commandId"
    expected = {
        resolution_anchor: 1,
        dispatch_anchor: 1,
        detail_anchor: 1,
        command_detail_anchor: 2,
    }
    for anchor, count in expected.items():
        actual = source.count(anchor)
        if actual != count:
            raise ValueError(
                "OpenVSCode keybinding telemetry contract mismatch: "
                f"expected {count} trace-correlation anchors, found {actual}"
            )
    source = source.replace(resolution_anchor, resolution_replacement, 1)
    source = source.replace(dispatch_anchor, dispatch_replacement, 1)
    source = source.replace(
        detail_anchor,
        "{detail:{trace_id:$ebTraceId,key_label:a,dispatch_chord:n",
        1,
    )
    return source.replace(
        command_detail_anchor,
        "{detail:{trace_id:$ebTraceId,resolved_command:l.commandId",
    )


def _repair_route_event_syntax(source: str) -> str:
    repairs = {
        "command_args:i[0]}}})));": "command_args:i[0]}})));",
        "command:e}}}));return": "command:e}}));return",
        "error:String(n).slice(0,240)}}}));throw": (
            "error:String(n).slice(0,240)}}));throw"
        ),
    }
    for malformed, corrected in repairs.items():
        source = source.replace(malformed, corrected)
    return source
