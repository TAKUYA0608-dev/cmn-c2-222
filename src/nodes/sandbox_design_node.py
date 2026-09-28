"""SandboxDesignNode — inner workflow node (step 4, LLM).

Subprocess-injection attack-surface analysis for the markitdown CLI: propose a
container / K8s SecurityContext / gVisor spec. The control set is derived
deterministically from the use-case sensitivity; the LLM supplies the rationale.
Reached only on the grounded branch.
"""

from __future__ import annotations

import json
from typing import Any, ClassVar

from framework.nodes.function_node import FunctionNode
from framework.schemas.agent_status import AgentStatus
from framework.schemas.trust_level import TrustLevel

from src.services.service import LLMClient

try:  # S-4 canonical platform logger (PB-1)
    from shared.utils.audit_logger import emit_trace_event
except ImportError:  # local test env — platform logger not installed
    from src.utils.audit import emit_trace_event

_BASE_CONTROLS = [
    "read-only rootfs",
    "drop ALL Linux capabilities",
    "seccomp profile (default-deny)",
    "no network namespace",
    "non-root user",
    "memory + CPU limits",
]
_HIGH_SENSITIVITY_CONTROLS = ["gVisor / Kata runtime isolation", "per-tenant ephemeral workspace"]


class SandboxDesignNode(FunctionNode):
    """LLM-assisted subprocess-sandbox spec (deterministic controls + LLM rationale)."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        super().__init__()
        # None = no LLM bound. Resolved by the outer graph (explicit kw > config["llm"])
        # and threaded through the GraphNode; a bare node omits the narrative (no stub).
        self._llm: LLMClient | None = llm_client

    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        if state.get("error_code"):
            return {}

        try:
            tags = json.loads(state.get("usecase_tags") or "{}")
        except (json.JSONDecodeError, TypeError):
            tags = {}
        sensitivity = tags.get("sensitivity", ["internal"])

        controls = list(_BASE_CONTROLS)
        if any(s in ("secret", "customer") for s in sensitivity):
            controls += _HIGH_SENSITIVITY_CONTROLS

        if self._llm is None:
            # No LLM bound: the controls are deterministic; no rationale is invented.
            # S-4: field names only.
            emit_trace_event("llm_not_configured", {"fields": ["sandbox_spec"]}, state)
            narrative = ""
        else:
            narrative = self._llm.generate(
                f"Justify the subprocess sandbox controls for sensitivity={sensitivity}: {controls}. One sentence."
            )
        spec = {"controls": controls, "narrative": narrative}

        emit_trace_event("sandbox_designed", {"control_count": len(controls)}, state)
        return {
            "sandbox_spec": json.dumps(spec, ensure_ascii=False),
            "status": AgentStatus.SUCCESS.value,
        }
