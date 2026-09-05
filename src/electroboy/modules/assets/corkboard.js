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

  function generationPicker() {
    let dialog = document.getElementById("corkboardGenerationPicker");
    if (dialog) return dialog;
    dialog = document.createElement("dialog");
    dialog.id = "corkboardGenerationPicker";
    dialog.className = "ad-hoc-session-dialog corkboard-picker-dialog";
    dialog.innerHTML = `
      <form method="dialog" class="ad-hoc-session-form">
        <header class="ad-hoc-session-header">
          <div><h2>Generate Corkboard</h2>
            <p class="corkboard-generation-scope"></p></div>
          <button class="ad-hoc-session-close" type="button"
                  aria-label="Close">&times;</button>
        </header>
        <fieldset class="ad-hoc-session-options">
          <legend>Analysis pass</legend>
          <div class="ad-hoc-session-list corkboard-generation-passes"></div>
        </fieldset>
        <label class="ad-hoc-session-custom">Board name <span>(optional)</span>
          <input class="ad-hoc-session-uuid corkboard-generation-title"
                 maxlength="200" autocomplete="off"
                 placeholder="Use the suggested name"></label>
        <section class="corkboard-generation-progress" hidden>
          <progress max="100" value="0"></progress>
          <p class="ad-hoc-session-details corkboard-generation-step"></p>
        </section>
        <p class="ad-hoc-session-error corkboard-generation-error" hidden></p>
        <footer class="ad-hoc-session-footer">
          <button class="corkboard-generation-cancel" type="button">Cancel</button>
          <button class="ad-hoc-session-submit corkboard-generation-submit"
                  type="submit">Generate</button>
        </footer>
      </form>`;
    document.body.append(dialog);
    return dialog;
  }

  async function generationPasses(runtime) {
    const response = await fetch(
      contextUrl(runtime, "/api/corkboard-generation/passes"),
      { cache: "no-store", headers: { Accept: "application/json" } },
    );
    const payload = await response.json().catch(() => ({
      error: "generation passes failed",
    }));
    if (!response.ok) {
      throw new Error(payload.error || "generation passes failed");
    }
    return Array.isArray(payload.passes) ? payload.passes : [];
  }

  function generationScopeLabel(scope) {
    return scope.type === "file"
      ? `Source file: ${scope.path}`
      : "Source: Entire active project";
  }

  function generationDelay(milliseconds) {
    return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
  }

  async function generationStatus(runtime, jobId) {
    const parameters = new URLSearchParams({ job_id: jobId });
    const response = await fetch(contextUrl(
      runtime,
      `/api/corkboard-generation?${parameters.toString()}`,
    ), { cache: "no-store" });
    const payload = await response.json().catch(() => ({
      error: "generation status failed",
    }));
    if (!response.ok) throw new Error(payload.error || "generation status failed");
    return payload;
  }

  async function generate(runtime, options = {}) {
    const scope = options.scope && typeof options.scope === "object"
      ? { ...options.scope }
      : { type: "project" };
    scope.type = scope.type === "file" ? "file" : "project";
    scope.path = String(scope.path || "").trim();
    if (scope.type === "file" && !scope.path) {
      throw new Error("Select a source file before generating a corkboard.");
    }
    const dialog = generationPicker();
    const form = dialog.querySelector("form");
    const passList = dialog.querySelector(".corkboard-generation-passes");
    const title = dialog.querySelector(".corkboard-generation-title");
    const progress = dialog.querySelector(".corkboard-generation-progress");
    const progressBar = progress.querySelector("progress");
    const step = dialog.querySelector(".corkboard-generation-step");
    const error = dialog.querySelector(".corkboard-generation-error");
    const close = dialog.querySelector(".ad-hoc-session-close");
    const cancel = dialog.querySelector(".corkboard-generation-cancel");
    const submit = dialog.querySelector(".corkboard-generation-submit");
    dialog.querySelector(".corkboard-generation-scope").textContent =
      generationScopeLabel(scope);
    passList.textContent = "Loading passes…";
    title.value = "";
    title.disabled = false;
    progress.hidden = true;
    error.hidden = true;
    submit.disabled = true;
    close.disabled = false;
    cancel.disabled = false;
    const passes = await generationPasses(runtime);
    if (!passes.length) throw new Error("No corkboard generation passes are available.");
    passList.replaceChildren(...passes.map((entry, index) => {
      const option = document.createElement("label");
      option.className = "ad-hoc-session-option";
      const input = document.createElement("input");
      input.type = "radio";
      input.name = "corkboard-generation-pass";
      input.value = String(entry.id || "");
      input.checked = index === 0;
      const copy = document.createElement("span");
      copy.className = "ad-hoc-session-option-copy";
      const label = document.createElement("strong");
      label.textContent = String(entry.label || entry.id || "Generation pass");
      const description = document.createElement("span");
      description.className = "ad-hoc-session-details";
      description.textContent = String(entry.description || "");
      copy.append(label, description);
      option.append(input, copy);
      return option;
    }));
    submit.disabled = false;

    return new Promise((resolve) => {
      let finished = false;
      let running = false;
      const finish = (value) => {
        if (finished) return;
        finished = true;
        if (dialog.open) dialog.close();
        resolve(value);
      };
      close.onclick = () => {
        if (!running) finish(null);
      };
      cancel.onclick = () => {
        if (!running) finish(null);
      };
      dialog.oncancel = (event) => {
        event.preventDefault();
        if (!running) finish(null);
      };
      form.onsubmit = async (event) => {
        event.preventDefault();
        if (running) return;
        const selected = passList.querySelector(
          'input[name="corkboard-generation-pass"]:checked',
        );
        if (!selected) return;
        running = true;
        close.disabled = true;
        cancel.disabled = true;
        submit.disabled = true;
        title.disabled = true;
        progress.hidden = false;
        progressBar.value = 5;
        step.textContent = "Starting non-interactive agent…";
        error.hidden = true;
        try {
          const response = await fetch(contextUrl(runtime, "/api/corkboard-generation"), {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              scope,
              pass: selected.value,
              title: title.value.trim(),
              provider: options.provider || "",
            }),
          });
          let job = await response.json().catch(() => ({
            error: "corkboard generation failed",
          }));
          if (!response.ok) throw new Error(job.error || "corkboard generation failed");
          while (job.status === "queued" || job.status === "running") {
            progressBar.value = Number(job.progress || 0);
            step.textContent = String(job.step || "Generating…");
            await generationDelay(750);
            job = await generationStatus(runtime, job.job_id);
          }
          progressBar.value = Number(job.progress || 100);
          step.textContent = String(job.step || job.status || "Complete");
          if (job.status !== "complete" || !job.result) {
            throw new Error(job.error || "corkboard generation failed");
          }
          const generated = {
            ...job.result,
            board_id: job.result.board_id || job.board_id,
            provider: job.result.provider || job.provider,
            title: job.result.title || job.title,
          };
          if (options.show !== false) {
            show(runtime, generated, { ...options, freeform: true });
          }
          window.postMessage({
            type: "electroboy-corkboard-generated",
            board: generated,
          }, window.location.origin);
          finish(generated);
        } catch (generationError) {
          running = false;
          error.textContent = generationError.message || String(generationError);
          error.hidden = false;
          close.disabled = false;
          cancel.disabled = false;
          submit.disabled = false;
          title.disabled = false;
          progress.hidden = true;
        }
      };
      dialog.showModal();
    });
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
      "corkboard-generation",
    ],
    actions: { show, openDocument, newDocument, generate },
  });
})();
