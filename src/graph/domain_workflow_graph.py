"""DocIngestionWorkflowGraph — inner Cat 2 BaseGraph (`src/graph/domain_workflow_graph.py`).

Instantiated by `DocIngestionWorkflowGraphNode.get_subgraph()`. Implements the multi-step
design-advisory workflow with a grounding-conditional branch:

    START → usecase_classify → pattern_retrieve → {route}
                                  ├─ grounded   → architecture_match → sandbox_design → compliance_output → END
                                  └─ ungrounded → compliance_output (insufficient-grounding safe answer) → END

Inherits `BaseGraph` directly (custom topology). The knowledge store + LLM are passed via
`config` from the parent GraphNode. `get_output()` is designed together with
`DocIngestionWorkflowGraphNode.merge_output()`.
"""

from __future__ import annotations
from typing import Any

from langgraph.graph import END, START

from framework.graph.base_graph import BaseGraph
from framework.schemas.agent_state import AgentState
from framework.schemas.agent_status import AgentStatus

from src.schemas.state import DocIngestionState
from src.nodes.usecase_classify_node import UseCaseClassifyNode
from src.nodes.pattern_retrieve_node import PatternRetrieveNode
from src.nodes.architecture_match_node import ArchitectureMatchNode
from src.nodes.sandbox_design_node import SandboxDesignNode
from src.nodes.compliance_output_node import ComplianceOutputNode


class DocIngestionWorkflowGraph(BaseGraph):
    """Inner workflow: classify → retrieve → (architecture → sandbox) → compliance-output."""

    @property
    def name(self) -> str:
        return "doc_ingestion_advisory_workflow"

    @property
    def state_schema(self) -> type:
        return DocIngestionState

    def _validate_config(self) -> None:
        # knowledge_store / llm_client are optional: no store -> seed KB; no LLM -> the
        # narrative nodes omit their sentence (never a stub). Threaded from the outer graph.
        return None

    def register_nodes(self) -> None:
        store = self.config.get("knowledge_store")
        llm = self.config.get("llm_client")
        self._nodes["usecase_classify"] = UseCaseClassifyNode()
        self._nodes["pattern_retrieve"] = PatternRetrieveNode(knowledge_store=store)
        self._nodes["architecture_match"] = ArchitectureMatchNode(llm_client=llm)
        self._nodes["sandbox_design"] = SandboxDesignNode(llm_client=llm)
        self._nodes["compliance_output"] = ComplianceOutputNode()

    def add_edges(self) -> None:
        self._sg.add_edge(START, "usecase_classify")
        self._sg.add_edge("usecase_classify", "pattern_retrieve")
        # Wrap route in a lambda: LangGraph captures the path callable at compile time;
        # passing the bound method `self.route` directly does not branch reliably here,
        # so defer to it via a fresh closure. Branch behaviour is validated by
        # tests/unit/test_agent.py::test_agent_ungrounded_fast_path (ungrounded → safe answer)
        # and ::test_agent_end_to_end_grounded_proposal (grounded → architecture path).
        self._sg.add_conditional_edges(
            "pattern_retrieve",
            lambda s: self.route(s),
            {"architecture_match": "architecture_match", "compliance_output": "compliance_output"},
        )
        self._sg.add_edge("architecture_match", "sandbox_design")
        self._sg.add_edge("sandbox_design", "compliance_output")
        self._sg.add_edge("compliance_output", END)

    def route(self, state: AgentState) -> str:
        """Ungrounded retrieval (or an upstream error) → safe compliance_output; else design."""
        if state.get("error_code"):
            return "compliance_output"
        return "architecture_match" if (state.get("retrieval_count") or 0) > 0 else "compliance_output"

    def get_output(self, state: AgentState) -> dict[str, Any]:
        return {
            "answer": state.get("answer"),
            "citations": state.get("citations"),
            "usecase_tags": state.get("usecase_tags"),
            "retrieved_patterns": state.get("retrieved_patterns"),
            "retrieval_count": state.get("retrieval_count"),
            "architecture_skeleton": state.get("architecture_skeleton"),
            "sandbox_spec": state.get("sandbox_spec"),
            "status": state.get("status", AgentStatus.SUCCESS.value),
            "trace_id": state.get("trace_id"),
            "correlation_id": state.get("correlation_id"),
            "node_history": state.get("node_history", []),
            "error_code": state.get("error_code"),
            "error_message": state.get("error_message"),
        }
