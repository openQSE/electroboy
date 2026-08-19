# ElectroBoy Workspace Isolation Detailed Design

## Purpose

ElectroBoy must support several projects progressing concurrently without
leaking documents, agents, project state, or GUI state between browser tabs.
The durable unit of isolation is an **ElectroBoy workspace**. Each workspace has
a UUID and contains the complete state needed to stop viewing the workspace and
return to it later.

An ElectroBoy workspace is distinct from an agent process and from a temporary
browser connection. The service can supervise many workspaces and many agent
processes at once, while each browser tab is attached to no more than one
workspace and each workspace is controlled by no more than one browser tab.

## Terminology

- **Workspace**: Durable ElectroBoy state for one active project or equivalent
  workflow-owned resource.
- **Workspace UUID**: Stable identifier assigned when a workspace is created.
- **Browser connection**: One browser tab connected to the ElectroBoy service.
- **Tab ID**: Identifier stored in that tab's `sessionStorage`.
- **Lease**: Exclusive, time-limited attachment between a tab and a workspace.
- **Agent process**: A Codex, Claude, shell, or other process owned by one
  workspace.
- **Workspace registry**: Service-wide inventory of durable workspaces.
- **Process registry**: Internal inventory of agent processes and their owning
  workspace UUIDs.

The existing `BrowserContext` model is close to the required workspace model.
It should evolve into the durable workspace rather than remain a second,
overlapping state container.

## User Experience

The Project menu retains its existing actions and adds a direct Workspace
action:

```text
Project
  Open
  New
  Workspace
  Close
```

Workspace is not an expandable submenu. Selecting it opens an overlay using the
same visual language as the ad-hoc agent selector. The overlay lists only
detached workspaces that are available to the current service owner. Attached
workspaces are omitted so the user is not invited to perform an operation that
will be rejected.

Each row displays the workspace name, project path or workflow-owned resource,
workflow and stage, running agent count, and last activity time. The workspace
name is normally derived from the effective project directory. For example, a
QFw project produces a workspace named `QFw`. A meta-project can use a more
specific label such as `openQSE - QFw`. Workflows without filesystem projects
must provide their own stable identity and display-name resolver.

A new browser tab starts with no workspace attached. Project-independent UI
remains available, but project documents, agents, workflow actions, status, and
progress are inactive. The user can open a project, create a project, or select
a detached workspace.

Opening or creating a project creates and attaches a workspace when no active
workspace exists for that canonical project identity. If a detached workspace
already exists, ElectroBoy reuses it. If the matching workspace is attached to
another tab, ElectroBoy rejects the operation.

## Workspace State

A workspace record contains at least:

```json
{
  "schema_version": 1,
  "workspace_id": "uuid",
  "name": "QFw",
  "workflow_id": "software",
  "project_kind": "project",
  "project_identity": "/canonical/path/to/QFw",
  "activation_root": "/canonical/path/to/QFw",
  "active_project_root": "/canonical/path/to/QFw",
  "active_repository_name": null,
  "workflow_state": {},
  "module_state": {},
  "selected_agent_id": null,
  "open_documents": [],
  "pane_layout": {},
  "created_at": "timestamp",
  "updated_at": "timestamp",
  "last_attached_at": "timestamp",
  "status": "detached"
}
```

Workflow and module state remains namespaced. A workflow serializes only its own
namespace, and a reusable module serializes only its module namespace. Live
Python process objects are never written into the workspace manifest. Their
stable IDs and recoverable metadata are stored separately by the process
manager.

The project identity must be canonical and workflow-aware. Filesystem workflows
use a normalized real path. Database-backed and remote workflows provide an
opaque identity through a public workspace-provider contract.

## Workspace Registry

The service core owns a thread-safe workspace registry. It supports creation,
lookup, persistence, listing, attachment, detachment, transactional switching,
heartbeats, and closure. It does not contain workflow-specific project logic.

Workspace manifests are stored beneath the ElectroBoy service state directory
and updated atomically. On service startup, the registry loads manifests before
restoring recoverable agent processes. A process record that refers to an
unknown workspace is invalid and must not cause an implicit workspace to be
created.

The registry enforces one non-closed workspace for each workflow and canonical
project identity. This prevents separate tabs from launching independent agents
against the same working tree without realizing that they share files.

## Exclusive Attachment

Each browser tab receives a random tab ID stored in `sessionStorage`. Attaching
a workspace creates a lease containing the workspace UUID, tab ID, private
lease token, and latest heartbeat time.

The server performs attachment under the workspace-registry lock. An attachment
succeeds only when the workspace is detached, its previous lease has expired,
or the request proves that it is a reload from the current lease owner. An
attempt from another tab receives `409 Conflict`.

The browser sends a heartbeat at a fixed interval. Reloading the same tab keeps
the tab ID and lease token. Explicit switching and closing send a detach request.
A best-effort unload notification improves responsiveness, but correctness must
depend on heartbeat expiration because unload events are not reliable.

Agent processes continue running while their workspace is detached. A detached
workspace remains resumable until the user closes it or a separately configured
retention policy removes an inactive workspace. Running agents prevent automatic
garbage collection.

## Transactional Switching

Switching must not detach the current workspace before confirming that the
target is available. The server validates the target lease and then changes both
workspace attachments in one locked transaction. If validation fails, the
current workspace remains attached and unchanged.

After a successful switch, the browser closes streams associated with the old
workspace, clears rendered state, updates its stored workspace UUID and lease,
loads the target snapshot, and reconnects only the target's streams and agents.

## API Contract

The core workspace capability owns routes equivalent to:

```text
GET  /api/workspaces
POST /api/workspaces
GET  /api/workspaces/{workspace_id}
POST /api/workspaces/{workspace_id}/attach
POST /api/workspaces/{workspace_id}/switch
POST /api/workspaces/{workspace_id}/detach
POST /api/workspaces/{workspace_id}/heartbeat
POST /api/workspaces/{workspace_id}/close
```

The selection overlay requests detached workspaces only. The server still
revalidates availability during attachment to handle races between clients.

Project, document, workflow, shell, progress, corkboard, and agent routes
require the workspace UUID and lease credential. Route dispatch resolves a
typed workspace service through `ServiceServices`; plugins must not read a
central service-state object. A workspace UUID by itself is not authorization
to inspect or mutate workspace state.

The current `context_id` query contract becomes `workspace_id`. A compatibility
reader may accept old persisted `context_id` fields during migration, but new
responses and plugin interfaces use workspace terminology.

## Project Open And Create

Open and create operations resolve a `WorkspaceDescriptor` before changing the
current tab:

```text
workspace identity
workspace display name
workflow id
project kind
activation root, when applicable
active project root, when applicable
owner scope, when applicable
```

The registry searches for a non-closed workspace with the same workflow and
identity. A detached match is attached, an attached match produces a conflict,
and no match creates a new workspace. When the tab is already attached, this is
performed as a transactional switch.

Workflow plugins that represent database accounts, remote environments, or
other non-filesystem resources supply the descriptor through a narrow public
provider interface. Core must not import those workflows or understand their
domain identifiers.

## Agent Process Isolation

The service keeps an internal process registry for supervision, persistence,
health reporting, and restart recovery. Every process record contains exactly
one workspace UUID. Agent selection endpoints return processes belonging to the
requesting workspace only.

The service-wide process registry must not populate the normal agent selector.
Cross-workspace agent attachment is removed. Resuming work means attaching the
complete workspace, not copying an agent into a different workspace or rewriting
the target workspace's project state.

Process restoration attaches a surviving process to its original restored
workspace. Missing or invalid ownership metadata is reported and quarantined
instead of assigning the process to a newly created workspace.

## Frontend State And Hydration

Core frontend state contains the current workspace UUID, tab ID, lease token,
and shared shell state. Workflow and capability bundles register serialization,
clearing, and hydration hooks through the frontend runtime.

Workspace switching follows this order:

1. Atomically switch the server lease.
2. Stop heartbeats and event streams for the previous workspace.
3. Invoke module and workflow clearing hooks.
4. Clear agent output, progress, documents, popouts, drafts, and cached status.
5. Store the new workspace UUID and lease in tab-local storage.
6. Load the complete workspace snapshot.
7. Invoke module and workflow hydration hooks.
8. Reconnect agent, progress, document, and project-shell streams.
9. Start the new workspace heartbeat.

Broadcast channels, popout identifiers, document drafts, event streams, and
other browser caches are keyed by workspace UUID. No workflow or module uses a
browser-global cache for project-owned data.

Pane layout and open-document state are workspace data. Presentation defaults
can remain local preferences, but the active pane arrangement and selected
artifacts must follow the workspace when it is resumed.

## Workspace Overlay

The overlay is a reusable core UI contribution rather than software-engineering
workflow code. It uses the existing modal and selection patterns but calls the
workspace capability through its public frontend runtime API.

The overlay includes a refresh action, accessible row selection, an explicit
Attach action, and Cancel. An empty result explains that no detached workspaces
are available. If another tab claims a workspace between listing and attaching,
the overlay reports the conflict and refreshes without disturbing the current
workspace.

## Closing And Retention

Closing a browser tab only detaches the workspace. Closing a project through the
Project menu closes its workspace after active agents are stopped or the user
confirms termination. A closed workspace is removed from the detached-workspace
overlay and cannot be attached.

Detached workspaces with running agents persist. Detached workspaces without
running agents can be retained indefinitely initially. A future retention policy
may archive or delete them based on last activity, but it must never remove an
active process without an explicit policy and visible reporting.

## Migration

Existing context IDs are treated as workspace UUIDs when possible. Persisted
agent records migrate `context_id` to `workspace_id` and retain the original UUID.
Existing namespaced workflow and module state moves into the workspace manifest.

Frontend `electroboy.contextId.*` keys are read once and converted to the new
workspace key. A restored context is attached only if no other live lease owns
it. The old global session-registry attachment endpoint is removed after process
records have been migrated.

Plugins receive a versioned workspace API. Packages that still require
`request.context_id`, `services.contexts`, or `contextUrl()` fail with a clear
compatibility error rather than silently operating without lease validation.

## Implementation Steps

1. Introduce workspace terminology and public workspace protocols.
2. Replace `BrowserContext` and `ContextStore` with durable workspace models.
3. Add atomic workspace persistence and startup restoration.
4. Add workflow-extensible workspace identity and display-name descriptors.
5. Enforce one active workspace for each workflow and project identity.
6. Add tab IDs, lease tokens, heartbeats, and atomic attachment validation.
7. Add workspace list, attach, switch, detach, heartbeat, and close routes.
8. Require workspace lease validation on all stateful module and workflow routes.
9. Convert project open and create operations into create-or-resume workspace
   operations.
10. Map every agent process to one workspace and remove cross-workspace attach.
11. Add the Project -> Workspace overlay and empty-tab startup state.
12. Add module and workflow serialization, clearing, and hydration hooks.
13. Key frontend streams, channels, popouts, drafts, and caches by workspace UUID.
14. Define project closure, detached retention, and process cleanup behavior.
15. Migrate existing context and process records without changing their UUIDs.
16. Update plugin documentation, API documentation, and built-in workflows.
17. Add isolation, lease, switching, persistence, migration, and browser tests.
18. Validate core-only, individual-workflow, and aggregate package combinations.

## Validation

Backend tests must prove exclusive attachment, heartbeat expiry, same-tab reload,
transactional switching, detached listing, project reuse, process ownership, and
workspace restoration after a service restart.

Browser tests must run at least two tabs with different workspaces. They must
verify that documents, agents, project status, scratch data, pane layouts, and
event streams never cross workspace boundaries. They must also close one tab,
confirm that its agents continue, and attach its detached workspace from a new
tab.

Plugin boundary tests must run core without optional workflows, each built-in
workflow independently, and an external workflow with a non-filesystem workspace
identity. Health and registry payloads should report workspace and provider
metadata without exposing another workspace's content.
