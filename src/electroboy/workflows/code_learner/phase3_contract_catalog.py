"""Shared structural contracts for AI-authored Phase 3 records."""

from __future__ import annotations

from collections.abc import Mapping

RECONCILIATION_REQUIRED_FIELDS = (
    "schema_version",
    "record_type",
    "repository_revision",
    "analysis_run_id",
    "overlap_group_id",
    "decision",
    "partitions",
    "reason",
    "limitations",
)
RECONCILIATION_PARTITION_REQUIRED_FIELDS = ("candidate_ids", "reason")

MODULE_REQUIRED_FIELDS = (
    "schema_version",
    "record_type",
    "repository_revision",
    "id",
    "name",
    "kind",
    "purpose",
    "responsibility",
    "component_ids",
    "primary_component_ids",
    "entry_component_ids",
    "primary_for_component_ids",
    "grouping_rationale",
    "source_refs",
    "confidence",
    "limitations",
)

MODULE_RELATIONSHIP_REQUIRED_FIELDS = (
    "schema_version",
    "record_type",
    "repository_revision",
    "id",
    "from_module_id",
    "to_module_id",
    "kind",
    "summary",
    "direction",
    "condition",
    "confidence",
    "supporting_component_ids",
    "source_refs",
    "limitations",
)
RELATIONSHIP_DIRECTION_VALUES = ("directed", "bidirectional")
EVIDENCE_CONFIDENCE_VALUES = ("verified", "high", "medium", "low", "unknown")

ARCHITECTURE_HORIZONTAL_FIELDS = (
    "repository_purpose",
    "external_boundaries",
    "entry_surfaces",
    "modules",
    "relationships",
    "state",
    "build",
    "tests",
    "constraints",
)
ARCHITECTURE_HORIZONTAL_MODULE_FIELDS = (
    "module_id",
    "name",
    "summary",
    "component_ids",
)
ARCHITECTURE_VERTICAL_SLICE_FIELDS = (
    "id",
    "title",
    "ordered_steps",
    "alternate_flows",
    "error_flows",
    "dynamic_behavior",
    "unresolved",
)
ARCHITECTURE_STEP_FIELDS = (
    "order",
    "module_id",
    "component_ids",
    "summary",
    "symbol_locators",
    "source_refs",
)
ARCHITECTURE_KNOWLEDGE_REQUIRED_FIELDS = (
    "schema_version",
    "record_type",
    "repository_revision",
    "id",
    "title",
    "body",
    "module_ids",
    "component_ids",
    "horizontal",
    "vertical_slices",
    "diagrams",
    "deep_links",
    "limitations",
)

MODULE_HORIZONTAL_FIELDS = (
    "purpose",
    "interfaces",
    "relationship_ids",
    "configuration",
    "state",
    "tests",
    "risks",
    "peer_navigation",
)
MODULE_VERTICAL_FIELDS = (
    "components",
    "initialization",
    "normal_flow",
    "alternate_flow",
    "errors",
    "data",
    "concurrency",
    "important_functions",
)
MODULE_VERTICAL_COMPONENT_FIELDS = (
    "component_id",
    "summary",
)
MODULE_KNOWLEDGE_REQUIRED_FIELDS = (
    "schema_version",
    "record_type",
    "repository_revision",
    "id",
    "module_id",
    "title",
    "body",
    "module_ids",
    "component_ids",
    "horizontal",
    "vertical",
    "diagrams",
    "peer_links",
    "deep_links",
    "intentional_component_overlap",
    "limitations",
)

FUNCTION_DETAIL_FIELDS = (
    "purpose",
    "contract",
    "local_flow",
    "callers",
    "callees",
    "state",
    "errors",
    "concurrency",
    "tests",
    "limitations",
)
FUNCTION_KNOWLEDGE_REQUIRED_FIELDS = (
    "schema_version",
    "record_type",
    "repository_revision",
    "id",
    "title",
    "body",
    "symbol",
    "component_ids",
    "module_ids",
    *FUNCTION_DETAIL_FIELDS,
    "call_edges",
    "diagrams",
)
CALL_CONFIDENCE_VALUES = ("direct", "inferred", "dynamic", "unresolved")
CALL_EDGE_REQUIRED_FIELDS = (
    "from_symbol_key",
    "to_symbol_key",
    "confidence",
    "summary",
)
KNOWLEDGE_REQUEST_REQUIRED_FIELDS = (
    "schema_version",
    "record_type",
    "repository_revision",
    "id",
    "request_type",
    "status",
    "reason",
)
KNOWLEDGE_REQUEST_TYPE_VALUES = (
    "missing_file",
    "missing_component",
    "missing_endpoint",
    "missing_knowledge",
)
KNOWLEDGE_REQUEST_STATUS_VALUES = ("open", "resolved", "dismissed")
DIAGRAM_REQUIRED_FIELDS = (
    "id",
    "type",
    "node_ids",
    "relationship_ids",
    "mermaid",
)
LINK_REQUIRED_FIELDS = ("target_type", "target_id")

AGENT_RECORD_REQUIRED_FIELDS = {
    "component_reconciliation": RECONCILIATION_REQUIRED_FIELDS,
    "module": MODULE_REQUIRED_FIELDS,
    "module_relationship": MODULE_RELATIONSHIP_REQUIRED_FIELDS,
    "architecture_knowledge": ARCHITECTURE_KNOWLEDGE_REQUIRED_FIELDS,
    "module_knowledge": MODULE_KNOWLEDGE_REQUIRED_FIELDS,
    "function_knowledge": FUNCTION_KNOWLEDGE_REQUIRED_FIELDS,
    "knowledge_request": KNOWLEDGE_REQUEST_REQUIRED_FIELDS,
}
NESTED_REQUIRED_FIELDS = {
    "reconciliation_partition": RECONCILIATION_PARTITION_REQUIRED_FIELDS,
    "architecture_horizontal": ARCHITECTURE_HORIZONTAL_FIELDS,
    "architecture_horizontal_module": ARCHITECTURE_HORIZONTAL_MODULE_FIELDS,
    "architecture_vertical_slice": ARCHITECTURE_VERTICAL_SLICE_FIELDS,
    "architecture_step": ARCHITECTURE_STEP_FIELDS,
    "module_horizontal": MODULE_HORIZONTAL_FIELDS,
    "module_vertical": MODULE_VERTICAL_FIELDS,
    "module_vertical_component": MODULE_VERTICAL_COMPONENT_FIELDS,
    "call_edge": CALL_EDGE_REQUIRED_FIELDS,
    "diagram": DIAGRAM_REQUIRED_FIELDS,
    "deep_link": LINK_REQUIRED_FIELDS,
}
NESTED_ARRAY_REFS = (
    ("architecture_horizontal", "modules", "architecture_horizontal_module"),
    ("module_vertical", "components", "module_vertical_component"),
)


def contract_field_text(record_type: str) -> str:
    """Return an exact required-field sentence for an AI prompt."""

    fields = AGENT_RECORD_REQUIRED_FIELDS[record_type]
    return (
        f"Every `{record_type}` record must contain: "
        + ", ".join(f"`{field}`" for field in fields)
        + "."
    )


def nested_contract_field_text(record_type: str) -> str:
    """Return an exact required-field sentence for one nested AI object."""

    fields = NESTED_REQUIRED_FIELDS[record_type]
    return (
        f"Every `{record_type}` object must contain: "
        + ", ".join(f"`{field}`" for field in fields)
        + "."
    )


def missing_required_fields(
    record: Mapping[str, object], fields: tuple[str, ...]
) -> tuple[str, ...]:
    """Return contract fields absent from one runtime record."""

    return tuple(field for field in fields if field not in record)


def validate_phase3_schema_alignment(schema: Mapping[str, object]) -> None:
    """Cross-check every AI record and nested shape against the JSON Schema."""

    definitions = schema.get("$defs")
    if not isinstance(definitions, Mapping):
        raise RuntimeError("Phase 3 schema has no $defs object")
    header = _definition(definitions, "header")
    header_required = set(_strings(header, "required"))
    header_properties = set(_properties(header))
    for name, fields in AGENT_RECORD_REQUIRED_FIELDS.items():
        contract = _composed_definition(definitions, name)
        actual = header_required | set(_strings(contract, "required"))
        expected = set(fields)
        if actual != expected:
            raise RuntimeError(
                f"{name} schema required fields do not match runtime contract: "
                f"expected {sorted(expected)}, found {sorted(actual)}"
            )
        missing_properties = expected - (header_properties | set(_properties(contract)))
        if missing_properties:
            raise RuntimeError(
                f"{name} schema has required fields without properties: "
                f"{sorted(missing_properties)}"
            )
    for name, fields in NESTED_REQUIRED_FIELDS.items():
        contract = _definition(definitions, name)
        actual = set(_strings(contract, "required"))
        if actual != set(fields):
            raise RuntimeError(
                f"{name} schema required fields do not match runtime contract"
            )
        missing_properties = set(fields) - set(_properties(contract))
        if missing_properties:
            raise RuntimeError(
                f"{name} schema has required fields without properties: "
                f"{sorted(missing_properties)}"
            )
    for owner, field, target in NESTED_ARRAY_REFS:
        properties = _properties(_definition(definitions, owner))
        value = properties.get(field)
        items = value.get("items") if isinstance(value, Mapping) else None
        expected_ref = f"#/$defs/{target}"
        if not isinstance(items, Mapping) or items.get("$ref") != expected_ref:
            raise RuntimeError(
                f"{owner}.{field} must reference the {target} contract"
            )
    _enum(
        _composed_definition(definitions, "module_relationship"),
        "direction",
        RELATIONSHIP_DIRECTION_VALUES,
    )
    for name in ("module", "module_relationship"):
        _enum(
            _composed_definition(definitions, name),
            "confidence",
            EVIDENCE_CONFIDENCE_VALUES,
        )
    _enum(
        _definition(definitions, "call_edge"),
        "confidence",
        CALL_CONFIDENCE_VALUES,
    )
    _enum(
        _composed_definition(definitions, "knowledge_request"),
        "request_type",
        KNOWLEDGE_REQUEST_TYPE_VALUES,
    )
    _enum(
        _composed_definition(definitions, "knowledge_request"),
        "status",
        KNOWLEDGE_REQUEST_STATUS_VALUES,
    )


def _definition(
    definitions: Mapping[str, object], name: str
) -> Mapping[str, object]:
    value = definitions.get(name)
    if not isinstance(value, Mapping) or value.get("type") != "object":
        raise RuntimeError(f"Phase 3 schema has no object definition for {name}")
    return value


def _composed_definition(
    definitions: Mapping[str, object], name: str
) -> Mapping[str, object]:
    value = definitions.get(name)
    parts = value.get("allOf") if isinstance(value, Mapping) else None
    if not isinstance(parts, list):
        raise RuntimeError(f"Phase 3 schema {name} definition has no allOf array")
    for part in parts:
        if isinstance(part, Mapping) and part.get("type") == "object":
            return part
    raise RuntimeError(f"Phase 3 schema {name} has no object contract")


def _strings(contract: Mapping[str, object], field: str) -> list[str]:
    values = contract.get(field)
    if not isinstance(values, list) or any(
        not isinstance(value, str) for value in values
    ):
        raise RuntimeError(f"Phase 3 schema {field} must be an array of strings")
    return values


def _properties(contract: Mapping[str, object]) -> Mapping[str, object]:
    properties = contract.get("properties")
    if not isinstance(properties, Mapping):
        raise RuntimeError("Phase 3 schema object has no properties")
    return properties


def _enum(
    contract: Mapping[str, object], field: str, expected: tuple[str, ...]
) -> None:
    properties = contract.get("properties")
    value = properties.get(field) if isinstance(properties, Mapping) else None
    actual = value.get("enum") if isinstance(value, Mapping) else None
    if not isinstance(actual, list) or set(actual) != set(expected):
        raise RuntimeError(f"Phase 3 schema {field} enum does not match contract")
