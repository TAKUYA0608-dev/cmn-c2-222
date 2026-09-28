"""DocIngestionWorkflowGraphNode (main slot) — Cat 2 GraphNode.

Wraps the inner `DocIngestionWorkflowGraph` (`src/graph/domain_workflow_graph.py`). The
framework's `GraphNode.execute()` calls `get_subgraph()`, `extract_input()`, then
`inner.invoke(user_input, ctx=...)`, and maps the result back via `merge_output()`.

Cat 2 contract (docs/02 + scaffold graph_cat2_sample.py):
  - `execute` self-skips the subgraph when the outer pipeline already errored (S-1
    rejection in pre_process) so post_process still runs + audits.
  - `extract_input`  → the normalized query JSON (`validated_input`); becomes the inner
                       graph's `user_input`.
  - `merge_output`   → maps the inner workflow result into the outer state delta.
  - `error_strategy="handle"` + `on_subgraph_error` keep `status=SUCCESS` (carrying
                       `error_code`) so ResponseValidate ALWAYS runs S-3 + S-4 (criterion #9).
"""

from __future__ import annotations

from typing import Any, ClassVar, cast

from framework.nodes.graph_node import GraphNode
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus

try:  # S-4 canonical platform logger (PB-1)
    from shared.utils.audit_logger import emit_trace_event
except ImportError:  # local test env — platform logger not installed
    from src.utils.audit import emit_trace_event
from framework.schemas.trust_level import TrustLevel

from src.services.service import KnowledgeStore, LLMClient
from src.graph.domain_workflow_graph import DocIngestionWorkflowGraph


class DocIngestionWorkflowGraphNode(GraphNode):
    """main slot — runs the doc-ingestion advisory workflow as an inner BaseGraph."""

    required_trust_level: ClassVar[TrustLevel] = TrustLevel.VERIFIED_EXTERNAL

    error_strategy = "handle"  # degrade gracefully; outer post_process still audits

    def __init__(self, knowledge_store: KnowledgeStore | None = None, llm_client: LLMClient | None = None) -> None:
        super().__init__()
        self._subgraph = DocIngestionWorkflowGraph(
            config={"knowledge_store": knowledge_store, "llm_client": llm_client}
        )

    def execute(self, state: AgentState) -> dict[str, Any]:
        # Self-skip the subgraph when the outer pipeline already errored (e.g. S-1 rejected
        # the input in pre_process). Return status=SUCCESS so the post-main router still
        # routes to post_process (ResponseValidate audits) — ERROR would skip to finalize.
        if state.get("error_code"):
            emit_trace_event("main_workflow_skipped", {"error_code": state["error_code"]}, state)  # S-4 (TC-05)
            return {"status": AgentStatus.SUCCESS.value}
        result = cast(dict[str, Any], super().execute(state))
        emit_trace_event(
            "main_workflow_complete", {"error_code": (result or {}).get("error_code")}, state
        )  # S-4 (TC-05)
        return result

    def get_subgraph(self) -> DocIngestionWorkflowGraph:
        return self._subgraph

    def extract_input(self, state: AgentState) -> str:
        return state.get("validated_input") or state.get("user_input") or ""

    def merge_output(self, state: AgentState, sub_result: dict[str, Any]) -> dict[str, Any]:
        """Map the inner workflow result into the outer state (changed keys only)."""
        return {
            "answer": sub_result.get("answer"),
            "citations": sub_result.get("citations"),
            "usecase_tags": sub_result.get("usecase_tags"),
            "retrieved_patterns": sub_result.get("retrieved_patterns"),
            "retrieval_count": sub_result.get("retrieval_count"),
            "architecture_skeleton": sub_result.get("architecture_skeleton"),
            "sandbox_spec": sub_result.get("sandbox_spec"),
            "error_code": sub_result.get("error_code"),
            "error_message": sub_result.get("error_message"),
            "status": AgentStatus.SUCCESS.value,
        }

    def on_subgraph_error(self, state: AgentState, error: Exception) -> dict[str, Any]:
        """Graceful degradation — keep status SUCCESS so post_process (S-3/S-4) still runs."""
        return {
            "error_code": "WORKFLOW_ERROR",
            "error_message": str(error)[:200],
            "answer": "Unable to complete the document-ingestion design advisory due to an internal error.",
            "citations": "[]",
            "status": AgentStatus.SUCCESS.value,
        }
