"""Unit tests — DocIngestionWorkflowGraphNode (Cat 2 main-slot GraphNode contract).

Covers the GraphNode contract at the unit level so a regression in `extract_input` /
`merge_output` / `on_subgraph_error` / `execute` self-skip is caught without running the
full agent path.
"""

from __future__ import annotations

from framework.schemas.agent_status import AgentStatus

from src.nodes.main_node import DocIngestionWorkflowGraphNode
from src.services.service import StubLLMClient

_MERGED_KEYS = {
    "answer",
    "citations",
    "usecase_tags",
    "retrieved_patterns",
    "retrieval_count",
    "architecture_skeleton",
    "sandbox_spec",
    "status",
}


def _node():
    return DocIngestionWorkflowGraphNode(llm_client=StubLLMClient("x"))


def test_extract_input_prefers_validated_input():
    n = _node()
    assert n.extract_input({"validated_input": "VI", "user_input": "UI"}) == "VI"
    assert n.extract_input({"user_input": "UI"}) == "UI"  # falls back to user_input
    assert n.extract_input({}) == ""


def test_merge_output_maps_inner_fields_into_outer_keys():
    n = _node()
    sub = {
        "answer": "proposal",
        "citations": '[{"id": "appi-a18", "official_ref": "個人情報の保護に関する法律（平成15年法律第57号）第18条"}]',
        "usecase_tags": "{}",
        "retrieved_patterns": "[]",
        "retrieval_count": 3,
        "architecture_skeleton": "{}",
        "sandbox_spec": "{}",
    }
    out = n.merge_output({}, sub)
    assert _MERGED_KEYS.issubset(out)
    assert out["answer"] == "proposal" and out["retrieval_count"] == 3
    assert out["status"] == AgentStatus.SUCCESS.value


def test_merge_output_propagates_error_code():
    n = _node()
    out = n.merge_output({}, {"error_code": "RETRIEVAL_FAILED", "error_message": "kb down"})
    assert out["error_code"] == "RETRIEVAL_FAILED"
    assert out["status"] == AgentStatus.SUCCESS.value  # degraded, still routes to post_process


def test_on_subgraph_error_degrades_with_success_status():
    n = _node()
    out = n.on_subgraph_error({}, RuntimeError("boom"))
    assert out["error_code"] == "WORKFLOW_ERROR"
    assert out["status"] == AgentStatus.SUCCESS.value  # S-3/S-4 contract: post_process must run
    assert out["answer"]  # a degraded answer is emitted


def test_execute_self_skips_subgraph_on_outer_error_code():
    """When pre_process (S-1) already errored, the GraphNode must NOT run the subgraph,
    but must return status=SUCCESS so the router still reaches post_process (audit)."""
    n = _node()
    out = n.execute({"error_code": "INJECTION_DETECTED"})
    assert out == {"status": AgentStatus.SUCCESS.value}
