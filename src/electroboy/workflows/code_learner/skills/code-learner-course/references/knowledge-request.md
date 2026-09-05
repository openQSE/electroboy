# Knowledge Request

Use request-only output when a required course claim, relationship, runtime
flow, diagram, caller, callee, state access, error path, or source reference
cannot be grounded in the supplied knowledge.

Emit one or more `knowledge_request` records conforming to the canonical
knowledge schema. Identify the selected course scope, precise missing facts,
related record IDs, likely repository-relative source locations when known,
and `status: "open"`. Do not also emit document or section records.

Do not use a lesson section, prose disclaimer, or fabricated low-confidence
claim as a substitute for a request. Non-blocking uncertainty may remain in a
course when the required learning path is still accurate and useful.
