# ElectroBoy Mind Map Detailed Design

## Purpose

The Mind Map capability provides a lightweight planning surface for the
software-engineering and creative-writing workflows. Users can build a graph
manually, arrange ideas on an unbounded canvas, and connect planning nodes to
supporting project files. Node content may be as short or as long as the plan
requires.

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
- Accept arbitrarily long node text without truncating stored content.
- Offer compact and expanded node presentation for large maps.
- Link nodes to project files, arbitrary filesystem files, and web URLs.
- Create a Markdown document from a node and edit it without leaving the map.
- Preview every file format supported by ElectroBoy, including text and images.
- Store maps in portable, versioned files suitable for source control.
- Reuse one renderer for editable maps and provider-backed projections.
- Keep the module independent of software and creative workflow policy.

## Non-Goals

The initial capability does not provide real-time collaboration, comments,
presentation mode, task scheduling, or a large template gallery. Rich text,
arbitrary shapes, image attachments, AI-generated maps, and several competing
layout engines are outside the initial scope.

Mind Map is its own selectable pane. It owns the canvas, map interaction, and
linked-content overlay. The overlay delegates file rendering and editing to
the existing ElectroBoy file capabilities so supported formats behave
consistently in both panes.

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

The generic Mind Map capability remains the shared base for both uses. The
ElectroBoy editable map inherits its graph and canvas behavior from that base,
then adds file persistence and mutation commands. Better Planned continues to
use the provider projection without depending on editable-map code.

```text
Generic Mind Map capability
  shared graph model, canvas, layout, pan, zoom, and relationship modes
  |
  +-- Provider projection
  |     loads workflow-owned records
  |     permits only declared provider actions
  |     used by Better Planned
  |
  +-- ElectroBoy editable-map extension
        loads and saves a versioned map file
        adds node and link mutation commands
        used by software and creative workflows
```

## Design Principles

Planning should remain faster than formatting. Keyboard shortcuts perform the
common node operations, while the pane's context tools provide the same
commands for pointer use.

Spatial position carries meaning. Adding or editing a node must not cause the
whole map to move. New nodes receive sensible initial positions, and users can
request branch cleanup explicitly.

Node input has no content-length limit. Compact presentation keeps a large map
readable, while in-place expansion shows the complete node text. Linked files
remain useful for material that benefits from a dedicated renderer or editor.

The map file stores information that defines the map and must survive wherever
the file is opened. This includes node text, parent and child relationships,
sibling order, node positions, and links. Temporary details about the current
screen stay with that browser view. Examples include which node is focused,
the current pan and zoom, and which nodes are temporarily expanded. Moving the
camera therefore does not create a source-control change, while moving a node
does.

## User Interface

### Pane Integration

Mind Map is a reusable, selectable pane type available to both built-in
workflows. The left navigation places a `Mind Map` entry directly below
`Corkboard`. Its actions open an existing map or create a new map. Opening or
creating a map selects a Mind Map pane and loads that map into it.

Each workflow may supply a suggested default location. The pane, actions, and
storage behavior remain owned by the Mind Map module.

The pane context tools mirror the keyboard commands. They provide a discoverable
path to every operation without adding controls around the selected node.

| Section | Actions |
| --- | --- |
| File | New, Open, Save As |
| Edit | Undo, Redo |
| Node | Independent, Child, Sibling, Edit, Delete |
| Link | File, Web, Create Document, Remove Link |
| View | Compact or expanded nodes, Zoom, Fit, Focus, Collapse All, Tidy Branch |

The toolbar favors icons where their meaning is established. Every icon has a
tooltip and accessible label.

### Node Creation

Double-clicking empty canvas space creates an independent root node at that
position. The node enters text-editing mode immediately.

Node creation is keyboard-driven. Selecting a node does not display a floating
toolbar or add buttons around it. Context-tool actions provide the equivalent
pointer-accessible operations without crowding the map.

| Input | Operation |
| --- | --- |
| `Tab` | Add a child to the selected node |
| `Enter` | Add a sibling and begin editing it |
| `Shift+Enter` | Add an independent root near the selection |
| `F2` | Edit the selected node text |
| `Delete` | Delete the selected node or subtree |
| `Escape` | Finish editing or clear the selection |
| `Ctrl+Z` / `Cmd+Z` | Undo |
| `Ctrl+Shift+Z` / `Cmd+Shift+Z` | Redo |

The browser's operating-system convention determines whether `Ctrl` or `Cmd`
is shown in help text.

### Selection and Editing

A primary-button click gives a node focus. The focused node uses a distinctive
high-contrast border and background treatment, supplemented by an outline or
shadow so focus is not communicated by color alone. `Tab` and `Enter` create a
child or sibling only while a node has focus and text editing is inactive.

Double-clicking the text or pressing `F2` starts inline editing. Pressing
`Enter` while editing accepts the content. `Shift+Enter` inserts a line break
while editing; it creates an independent root only when editing is inactive.

Node text is stored without a length limit. Compact mode displays approximately
80 characters, wrapping them within the compact node width. Longer content is
line-clamped and ends with an `… more` control. Activating it expands the node
in place and increases its height until the complete wrapped text is visible.
An `… less` control returns the node to compact presentation.

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

Holding the middle mouse button and dragging pans the canvas. Panning works
over nodes, edges, and empty space, and it never moves or selects the item under
the pointer. A primary-button drag moves a node.

The mouse wheel zooms around the pointer location. `Fit` frames all visible
nodes, while `Center Selection` frames only the focused node or subtree.

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

A node may have zero or more links. The interface recognizes these types:

- `file` points to any format supported by ElectroBoy and may include a heading
  or fragment where that format supports navigation.
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
2. Derive an editable initial heading from the first non-empty line of node
   text and create the file.
3. Save the document path on the node.
4. Show a document badge on the node.
5. Open the document in the linked-content overlay.

Software and creative workflows may suggest different directories. The module
accepts the suggestion through a narrow public interface and never imports a
workflow to determine the path.

The node text and document heading are independent after creation. Editing one
does not silently rename or rewrite the other. A missing document produces a
broken-link indicator and repair action without removing the map node.

### Linked-Content Overlay

Internal files open in a right-side overlay so the map remains visible. The
overlay supports the file formats already handled by ElectroBoy, including
Markdown, plain text, JPEG, PNG, PDF, and DOCX. Each format uses its established
renderer. Editing controls appear only for formats with editing support.

The overlay reuses File pane navigation history, font controls, and link
handling through public file and document capabilities.

The overlay provides these actions:

- Preview the linked file and edit it when its format supports editing.
- Navigate backward and forward through followed links.
- Open the file in the File pane.
- Pop the file into its own window.
- Close the overlay and return focus to the originating map node.

The overlay remembers the file and scroll location while it remains open.
Opening a file that already has a File pane buffer reuses that buffer's
underlying file identity rather than creating a duplicate buffer.

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
      "text": "Release 1.0",
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
      "text": "Validation",
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

### Map Data and Browser View

The `.mindmap.json` file contains the shared map. It records node text,
hierarchy, sibling order, durable positions, and links. Arbitrarily long node
text is stored in full regardless of whether the node is compact or expanded
on screen.

The Mind Map module separately records how one browser is looking at the map.
This browser-view record includes pan, zoom, focused node, compact or expanded
nodes, collapsed branches, and transient overlay state. Its key includes the
browser connection and canonical map identity.

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

The generic Mind Map capability owns:

- The normalized graph contract used by provider projections.
- Shared node and edge rendering.
- Canvas layout, middle-button pan, wheel zoom, and relationship modes.
- Read-only provider actions and capability declarations.

The ElectroBoy editable-map extension owns:

- Schema validation and migration.
- File loading and atomic saving.
- Editable-map routes.
- Mutation commands and undo history.
- Compact and expanded node presentation.
- Mind Map pane actions and namespaced state.

Shared file and document capabilities own rendering and editing linked files.
Core owns pane composition, connection identity, transport, and module
discovery. Workflows own launch placement and optional path suggestions.

Better Planned continues to own its relationship meanings, authorization, and
source data. It provides normalized graph data to the generic Mind Map
capability and does not import the editable extension. Existing clean and full
relationship modes retain their behavior.

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

Provider projection remains a read contract. The generic renderer receives a
normalized graph plus declared capabilities. The editable extension activates
mutation controls only for a file-backed ElectroBoy map. Provider-backed maps
therefore cannot accidentally expose save or node-mutation operations.

### Dependency Direction

```text
workflow launcher
       |
       v
ElectroBoy editable Mind Map API
       |
       +--> generic Mind Map capability
       +--> map storage service
       +--> file and document public action APIs

Better Planned provider
       |
       v
Generic Mind Map projection protocol
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
text, hierarchy level, expansion state, and link badges to assistive
technology.

Arrow keys move selection between nearby nodes. An optional outline view may
provide a linear representation in a later phase if canvas navigation remains
difficult for screen-reader users.

## Security

File and document links pass through the existing ElectroBoy file-access and
rendering paths. User-provided node text and link labels are escaped before DOM
insertion. URLs accept supported schemes only and external navigation uses
safe opener behavior.

The service validates every loaded or saved path. A workflow path suggestion
is advisory and does not grant additional filesystem access.

## Delivery Phases

### Phase 1 — Editable Planning Maps

- Create and open `.mindmap.json` files.
- Add independent, child, and sibling nodes.
- Rename, move, reparent, detach, and delete nodes.
- Support arbitrarily long node text with compact and expanded presentation.
- Pan with middle-button drag and zoom with the wheel.
- Fit, collapse, focus, undo, and redo.
- Persist hierarchy, order, and positions safely.
- Add Open and New under Mind Map below Corkboard in the left navigation.
- Expose Mind Map as a selectable pane in software and creative workflows.

### Phase 2 — Documents and Links

- Attach supported files and web URLs.
- Create a linked Markdown document.
- Preview Markdown, text, image, PDF, and DOCX files in the content overlay.
- Edit linked files where the existing file capability supports editing.
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
focused-node styling, long text, compact expansion, dragging, reparenting,
cycle rejection, collapse counts, undo and redo. They also verify
middle-button panning from every canvas target, wheel zoom stability, save
conflicts, and linked-content overlay behavior.

Composition tests run the software and creative workflows independently. A
Better Planned test verifies that provider projections remain read-only and
render through the shared canvas without exposing editable controls. It also
protects Better Planned clean and full relationship modes from regressions.

Performance tests construct representative maps with hundreds and thousands
of nodes. They measure initial rendering, pointer responsiveness, save payload
size, and whether hidden or off-screen branches create unnecessary DOM work.

## Acceptance Criteria

- A user can create a useful plan without opening a menu after the first node.
- A focused node has an unmistakable visual treatment.
- `Tab` and `Enter` create a child and sibling without displaying node controls.
- Middle-button dragging pans from any point and wheel movement zooms the map.
- Independent clusters and hierarchical branches coexist on one canvas.
- Editing one branch does not unexpectedly reposition another branch.
- Node input has no content-length limit and can expand to show all text.
- A node can preview supported files without losing map context.
- The left navigation can open or create a map below the Corkboard entry.
- Pending edits survive ordinary pane switches and report failed saves clearly.
- Two open views cannot silently overwrite one another.
- The same Mind Map module works in software and creative workflows.
- Better Planned continues to supply its graph through the unchanged generic
  provider boundary and retains both relationship modes.
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
