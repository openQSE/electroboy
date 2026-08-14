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
  "card_type": "card"
}
```

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
