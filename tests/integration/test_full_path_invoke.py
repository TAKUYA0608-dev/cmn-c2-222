# CMN-C2-222 — Integration: the production path, on the real SDK.
#
# Every test builds the agent the way the Marketplace runner does —
# `Graph(config=<config/config.yaml dict>)`, no keyword backends, no llm_client — or
# adds one dependency at a time to prove a specific seam, then goes through the
# framework's own `invoke()` (outer AgentBaseGraph → GraphNode → inner workflow).
# Pinned here: the bare run answers deterministically (grounded skeleton + sandbox
# controls + cited passages, no LLM needed), `config["llm"]` is threaded through the
# GraphNode into the inner narrative nodes and shapes the answer, an explicit
# `llm_client=` wins over it, and with no LLM the narrative is omitted — never a stub.

import json
import pathlib

import pytest
import yaml

from framework.schemas.invocation_context import InvocationContext
from framework.schemas.trust_level import TrustLevel

from src.graph.graph import Graph
from src.services.service import ConfigLLMAdapter, StubLLMClient, resolve_llm_client

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_QUESTION = "Customer contract PDF + Excel into AI-KB, legal industry, APPI-safe?"
_STUB_PREFIX = "Recommended design based on the retrieved guidance"


def _runner_config() -> dict:
    """The dict the runner passes: config/config.yaml as loaded, nothing added."""
    cfg = yaml.safe_load((_REPO_ROOT / "config" / "config.yaml").read_text(encoding="utf-8"))
    assert isinstance(cfg, dict) and cfg, "config/config.yaml must load to a non-empty dict"
    return cfg


def _ctx() -> InvocationContext:
    return InvocationContext(caller_id="marketplace-user", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)


def _invoke(agent, message: str = _QUESTION) -> dict:
    agent.compile()
    return agent.invoke(message, ctx=_ctx(), input_context={"conversation_history": []})


def _is_success(out: dict) -> bool:
    return str(out.get("status", "")).lower().endswith("success")


def _inner_llms(agent) -> list:
    """The LLM objects held by the inner narrative nodes the GraphNode wires."""
    agent.compile()
    inner = agent._nodes["main"].get_subgraph()
    inner.compile()  # idempotent; registers the inner nodes exactly as the runtime does
    return [inner._nodes["architecture_match"]._llm, inner._nodes["sandbox_design"]._llm]


class _ScriptedLLM:
    """A config["llm"]-shaped client: `invoke(prompt) -> str`, no `generate`."""

    def __init__(self, reply: str = "SCRIPTED: isolate the markitdown worker and never trust its output.") -> None:
        self.prompts: list[str] = []
        self.reply = reply

    def invoke(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.reply


class _RaisingLLM:
    def invoke(self, prompt: str) -> str:
        raise RuntimeError("upstream LLM failure")


class TestBareRunnerConstruction:
    """`Graph(config=...)` alone — exactly what the Marketplace runner does."""

    def test_answers_deterministically_without_any_llm(self):
        agent = Graph(config=_runner_config())
        assert agent._llm_client is None, "a bare graph must not bind a stub LLM silently"
        assert _inner_llms(agent) == [None, None], "the inner narrative nodes bound a stub"
        out = _invoke(agent)
        assert _is_success(out), out.get("status")
        assert out.get("output"), "a runner-shaped invocation produced no output"
        assert out.get("error_code") is None, out.get("error_code")
        assert (out.get("retrieval_count") or 0) >= 1
        assert "Architecture Proposal" in out["output"]
        assert json.loads(out.get("citations") or "[]"), "no citations reached the caller"
        assert _STUB_PREFIX not in out["output"], "a stub narrative leaked through"
        assert json.loads(out["architecture_skeleton"])["narrative"] == ""
        assert json.loads(out["sandbox_spec"])["narrative"] == ""


class TestConfigLlmSeam:
    """`config["llm"]` reaches the inner nodes through the GraphNode; explicit kw wins."""

    def test_scripted_config_llm_shapes_the_narrative(self):
        llm = _ScriptedLLM()
        agent = Graph(config={**_runner_config(), "llm": llm})
        for held in _inner_llms(agent):
            assert isinstance(held, ConfigLLMAdapter) and held._client is llm
        out = _invoke(agent)
        assert _is_success(out) and out.get("error_code") is None, out
        assert len(llm.prompts) == 2, "expected one call per narrative node (architecture + sandbox)"
        assert "markitdown ingestion architecture" in llm.prompts[0]
        assert "sandbox controls" in llm.prompts[1]
        assert llm.reply in out["output"], "the answer does not derive from the client's reply"
        assert json.loads(out["architecture_skeleton"])["narrative"] == llm.reply

    def test_explicit_llm_client_wins_over_config_llm(self):
        config_llm = _ScriptedLLM(reply="FROM CONFIG")
        out = _invoke(
            Graph(config={**_runner_config(), "llm": config_llm}, llm_client=StubLLMClient("FROM EXPLICIT KW"))
        )
        assert "FROM EXPLICIT KW" in out["output"]
        assert config_llm.prompts == [], "config['llm'] was called although an explicit client was given"

    def test_raising_config_llm_surfaces_as_a_named_error(self):
        out = _invoke(Graph(config={**_runner_config(), "llm": _RaisingLLM()}))
        # GraphNode error_strategy="handle": the inner failure becomes a named degradation.
        assert _is_success(out)
        assert out.get("error_code") == "WORKFLOW_ERROR", out.get("error_code")
        assert out.get("output"), "a degraded run must still publish a non-empty output"
        assert _STUB_PREFIX not in out["output"]

    def test_adapter_prefers_invoke_then_complete_and_coerces_message_content(self):
        class _Msg:
            content = "reply text"

        class _CompleteOnly:
            def complete(self, prompt, **kw):
                return _Msg()

        assert ConfigLLMAdapter(_ScriptedLLM(reply="x")).generate("p") == "x"
        assert ConfigLLMAdapter(_CompleteOnly()).generate("p") == "reply text"
        with pytest.raises(TypeError):
            ConfigLLMAdapter(object())
        with pytest.raises(TypeError):
            Graph(config={**_runner_config(), "llm": object()})
        assert resolve_llm_client(None, {"llm": None}) is None
        assert resolve_llm_client(None, None) is None
        stub = StubLLMClient()
        assert resolve_llm_client(None, {"llm": stub}) is stub  # already speaks generate()
        assert resolve_llm_client(stub, {"llm": _ScriptedLLM()}) is stub
