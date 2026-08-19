(function () {
  "use strict";

  function showMessage(runtime, message) {
    const tree = runtime.elements.creativeTree;
    tree.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "creative-binder-status";
    empty.textContent = message;
    tree.append(empty);
  }

  function renderTree(runtime) {
    const tree = runtime.elements.creativeTree;
    const state = runtime.getState();
    tree.replaceChildren();
    const entries = state.creativeTreePayload &&
      Array.isArray(state.creativeTreePayload.entries)
      ? state.creativeTreePayload.entries
      : [];
    if (entries.length === 0) {
      showMessage(runtime, "No writing documents yet.");
      return;
    }
    for (const entry of entries) {
      appendEntry(runtime, entry, 0);
    }
  }

  function iconSvg(name) {
    const icons = {
      file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><path d="M14 2v6h6"></path>',
      folder: '<path d="M3 7h7l2 2h9v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>',
      "folder-open": '<path d="M3 7h7l2 2h9l-2 9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><path d="M3 7v11"></path>',
      markdown: '<rect x="3" y="5" width="18" height="14" rx="2"></rect><path d="M7 15V9l3 3 3-3v6"></path><path d="M17 9v6"></path><path d="M15 13l2 2 2-2"></path>',
      corkboard: '<rect x="4" y="4" width="16" height="16" rx="2"></rect><path d="M8 8h5v4H8z"></path><path d="M14 12h4v5h-4z"></path><path d="M8 14h4v3H8z"></path>',
    };
    return `<svg viewBox="0 0 24 24" fill="none" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[name] || icons.file}</svg>`;
  }

  function iconName(entry, expanded) {
    if ((entry.type || "") === "directory") {
      return expanded ? "folder-open" : "folder";
    }
    if (entry.corkboard) {
      return "corkboard";
    }
    return entry.markdown ? "markdown" : "file";
  }

  function iconClass(entry) {
    if ((entry.type || "") === "directory") {
      return "folder";
    }
    if (entry.corkboard) {
      return "corkboard";
    }
    return entry.markdown ? "markdown" : "file";
  }

  function actionIconSvg(name) {
    const icons = {
      rename: '<path d="m12 20h9"></path><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"></path>',
      trash: '<path d="M3 6h18"></path><path d="M8 6V4h8v2"></path><path d="m19 6-1 14H6L5 6"></path><path d="M10 11v5"></path><path d="M14 11v5"></path>',
    };
    return `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[name] || ""}</svg>`;
  }

  function appendEntry(runtime, entry, depth) {
    const state = runtime.getState();
    const action = creativeActions(runtime);
    const tree = runtime.elements.creativeTree;
    const type = entry.type || "file";
    const entryActionType = entry.corkboard ? "corkboard" : type;
    const path = String(entry.path || "");
    const isDirectory = type === "directory";
    const expanded = isDirectory && state.expandedCreativeFolders.has(path);
    const row = document.createElement("div");
    row.className = `creative-tree-row ${type}`;
    row.classList.toggle("expanded", expanded);
    row.style.setProperty("--creative-depth-indent", `${depth * 16}px`);
    row.title = path;
    row.tabIndex = 0;
    row.classList.toggle(
      "active",
      (isDirectory && path === state.creativeActiveFolder) ||
        (!isDirectory && path === state.creativeActiveDocument),
    );
    row.setAttribute("role", "treeitem");
    if (isDirectory) {
      row.setAttribute("aria-expanded", expanded ? "true" : "false");
    }

    const icon = document.createElement("span");
    icon.className = `creative-tree-icon ${iconClass(entry)}`;
    icon.innerHTML = iconSvg(iconName(entry, expanded));
    const name = state.creativeEditingPath === path
      ? renameInput(runtime, entry, type, path)
      : treeName(entry, path);
    const rename = iconButton(
      "rename",
      `Rename ${path}`,
      () => action.beginCreativeRename(path, entryActionType),
    );
    const remove = iconButton(
      "trash",
      `Delete ${path}`,
      () => action.deleteCreativeEntry(path, entryActionType),
      "danger",
    );

    if (isDirectory) {
      const disclosure = document.createElement("span");
      disclosure.className = "creative-tree-disclosure";
      disclosure.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        toggleFolder(runtime, path);
      });
      row.append(icon, name, rename, remove, disclosure);
    } else {
      row.append(icon, name, rename, remove);
    }
    row.addEventListener("click", () => activateEntry(runtime, entry, path, type));
    row.addEventListener("dblclick", (event) => {
      event.preventDefault();
      action.beginCreativeRename(path, entryActionType);
    });
    row.addEventListener("keydown", (event) => {
      if (event.target !== row) {
        return;
      }
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        activateEntry(runtime, entry, path, type);
      } else if (event.key === "F2") {
        event.preventDefault();
        action.beginCreativeRename(path, entryActionType);
      } else if (event.key === "Delete") {
        event.preventDefault();
        action.deleteCreativeEntry(path, entryActionType);
      }
    });
    tree.append(row);

    if (isDirectory && expanded) {
      for (const child of entry.children || []) {
        appendEntry(runtime, child, depth + 1);
      }
      appendFolderActions(runtime, path, depth + 1);
    }
  }

  function treeName(entry, path) {
    const name = document.createElement("span");
    name.className = "creative-tree-name";
    name.textContent = String(
      (entry.corkboard && entry.title) || entry.name || path || "Untitled",
    );
    return name;
  }

  function iconButton(iconName, title, handler, extraClass = "") {
    const button = document.createElement("button");
    button.className = `creative-tree-icon-button ${extraClass}`.trim();
    button.type = "button";
    button.title = title;
    button.setAttribute("aria-label", title);
    button.innerHTML = actionIconSvg(iconName);
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      handler();
    });
    button.addEventListener("dblclick", (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
    return button;
  }

  function activateEntry(runtime, entry, path, type) {
    const action = creativeActions(runtime);
    if (type === "directory") {
      action.selectCreativeFolder(path);
    } else if (entry.corkboard) {
      action.selectCreativeCorkboard(path);
    } else if (entry.markdown) {
      action.selectCreativeDocument(path);
    } else {
      action.appendOutput(
        `${path} is visible in the Binder but is not editable yet.\n`,
        "system",
      );
    }
  }

  function renameInput(runtime, entry, type, path) {
    const action = creativeActions(runtime);
    const input = document.createElement("input");
    input.className = "creative-tree-name-input";
    input.type = "text";
    input.value = String(
      (entry.corkboard && entry.title) || entry.name || basename(path),
    );
    input.setAttribute("aria-label", `Rename ${path}`);
    input.addEventListener("click", (event) => event.stopPropagation());
    input.addEventListener("dblclick", (event) => event.stopPropagation());
    input.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        action.finishCreativeRename(path, type, input.value);
      } else if (event.key === "Escape") {
        event.preventDefault();
        action.cancelCreativeRename();
      }
    });
    input.addEventListener("blur", () => {
      action.finishCreativeRename(path, type, input.value);
    });
    window.requestAnimationFrame(() => {
      input.focus();
      input.select();
    });
    return input;
  }

  function appendFolderActions(runtime, path, depth) {
    const action = creativeActions(runtime);
    const actions = document.createElement("div");
    actions.className = "creative-tree-actions";
    actions.style.setProperty("--creative-depth-indent", `${depth * 16}px`);
    const entries = [
      ["New folder", action.createCreativeFolder],
      ["New file", action.createCreativeDocument],
      ["New board", action.createCreativeCorkboard],
    ];
    for (const [label, handler] of entries) {
      const button = document.createElement("button");
      button.className = "creative-tree-action";
      button.type = "button";
      button.textContent = label;
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        runtime.updateState({ creativeActiveFolder: path });
        renderTree(runtime);
        handler(path);
      });
      actions.append(button);
    }
    runtime.elements.creativeTree.append(actions);
  }

  function toggleFolder(runtime, path) {
    if (!path) {
      return;
    }
    const folders = runtime.getState().expandedCreativeFolders;
    if (folders.has(path)) {
      folders.delete(path);
    } else {
      folders.add(path);
    }
    renderTree(runtime);
  }

  function basename(path) {
    const parts = String(path || "").split("/").filter(Boolean);
    return parts.length ? parts[parts.length - 1] : "";
  }

  function creativeActions(runtime) {
    const invoke = (action, ...args) =>
      window.ElectroBoyFrontend.invokeWorkflow(
        "creative-writing",
        action,
        ...args,
      );
    return {
      appendOutput: runtime.notifications.appendOutput,
      beginCreativeRename: (...args) => invoke("beginCreativeRename", ...args),
      cancelCreativeRename: (...args) => invoke("cancelCreativeRename", ...args),
      createCreativeCorkboard: (...args) => invoke("createCreativeCorkboardInline", ...args),
      createCreativeDocument: (...args) => invoke("createCreativeDocumentInline", ...args),
      createCreativeFolder: (...args) => invoke("createCreativeFolderInline", ...args),
      deleteCreativeEntry: (...args) => invoke("deleteCreativeEntry", ...args),
      finishCreativeRename: (...args) => invoke("finishCreativeRename", ...args),
      selectCreativeCorkboard: (...args) => invoke("selectCreativeCorkboard", ...args),
      selectCreativeDocument: (...args) => invoke("selectCreativeDocument", ...args),
      selectCreativeFolder: (...args) => invoke("selectCreativeFolder", ...args),
    };
  }

  window.ElectroBoyFrontend.registerModule({
    id: "binder",
    label: "Binder",
    capabilities: ["tree", "navigation", "entry-actions"],
    actions: {
      renderTree,
      showMessage,
    },
  });
})();
