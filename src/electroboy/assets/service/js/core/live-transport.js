(function initializeLiveTransport() {
  "use strict";

  const workerPath = "/assets/service/js/core/live-transport-worker.js";
  const clientId = globalThis.crypto && globalThis.crypto.randomUUID
    ? globalThis.crypto.randomUUID()
    : `page-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const sources = new Map();
  let sequence = 0;
  let manager = null;
  let heartbeatTimer = 0;

  function websocketUrl() {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${window.location.host}/api/live`;
  }

  function subscriptionPath(url) {
    const parsed = new URL(url, window.location.href);
    if (parsed.origin !== window.location.origin) {
      throw new TypeError("live event streams must use the ElectroBoy origin");
    }
    return `${parsed.pathname}${parsed.search}`;
  }

  function deliver(payload) {
    const source = sources.get(String(payload.subscription_id || ""));
    if (source) {
      source.receive(payload);
    }
  }

  function sharedWorkerManager() {
    if (!("SharedWorker" in window)) {
      return null;
    }
    try {
      const worker = new SharedWorker(workerPath, "electroboy-live-v1");
      worker.port.addEventListener("message", (event) => deliver(event.data || {}));
      worker.port.start();
      return {
        subscribe(source) {
          worker.port.postMessage({
            type: "subscribe",
            client_id: clientId,
            subscription_id: source.subscriptionId,
            path: source.path,
            last_event_id: source.lastEventId,
          });
        },
        unsubscribe(source) {
          worker.port.postMessage({
            type: "unsubscribe",
            client_id: clientId,
            subscription_id: source.subscriptionId,
          });
        },
        heartbeat() {
          worker.port.postMessage({ type: "heartbeat", client_id: clientId });
        },
        close() {
          worker.port.postMessage({ type: "close", client_id: clientId });
          worker.port.close();
        },
      };
    } catch (error) {
      return null;
    }
  }

  function pageWebSocketManager() {
    let socket = null;
    let reconnectTimer = 0;
    let reconnectDelay = 250;

    function sendSubscription(source) {
      if (!socket || socket.readyState !== WebSocket.OPEN) {
        return;
      }
      socket.send(JSON.stringify({
        type: "subscribe",
        subscription_id: source.subscriptionId,
        path: source.path,
        last_event_id: source.lastEventId,
      }));
    }

    function connect() {
      if (!sources.size || (
        socket
        && (socket.readyState === WebSocket.OPEN
          || socket.readyState === WebSocket.CONNECTING)
      )) {
        return;
      }
      clearTimeout(reconnectTimer);
      reconnectTimer = 0;
      const connectedSocket = new WebSocket(websocketUrl());
      socket = connectedSocket;
      connectedSocket.addEventListener("open", () => {
        if (socket !== connectedSocket) {
          return;
        }
        reconnectDelay = 250;
        sources.forEach(sendSubscription);
      });
      connectedSocket.addEventListener("message", (event) => {
        if (socket !== connectedSocket) {
          return;
        }
        try {
          deliver(JSON.parse(event.data));
        } catch (error) {
          // Ignore malformed transport messages and keep the connection alive.
        }
      });
      connectedSocket.addEventListener("close", () => {
        if (socket !== connectedSocket) {
          return;
        }
        socket = null;
        sources.forEach((source) => source.receive({
          type: "error",
          subscription_id: source.subscriptionId,
          message: "live connection closed",
        }));
        if (sources.size && !reconnectTimer) {
          reconnectTimer = setTimeout(connect, reconnectDelay);
          reconnectDelay = Math.min(reconnectDelay * 2, 5000);
        }
      });
      connectedSocket.addEventListener("error", () => {});
    }

    return {
      subscribe(source) {
        connect();
        sendSubscription(source);
      },
      unsubscribe(source) {
        if (socket && socket.readyState === WebSocket.OPEN) {
          socket.send(JSON.stringify({
            type: "unsubscribe",
            subscription_id: source.subscriptionId,
          }));
        }
        if (!sources.size && socket) {
          socket.close();
          socket = null;
        }
      },
      heartbeat() {},
      close() {
        clearTimeout(reconnectTimer);
        reconnectTimer = 0;
        if (socket) {
          socket.close();
          socket = null;
        }
      },
    };
  }

  class LiveEventSource extends EventTarget {
    constructor(url) {
      super();
      sequence += 1;
      this.url = new URL(url, window.location.href).href;
      this.path = subscriptionPath(url);
      this.subscriptionId = `${clientId}:${sequence}`;
      this.lastEventId = "";
      this.readyState = LiveEventSource.CONNECTING;
      this.withCredentials = false;
      this.onopen = null;
      this.onerror = null;
      this.onmessage = null;
      sources.set(this.subscriptionId, this);
      manager.subscribe(this);
    }

    close() {
      if (this.readyState === LiveEventSource.CLOSED) {
        return;
      }
      this.readyState = LiveEventSource.CLOSED;
      sources.delete(this.subscriptionId);
      manager.unsubscribe(this);
    }

    receive(payload) {
      if (this.readyState === LiveEventSource.CLOSED) {
        return;
      }
      if (payload.type === "open") {
        this.readyState = LiveEventSource.OPEN;
        this.emit(new Event("open"));
        return;
      }
      if (payload.type === "error") {
        this.readyState = LiveEventSource.CONNECTING;
        this.emit(new Event("error"));
        return;
      }
      if (payload.type !== "event") {
        return;
      }
      this.lastEventId = String(payload.last_event_id || this.lastEventId);
      const type = String(payload.event || "message");
      this.emit(new MessageEvent(type, {
        data: String(payload.data || ""),
        lastEventId: this.lastEventId,
        origin: window.location.origin,
      }));
    }

    emit(event) {
      this.dispatchEvent(event);
      const handler = this[`on${event.type}`];
      if (typeof handler === "function") {
        handler.call(this, event);
      }
    }
  }

  LiveEventSource.CONNECTING = 0;
  LiveEventSource.OPEN = 1;
  LiveEventSource.CLOSED = 2;
  LiveEventSource.prototype.CONNECTING = 0;
  LiveEventSource.prototype.OPEN = 1;
  LiveEventSource.prototype.CLOSED = 2;

  manager = sharedWorkerManager() || pageWebSocketManager();
  heartbeatTimer = window.setInterval(() => manager.heartbeat(), 15000);

  function close() {
    window.clearInterval(heartbeatTimer);
    heartbeatTimer = 0;
    Array.from(sources.values()).forEach((source) => source.close());
    manager.close();
  }

  window.addEventListener("pagehide", close, { once: true });
  window.ElectroBoyLiveTransport = {
    eventSource(url) {
      return new LiveEventSource(url);
    },
    close,
  };
}());
