"""QueryNormalizeNode — pre_process slot / S-1 input boundary.

Validate + normalize the NL design question, NFKC-normalize, reject injection, size-cap,
and capture optional context (deploy-env / doc-mix / industry) + regulation scope into a
normalized query JSON. That JSON becomes `validated_input`, which the main-slot GraphNode
hands to the inner workflow graph. Parse only — no retrieval / reasoning here.
"""

from __future__ import annotations

import json
import re
import unicodedata
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

try:  # S-4 canonical platform logger (PB-1)
    from shared.utils.audit_logger import emit_trace_event
except ImportError:  # local test env — platform logger not installed
    from src.utils.audit import emit_trace_event

_MAX_LEN = 2000

_INJECTION = re.compile(
    r"(?i)(ignore\s+(?:all\s+)?(?:previous|prior|above)\s+instructions"
    r"|disregard\s+(?:the\s+)?(?:system|previous)\s+(?:prompt|instructions)"
    r"|reveal\s+(?:your\s+)?system\s+prompt"
    r"|<\s*script\b|</\s*script\s*>)"
)
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class QueryNormalizeNode(FunctionNode):
    """S-1: validate + normalize the design question; capture context + regulation scope."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("error_code"):
            return {}

        ic = state.get("input_context") or {}
        raw = state.get("query") or state.get("user_input") or ""
        text = str(raw)

        if not text.strip():
            return self._reject(state, "INPUT_EMPTY", "QueryNormalizeNode: design question is empty or missing")
        if len(text) > _MAX_LEN:
            return self._reject(state, "INPUT_TOO_LONG", f"QueryNormalizeNode: question exceeds {_MAX_LEN} chars")
        if _INJECTION.search(text):
            return self._reject(state, "INJECTION_DETECTED", "QueryNormalizeNode: prompt-injection pattern rejected")

        normalized = unicodedata.normalize("NFKC", text)
        normalized = _CONTROL.sub("", normalized).strip()
        normalized = re.sub(r"\s+", " ", normalized)

        nq = {
            "query": normalized,
            "context": ic.get("context") or state.get("context") or "",
            "regulation_scope": ic.get("regulation_scope") or state.get("regulation_scope") or "",
        }
        emit_trace_event("query_normalized", {"length": len(normalized)}, state)  # S-4 (TC-05)
        return {
            "validated_input": json.dumps(nq, ensure_ascii=False),
            "query": normalized,
            "status": AgentStatus.SUCCESS.value,
        }

    @staticmethod
    def _reject(state: dict[str, Any], code: str, message: str) -> dict[str, Any]:
        """S-1 rejection — degraded (SUCCESS + error_code) so post_process still audits; S-4 emits here too (TC-05)."""
        emit_trace_event("query_rejected", {"error_code": code}, state)
        return {"error_code": code, "error_message": message, "status": AgentStatus.SUCCESS.value}
