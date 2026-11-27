# Selecting an agent backend

The **Backend** dropdown selects the default for the active workspace. ElectroBoy
finds supported executable names on the service's `PATH`, including `codex`,
`codex-*` wrappers, and `opencode`; wrapper names are not configured in code.
Discovery refreshes when the selector is opened. Duplicate names resolve in
normal `PATH` order and executable symlinks are supported. The internal
`codex-linux-sandbox` helper is excluded because it is not an agent CLI. A
saved selection remains visible if its executable is unavailable.

Changing a workspace default affects future launches in that workspace. Existing
agents and background jobs continue with the executable they captured at launch,
and other workspaces keep their own defaults. The choice is saved with the
workspace and restored when it is reopened.

Agent start dialogs provide an optional per-agent selection. The Agent pane's
tools also provide a selection for its next launch and an **Info** button showing
the selected agent's executable and related sessions in the active workspace.
Overrides do not change the workspace default.

When a session is resumed, its recorded provider and executable are retained;
a conflicting override is rejected. If an older session lacks a reliable
executable record, select and confirm the executable used for that session.
Older workspace session records are converted when the project opens. Existing
provider session IDs and conversation history are preserved.

## Sidebar sessions

Agent and Shell are separate expandable sidebar menus shared across workflows.
Agent contains the agent selector and Rename button. Shell lists running shells
for the current context and provides Start to open a new shell window. Selecting
an existing shell brings its window forward; browser popup and focus settings
still apply.

## Configuration and scope

Install and authenticate the selected CLI in the service user's environment.
The workspace selection chooses the provider for its agent launches and
background jobs. For `codex` and
`opencode`, project runtime entries still supply executable paths, arguments,
environment allowlists, and options. Selecting a discovered `codex-*` wrapper
overrides only the executable for both interactive and background work; the
project's Codex arguments, environment allowlists, and options remain in effect.
These names must be executable files on the service's `PATH`, rather
than shell aliases or functions. Start the service from the environment whose
`PATH` should supply the choices; changing a parent shell's `PATH` requires
restarting the service to inherit it. Discovery checks filenames and executable
permissions without running the discovered programs. Codex history discovery
asks the selected executable for its configured home,
so wrappers can use different session directories. If the executable cannot
report a home, discovery falls back to the service environment.
Project role mappings cannot silently select a different provider for a GUI launch.
Standalone CLI commands retain their normal project configuration behavior.
ElectroBoy propagates `ELECTROBOY_AGENT_BACKEND` into managed agent children,
and `ELECTROBOY_AGENT_EXECUTABLE` when a discovered Codex wrapper is selected.

OpenCode support targets the v2 CLI, checked against installed version 2.0.32.
Interactive sessions use `opencode <directory> --standalone --session ...
--prompt ...`. Background turns use `opencode run --standalone --format json`
with the prompt on stdin. Private servers ensure that work belongs to the
managed process tree. OpenCode credentials, model selection, and ordinary tool
permissions come from its native configuration. The Code Learner tutor uses a
read-only OpenCode agent configuration instead of Codex's sandbox flag.

References: [OpenCode CLI](https://docs.opencode.ai/docs/cli/),
[configuration](https://docs.opencode.ai/docs/config/), and
[permissions](https://docs.opencode.ai/docs/permissions/).

Provider session identities are kept separate. Software and Creative Writing
can resume OpenCode sessions created by ElectroBoy in the same project and
scope. Existing Codex discovery continues when Codex is selected. Switching
providers starts fresh pipeline and Code Learner conversations where the saved
provider differs. It does not translate conversation history between providers.
