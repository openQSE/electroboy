"""Presentation projections for trusted AI-authored course content."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping


class CoursePresentation:
    """Resolve internal learner IDs without changing persisted course data."""

    def __init__(
        self,
        components: Iterable[Mapping[str, object]],
        modules: Iterable[Mapping[str, object]],
    ) -> None:
        names: dict[str, str] = {}
        for records, id_field, name_field in (
            (components, "eb_comp_id", "ai_component_name"),
            (modules, "eb_module_id", "ai_module_name"),
        ):
            for record in records:
                identifier = str(record.get(id_field) or "")
                name = str(record.get(name_field) or "")
                if identifier and name:
                    names[identifier] = name
        self._names = names
        self._pattern = (
            re.compile(
                r"(?<![A-Za-z0-9_-])(" + "|".join(
                    re.escape(identifier)
                    for identifier in sorted(names, key=len, reverse=True)
                ) + r")(?![A-Za-z0-9_-])"
            )
            if names
            else None
        )

    def text(self, value: object) -> str:
        text = str(value or "")
        if self._pattern is None:
            return text
        return self._pattern.sub(lambda match: self._names[match.group(1)], text)
