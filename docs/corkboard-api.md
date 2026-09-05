# Corkboard API

This document is the operating guide for agents that need to manage
ElectroBoy creative-writing corkboards.

Use the `electroboy corkboard ...` commands for corkboard changes. Do not edit
`.corkboard.json` files or `.electroboy/creative/corkboards.json` directly
unless the writer explicitly asks for raw file editing.

## Board Types

ElectroBoy supports two corkboard types.

### Freeform Corkboards

Freeform corkboards are JSON files ending in `.corkboard.json`.

Each board stores a user-facing `title` independently from its file path. The
path is the stable internal identity; changing the title does not rename the
file or change its `.corkboard.json` type.

Use them for arbitrary idea cards with x/y positions:

```bash
electroboy corkboard create corkboard/ideas.corkboard.json
electroboy corkboard show corkboard/ideas.corkboard.json
```

Each card has:

```json
{
  "id": "opening-beat",
  "title": "Opening beat",
  "note": "Start with a quiet contradiction.",
  "x": 188,
  "y": 144,
  "rotation": -1,
  "color": "butter",
  "width": 360,
  "height": 240,
  "card_type": "card"
}
```

`width` and `height` are optional board-coordinate dimensions. When omitted,
the viewer's board-wide card-size setting is used.

Freeform boards may also contain connectors. Connector anchors are relative to
card edges, so they continue to follow cards when cards move or resize:

```json
{
  "id": "opening-to-discovery",
  "source": {"card_id": "opening-beat", "side": "right", "offset": 0.5},
  "target": {"card_id": "discovery", "side": "left", "offset": 0.5},
  "color": "#ead8b0",
  "thickness": 3,
  "curve": 0.18,
  "style": "string",
  "label": "causes"
}
```

Connector sides may be `auto`, `top`, `right`, `bottom`, or `left`. Styles may
be `string`, `line`, or `dashed`.

The `color` field may be one of the built-in palette ids (`butter`, `rose`,
`sky`, `mint`, `lilac`, `peach`, or `slate`) or a six-digit hex color. Prefer
palette ids unless the writer asks for a specific custom color.

Cards may also be converted into groups. A group card references a separate
freeform corkboard file instead of embedding its child cards:

```json
{
  "id": "opening-scene",
  "title": "Opening scene",
  "note": "Break the scene into beats.",
  "card_type": "group",
  "board_path": "corkboard/groups/ideas/opening-scene.corkboard.json"
}
```

The child board initially inherits the group card's title. Multiple groups may
have the same visible title because their `board_path` values remain unique.
Internal group-board files are hidden from the Binder and should be renamed by
editing the title in the corkboard toolbar, not by renaming the JSON file.

### Folder Corkboards

Folder corkboards are generated from the child files and folders in a
directory. Adding, deleting, or renaming cards means adding, deleting, or
renaming files or folders. Only card notes, card colors, and display order are
corkboard metadata.

Use folder corkboards for chapter or scene ordering:

```bash
electroboy corkboard show chapters
```

## Freeform Commands

Create a corkboard:

```bash
electroboy corkboard create corkboard/ideas.corkboard.json
```

List known freeform corkboard files:

```bash
electroboy corkboard list
```

Show a corkboard as JSON:

```bash
electroboy corkboard show corkboard/ideas.corkboard.json
```

Add a card:

```bash
electroboy corkboard card add corkboard/ideas.corkboard.json \
  --title "Opening beat" \
  --note "The character notices something is wrong." \
  --x 120 \
  --y 180
```

Add a card with a stable id:

```bash
electroboy corkboard card add corkboard/ideas.corkboard.json \
  --id opening-beat \
  --title "Opening beat"
```

Update card text:

```bash
electroboy corkboard card update corkboard/ideas.corkboard.json opening-beat \
  --title "Opening image" \
  --note "Make the contradiction visible in the first paragraph."
```

Move a card:

```bash
electroboy corkboard card move corkboard/ideas.corkboard.json opening-beat \
  --x 300 \
  --y 220
```

Style a card:

```bash
electroboy corkboard card style corkboard/ideas.corkboard.json opening-beat \
  --color butter \
  --rotation -2
```

Resize a card:

```bash
electroboy corkboard card resize corkboard/ideas.corkboard.json opening-beat \
  --width 420 --height 260
```

Convert a card into a nested group corkboard:

```bash
electroboy corkboard card group corkboard/ideas.corkboard.json opening-scene
```

Optionally choose the child corkboard file:

```bash
electroboy corkboard card group corkboard/ideas.corkboard.json opening-scene \
  --board-path corkboard/scenes/opening-scene.corkboard.json
```

Delete a card:

```bash
electroboy corkboard card delete corkboard/ideas.corkboard.json opening-beat
```

Connect two cards:

```bash
electroboy corkboard connector add corkboard/ideas.corkboard.json \
  opening-beat discovery \
  --source-side right --target-side left \
  --label "leads to"
```

Delete a connector:

```bash
electroboy corkboard connector delete corkboard/ideas.corkboard.json \
  opening-beat-to-discovery
```

Deleting a card also removes every connector attached to that card.

## HTTP Operations

The generic HTTP API uses the active workflow's corkboard provider. Clients
must include the active `context_id` query parameter.

- `GET /api/corkboards`: list boards.
- `POST /api/corkboards`: create a board from `board_id` and optional `title`.
- `GET /api/corkboard?board_id=...`: retrieve cards and connectors.
- `POST /api/corkboard`: apply an operation.

Create or partially update a card with `action: "create-card"`,
`action: "update-card"`, or `action: "patch-card"` and a `card` object. Delete one with
`action: "delete-card"` and `card_id`.

Create or update a connector with `action: "create-connector"` or
`action: "update-connector"` and a `connector` object. Delete one with
`action: "delete-connector"` and `connector_id`.

```json
{
  "provider": "creative-files",
  "board_id": "corkboard/ideas.corkboard.json",
  "board_type": "freeform",
  "action": "create-connector",
  "connector": {
    "id": "opening-to-discovery",
    "source": {"card_id": "opening-beat", "side": "right", "offset": 0.5},
    "target": {"card_id": "discovery", "side": "left", "offset": 0.5}
  }
}
```

## Direct Manipulation

- Left-drag from the left, right, or bottom interaction border to another card
  to create a connector. The top edge remains a card-dragging surface.
- Right-drag across one or more connector strings to cut them. The red dashed
  line is temporary; intersected connectors are removed when the button is
  released.

## Folder Commands

Show a folder board as JSON:

```bash
electroboy corkboard show chapters
```

Set a note on a folder-backed card:

```bash
electroboy corkboard folder note chapters chapter-01.md \
  --note "Needs a sharper final turn." \
  --color sky
```

Set display order:

```bash
electroboy corkboard folder reorder chapters \
  --order chapter-02.md chapter-01.md chapter-03.md
```

Comma-separated order is also accepted:

```bash
electroboy corkboard folder reorder chapters \
  --order chapter-02.md,chapter-01.md,chapter-03.md
```

Any omitted visible child files or folders are appended after the requested
order.

## Agent Rules

When the active target is a freeform corkboard:

- Use `electroboy corkboard card ...` commands for card changes.
- When asked to build a board from a writeup, read the requested source,
  create one stable card id per scene or beat, arrange the cards in reading
  order, and use connectors for explicit narrative relationships.
- Use `electroboy corkboard connector ...` for relationships between cards.
- Use `electroboy corkboard card resize ...` only when the writer requests
  emphasis or a specific card size.
- Use `electroboy corkboard card group ...` when a card should become a
  nested corkboard. Do not manually embed child cards in the parent card.
- Use `electroboy corkboard show ...` before making edits if the current card
  state is unknown.
- Preserve existing card ids when updating, moving, styling, or deleting.
- Deleting a group card removes the parent-board reference only. It does not
  delete the child corkboard file unless the writer explicitly asks.

When the active target is a folder corkboard:

- Use `electroboy corkboard folder note ...` for card notes.
- Use `electroboy corkboard folder note ... --color <palette-id>` for card
  colors.
- Use `electroboy corkboard folder reorder ...` for visual order.
- Create, delete, or rename files and folders only when the writer asks.

After changing a corkboard, briefly report what changed.
