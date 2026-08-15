"""Corkboard capability module declaration."""

from __future__ import annotations

from electroboy.service.registry import ServiceModule

from .common import route


def module() -> ServiceModule:
    return ServiceModule(
        id="corkboard",
        label="Corkboard",
        routes=(
            route("GET", "/artifacts/creative-corkboard", "corkboard", "view"),
            route("POST", "/api/creative/corkboard", "corkboard", "save"),
            route("POST", "/api/creative/corkboards", "corkboard", "create"),
        ),
        capabilities=frozenset({"folder-corkboard", "freeform-corkboard"}),
        state_namespace="corkboard",
    )

