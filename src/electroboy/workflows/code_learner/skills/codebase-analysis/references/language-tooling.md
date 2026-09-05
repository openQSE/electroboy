# Language Tooling

ElectroBoy supplies the canonical file manifest and raw Universal Ctags JSONL.
Use Ctags records to locate functions, methods, classes, interfaces, types,
routes, commands, and other language constructs, but do not treat tags as
architectural ownership, call relationships, or runtime behavior.

Emit source-oriented locators, never Ctags line numbers or output ordering as
IDs. Include file ID, name, kind, scope, signature, and source range when known.
Read the referenced source before making behavioral claims. If Ctags lacks a
parser or symbol, provide file, name, and range evidence so ElectroBoy can run
targeted Ctags and repository-search resolution.

Do not build the learned repository or require a compilation database, object
files, language server, editor, or runtime trace. Preserve ambiguity for
overloads, nested scopes, generated code, macros, reflection, and dynamic
dispatch.
