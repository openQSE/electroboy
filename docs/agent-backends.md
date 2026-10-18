# Selecting an agent backend

The **Backend** dropdown in the top toolbar selects **Codex** or **OpenCode**
for all workspaces served by one ElectroBoy service. The initial selection is
Codex. Page reloads and other browser tabs use the server's selection. Restarting
the service resets it to Codex.

Changing the selection opens an ElectroBoy confirmation dialog. Cancel, Escape,
and the close button leave the selection and agents untouched. Confirming stops
all active agent terminals and background agent invocations, invalidates queued
agent launches, then changes the backend. Shell terminals remain running. Files
already written and session transcripts remain available.

The server checks the target executable before stopping agents. If termination
fails, it retains the previous backend and reports the failure; agents already
stopped cannot be restored automatically. Concurrent switches use a revision
check. Starts prepared before a switch must be retried.

## Configuration and scope

Install and authenticate the selected CLI in the service user's environment.
The GUI selection chooses the provider for every role. Project runtime entries
still supply executable paths, arguments, environment allowlists, and options;
role mappings cannot silently select a different provider for a GUI launch.
Standalone CLI commands retain their normal project configuration behavior.
ElectroBoy propagates `ELECTROBOY_AGENT_BACKEND` only into managed agent children.

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

GET returns the backend, revision, switching state, and active-agent counts.
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
