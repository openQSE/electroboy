"use strict";

const subscriptions = new Map();
const clients = new Map();
let socket = null;
let reconnectTimer = 0;
let reconnectDelay = 250;

function socketUrl() {
  const protocol = self.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${self.location.host}/api/live`;
}

function postToSubscription(subscription, payload) {
  try {
    subscription.port.postMessage(payload);
  } catch (error) {
    removeClient(subscription.clientId);
  }
}

function sendSubscription(subscription) {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    return;
  }
  socket.send(JSON.stringify({
    type: "subscribe",
    subscription_id: subscription.id,
    path: subscription.path,
    last_event_id: subscription.lastEventId,
  }));
}

function connect() {
  if (!subscriptions.size || (
    socket
    && (socket.readyState === WebSocket.OPEN
      || socket.readyState === WebSocket.CONNECTING)
  )) {
    return;
  }
  clearTimeout(reconnectTimer);
  reconnectTimer = 0;
  const connectedSocket = new WebSocket(socketUrl());
  socket = connectedSocket;
  connectedSocket.addEventListener("open", () => {
    if (socket !== connectedSocket) {
      return;
    }
    reconnectDelay = 250;
    subscriptions.forEach(sendSubscription);
  });
  connectedSocket.addEventListener("message", (event) => {
    if (socket !== connectedSocket) {
      return;
    }
    let payload;
    try {
      payload = JSON.parse(event.data);
    } catch (error) {
      return;
    }
    const subscription = subscriptions.get(String(payload.subscription_id || ""));
    if (!subscription) {
      return;
    }
    if (payload.type === "event" && payload.last_event_id) {
      subscription.lastEventId = String(payload.last_event_id);
    }
    postToSubscription(subscription, payload);
  });
  connectedSocket.addEventListener("close", () => {
    if (socket !== connectedSocket) {
      return;
    }
    socket = null;
    subscriptions.forEach((subscription) => {
      postToSubscription(subscription, {
        type: "error",
        subscription_id: subscription.id,
        message: "live connection closed",
      });
    });
    if (subscriptions.size && !reconnectTimer) {
      reconnectTimer = setTimeout(connect, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 2, 5000);
    }
  });
  connectedSocket.addEventListener("error", () => {});
}

function closeSocketWhenIdle() {
  if (subscriptions.size || !socket) {
    return;
  }
  clearTimeout(reconnectTimer);
  reconnectTimer = 0;
  socket.close();
  socket = null;
}

function unsubscribe(subscriptionId, notifyServer = true) {
  const subscription = subscriptions.get(subscriptionId);
  if (!subscription) {
    return;
  }
  subscriptions.delete(subscriptionId);
  const client = clients.get(subscription.clientId);
  if (client) {
    client.subscriptionIds.delete(subscriptionId);
  }
  if (notifyServer && socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({
      type: "unsubscribe",
      subscription_id: subscriptionId,
    }));
  }
  closeSocketWhenIdle();
}

function removeClient(clientId) {
  const client = clients.get(clientId);
  if (!client) {
    return;
  }
  Array.from(client.subscriptionIds).forEach((id) => unsubscribe(id));
  clients.delete(clientId);
}

function handlePortMessage(port, event) {
  const message = event.data || {};
  const clientId = String(message.client_id || "");
  if (!clientId) {
    return;
  }
  let client = clients.get(clientId);
  if (!client) {
    client = {
      port,
      subscriptionIds: new Set(),
      lastSeen: Date.now(),
    };
    clients.set(clientId, client);
  }
  client.lastSeen = Date.now();
  if (message.type === "close") {
    removeClient(clientId);
    return;
  }
  if (message.type === "heartbeat") {
    return;
  }
  const subscriptionId = String(message.subscription_id || "");
  if (!subscriptionId) {
    return;
  }
  if (message.type === "unsubscribe") {
    unsubscribe(subscriptionId);
    return;
  }
  if (message.type !== "subscribe") {
    return;
  }
  unsubscribe(subscriptionId);
  const subscription = {
    id: subscriptionId,
    clientId,
    port,
    path: String(message.path || ""),
    lastEventId: String(message.last_event_id || ""),
  };
  subscriptions.set(subscriptionId, subscription);
  client.subscriptionIds.add(subscriptionId);
  connect();
  sendSubscription(subscription);
}

self.onconnect = (event) => {
  const port = event.ports[0];
  port.addEventListener("message", (message) => handlePortMessage(port, message));
  port.start();
};

setInterval(() => {
  const staleBefore = Date.now() - 300000;
  clients.forEach((client, clientId) => {
    if (client.lastSeen < staleBefore) {
      removeClient(clientId);
    }
  });
}, 60000);
