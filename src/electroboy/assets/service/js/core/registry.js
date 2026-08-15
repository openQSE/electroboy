(function () {
  "use strict";

  const existing = window.ElectroBoyFrontend || {};
  const workflows = Array.isArray(existing.workflows) ? existing.workflows : [];
  const modules = Array.isArray(existing.modules) ? existing.modules : [];
  let runtime = existing.runtime || null;
  const mounted = new Set();

  function upsert(collection, item) {
    const index = collection.findIndex((entry) => entry.id === item.id);
    if (index >= 0) {
      collection[index] = item;
      return;
    }
    collection.push(item);
  }

  function mountContribution(kind, contribution) {
    if (!runtime || typeof contribution.mount !== "function") {
      return;
    }
    const key = `${kind}:${contribution.id}`;
    if (mounted.has(key)) {
      return;
    }
    contribution.mount(runtime);
    mounted.add(key);
  }

  function contributionById(collection, id) {
    return collection.find((entry) => entry.id === id) || null;
  }

  window.ElectroBoyFrontend = {
    workflows,
    modules,
    registerWorkflow(workflow) {
      if (!workflow || !workflow.id || !workflow.label || !workflow.mode) {
        throw new Error("workflow registration requires id, label, and mode");
      }
      upsert(workflows, { ...workflow });
      mountContribution("workflow", workflow);
    },
    registerModule(module) {
      if (!module || !module.id || !module.label) {
        throw new Error("module registration requires id and label");
      }
      upsert(modules, { ...module });
      mountContribution("module", module);
    },
    bindRuntime(nextRuntime) {
      if (!nextRuntime || typeof nextRuntime !== "object") {
        throw new Error("frontend runtime is required");
      }
      runtime = nextRuntime;
      this.runtime = runtime;
      for (const module of modules) {
        mountContribution("module", module);
      }
      for (const workflow of workflows) {
        mountContribution("workflow", workflow);
      }
    },
    workflow(id) {
      return contributionById(workflows, id);
    },
    workflowForMode(mode) {
      return workflows.find((entry) => entry.mode === mode) || null;
    },
    module(id) {
      return contributionById(modules, id);
    },
    stageActions(mode, stageId) {
      const workflow = this.workflowForMode(mode);
      if (!workflow || typeof workflow.stageActions !== "function") {
        return [];
      }
      return workflow.stageActions(stageId, runtime) || [];
    },
    invokeWorkflow(id, action, ...args) {
      const workflow = this.workflow(id);
      const handler = workflow && workflow.actions
        ? workflow.actions[action]
        : null;
      if (typeof handler !== "function") {
        throw new Error(`workflow action is not registered: ${id}.${action}`);
      }
      return handler(runtime, ...args);
    },
    invokeModule(id, action, ...args) {
      const module = this.module(id);
      const handler = module && module.actions ? module.actions[action] : null;
      if (typeof handler !== "function") {
        throw new Error(`module action is not registered: ${id}.${action}`);
      }
      return handler(runtime, ...args);
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
    listModules() {
      return [...modules];
    },
  };
})();
