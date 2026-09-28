"""PatternRetrieveNode — inner workflow node (step 2).

Vector/lexical RAG over the design-guidance KB (markitdown docs + APPI + 電子帳簿保存法 +
industry guidelines + subprocess-sandbox best practices) via the injected KnowledgeStore.
A zero-result retrieval is NOT an error — the inner graph routes ungrounded runs to a safe
"insufficient grounding" answer instead of letting the LLM hallucinate architecture advice.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.services.service import KnowledgeStore, seed_knowledge_store

try:  # S-4 canonical platform logger (PB-1)
    from shared.utils.audit_logger import emit_trace_event
except ImportError:  # local test env — platform logger not installed
    from src.utils.audit import emit_trace_event

_TOP_K = 6


class PatternRetrieveNode(FunctionNode):
    """Retrieve top-k design-guidance passages for the tagged use case."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, knowledge_store: KnowledgeStore | None = None) -> None:
        super().__init__()
        self._store: KnowledgeStore = knowledge_store or seed_knowledge_store()

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("error_code"):
            return {}

        try:
            nq = json.loads(state.get("user_input") or "{}")
        except (json.JSONDecodeError, TypeError):
            nq = {}
        try:
            tags = json.loads(state.get("usecase_tags") or "{}")
        except (json.JSONDecodeError, TypeError):
            tags = {}

        query = str(nq.get("query") or "")
        flat_tags = [*tags.get("industries", []), *tags.get("regulations", []), *tags.get("sensitivity", [])]
        try:
            passages = self._store.search(query, flat_tags, top_k=_TOP_K) or []
        except Exception as e:  # external KB failure → propagate via error_code (no raise)
            return {
                "error_code": "RETRIEVAL_FAILED",
                "error_message": f"PatternRetrieveNode: {str(e)[:160]}",
                "status": AgentStatus.SUCCESS.value,
            }  # degraded: error_code set; keep SUCCESS so post_process (S-3/S-4) still runs

        emit_trace_event("patterns_retrieved", {"retrieval_count": len(passages)}, state)
        return {
            "retrieved_patterns": json.dumps(passages, ensure_ascii=False),
            "retrieval_count": len(passages),
            "status": AgentStatus.SUCCESS.value,
        }
