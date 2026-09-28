# PB-6 — Invoke execution order.
#
# node_history records visited node CLASS names. For this Cat 2 template the
# `main` slot is a GraphNode (DocIngestionWorkflowGraphNode) wrapping the inner
# BaseGraph (usecase_classify → pattern_retrieve → architecture_match →
# sandbox_design → compliance_output). The inner workflow nodes are
# encapsulated inside the GraphNode's subgraph and do NOT surface in the outer
# node_history — only the `main` slot does. Canonical outer slot order:
#   InitializeNode → QueryNormalizeNode → DocIngestionWorkflowGraphNode
#     → ResponseValidateNode → FinalizeNode
# This PB asserts the ordering invariant holds end-to-end: the S-1 trust-gated
# pre_process (QueryNormalize) precedes main, and post_process
# (ResponseValidate: S-3 gate + S-4 audit) precedes finalize.

from __future__ import annotations

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import DocIngestionAdvisoryAgent
from src.services.service import StubLLMClient

_CANONICAL = [
    "InitializeNode",
    "QueryNormalizeNode",
    "DocIngestionWorkflowGraphNode",
    "ResponseValidateNode",
    "FinalizeNode",
]


def _history() -> list[str]:
    agent = DocIngestionAdvisoryAgent(llm_client=StubLLMClient("narrative"))
    out = agent.invoke(
        "legal docs ingestion design?",
        ctx=InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL),
    )
    return out["node_history"]


def test_pb6_canonical_slot_order():
    history = _history()
    first = {n: history.index(n) for n in _CANONICAL}
    for a, b in zip(_CANONICAL, _CANONICAL[1:]):
        assert first[a] < first[b], f"PB-6: {a} must precede {b}, got {history}"


def test_pb6_initialize_first_finalize_last():
    history = _history()
    assert history[0] == "InitializeNode"
    assert history[-1] == "FinalizeNode"


def test_pb6_inner_workflow_not_surfaced():
    # The Cat 2 inner-workflow nodes live inside the GraphNode subgraph and must
    # not appear in the outer node_history.
    history = _history()
    for inner in ("UseCaseClassifyNode", "PatternRetrieveNode", "ComplianceOutputNode"):
        assert inner not in history, f"PB-6: inner node {inner} must not surface in node_history"
