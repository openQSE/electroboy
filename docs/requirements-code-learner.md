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
general-purpose IDE. It needs enough code browsing capability to teach the
project well, while avoiding the cost and scope of building an editor,
debugger, terminal, or full development environment.

## Product Direction

- Code Learner is a separate workflow from software implementation,
  requirements authoring, creative writing, and planning.
- The primary artifact is a walkthrough made of ordered steps.
- Each step connects explanation text to one or more source locations.
- The code view is read-only.
- Navigation is course-oriented: next step, previous step, outline, and jump to
  referenced code.
- The experience should help users build a mental model of the repository
  before asking them to modify it.

## Goals

- Generate a practical learning path for a selected repository or subdirectory.
- Present code and explanation side by side in synchronized panes.
- Highlight the exact lines, symbols, or blocks being discussed.
- Allow users to step forward and backward through the walkthrough.
- Preserve walkthrough state so a user can resume where they left off.
- Let users inspect nearby code without leaving the walkthrough context.
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

## Target Experience

The workflow opens into a focused learning surface:

- A walkthrough outline shows the current lesson sequence.
- A read-only code pane displays the active file.
- The current line range is highlighted and scrolled into view.
- An explanation pane describes what the highlighted code does and why it
  matters.
- Previous and next controls move through the walkthrough.
- Optional references can jump to related files or earlier/later steps.

The user should not need to choose files manually for every step. The workflow
should propose a coherent path through entry points, domain models, important
services, UI modules, workflow boundaries, and tests when those are relevant.

## Walkthrough Model

A walkthrough is durable structured data. Each walkthrough should include:

- repository root or selected source root
- title
- intended audience or learning goal
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

## Functional Requirements

- `CL-1` Code Learner provides a distinct workflow entry point.
- `CL-2` A user can start a walkthrough for a repository, workspace, or selected
  subdirectory.
- `CL-3` ElectroBoy can generate an initial walkthrough plan from repository
  structure, source files, docs, and tests.
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

## Quality Requirements

- The code pane must remain responsive on large source files.
- Highlighting must not require loading the whole repository into the browser.
- The workflow should degrade gracefully when syntax highlighting is unavailable
  for a language.
- Navigation between steps should preserve pane layout and scroll position where
  practical.
- The generated path should prioritize important code over exhaustive coverage.
- The design should avoid workflow-specific duplication of generic file reading,
  code rendering, and source location behavior.

## Suggested Architecture Boundary

Code Learner should be built from small reusable parts:

- **Walkthrough planner**: produces ordered steps from repository context and a
  learning goal.
- **Walkthrough state**: stores steps, current position, source revision, and
  review metadata.
- **Source adapter**: reads files and resolves source locations safely.
- **Read-only code viewer**: renders code, syntax highlighting, active ranges,
  and source-location navigation.
- **Explanation pane**: renders the current step explanation and related links.
- **Navigator**: owns previous, next, outline selection, and resume behavior.

The reusable code viewer should not know how a walkthrough is generated. The
planner should not know how panes are arranged. The workflow should compose
those pieces.

## Initial Acceptance Criteria

- A user can create a Code Learner walkthrough for the ElectroBoy repository.
- The workflow shows at least three generated steps with source file references.
- Clicking a step opens the referenced file in a read-only code pane.
- The active line range is visibly highlighted.
- Previous and next controls update both the highlighted source range and the
  explanation pane.
- Reloading or reopening the workflow restores the current walkthrough and step.
- The code pane exposes no editing controls.
- Tests cover the walkthrough data contract and basic UI wiring.

## Open Decisions

- What should the first workflow entry point be: CLI command, browser workflow
  button, or both?
- Should users choose a learning goal before generation, such as "architecture",
  "new contributor", "frontend", or "tests"?
- Should walkthrough steps support multiple highlighted ranges in one file?
- Should steps support multiple files at once, or should each step keep one
  primary file with secondary references?
- What syntax-highlighting library should the read-only code viewer use?
- Should generated walkthroughs be editable as course content later, or only
  regenerable?
- How should the workflow present confidence, stale source, or hallucination
  risk?
- Should a walkthrough be exportable to Markdown after generation?
