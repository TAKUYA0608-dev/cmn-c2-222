"""CMN-C2-222 Office Doc AI-Ready Advisory — State (shared by outer + inner Cat 2 graphs).

Flat TypedDict per the node and state-safety contracts: every field is an Optional primitive or a
JSON-serialized string (msgpack round-trips cleanly). No Pydantic, no dataclass, no
arbitrary objects, and never JWT / API keys / credentials. The agent advises on design
and never ingests real documents (extraction is a separate Tool); ResponseValidate
redacts any leaked secret / customer PII before egress.

Cat 2 (docs/02): the outer AgentBaseGraph and the inner BaseGraph SHARE this schema.
Inside the inner graph the normalized query arrives as `user_input` (the `validated_input`
JSON the outer pre_process built).
"""

from __future__ import annotations

from typing import Optional

from framework.schemas.agent_state import AgentState


class DocIngestionState(AgentState):
    """State for the markitdown ingestion design-advisory workflow (outer + inner)."""

    # ─── Input (caller supplies via user_input + input_context) ───
    query: Optional[str]  # NL design question
    context: Optional[str]  # optional deploy-env / doc-mix / industry hint
    regulation_scope: Optional[str]  # optional regulation scope hint

    # ─── QueryNormalizeNode (pre_process, S-1) ───
    validated_input: Optional[str]  # normalized query JSON → passed to the inner graph

    # ─── UseCaseClassifyNode (inner) ───
    usecase_tags: Optional[str]  # JSON: {industries, sensitivity, regulations}

    # ─── PatternRetrieveNode (inner) ───
    retrieved_patterns: Optional[str]  # JSON: [{id, source, text, score}]
    retrieval_count: Optional[int]

    # ─── ArchitectureMatchNode (inner, LLM) ───
    architecture_skeleton: Optional[str]  # JSON: {markitdown_pattern, extraction_layer, narrative}

    # ─── SandboxDesignNode (inner, LLM) ───
    sandbox_spec: Optional[str]  # JSON: {controls, narrative}

    # ─── ComplianceOutputNode (inner) ───
    answer: Optional[str]  # Markdown architecture proposal
    citations: Optional[str]  # JSON: [citation, ...]

    # ─── ResponseValidateNode (post_process, S-3 + S-4) ───
    validation_status: Optional[str]  # "passed" | "redacted" | "rejected" | "insufficient_grounding"
    disclaimer_present: Optional[bool]  # True once the legal disclaimer block is attached
    redaction_count: Optional[int]
    audit_logged: Optional[bool]

    # ─── Error propagation (any node / GraphNode; downstream self-skip) ───
    error_code: Optional[str]
    error_message: Optional[str]


# Backward-compat alias: scaffold (graph.py / server.py / examples) references `State`.
State = DocIngestionState
