# Component Discovery

Read the complete file manifest before proposing components. Inspect project
documentation, build and dependency surfaces, entry points, registrations,
interfaces, state, tests, and representative implementation paths. Use raw
Ctags evidence as a symbol locator, then read source to understand meaning.

A component is the smallest source-backed architectural construct useful for
teaching. It may be one important function, a related function set, a type and
its operations, one file, several files, a registered implementation, or an
equivalent construct in the repository's languages.

Choose boundaries from multiple signals where available: source-defined names,
build ownership, package boundaries, registrations, runtime composition,
interfaces, dependencies, and tests. Do not create one component per symbol or
one repository-wide component unless the source genuinely supports that
boundary. Do not create a miscellaneous component to consume unassigned files.

Discover extension families generically, including providers, plugins,
drivers, adapters, backends, transports, handlers, workflows, passes, and
repository-specific equivalents. At this stage each concrete implementation
may become a component, but do not synthesize modules or relationships.

For every candidate, distinguish implementation it owns from files or ranges
that merely support the interpretation. Use a source-defined name when one is
available and record when a name is inferred. Repository-wide scope means the
full selected manifest; recent changes must not suppress unchanged systems.
