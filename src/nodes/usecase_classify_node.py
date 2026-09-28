"""UseCaseClassifyNode — inner workflow node (step 1).

Deterministically tag the design question: SECRET / customer / internal sensitivity ×
industry (legal / finance / medical / education / general) × applicable regulation set
(現行 個人情報保護法 (APPI) / 電子帳簿保存法 / GDPR). Inside the inner graph the normalized query arrives
as `user_input` (the `validated_input` JSON the outer pre_process produced).
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.services.service import classify_usecase

try:  # S-4 canonical platform logger (PB-1)
    from shared.utils.audit_logger import emit_trace_event
except ImportError:  # local test env — platform logger not installed
    from src.utils.audit import emit_trace_event


class UseCaseClassifyNode(FunctionNode):
    """Deterministic SECRET/customer × industry × regulation tagging."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("error_code"):
            return {}

        try:
            nq = json.loads(state.get("user_input") or "{}")
        except (json.JSONDecodeError, TypeError):
            nq = {}
        query = " ".join(str(v) for v in (nq.get("query"), nq.get("context"), nq.get("regulation_scope")) if v)

        tags = classify_usecase(query)
        emit_trace_event(
            "usecase_classified",
            {"industry_count": len(tags["industries"]), "regulation_count": len(tags["regulations"])},
            state,
        )
        return {
            "usecase_tags": json.dumps(tags, ensure_ascii=False),
            "status": AgentStatus.SUCCESS.value,
        }
