# Selecting an agent backend

The **Backend** dropdown in the shared left sidebar discovers executable files
named `codex` or `codex-*` on the ElectroBoy service's `PATH`. There is no fixed
list of wrapper names. Discovered wrappers use the Codex adapter and session
format. Duplicate names appear once and resolve in normal `PATH` order;
executable symlinks are supported. The internal `codex-linux-sandbox` helper is
excluded because it is not an agent CLI. The built-in `codex` and `opencode`
entries also support project-configured executable paths. Unavailable entries are
disabled. Discovery refreshes with the selector, so installing or removing a
wrapper in an existing `PATH` directory updates the choices without a restart.
The initial selection is `codex`. Page reloads and other browser tabs
use the server's selection. The service saves successful selections in
`.electroboy/service/agent-backend.json` beneath its state root and restores
them on restart. An unavailable saved choice remains selected so the operator
can see it and choose an available alternative.

Changing the selection opens an ElectroBoy confirmation dialog. Cancel, Escape,
and the close button leave the selection and agents untouched. Confirming stops
all active agent terminals and background agent invocations, invalidates queued
agent launches, then changes the backend. Shell terminals remain running. Files
already written and session transcripts remain available.

The server checks the target executable before stopping agents. If termination
fails, it retains the previous backend and reports the failure; agents already
stopped cannot be restored automatically. Concurrent switches use a revision
check. Starts prepared before a switch must be retried.

## Sidebar sessions

Agent and Shell are separate expandable sidebar menus shared across workflows.
Agent contains the agent selector and Rename button. Shell lists running shells
for the current context and provides Start to open a new shell window. Selecting
an existing shell brings its window forward; browser popup and focus settings
still apply. The list refreshes every two seconds while the Shell menu is open.
Closing a disposable shell window keeps the existing shell cleanup behavior.
The top pane retains Splash, Text, connection status, and Help. Text controls
size to their contents so larger interface fonts do not clip their labels.

## Configuration and scope

Install and authenticate the selected CLI in the service user's environment.
The GUI selection chooses the provider for every role. For `codex` and
`opencode`, project runtime entries still supply executable paths, arguments,
environment allowlists, and options. Selecting a discovered `codex-*` wrapper
overrides only the executable for both interactive and background work; the
project's Codex arguments, environment allowlists, and options remain in effect.
These names must be executable files on the service's `PATH`, rather
than shell aliases or functions. Start the service from the environment whose
`PATH` should supply the choices; changing a parent shell's `PATH` requires
restarting the service to inherit it. Discovery checks filenames and executable
permissions without running the discovered programs. Wrapper-specific history
discovery still uses the service's `CODEX_HOME`; the service cannot infer a home
set inside a wrapper.
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

## Implementation

The existing agent sessions capability owns `/api/runtime/config` and the
frontend control. `service/agent_backend.py` coordinates selection, launch
admission, and cancellation using the service's existing lock. PTY and tmux
sessions carry a selection snapshot and a child environment override. Background
jobs capture a runtime factory with the same revision and cancellation event.
Workflow code requests these capabilities through `SessionServices`.

GET returns the selected binary as `backend`, its provider as `provider`,
the discovered choices and built-in providers as `backends`, per-entry
`availability`, revision, switching state, and active-agent counts. Switching
between two Codex binaries follows the same confirmation and cancellation rules
as changing providers.
POST accepts `backend`, `revision`, and `confirmed: true`. Unknown backends,
stale revisions, missing confirmation, unavailable executables, and failed
termination produce errors without reporting a successful switch.

## Verification

Run from the repository root:

```bash
source .electroboy/bin/activate
python -m pytest tests/test_agent_backend.py tests/test_opencode_runtime.py tests/test_opencode_integration.py -q
python -m pytest tests/test_service.py tests/test_runtime_adapters.py tests/test_runtime_config.py tests/test_corkboard_generation.py -q
python -m pytest tests/test_code_learner_controller.py tests/test_code_learner_agent_sessions.py tests/test_code_learner_tutor.py tests/test_code_learner_module_scheduler.py tests/test_ad_hoc_sessions.py -q
```

The tests use temporary projects and fixture executables, including real process
termination, rather than making paid model requests. Browser validation covers
the styled dialog, cancellation, switching both ways, reload, and tab sync.

### Validation recorded for this change

- Focused service, runtime, workflow, generation, and packaging suite: 319 passed.
- Repository suite excluding `tests/test_browser_smoke.py`: 671 passed, 2 skipped.
- Subsequent focused checks after final adapter and UI adjustments: 37 passed.
- Direct browser checks passed for default selection, the custom picker, Cancel,
  Escape, both switching directions, refresh, and synchronization across tabs.
- Real PTY and tmux child processes were stopped in automated tests.
- The existing browser smoke harness failed with Snap Chromium fixture access
  errors and timed out in five checks when run with Brave. Direct Playwright
  checks of this feature succeeded using Brave.
- No paid model requests were made. OpenCode v2.0.32 help was checked locally;
  adapter execution tests used deterministic fixture executables.

### Binary selector validation

The approved selector design reuses the existing backend switch lifecycle and
keeps provider identity separate from binary selection. Implementation extends
the backend coordinator and runtime resolver, then the existing agent-sessions
frontend. No workflow-specific selector or adapter was added.

Validation passed with 313 tests across these two commands. Fixture execution
covers launching a named wrapper and stopping it during a same-provider switch;
other tests cover both wrapper names, PTY/tmux configuration, workflow-child
environment propagation, background resolution, persistence, availability,
and stale revisions. JavaScript syntax and `git diff --check` also passed.
No live model requests or browser interaction checks were performed.

```bash
source .electroboy/bin/activate
python -m pytest tests/test_agent_backend.py tests/test_runtime_config.py tests/test_runtime_adapters.py tests/test_service.py -q
python -m pytest tests/test_opencode_runtime.py tests/test_opencode_integration.py tests/test_code_learner_controller.py tests/test_code_learner_agent_sessions.py tests/test_code_learner_tutor.py tests/test_ad_hoc_sessions.py -q
```
