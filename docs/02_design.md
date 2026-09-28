# Template Design Specification — CMN-C2-222

**Template ID:** CMN-C2-222
**Agent Class:** DocIngestionAdvisoryAgent
**Category:** **Cat 2** (multi-step domain workflow — markitdown-based Office→AI-ready ingestion **design advisory** Q&A)
**Industry:** CMN (cross-industry)
**SoT:** scaffold/#1289, SoT note #944504 (JP) / #944498 (EN)

> **Scope (SoT §4):** this is a **design-advisory Q&A** agent. It does NOT convert/extract
> documents — the deterministic markitdown extraction is a separate Tool/Service and is OUT of
> scope. The agent answers *"how should we design a safe, compliant markitdown ingestion
> pipeline?"* and returns a structured architecture proposal with clause-level citations + a
> legal disclaimer.

> **Cat 2 architecture (per scaffold `graph_cat2_sample.py`):** outer fixed 5-node
> `AgentBaseGraph`; the multi-step reasoning workflow is encapsulated in a **`GraphNode`
> subclass in the `main` slot** wrapping an **inner `BaseGraph`** at
> `src/graph/domain_workflow_graph.py`. NOT a Cat 1 composite.

## Position in AgentCore Architecture

- **Outer L1 Base: `AgentBaseGraph`** (fixed backbone; `main` = a `GraphNode` subclass)
- **Inner Base: `BaseGraph`** (custom topology with a grounding-conditional branch) at `src/graph/domain_workflow_graph.py`
- **Three-Layer Separation:** State = flat TypedDict (`DocIngestionState(AgentState)`, shared outer+inner); Node = L1 inheritance (`FunctionNode` slot/domain nodes + `GraphNode` main); Graph = composition

## Architecture Overview

### Node Configuration — Outer graph (`src/graph/graph.py`)

| Slot | Node | Responsibility | Inherits |
|------|------|---------------|----------|
| initialize | InitializeNode | schema_version, session_id, trust_level | default (framework) |
| **pre_process** | **QueryNormalizeNode** | S-1 input boundary: NFKC/injection/size; parse the NL design question → normalized query JSON (industry / doc-type / regulation / deployment-env, conservative defaults for missing). `validated_input` = normalized query JSON string. | FunctionNode |
| **main** | **DocIngestionWorkflowGraphNode** | `GraphNode` wrapping inner `DocIngestionWorkflowGraph`; runs classify → retrieve → architecture → sandbox → compliance-output | **GraphNode** |
| **post_process** | **ResponseValidateNode** | **S-3 gate**: citation completeness + **mandatory legal-disclaimer block** + sensitive-value redaction + hallucination heuristic | FunctionNode |
| finalize | FinalizeNode | response_metadata, total_time_ms | default (framework) |

### Node Configuration — Inner graph (`src/graph/domain_workflow_graph.py`, `BaseGraph`)

| Node | Responsibility | LLM? |
|------|----------------|------|
| **UseCaseClassify** | tag SECRET / customer / internal mix × industry (legal/finance/medical/education/general) × applicable regulation set (APPI 2026 / 電子帳簿保存法 / GDPR) | **no (deterministic keyword map)** |
| **PatternRetrieve** | vector RAG over markitdown docs + APPI + 電帳法 + industry guidelines (FSA/MHLW/MOJ/MEXT) + subprocess-sandbox best-practices KB (DI `KnowledgeStore`) | no (retrieval) |
| ↳ *route* | conditional: grounded (≥1 relevant passage) → ArchitectureMatch; **ungrounded → ComplianceOutput** (insufficient-grounding safe answer, no hallucinated architecture) | — |
| **ArchitectureMatch** | cross-axis (deploy-env × doc-type × regulation × industry) inference → markitdown invocation pattern + extraction-layer skeleton | LLM |
| **SandboxDesign** | subprocess-injection attack-surface analysis → container/K8s SecurityContext / gVisor spec | LLM |
| **ComplianceOutput** | assemble architecture + chunking strategy + clause-level citations → Markdown proposal + JSON citation set (**no LLM — pure string/template assembly from the prior nodes' JSON**) | no |

> **Why UseCaseClassify is deterministic (not LLM):** the regulation / industry / sensitivity
> tags drive retrieval and the SecurityContext controls, so they must be reproducible and
> auditable — a keyword map is the safe choice. The LLM-heavy reasoning lives in
> ArchitectureMatch + SandboxDesign (narrative), grounded in retrieved passages.

### Data Flow

```
Outer backbone (fixed):
  START → initialize → pre_process(QueryNormalize) → main(DocIngestionWorkflowGraphNode)
        → post_process(ResponseValidate) → finalize → END
                                            ↓ (RETRY, max 3) pre_process

Inside main → inner DocIngestionWorkflowGraph (BaseGraph):
  START → UseCaseClassify → PatternRetrieve → {route}
                                  ├─ grounded   → ArchitectureMatch → SandboxDesign → ComplianceOutput → END
                                  └─ ungrounded → ComplianceOutput(insufficient-grounding safe answer) → END
```

> **RETRY loop:** `↓ (RETRY, max 3)` is the framework backbone affordance — the
> outer `AgentBaseGraph.route()` sends `status=RETRY` back to `pre_process` (up to
> `max_retry`, default 3). **This template never sets `status=RETRY`** (no node returns it):
> input problems are rejected at S-1 (error_code), and inner failures degrade gracefully via
> `error_code` (no re-run). So the RETRY edge exists structurally but is not exercised; there
> is no template-specific retry trigger to specify.

### GraphNode contract — `DocIngestionWorkflowGraphNode` (resolves CoE criterion #9)

- **`get_subgraph()`** → instantiate `DocIngestionWorkflowGraph` (cached in `__init__`)
- **`extract_input(state)`** → `state["validated_input"]` (normalized query JSON from QueryNormalize)
- **`merge_output(state, sub_result)`** → map inner `get_output()` into the outer state delta: `{answer, citations, usecase_tags, architecture_skeleton, sandbox_spec, status}` (changed keys only)
- **`error_strategy = "handle"`** — on inner-graph exception, `on_subgraph_error()` sets `error_code` + a degraded message; the outer **ResponseValidate still runs S-3 (disclaimer + redaction) + S-4 audit** so an advisory answer (or a safe refusal) is always returned. Inner per-node failures self-skip via `error_code`.

> **Inner `get_output()` ↔ outer `merge_output()`:** the inner graph's `get_output(state)` is
> the counterpart to `merge_output()` — it returns the dict the GraphNode consumes as
> `sub_result`. Shape: `{answer, citations, usecase_tags, retrieved_patterns, retrieval_count,
> architecture_skeleton, sandbox_spec, status, trace_id, correlation_id, node_history,
> error_code, error_message}`. `merge_output()` maps the changed subset (+ `error_code`).

> **InvocationContext propagation:** the framework's `GraphNode.execute()` builds
> `ctx = InvocationContext.from_state(state)` and calls `inner.invoke(user_input, ctx=ctx)`;
> `BaseGraph.invoke()` seeds the inner initial_state with `caller_trust_level` / `session_id` /
> `correlation_id` from that ctx (so S-1 works inside the inner graph). The template does not
> thread `config["configurable"]` manually — the framework owns this hand-off.

### Normalized query (`validated_input`) schema

`QueryNormalizeNode` emits `validated_input` as a JSON string with this exact shape; it is the
inner graph's `user_input`, parsed by UseCaseClassify / PatternRetrieve:

```json
{ "query": "<normalized NL design question>",   // str, required
  "context": "<deploy-env / doc-mix / industry hint or ''>",   // str, '' when absent
  "regulation_scope": "<APPI/電帳法/GDPR hint or ''>" }         // str, '' when absent
```
`context` / `regulation_scope` default to `""` when the caller omits them — UseCaseClassify
still infers tags from `query` alone (with conservative defaults).

### DI interfaces (`src/services/service.py`)

```python
@runtime_checkable
class KnowledgeStore(Protocol):
    # returns top-k passages: [{"id": str, "source": str, "text": str, "score": float}]
    def search(self, query: str, tags: list[str], top_k: int = 6) -> list[dict]: ...

@runtime_checkable
class LLMClient(Protocol):
    def generate(self, prompt: str) -> str: ...   # narrative only (ArchitectureMatch/SandboxDesign)
```

`classify_usecase(query) -> {industries, sensitivity, regulations}` is a pure deterministic
function in the same module. Production binds the real vector KB + platform LLM (via
`ctx.secrets`); tests bind `InMemoryKnowledgeStore` + `StubLLMClient`.

### State Definition (`src/schemas/state.py`)

| Field | Type | Purpose | Written by |
|-------|------|---------|-----------|
| query / context / regulation_scope | Optional[str] | caller input (NL design question, optional deploy-env/doc-mix/industry, optional regulation scope) | caller |
| validated_input | Optional[str] | normalized query JSON (passed to inner graph) | QueryNormalize |
| usecase_tags | Optional[str] | SECRET/customer/internal × industry × regulation JSON | UseCaseClassify (inner) |
| retrieved_patterns / retrieval_count | Optional[str] / Optional[int] | top-k passages JSON (with provenance) + count | PatternRetrieve (inner) |
| architecture_skeleton | Optional[str] | markitdown invocation pattern + extraction-layer JSON | ArchitectureMatch (inner) |
| sandbox_spec | Optional[str] | subprocess-sandbox / container-security spec JSON | SandboxDesign (inner) |
| answer / citations | Optional[str] | Markdown architecture proposal + citation JSON | ComplianceOutput (inner) → merge_output |
| validation_status / disclaimer_present / redaction_count / audit_logged | Optional[str/bool/int/bool] | S-3/S-4 outcome | ResponseValidate |
| error_code / error_message | Optional[str] | error propagation (inner + outer) | any node / on_subgraph_error |

**State Constraints (mandatory):**
- Flat TypedDict only; no Pydantic / dataclass (msgpack); shared outer + inner
- No credentials / customer document content in State — the agent advises on design, never ingests real documents (extraction is the separate Tool's job); ResponseValidate redacts any leaked secret/PII
- InvocationContext via `config["configurable"]` only

## Framework Utilization

### Shared Components Used
- [x] InvocationContext — via `config["configurable"]`; auto-injected into the inner graph by `GraphNode`
- [x] SecurityViolationError — framework S-1/S-2 `@final` gates
- [x] S-2: framework `@final` `_security_gate_input()` on FunctionNodes; QueryNormalize NFKC/injection/size in `execute()`. **The `main` GraphNode's S-2/S-3 are a deliberate no-op passthrough — and it is safe because:** (a) the GraphNode receives input only from `pre_process` (QueryNormalize), which already applied the S-1/S-2 input boundary; (b) every inner node is a `FunctionNode`, so each runs the framework `@final` S-2 gate again on its own execute(); (c) the inner output re-enters the outer `post_process` (ResponseValidate), which applies the S-3 output gate (citation + disclaimer + redaction). So no input/output crosses a boundary ungated — the GraphNode passthrough adds no gap. This is the GraphNode pattern sanctioned in the platform security-layer contract (S-2/S-3 hook pattern).
- [x] S-3: domain S-3 in `ResponseValidateNode.execute()` — citation completeness + **legal disclaimer** + redaction + hallucination heuristic
- [x] S-4: `emit_trace_event()` in UseCaseClassify, PatternRetrieve, ArchitectureMatch, SandboxDesign, ComplianceOutput, ResponseValidate. Lifecycle events framework-owned.

### Composition Pattern
- **Pattern:** **Cat 2 — `GraphNode` (inner `BaseGraph`)** in the `main` slot
- **Error propagation strategy (criterion #9):** inner per-node → `error_code` self-skip; inner graph failure → GraphNode `error_strategy="handle"` → `on_subgraph_error()`; outer ResponseValidate always runs S-3 + S-4
- Inner topology branch = grounding gate (no architecture advice without retrieved grounding) — the Cat 2 value + a hallucination safeguard

## Import Isolation Confirmation
- [x] Template does not import `agenticstar` (Level 0) — PB-4 AST scan
- [x] Import targets: `framework/` (AgentBaseGraph, BaseGraph, GraphNode, FunctionNode, AgentState, AgentStatus, InvocationContext) + `shared/` (audit_logger via wrapper) only

## Design Decision Record

| Decision | Option A | Option B | Chosen | Rationale |
|----------|----------|----------|--------|-----------|
| Cat | Cat 1 (flat composite) | **Cat 2 (GraphNode + inner BaseGraph)** | **Cat 2** | specific job-to-be-done (ingestion-pipeline design advisory) with a grounding-conditional branch; CoE Cat 2 pattern mandatory |
| Inner base | AgentBaseGraph | **BaseGraph** | **BaseGraph** | custom topology with branching; no inner pre/main/post slots needed |
| Scope | also run extraction | **advisory only** | **advisory only** | actual markitdown CLI execution / file I/O is a separate Tool/Service (SoT §4) — this agent advises on design |
| Ungrounded path | best-effort LLM answer | **insufficient-grounding safe answer** | **safe answer** | never hallucinate architecture/compliance advice without retrieved grounding (hallucination safeguard) |
| GraphNode error_strategy | propagate | **handle** | **handle** | advisory must still emit (degraded) answer + disclaimer + audit on inner failure (criterion #9) |
| Backends | committed | DI Protocol + stub | **DI Protocol** | offline-testable; prod binds the real vector KB + platform LLM |
| LLM binding (ADR-7) | silent `StubLLMClient` default | explicit `llm_client` > `config["llm"]` (adapted) > none, **no silent stub** | **config seam, no stub** | the Marketplace runner constructs `Graph(config=...)`; a stub bound by default runs on the Marketplace even with Azure keys registered |

### ADR-7 — `config["llm"]` seam through the GraphNode, deterministic proposal kept (2026-09-03)

- **Context.** The Marketplace runner constructs the agent as `agent_cls(config=<config.yaml>)`
  — no `llm_client` keyword — and the fleet entry point can only place a lazily-resolved Azure
  client under `config["llm"]` (an object answering `invoke(prompt)` / `complete(prompt)`). Before
  this ADR the outer graph read only the keyword, and the inner `ArchitectureMatchNode` /
  `SandboxDesignNode` bound a `StubLLMClient` when nothing reached them, so the Marketplace
  deployment ran on the stub regardless of registered keys (a canned "Recommended design…"
  sentence appeared as the narrative in every proposal).
- **Decision.** `service.resolve_llm_client(explicit, config)` in the outer `__init__`: explicit
  `llm_client` kw > `config["llm"]` (adapted by `service.ConfigLLMAdapter` to `generate(prompt)`;
  an unusable object raises at construction; client exceptions are never swallowed — the GraphNode's
  `error_strategy="handle"` reports them as `WORKFLOW_ERROR`) > none. The resolved client is threaded
  exactly as before: `DocIngestionWorkflowGraphNode(llm_client=...)` → inner
  `DocIngestionWorkflowGraph(config={"llm_client": ...})` → the two narrative nodes. The stub is
  never bound by default (tests inject it).
- **Deterministic proposal KEPT.** The skeleton, sandbox controls, chunking guidance and citations
  are rule-based (`ComplianceOutput` assembles, no LLM), so a bare run still answers with citations.
  With no LLM bound the narrative nodes set `narrative=""` (the assembler already omits empty
  narratives) and emit the S-4 event `llm_not_configured` (field names only). No `error_code` is set
  because the proposal is complete.
- **Consequences.** `tests/integration/test_full_path_invoke.py` pins the bare-construction path on
  the real SDK, the threading of `config["llm"]` through the GraphNode into the inner nodes (the
  scripted reply appears in the output), the explicit-kw precedence, and the raising-client outcome.
