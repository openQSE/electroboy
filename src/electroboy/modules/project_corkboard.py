"""Reusable project-backed corkboard provider."""

from __future__ import annotations

import re
from pathlib import Path

from electroboy.service.corkboard import normalize_board_snapshot
from electroboy.service.services import ServiceServices
from electroboy.state_store import StateError

from .creative_workspace import (
    CREATIVE_CORKBOARD_SUFFIX,
    _create_creative_corkboard,
    _creative_corkboard_payload,
    save_creative_corkboard,
)

PROJECT_CORKBOARD_DIRECTORY = Path(".electroboy") / "shared" / "corkboards"
PROJECT_CORKBOARD_PROVIDER = "project-files"


def _board_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project-board"


class ProjectCorkboardProvider:
    """Bind the shared corkboard implementation to an active project."""

    provider_id = PROJECT_CORKBOARD_PROVIDER

    def __init__(self, services: ServiceServices) -> None:
        self.services = services

    def _relative_board_path(self, board_id: str) -> str:
        raw = board_id.strip().replace("\\", "/")
        prefix = PROJECT_CORKBOARD_DIRECTORY.as_posix()
        if raw.startswith(f"{prefix}/"):
            candidate = Path(raw)
        else:
            name = raw.removesuffix(CREATIVE_CORKBOARD_SUFFIX)
            candidate = PROJECT_CORKBOARD_DIRECTORY / (
                f"{_board_slug(name)}{CREATIVE_CORKBOARD_SUFFIX}"
            )
        if (
            candidate.is_absolute()
            or any(part in {"", ".."} for part in candidate.parts)
            or candidate.parent != PROJECT_CORKBOARD_DIRECTORY
            or not candidate.name.endswith(CREATIVE_CORKBOARD_SUFFIX)
        ):
            raise StateError("invalid project corkboard id")
        return candidate.as_posix()

    def list_boards(
        self,
        context_id: str,
        *,
        connection_id: str = "",
    ) -> list[dict[str, object]]:
        root = self.services.contexts.active_project_root(context_id)
        directory = root / PROJECT_CORKBOARD_DIRECTORY
        if not directory.is_dir():
            return []
        boards: list[dict[str, object]] = []
        for path in sorted(directory.glob(f"*{CREATIVE_CORKBOARD_SUFFIX}")):
            board_id = path.relative_to(root).as_posix()
            snapshot = self.get_board(
                context_id,
                board_id,
                connection_id=connection_id,
            )
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
        normalized_id = self._relative_board_path(board_id)
        payload = _creative_corkboard_payload(
            root,
            normalized_id,
            title=title,
            context_id=context_id,
        )
        return normalize_board_snapshot(
            {
                **payload,
                "capabilities": [
                    "change-color",
                    "create-card",
                    "delete-card",
                    "edit-card",
                    "move-card",
                    "rename-board",
                ],
            },
            provider_id=self.provider_id,
            board_id=normalized_id,
        )

    def apply_operation(
        self,
        context_id: str,
        payload: dict[str, object],
        *,
        connection_id: str = "",
    ) -> dict[str, object]:
        root = self.services.contexts.active_project_root(context_id)
        board_id = self._relative_board_path(str(payload.get("board_id") or ""))
        action = str(payload.get("action") or "").strip()
        operation: dict[str, object] = {
            "board_type": "freeform",
            "corkboard": board_id,
        }
        if action == "rename-board":
            operation.update(action="title", title=payload.get("title"))
        elif action == "delete-card":
            operation.update(action="delete", card_id=payload.get("card_id"))
        elif action == "update-card":
            operation["card"] = payload.get("card")
        else:
            raise StateError(f"unsupported project corkboard action: {action}")
        return save_creative_corkboard(root, operation)

    def create_board(
        self,
        context_id: str,
        board_id: str,
        *,
        title: str | None = None,
        connection_id: str = "",
    ) -> dict[str, object]:
        root = self.services.contexts.active_project_root(context_id)
        normalized_id = self._relative_board_path(board_id or title or "")
        path = _create_creative_corkboard(root, normalized_id, title=title)
        return {
            "status": "created",
            "board_id": path,
            "path": path,
            "provider": self.provider_id,
            "title": title
            or Path(path).name.removesuffix(CREATIVE_CORKBOARD_SUFFIX),
        }
