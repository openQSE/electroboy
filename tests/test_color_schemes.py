"""Shared color preferences must survive reloads and update existing surfaces."""

import json
import shutil
import subprocess
import threading
import urllib.request
from pathlib import Path

import pytest

from electroboy.service.app import create_server
from electroboy.service.frontend import with_theme_assets

ROOT = Path(__file__).resolve().parents[1]
THEME = ROOT / "src/electroboy/assets/service/js/core/theme.js"
NODE = shutil.which("node")

HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8');
function boot(stored = null, storageBlocked = false) {
  const window = new EventTarget();
  const select = new EventTarget();
  select.replaceChildren = (...options) => { select.options = options; };
  select.value = ''; select.disabled = true;
  const properties = new Map([['--font-size', '18px']]);
  const values = new Map([['electroboy.colorScheme', stored]]);
  window.localStorage = {
    getItem(key) { if (storageBlocked) throw Error('blocked'); return values.get(key); },
    setItem(key, value) { if (storageBlocked) throw Error('blocked'); values.set(key, value); },
  };
  const document = {
    readyState: 'complete',
    documentElement: { dataset: {}, style: {
      setProperty(key, value) { properties.set(key, value); },
      removeProperty(key) { properties.delete(key); },
    } },
    getElementById(id) { return id === 'colorSchemeSelect' ? select : null; },
    createElement() { return {}; },
  };
  class CustomEvent extends Event { constructor(type, init) { super(type); this.detail = init.detail; } }
  vm.runInNewContext(source, { window, document, CustomEvent });
  return { window, document, select, properties, values, api: window.ElectroBoyTheme };
}
"""


def run_node(script):
    if not NODE:
        pytest.skip("Node.js is not installed")
    result = subprocess.run(
        [NODE, "-e", HARNESS + script, str(THEME)],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_scheme_selection_storage_sync_and_terminal_lifecycle():
    run_node(r"""
const env = boot();
const {api, select, properties, values, window} = env;
assert.equal(api.schemes().length, 7);
assert.equal(select.disabled, false);
assert.equal(select.options.length, 7);
assert.equal(api.get().id, 'electroboy-dark');
assert.equal(properties.has('--theme-bg'), false);
assert.equal(api.terminalTheme().background, '#10141f');
const terminal = { options: {fontSize: 18}, dispose() { this.disposed = true; } };
api.bindTerminal(terminal);
api.bindTerminal(terminal);
let events = 0;
const unsubscribe = api.subscribe(() => { events += 1; });
select.value = 'light';
select.dispatchEvent(new Event('change'));
assert.equal(api.get().mode, 'light');
assert.equal(values.get('electroboy.colorScheme'), 'light');
assert.equal(properties.get('--theme-bg'), '#f6f8fa');
assert.equal(terminal.options.theme.background, '#f6f8fa');
assert.equal(terminal.options.fontSize, 18);
assert.equal(boot(values.get('electroboy.colorScheme')).api.get().id, 'light');
const sync = new Event('storage');
sync.key = 'electroboy.colorScheme'; sync.newValue = 'nord';
window.dispatchEvent(sync);
assert.equal(select.value, 'nord');
assert.equal(terminal.options.theme.background, '#2e3440');
terminal.dispose();
api.set('dracula');
assert.equal(terminal.options.theme.background, '#2e3440');
unsubscribe();
assert.equal(events, 3);
api.set('not-a-scheme');
assert.equal(api.get().id, 'electroboy-dark');
assert.equal(properties.has('--theme-bg'), false);
assert.equal(properties.get('--font-size'), '18px');
assert.equal(api.ideTheme().colors, null);
""")


def test_unavailable_or_invalid_storage_does_not_break_selection():
    run_node(r"""
assert.equal(boot('obsolete').api.get().id, 'electroboy-dark');
const env = boot(null, true);
env.api.set('solarized');
assert.equal(env.api.get().mode, 'light');
assert.equal(env.properties.get('--theme-bg'), '#fdf6e3');
""")


def test_palette_text_contrast_and_independent_choices():
    palettes = json.loads(run_node(r"""
const api = boot().api;
console.log(JSON.stringify(api.schemes().map(({id}) => { api.set(id); return api.get(); })));
"""))
    assert len({palette["colors"]["bg"] for palette in palettes}) == 7

    def luminance(color):
        values = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [value / 12.92 if value <= .04045 else ((value + .055) / 1.055) ** 2.4
                  for value in values]
        return sum(value * weight for value, weight in zip(linear, (.2126, .7152, .0722)))

    def contrast(first, second):
        low, high = sorted((luminance(first), luminance(second)))
        return (high + .05) / (low + .05)

    for palette in palettes:
        colors = palette["colors"]
        assert contrast(colors["text"], colors["bg"]) >= 4.5, palette["id"]
        assert contrast(colors["muted"], colors["panel"]) >= 4.5, palette["id"]
        assert contrast(colors["onAccent"], colors["accent"]) >= 4.5, palette["id"]


def test_theme_assets_are_added_once_before_page_styles():
    page = '<html><head><style>body { color: red; }</style></head><body></body></html>'
    themed = with_theme_assets(page)
    assert themed.count("/js/core/theme.js") == 1
    assert themed.index("/js/core/theme.js") < themed.index("<style>")
    assert with_theme_assets(themed) == themed
    assert "/js/core/theme.js" in with_theme_assets(
        '<html><HEAD></HEAD><body><code>data-electroboy-theme</code></body></html>'
    )
    assert with_theme_assets("<section>A fragment</section>") == "<section>A fragment</section>"


def test_theme_assets_reach_shell_detached_panes_and_documents(tmp_path):
    server = create_server(tmp_path / "service", port=0)
    context_id = server.service_state.create_context()["context_id"]
    opened = server.service_state.create_project(context_id, str(tmp_path / "project"))
    context_id = opened.get("context_id", context_id)
    server.service_state.select_workflow_stage(context_id, "requirements")
    server.service_state.contexts[context_id].requirements_started = True
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        for path in ("/", f"/pane/agent?context_id={context_id}", f"/artifacts/requirements?context_id={context_id}",
                     f"/artifacts/edit?artifact=requirements&context_id={context_id}"):
            response = urllib.request.urlopen(origin + path)
            page = response.read().decode()
            assert page.count('/js/core/theme.js') == 1, path
            assert '/css/themes.css' in page, path
        for path, expected in (("/js/core/theme.js", "application/javascript"),
                               ("/css/themes.css", "text/css")):
            response = urllib.request.urlopen(origin + "/assets/service" + path)
            assert response.headers.get_content_type() == expected
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_ide_extension_applies_and_restores_workbench_and_syntax_colors():
    extension = ROOT / "src/electroboy/ide/extensions/electroboy-bridge/extension.js"
    run_node(r"""
const updates = new Map();
const context = { module: { exports: {} }, require(id) {
  if (id !== 'vscode') return require(id);
  return { ConfigurationTarget: { Global: 1 }, workspace: {
    getConfiguration(section) { return {
      async update(key, value) { updates.set(`${section}.${key}`, value); },
    }; },
  } };
} };
vm.runInNewContext(fs.readFileSync(""" + json.dumps(str(extension)) + r""", 'utf8') +
  '\nmodule.exports.applyScheme = applyColorScheme;', context);
async function check() {
  const api = boot().api;
  api.set('light');
  await context.module.exports.applyScheme(api.ideTheme());
  assert.equal(updates.get('workbench.colorTheme'), 'Default Light Modern');
  const colors = updates.get('workbench.colorCustomizations');
  assert.equal(colors['editor.background'], '#f6f8fa');
  assert.equal(colors['sideBar.foreground'], '#1f2328');
  assert.equal(colors['tab.activeBackground'], '#f6f8fa');
  assert.equal(colors['menu.selectionForeground'], '#ffffff');
  assert.equal(updates.get('editor.tokenColorCustomizations').comments, '#57606a');
  api.set('electroboy-dark');
  await context.module.exports.applyScheme(api.ideTheme());
  assert.equal(updates.get('workbench.colorTheme'), 'ElectroBoy');
  assert.equal(updates.get('workbench.colorCustomizations'), undefined);
  assert.equal(updates.get('editor.tokenColorCustomizations'), undefined);
}
check().catch((error) => { console.error(error); process.exitCode = 1; });
""")
