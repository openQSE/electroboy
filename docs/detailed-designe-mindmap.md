# ElectroBoy Mind Map Detailed Design

## Purpose

The Mind Map capability provides a lightweight planning surface for the
software-engineering and creative-writing workflows. Users can build a graph
manually, arrange ideas on an unbounded canvas, and connect concise planning
nodes to detailed project documents.

ElectroBoy owns the reusable editor, storage format, and document integration.
Workflows may expose the capability and provide defaults, but the map does not
depend on workflow-specific records. Provider-backed projections, including the
Better Planned traceability map, continue to use the same renderer in a
read-only mode.

## Goals

- Create independent root nodes anywhere on the canvas.
- Add child and sibling nodes quickly with the keyboard or pointer.
- Reparent, detach, reorder, rename, move, and delete nodes.
- Preserve a stable spatial layout while supporting explicit branch cleanup.
- Collapse branches and focus on one area of a large plan.
- Link nodes to project files, arbitrary filesystem files, and web URLs.
- Create a Markdown document from a node and edit it without leaving the map.
- Store maps in portable, versioned files suitable for source control.
- Reuse one renderer for editable maps and provider-backed projections.
- Keep the module independent of software and creative workflow policy.

## Non-Goals

The initial capability does not provide real-time collaboration, comments,
presentation mode, task scheduling, or a large template gallery. Rich text,
arbitrary shapes, image attachments, AI-generated maps, and several competing
layout engines are outside the initial scope.

The map does not replace the File pane or create another document editor. It
uses the existing document rendering and editing capability.

## Existing Foundation

ElectroBoy already registers a `mind_map` capability module. Its renderer
supports a canvas, edges, pan and zoom, node movement, branch expansion, and
saved view state. The service exposes read-only routes that obtain their data
from the active workflow's `MindMapProvider`.

The existing provider contract represents source traceability. It groups nodes
as sources, observations, provider events, and facts. Better Planned implements
that contract by projecting its workflow records into a graph. This remains a
valid provider-projection use case, but it is not a suitable persistent model
for a user-authored planning map.

The implementation separates two map modes behind a shared canvas:

```text
Mind Map canvas and interaction layer
  |
  +-- Editable map document
  |     loads and saves a versioned map file
  |     permits graph mutations
  |
  +-- Provider projection
        loads workflow-owned records
        permits only declared provider actions
```

## Design Principles

Planning should remain faster than formatting. A selected node exposes the
few operations needed to continue thinking, while less frequent actions stay
in the pane's context tools.

Spatial position carries meaning. Adding or editing a node must not cause the
whole map to move. New nodes receive sensible initial positions, and users can
request branch cleanup explicitly.

Nodes summarize ideas. Detailed prose belongs in linked Markdown documents,
which keeps the graph readable even when the plan grows.

Content state and viewing state are distinct. Node identities, hierarchy,
order, positions, and links belong in the map file. Selection, pan, zoom, and
temporary focus belong to per-connection or browser view state.

## User Interface

### Pane Integration

Mind Map is a reusable pane type available to both built-in workflows. Each
workflow may add a launcher or suggested default location. The pane and its
actions remain owned by the Mind Map module.

The pane context tools contain four sections.

| Section | Actions |
| --- | --- |
| File | New, Open, Save As |
| Node | Independent, Child, Sibling, Delete |
| Link | File, Web, Create Document |
| View | Zoom, Fit, Focus, Collapse All, Tidy Branch |

The toolbar favors icons where their meaning is established. Every icon has a
tooltip and accessible label.

### Node Creation

Double-clicking empty canvas space creates an independent root node at that
position. The node enters text-editing mode immediately.

Selecting one node reveals compact add controls beside it. One control creates
a child and the other creates a sibling. The controls disappear during text
editing, canvas movement, or multi-selection.

Keyboard operations provide the fastest creation path.

| Input | Operation |
| --- | --- |
| `Tab` | Add a child to the selected node |
| `Enter` | Add a sibling and begin editing it |
| `Shift+Enter` | Add an independent root near the selection |
| `F2` | Edit the selected node title |
| `Delete` | Delete the selected node or subtree |
| `Escape` | Finish editing or clear the selection |
| `Ctrl+Z` / `Cmd+Z` | Undo |
| `Ctrl+Shift+Z` / `Cmd+Shift+Z` | Redo |

The browser's operating-system convention determines whether `Ctrl` or `Cmd`
is shown in help text.

### Selection and Editing

A single click selects a node. Double-clicking the title or pressing `F2`
starts inline editing. Pressing `Enter` while editing accepts the title, while
`Shift+Enter` inserts a line break only if multiline titles are enabled in a
future format version.

Deletion of a leaf happens immediately and remains undoable. Deleting a node
with descendants presents a confirmation that includes the number of affected
nodes. An alternative command may promote the node's children instead of
deleting them.

### Moving and Reparenting

Dragging a node changes its durable position. Dragging it over another node
shows a clear attachment target. Dropping on that target reparents the node and
its descendants.

Dropping a branch on empty canvas detaches it and turns its top node into an
independent root. Reparenting cannot create a cycle. A rejected drop restores
the original position and gives a brief explanation.

New children and siblings are placed using a deterministic local layout. Their
creation does not recalculate unrelated branches. `Tidy Branch` arranges the
selected subtree while leaving the remainder of the map untouched.

### Infinite Canvas

The canvas uses a transformed world coordinate system rather than a fixed
document rectangle. Nodes store world coordinates. The renderer expands its
interactive bounds as content moves and does not impose a user-visible edge.

Pointer dragging on empty space pans the canvas. A wheel or trackpad gesture
zooms around the pointer location. `Fit` frames all visible nodes, while
`Center Selection` frames only the selected node or subtree.

Zoom has a practical renderer safety range rather than a font-size policy.
The controls accept direct numeric input in addition to increment and decrement
buttons, following ElectroBoy's other zoom controls.

### Branch Visibility

A branch control collapses or expands a node's descendants. A collapsed node
shows the number of hidden descendants. Collapse state is view state by
default, allowing two panes to inspect the same map differently.

Focus mode emphasizes one branch and fades the rest of the graph. It changes
visibility only and never alters hierarchy or positions.

## Links and Documents

### Link Types

A node may have zero or more links. The initial interface recognizes these
types:

- `file` points to a file and may include a heading or fragment.
- `url` points to an external web location.
- `document` identifies the primary Markdown document for the node.

Relative file paths are resolved from the map file's directory. Absolute paths
are supported through the same access policy used by the File pane. The UI
visually distinguishes project-relative, external-filesystem, and web links.

Selecting a link badge opens the target. Clicking the node body continues to
select or edit the planning node, preventing link navigation from interfering
with normal map manipulation.

### Create Linked Document

`Create Document` is a non-destructive operation. The planning node remains in
the graph and gains a primary document link.

The operation follows this sequence:

1. Choose or accept a suggested Markdown path.
2. Create the file with the node title as its initial level-one heading.
3. Save the document path on the node.
4. Show a document badge on the node.
5. Open the document in the document-peek overlay.

Software and creative workflows may suggest different directories. The module
accepts the suggestion through a narrow public interface and never imports a
workflow to determine the path.

The node title and document heading are independent after creation. Renaming
one does not silently rename or rewrite the other. A missing document produces
a broken-link indicator and repair action without removing the map node.

### Document-Peek Overlay

Internal files open in a right-side overlay so the map remains visible. The
overlay reuses the existing File pane renderer, editor, navigation history,
font controls, and link handling through a public document capability.

The overlay provides these actions:

- Preview or edit the document.
- Navigate backward and forward through followed document links.
- Open the document in the File pane.
- Pop the document into its own window.
- Close the overlay and return focus to the originating map node.

The overlay remembers the document and scroll location while it remains open.
Opening a document that already has a File pane buffer reuses that buffer's
underlying document identity rather than creating a duplicate buffer.

External URLs open in a browser tab by default. Many sites prohibit embedding
through content-security or frame restrictions, so external overlays cannot be
relied upon as a general navigation mechanism.

## Persistence Model

### File Format

Editable maps use files ending in `.mindmap.json`. The schema is versioned and
designed for readable diffs. Stable IDs preserve references across renames and
movement.

An illustrative document follows.

```json
{
  "schema_version": 1,
  "id": "release-plan",
  "title": "Release plan",
  "nodes": [
    {
      "id": "node-release",
      "title": "Release 1.0",
      "parent_id": null,
      "order": 0,
      "x": 120,
      "y": 160,
      "links": [
        {
          "id": "link-release-document",
          "type": "document",
          "target": "docs/release-1.0.md"
        }
      ]
    },
    {
      "id": "node-validation",
      "title": "Validation",
      "parent_id": "node-release",
      "order": 0,
      "x": 440,
      "y": 120,
      "links": []
    }
  ],
  "relationships": []
}
```

`parent_id` defines the branch hierarchy. Coordinates never determine
parentage. `order` establishes sibling ordering independently from vertical
position.

The `relationships` collection is reserved for explicit cross-branch links.
The initial UI may omit relationship creation while retaining forward schema
compatibility.

### View State

View state uses the Mind Map module's namespaced state. Its key includes the
browser connection and canonical map identity. It may contain pan, zoom,
selection, focus, collapsed branches, and transient overlay state.

Durable node positions stay in the map file because they express the author's
arrangement. Moving the viewport does not rewrite the file.

### Save Behavior

Graph mutations update an in-memory model and enter the undo history. The
client sends debounced saves after short editing bursts. The service writes a
validated complete document atomically through a temporary file and rename.

Every load returns a revision token derived from the file state. Saves include
the expected revision. A stale writer receives a conflict response rather than
overwriting changes from another pane or browser connection.

Closing a pane flushes pending changes when possible. Correctness does not rely
on unload callbacks because browsers may suspend or terminate a page without
running them.

### JSON Canvas Interchange

JSON Canvas provides a useful interchange format for spatial graphs. Its text,
file, link, group, and edge nodes map well to much of the ElectroBoy model.
Parent ordering and view semantics do not have direct equivalents.

Import and export can be added after the native schema stabilizes. Import
derives hierarchy from directed edges when unambiguous and leaves other nodes
independent. Export emits text, file, link, and edge records while preserving
the visible coordinates.

## Service Architecture

### Ownership

The reusable Mind Map module owns:

- Schema validation and migration.
- File loading and atomic saving.
- Editable-map routes.
- The shared canvas and interaction controller.
- Mind Map pane actions and namespaced state.
- The public adapter for provider projections.

The shared document capability owns rendering and editing linked files. Core
owns pane composition, connection identity, transport, and module discovery.
Workflows own launch placement and optional path suggestions.

Better Planned continues to own its relationship meanings, authorization, and
source data. It provides normalized graph data without importing private Mind
Map implementation details.

### Public Contracts

The module exposes a small editable-document service contract. Exact route
names follow the repository route registry, but the logical operations are:

| Method | Operation |
| --- | --- |
| `GET` | Load and validate a map document |
| `POST` | Create a map document |
| `PUT` | Save a complete map with a revision precondition |
| `POST` | Create and attach a linked Markdown document |

Node editing remains a client-side transaction until the next complete save.
This keeps the server API small and ensures undo can treat related changes as
one operation.

Provider projection remains a read contract. The renderer receives a
normalized generic graph plus declared capabilities. Mutation controls appear
only when the loaded source advertises editable-document capabilities.

### Dependency Direction

```text
workflow launcher
       |
       v
Mind Map public action API
       |
       +--> map storage service
       +--> shared canvas renderer
       +--> document public action API

Better Planned provider
       |
       v
Mind Map projection protocol
```

The Mind Map module does not import Better Planned, software-engineering, or
creative-writing packages. Frontend code receives runtime interfaces and does
not reach into private shell globals.

## Frontend Design

The shared canvas renderer is split into focused components.

```text
mind-map pane controller
  +-- map model and command history
  +-- selection controller
  +-- canvas transform controller
  +-- node and edge renderer
  +-- local branch layout
  +-- persistence adapter
  +-- document-link adapter
```

Every user mutation is represented as a reversible command. Compound actions,
such as reparenting and repositioning, produce one undo entry. Rendering is
scheduled once per animation frame and batches DOM updates to prevent pointer
movement from creating unbounded work.

Only visible nodes and a reasonable overscan region need full DOM content on a
large map. Edges may remain in one SVG layer. Virtualization becomes necessary
only after measured node counts demonstrate a rendering limit.

## Error Handling

Malformed map files open in a non-editable error view that identifies the
invalid field. The original file remains unchanged.

Failed saves leave the local model and undo history intact. The pane displays a
persistent unsaved indicator with retry and save-as options. Revision conflicts
offer reload and save-copy actions rather than silently choosing a version.

Document creation is transactional from the user's perspective. If the file is
created but attaching its link fails, the result reports the created path and
offers a retry. Existing files are never overwritten without confirmation.

## Accessibility

All canvas actions have keyboard equivalents. Selection remains visible at all
zoom levels, and focus is restored after overlays close. Nodes expose their
title, hierarchy level, expansion state, and link badges to assistive
technology.

Arrow keys move selection between nearby nodes. An optional outline view may
provide a linear representation in a later phase if canvas navigation remains
difficult for screen-reader users.

## Security

File and document links pass through the existing ElectroBoy file-access and
rendering paths. User-provided titles and link labels are escaped before DOM
insertion. URLs accept supported schemes only and external navigation uses
safe opener behavior.

The service validates every loaded or saved path. A workflow path suggestion
is advisory and does not grant additional filesystem access.

## Delivery Phases

### Phase 1 — Editable Planning Maps

- Create and open `.mindmap.json` files.
- Add independent, child, and sibling nodes.
- Rename, move, reparent, detach, and delete nodes.
- Pan, zoom, fit, collapse, undo, and redo.
- Persist hierarchy, order, and positions safely.
- Expose the pane in software and creative workflows.

### Phase 2 — Documents and Links

- Attach files and web URLs.
- Create a linked Markdown document.
- Preview and edit internal files in the document-peek overlay.
- Reuse File pane buffers and navigation behavior.
- Report and repair broken links.

### Phase 3 — Planning Scale

- Add focus mode and search.
- Add explicit cross-branch relationships.
- Add a small color and tag vocabulary.
- Export PNG, SVG, and a Markdown outline.
- Import and export JSON Canvas where conversion is lossless enough.

## Testing Strategy

Service tests cover schema validation, migration, path handling, atomic saves,
revision conflicts, and linked-document creation. Module tests confirm that a
core-only installation loads without either workflow package.

Browser tests cover node creation shortcuts, pointer creation, inline editing,
dragging, reparenting, cycle rejection, collapse counts, undo and redo, pan and
zoom stability, save conflicts, and document overlay behavior.

Composition tests run the software and creative workflows independently. A
Better Planned test verifies that provider projections remain read-only and
render through the shared canvas without exposing editable controls.

Performance tests construct representative maps with hundreds and thousands
of nodes. They measure initial rendering, pointer responsiveness, save payload
size, and whether hidden or off-screen branches create unnecessary DOM work.

## Acceptance Criteria

- A user can create a useful plan without opening a menu after the first node.
- Independent clusters and hierarchical branches coexist on one canvas.
- Editing one branch does not unexpectedly reposition another branch.
- A node can create and reopen a Markdown document without losing map context.
- Pending edits survive ordinary pane switches and report failed saves clearly.
- Two open views cannot silently overwrite one another.
- The same Mind Map module works in software and creative workflows.
- Better Planned continues to supply its graph through a provider boundary.
- Optional workflows are absent from core and module imports.

## Open Questions

- Should collapse state remain entirely per view, or can users save a preferred
  collapsed presentation in the map file?
- Should the initial release support one primary document plus several links,
  or present every link uniformly?
- Which directories should each workflow suggest for new map and document
  files?
- Should deleting a parent default to deleting its subtree or promoting its
  children?
- At what measured map size should the renderer enable node virtualization?
