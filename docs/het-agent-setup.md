# Heterogeneous agent setup

## Purpose and terminology

ElectroBoy supports concurrent agents using different providers and executables.
Each workspace has a default selection, which can be overridden for an agent.

- **Workspace** means the browser workspace identified by `workspace_id` or
  `context_id`, rather than a browser tab or pane.
- **Agent session** means one launched or resumable agent conversation.
- **Provider** means a runtime family, such as Codex or OpenCode.
- **Selection** means an executable such as `codex-atoz`, `codex-ornl`,
  `codex`, or `opencode`, and its derived provider.

## Requirements

### Workspace defaults and migration

- Maintain a separate default selection for each workspace. Connections to the
  same workspace share its default; different workspaces, including shared
  workspaces, can select different defaults.
- Persist defaults in namespaced workspace module state through the existing
  workspace registry. Restore the saved value with the workspace.
- Upgrade an older workspace when it is opened or restored, before exposing
  it for agent operations. Convert its default and session records to the
  current representation in one migration boundary. Normal launch, history,
  resume, and UI paths operate only on that representation.
- Give an older workspace without a default the existing service selection in
  `.electroboy/service/agent-backend.json`, or `codex` if it is absent or
  invalid. Persist the result. The legacy file is not a shared mutable default.
- Apply the same initialization when creating a workspace. Project-specific
  persistence beyond the workspace lifecycle is outside this design.
- Make workspace upgrades versioned and idempotent. Persist the converted data
  and version together; if conversion or persistence fails, report the error
  and leave the previous workspace data intact. Reopening must not duplicate
  records or overwrite a user's newer selections.
- Convert associated session records at the migration boundary, including
  records held in existing service catalogs. Restrict changes to the workspace
  and project being opened, preserve provider IDs and history, and coordinate
  writes with the existing locks and storage mechanisms.
- If an old session's executable cannot be determined, represent it explicitly
  as unresolved in the current format. Do not guess its identity or discard it.
- Validate the executable before saving a new default. If persistence fails,
  retain the prior value. Show an unavailable stored default so the user can
  select a replacement.
- Changing a default affects only selections resolved after the change. It
  must not stop running agents, cancel running or queued jobs, or invalidate a
  launch that already captured its selection.

### Agent launch and concurrent execution

- Allow multiple agents in one workspace, and agents in different workspaces,
  to run concurrently with different selections, including Codex and OpenCode.
- Resolve each new agent's selection once at the start of its launch request.
  A per-agent override takes precedence over the workspace default and does not
  change that default.
- Capture the selection before history lookup, command construction, and
  session preparation. Use that same selection throughout the launch.
- Check executable availability again at launch. Report a failure on the
  affected agent and clean up partially created session state; leave other
  agents and workspaces unaffected.
- Preserve existing workflow locks, approvals, and process lifetime rules.
  Heterogeneous agents do not override workflow concurrency restrictions.
- Support the selection on all interactive launch paths, including creative
  general and document agents, software agents, and code-learner agents.

### Session identity, history, and resume

- Record the provider and stable executable name for every agent session. Keep
  the resolved launch command in `provider_executable` where required by
  session discovery. Persist these values with the session record.
- Attach to a running session using its recorded selection. Reject a conflicting
  override rather than silently attaching to a different agent.
- Resume a completed conversation with its recorded provider and executable,
  even if the workspace default has changed. Reject a conflicting override or
  unavailable executable with an actionable error; retain the saved record.
- Start a new conversation to use a different provider. Changing a selection
  must not convert a Codex conversation into an OpenCode conversation or
  vice versa.
- Show the provider and executable for running and resumable sessions. Keep
  workspace, project, scope, provider, and executable associated with history.
- Search and validate Codex sessions against the home reported by the captured
  executable, since wrappers may set different `CODEX_HOME` values. Use the
  corresponding OpenCode session mechanism for OpenCode history.
- Look up an explicitly entered session ID in the selected provider's history.
  Session discovery and resume must not alter or delete other providers'
  history.
- For an unresolved session, ask the user to choose a compatible executable
  when resuming. Validate the session against it and persist the selection
  after successful resolution. Do not silently substitute a different provider
  or claim an unverified conversation was resumed.

### Background jobs

- Capture the workspace default when a background job is created. Keep that
  selection through queuing, execution, and any continuation belonging to it.
- Support an explicit per-job override only on surfaces that expose one.
  Otherwise use the captured workspace default.
- Apply this contract to workflow stages and reviews, creative corkboard
  generation, code-learner generation, and other managed jobs.
- Associate cancellation with the individual job or explicit stop action,
  not with a change to the workspace default.

### Workspace default UI

- Convert the existing backend control into a workspace default selector.
  Explain that the selection applies to new work.
- Change the default without a stop-all-agents confirmation or interruption.
- Refresh the displayed selection on workspace changes and synchronize it
  between connections to the same workspace.
- Show unavailable executable choices and surface save or validation failures.

### Agent selection UI

- Provide a per-agent selector on agent start surfaces, initialized from the
  workspace default. Send its choice with the launch request without changing
  the workspace default.
- Cover creative general and document agents, software agent start dialogs,
  and other interactive agent launch surfaces.
- Provide an agent selector in the Agent pane's context tools. It sets the
  selection for the next agent started from that pane, initially using the
  workspace default.
- Carry the pane selection into its Start dialog, where the user can override
  it for that launch. Reinitialize the pane selection from the new workspace
  default when the active workspace changes.
- Show an existing session's recorded selection when it is selected. A change
  to the pane's next-launch selection must not change an existing session.
- Display a fixed selection for a resumed conversation and explain any
  provider, executable, or availability conflict.

### Agent Info UI

- Add a read-only Info button to the Agent pane's context tools.
- Show the selected session's status, provider, executable name, resolved
  binary path when available, workspace, project, and session identifiers.
- List sessions in the current active workspace that use the same provider and
  executable, with their names, statuses, and IDs. Distinguish running sessions
  from completed or resumable sessions.
- Refresh information when Info opens. Identify stopped or unavailable agents,
  explain unresolved selections, and show an empty state if none is selected.
- Use authorized session and history APIs. Exclude session contents,
  credentials, and sessions from other workspaces.

### API, ownership, and concurrency

- Extend the existing session service for executable discovery, validation,
  selection resolution, session preparation, and managed runtime factories.
  Pass workspace identity and an optional per-launch override through its
  public protocol. Do not add a parallel backend manager.
- Keep provider-specific command construction in the existing adapters and
  workflow controllers. Resolve the selection before provider-specific work.
- Use the existing backend discovery and provider mapping. Accept executable
  names under the existing validation rules, not arbitrary shell fragments.
- Provide workspace-scoped configuration reads and writes through the existing
  module route registration. Reads return the default and available choices;
  writes validate the selection and require the appropriate workspace lease.
- Use the existing context URL mechanism for workspace, connection, and lease
  information. Reject mutations without valid workspace context. A transition
  route must not retain the service-wide stop behavior.
- Capture a coherent launch selection under the service lock when default
  changes and launches race. The captured selection is immutable thereafter.
  A default change cannot invalidate a previously captured launch.

## Existing implementation and change boundaries

- `service/agent_backend.py` owns one service-wide selection, cancellation
  epoch, and revision. Switching currently stops agents across all contexts.
- `modules/assets/agent-backend.js` uses the global `/api/runtime/config`
  route and warns that all agents will stop.
- Creative, software, and code-learner controllers, as well as background job
  factories, read the shared selection through `SessionServices`. Each call
  site must receive a workspace or captured agent selection instead.
- Creative and software histories already store provider metadata and sometimes
  `provider_executable`. Extend those records and lookup paths rather than
  creating a second history store.

## Implementation checklist

Each item describes an independently reviewable result. Check an item only
after its code and relevant validation are complete.

### 1. Workspace selection and migration

- [x] Add namespaced workspace default storage using the workspace registry;
      verify isolation, project reset, restore, and failed-write rollback.
- [ ] Verify workspace default storage for shared workspaces.
- [ ] Upgrade older workspaces and their associated session records at open or
      restore, using recorded provider and executable metadata when reliable.
      Persist the current representation and version as one upgrade.
- [ ] Seed missing defaults from the legacy service binary, falling back to
      `codex`, and mark sessions with unknown executables as unresolved.
- [ ] Make upgrades idempotent, scoped to the workspace and project, and safe
      on failure; keep history and provider identifiers intact.
- [x] Add selection resolution and executable availability validation to the
      existing session service contract, scoped by workspace.
- [x] Implement workspace-scoped configuration reads and writes with existing
      attachment and lease validation. The new endpoint rejects requests
      without workspace context.
- [ ] Remove the old service-wide configuration mutation path after the
      workspace UI and all launch paths use the scoped contract.
- [ ] Remove global stop, cancellation epoch, and revision invalidation from
      default changes; retain cancellation for explicit job/session stops.
- [ ] Verify independent defaults, one-time migration, reopen and restart,
      migration failure, lease rejection, and concurrent change/launch ordering
      in `tests/test_agent_backend.py`.

### 2. Agent launch and resume

- [x] Add an immutable selection and pass it through the session-service
      preparation contract; verify its metadata and launch command.
- [x] Add an explicit provider filter to service session history lookup.
- [x] Capture workspace defaults and explicit overrides for new creative,
      software ad hoc, and software stage agent launches. Capture workspace
      defaults for code-learner tutor launches.
- [ ] Capture provider and executable once per launch and persist both the
      stable selection and resolved executable in agent session metadata.
- [ ] Update session preparation and process guards to use the captured
      selection without checking a mutable service-wide backend revision.
- [ ] Route creative general and document agents through workspace defaults
      and explicit overrides; keep scope and existing agent reuse rules.
- [ ] Route software ad hoc, stage, interactive, and review agents through the
      same selection contract. Update code-learner interactive agent launches.
- [ ] Preserve provider/executable affinity for attachment and resume, reject
      conflicting overrides, and handle missing executables without affecting
      other sessions.
- [ ] Update Codex and OpenCode history lookup to filter by the captured
      selection and retain each record's own executable. Resolve an explicitly
      unresolved selection with user input and persist the validated result.
- [ ] Remove legacy workspace format branches from launch, history, resume,
      and UI paths; consume only the converted representation.
- [ ] Test mixed live agents, separate workspace defaults, overrides, resume
      after a default change, both providers, unavailable binaries, legacy
      metadata, and session-history isolation.

### 3. Background jobs and workflow integration

- [x] Capture workspace selections for corkboard and code-learner generation;
      retain the initialization selection in its scheduler continuation.
- [ ] Bind managed runtime factories to a captured workspace selection and
      replace global-switch cancellation with per-job cancellation.
- [ ] Pass workspace identity and captured selections to software workflow
      runs, creative corkboard generation, and code-learner generation.
- [ ] Audit remaining session-service callers and workflow CLI/adapter launch
      paths for implicit reads of a global backend or executable.
- [ ] Test queued and running jobs across default changes, explicit job
      cancellation, workflow locks, and simultaneous provider execution.

### 4. User interface

- [ ] Change the existing backend control to a workspace default selector;
      remove stop-all confirmation and use context-aware requests.
- [ ] Refresh the displayed default when switching workspaces and when another
      connection changes the same workspace's default.
- [ ] Add a per-agent selector to creative general and document start dialogs,
      software agent start dialogs, and other interactive launch surfaces.
- [ ] Add a next-launch agent selector to the Agent context tools, initialized
      from the workspace default and propagated to that pane's Start dialog.
      Verify it does not change the default or a running session's selection.
- [ ] Add an Info button to the Agent context tools. Show the selected session's
      status, provider, binary, workspace, project, and IDs, plus the current
      workspace's sessions using that provider and executable.
- [ ] Distinguish running and completed sessions in Info, handle unresolved
      selections and no selected session, and respect workspace authorization.
- [ ] Show the selection on running and resumable sessions. Display a fixed
      selection when resuming and explain conflicts or missing executables.
- [ ] Pass the selected override through each frontend action, route, and
      controller without changing the workspace default.
- [ ] Add service static assertions and behavioral browser coverage for default
      changes, context-tool selection, Info, and preserving a running agent.

### 5. Validation and documentation

- [ ] Run focused backend and service tests and frontend browser tests for
      the affected launch paths; resolve any failures.
- [ ] Exercise Codex wrapper and OpenCode selections concurrently, including
      restart and resume, with the executables available in the test setup.
- [ ] Review service and workflow boundaries for global selection reads,
      provider-specific logic in core, and untracked launch paths.
- [ ] Update operator documentation to explain workspace defaults, overrides,
      provider-specific history, resume behavior, and legacy migration.
- [ ] Preserve review findings, validation commands, results, and decisions
      according to the project development workflow.

## Acceptance criteria

A workspace using `codex-atoz` can start an agent, switch its default to
`opencode`, and start a second agent without interrupting the first. It can
then start a third agent with a `codex-ornl` override while keeping OpenCode as
the workspace default. Another workspace keeps its own default throughout.
After restart, each saved agent can be resumed using its recorded provider and
executable, subject to that executable and its history being available.
