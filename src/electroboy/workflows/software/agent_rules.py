"""Agent document rules owned by the software-engineering workflow."""

from __future__ import annotations

from pathlib import Path

from electroboy.service.agent_rules import materialize_workflow_agent_rules
from electroboy.service.registry import AgentRuleDefinition

SOFTWARE_AGENT_RULES = (
    AgentRuleDefinition(
        id="software.structured-artifacts",
        label="Software Workflow Artifacts",
        priority=30,
        content="""\
ElectroBoy maintains these structured document pairs.

| Artifact | Structured source | Generated companion |
| --- | --- | --- |
| `requirements` | `docs/requirements.jsonl` | `docs/requirements.md` |
| `design` | `docs/detailed-design.jsonl` | `docs/detailed-design.md` |
| `implementation-plan` | `docs/implementation-plan.jsonl` | `docs/implementation-plan.md` |
| `test-plan` | `docs/test-plan.jsonl` | `docs/test-plan.md` |

Requirements state observable behavior, constraints, and acceptance criteria.
Design records architecture, interfaces, state, failure handling, and important
tradeoffs. Implementation plans divide the design into ordered, verifiable
units. Test plans cover system behavior, environment assumptions, procedures,
and expected results.

Any software agent may update these artifacts when the operator asks. Apply the
structured document source rules even when the session was started for coding,
review, validation, documentation, or ad-hoc work.""",
    ),
    AgentRuleDefinition(
        id="software.general-documents",
        label="Software Documentation",
        priority=40,
        content="""\
Use the repository's established location and format for ordinary software
documentation. Keep operational instructions executable and name commands,
paths, prerequisites, and expected outcomes precisely.

For a new recipe with no project convention, recommend
`docs/recipes/<lowercase-kebab-case>.md`. A recipe should identify its purpose,
prerequisites, procedure, verification, and recovery guidance when recovery is
relevant.

For manual pages, follow the project's existing man-page toolchain and section
layout. If none exists, recommend the conventional
`man/man<section>/<command>.<section>` path and confirm the desired section
before creating the file.""",
    ),
)


def materialize_software_agent_rules(root: Path) -> str:
    """Materialize the effective rules for a software project."""

    return materialize_workflow_agent_rules(root, "software")


def prompt_with_software_agent_rules(prompt: str, rules_path: str) -> str:
    """Add the invariant document-rule instruction to an agent prompt."""

    return "\n".join(
        [
            prompt.rstrip(),
            "",
            "ElectroBoy document rules:",
            f"- Effective rules file: {rules_path}",
            "- Before creating, naming, or modifying a document, read that file",
            "  and follow every applicable required rule.",
            "- Naming guidance is a recommendation unless the operator specifies",
            "  a name or the rules mark a requirement.",
        ]
    ).rstrip() + "\n"
