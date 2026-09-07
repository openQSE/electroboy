# OpenVSCode Integration Spike

## Decision

ElectroBoy will integrate OpenVSCode Server `1.109.5` through a same-origin
ElectroBoy HTTP and WebSocket proxy. The managed IDE process will listen on a
Unix-domain socket inside a network-isolated process sandbox. It will not
allocate a TCP port.

This design was selected because the pinned release supports
`--socket-path`, authenticated access and WebSockets work through a raw socket
relay, and an OpenVSCode workbench renders correctly inside an
ElectroBoy-sized iframe. The Unix socket also gives one stable provider endpoint
per workspace without consuming another TCP listener.

## Pinned Runtime

| Field | Value |
| --- | --- |
| Provider | OpenVSCode Server |
| Version | `1.109.5` |
| Release date | 2026-02-20 |
| Platform | Linux x86-64 |
| Archive | `openvscode-server-v1.109.5-linux-x64.tar.gz` |
| Size | 76,686,959 bytes |
| SHA-256 | `b433bf4f0227321a7014d8460d10a8f958adc0f45aa79bd889e84e65e8f88363` |

The archive digest was verified before extraction. The release was launched
from `/tmp`; no runtime files were added to the ElectroBoy repository.

## Functional Results

- An unauthenticated request returned HTTP `403`.
- A request with the configured connection token established an authenticated
  cookie and loaded the workbench.
- The repository opened through the `folder` URL parameter.
- The browser edited and saved `README.md`; the saved bytes were verified from
  the host filesystem.
- The integrated terminal created a file and initialized a Git repository.
- The workbench detected the resulting Git branch and untracked-file count.
- The extension host, file watcher and pseudo-terminal host started normally.
- The workbench rendered in a cross-origin `980x700` iframe.
- Two workbench WebSocket channels remained connected through a raw TCP-to-Unix
  relay.
- Browser storage and clipboard APIs remained available in the embedded frame.
- Direct top-level loading works, so an ElectroBoy pop-out can use the same
  proxied endpoint.

## Sandbox Results

Bubblewrap successfully created an unprivileged network namespace on the test
host. The namespace had no network route or DNS resolution. OpenVSCode remained
usable through its Unix socket and retained token authentication. The launch
used `--telemetry-level off`.

The server reported a nonfatal MAC-address warning because the empty network
namespace has no normal network interface. Readiness and editor functionality
were unaffected. Production diagnostics should suppress repetition of this
known warning while retaining it in bounded provider output.

## Resource Results

One sandboxed instance with two browser clients used approximately 610 MiB RSS,
eight descendant processes, 209 open file descriptors and one Unix listener.
Each additional browser client caused OpenVSCode to create another extension
host and file watcher. ElectroBoy must therefore bound both live IDE instances
and simultaneous views of an instance; process reuse alone does not bound
resource consumption.

On the spike host, authenticated HTTP readiness over the Unix socket took 127
ms with a fresh managed profile and 125 ms after restarting with that profile.
These measurements cover provider process readiness, not browser workbench
rendering or extension activation.

## Proxy Requirements Confirmed by the Spike

The pinned release emits a Content Security Policy that permits generic HTTPS
connections and `vscode-cdn.net` frames. The production proxy must rewrite that
policy according to the selected IDE egress mode. It must preserve HTTP
streaming, authentication cookies, WebSocket upgrades and large static assets.

The proxy must not expose the provider connection token to the browser. It will
authenticate the browser using the ElectroBoy workspace lease and attach the
provider token only on the private Unix-socket request.
