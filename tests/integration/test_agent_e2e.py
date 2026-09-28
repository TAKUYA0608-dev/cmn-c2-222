"""Integration — CMN-C2-222 end-to-end through the outer agent + inner Cat 2 workflow."""
from __future__ import annotations

import json

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel
from src.graph.graph import DocIngestionAdvisoryAgent
from src.services.service import InMemoryKnowledgeStore, StubLLMClient



def _ctx():
    # S-1: nodes require VERIFIED_EXTERNAL (config/agent.yaml) — tests invoke as a verified caller.
    return InvocationContext(caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)

def test_e2e_full_grounded_workflow():
    agent = DocIngestionAdvisoryAgent(llm_client=StubLLMClient("design narrative"))
    out = agent.invoke(
        "Finance customer records into AI-KB with markitdown — APPI + sandbox design?",
        ctx=_ctx(),
        input_context={"context": "on-prem K8s"},
    )
    assert out["status"] == "success"
    assert out["retrieval_count"] > 0
    arch = json.loads(out["architecture_skeleton"])
    assert arch["narrative"] == "design narrative"
    sandbox = json.loads(out["sandbox_spec"])
    assert sandbox["controls"]
    # post_process (S-3 + S-4) ran on the merged output
    assert out["disclaimer_present"] is True
    assert out["audit_logged"] is True
    assert out["validation_status"] in ("passed", "redacted")


def test_e2e_degraded_path_still_audits():
    """A broken KB (raises) → propagated via error_code → outer still audits + disclaims."""
    class _BrokenStore(InMemoryKnowledgeStore):
        def search(self, query, tags, top_k=6):
            raise RuntimeError("kb backend down")

    agent = DocIngestionAdvisoryAgent(knowledge_store=_BrokenStore())
    out = agent.invoke("legal contract ingestion design?", ctx=_ctx())
    assert out["audit_logged"] is True          # S-4 ran despite the inner failure
    assert out["error_code"] == "RETRIEVAL_FAILED"
    assert out["status"] == "success"           # degraded, not a hard crash
