# Repository Discovery

Inventory the repository before deciding its modules. Identify languages,
generated and vendored regions, build and dependency manifests, produced
artifacts, executable and public entry points, processes, state stores,
external systems, tests, examples, and documentation.

Infer modules from multiple signals: build targets, package boundaries,
registration tables, runtime composition, interfaces, dependencies, tests,
and source ownership. A directory name alone is not proof of a module.

Search generically for extension families such as providers, plugins, drivers,
adapters, backends, transports, handlers, workflows, passes, and strategies.
For every family, identify its contract, registration and selection mechanism,
shared infrastructure, and every concrete implementation in the checkout.
Create distinct implementation/module records where behavior is independently
meaningful. Record every exclusion and its reason.

Repository-wide scope means the full selected checkout. Recent modifications
may be noteworthy but must not suppress unchanged subsystems.
