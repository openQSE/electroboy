(function () {
  "use strict";

  function contextUrl(runtime, path) {
    return runtime.http.contextUrl(path);
  }

  function show(runtime, source, options = {}) {
    const descriptor = typeof source === "string"
      ? {
          id: source,
          provider: options.provider || "creative-files",
          title: options.title || "",
        }
      : { ...(source || {}) };
    const boardId = String(descriptor.id || descriptor.board_id || "").trim();
    if (!boardId) {
      return;
    }
    const provider = String(descriptor.provider || options.provider || "").trim();
    const freeform = Boolean(options.freeform || descriptor.freeform) ||
      /\.corkboard\.json$/i.test(boardId);
    const label = String(descriptor.title || options.title || "").trim() || (freeform
      ? runtime.paths.basename(boardId).replace(/\.corkboard\.json$/i, "")
      : runtime.paths.basename(boardId));
    const board = {
      id: boardId,
      label,
      provider,
    };
    const item = {
      id: `corkboard-${provider || "active"}-${boardId}`,
      kind: "corkboard",
      title: `${freeform ? "Corkboard" : "Folder board"}: ${label}`,
      editing: false,
      board,
    };
    runtime.modules.invoke(
      "documents",
      "showArtifactPreviews",
      [item],
      { manual: true, stage: options.stage || runtime.getState().workflowMode },
    );
  }

  async function boards(runtime) {
    const response = await fetch(contextUrl(runtime, "/api/corkboards"), {
      cache: "no-store",
      headers: { Accept: "application/json" },
    });
    const payload = await response.json().catch(() => ({
      error: "corkboard list failed",
    }));
    if (!response.ok) {
      throw new Error(payload.error || "corkboard list failed");
    }
    return Array.isArray(payload.boards) ? payload.boards : [];
  }

  function picker() {
    let dialog = document.getElementById("corkboardDocumentPicker");
    if (dialog) {
      return dialog;
    }
    dialog = document.createElement("dialog");
    dialog.id = "corkboardDocumentPicker";
    dialog.className = "ad-hoc-session-dialog corkboard-picker-dialog";
    dialog.innerHTML = `
      <form method="dialog" class="ad-hoc-session-form">
        <header class="ad-hoc-session-header">
          <div><h2 class="corkboard-picker-title">Corkboard</h2>
            <p class="corkboard-picker-description"></p></div>
          <button class="ad-hoc-session-close" type="button"
                  aria-label="Close">&times;</button>
        </header>
        <fieldset class="ad-hoc-session-options corkboard-picker-existing">
          <legend>Corkboards</legend>
          <div class="ad-hoc-session-list corkboard-picker-list"></div>
        </fieldset>
        <label class="ad-hoc-session-custom corkboard-picker-new">Name
          <input class="ad-hoc-session-uuid corkboard-picker-name"
                 maxlength="200" autocomplete="off"></label>
        <p class="ad-hoc-session-error corkboard-picker-error" hidden></p>
        <footer class="ad-hoc-session-footer">
          <button class="corkboard-picker-cancel" type="button">Cancel</button>
          <button class="ad-hoc-session-submit corkboard-picker-submit"
                  type="submit">Open</button>
        </footer>
      </form>`;
    document.body.append(dialog);
    return dialog;
  }

  async function choose(runtime, mode) {
    const dialog = picker();
    const creating = mode === "new";
    const existing = dialog.querySelector(".corkboard-picker-existing");
    const list = dialog.querySelector(".corkboard-picker-list");
    const nameLabel = dialog.querySelector(".corkboard-picker-new");
    const name = dialog.querySelector(".corkboard-picker-name");
    const error = dialog.querySelector(".corkboard-picker-error");
    const submit = dialog.querySelector(".corkboard-picker-submit");
    dialog.querySelector(".corkboard-picker-title").textContent = creating
      ? "New Corkboard"
      : "Open Corkboard";
    dialog.querySelector(".corkboard-picker-description").textContent = creating
      ? "Create a project corkboard."
      : "Choose a project corkboard.";
    existing.hidden = creating;
    nameLabel.hidden = !creating;
    error.hidden = true;
    name.value = "";
    list.replaceChildren();
    submit.disabled = false;
    submit.textContent = creating ? "Create" : "Open";
    const available = creating ? [] : await boards(runtime);
    if (!creating && available.length === 0) {
      list.textContent = "No corkboards yet.";
      submit.disabled = true;
    }
    available.forEach((entry, index) => {
      const option = document.createElement("label");
      option.className = "ad-hoc-session-option";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "corkboard-document";
      input.value = String(index);
      input.checked = index === 0;
      const copy = document.createElement("span");
      copy.className = "ad-hoc-session-option-copy";
      const title = document.createElement("strong");
      title.textContent = String(entry.title || entry.board_id || "Corkboard");
      const details = document.createElement("span");
      details.className = "ad-hoc-session-details";
      details.textContent = String(entry.board_id || "");
      copy.append(title, details);
      option.append(input, copy);
      option.dataset.board = JSON.stringify(entry);
      list.append(option);
    });
    return new Promise((resolve) => {
      let finished = false;
      const finish = (value) => {
        if (finished) {
          return;
        }
        finished = true;
        dialog.close();
        resolve(value);
      };
      dialog.querySelector(".ad-hoc-session-close").onclick = () => finish(null);
      dialog.querySelector(".corkboard-picker-cancel").onclick = () => finish(null);
      dialog.oncancel = (event) => {
        event.preventDefault();
        finish(null);
      };
      dialog.querySelector("form").onsubmit = (event) => {
        event.preventDefault();
        if (creating) {
          const title = name.value.trim();
          if (!title) {
            error.textContent = "Enter a name.";
            error.hidden = false;
            name.focus();
            return;
          }
          finish({ title });
          return;
        }
        const selected = list.querySelector(
          'input[name="corkboard-document"]:checked',
        );
        const option = selected
          ? selected.closest(".ad-hoc-session-option")
          : null;
        finish(option ? JSON.parse(option.dataset.board) : null);
      };
      dialog.showModal();
      if (creating) {
        name.focus();
      }
    });
  }

  function newBoardId(title, existing, options = {}) {
    const suffix = String(options.suffix || "");
    if (!suffix) {
      return title;
    }
    const directory = String(options.directory || "")
      .trim()
      .replace(/^\/+|\/+$/g, "");
    const stem = String(title || "")
      .trim()
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "") || "board";
    const prefix = directory ? `${directory}/` : "";
    const used = new Set(existing.map((entry) => String(entry.board_id || "")));
    let candidate = `${prefix}${stem}${suffix}`;
    let index = 2;
    while (used.has(candidate)) {
      candidate = `${prefix}${stem}-${index}${suffix}`;
      index += 1;
    }
    return candidate;
  }

  async function openDocument(runtime, options = {}) {
    const selected = await choose(runtime, "open");
    if (selected && options.show !== false) {
      show(runtime, selected, options);
    }
    return selected;
  }

  async function newDocument(runtime, options = {}) {
    const choice = await choose(runtime, "new");
    if (!choice) {
      return null;
    }
    const existing = await boards(runtime);
    const boardId = newBoardId(choice.title, existing, options);
    const response = await fetch(contextUrl(runtime, "/api/corkboards"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ board_id: boardId, title: choice.title }),
    });
    const payload = await response.json().catch(() => ({
      error: "corkboard creation failed",
    }));
    if (!response.ok) {
      throw new Error(payload.error || "corkboard creation failed");
    }
    const created = {
      ...payload,
      board_id: payload.board_id || payload.path || boardId,
      title: payload.title || choice.title,
    };
    if (options.show !== false) {
      show(runtime, created, options);
    }
    return created;
  }

  window.ElectroBoyFrontend.registerModule({
    id: "corkboard",
    label: "Corkboard",
    capabilities: [
      "corkboard-provider",
      "folder-corkboard",
      "freeform-corkboard",
      "selectable-corkboard-layout",
      "corkboard-auto-organize",
      "corkboard-board-selector",
    ],
    actions: { show, openDocument, newDocument },
  });
})();
