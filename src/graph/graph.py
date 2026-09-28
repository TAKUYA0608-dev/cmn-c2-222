"""CMN-C2-222 DocIngestionAdvisoryAgent — outer Cat 2 graph composition.

L1-direct inheritance from AgentBaseGraph. The outer graph is the fixed 5-node backbone
(START → initialize → pre_process → main → post_process → finalize → END); the multi-step
design-advisory workflow is encapsulated in a GraphNode in the `main` slot wrapping an
inner BaseGraph (`src/graph/domain_workflow_graph.py`). This is the Cat 2 pattern — NOT a
Cat 1 composite FunctionNode-in-main.

    pre_process  = QueryNormalizeNode             (S-1 input boundary; normalized query JSON)
    main         = DocIngestionWorkflowGraphNode  (GraphNode → inner DocIngestionWorkflowGraph:
                                                   classify → retrieve → {architecture → sandbox} → compliance-output)
    post_process = ResponseValidateNode           (S-3 citation + legal disclaimer + redaction + S-4)

This is a design-ADVISORY agent: it never ingests/extracts real documents (a separate
Tool's job). The knowledge base + LLM are dependency-injected so the agent is
offline-testable. A bare ``Graph(config=...)`` (the Marketplace runner form) binds the
seed KB; the LLM resolves as explicit ``llm_client`` > ``config["llm"]`` (the fleet entry
point's lazy Azure client, adapted) > none and is threaded through the GraphNode into the
inner workflow. The proposal is deterministic (grounded skeleton + sandbox controls +
cited passages) so a run without an LLM still answers; only the narrative sentences are
omitted, with a named S-4 record — no stub is ever bound silently.
"""

from __future__ import annotations
from typing import Any

from framework.graph.agent_base_graph import AgentBaseGraph

from src.schemas.state import DocIngestionState
from src.services.service import KnowledgeStore, LLMClient, resolve_llm_client
from src.nodes.query_normalize_node import QueryNormalizeNode
from src.nodes.main_node import DocIngestionWorkflowGraphNode
from src.nodes.response_validate_node import ResponseValidateNode


class DocIngestionAdvisoryAgent(AgentBaseGraph):
    """markitdown Office→AI-ready ingestion design-advisory Q&A agent (Cat 2)."""

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        knowledge_store: KnowledgeStore | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self._knowledge_store = knowledge_store
        # explicit kw > config["llm"] > None (see service.resolve_llm_client)
        self._llm_client = resolve_llm_client(llm_client, config)
        super().__init__(config)

    @property
    def name(self) -> str:
        return "DocIngestionAdvisoryAgent"

    @property
    def state_schema(self) -> type:
        return DocIngestionState

    def register_nodes(self) -> None:
        super().register_nodes()  # framework injects InitializeNode + FinalizeNode
        self._nodes["pre_process"] = QueryNormalizeNode()
        self._nodes["main"] = DocIngestionWorkflowGraphNode(
            knowledge_store=self._knowledge_store,
            llm_client=self._llm_client,
        )
        self._nodes["post_process"] = ResponseValidateNode()

    def get_output(self, state: dict[str, Any]) -> dict[str, Any]:
        # The Marketplace runner rejects a successful invocation whose output
        # is missing (verified on a deployed Pod), and a degraded run
        # (SUCCESS + error_code) leaves "answer" unset. Report the degradation —
        # this states what happened, it does not invent an answer.
        #
        # Only on SUCCESS: a request refused by the S-2 gate (status ERROR) must
        # keep publishing nothing, or the refusal is undone.
        _output = state.get("answer")
        if not _output and str(state.get("status", "")).lower().endswith("success"):
            _code = state.get("error_code") or "NO_CONTENT"
            _output = (
                "This request could not be completed "
                f"(error_code={_code}). No content was produced; "
                "see error_code and error_log for the degradation cause."
            )
        return {
            "output": _output,
            "answer": state.get("answer"),
            "citations": state.get("citations"),
            "usecase_tags": state.get("usecase_tags"),
            "retrieval_count": state.get("retrieval_count"),
            "architecture_skeleton": state.get("architecture_skeleton"),
            "sandbox_spec": state.get("sandbox_spec"),
            "validation_status": state.get("validation_status"),
            "disclaimer_present": state.get("disclaimer_present"),
            "redaction_count": state.get("redaction_count"),
            "audit_logged": state.get("audit_logged"),
            "status": state.get("status"),
            "error_code": state.get("error_code"),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
            "error_log": state.get("error_log", []),
        }


# Backward-compat alias — the scaffold (api/server.py) imports `Graph`.
Graph = DocIngestionAdvisoryAgent
