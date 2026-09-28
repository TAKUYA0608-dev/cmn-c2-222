"""ArchitectureMatchNode — inner workflow node (step 3, LLM).

Cross-axis (deploy-env × doc-type × regulation × industry) inference: select the
markitdown invocation pattern + extraction-layer skeleton, grounded in the retrieved
guidance passages. The injected LLM supplies the narrative; the structured skeleton is
derived deterministically from the tags. Reached only on the grounded branch.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar, cast

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.services.service import LLMClient

try:  # S-4 canonical platform logger (PB-1)
    from shared.utils.audit_logger import emit_trace_event
except ImportError:  # local test env — platform logger not installed
    from src.utils.audit import emit_trace_event


class ArchitectureMatchNode(FunctionNode):
    """LLM-assisted markitdown architecture skeleton (deterministic shape + LLM narrative)."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        super().__init__()
        # None = no LLM bound. Resolved by the outer graph (explicit kw > config["llm"])
        # and threaded through the GraphNode; a bare node omits the narrative (no stub).
        self._llm: LLMClient | None = llm_client

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("error_code"):
            return {}

        tags = _load_obj(state.get("usecase_tags"))
        passages = _load_list(state.get("retrieved_patterns"))
        sources = [p.get("source") for p in passages]

        regulated = bool(tags.get("regulations"))
        skeleton = {
            "markitdown_pattern": "sandboxed-subprocess CLI (untrusted output)",
            "extraction_layer": "isolated worker → markdown normalize → chunk → embed",
            "regulation_controls": tags.get("regulations", []),
            "grounded_in": sources,
        }
        if self._llm is None:
            # No LLM bound: the deterministic skeleton stands on its own; no narrative
            # is invented. S-4: field names only.
            emit_trace_event("llm_not_configured", {"fields": ["architecture_skeleton"]}, state)
            skeleton["narrative"] = ""
        else:
            skeleton["narrative"] = self._llm.generate(
                f"Design a markitdown ingestion architecture for industries={tags.get('industries')} "
                f"regulations={tags.get('regulations')} sensitivity={tags.get('sensitivity')}. "
                f"Grounding sources: {sources}. One paragraph."
            )

        emit_trace_event("architecture_matched", {"regulated": regulated, "source_count": len(sources)}, state)
        return {
            "architecture_skeleton": json.dumps(skeleton, ensure_ascii=False),
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
