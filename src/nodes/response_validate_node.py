"""ResponseValidateNode — post_process slot. **S-3 gate + S-4 audit.**

Terminal node, runs on the merged inner-workflow output. Responsibilities:
  1. **Citation completeness** — a grounded architecture proposal must carry citations; an
     uncited proposal is rejected. The insufficient-grounding safe answer is exempt.
  2. **Mandatory legal disclaimer** — every advisory answer gets a legal-disclaimer block
     appended (this is design guidance, not legal advice).
  3. **Sensitive-value redaction** — API keys / credentials and customer PII are redacted.
  4. **S-4 audit** — emit one redacted per-invocation event. Always fires (even on the
     degraded / insufficient-grounding path) — silent failure is prohibited.

Domain validation in `execute()`, distinct from the framework `@final` credential gate.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

try:  # S-4 canonical platform logger (PB-1)
    from shared.utils.audit_logger import emit_trace_event
except ImportError:  # local test env — platform logger not installed
    from src.utils.audit import emit_trace_event

_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_PHONE = re.compile(r"\b(?:0\d{1,4}[-\s]?\d{1,4}[-\s]?\d{3,4}|\+\d{8,15})\b")
_APIKEY = re.compile(
    r"\b(?:sk-[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{12,}|eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,})\b"
)
_REDACTED_SECRET = "[REDACTED:secret]"
_REDACTED_PII = "[REDACTED:pii]"

_DISCLAIMER = (
    "\n\n---\n_Disclaimer: this is AI-generated design guidance for a markitdown ingestion "
    "pipeline, not legal advice. Validate against the current 個人情報保護法 (APPI) / 電子帳簿保存法 / GDPR "
    "texts and your compliance officer before implementation._"
)


def _sanitize(text: str) -> tuple[str, int]:
    count = 0

    def _sub(repl: str) -> Callable[[re.Match[str]], str]:
        def _f(_m: "re.Match[str]") -> str:
            nonlocal count
            count += 1
            return repl

        return _f

    text = _APIKEY.sub(_sub(_REDACTED_SECRET), text)
    text = _EMAIL.sub(_sub(_REDACTED_PII), text)
    text = _PHONE.sub(_sub(_REDACTED_PII), text)
    return text, count


class ResponseValidateNode(FunctionNode):
    """S-3 citation completeness + legal disclaimer + secret/PII redaction + S-4 audit."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        answer = state.get("answer") or ""
        retrieval_count = state.get("retrieval_count") or 0
        try:
            citations = json.loads(state.get("citations") or "[]")
        except (json.JSONDecodeError, TypeError):
            citations = []

        # ── error path (S-1 input rejection or inner degradation): always audit, no disclaimer ──
        # Review finding M-1: exactly ONE `agent_invoke_complete` event fires per invocation — this branch
        # emits + `return`s for the error path; the normal path emits once at the end. The early
        # `return` guarantees the two emit sites are mutually exclusive (no double-fire).
        if state.get("error_code"):
            if not answer:
                answer = f"This request could not be completed ({state['error_code']})."
            answer, redaction_count = _sanitize(answer)
            emit_trace_event(
                "agent_invoke_complete",
                {
                    "validation_status": "rejected",
                    "redaction_count": redaction_count,
                    "disclaimer_present": False,
                    "error_code": state["error_code"],
                },
                state,
            )
            return {
                "answer": answer,
                "validation_status": "rejected",
                "disclaimer_present": False,
                "redaction_count": redaction_count,
                "audit_logged": True,
                "status": AgentStatus.SUCCESS.value,
            }

        grounded = retrieval_count > 0
        validation_status = "passed"

        # ── citation completeness: a grounded proposal must be cited ──
        if grounded and not citations:
            answer = (
                "This architecture proposal was withheld because it could not be cited "
                "to its source guidance / regulation passages."
            )
            validation_status = "rejected"
        elif not grounded:
            validation_status = "insufficient_grounding"

        # ── sensitive-value redaction ──
        answer, redaction_count = _sanitize(answer)
        if redaction_count and validation_status == "passed":
            validation_status = "redacted"

        # ── mandatory legal disclaimer (every advisory answer) ──
        disclaimer_present = False
        if validation_status != "rejected":
            answer = answer + _DISCLAIMER
            disclaimer_present = True

        # ── S-4 audit (always fires) ──
        payload: dict[str, Any] = {
            "retrieval_count": retrieval_count,
            "citation_count": len(citations),
            "validation_status": validation_status,
            "redaction_count": redaction_count,
            "disclaimer_present": disclaimer_present,
        }
        if state.get("error_code"):
            payload["error_code"] = state["error_code"]
        emit_trace_event("agent_invoke_complete", payload, state)

        return {
            "answer": answer,
            "validation_status": validation_status,
            "disclaimer_present": disclaimer_present,
            "redaction_count": redaction_count,
            "audit_logged": True,
            "status": AgentStatus.SUCCESS.value,
        }
