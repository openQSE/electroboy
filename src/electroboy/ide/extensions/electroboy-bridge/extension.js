"use strict";

const fs = require("fs");
const path = require("path");
const vscode = require("vscode");

const PROTOCOL_VERSION = 1;
const POLL_INTERVAL_MS = 250;
const CONTEXT_DELAY_MS = 100;

let pollingTimer = null;
let contextTimer = null;
let revision = 0;
let registration = null;
let bridgeDirectory = "";
let processing = new Set();

async function activate(context) {
  await applyManagedWorkbenchSettings();
  revision = Date.now() * 1000;
  bridgeDirectory = String(
    vscode.workspace.getConfiguration("electroboy.bridge").get("directory", ""),
  ).trim();
  registration = readJson(path.join(bridgeDirectory, "registration.json"));
  if (!validRegistration(registration)) return;

  const update = () => scheduleContextUpdate();
  context.subscriptions.push(
    vscode.window.onDidChangeActiveTextEditor(update),
    vscode.window.onDidChangeTextEditorSelection(update),
    vscode.workspace.onDidChangeTextDocument((event) => {
      if (event.document === vscode.window.activeTextEditor?.document) update();
    }),
    vscode.workspace.onDidSaveTextDocument(update),
    vscode.workspace.onDidCloseTextDocument(update),
  );
  scheduleContextUpdate();
  pollCommands();
  pollingTimer = setInterval(pollCommands, POLL_INTERVAL_MS);
  context.subscriptions.push({ dispose: deactivate });
}

async function applyManagedWorkbenchSettings() {
  const workbench = vscode.workspace.getConfiguration("workbench");
  if (workbench.get("colorTheme") !== "ElectroBoy") {
    await workbench.update(
      "colorTheme",
      "ElectroBoy",
      vscode.ConfigurationTarget.Global,
    );
  }
}

function deactivate() {
  if (pollingTimer) clearInterval(pollingTimer);
  if (contextTimer) clearTimeout(contextTimer);
  pollingTimer = null;
  contextTimer = null;
  processing.clear();
}

function scheduleContextUpdate() {
  if (contextTimer) clearTimeout(contextTimer);
  contextTimer = setTimeout(writeEditorContext, CONTEXT_DELAY_MS);
}

function writeEditorContext() {
  contextTimer = null;
  const editor = vscode.window.activeTextEditor;
  revision += 1;
  const payload = envelope({
    revision,
    path: editor ? repositoryPath(editor.document.uri.fsPath) : null,
    language: editor?.document.languageId || null,
    cursor: editor ? position(editor.selection.active) : null,
    selection: editor
      ? {
          start: position(editor.selection.start),
          end: position(editor.selection.end),
        }
      : { start: null, end: null },
    dirty: Boolean(editor?.document.isDirty),
  });
  writeJsonAtomic(path.join(bridgeDirectory, "context.json"), payload);
}

async function pollCommands() {
  if (!registration) return;
  const completed = new Set(
    readJsonl(path.join(bridgeDirectory, "responses.jsonl"))
      .filter(authenticated)
      .map((record) => String(record.request_id || "")),
  );
  const commands = readJsonl(path.join(bridgeDirectory, "commands.jsonl"));
  for (const command of commands) {
    const requestId = String(command.request_id || "");
    if (
      !requestId ||
      !authenticated(command) ||
      completed.has(requestId) ||
      processing.has(requestId)
    ) {
      continue;
    }
    processing.add(requestId);
    try {
      if (command.command !== "open_location") {
        throw new Error(`unsupported bridge command: ${command.command}`);
      }
      await openLocation(command.location || {});
      appendResponse(requestId, true, null);
    } catch (error) {
      appendResponse(requestId, false, String(error.message || error));
    } finally {
      processing.delete(requestId);
    }
  }
}

async function openLocation(location) {
  const target = path.resolve(registration.project_root, String(location.path || ""));
  const document = await vscode.workspace.openTextDocument(vscode.Uri.file(target));
  const editor = await vscode.window.showTextDocument(document, { preview: false });
  let selection = await symbolSelection(document, String(location.symbol || ""));
  if (!selection) {
    const start = vscodePosition(location.line, location.column);
    const end = vscodePosition(
      location.end_line || location.line,
      location.end_column || location.column,
    );
    selection = new vscode.Selection(start, end);
  }
  editor.selection = selection;
  editor.revealRange(selection, vscode.TextEditorRevealType.InCenterIfOutsideViewport);
}

async function symbolSelection(document, symbolName) {
  if (!symbolName) return null;
  const symbols =
    (await vscode.commands.executeCommand(
      "vscode.executeDocumentSymbolProvider",
      document.uri,
    )) || [];
  const found = findSymbol(symbols, symbolName);
  if (!found) return null;
  const range = found.selectionRange || found.location?.range || found.range;
  return range ? new vscode.Selection(range.start, range.end) : null;
}

function findSymbol(symbols, symbolName) {
  for (const symbol of symbols) {
    if (symbol.name === symbolName) return symbol;
    const child = findSymbol(symbol.children || [], symbolName);
    if (child) return child;
  }
  return null;
}

function appendResponse(requestId, ok, error) {
  const payload = envelope({ request_id: requestId, ok, error });
  fs.appendFileSync(
    path.join(bridgeDirectory, "responses.jsonl"),
    `${JSON.stringify(payload)}\n`,
    { encoding: "utf8", mode: 0o600 },
  );
}

function envelope(payload) {
  return {
    protocol_version: PROTOCOL_VERSION,
    workspace_id: registration.workspace_id,
    instance_id: registration.instance_id,
    auth: registration.secret,
    ...payload,
  };
}

function authenticated(payload) {
  return (
    payload.protocol_version === PROTOCOL_VERSION &&
    payload.workspace_id === registration.workspace_id &&
    payload.instance_id === registration.instance_id &&
    payload.auth === registration.secret
  );
}

function validRegistration(payload) {
  return (
    payload &&
    payload.protocol_version === PROTOCOL_VERSION &&
    typeof payload.workspace_id === "string" &&
    typeof payload.instance_id === "string" &&
    typeof payload.project_root === "string" &&
    typeof payload.secret === "string" &&
    payload.secret.length >= 32
  );
}

function repositoryPath(filePath) {
  const relative = path.relative(registration.project_root, filePath);
  return relative && !relative.startsWith("..") ? relative : null;
}

function position(value) {
  return { line: value.line + 1, column: value.character + 1 };
}

function vscodePosition(line, column) {
  return new vscode.Position(
    Math.max(0, Number(line || 1) - 1),
    Math.max(0, Number(column || 1) - 1),
  );
}

function readJson(filePath) {
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (_error) {
    return null;
  }
}

function readJsonl(filePath) {
  try {
    return fs
      .readFileSync(filePath, "utf8")
      .split(/\r?\n/)
      .filter(Boolean)
      .flatMap((line) => {
        try {
          return [JSON.parse(line)];
        } catch (_error) {
          return [];
        }
      });
  } catch (_error) {
    return [];
  }
}

function writeJsonAtomic(filePath, payload) {
  const temporary = `${filePath}.${process.pid}.tmp`;
  fs.writeFileSync(temporary, `${JSON.stringify(payload)}\n`, {
    encoding: "utf8",
    mode: 0o600,
  });
  fs.renameSync(temporary, filePath);
}

module.exports = {
  activate,
  applyManagedWorkbenchSettings,
  deactivate,
  findSymbol,
  validRegistration,
};
