(function () {
  "use strict";

  let generationJob = null;
  let generationPollTimer = 0;
  let generationPollOptions = {};
  let generationRuntime = null;
  let generationContextId = "";
  let publishedGenerationSignature = "";
  let completedGenerationJobId = "";
  let pendingFilePicker = null;
  let filePickerSequence = 0;
  const CORKBOARD_SUFFIX = ".corkboard.json";

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

  function projectRoot(runtime) {
    const state = runtime.getState ? runtime.getState() : {};
    return String(
      state.activeProjectRoot || state.activationRoot || state.serviceRoot || ".",
    );
  }

  function corkboardSuffix(options = {}) {
    return String(options.suffix || CORKBOARD_SUFFIX);
  }

  function withCorkboardSuffix(path, options = {}) {
    const suffix = corkboardSuffix(options);
    const requested = String(path || "").trim();
    if (!requested || !suffix) {
      return requested;
    }
    return requested.toLowerCase().endsWith(suffix.toLowerCase())
      ? requested
      : `${requested}${suffix}`;
  }

  function projectRelativePath(runtime, target) {
    const requested = String(target || "").trim().replace(/\\+/g, "/");
    const root = projectRoot(runtime).replace(/\\+/g, "/").replace(/\/+$/, "");
    if (!requested || !root) {
      return requested;
    }
    if (requested === root) {
      return "";
    }
    if (requested.startsWith(`${root}/`)) {
      return requested.slice(root.length + 1);
    }
    return requested;
  }

  function boardBasename(path) {
    const normalized = String(path || "").replace(/\\+/g, "/").replace(/\/+$/, "");
    return normalized.split("/").pop() || normalized || "Corkboard";
  }

  function titleFromBoardPath(path, options = {}) {
    const suffix = corkboardSuffix(options);
    const name = boardBasename(path);
    return suffix && name.toLowerCase().endsWith(suffix.toLowerCase())
      ? name.slice(0, -suffix.length)
      : name;
  }

  function finishFilePicker(value) {
    if (!pendingFilePicker) return;
    const pending = pendingFilePicker;
    pendingFilePicker = null;
    window.clearInterval(pending.timer);
    window.removeEventListener("message", pending.listener);
    pending.resolve(value);
  }

  function chooseFile(runtime, mode, options = {}) {
    if (pendingFilePicker) {
      pendingFilePicker.popup?.focus();
      return Promise.resolve(null);
    }
    const browserMode = mode === "new" ? "file-new" : "file-open";
    const selectionChannel = `corkboard-${Date.now()}-${++filePickerSequence}`;
    const parameters = new URLSearchParams({
      path: projectRoot(runtime),
      mode: browserMode,
      selection_channel: selectionChannel,
    });
    const suffix = corkboardSuffix(options);
    if (suffix) {
      parameters.set("new_extension", suffix);
    }
    const popup = window.open(
      `/file-browser?${parameters.toString()}`,
      `electroboy-${selectionChannel}`,
      "popup=yes,width=980,height=720,menubar=no,toolbar=no,location=no,"
        + "status=no,scrollbars=yes,resizable=yes",
    );
    if (!popup) {
      return Promise.resolve(null);
    }
    return new Promise((resolve) => {
      const listener = (event) => {
        if (event.origin !== window.location.origin) return;
        const data = event.data || {};
        if (
          data.type === "electroboy-file-browser-select"
          && data.selection_channel === selectionChannel
          && event.source === popup
        ) {
          finishFilePicker(String(data.path || "").trim() || null);
        }
      };
      const timer = window.setInterval(() => {
        if (popup.closed) finishFilePicker(null);
      }, 300);
      pendingFilePicker = { listener, mode: browserMode, popup, resolve, timer };
      window.addEventListener("message", listener);
    });
  }

  async function openDocument(runtime, options = {}) {
    const target = await chooseFile(runtime, "open", options);
    if (!target) {
      return null;
    }
    const boardId = projectRelativePath(runtime, target);
    const selected = {
      board_id: boardId,
      id: boardId,
      provider: options.provider || "",
      title: titleFromBoardPath(boardId, options),
    };
    if (selected && options.show !== false) {
      show(runtime, selected, options);
    }
    return selected;
  }

  async function newDocument(runtime, options = {}) {
    const target = await chooseFile(runtime, "new", options);
    if (!target) {
      return null;
    }
    const boardId = projectRelativePath(
      runtime,
      withCorkboardSuffix(target, options),
    );
    const title = options.title || titleFromBoardPath(boardId, options);
    const response = await fetch(contextUrl(runtime, "/api/corkboards"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ board_id: boardId, title }),
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
      title: payload.title || title,
    };
    if (options.show !== false) {
      show(runtime, created, options);
    }
    return created;
  }

  function deletionPicker() {
    let dialog = document.getElementById("corkboardDeletionPicker");
    if (dialog) return dialog;
    dialog = document.createElement("dialog");
    dialog.id = "corkboardDeletionPicker";
    dialog.className = "ad-hoc-session-dialog corkboard-delete-dialog";
    dialog.innerHTML = `
      <form method="dialog" class="ad-hoc-session-form">
        <header class="ad-hoc-session-header">
          <div><h2>Delete Corkboards</h2>
            <p>Select the corkboards to move to project Trash.</p></div>
          <button class="ad-hoc-session-close" type="button"
                  aria-label="Close">&times;</button>
        </header>
        <fieldset class="ad-hoc-session-options">
          <legend>Existing corkboards</legend>
          <div class="ad-hoc-session-list corkboard-delete-list"></div>
        </fieldset>
        <p class="ad-hoc-session-error corkboard-delete-error" hidden></p>
        <footer class="ad-hoc-session-footer">
          <button class="corkboard-delete-cancel" type="button">Cancel</button>
          <button class="ad-hoc-session-submit corkboard-delete-submit"
                  type="submit" disabled>Move to Trash</button>
        </footer>
      </form>`;
    document.body.append(dialog);
    return dialog;
  }

  async function chooseBoardsToDelete(runtime) {
    const dialog = deletionPicker();
    const list = dialog.querySelector(".corkboard-delete-list");
    const error = dialog.querySelector(".corkboard-delete-error");
    const submit = dialog.querySelector(".corkboard-delete-submit");
    const available = await boards(runtime);
    error.hidden = true;
    submit.disabled = true;
    list.replaceChildren();
    if (!available.length) {
      const empty = document.createElement("span");
      empty.className = "ad-hoc-session-details";
      empty.textContent = "No corkboards yet.";
      list.append(empty);
    } else {
      list.replaceChildren(...available.map((entry, index) => {
        const option = document.createElement("label");
        option.className = "ad-hoc-session-option";
        const input = document.createElement("input");
        input.type = "checkbox";
        input.name = "corkboard-delete-document";
        input.value = String(index);
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
        return option;
      }));
    }
    list.onchange = () => {
      submit.disabled = !list.querySelector(
        'input[name="corkboard-delete-document"]:checked',
      );
    };
    return new Promise((resolve) => {
      let finished = false;
      const finish = (value) => {
        if (finished) return;
        finished = true;
        if (dialog.open) dialog.close();
        resolve(value);
      };
      dialog.querySelector(".ad-hoc-session-close").onclick = () => finish([]);
      dialog.querySelector(".corkboard-delete-cancel").onclick = () => finish([]);
      dialog.oncancel = (event) => {
        event.preventDefault();
        finish([]);
      };
      dialog.querySelector("form").onsubmit = (event) => {
        event.preventDefault();
        const selected = Array.from(list.querySelectorAll(
          'input[name="corkboard-delete-document"]:checked',
        )).map((input) => {
          const option = input.closest(".ad-hoc-session-option");
          return option ? JSON.parse(option.dataset.board) : null;
        }).filter(Boolean);
        if (selected.length) finish(selected);
      };
      dialog.showModal();
    });
  }

  async function deleteDocuments(runtime, options = {}) {
    const selected = await chooseBoardsToDelete(runtime);
    if (!selected.length) return null;
    const boardIds = selected.map((entry) => String(entry.board_id || ""));
    const response = await fetch(contextUrl(runtime, "/api/corkboards/delete"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        board_ids: boardIds,
        provider: options.provider || selected[0].provider || "",
      }),
    });
    const payload = await response.json().catch(() => ({
      error: "corkboard deletion failed",
    }));
    if (!response.ok) {
      throw new Error(payload.error || "corkboard deletion failed");
    }
    window.postMessage({
      type: "electroboy-corkboards-deleted",
      board_ids: boardIds,
      result: payload,
    }, window.location.origin);
    return payload;
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

  async function generationStatus(runtime, jobId = "") {
    const parameters = new URLSearchParams();
    if (jobId) parameters.set("job_id", jobId);
    const query = parameters.toString();
    const response = await fetch(contextUrl(
      runtime,
      `/api/corkboard-generation${query ? `?${query}` : ""}`,
    ), { cache: "no-store" });
    const payload = await response.json().catch(() => ({
      error: "generation status failed",
    }));
    if (!response.ok) throw new Error(payload.error || "generation status failed");
    return payload;
  }

  function generationTask(job = generationJob) {
    if (!job || !job.job_id) return null;
    return {
      id: String(job.job_id),
      label: String(job.title || "Corkboard generation"),
      detail: String(job.step || job.status || "Generating…"),
      progress: Math.max(0, Math.min(100, Number(job.progress || 0))),
      status: String(job.status || "queued"),
    };
  }

  function publishGenerationJob(runtime, job, force = false) {
    if (!job || !job.job_id) return;
    generationJob = job;
    const signature = [job.job_id, job.status, job.progress, job.updated_at].join(":");
    if (!force && signature === publishedGenerationSignature) return;
    publishedGenerationSignature = signature;
    runtime.modules.invoke("progress", "renderBackgroundTask", job);
    window.dispatchEvent(new CustomEvent(
      "electroboy-corkboard-generation-progress",
      { detail: job },
    ));
    runtime.ui.refreshStageActionPanel();
  }

  function finishGeneratedBoard(runtime, job, options = {}) {
    if (
      job.status !== "complete" ||
      !job.result ||
      completedGenerationJobId === String(job.job_id)
    ) {
      return;
    }
    completedGenerationJobId = String(job.job_id);
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
  }

  function stopGenerationMonitor() {
    if (generationPollTimer) {
      window.clearTimeout(generationPollTimer);
      generationPollTimer = 0;
    }
  }

  async function pollGeneration() {
    generationPollTimer = 0;
    if (!generationRuntime || !generationJob?.job_id) return;
    const contextId = generationContextId;
    const jobId = String(generationJob.job_id);
    try {
      const job = await generationStatus(generationRuntime, jobId);
      if (
        generationContextId !== contextId ||
        String(generationJob?.job_id || "") !== jobId
      ) {
        return;
      }
      publishGenerationJob(generationRuntime, job);
      if (job.status === "queued" || job.status === "running") {
        generationPollTimer = window.setTimeout(pollGeneration, 1000);
        return;
      }
      finishGeneratedBoard(generationRuntime, job, generationPollOptions);
      if (job.status === "failed") {
        generationRuntime.notifications.appendOutput(
          `${job.error || "corkboard generation failed"}\n`,
          "error",
        );
      }
    } catch (error) {
      if (
        generationContextId !== contextId ||
        String(generationJob?.job_id || "") !== jobId
      ) {
        return;
      }
      generationRuntime.notifications.appendOutput(
        `corkboard generation status failed: ${error.message || error}\n`,
        "error",
      );
      generationPollTimer = window.setTimeout(pollGeneration, 3000);
    }
  }

  function monitorGeneration(runtime, job, options = {}) {
    stopGenerationMonitor();
    generationRuntime = runtime;
    generationContextId = String(runtime.getState().contextId || "");
    generationPollOptions = { ...options };
    publishGenerationJob(runtime, job, true);
    if (job.status === "queued" || job.status === "running") {
      generationPollTimer = window.setTimeout(pollGeneration, 750);
    } else {
      finishGeneratedBoard(runtime, job, options);
    }
  }

  async function syncGeneration(runtime) {
    const contextId = String(runtime.getState().contextId || "");
    if (!contextId) return null;
    if (generationContextId && generationContextId !== contextId) {
      const previousJobId = generationJob?.job_id || "";
      stopGenerationMonitor();
      generationJob = null;
      publishedGenerationSignature = "";
      completedGenerationJobId = "";
      runtime.modules.invoke("progress", "clearBackgroundTask", previousJobId);
      window.dispatchEvent(new CustomEvent(
        "electroboy-corkboard-generation-progress",
        { detail: null },
      ));
      runtime.ui.refreshStageActionPanel();
    }
    generationContextId = contextId;
    const latest = await generationStatus(runtime).catch(() => null);
    if (String(runtime.getState().contextId || "") !== contextId) return null;
    if (!latest || !latest.job_id) {
      generationJob = null;
      publishedGenerationSignature = "";
      runtime.ui.refreshStageActionPanel();
      return null;
    }
    if (
      generationJob?.job_id === latest.job_id &&
      (latest.status === "queued" || latest.status === "running")
    ) {
      publishGenerationJob(runtime, latest);
      return latest;
    }
    monitorGeneration(runtime, latest, { show: false });
    return latest;
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
    const error = dialog.querySelector(".corkboard-generation-error");
    const close = dialog.querySelector(".ad-hoc-session-close");
    const cancel = dialog.querySelector(".corkboard-generation-cancel");
    const submit = dialog.querySelector(".corkboard-generation-submit");
    dialog.querySelector(".corkboard-generation-scope").textContent =
      generationScopeLabel(scope);
    passList.textContent = "Loading passes…";
    title.value = "";
    title.disabled = false;
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
          const job = await response.json().catch(() => ({
            error: "corkboard generation failed",
          }));
          if (!response.ok) throw new Error(job.error || "corkboard generation failed");
          finish(job);
          monitorGeneration(runtime, job, options);
        } catch (generationError) {
          running = false;
          error.textContent = generationError.message || String(generationError);
          error.hidden = false;
          close.disabled = false;
          cancel.disabled = false;
          submit.disabled = false;
          title.disabled = false;
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
      "corkboard-board-deletion",
    ],
    actions: {
      show,
      openDocument,
      newDocument,
      deleteDocuments,
      generate,
      generationJob: () => generationJob,
      generationTask: (_runtime, job = generationJob) => generationTask(job),
      syncGeneration,
    },
    mount(runtime) {
      generationRuntime = runtime;
    },
  });
})();
