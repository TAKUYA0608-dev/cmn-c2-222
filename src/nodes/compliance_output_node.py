"""ComplianceOutputNode — inner workflow node (step 5, terminal).

Assemble the architecture proposal + chunking strategy + clause-level citations into a
Markdown answer. Handles both branches:
  - grounded   → full architecture proposal (markitdown pattern + sandbox + citations)
  - ungrounded → a safe "insufficient grounding" answer that does NOT invent architecture
                 or compliance advice (the hallucination safeguard).
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, cast

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

try:  # S-4 canonical platform logger (PB-1)
    from shared.utils.audit_logger import emit_trace_event
except ImportError:  # local test env — platform logger not installed
    from src.utils.audit import emit_trace_event

_INSUFFICIENT = (
    "## Insufficient grounding\n\n"
    "I could not retrieve enough relevant design-guidance or regulation passages to safely "
    "recommend a markitdown ingestion architecture for this question. Rather than guess at "
    "compliance-sensitive design, please refine the question (industry, document types, "
    "applicable regulation, deployment environment) or extend the knowledge base."
)


class ComplianceOutputNode(FunctionNode):
    """Assemble the architecture proposal + citations (or a safe insufficient-grounding answer)."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("error_code"):
            return {
                "answer": "The design advisory could not be completed due to an upstream error.",
                "citations": json.dumps([], ensure_ascii=False),
                "status": AgentStatus.SUCCESS.value,
            }

        passages = _load_list(state.get("retrieved_patterns"))
        if not passages:
            emit_trace_event("compliance_output", {"grounded": False}, state)
            return {
                "answer": _INSUFFICIENT,
                "citations": json.dumps([], ensure_ascii=False),
                "status": AgentStatus.SUCCESS.value,
            }

        tags = _load_obj(state.get("usecase_tags"))
        arch = _load_obj(state.get("architecture_skeleton"))
        sandbox = _load_obj(state.get("sandbox_spec"))

        lines = ["## markitdown Ingestion — Architecture Proposal", ""]
        lines.append(
            f"**Industry:** {', '.join(tags.get('industries', []))}  "
            f"**Sensitivity:** {', '.join(tags.get('sensitivity', []))}  "
            f"**Regulation:** {', '.join(tags.get('regulations', []))}"
        )
        lines.append("")
        lines.append("### Architecture")
        lines.append(f"- Pattern: {arch.get('markitdown_pattern')}")
        lines.append(f"- Extraction layer: {arch.get('extraction_layer')}")
        if arch.get("narrative"):
            lines.append(f"- {arch.get('narrative')}")
        lines.append("")
        lines.append("### Subprocess sandbox")
        for c in sandbox.get("controls", []):
            lines.append(f"- {c}")
        if sandbox.get("narrative"):
            lines.append(f"- _{sandbox.get('narrative')}_")
        lines.append("")
        lines.append("### Chunking")
        lines.append("- Chunk by semantic heading with overlap; cap to embedding context; preserve tables.")

        # Provenance must reach the caller, not stop at the KB record: each
        # citation carries the record's verifiable ``official_ref`` (statute
        # number / named external document / template-owned baseline) so the
        # person reading the answer can check the source (,
        # applied here as in sibling templates).
        citations = [
            {
                "id": p.get("id"),
                "source": p.get("source"),
                "official_ref": p.get("official_ref"),
                "effective_date": p.get("effective_date"),
            }
            for p in passages
        ]
        emit_trace_event("compliance_output", {"grounded": True, "citation_count": len(citations)}, state)
        return {
            "answer": "\n".join(lines).strip(),
            "citations": json.dumps(citations, ensure_ascii=False),
            "status": AgentStatus.SUCCESS.value,
        }


def _load_obj(raw: Any) -> dict[str, Any]:
    try:
        return cast(dict[str, Any], json.loads(raw or "{}"))
    except (json.JSONDecodeError, TypeError):
        return {}


def _load_list(raw: Any) -> list[dict[str, Any]]:
    try:
        return cast(list[dict[str, Any]], json.loads(raw or "[]"))
    except (json.JSONDecodeError, TypeError):
        return []
