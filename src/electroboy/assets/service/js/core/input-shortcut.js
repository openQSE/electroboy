(function () {
  "use strict";

  const STORAGE_KEY = "electroboy.agentSendShortcut.v1";
  const DEFAULT_SHORTCUT = Object.freeze({
    key: "Enter",
    alt: false,
    ctrl: false,
    meta: false,
    shift: true,
  });
  const MODIFIER_KEYS = new Set([
    "Alt",
    "AltGraph",
    "Control",
    "Meta",
    "Shift",
  ]);

  function normalizedKey(value) {
    const key = String(value || "");
    if (key === " ") return "Space";
    if (key === "Esc") return "Escape";
    if (key.length === 1) return key.toUpperCase();
    return key;
  }

  function normalize(shortcut) {
    const candidate = shortcut && typeof shortcut === "object" ? shortcut : {};
    const key = normalizedKey(candidate.key);
    if (!key || MODIFIER_KEYS.has(key) || key === "Escape") {
      return { ...DEFAULT_SHORTCUT };
    }
    return {
      key,
      alt: Boolean(candidate.alt),
      ctrl: Boolean(candidate.ctrl),
      meta: Boolean(candidate.meta),
      shift: Boolean(candidate.shift),
    };
  }

  function load() {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      return stored ? normalize(JSON.parse(stored)) : { ...DEFAULT_SHORTCUT };
    } catch (error) {
      return { ...DEFAULT_SHORTCUT };
    }
  }

  function save(shortcut) {
    const normalized = normalize(shortcut);
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(normalized));
    } catch (error) {
      return normalized;
    }
    return normalized;
  }

  function eventShortcut(event) {
    return normalize({
      key: event.key,
      alt: event.altKey,
      ctrl: event.ctrlKey,
      meta: event.metaKey,
      shift: event.shiftKey,
    });
  }

  function validEventShortcut(event) {
    if (!event.key || MODIFIER_KEYS.has(event.key) || event.key === "Escape") {
      return false;
    }
    return event.key === "Enter" || event.altKey || event.ctrlKey ||
      event.metaKey || event.shiftKey;
  }

  function keyLabel(key) {
    const labels = {
      ArrowDown: "Down",
      ArrowLeft: "Left",
      ArrowRight: "Right",
      ArrowUp: "Up",
      Backspace: "Backspace",
      Delete: "Delete",
      Enter: "Enter",
      Space: "Space",
      Tab: "Tab",
    };
    return labels[key] || key;
  }

  function label(shortcut) {
    const normalized = normalize(shortcut);
    const parts = [];
    if (normalized.ctrl) parts.push("Ctrl");
    if (normalized.alt) parts.push("Alt");
    if (normalized.shift) parts.push("Shift");
    if (normalized.meta) parts.push("Meta");
    parts.push(keyLabel(normalized.key));
    return parts.join("+");
  }

  function modifierLabel(event) {
    const parts = [];
    if (event.ctrlKey || event.key === "Control") parts.push("Ctrl");
    if (event.altKey || event.key === "Alt") parts.push("Alt");
    if (event.shiftKey || event.key === "Shift") parts.push("Shift");
    if (event.metaKey || event.key === "Meta") parts.push("Meta");
    return parts.length > 0 ? `${parts.join("+")}+...` : "Press shortcut";
  }

  function matches(event, shortcut) {
    const normalized = normalize(shortcut);
    return normalizedKey(event.key) === normalized.key &&
      Boolean(event.altKey) === normalized.alt &&
      Boolean(event.ctrlKey) === normalized.ctrl &&
      Boolean(event.metaKey) === normalized.meta &&
      Boolean(event.shiftKey) === normalized.shift;
  }

  function bindRecorder(button) {
    let shortcut = load();
    let armed = false;

    function render(message = "") {
      button.textContent = message || label(shortcut);
      button.title = armed
        ? "Press a key chord. Escape cancels."
        : `Send message: ${label(shortcut)}. Hover to record a new shortcut.`;
      button.setAttribute("aria-label", button.title);
    }

    function disarm() {
      armed = false;
      button.classList.remove("recording", "invalid");
      render();
    }

    button.addEventListener("pointerenter", () => {
      armed = true;
      button.classList.add("recording");
      render("Press shortcut");
    });
    button.addEventListener("pointerleave", disarm);
    window.addEventListener("keydown", (event) => {
      if (!armed) {
        return;
      }
      event.preventDefault();
      event.stopImmediatePropagation();
      if (event.key === "Escape") {
        disarm();
        return;
      }
      if (MODIFIER_KEYS.has(event.key)) {
        render(modifierLabel(event));
        return;
      }
      if (!validEventShortcut(event)) {
        button.classList.add("invalid");
        render("Add modifier");
        return;
      }
      shortcut = save(eventShortcut(event));
      armed = false;
      button.classList.remove("recording", "invalid");
      render();
    }, true);
    window.addEventListener("storage", (event) => {
      if (event.key !== STORAGE_KEY) {
        return;
      }
      shortcut = load();
      if (!armed) {
        render();
      }
    });
    render();

    return Object.freeze({
      matches: (event) => matches(event, shortcut),
      shortcut: () => ({ ...shortcut }),
    });
  }

  window.ElectroBoyInputShortcut = Object.freeze({
    DEFAULT_SHORTCUT,
    STORAGE_KEY,
    bindRecorder,
    label,
    load,
    matches,
    normalize,
    save,
  });
})();
