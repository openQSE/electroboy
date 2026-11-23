(function () {
  "use strict";
  if (window.ElectroBoyTheme) return;

  const STORAGE_KEY = "electroboy.colorScheme";
  const CHANGE_EVENT = "electroboy-theme-change";
  const schemes = [
    {
      id: "electroboy-dark", label: "ElectroBoy Dark", mode: "dark",
      colors: {
        bg: "#10141f", panel: "#151b29", raised: "#1d2638", inset: "#0d1117",
        text: "#e7edf7", muted: "#aab8cf", border: "#364156",
        accent: "#66d9e8", onAccent: "#10141f", error: "#ff6b6b",
        success: "#51cf66", warning: "#ffd43b", info: "#74c0fc",
        purple: "#da77f2", cyan: "#66d9e8",
      },
    },
    {
      id: "light", label: "ElectroBoy Light", mode: "light",
      colors: {
        bg: "#f6f8fa", panel: "#ffffff", raised: "#eaeef2", inset: "#eef2f6",
        text: "#1f2328", muted: "#57606a", border: "#b8c3cf",
        accent: "#0969da", onAccent: "#ffffff", error: "#b42318",
        success: "#1a7f37", warning: "#8a5600", info: "#0969da",
        purple: "#8250df", cyan: "#0e6b78",
      },
    },
    {
      id: "dracula", label: "Dracula", mode: "dark",
      colors: {
        bg: "#282a36", panel: "#303341", raised: "#44475a", inset: "#21222c",
        text: "#f8f8f2", muted: "#a7b1d2", border: "#6272a4",
        accent: "#bd93f9", onAccent: "#282a36", error: "#ff5555",
        success: "#50fa7b", warning: "#f1fa8c", info: "#8be9fd",
        purple: "#ff79c6", cyan: "#8be9fd",
      },
    },
    {
      id: "nord", label: "Nord", mode: "dark",
      colors: {
        bg: "#2e3440", panel: "#3b4252", raised: "#434c5e", inset: "#272c36",
        text: "#eceff4", muted: "#c2cad8", border: "#66758c",
        accent: "#88c0d0", onAccent: "#2e3440", error: "#e59a9f",
        success: "#a3be8c", warning: "#ebcb8b", info: "#81a1c1",
        purple: "#b48ead", cyan: "#8fbcbb",
      },
    },
    {
      id: "gruvbox", label: "Gruvbox Dark", mode: "dark",
      colors: {
        bg: "#282828", panel: "#32302f", raised: "#3c3836", inset: "#1d2021",
        text: "#ebdbb2", muted: "#bdae93", border: "#7c6f64",
        accent: "#fabd2f", onAccent: "#282828", error: "#fb4934",
        success: "#b8bb26", warning: "#fabd2f", info: "#83a598",
        purple: "#d3869b", cyan: "#8ec07c",
      },
    },
    {
      id: "solarized", label: "Solarized Light", mode: "light",
      colors: {
        bg: "#fdf6e3", panel: "#fdf6e3", raised: "#eee8d5", inset: "#eee8d5",
        text: "#586e75", muted: "#5c7279", border: "#93a1a1",
        accent: "#006b9b", onAccent: "#fdf6e3", error: "#c1322b",
        success: "#526c00", warning: "#8a6500", info: "#006b9b",
        purple: "#8b4899", cyan: "#087f7d",
      },
    },
    {
      id: "catppuccin", label: "Catppuccin Mocha", mode: "dark",
      colors: {
        bg: "#1e1e2e", panel: "#313244", raised: "#45475a", inset: "#181825",
        text: "#cdd6f4", muted: "#a6adc8", border: "#6c7086",
        accent: "#cba6f7", onAccent: "#1e1e2e", error: "#f38ba8",
        success: "#a6e3a1", warning: "#f9e2af", info: "#89b4fa",
        purple: "#f5c2e7", cyan: "#94e2d5",
      },
    },
  ];
  const legacyTerminal = {
    background: "#10141f", foreground: "#e7edf7", cursor: "#e7edf7",
    selectionBackground: "#2b6173", black: "#151923", red: "#ff6b6b",
    green: "#51cf66", yellow: "#ffd43b", blue: "#74c0fc",
    magenta: "#da77f2", cyan: "#66d9e8", white: "#f1f3f5",
    brightBlack: "#5c677d", brightRed: "#ff8787", brightGreen: "#69db7c",
    brightYellow: "#ffe066", brightBlue: "#91caff", brightMagenta: "#e599f7",
    brightCyan: "#99e9f2", brightWhite: "#ffffff",
  };
  let current = schemes[0];
  const boundTerminals = new WeakSet();

  function subscribe(listener) {
    window.addEventListener(CHANGE_EVENT, listener);
    return () => window.removeEventListener(CHANGE_EVENT, listener);
  }

  function apply(id, persist = false) {
    current = schemes.find((scheme) => scheme.id === id) || schemes[0];
    const root = document.documentElement;
    root.dataset.colorScheme = current.id;
    const legacy = current === schemes[0];
    for (const [key, value] of Object.entries(current.colors)) {
      const property = `--theme-${key.replace(/[A-Z]/g, (letter) => `-${letter.toLowerCase()}`)}`;
      if (legacy) root.style.removeProperty(property);
      else root.style.setProperty(property, value);
    }
    if (legacy) root.style.removeProperty("--theme-color-scheme");
    else root.style.setProperty("--theme-color-scheme", current.mode);
    if (persist) {
      try { window.localStorage.setItem(STORAGE_KEY, current.id); }
      catch (_error) { /* The current window remains usable without storage. */ }
    }
    const select = document.getElementById("colorSchemeSelect");
    if (select) select.value = current.id;
    window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: current.id }));
    return current.id;
  }

  function terminalTheme() {
    if (current === schemes[0]) return { ...legacyTerminal };
    const p = current.colors;
    return {
      background: p.bg, foreground: p.text, cursor: p.accent, cursorAccent: p.bg,
      selectionBackground: `${p.border}80`, black: p.inset, brightBlack: p.muted,
      red: p.error, brightRed: p.error, green: p.success, brightGreen: p.success,
      yellow: p.warning, brightYellow: p.warning, blue: p.info, brightBlue: p.info,
      magenta: p.purple, brightMagenta: p.purple, cyan: p.cyan, brightCyan: p.cyan,
      white: p.text, brightWhite: p.text,
    };
  }

  function bindTerminal(terminal) {
    if (!terminal || boundTerminals.has(terminal)) return;
    boundTerminals.add(terminal);
    const update = () => { terminal.options.theme = terminalTheme(); };
    const unsubscribe = subscribe(update);
    const dispose = terminal.dispose.bind(terminal);
    terminal.dispose = (...args) => {
      unsubscribe();
      boundTerminals.delete(terminal);
      return dispose(...args);
    };
    update();
  }

  function mountSelector() {
    const select = document.getElementById("colorSchemeSelect");
    if (!select) return;
    select.replaceChildren(...schemes.map((scheme) => {
      const option = document.createElement("option");
      option.value = scheme.id;
      option.textContent = scheme.label;
      return option;
    }));
    select.value = current.id;
    select.disabled = false;
    select.addEventListener("change", () => apply(select.value, true));
  }

  window.ElectroBoyTheme = {
    get: () => ({ ...current, colors: { ...current.colors } }),
    schemes: () => schemes.map(({ id, label, mode }) => ({ id, label, mode })),
    set: (id) => apply(id, true),
    subscribe,
    terminalTheme,
    bindTerminal,
    ideTheme: () => ({
      mode: current.mode,
      colors: current === schemes[0] ? null : { ...current.colors },
    }),
  };
  let stored;
  try { stored = window.localStorage.getItem(STORAGE_KEY); }
  catch (_error) { /* Use the original scheme when storage is unavailable. */ }
  apply(stored);
  window.addEventListener("storage", (event) => {
    if (event.key === STORAGE_KEY || event.key === null) apply(event.newValue);
  });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", mountSelector, { once: true });
  } else mountSelector();
})();
