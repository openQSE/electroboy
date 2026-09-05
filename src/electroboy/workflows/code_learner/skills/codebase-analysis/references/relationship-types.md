# Relationships And Runtime Flows

Use the supplied canonical relationship enum. Select the narrowest accurate type and
support it with source evidence. Capture ownership and containment, compile and
runtime dependencies, calls and dynamic dispatch, implementation, creation and
lifecycle, state reads and writes, events, configuration, persistence, tests,
deployment, and external communication where present.

Do not flatten an end-to-end behavior into disconnected edges. Create an
ordered runtime-flow record for major startup, shutdown, request, command,
authentication, data, persistence, messaging, selection, background-job,
error, and retry paths that exist in the repository.

Each flow step names known participants and supporting relationship IDs.
Represent branches and alternate flows. Mark function pointers, reflection,
generated calls, runtime registration, external code, and other unresolved
boundaries explicitly rather than presenting them as verified static calls.

For Phase 3 module relationship passes, endpoints are frozen module IDs only.
Components and symbols are evidence, never endpoints. Do not perform component
reconciliation or create inline components or modules. Unknown endpoints become
targeted requests. Preserve conditions, direction, confidence, limitations, and
dynamic or unresolved behavior.
