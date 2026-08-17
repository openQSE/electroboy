(function () {
  "use strict";

  const CHANNEL_NAME = "electroboy.sharedPaneState.v1";
  let connectionSequence = 0;

  function connect(options = {}) {
    const pane = String(options.pane || "");
    if (!pane) {
      throw new Error("shared pane synchronization requires a pane name");
    }
    const context = typeof options.context === "function"
      ? options.context
      : () => String(options.context || "");
    const snapshot = typeof options.snapshot === "function"
      ? options.snapshot
      : () => undefined;
    const receive = typeof options.receive === "function"
      ? options.receive
      : () => {};
    const priority = Number(options.priority || 0);
    const source = `${Date.now().toString(36)}-${++connectionSequence}-${Math.random()
      .toString(36).slice(2)}`;
    const channel = typeof window.BroadcastChannel === "function"
      ? new window.BroadcastChannel(CHANNEL_NAME)
      : null;
    let revision = 0;
    let receivedPriority = Number.NEGATIVE_INFINITY;
    let closed = false;

    function currentContext() {
      return String(context() || "");
    }

    function post(kind, state, target = "") {
      if (!channel || closed) {
        return;
      }
      channel.postMessage({
        kind,
        pane,
        context: currentContext(),
        source,
        target,
        state,
        revision,
        priority,
      });
    }

    function publish(state = snapshot()) {
      revision = Math.max(Date.now(), revision + 1);
      receivedPriority = priority;
      post("state", state);
    }

    function request() {
      post("request", null);
    }

    function handleMessage(event) {
      const message = event.data;
      if (
        !message
        || message.pane !== pane
        || message.context !== currentContext()
        || message.source === source
        || (message.target && message.target !== source)
      ) {
        return;
      }
      if (message.kind === "request") {
        post("state", snapshot(), message.source);
        return;
      }
      if (message.kind !== "state") {
        return;
      }
      const nextRevision = Number(message.revision || 0);
      const nextPriority = Number(message.priority || 0);
      if (
        nextRevision < revision
        || (nextRevision === revision && nextPriority < receivedPriority)
      ) {
        return;
      }
      revision = nextRevision;
      receivedPriority = nextPriority;
      receive(message.state, {
        context: message.context,
        pane,
        source: message.source,
      });
    }

    if (channel) {
      channel.addEventListener("message", handleMessage);
      window.queueMicrotask(request);
    }

    return {
      available: Boolean(channel),
      publish,
      request,
      close() {
        if (closed) {
          return;
        }
        closed = true;
        if (channel) {
          channel.removeEventListener("message", handleMessage);
          channel.close();
        }
      },
    };
  }

  window.ElectroBoyPaneSync = { connect };
})();
