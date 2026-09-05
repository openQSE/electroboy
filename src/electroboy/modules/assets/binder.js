(function () {
  "use strict";

  let folderColorPicker = null;
  let folderColorPickerAnchor = null;
  let folderColorPickerDocumentHandler = null;

  function showMessage(runtime, message) {
    const tree = runtime.elements.creativeTree;
    tree.replaceChildren();
    const empty = document.createElement("div");
    empty.className = "creative-binder-status";
    empty.textContent = message;
    tree.append(empty);
  }

  function folderEntryVisible(entry) {
    return !entry.corkboard && String(entry.path || "") !== "corkboard";
  }

  function renderTree(runtime) {
    const tree = runtime.elements.creativeTree;
    const state = runtime.getState();
    closeFolderColorPicker();
    tree.replaceChildren();
    const entries = state.creativeTreePayload &&
      Array.isArray(state.creativeTreePayload.entries)
      ? state.creativeTreePayload.entries
      : [];
    const folderEntries = entries.filter(folderEntryVisible);
    if (folderEntries.length === 0) {
      showMessage(runtime, "No writing documents yet.");
      return;
    }
    for (const entry of folderEntries) {
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
    if (isDirectory) {
      applyFolderColor(runtime, row, entry);
    }
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
      ? renameInput(runtime, entry, entryActionType, path)
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
      const color = folderColorButton(runtime, entry, path);
      const disclosure = document.createElement("span");
      disclosure.className = "creative-tree-disclosure";
      disclosure.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        toggleFolder(runtime, path);
      });
      row.append(icon, name, color, rename, remove, disclosure);
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
      for (const child of (entry.children || []).filter(folderEntryVisible)) {
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

  function folderPalette(runtime) {
    const payload = runtime.getState().creativeTreePayload;
    return payload && Array.isArray(payload.folder_palette)
      ? payload.folder_palette
      : [];
  }

  function folderPaletteEntry(runtime, colorId) {
    const palette = folderPalette(runtime);
    return palette.find((entry) => entry.id === colorId) || palette[0] || {
      id: "navy",
      label: "Navy",
      value: "#1f3f5f",
      border: "#18324d",
    };
  }

  function applyFolderColor(runtime, row, entry) {
    const color = folderPaletteEntry(runtime, entry.folder_color);
    row.style.setProperty("--creative-folder-color", color.value);
    row.style.setProperty("--creative-folder-border", color.border);
  }

  function folderColorButton(runtime, entry, path) {
    const color = folderPaletteEntry(runtime, entry.folder_color);
    const button = document.createElement("button");
    button.className = "creative-folder-color-button";
    button.type = "button";
    button.title = `Change ${path} color`;
    button.setAttribute("aria-label", `Change ${path} color`);
    button.setAttribute("aria-haspopup", "listbox");
    button.setAttribute("aria-expanded", "false");
    button.style.setProperty("--creative-folder-swatch", color.value);
    button.addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      showFolderColorPicker(runtime, path, entry.folder_color, button);
    });
    button.addEventListener("dblclick", (event) => {
      event.preventDefault();
      event.stopPropagation();
    });
    return button;
  }

  function closeFolderColorPicker() {
    if (folderColorPickerDocumentHandler) {
      document.removeEventListener("pointerdown", folderColorPickerDocumentHandler);
      folderColorPickerDocumentHandler = null;
    }
    if (folderColorPickerAnchor) {
      folderColorPickerAnchor.setAttribute("aria-expanded", "false");
      folderColorPickerAnchor = null;
    }
    if (folderColorPicker) {
      folderColorPicker.remove();
      folderColorPicker = null;
    }
  }

  function positionFolderColorPicker(picker, anchor) {
    const anchorBox = anchor.getBoundingClientRect();
    const pickerBox = picker.getBoundingClientRect();
    const left = Math.max(
      8,
      Math.min(anchorBox.left, window.innerWidth - pickerBox.width - 8),
    );
    const below = anchorBox.bottom + 6;
    const top = below + pickerBox.height <= window.innerHeight - 8
      ? below
      : Math.max(8, anchorBox.top - pickerBox.height - 6);
    picker.style.left = `${left}px`;
    picker.style.top = `${top}px`;
  }

  function showFolderColorPicker(runtime, path, selectedColor, anchor) {
    closeFolderColorPicker();
    const picker = document.createElement("div");
    picker.className = "creative-folder-color-picker";
    picker.setAttribute("role", "listbox");
    picker.setAttribute("aria-label", `Folder color for ${path}`);
    const action = creativeActions(runtime);
    for (const color of folderPalette(runtime)) {
      const option = document.createElement("button");
      option.className = "creative-folder-color-option";
      option.type = "button";
      option.title = color.label;
      option.setAttribute("role", "option");
      option.setAttribute("aria-label", color.label);
      option.setAttribute("aria-selected", String(color.id === selectedColor));
      option.style.setProperty("--creative-folder-swatch", color.value);
      option.addEventListener("click", (event) => {
        event.preventDefault();
        event.stopPropagation();
        closeFolderColorPicker();
        action.setCreativeFolderColor(path, color.id);
      });
      picker.append(option);
    }
    picker.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        closeFolderColorPicker();
        anchor.focus();
      }
    });
    document.body.append(picker);
    folderColorPicker = picker;
    folderColorPickerAnchor = anchor;
    anchor.setAttribute("aria-expanded", "true");
    positionFolderColorPicker(picker, anchor);
    const selected = picker.querySelector('[aria-selected="true"]');
    (selected || picker.firstElementChild)?.focus();
    window.setTimeout(() => {
      if (folderColorPicker !== picker) {
        return;
      }
      folderColorPickerDocumentHandler = (event) => {
        if (!picker.contains(event.target) && event.target !== anchor) {
          closeFolderColorPicker();
        }
      };
      document.addEventListener("pointerdown", folderColorPickerDocumentHandler);
    }, 0);
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

  function renameInput(runtime, entry, actionType, path) {
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
        action.finishCreativeRename(path, actionType, input.value);
      } else if (event.key === "Escape") {
        event.preventDefault();
        action.cancelCreativeRename();
      }
    });
    input.addEventListener("blur", () => {
      action.finishCreativeRename(path, actionType, input.value);
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
      createCreativeDocument: (...args) => invoke("createCreativeDocumentInline", ...args),
      createCreativeFolder: (...args) => invoke("createCreativeFolderInline", ...args),
      deleteCreativeEntry: (...args) => invoke("deleteCreativeEntry", ...args),
      finishCreativeRename: (...args) => invoke("finishCreativeRename", ...args),
      setCreativeFolderColor: (...args) => invoke("setCreativeFolderColor", ...args),
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
