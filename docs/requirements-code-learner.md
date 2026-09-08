# Code Learner Workflow Requirements

## Status

This document records an early product direction for a dedicated Code Learner
workflow. It defines the intended experience, boundaries, and initial
requirements so the design can be refined incrementally before implementation.

## Purpose

Code Learner helps a user understand an unfamiliar codebase through a guided,
step-by-step walkthrough. ElectroBoy should formulate a useful learning path,
show the relevant source code, highlight the current code region, and explain
that region in a separate pane.

The workflow should feel like a structured course over the repository, not a
general-purpose IDE. AI analysis should identify useful learning material from
the codebase, then ElectroBoy should formalize that material into a durable
course with verified source references, ordered steps, and navigation state. It
needs enough code browsing capability to teach the project well, while avoiding
the cost and scope of building an editor, debugger, terminal, or full
development environment.

## Product Direction

- Code Learner is a separate workflow from software implementation,
  requirements authoring, creative writing, and planning.
- The primary artifact is a learning course made of ordered walkthrough steps.
- Each step connects explanation text to one or more source locations.
- The code view is read-only.
- The code view should use language-aware syntax highlighting when available.
- Navigation is course-oriented: next step, previous step, outline, and jump to
  referenced code.
- The explanation pane should present the current step like a lesson slide,
  with previous and next controls kept close to the lesson content.
- A learner Q&A session should stay aware of the user's current course
  position, active file, highlighted range, and selected source context.
- The experience should help users build a mental model of the repository
  before asking them to modify it.

## Goals

- Generate a practical learning path for a selected repository or subdirectory.
- Support Architecture, Module, and Function learning modes.
- Present code and explanation side by side in synchronized panes.
- Highlight the exact lines, symbols, or blocks being discussed.
- Allow users to step forward and backward through the walkthrough.
- Preserve walkthrough state so a user can resume where they left off.
- Let users inspect nearby code without leaving the walkthrough context.
- Let users ask contextual questions about the currently visible lesson or code
  without manually supplying file names, line numbers, or symbol names.
- Support incremental improvement of the walkthrough content.
- Keep source-reading and walkthrough-rendering logic reusable by future
  workflows.

## Non-Goals

- Build a full IDE.
- Edit source files from the Code Learner workflow.
- Provide refactoring, formatting, language server, debugger, terminal, or test
  execution features as part of the first version.
- Replace the software development workflow for making code changes.
- Require perfect static analysis before a useful walkthrough can be created.
- Guarantee that generated explanations are complete or authoritative without
  user review.
- Turn the learner Q&A session into an editing, refactoring, debugging, or
  terminal-driven implementation assistant in the first version.

## Target Experience

The workflow opens into a focused learning surface:

- A walkthrough outline shows the current lesson sequence.
- A read-only code pane displays the active file with syntax highlighting based
  on the file language when available.
- The current line range is highlighted and scrolled into view.
- An explanation pane describes what the highlighted code does and why it
  matters, using a slide-like presentation for the current lesson.
- Previous and next controls move through the walkthrough from the explanation
  pane.
- Optional references can jump to related files or earlier/later steps.
- A contextual learner Q&A affordance lets the user ask follow-up questions
  about the current lesson, active source range, visible code, or selected
  symbol without restating that context.

The user should not need to choose files manually for every step. The workflow
should propose a coherent path through entry points, domain models, important
services, UI modules, workflow boundaries, and tests when those are relevant.

## Learning Modes

Code Learner initially supports three learning modes. The modes represent
different user intents rather than one linear depth scale.

### Architecture

Architecture mode describes the repository's purpose, goals, APIs, entry
points, major components, boundaries, and important data or control flows. It
should give the user a usable mental model of how the system fits together
without descending into exhaustive module or function-level detail.

Architecture mode should be useful when the user asks:

- What is this project for?
- What are the major moving parts?
- What APIs, commands, services, or workflows define the system boundary?
- Where should I start reading?

### Module

Module mode lets the user select a specific module, package, directory, or
component for a deep dive. The generated course should explain that module's
responsibilities, public interfaces, key files, internal flow, dependencies,
related tests, and how it connects to the rest of the repository.

Module mode should avoid attempting to cover the whole repository. It should
stay centered on the selected module while linking to external dependencies or
callers only when they clarify the module's role.

### Function

Function mode requires a function, method, class, or symbol name as input. The
generated course should explain the selected symbol's purpose, inputs, outputs,
local control flow, important branches, side effects, callers, callees, and
call tree where that information can be inferred from the source.

When a function name is ambiguous or cannot be resolved, the workflow should
show the candidate matches or a clear missing-symbol message instead of
generating an explanation against an uncertain target.

## Walkthrough Model

A walkthrough is durable structured data. Each walkthrough should include:

- repository root or selected source root
- title
- intended audience or learning goal
- learning mode: Architecture, Module, or Function
- mode-specific target when relevant, such as selected module path or function
  symbol
- ordered steps
- current step position
- generated timestamp and source revision when available

Each step should include:

- stable step id
- title
- explanation
- primary file path
- primary line range or symbol reference
- optional secondary references
- optional prerequisite or follow-up step references
- optional confidence or review status

The model should remain independent of the visual layout. A desktop pane grid,
future mobile view, exported document, or command-line summary should all be
able to consume the same walkthrough data.

## Learner Q&A Context

Code Learner should support a contextual AI session for follow-up questions.
The session should know what the user is currently looking at so questions like
"Why does this branch exist?", "Where is this called?", or "How does this fit
with the previous step?" can be answered without the user copying file paths,
line numbers, or source snippets into the prompt.

The learner context should include:

- active walkthrough id and learning mode
- current step id, title, and outline position
- active file path and source revision
- highlighted source range for the current step
- current code viewport when practical
- user-selected source range or symbol when present
- related references attached to the current step
- recent learner Q&A history for the same walkthrough

When a user selects a specific code range or symbol, that selection should take
priority over the broader step highlight. When no selection exists, the current
step's primary source reference should be the default question context.

Learner Q&A answers should remain grounded in source references where
practical. If the assistant needs broader repository context to answer a
question, it should retrieve only the relevant files or symbols instead of
loading the entire repository into the conversation.

## Functional Requirements

- `CL-1` Code Learner provides a distinct workflow entry point.
- `CL-2` A user can start a walkthrough for a repository, workspace, or selected
  subdirectory.
- `CL-3` ElectroBoy can generate an initial walkthrough plan from repository
  structure, source files, docs, and tests, then formalize the result into
  durable course state with verified source references where practical.
- `CL-4` The generated walkthrough is stored as durable structured state.
- `CL-5` The user can resume an existing walkthrough without regenerating it.
- `CL-6` The UI displays walkthrough outline, read-only code, and explanation
  panes together.
- `CL-7` Selecting a walkthrough step opens the step's primary source file.
- `CL-8` The active source range is highlighted and scrolled into view.
- `CL-9` Next and previous controls move between steps without losing the
  current walkthrough state.
- `CL-10` The user can jump from a step to related references when they are
  available.
- `CL-11` The code pane allows read-only inspection of nearby lines.
- `CL-12` The workflow clearly avoids edit affordances in the code pane.
- `CL-13` Missing, moved, or changed files are reported in the step view instead
  of causing the workflow to fail silently.
- `CL-14` A walkthrough records enough source revision information to warn when
  the code may have changed since generation.
- `CL-15` Generated explanations are traceable to the source locations they
  describe.
- `CL-16` The code pane applies language-aware syntax highlighting when the
  active file's language is supported.
- `CL-17` A user can create an Architecture walkthrough for a selected
  repository or source root.
- `CL-18` A user can create a Module walkthrough by selecting a specific module,
  package, directory, or component.
- `CL-19` A user can create a Function walkthrough by providing a function,
  method, class, or symbol name.
- `CL-20` Function walkthrough generation reports ambiguous or unresolved
  symbols before presenting course content for a specific target.
- `CL-21` A user can ask a learner Q&A question while viewing a walkthrough
  step.
- `CL-22` Learner Q&A receives the active walkthrough, current step, active
  file, highlighted source range, and selected source context when available.
- `CL-23` Learner Q&A answers can refer to the current code context without
  requiring the user to provide file paths, line numbers, or symbol names in
  the question.
- `CL-24` Navigating to a different step updates the learner Q&A context before
  subsequent questions are answered.
- `CL-25` Learner Q&A preserves enough conversation history to support
  follow-up questions within the same walkthrough.

## Quality Requirements

- The code pane must remain responsive on large source files.
- Highlighting must not require loading the whole repository into the browser.
- The workflow should degrade gracefully when syntax highlighting is unavailable
  for a language.
- Navigation between steps should preserve pane layout and scroll position where
  practical.
- Learner Q&A context should be bounded to the active lesson and relevant
  source references so routine questions do not require loading the whole
  repository.
- Learner Q&A should make stale source or unresolved context visible when the
  active file no longer matches the generated walkthrough reference.
- The generated path should prioritize important code over exhaustive coverage.
- The design should avoid workflow-specific duplication of generic file reading,
  code rendering, and source location behavior.

## Suggested Architecture Boundary

Code Learner should be built from small reusable parts:

- **Repository analyzer**: gathers repository structure, source files, docs,
  tests, entry points, module candidates, and symbol candidates.
- **Walkthrough planner**: produces ordered steps from repository context,
  learning mode, and mode-specific target.
- **Course formalizer**: validates and normalizes generated learning material
  into durable walkthrough state with source references.
- **Walkthrough state**: stores steps, current position, source revision, and
  review metadata.
- **Source adapter**: reads files and resolves source locations safely.
- **Read-only code viewer**: renders code, syntax highlighting, active ranges,
  and source-location navigation.
- **Explanation pane**: renders the current step explanation and related links.
- **Learner context provider**: tracks the active walkthrough, current step,
  active source range, user selection, and related references for AI Q&A.
- **Learner Q&A session**: answers contextual questions using the learner
  context and relevant source retrieval without owning course navigation.
- **Navigator**: owns previous, next, outline selection, and resume behavior.

The reusable code viewer should not know how a walkthrough is generated. The
planner should not know how panes are arranged. The workflow should compose
those pieces.

## Initial Acceptance Criteria

- A user can create a Code Learner walkthrough for the ElectroBoy repository.
- The workflow shows at least three generated steps with source file references.
- Clicking a step opens the referenced file in a read-only code pane.
- The read-only code pane syntax-highlights a supported source file language.
- The active line range is visibly highlighted.
- Previous and next controls update both the highlighted source range and the
  explanation pane.
- Reloading or reopening the workflow restores the current walkthrough and step.
- The code pane exposes no editing controls.
- Architecture mode produces a course describing purpose, APIs, entry points,
  major components, and important flows.
- Module mode accepts a selected module and keeps the generated course centered
  on that module.
- Function mode accepts a function or symbol name and resolves it before
  generating a call-flow-oriented explanation.
- Asking a learner Q&A question from a step answers using the current step's
  file and highlighted range without requiring the user to name them.
- Selecting a code range before asking a learner Q&A question scopes the answer
  to that selection.
- Moving to the next or previous step updates the learner Q&A context for the
  next question.
- Tests cover the walkthrough data contract and basic UI wiring.

## Open Decisions

- What should the first workflow entry point be: CLI command, browser workflow
  button, or both?
- How should the workflow present Architecture, Module, and Function mode
  selection in the first UI?
- How should Module mode discover and display selectable modules?
- How should Function mode discover, search, and disambiguate symbols?
- Where should learner Q&A live in the UI: inside the explanation pane, as a
  collapsible panel, or as a separate pane?
- Should learner Q&A history be persisted with the walkthrough or kept as
  ephemeral session state?
- How much visible code context should be included automatically with each
  learner Q&A request?
- Should walkthrough steps support multiple highlighted ranges in one file?
- Should steps support multiple files at once, or should each step keep one
  primary file with secondary references?
- What syntax-highlighting library should the read-only code viewer use?
- Should generated walkthroughs be editable as course content later, or only
  regenerable?
- How should the workflow present confidence, stale source, or hallucination
  risk?
- Should a walkthrough be exportable to Markdown after generation?

## Implementation Checklist

Use this checklist to keep implementation ordered and scoped.

1. [ ] Confirm the v1 scope: Architecture, Module, Function, read-only code
   pane, explanation pane, course navigation, and learner Q&A.
2. [ ] Inspect existing workflow entry point, routing, UI, state persistence,
   file-reading, and AI-session patterns that Code Learner should reuse.
3. [ ] Define the shared Code Learner domain model for walkthroughs, steps,
   source references, learning modes, mode targets, source revision metadata,
   review status, and learner Q&A context.
4. [ ] Add data-contract tests for walkthrough serialization, required fields,
   optional references, mode-specific targets, and current step state.
5. [ ] Implement the source adapter for safe path resolution, file loading,
   language detection, line-range extraction, and source revision checks.
6. [ ] Add source adapter tests for missing files, moved files, stale revision
   warnings, unsupported languages, and large-file boundaries.
7. [ ] Implement repository analysis for source tree summaries, documentation,
   tests, entry points, module candidates, and symbol candidates.
8. [ ] Add module discovery behavior so Module mode can present selectable
   modules, packages, directories, or components.
9. [ ] Add symbol discovery and resolution behavior so Function mode can find,
   disambiguate, or report unresolved function, method, class, and symbol names.
10. [ ] Define the planner interface that accepts repository context, learning
   mode, mode-specific target, and optional learning goal.
11. [ ] Implement Architecture planning to produce a course about purpose,
   APIs, entry points, major components, boundaries, and important flows.
12. [ ] Implement Module planning to produce a course centered on the selected
   module's responsibilities, public interfaces, key files, dependencies, and
   tests.
13. [ ] Implement Function planning to produce a course about the selected
   symbol's purpose, inputs, outputs, local flow, side effects, callers,
   callees, and inferred call tree.
14. [ ] Implement the course formalizer to normalize AI output, assign stable
   step ids, verify referenced files and ranges, attach confidence or review
   status, and reject ambiguous Function targets.
15. [ ] Persist generated walkthrough state, including current step, learning
   mode, target, generated timestamp, source revision, and review metadata.
16. [ ] Add resume behavior so reopening Code Learner restores the last
   walkthrough and current step without regeneration.
17. [ ] Build the Code Learner workflow shell with outline, read-only code pane,
   explanation pane, and previous/next controls.
18. [ ] Build the learning-mode start flow for Architecture, Module, and
   Function, including module selection and symbol disambiguation states.
19. [ ] Build the read-only code viewer with line numbers, syntax highlighting,
   active range highlighting, scroll-to-range behavior, and no edit affordances.
20. [ ] Connect outline selection and previous/next navigation to update the
   active file, highlighted range, explanation content, and persisted current
   step.
21. [ ] Add related-reference navigation for secondary source references and
   prerequisite or follow-up steps.
22. [ ] Implement learner Q&A context tracking for active walkthrough, current
   step, active file, highlighted range, visible code viewport, selected source
   range or symbol, related references, and recent learner questions.
23. [ ] Connect learner Q&A so questions can be answered from current context
   without requiring the user to provide file paths, line numbers, or symbols.
24. [ ] Ensure selecting a code range or symbol overrides the broader step
   context for the next learner Q&A question.
25. [ ] Ensure navigating between steps updates learner Q&A context before the
   next question is answered.
26. [ ] Add stale-source and unresolved-context UI states for both walkthrough
   steps and learner Q&A answers.
27. [ ] Add focused UI tests for mode selection, step navigation, source
   highlighting, resume behavior, missing source reporting, and learner Q&A
   context updates.
28. [ ] Add planner or formalizer tests with deterministic fixtures so course
   generation can be verified without depending on live AI responses.
29. [ ] Verify performance on large files and confirm the browser does not need
   to load the entire repository for ordinary step navigation or Q&A.
30. [ ] Run the relevant test suite and manually exercise the first complete
   flow: create walkthrough, navigate steps, inspect highlighted code, ask
   contextual Q&A, reload, and resume.
