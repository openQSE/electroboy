"""Single source for the Phase 3 component-candidate record contract."""

from __future__ import annotations

import json
from collections.abc import Mapping

COMPONENT_CONFIDENCE_VALUES = (
    "verified",
    "high",
    "medium",
    "low",
    "unknown",
)
COMPONENT_NAME_ORIGIN_VALUES = ("source_defined", "inferred")
COMPONENT_CANDIDATE_REQUIRED_FIELDS = (
    "schema_version",
    "record_type",
    "analysis_run_id",
    "repository_revision",
    "candidate_id",
    "name",
    "name_origin",
    "kind",
    "responsibility",
    "file_ids",
    "symbols",
    "owned_source_refs",
    "supporting_source_refs",
    "confidence",
    "limitations",
)
SOURCE_REFERENCE_REQUIRED_FIELDS = (
    "file_id",
    "start_line",
    "end_line",
    "reason",
)
SYMBOL_LOCATOR_REQUIRED_FIELDS = (
    "file_id",
    "name",
    "kind",
    "start_line",
    "end_line",
)


def component_candidate_example(
    *,
    analysis_run_id: str = "run-example",
    repository_revision: str = "revision-example",
    file_id: str = "file:src/example.c",
) -> dict[str, object]:
    """Return the canonical complete candidate shape shown to analysis agents."""

    return {
        "schema_version": 1,
        "record_type": "component_candidate",
        "analysis_run_id": analysis_run_id,
        "repository_revision": repository_revision,
        "candidate_id": "candidate-example",
        "name": "Source-defined component name",
        "name_origin": "source_defined",
        "kind": "subsystem",
        "responsibility": "Explains the source-backed responsibility.",
        "file_ids": [file_id],
        "symbols": [
            {
                "file_id": file_id,
                "name": "entry_point",
                "kind": "function",
                "scope": "",
                "language": "C",
                "signature": "(void)",
                "start_line": 1,
                "end_line": 1,
            }
        ],
        "owned_source_refs": [
            {
                "file_id": file_id,
                "start_line": 1,
                "end_line": 1,
                "reason": "Defines the component entry point.",
            }
        ],
        "supporting_source_refs": [],
        "confidence": "high",
        "limitations": [],
    }


def component_candidate_contract_text(
    *,
    analysis_run_id: str,
    repository_revision: str,
    example_file_id: str,
) -> str:
    """Render explicit agent-facing instructions from shared contract constants."""

    example = component_candidate_example(
        analysis_run_id=analysis_run_id,
        repository_revision=repository_revision,
        file_id=example_file_id,
    )
    confidence = ", ".join(f"`{value}`" for value in COMPONENT_CONFIDENCE_VALUES)
    origins = ", ".join(f"`{value}`" for value in COMPONENT_NAME_ORIGIN_VALUES)
    required_fields = ", ".join(COMPONENT_CANDIDATE_REQUIRED_FIELDS)
    return f"""Component candidate record contract:
- Every record must contain all of these fields: {required_fields}.
- `name_origin` must be one of: {origins}.
- `confidence` must be one of: {confidence}. Do not use a numeric score.
- `symbols` is an array of source-oriented symbol locators. Every locator has
  `file_id`, `name`, `kind`, positive inclusive `start_line`, and positive
  inclusive `end_line`; `scope`, `language`, and `signature` are optional.
- `owned_source_refs` must contain at least one source reference.
- `supporting_source_refs` is required but may be an empty array.
- Every owned or supporting source reference has exactly the same required
  shape: `file_id`, positive inclusive `start_line`, positive inclusive
  `end_line`, and non-empty `reason`. Use `reason`, never `role`.
- `limitations` is an array of strings and may be empty.

Valid complete record-shape example (replace the example semantics and ranges
with evidence from the repository):
{json.dumps(example, indent=2, sort_keys=True)}"""


def validate_component_schema_alignment(schema: Mapping[str, object]) -> None:
    """Fail when the packaged JSON Schema drifts from runtime contract constants."""

    definitions = schema.get("$defs")
    if not isinstance(definitions, Mapping):
        raise RuntimeError("Phase 3 schema has no $defs object")
    header = _object_contract(definitions, "header")
    candidate = _composed_contract(definitions, "component_candidate")
    source_reference = _object_contract(definitions, "source_reference")
    symbol_locator = _object_contract(definitions, "symbol_locator")

    required = set(_string_array(header, "required")) | set(
        _string_array(candidate, "required")
    )
    expected = set(COMPONENT_CANDIDATE_REQUIRED_FIELDS)
    if required != expected:
        raise RuntimeError(
            "component_candidate schema required fields do not match runtime "
            f"contract: expected {sorted(expected)}, found {sorted(required)}"
        )
    _require_fields(
        source_reference,
        "source_reference",
        SOURCE_REFERENCE_REQUIRED_FIELDS,
    )
    _require_fields(
        symbol_locator,
        "symbol_locator",
        SYMBOL_LOCATOR_REQUIRED_FIELDS,
    )
    _require_enum(
        candidate,
        "confidence",
        COMPONENT_CONFIDENCE_VALUES,
    )
    _require_enum(
        candidate,
        "name_origin",
        COMPONENT_NAME_ORIGIN_VALUES,
    )


def _composed_contract(
    definitions: Mapping[str, object], name: str
) -> Mapping[str, object]:
    definition = definitions.get(name)
    if not isinstance(definition, Mapping):
        raise RuntimeError(f"Phase 3 schema has no {name} definition")
    parts = definition.get("allOf")
    if not isinstance(parts, list):
        raise RuntimeError(f"Phase 3 schema {name} definition has no allOf array")
    for part in parts:
        if isinstance(part, Mapping) and part.get("type") == "object":
            return part
    raise RuntimeError(f"Phase 3 schema {name} has no object contract")


def _object_contract(
    definitions: Mapping[str, object], name: str
) -> Mapping[str, object]:
    definition = definitions.get(name)
    if not isinstance(definition, Mapping) or definition.get("type") != "object":
        raise RuntimeError(f"Phase 3 schema has no object definition for {name}")
    return definition


def _string_array(contract: Mapping[str, object], field: str) -> list[str]:
    values = contract.get(field)
    if not isinstance(values, list) or any(
        not isinstance(value, str) for value in values
    ):
        raise RuntimeError(f"Phase 3 schema {field} must be an array of strings")
    return values


def _require_fields(
    contract: Mapping[str, object], name: str, expected: tuple[str, ...]
) -> None:
    actual = set(_string_array(contract, "required"))
    if actual != set(expected):
        raise RuntimeError(
            f"{name} schema required fields do not match runtime contract: "
            f"expected {sorted(expected)}, found {sorted(actual)}"
        )


def _require_enum(
    contract: Mapping[str, object], field: str, expected: tuple[str, ...]
) -> None:
    properties = contract.get("properties")
    property_schema = properties.get(field) if isinstance(properties, Mapping) else None
    values = (
        property_schema.get("enum")
        if isinstance(property_schema, Mapping)
        else None
    )
    if not isinstance(values, list) or set(values) != set(expected):
        raise RuntimeError(
            f"component_candidate {field} enum does not match runtime contract"
        )
