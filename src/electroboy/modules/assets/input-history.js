(function () {
  "use strict";

  const STORAGE_KEY = "electroboy.agentInputHistory.v1";
  const MAX_ENTRIES = 2000;
  let controllerSequence = 0;
  let memoryEntries = [];

  function normalizedEntries(value) {
    const entries = Array.isArray(value)
      ? value
      : value && Array.isArray(value.entries)
        ? value.entries
        : [];
    return entries
      .filter((entry) => typeof entry === "string" && entry.trim())
      .slice(-MAX_ENTRIES);
  }

  function loadEntries() {
    try {
      const stored = window.localStorage.getItem(STORAGE_KEY);
      if (!stored) {
        return memoryEntries.slice();
      }
      memoryEntries = normalizedEntries(JSON.parse(stored));
    } catch (error) {
      return memoryEntries.slice();
    }
    return memoryEntries.slice();
  }

  function quotaExceeded(error) {
    return error && (
      error.name === "QuotaExceededError" ||
      error.name === "NS_ERROR_DOM_QUOTA_REACHED" ||
      error.code === 22 ||
      error.code === 1014
    );
  }

  function saveEntries(entries) {
    const retained = normalizedEntries(entries);
    while (true) {
      memoryEntries = retained.slice();
      try {
        window.localStorage.setItem(
          STORAGE_KEY,
          JSON.stringify({ version: 1, entries: retained }),
        );
        return retained.slice();
      } catch (error) {
        if (!quotaExceeded(error) || retained.length === 0) {
          return retained.slice();
        }
        const trimCount = Math.max(1, Math.ceil(retained.length * 0.05));
        retained.splice(0, trimCount);
      }
    }
  }

  function appendEntry(value) {
    if (typeof value !== "string" || !value.trim()) {
      return loadEntries();
    }
    const entries = loadEntries();
    entries.push(value);
    return saveEntries(entries.slice(-MAX_ENTRIES));
  }

  function element(tagName, className = "", text = "") {
    const node = document.createElement(tagName);
    if (className) {
      node.className = className;
    }
    if (text) {
      node.textContent = text;
    }
    return node;
  }

  function create(options = {}) {
    const input = options.input;
    const button = options.button;
    if (!input || !button) {
      throw new Error("input history requires an input and a button");
    }

    controllerSequence += 1;
    const dialogId = `electroboyInputHistory${controllerSequence}`;
    const titleId = `${dialogId}Title`;
    const overlay = element("div", "input-history-overlay");
    overlay.id = dialogId;
    overlay.hidden = true;
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-labelledby", titleId);

    const card = element("section", "input-history-card");
    const header = element("header", "input-history-header");
    const headingGroup = element("div", "input-history-heading");
    const title = element("h1", "", "Input history");
    title.id = titleId;
    const summary = element(
      "p",
      "",
      `Most recent first · up to ${MAX_ENTRIES.toLocaleString()} saved inputs`,
    );
    const closeButton = element("button", "input-history-close", "×");
    closeButton.type = "button";
    closeButton.title = "Close input history";
    closeButton.setAttribute("aria-label", "Close input history");
    const count = element("div", "input-history-count");
    const list = element("div", "input-history-list");
    list.setAttribute("role", "list");
    const empty = element(
      "p",
      "input-history-empty",
      "No submitted agent inputs have been saved yet.",
    );

    headingGroup.append(title, summary);
    header.append(headingGroup, closeButton);
    card.append(header, count, list, empty);
    overlay.append(card);
    document.body.append(overlay);

    button.setAttribute("aria-haspopup", "dialog");
    button.setAttribute("aria-controls", dialogId);
    button.setAttribute("aria-expanded", "false");

    let previousFocus = null;

    function restoreEntry(value) {
      input.value = value;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      close({ restoreFocus: false });
      input.focus();
      if (typeof input.setSelectionRange === "function") {
        input.setSelectionRange(value.length, value.length);
      }
    }

    function render() {
      const entries = loadEntries();
      list.replaceChildren();
      const newestFirst = entries.slice().reverse();
      for (const value of newestFirst) {
        const entry = element("button", "input-history-entry", value);
        entry.type = "button";
        entry.setAttribute("role", "listitem");
        entry.title = "Restore this input";
        entry.addEventListener("click", () => restoreEntry(value));
        list.append(entry);
      }
      const total = entries.length;
      count.textContent = `${total.toLocaleString()} saved input${total === 1 ? "" : "s"}`;
      empty.hidden = total !== 0;
      list.hidden = total === 0;
      return newestFirst;
    }

    function open() {
      previousFocus = document.activeElement;
      const entries = render();
      overlay.hidden = false;
      button.setAttribute("aria-expanded", "true");
      const firstEntry = list.querySelector(".input-history-entry");
      (firstEntry || closeButton).focus();
      return entries;
    }

    function close(closeOptions = {}) {
      if (overlay.hidden) {
        return;
      }
      overlay.hidden = true;
      button.setAttribute("aria-expanded", "false");
      if (
        closeOptions.restoreFocus !== false &&
        previousFocus &&
        typeof previousFocus.focus === "function"
      ) {
        previousFocus.focus();
      }
      previousFocus = null;
    }

    function focusableElements() {
      return Array.from(
        overlay.querySelectorAll("button:not([disabled]), [tabindex]:not([tabindex='-1'])"),
      ).filter((candidate) => !candidate.hidden);
    }

    function handleKeydown(event) {
      if (overlay.hidden) {
        return;
      }
      if (event.key === "Escape") {
        event.preventDefault();
        event.stopImmediatePropagation();
        close();
        return;
      }
      if (event.key !== "Tab") {
        return;
      }
      const focusable = focusableElements();
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    button.addEventListener("click", open);
    closeButton.addEventListener("click", () => close());
    overlay.addEventListener("click", (event) => {
      if (event.target === overlay) {
        close();
      }
    });
    window.addEventListener("keydown", handleKeydown, true);
    window.addEventListener("storage", (event) => {
      if (event.key === STORAGE_KEY && !overlay.hidden) {
        render();
      }
    });

    return Object.freeze({
      close,
      open,
      record(value) {
        const entries = appendEntry(value);
        if (!overlay.hidden) {
          render();
        }
        return entries.length;
      },
      size: () => loadEntries().length,
    });
  }

  window.ElectroBoyInputHistory = Object.freeze({
    MAX_ENTRIES,
    STORAGE_KEY,
    appendEntry,
    create,
    loadEntries,
  });
})();
