"""Public provider contract for workflow-backed corkboards."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from electroboy.state_store import StateError


class CorkboardProvider(Protocol):
    """Translate a workflow data source into generic corkboard operations."""

    provider_id: str

    def get_board(
        self,
        context_id: str,
        board_id: str,
        *,
        title: str | None = None,
    ) -> dict[str, object]: ...

    def apply_operation(
        self,
        context_id: str,
        payload: dict[str, object],
    ) -> dict[str, object]: ...

    def create_board(
        self,
        context_id: str,
        board_id: str,
    ) -> dict[str, object]: ...


@runtime_checkable
class CorkboardWorkflowController(Protocol):
    """Structural controller capability consumed by the corkboard module."""

    def get_corkboard_provider(self) -> CorkboardProvider: ...


def normalize_board_snapshot(
    payload: dict[str, object],
    *,
    provider_id: str,
    board_id: str,
) -> dict[str, object]:
    """Validate and enrich the provider-neutral renderer payload."""

    board_type = str(payload.get("board_type") or "").strip()
    if board_type not in {"folder", "freeform"}:
        raise StateError(f"unknown corkboard type: {board_type or 'missing'}")
    cards = payload.get("cards")
    if not isinstance(cards, list):
        raise StateError("corkboard cards must be a list")
    normalized_cards: list[dict[str, object]] = []
    for index, card in enumerate(cards):
        if not isinstance(card, dict):
            raise StateError(f"corkboard card {index + 1} must be an object")
        card_id = str(
            card.get("id")
            or card.get("path")
            or card.get("name")
            or f"card-{index + 1}"
        ).strip()
        normalized_cards.append({**card, "id": card_id})
    title = str(payload.get("title") or "").strip()
    if not title:
        raise StateError("corkboard title is required")
    capabilities = payload.get("capabilities")
    if not isinstance(capabilities, list):
        capabilities = []
    normalized_ratio: float | None = None
    requested_ratio = payload.get("card_aspect_ratio")
    if requested_ratio is not None:
        try:
            normalized_ratio = float(requested_ratio)
        except (TypeError, ValueError) as error:
            raise StateError("corkboard card aspect ratio must be numeric") from error
        if not 0.25 <= normalized_ratio <= 4:
            raise StateError("corkboard card aspect ratio is out of range")
    return {
        **payload,
        "schema_version": 1,
        "provider": provider_id,
        "board_id": board_id,
        "title": title,
        "board_type": board_type,
        "cards": normalized_cards,
        "capabilities": [str(item) for item in capabilities],
        **(
            {"card_aspect_ratio": normalized_ratio}
            if normalized_ratio is not None
            else {}
        ),
    }
