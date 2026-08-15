(function () {
  "use strict";

  const existing = window.ElectroBoyFrontend || {};
  const workflows = Array.isArray(existing.workflows) ? existing.workflows : [];
  const modules = Array.isArray(existing.modules) ? existing.modules : [];

  function upsert(collection, item) {
    const index = collection.findIndex((entry) => entry.id === item.id);
    if (index >= 0) {
      collection[index] = item;
      return;
    }
    collection.push(item);
  }

  window.ElectroBoyFrontend = {
    workflows,
    modules,
    registerWorkflow(workflow) {
      if (!workflow || !workflow.id || !workflow.label || !workflow.mode) {
        throw new Error("workflow registration requires id, label, and mode");
      }
      upsert(workflows, { ...workflow });
    },
    registerModule(module) {
      if (!module || !module.id || !module.label) {
        throw new Error("module registration requires id and label");
      }
      upsert(modules, { ...module });
    },
    listWorkflows() {
      return [...workflows].sort((left, right) => {
        const leftOrder = Number.isFinite(left.order) ? left.order : 1000;
        const rightOrder = Number.isFinite(right.order) ? right.order : 1000;
        if (leftOrder !== rightOrder) {
          return leftOrder - rightOrder;
        }
        return left.label.localeCompare(right.label);
      });
    },
  };
})();

