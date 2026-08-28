# Standalone Desktop and Mobile Client Requirements

## Status

This document records a parked product direction. It defines the boundary and
evaluation criteria for future planning without scheduling implementation.

## Purpose

ElectroBoy is delivered through a web interface served by the local service.
That interface can also support a dedicated desktop application and future
mobile clients without creating a second workflow implementation.

The desktop application should provide a focused ElectroBoy environment with
no general-purpose browser controls. Better-Planned should reuse the same
client and service contracts while presenting an interface designed for mobile
use.

## Decision Summary

- The web frontend remains the reusable user-interface foundation.
- A native application shell hosts the frontend on desktop and mobile.
- The ElectroBoy service remains the authority for workspaces, agents, files,
  workflows, and durable state.
- Platform-specific capabilities are exposed through narrow client adapters.
- A maintained Brave or Chromium fork is outside the planned architecture.
- Desktop and mobile layouts share capabilities without sharing every view.

## Motivation

A dedicated application can remove the address bar, history, tabs, extensions,
and unrelated browser profile behavior. It can also control window creation,
background throttling, local service startup, remote connections, native file
dialogs, application updates, and crash diagnostics.

Removing browser controls does not remove the browser engine. Rendering,
JavaScript execution, GPU composition, networking, and xterm.js remain browser
engine responsibilities. Application faults such as excessive terminal writes
or unbounded event streams must still be fixed in ElectroBoy.

Maintaining a Chromium-derived browser would add engine builds, security
updates, platform patches, and continuous upstream integration to the product.
The standalone client should use an embedding framework that already owns
those responsibilities.

## Goals

- Distribute ElectroBoy as an installable desktop application.
- Preserve browser access as a supported client.
- Reuse the existing frontend modules and workflow contributions.
- Give the desktop host control over page suspension and application lifetime.
- Support local services, remote services, and SSH-tunneled services.
- Establish a shared client foundation for Better-Planned mobile access.
- Keep workspace and agent-session state isolated between client connections.
- Measure efficiency and stability before choosing an embedding framework.

## Non-Goals

- Maintain a private fork of Brave, Chromium, Blink, or V8.
- Move workflow policy from the ElectroBoy service into a native shell.
- Give renderer JavaScript unrestricted filesystem or process access.
- Replace the browser client with a desktop-only distribution.
- Treat a scaled-down desktop pane grid as the mobile interface.
- Expose a local development service directly to an untrusted network.
- Assume that a native wrapper fixes frontend rendering or transport defects.

## Target Architecture

```text
Desktop browser   Desktop application   Mobile application
       |                  |                     |
       +---------- Platform client adapters ---+
                          |
               Shared frontend runtime
                          |
             Module and workflow bundles
                          |
                    HTTP and SSE
                          |
                  ElectroBoy service
                          |
       Workspaces, sessions, files, and workflow state
```

The shared frontend runtime owns composition, state presentation, transport,
and platform-neutral interaction logic. Reusable capabilities remain in
frontend modules. Software engineering, creative writing, Better-Planned, and
other workflows continue to contribute their own navigation and actions.

The native host must not import workflow-specific behavior. It provides a
small platform interface that any installed workflow can use.

## Platform Adapter Boundary

The browser, desktop, and mobile clients should implement the same logical
platform interface where their capabilities overlap. That interface covers:

- creating, closing, and focusing application windows
- selecting files and export destinations
- opening trusted external links
- showing native notifications
- storing non-secret client preferences
- reporting visibility and suspension state
- connecting to local or remote services
- managing an optional SSH tunnel
- reporting application and engine versions

Secrets, SSH keys, and authentication tokens belong in an operating-system
credential store or another protected facility. They must not be placed in
browser local storage.

## Desktop Host Evaluation

The desktop host should be selected through a measured prototype rather than
through a browser-engine fork.

| Candidate | Primary benefit | Main tradeoff |
| --- | --- | --- |
| Electron | Consistent Chromium behavior and low migration risk | Larger runtime and application package |
| Tauri 2 | Small package that uses the operating system webview | Different engines and behavior across platforms |
| CEF | Direct Chromium embedding with a stable native API | More native code, packaging, and lifecycle work |

Electron is the leading prototype candidate because the frontend and xterm.js
behavior are already exercised in Chromium. It also permits background
throttling to be disabled for the application window. The renderer should keep
Node.js integration disabled, use context isolation, and remain sandboxed.

Tauri should be benchmarked against the Electron prototype. It may reduce
package size and some runtime overhead, but Linux uses WebKitGTK while Windows
uses WebView2. That variation expands compatibility testing for terminal,
editor, file, and streaming behavior.

CEF remains an option when direct native control justifies a larger C++
integration. It should not be the starting point for the desktop client.

A Chromium application-mode window with a dedicated profile can provide an
early operational experiment. It does not replace framework evaluation or
produce the final distributable application.

## Desktop Functional Requirements

- `SA-1` The application opens directly into the ElectroBoy interface without
  an address bar, browser tabs, or general browser navigation.
- `SA-2` The application can connect to an existing service URL.
- `SA-3` A packaged deployment can start and monitor a local ElectroBoy
  service when that deployment owns the service lifecycle.
- `SA-4` The application preserves workspace identifiers, connection leases,
  and agent-session isolation across windows.
- `SA-5` Pane pop-outs become managed application windows and preserve their
  owning workspace connection.
- `SA-6` Backgrounding or hiding a window does not silently detach its
  workspace. The host either prevents throttling or makes suspension and
  reconnection explicit.
- `SA-7` The application supports native file selection and exports through a
  constrained platform adapter.
- `SA-8` External navigation is limited to approved destinations and opens in
  the system browser when appropriate.
- `SA-9` The application reports its shell, engine, frontend, and service
  versions for diagnostics.
- `SA-10` Desktop packaging provides signed updates or a documented managed
  installation path.

## Desktop Quality Requirements

- Idle CPU and memory use must be measured against the supported browser
  client under equivalent workspaces and panes.
- Terminal throughput and input latency must be measured with large agent
  transcripts and sustained output.
- Multi-day idle testing must cover hidden windows, minimized windows, network
  interruption, service restart, and workspace lease renewal.
- A renderer failure must not terminate the ElectroBoy service or its durable
  agent sessions.
- Restarting the desktop shell must recover attachable workspaces without
  leaking state from another workspace.
- The host must use a dedicated profile and must not load browser extensions.
- Engine and framework security updates require a documented release cadence.

## Mobile Product Direction

Better-Planned should use a mobile presentation built from the shared frontend
runtime and service contracts. A phone interface should show one primary task
at a time. Bottom navigation, touch-sized actions, focused document views, and
agent notifications replace the resizable desktop pane grid.

Terminal access may be offered as a dedicated full-screen view. Planning,
agent interaction, document review, approvals, and status monitoring should
not require a terminal layout.

The first mobile delivery candidate is an installable progressive web
application. A native container can follow when application-store delivery,
push notifications, protected credential storage, or other device features
are required. Capacitor is the leading web-first container candidate. Tauri 2
mobile should remain part of the evaluation if a shared Rust host becomes
valuable.

## Mobile Functional Requirements

- `SA-11` The mobile interface supports narrow screens without horizontal
  dependence on the desktop pane layout.
- `SA-12` A user can attach to a workspace, review status, interact with an
  agent, open documents, and perform workflow actions from a phone.
- `SA-13` Navigation preserves the active document, location, and agent session
  when moving between mobile views.
- `SA-14` Mobile backgrounding and resume are detectable. The client reports
  connection loss and renews or reattaches through the workspace protocol.
- `SA-15` The mobile client can be installed as a PWA or packaged application.
- `SA-16` Native packaging does not introduce a second workflow or state
  implementation.

## Remote Connectivity

A mobile device cannot reach a service running on another machine through the
device's own loopback address. Mobile distribution therefore depends on an
explicit remote connection model.

Supported designs may include a VPN connection, an application-managed SSH
tunnel, or an authenticated HTTPS gateway. Every remote design must provide:

- authenticated client identity
- encrypted transport
- explicit workspace authorization
- revocable credentials
- bounded file access
- session and request auditing
- reconnect behavior that preserves isolation

The choice among VPN, SSH, and a hosted gateway must be made before a public
mobile release. The desktop application can support local and SSH-tunneled
operation without committing the mobile product to the same transport.

## Packaging and Compatibility

The frontend and service require an explicit compatibility handshake. A client
must detect unsupported service versions and present a useful upgrade path.

Desktop packaging must define whether the Python service is bundled, installed
as a managed system service, or discovered separately. The shell should keep
these deployment modes behind one service-connection interface.

Mobile packaging should reuse the same generated frontend assets where
possible. Platform-specific code belongs in the platform adapter or a native
plugin with a narrow API.

## Evaluation Plan

### Phase 1. Application-Mode Baseline

Run the existing frontend in Chromium application mode with an isolated
profile. Record startup time, idle resource use, terminal throughput,
background behavior, and long-idle stability.

### Phase 2. Desktop Shell Prototypes

Host the same frontend in minimal Electron and Tauri applications. Each
prototype connects to the existing service without changing workflow code.
Compare engine compatibility, resource use, packaging effort, diagnostics,
security controls, and suspension behavior.

### Phase 3. Desktop Productization

Select one host, formalize the platform adapter, add service discovery, and
produce a signed Linux package. Additional desktop platforms can follow after
the client and service contracts stabilize.

### Phase 4. Responsive Better-Planned Client

Create the mobile information architecture and responsive views on top of the
shared client runtime. Validate the PWA on representative phones and tablets.

### Phase 5. Native Mobile Packaging

Package the responsive client after the remote connection and credential model
is approved. Add native features only through constrained adapters.

## Acceptance Criteria for Architecture Selection

- The desktop prototype runs existing module and workflow bundles without
  workflow-specific host code.
- Browser, desktop, and mobile clients can use the same service contracts.
- Workspace isolation tests cover multiple windows and multiple client types.
- Long-idle testing reproduces or rules out page suspension and connection
  loss under each candidate host.
- Resource measurements compare complete equivalent workloads rather than
  empty windows.
- The selected framework has an acceptable security-update and packaging path.
- Mobile validation includes interrupted networks and operating-system
  background suspension.

## Open Questions

- Should the desktop package bundle the Python service or manage a separately
  installed service?
- Which desktop operating systems are required for the first supported
  release?
- Should SSH tunnel management belong to the desktop host or an external tool?
- Which remote connection model is appropriate for Better-Planned mobile use?
- Does mobile need offline read access or queued actions?
- Are push notifications required for completed agents and approvals?
- Should Electron's consistent Chromium runtime take priority over Tauri's
  smaller package?
- What evidence would justify moving from Electron or Tauri to CEF?

## References

- [Electron overview](https://www.electronjs.org/docs/latest/)
- [Electron window customization](https://www.electronjs.org/docs/latest/tutorial/window-customization)
- [Electron security guidance](https://www.electronjs.org/docs/latest/tutorial/security)
- [Tauri architecture](https://v2.tauri.app/concept/architecture/)
- [Tauri webview versions](https://v2.tauri.app/reference/webview-versions/)
- [Capacitor documentation](https://capacitorjs.com/docs)
- [Chromium Embedded Framework](https://chromiumembedded.github.io/cef/general_usage.html)
- [Chromium Linux build documentation](https://chromium.googlesource.com/chromium/src/+/master/docs/linux/build_instructions.md)
