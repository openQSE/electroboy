# Corkboard Provider API

ElectroBoy's corkboard module renders normalized board snapshots. Workflows own
the source of truth and expose it through `CorkboardProvider`; the shared module
does not read workflow files or databases directly.

Plugin authors can import the stable contracts from:

```python
from electroboy.service.plugin_api import (
    CorkboardProvider,
    normalize_board_snapshot,
)
```

## Provider contract

A workflow controller that supports corkboards implements
`get_corkboard_provider()` and returns an object with these operations:

```python
class FamilyWorkflowController:
    def get_corkboard_provider(self) -> CorkboardProvider:
        return self.family_corkboards
```

- `get_board(context_id, board_id, title=None)` returns a normalized snapshot.
- `apply_operation(context_id, payload)` applies a card or board mutation.
- `create_board(context_id, board_id)` creates a board when the provider allows
  user-created boards.

Providers should call `normalize_board_snapshot()` before returning. It adds
the stable provider and board identifiers, validates the board shape, and gives
every card a stable ID.

Renderer mutations use provider-neutral action names:

- `update-card`, with `board_id`, `board_type`, and `card`
- `delete-card`, with `board_id` and `card_id`
- `reorder-cards`, with `board_id` and an ordered list of card IDs
- `rename-board`, with `board_id` and `title`

The provider translates those operations into its own filesystem commands or
database transactions.

## Board snapshot

```json
{
  "schema_version": 1,
  "provider": "better-planned-family",
  "board_id": "member:184",
  "board_type": "freeform",
  "title": "Ari",
  "capabilities": ["open-card"],
  "cards": [
    {
      "id": "activity:991",
      "title": "Soccer practice",
      "note": "Bring the blue uniform.",
      "x": 120,
      "y": 80,
      "rotation": 0,
      "color": "sky",
      "target": {
        "type": "better-planned-entry",
        "id": "991"
      },
      "metadata": {
        "people": ["Ari"],
        "deadline": "2026-08-20",
        "status": "needs-review"
      }
    }
  ]
}
```

`target` and `metadata` are provider-owned values. The shared renderer displays
metadata and sends the opaque target to the active workflow when a user opens a
card. The workflow decides which pane or record view to open.

Supported capability names are:

- `open-card`
- `create-card`
- `edit-card`
- `delete-card`
- `move-card`
- `reorder-card`
- `change-color`
- `group-card`
- `rename-board`

If a provider supplies a non-empty capability list, the renderer hides or
disables unsupported mutations. This permits database projections to begin as
read-only boards.

## Shared routes

The active workflow provider is served through:

```text
GET  /artifacts/corkboard?provider=<id>&board_id=<id>&context_id=<id>
GET  /api/corkboard?provider=<id>&board_id=<id>&context_id=<id>
POST /api/corkboard?context_id=<id>
POST /api/corkboards?context_id=<id>
```

The provider parameter must match the provider exposed by the active workflow.
Board IDs are opaque to ElectroBoy. Database providers should use stable domain
identifiers and perform authorization inside every provider operation.

The old `/artifacts/creative-corkboard` and `/api/creative/corkboard` routes
remain compatibility aliases. New workflows should only use the generic routes.

## Creative Writing

Creative Writing provides `creative-files`. It maps folders and
`.corkboard.json` files into snapshots while keeping its existing files and
`.electroboy/creative/corkboards.json` metadata authoritative. No creative
files are copied into the generic module.

## Database providers

A database-backed workflow should query and mutate its own database inside the
provider. ElectroBoy must not create corkboard files as a cache or second source
of truth. Providers should use transactions, authorize against the active
workflow context, and use revision checks when concurrent updates are possible.
