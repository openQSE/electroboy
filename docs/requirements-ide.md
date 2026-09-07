# ElectroBoy IDE Requirements

## Status

This document defines the initial requirements for adding a browser-based IDE
to ElectroBoy. It records the decision to use OpenVSCode Server as the first IDE
provider, while preserving the existing xterm.js terminal as a separate,
lighter-weight editing surface.

The first implementation must integrate a released OpenVSCode Server artifact.
It must not add Microsoft VS Code or OpenVSCode Server as a Git submodule, build
either source tree during normal ElectroBoy installation or startup, or couple
the ElectroBoy pane system directly to one IDE implementation.

## Core Decision

ElectroBoy will treat OpenVSCode Server as a managed external runtime dependency:

1. ElectroBoy pins a tested OpenVSCode Server release.
2. ElectroBoy locates a compatible system installation or installs the pinned
   release artifact into an ElectroBoy-managed data directory.
3. ElectroBoy supervises the IDE server as a child process associated with an
   ElectroBoy workspace and project.
4. ElectroBoy presents the IDE through its existing pane and pop-out system.
5. A small ElectroBoy VS Code extension supplies explicit communication between
   the IDE and ElectroBoy.
6. `vscode-neovim` is installed and enabled in the default managed IDE profile.
   Users may disable or reconfigure it from the IDE pane context menu. It is
   not the integration mechanism between OpenVSCode Server and ElectroBoy.
7. The existing xterm.js terminal continues to support terminal-native editors
   such as Vim and Neovim without requiring OpenVSCode Server.

ElectroBoy must consume release archives published by OpenVSCode Server rather
than cloning the repository. A Git submodule would provide a large source tree,
not a runnable IDE, and would transfer an unrelated Node/Yarn build pipeline to
ElectroBoy users and continuous integration.

If ElectroBoy later requires patches to OpenVSCode Server, those patches must be
built in a dedicated release pipeline. ElectroBoy should consume the resulting
versioned artifact rather than compiling the patched source at runtime.

## Goals

1. Provide a full graphical IDE inside the ElectroBoy workspace.
2. Let users edit the active project without leaving ElectroBoy.
3. Reuse OpenVSCode Server for file navigation, text editing, language services,
   source control, debugging, terminals, and extension hosting.
4. Support opening an IDE pane at a specific repository file, line, range, or
   symbol from another ElectroBoy pane.
5. Report the IDE's active file, cursor, and selection to ElectroBoy so agents
   and tutors can use the current editing context.
6. Keep IDE runtime acquisition, lifecycle, presentation, and editor integration
   behind modular interfaces.
7. Avoid duplicate IDE processes for the same active ElectroBoy workspace.
8. Bind the IDE to loopback and require per-instance authentication because
   other local processes and browser content may still reach localhost ports.
9. Preserve a lightweight xterm.js and Neovim path for users who do not need a
   graphical IDE.
10. Ship a pinned, tested `vscode-neovim` configuration enabled by default.
11. Match the established ElectroBoy visual language exactly so the IDE pane,
    menus, states, and controls do not look like a separate application shell.
12. Bound IDE processes, listeners, sockets, watchers, and retained streams so
    opening projects or panes cannot exhaust file descriptors.
13. Observe and control every outbound network attempt made by the IDE process
    tree or embedded IDE browser surface.

## Non-Goals

The first implementation will not:

- fork or rebuild Microsoft VS Code
- add the VS Code repository as a submodule
- add the OpenVSCode Server repository as a submodule
- compile OpenVSCode Server during ordinary ElectroBoy installation or startup
- reproduce Monaco, language servers, debugging, source control, or extension
  management inside ElectroBoy
- scrape the OpenVSCode DOM to discover editor state
- require the user to install `vscode-neovim` manually
- replace the existing xterm.js terminal pane
- synchronize one live IDE process across different host machines
- provide containerized or remote-host IDE execution in the first release
- promise compatibility with arbitrary Visual Studio Marketplace extensions
- overwrite a user's existing Neovim configuration

## Terminology

### IDE Provider

An adapter that can resolve, start, monitor, address, and stop a browser-based
IDE for an ElectroBoy workspace. OpenVSCode Server is the first provider.

### IDE Runtime

The installed executable distribution used by a provider. A runtime has a
provider name, version, platform, architecture, executable path, and origin.
Its origin is `managed` or `system`.

### IDE Instance

A running provider process associated with one ElectroBoy workspace and active
project. An instance includes process identity, workspace identity, repository
root, endpoint, connection token, profile directories, status, and timestamps.

### IDE Pane

An ElectroBoy pane that displays an IDE instance. The pane is a presentation of
the shared instance and does not own the server process.

### ElectroBoy IDE Bridge

A small VS Code extension owned by ElectroBoy. It exchanges explicit,
versioned commands and context events with the ElectroBoy service.

### Neovim Profile

The default managed IDE profile installs and enables `vscode-neovim`, points it
at a compatible Neovim executable, and keeps VS Code-specific configuration
separate from the user's ordinary terminal Neovim configuration. The user may
disable or reconfigure this profile from the IDE pane context menu.

## User Experience

### IDE Pane

The pane registry must expose an `IDE` pane type alongside File, Terminal,
Code Learner, and other pane types. Selecting it for an active project must:

1. Resolve or install the configured IDE runtime.
2. Start or reuse the IDE instance for the current workspace.
3. Display installation, startup, ready, stopped, and failed states clearly.
4. Load the IDE once its authenticated endpoint is ready.
5. Preserve ElectroBoy's existing pane resizing, moving, closing, docking, and
   pop-out behavior.

The IDE pane chrome must use the same colors, typography, spacing, borders,
selection treatment, icons, menus, loading states, empty states, and error
presentation as existing ElectroBoy panes. The managed OpenVSCode profile must
also apply an ElectroBoy IDE theme derived from the same design tokens for its
workbench, editor, tabs, sidebars, menus, selections, and status bar. OpenVSCode
may retain its native editor layout and interaction model, but neither its
default theme nor ElectroBoy-owned controls may introduce a second visual
language.

The IDE pane must expose a context menu using the standard ElectroBoy menu
component. It is the GUI entry point for IDE configuration, including provider
and runtime status, VSCode Neovim enablement and executable selection, startup
and idle behavior, diagnostics, restart, and stop actions. Configuration must
not be duplicated in a separate IDE-specific settings surface.

Opening a second IDE pane or pop-out for the same workspace must reuse the same
IDE instance. Closing a pane must not immediately stop an instance that is still
used by another pane or window.

### Project Lifecycle

The IDE is scoped to an ElectroBoy workspace and its active project:

- Activating a project makes the IDE action available.
- Opening the IDE starts or reuses that workspace's instance.
- Switching the active project must not show the prior project's files.
- Deactivating a project stops its IDE process after handling unsaved editor
  state according to the shutdown requirements below.
- Detaching a browser window does not stop a workspace-owned IDE instance.
- Closing the ElectroBoy service stops every IDE process it owns.
- A stale IDE process discovered after a service crash must not be adopted
  unless its identity and authentication data match persisted ElectroBoy state.
- Opening additional panes or pop-outs for the same workspace must not allocate
  another IDE port, process, watcher set, or provider log stream.
- Inactive IDE instances must be stopped according to a configurable bounded
  idle policy. ElectroBoy must also enforce a configured maximum number of live
  IDE instances and recover capacity by stopping eligible idle instances.

### Editor Navigation

ElectroBoy actions must be able to request:

- open repository-relative file
- reveal line
- select line range
- reveal symbol when the IDE can resolve it
- focus the IDE pane
- compare or open a diff when supplied by a future review workflow

These requests must go through the IDE provider and bridge contracts. Other
workflows must not construct provider URLs or send private OpenVSCode commands.

### Current Editor Context

The IDE bridge must report at least:

- active repository-relative file
- active editor language identifier
- cursor line and column
- selected start and end positions
- dirty state
- active workspace identity

ElectroBoy must make this context available through the same shared context
boundary used by agent input, tutors, and future workflows. Context updates
must be event driven and rate limited; ElectroBoy must not poll or scrape the
embedded IDE document.

## Modular Architecture

The implementation must separate the following responsibilities.

### Runtime Resolver

The runtime resolver locates a usable IDE executable. It supports these modes:

1. `managed`: use the ElectroBoy-pinned release, downloading it when absent.
2. `system`: use an operator-configured executable path and report its version.
3. `disabled`: expose no IDE start action while leaving all other ElectroBoy
   functionality operational.

Automatic selection may prefer an explicitly configured system executable and
otherwise use the managed runtime. The selected mode and resolved runtime must
be visible in service diagnostics.

### Runtime Installer

The managed installer must:

- use a manifest that pins provider, version, supported platform/architecture
  tuples, archive URL, archive format, and SHA-256 digest
- download only on explicit IDE use or an explicit installation command
- show download and extraction progress
- write into a temporary staging directory
- verify the complete archive before extraction
- publish an installation atomically after successful verification
- reject an unsupported platform without affecting other workflows
- reuse a valid existing installation
- avoid concurrent downloads of the same runtime
- retain enough metadata to explain where the executable came from
- support removing unused managed runtime versions

Managed data must live under the platform-appropriate ElectroBoy application
data directory, conceptually:

```text
<electroboy-data>/ide/runtimes/openvscode/<version>/<platform-architecture>/
```

The source repository and active user project must remain free of downloaded
IDE runtime files.

### IDE Provider Contract

The provider contract must expose responsibility-oriented operations similar to:

```text
resolve_runtime(configuration) -> runtime
start(workspace, project, runtime, profile) -> instance
status(instance) -> status
endpoint(instance) -> authenticated endpoint
open_location(instance, location) -> result
stop(instance, reason) -> result
```

The exact programming-language API belongs in the detailed design. The contract
must not expose OpenVSCode-specific process flags to pane renderers or unrelated
workflows.

### Instance Manager

The instance manager owns process lifecycle and the one-instance-per-workspace
guard. It must:

- allocate an available loopback port
- generate a cryptographically strong connection token
- allocate workspace-specific user-data and extension-data directories
- launch the provider with the active project as its workspace directory
- capture bounded startup diagnostics
- wait for a provider-specific readiness condition
- distinguish starting, ready, stopping, stopped, and failed states
- terminate a failed or timed-out child process
- prevent duplicate starts during concurrent pane requests
- retain the process independently of any single pane
- stop all owned processes during service shutdown
- enforce a configured upper bound on concurrently running IDE instances
- close listener sockets, proxy connections, WebSockets, file watchers, pipes,
  and diagnostic streams when an instance stops or fails
- reuse one provider endpoint for every pane and pop-out in a workspace
- expose resource counts sufficient to diagnose file-descriptor growth

The instance manager must not infer readiness merely because the child process
exists. It must check the server endpoint or another provider-defined readiness
signal.

### IDE Pane Adapter

The pane adapter consumes provider-neutral instance state and actions. It owns:

- loading and failure presentation
- authenticated IDE embedding
- retry and stop controls
- pane focus and pop-out integration
- forwarding open-location requests
- reacting to project deactivation and workspace changes

It does not own runtime downloads, process supervision, extension installation,
or editor context parsing.

### Bridge Service

The bridge service provides an authenticated, versioned protocol between the
ElectroBoy IDE Bridge extension and the ElectroBoy service. Its first protocol
must support:

- bridge registration for one workspace and IDE instance
- heartbeat and disconnect
- ElectroBoy-to-editor open-location commands
- editor-to-ElectroBoy active-context events
- request identifiers and explicit success or failure responses
- protocol version negotiation

The bridge must reject messages for another workspace or IDE instance. It must
not rely on connection tokens displayed in the IDE URL as its only authorization
mechanism.

## OpenVSCode Server Integration

### Launch Requirements

OpenVSCode Server must run as a child of the ElectroBoy service with:

- the active project as its workspace
- an OS-assigned or safely allocated port
- a loopback-only host binding
- a unique connection token
- workspace-specific user-data and extension directories
- inherited environment reduced to the variables required by the project and
  language tools
- stdout and stderr captured as bounded diagnostics

Tokens, authenticated URLs, and sensitive environment values must be redacted
from ordinary logs and GUI progress output.

### Embedding and Proxying

The implementation must begin with an integration spike that verifies:

- OpenVSCode resources load when embedded in an ElectroBoy pane
- WebSocket connections survive the chosen routing model
- service workers and browser storage do not collide across workspaces
- keyboard shortcuts reach the IDE correctly
- clipboard, drag-and-drop, file dialogs, and pop-out behavior remain usable
- authentication data is not leaked through referrers or ordinary logs

The preferred deployment is an authenticated ElectroBoy reverse-proxy route
under the ElectroBoy service origin. The proxy must support HTTP, WebSocket,
streaming, and rewritten location/resource paths required by the pinned
OpenVSCode release.

If the pinned release cannot be embedded reliably, the first fallback is an
ElectroBoy-managed pop-out window using the authenticated loopback endpoint.
The project must not weaken browser security headers globally merely to make an
iframe work.

### Network Sandbox and Egress Control

OpenVSCode Server must run inside a workspace-scoped network sandbox. The
sandbox boundary must include the server, extension hosts, language servers,
debug adapters, tasks, integrated terminals, and every descendant process.
Allowing an IDE child process to leave the sandbox would permit an extension or
tool to bypass the network policy by spawning another process.

ElectroBoy must support three egress modes:

1. `deny`: block outbound network access except authenticated communication with
   ElectroBoy-controlled endpoints required to operate the IDE. This is the
   default for the managed profile.
2. `allowlist`: permit only explicit workspace-scoped destination and port
   rules; block and log everything else.
3. `audit`: permit outbound connections but log each observed attempt and its
   disposition. The GUI must clearly indicate that audit mode does not prevent
   data transmission.

The control must operate at the network boundary rather than relying only on
proxy environment variables. HTTP proxy settings do not capture direct sockets,
custom DNS, UDP, or child processes that ignore the proxy. On Linux, the first
strong implementation should use an isolated network namespace or an
equivalent kernel-enforced boundary connected only through an ElectroBoy egress
broker. Other platforms require adapters with equivalent enforcement. When
strong enforcement is unavailable, ElectroBoy must report the sandbox as
unsupported and must not silently claim that outbound traffic is blocked.

The egress broker must record, when available:

- timestamp, workspace, and IDE instance
- originating process identifier and executable
- protocol and DNS query
- destination hostname, resolved address, and port
- matched policy rule and `allowed` or `blocked` disposition
- connection and byte counts without retaining transmitted content

Encrypted traffic normally reveals a destination but not the complete HTTPS
URL or payload. ElectroBoy must not install a TLS interception certificate or
claim to record encrypted request bodies. Logs must redact credentials, tokens,
URL query values, and repository content.

Browser-side traffic is outside the OpenVSCode server process sandbox.
ElectroBoy must separately constrain the embedded IDE with a restrictive Content
Security Policy and same-origin proxy rules. Blocked browser requests must be
reported back to ElectroBoy as sanitized policy violations. IDE pages, webviews,
service workers, and extension browser code must not contact external origins
directly in `deny` mode. Required external assets must be packaged locally or
fetched through an explicit, logged broker rule.

In `audit` mode, ElectroBoy must apply the equivalent policy as
`Content-Security-Policy-Report-Only` and route supported external requests
through its proxy so browser-side attempts are observable without being blocked.
The managed profile must explicitly disable product telemetry, feedback prompts,
automatic update checks, and automatic extension updates. Runtime and extension
downloads performed by ElectroBoy outside the IDE sandbox must use ElectroBoy's
audited download client and appear separately in network diagnostics.

The IDE pane context menu must expose the active egress mode, recent allowed and
blocked destinations, rule management, log clearing, and temporary workspace
exceptions. Changing from `deny` or `allowlist` to `audit` requires an explicit
warning that the IDE and its tools can transmit source code and credentials.

### Profiles and Persistence

IDE profile data must be isolated by ElectroBoy workspace or by an explicitly
defined reusable profile identity. At minimum, separate:

- OpenVSCode user data
- extension installation data
- workspace storage
- provider logs
- bridge registration data

The default managed profile must include the ElectroBoy IDE theme and the
default VSCode Neovim configuration. User changes may override profile settings
without changing ElectroBoy's application-wide theme configuration.

Project source remains in its original repository path. Profile cleanup must
never delete project files.

## Extensions

### ElectroBoy IDE Bridge Extension

The bridge extension is required for first-class integration. It must be small,
versioned with ElectroBoy, and installed into the managed IDE profile. It must
use supported VS Code extension APIs for editor state and commands.

The extension must not modify project source unless a user or ElectroBoy action
explicitly requests an editor operation. Reading active editor context must not
mark documents dirty.

The extension source may live in the ElectroBoy repository as its own package.
Its built VSIX is an ElectroBoy artifact; it is not a reason to vendor VS Code or
OpenVSCode Server source.

### VSCode Neovim

`vscode-neovim` is part of the default managed IDE profile. ElectroBoy must:

- pin a tested extension version
- install from a configured Open VSX source or a verified VSIX artifact
- verify any downloaded VSIX with a pinned digest
- detect a compatible Neovim executable
- report a clear unavailable state when Neovim is absent or too old
- keep VS Code-specific Neovim configuration separate where practical
- never overwrite `~/.config/nvim`, `init.lua`, or `init.vim`
- enable the profile by default when a compatible Neovim executable is present
- keep the IDE usable and report a degraded state when Neovim is unavailable
- allow the profile to be disabled or configured from the IDE pane context menu
  without affecting the IDE

OpenVSCode and VSCode Neovim compatibility must be tested as a version pair.
Updating either side requires rerunning editor input, command, selection,
extension-host, and reconnection tests.

### Other Extensions

The managed profile may install additional pinned extensions later. The first
implementation must not promise that extensions available only through the
Visual Studio Marketplace will work. Extension source, version, checksum, and
installation result must be diagnosable.

## xterm.js and Terminal Editors

The xterm.js terminal remains an independent ElectroBoy pane and must continue
to support `vim`, `nvim`, `tmux`, and ordinary shells. It is the preferred path
when a user wants:

- fast startup
- low resource usage
- an existing terminal Neovim configuration
- direct shell access
- no graphical IDE runtime download

ElectroBoy must not describe xterm.js as an IDE server. Xterm.js renders a
terminal connected to a pseudo-terminal; the shell and editor remain separate
processes owned by the backend.

Future work may add terminal-editor context integration, but that must use an
explicit Neovim plugin or RPC channel rather than parsing terminal escape output.

## Security Requirements

Loopback limits network exposure but does not establish user authorization.
Other processes on the host, browser content targeting localhost, or another
local user may attempt to reach an open IDE endpoint. Therefore localhost-only
operation still requires the following controls:

1. Every IDE server binds to loopback by default.
2. Every IDE server uses an unpredictable connection token.
3. Every bridge connection is bound to a workspace, IDE instance, and protocol
   version.
4. Tokens and authenticated URLs are redacted from logs and progress panes.
5. Reverse-proxy routes enforce the current ElectroBoy workspace lease.
6. The proxy permits access only to the IDE instance owned by that workspace.
7. Project paths supplied to the provider come from the active ElectroBoy
   workspace, not arbitrary browser input.
8. Runtime archives and VSIX files are verified before use.
9. Extraction rejects archive entries that escape the staging directory.
10. IDE process environment and diagnostics must not disclose unrelated service
    credentials.
11. The service must present a clear warning before exposing an IDE beyond
    loopback in any future remote-access mode.
12. Terminal and IDE surfaces must be treated as code-execution capabilities,
    not passive document viewers.
13. The complete IDE descendant process tree is subject to the selected network
    sandbox policy.
14. Browser-originated IDE and webview traffic is constrained separately with
    Content Security Policy and same-origin proxy enforcement.
15. Managed IDE profiles default to `deny` egress mode.
16. Network logging records destinations and dispositions but not source text,
    request bodies, credentials, authentication headers, or unredacted queries.

## Failure and Recovery

Failures in IDE acquisition or startup must not stop ElectroBoy or disable other
workflows. The GUI must distinguish:

- runtime not installed
- download unavailable
- checksum mismatch
- unsupported platform
- configured executable missing
- incompatible runtime version
- port allocation failure
- process exited during startup
- readiness timeout
- bridge extension unavailable
- IDE ready in a degraded state because default Neovim support is unavailable
- IDE process disconnected after becoming ready
- IDE instance limit reached with no eligible idle instance to stop
- network sandbox unavailable on the current platform
- IDE ready with outbound access denied
- outbound request blocked by policy

Retrying startup must reuse a verified runtime and clean up the failed process.
A checksum mismatch must discard the staged archive and require a fresh
download. A crashed instance may be restarted for the same workspace without
creating a second live process.

Before stopping an IDE with dirty editors, ElectroBoy must ask the provider to
surface normal editor save confirmation. If the provider cannot guarantee that
interaction during service shutdown, ElectroBoy must allow a bounded graceful
shutdown interval before terminating the process and report that unsaved editor
state may remain in provider backup storage.

## Configuration

The detailed design must define stable configuration for at least:

- provider selection
- managed, system, or disabled runtime mode
- system executable path
- pinned managed runtime version
- managed installation directory override
- IDE startup timeout
- IDE idle shutdown policy
- maximum concurrently running IDE instances
- IDE network egress mode
- workspace destination and port allowlist
- bounded network audit retention and redaction policy
- extension profile
- Neovim executable path
- optional extra provider arguments through a constrained advanced setting

These settings and their effective values must be available from the IDE pane
context menu using standard ElectroBoy menu controls. Settings that require a
restart must say so and offer a controlled restart action.

Unsafe defaults such as binding OpenVSCode Server to all interfaces or disabling
its connection token must not be exposed as ordinary GUI toggles.

## Diagnostics

ElectroBoy diagnostics must show:

- provider and runtime version
- managed or system runtime origin
- runtime executable path
- workspace and project identity
- instance state and process ID
- redacted endpoint
- startup duration
- bridge extension version and connection state
- default Neovim extension and executable status
- bounded recent provider output
- live IDE instance, listener, proxy connection, WebSocket, watcher, pipe, and
  retained diagnostic-stream counts
- network sandbox implementation and enforcement state
- bounded recent allowed and blocked egress events

Diagnostics must never print connection tokens or unredacted authenticated URLs.

## Implementation Checklist

### 1. Prove OpenVSCode Integration

- [x] Pin one OpenVSCode Server release for the integration spike.
- [x] Launch the release manually against a disposable repository.
- [x] Verify token-authenticated access over loopback.
- [x] Verify editor startup, file editing, save, terminal, source control, and
      extension-host behavior.
- [x] Verify embedding in an ElectroBoy-sized pane.
- [x] Verify WebSockets, browser storage, keyboard input, clipboard, and pop-out
      behavior.
- [ ] Verify service-worker webviews, drag-and-drop, and file-dialog behavior in
      the integrated ElectroBoy pane.
- [x] Decide whether the production surface uses a same-origin reverse proxy,
      direct loopback endpoint, or pop-out fallback.
- [x] Record resource consumption and cold/warm startup times.

Commit boundary: OpenVSCode integration spike and recorded decision.

### 2. Define Provider-Neutral Domain Contracts

- [x] Define runtime, instance, endpoint, status, location, and editor-context
      value objects.
- [x] Define the `IDEProvider` interface.
- [x] Define the runtime resolver and installer interfaces separately from the
      provider process interface.
- [x] Define workspace ownership and one-instance-per-workspace semantics.
- [x] Define provider-neutral error categories.
- [x] Add unit tests using a fake IDE provider.

Commit boundary: IDE domain and provider contracts.

### 3. Implement Runtime Resolution

- [x] Define the pinned runtime artifact manifest schema.
- [x] Add platform and architecture resolution.
- [x] Implement configured system executable discovery and version reporting.
- [x] Implement managed runtime lookup.
- [x] Implement disabled mode.
- [x] Expose the resolution result through diagnostics.
- [x] Add supported, unsupported, missing, and incompatible runtime tests.

Commit boundary: IDE runtime resolution.

### 4. Implement Managed Runtime Installation

- [ ] Download the pinned release archive into a staging directory.
- [ ] Report download and extraction progress.
- [ ] Verify the pinned SHA-256 digest before extraction.
- [ ] Reject escaping archive entries.
- [ ] Publish verified installations atomically.
- [ ] Guard concurrent installation attempts.
- [ ] Reuse existing verified installations.
- [ ] Support cleanup of unused versions.
- [ ] Add interrupted download, checksum mismatch, extraction failure, and
      concurrent install tests.

Commit boundary: managed OpenVSCode runtime installer.

### 5. Implement OpenVSCode Process Supervision

- [ ] Implement the OpenVSCode provider adapter.
- [ ] Allocate a loopback port and generated connection token.
- [ ] Create isolated user-data, extensions, workspace-storage, and log paths.
- [ ] Launch the active repository as the IDE workspace.
- [ ] Capture bounded and redacted process diagnostics.
- [ ] Implement a provider readiness check.
- [ ] Implement startup timeout and failed-process cleanup.
- [ ] Prevent duplicate starts for one ElectroBoy workspace.
- [ ] Reuse a ready instance across panes and pop-outs.
- [ ] Enforce the configured maximum live-instance count and idle cleanup.
- [ ] Close every listener, socket, watcher, pipe, and diagnostic stream when an
      instance stops, crashes, or fails startup.
- [ ] Add repeated open, close, project-switch, and restart tests that monitor
      file-descriptor counts and prove resource use remains bounded.
- [ ] Stop instances on project deactivation and service shutdown.
- [ ] Add lifecycle, concurrency, crash, restart, and shutdown tests.

Commit boundary: OpenVSCode instance lifecycle.

### 6. Implement IDE Network Sandboxing

- [ ] Define provider-neutral `deny`, `allowlist`, and `audit` egress policies.
- [ ] Default the managed IDE profile to `deny`.
- [ ] Implement the Linux network-sandbox adapter and ElectroBoy egress broker.
- [ ] Place OpenVSCode and every descendant process in the sandbox, including
      extension hosts, language servers, tasks, debug adapters, and terminals.
- [ ] Permit only authenticated ElectroBoy control traffic in `deny` mode.
- [ ] Record process, protocol, DNS, destination, port, rule, disposition, and
      bounded connection statistics without recording transmitted content.
- [ ] Redact credentials, tokens, query values, headers, and repository content.
- [ ] Add workspace-scoped destination and port rules for `allowlist` mode.
- [ ] Add an explicit warning before enabling permissive `audit` mode.
- [ ] Apply restrictive CSP and same-origin proxy rules to IDE pages, webviews,
      service workers, and extension browser code.
- [ ] Apply the equivalent report-only CSP and proxy logging in `audit` mode.
- [ ] Collect and sanitize browser CSP violation reports.
- [ ] Package required browser assets locally or route them through explicit,
      logged broker rules.
- [ ] Disable product telemetry, feedback prompts, automatic update checks, and
      automatic extension updates in the managed profile.
- [ ] Route ElectroBoy-managed runtime and extension downloads through the
      shared audited download client.
- [ ] Expose mode, enforcement status, recent events, rule management, temporary
      exceptions, and log clearing through the IDE pane context menu.
- [ ] Report unsupported enforcement instead of silently degrading to an
      unenforced policy.
- [ ] Test TCP, UDP, DNS, direct IP, proxy bypass, spawned-child, extension-host,
      terminal, task, language-server, WebSocket, webview, and service-worker
      traffic in every mode.
- [ ] Verify blocked requests do not leave the machine and allowed requests are
      logged once without sensitive payload data.

Commit boundary: IDE network sandbox and egress observability.

### 7. Add IDE Service APIs

- [ ] Add routes for runtime status and managed installation.
- [ ] Add routes for instance start, status, and stop.
- [ ] Add a provider-neutral open-location command route.
- [ ] Bind every operation to the current workspace lease.
- [ ] Redact endpoint authentication data from ordinary payloads.
- [ ] Expose structured diagnostics and recovery actions.
- [ ] Add route ownership, workspace isolation, and authorization tests.

Commit boundary: IDE service API.

### 8. Add the IDE Pane

- [ ] Register `IDE` as a reusable pane type.
- [ ] Add installation, starting, ready, stopped, and failure views.
- [ ] Embed the authenticated IDE using the routing decision from the spike.
- [ ] Preserve pane resizing, moving, closing, docking, and pop-out behavior.
- [ ] Match existing ElectroBoy pane colors, typography, spacing, borders,
      selection states, icons, menus, loading states, and error presentation.
- [ ] Add and apply an OpenVSCode theme derived from ElectroBoy design tokens.
- [ ] Verify workbench, editor, tabs, sidebars, menus, selections, and status bar
      remain visually consistent in every ElectroBoy-supported color mode.
- [ ] Add the standard ElectroBoy context menu to the IDE pane.
- [ ] Put IDE configuration, Neovim settings, diagnostics, restart, and stop
      actions in the IDE pane context menu.
- [ ] Reuse one instance across multiple views.
- [ ] Clear and disable the pane when its project is deactivated.
- [ ] Add retry and explicit stop actions.
- [ ] Verify desktop and constrained pane layouts visually.
- [ ] Add pane registration, state, and interaction tests.

Commit boundary: IDE pane presentation.

### 9. Build the ElectroBoy IDE Bridge Extension

- [ ] Create a separately packaged VS Code extension in the ElectroBoy source
      tree.
- [ ] Define and version the bridge protocol.
- [ ] Authenticate registration to one workspace and IDE instance.
- [ ] Report active file, language, cursor, selection, and dirty state.
- [ ] Implement file, line, range, and symbol navigation commands.
- [ ] Implement command request IDs and success or failure responses.
- [ ] Handle reconnection without duplicating event streams.
- [ ] Build a reproducible VSIX artifact.
- [ ] Install the bridge into managed IDE profiles.
- [ ] Add extension unit and OpenVSCode integration tests.

Commit boundary: ElectroBoy IDE bridge.

### 10. Integrate Editor Context Across ElectroBoy

- [ ] Add current IDE context to the shared workspace context model.
- [ ] Update context from bridge events with rate limiting.
- [ ] Let File, Code Learner, review, and agent surfaces open IDE locations
      through one shared action.
- [ ] Let agent and tutor prompts reference the current editor context without
      embedding unnecessary source content.
- [ ] Reset context on editor close, project switch, and deactivation.
- [ ] Add cross-workflow context and navigation tests.

Commit boundary: shared IDE navigation and context.

### 11. Add the Default VSCode Neovim Profile

- [ ] Select and pin a tested `vscode-neovim` version.
- [ ] Record a verified VSIX or Open VSX installation source.
- [ ] Detect the required Neovim version and executable path.
- [ ] Keep VS Code-specific settings isolated from normal Neovim use.
- [ ] Do not modify user Neovim configuration files.
- [ ] Install and enable VSCode Neovim in the default managed IDE profile.
- [ ] Expose enablement and Neovim executable selection through the IDE pane
      context menu.
- [ ] Keep the IDE operational in a clear degraded state when Neovim is absent
      or incompatible.
- [ ] Expose enabled, unavailable, incompatible, and disabled states.
- [ ] Verify insert, normal, visual, command, selection, clipboard, and
      reconnection behavior.
- [ ] Verify the bridge extension remains functional with Neovim enabled.
- [ ] Add profile installation and compatibility tests.

Commit boundary: default Neovim IDE profile and configuration controls.

### 12. Preserve the Terminal Editing Path

- [ ] Confirm xterm.js continues to launch Vim, Neovim, and tmux correctly.
- [ ] Keep terminal-editor startup independent of IDE runtime availability.
- [ ] Ensure IDE additions do not change project shell ownership or cleanup.
- [ ] Document the functional distinction between IDE and terminal panes.
- [ ] Add regression coverage for terminal startup and project deactivation.

Commit boundary: terminal editing regression protection.

### 13. Package and Release

- [ ] Add pinned artifact metadata for every supported platform and architecture.
- [ ] Verify managed installation from a clean ElectroBoy environment.
- [ ] Verify system executable mode.
- [ ] Verify offline and disabled behavior.
- [ ] Include required OpenVSCode and extension license notices.
- [ ] Define the upgrade and rollback process for runtime and extension pins.
- [ ] Confirm no OpenVSCode or VS Code Git submodule exists.
- [ ] Confirm normal installation does not compile OpenVSCode Server.
- [ ] Run the complete ElectroBoy test suite.

Commit boundary: IDE packaging and release readiness.

### 14. End-to-End Acceptance

- [ ] Activate a repository and open an IDE pane.
- [ ] Install or resolve the pinned runtime and reach ready state.
- [ ] Edit and save a source file from the IDE.
- [ ] Open a file and range from another ElectroBoy pane.
- [ ] Confirm ElectroBoy receives the IDE's active file and selection.
- [ ] Ask an agent or tutor a context-dependent question without manually naming
      the file or range.
- [ ] Open a second IDE pane or pop-out and confirm the process is reused.
- [ ] Verify modal editing with the default Neovim profile.
- [ ] Disable and re-enable Neovim from the IDE pane context menu.
- [ ] Repeatedly open and close IDE panes and projects while confirming process,
      port, socket, watcher, and file-descriptor counts remain bounded.
- [ ] Confirm the default sandbox blocks server, extension, child-process,
      terminal, and browser-originated external traffic.
- [ ] Confirm `allowlist` permits only configured workspace destinations.
- [ ] Confirm `audit` permits and logs traffic after displaying its warning.
- [ ] Inspect egress logs and confirm they contain destinations and dispositions
      without source code, request bodies, credentials, or token values.
- [ ] Deactivate the project and confirm the IDE process, pane state, and editor
      context are cleared.
- [ ] Restart ElectroBoy after an unclean exit and confirm stale IDE state is
      recovered or rejected safely.
- [ ] Confirm all tokens are absent from logs, diagnostics, and progress output.

Commit boundary: IDE end-to-end verification.

## Acceptance Criteria

The initial IDE feature is complete when:

1. ElectroBoy can resolve or install a pinned OpenVSCode Server release without
   cloning or compiling its repository.
2. No VS Code or OpenVSCode Server Git submodule exists.
3. One supervised IDE instance is reused for all IDE views belonging to one
   ElectroBoy workspace.
4. The instance is bound to loopback and protected by a generated token even
   when ElectroBoy itself is used only from localhost.
5. The IDE appears in the standard ElectroBoy pane and pop-out system, and all
   ElectroBoy-owned IDE controls match the existing GUI exactly.
6. A project file can be edited and saved from the IDE.
7. Other ElectroBoy workflows can open a file and range through a
   provider-neutral action.
8. The bridge reports active editor context without DOM scraping.
9. Agent and tutor context can identify the active editor file and selection.
10. Project switching and deactivation never expose the prior project in the IDE.
11. IDE acquisition or startup failure does not disable other ElectroBoy
    workflows.
12. The default VSCode Neovim profile works with a tested OpenVSCode and Neovim
    version combination, can be configured from the IDE pane context menu, and
    degrades cleanly when Neovim is unavailable.
13. Existing xterm.js project-shell and terminal-editor behavior remains intact.
14. Runtime and extension artifacts are pinned and verified before execution.
15. Connection tokens and authenticated URLs do not appear in ordinary logs or
    GUI progress output.
16. Repeated IDE use does not leak processes, ports, sockets, watchers, pipes,
    log streams, or file descriptors, and the configured live-instance limit is
    enforced.
17. The managed IDE defaults to kernel-enforced `deny` egress mode for its
    complete descendant process tree, while unsupported platforms clearly report
    that enforcement is unavailable.
18. Server-side and browser-side outbound attempts are blocked or allowed
    according to the selected workspace policy and appear once in redacted,
    bounded diagnostics.
19. Network controls and recent egress events are available from the IDE pane
    context menu.

## References

- [OpenVSCode Server](https://github.com/gitpod-io/openvscode-server)
- [OpenVSCode Server releases](https://github.com/gitpod-io/openvscode-server/releases)
- [OpenVSCode release image](https://github.com/gitpod-io/openvscode-releases/blob/main/Dockerfile)
- [VSCode Neovim](https://github.com/vscode-neovim/vscode-neovim)
- [xterm.js](https://github.com/xtermjs/xterm.js/)
- [xterm.js security guidance](https://xtermjs.org/docs/guides/security/)
