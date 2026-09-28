# Test Specification — CMN-C2-222 DocIngestionAdvisoryAgent

## Test Strategy
- Coverage: **88%** (target ≥80%). Test types: Unit / Integration.
- DI-based, no mocking: `InMemoryKnowledgeStore` + `StubLLMClient` injected; deterministic
  `classify_usecase` asserted directly. Cat 2 GraphNode contract unit-tested.
- Run: `python -m pytest tests/ -v` → **25 passed**.

## Framework Compliance (Mandatory)

| TC-ID | Test | Expected | Result |
|-------|------|----------|--------|
| TC-01 | State is flat TypedDict (`DocIngestionState(AgentState)`) | no Pydantic/dataclass | ✅ PB-2 |
| TC-02 | S-1 rejects injection / empty / oversize input | `error_code` set, status ERROR | ✅ `test_query_normalize_*` |
| TC-03 | No JWT/credential in `src/` | CI `gate-credential-scan` 0 violations | ✅ CI |
| TC-04 | InvocationContext via `config["configurable"]` / framework GraphNode hand-off | not stored in State | ✅ docs/02 |
| TC-05 | No duplicate lifecycle events in `execute()` | `node_start/complete/error` absent | ✅ (domain events only) |
| TC-06/07 | `_security_gate_input/output` not overridden (`@final`) | FunctionNode subclasses use `execute()` only | ✅ |
| TC-08 | `required_trust_level` = `VERIFIED_EXTERNAL` (valid enum) | import-safe | ✅ |
| TC-11 | ≥1 domain `emit_trace_event()` per node | event on every path incl. error | ✅ `test_*` + S-4 always-audit |

## Proof-of-Boundary (Mandatory)

| PB-ID | Boundary | Expected | Result |
|-------|----------|----------|--------|
| PB-2 | State serialization | primitives only | ✅ `tests/proof_of_boundary/test_state_safety.py` |
| PB-4 | Import isolation (no Level 0) | AST scan 0 violations | ✅ `tests/proof_of_boundary/test_import_isolation.py` |
| PB-5 | Checkpoint safety | no JWT/Pydantic | ✅ (flat TypedDict) |
| PB-6 | Invoke order (S-1 → S-2 → execute → S-3 → S-4) | framework-enforced | ✅ |

> _extra security hooks (TC-09/10): N/A — S-1 input gate is implemented in
> `QueryNormalizeNode.execute()`; S-3 output gate (citation + legal disclaimer + secret/PII
> redaction) in `ResponseValidateNode.execute()`. The `main` GraphNode's S-2/S-3 are a
> sanctioned no-op passthrough (rationale: docs/02 §Framework Utilization)._

## Business Logic Tests

| ID | Test | Expected | Result |
|----|------|----------|--------|
| BL-01 | `classify_usecase` deterministic tagging (industry × sensitivity × regulation) | reproducible tags + conservative defaults | ✅ `test_classify_usecase_*` |
| BL-02 | Inner grounded chain: classify → retrieve → architecture → sandbox → compliance | architecture proposal + citations | ✅ `test_inner_chain_grounded_path` |
| BL-03 | **Grounding branch**: ungrounded retrieval → safe "insufficient grounding" answer (no hallucinated architecture) | LLM design steps skipped | ✅ `test_compliance_output_ungrounded_safe_answer`, `test_agent_ungrounded_fast_path` |
| BL-04 | S-3: citation completeness + **mandatory legal disclaimer** + secret/PII redaction | disclaimer attached, secrets/PII redacted | ✅ `test_response_validate_appends_disclaimer_and_redacts` |
| BL-05 | GraphNode contract: extract_input / merge_output / on_subgraph_error / execute self-skip | unit-level coverage | ✅ `test_main_node.py` |
| BL-06 | Graceful degradation: KB failure → `RETRIEVAL_FAILED`, S-4 still audits | degraded, not a crash | ✅ `test_e2e_degraded_path_still_audits` |
| BL-07 | E2E grounded proposal through the full Cat 2 agent | proposal + disclaimer + audit | ✅ `test_e2e_full_grounded_workflow` |

## Execution Summary
- Total: **25 tests · Pass 25 / Fail 0** · Coverage **88%** · ruff clean
