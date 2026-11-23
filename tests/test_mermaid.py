"""Preserve diagram-specific layout defaults and explicit source configuration."""

import shutil
import subprocess
from pathlib import Path

import pytest

NODE = shutil.which("node")
ASSET = (
    Path(__file__).resolve().parents[1]
    / "src/electroboy/assets/service/js/core/mermaid.js"
)


@pytest.mark.skipif(NODE is None, reason="Node.js is not installed")
def test_rendering_and_theme_changes_preserve_layout_defaults_and_overrides():
    script = r"""
const assert = require('assert/strict');
const fs = require('fs');
const vm = require('vm');
const sources = [
  'mindmap\n  root((Project))\n    Requirements\n    Design',
  '---\nconfig:\n  layout: elk\n---\nflowchart TB\nA --> B',
  '---\nconfig:\n  layout: dagre\n---\nflowchart TB\nA --> B',
];
const diagrams = sources.map((source) => {
  let text = source;
  const node = {
    dataset: {}, svg: false,
    get textContent() { return text; },
    set textContent(value) { text = value; this.svg = false; },
    querySelector() { return this.svg; },
    removeAttribute() {}, setAttribute() {}, addEventListener() {},
  };
  return node;
});
const document = {
  readyState: 'loading',
  addEventListener() {},
  querySelectorAll() { return diagrams; },
};
let theme = {id: 'electroboy-dark'};
let onTheme;
const configurations = [];
const runs = [];
const window = {
  dispatchEvent() {},
  ElectroBoyTheme: {
    get: () => theme,
    subscribe(callback) { onTheme = callback; },
  },
  mermaid: {
    initialize(config) { configurations.push(config); },
    async run({nodes}) {
      runs.push(Array.from(nodes, node => node.textContent));
      nodes.forEach(node => { node.svg = true; });
    },
  },
};
vm.runInNewContext(fs.readFileSync(process.argv[1], 'utf8'), {
  document, window, CustomEvent: class {},
});
async function check() {
  await window.ElectroBoyMermaid.render(document);
  assert.deepEqual(runs[0], sources);
  theme = {id: 'light', mode: 'light', colors: {
    bg: '#ffffff', panel: '#ffffff', raised: '#eeeeee', text: '#111111',
    border: '#aaaaaa', accent: '#0969da',
  }};
  onTheme();
  await window.ElectroBoyMermaid.render(document);
  assert.equal(configurations.length, 2);
  for (const config of configurations) {
    // Mermaid's default chooses ELK for flowcharts and cose-bilkent for mindmaps.
    assert.equal(config.layout, undefined);
    assert.equal(config.look, 'classic');
    assert.equal(config.securityLevel, 'strict');
  }
  assert.deepEqual(runs[1], sources);
  assert.equal(configurations[1].themeVariables.background, '#ffffff');
}
check().catch(error => { console.error(error); process.exitCode = 1; });
"""
    completed = subprocess.run(
        [NODE, "-e", script, str(ASSET)],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
