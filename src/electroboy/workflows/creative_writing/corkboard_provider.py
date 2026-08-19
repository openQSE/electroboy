"""File-backed corkboard provider for the creative-writing workflow."""

from __future__ import annotations

from electroboy.modules.creative_workspace import (
    _create_creative_corkboard,
    _creative_corkboard_payload,
    save_creative_corkboard,
)
from electroboy.service.corkboard import normalize_board_snapshot
from electroboy.service.services import ServiceServices


class CreativeWritingCorkboardProvider:
    """Expose creative folders and ``.corkboard.json`` files as boards."""

    provider_id = "creative-files"

    def __init__(self, services: ServiceServices) -> None:
        self.services = services

    def list_boards(
        self,
        context_id: str,
        *,
        connection_id: str = "",
    ) -> list[dict[str, object]]:
        root = self.services.contexts.active_project_root(context_id)
        boards: list[dict[str, object]] = []
        for path in sorted(root.rglob("*.corkboard.json")):
            if ".electroboy" in path.parts or not path.is_file():
                continue
            board_id = path.relative_to(root).as_posix()
            snapshot = self.get_board(context_id, board_id)
            boards.append(
                {
                    "board_id": board_id,
                    "title": snapshot["title"],
                    "provider": self.provider_id,
                }
            )
        return boards

    def get_board(
        self,
        context_id: str,
        board_id: str,
        *,
        title: str | None = None,
        connection_id: str = "",
    ) -> dict[str, object]:
        root = self.services.contexts.active_project_root(context_id)
        payload = _creative_corkboard_payload(
            root,
            board_id,
            title=title,
            context_id=context_id,
        )
        return normalize_board_snapshot(
            {
                **payload,
                "capabilities": [
                    "change-color",
                    "change-layout",
                    "create-card",
                    "delete-card",
                    "edit-card",
                    "group-card",
                    "move-card",
                    "open-card",
                    "rename-board",
                    "reorder-card",
                ],
            },
            provider_id=self.provider_id,
            board_id=board_id,
        )

    def apply_operation(
        self,
        context_id: str,
        payload: dict[str, object],
        *,
        connection_id: str = "",
    ) -> dict[str, object]:
        root = self.services.contexts.active_project_root(context_id)
        return save_creative_corkboard(
            root,
            self._creative_operation(payload),
        )

    def _creative_operation(
        self,
        payload: dict[str, object],
    ) -> dict[str, object]:
        """Translate provider-neutral operations into the legacy file API."""

        board_id = str(payload.get("board_id") or "").strip()
        action = str(payload.get("action") or "").strip()
        if not board_id or action not in {
            "change-layout",
            "delete-card",
            "rename-board",
            "reorder-cards",
            "update-card",
        }:
            return payload
        board_type = str(payload.get("board_type") or "freeform")
        if action == "change-layout":
            return {
                "board_type": "freeform",
                "action": "layout",
                "corkboard": board_id,
                "layout": payload.get("layout"),
            }
        if action == "rename-board":
            return {
                "board_type": "freeform",
                "action": "title",
                "corkboard": board_id,
                "title": payload.get("title"),
            }
        if action == "delete-card":
            return {
                "board_type": "freeform",
                "action": "delete",
                "corkboard": board_id,
                "card_id": payload.get("card_id"),
            }
        if action == "reorder-cards":
            return {
                "board_type": "folder",
                "folder": board_id,
                "order": payload.get("order"),
            }
        card = payload.get("card")
        if not isinstance(card, dict):
            return payload
        if board_type == "folder":
            return {
                "board_type": "folder",
                "folder": board_id,
                "path": card.get("path") or card.get("id"),
                "note": card.get("note"),
                "color": card.get("color"),
            }
        return {
            "board_type": "freeform",
            "corkboard": board_id,
            "card": card,
        }

    def create_board(
        self,
        context_id: str,
        board_id: str,
        *,
        title: str | None = None,
        connection_id: str = "",
    ) -> dict[str, object]:
        root = self.services.contexts.active_project_root(context_id)
        path = _create_creative_corkboard(root, board_id, title=title)
        return {"status": "created", "path": path, "board_id": path}
