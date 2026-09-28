"""CMN-C2-222 — service layer: knowledge store + LLM (DI) + deterministic classification.

The retrieval knowledge base (markitdown docs + APPI (現行法) + 電子帳簿保存法 + industry
guidelines + subprocess-sandbox best-practices) and the LLM are injected as Protocols so
the template is offline-testable. Production binds the real vector KB + platform LLM
(via ``ctx.secrets``); tests bind the in-memory stubs.

Use-case classification (`classify_usecase`) is a **pure deterministic** keyword map — the
LLM is used only for the architecture / sandbox narrative, never to decide the regulation
or industry tags. This is a design-ADVISORY agent: it never ingests or extracts real
documents (that is a separate Tool); the KB holds design guidance passages only.

No ``agenticstar`` (Level 0) imports; no ``framework.*`` dependency — pure domain logic.
"""

from __future__ import annotations

import re
from typing import Any, Protocol, runtime_checkable

# ── Classification keyword maps (deterministic) ─────────────────────────────────
_INDUSTRY = {
    "legal": ["legal", "law", "contract", "litigation", "法務", "契約"],
    "finance": ["finance", "bank", "fsa", "金融", "銀行", "証券"],
    "medical": ["medical", "health", "clinical", "patient", "医療", "薬機"],
    "education": ["education", "school", "student", "教育", "学校"],
}
_SENSITIVITY = {
    "secret": ["secret", "confidential", "極秘", "機密"],
    "customer": ["customer", "client", "personal", "顧客", "個人情報"],
}
_REGULATION = {
    "APPI": ["appi", "個人情報", "personal information"],
    "電子帳簿保存法": ["電子帳簿", "電帳", "e-document", "電子保存"],
    "GDPR": ["gdpr", "eu", "europe"],
}

# ── Lexical tokenizer (ported from a sibling template) ────────
# ★ 日本語 KB × 語彙検索の構造欠陥 (本番 Pod で実証):
# str.split() は空白区切りなので日本語の文が 1 トークンに潰れ、日本語質問は
# 何も引けない。CJK 文字 bigram + 機能語除去で解決する。
_CJK_RE = re.compile(r"[぀-ヿ一-鿿ｦ-ﾟ]+")
_WORD_RE = re.compile(r"[a-z0-9][a-z0-9_.-]*")

# Function words carry no topical signal but are dense in prose, so they let an
# out-of-scope question score highly on any chunk (328 measured: "What is the
# weather in Tokyo today?" outscored a correct Japanese question on stopword
# overlap alone). Removal is what keeps the zero-hit refusal path honest.
_STOPWORDS = frozenset(
    """
a an the and or but if then than that this these those of in on at to for from by with
without about into over under as is are was were be been being do does did doing have
has had having i you he she it we they me my your his her its our their what which who
whom when where why how should would could can may might must will shall not no yes so
such only own same too very just also there here up down out off again further once
""".split()
)

# Japanese function-word bigrams. Bigram indexing makes a short function-word
# query dangerous rather than merely imprecise: "ある" yields the single term
# {ある} and any chunk containing it scores 1.0. Dropping these before scoring
# makes such a query yield no terms at all — the correct answer for a query
# with no topical content (ported from a sibling template).
_JA_FUNCTION_BIGRAMS = frozenset(
    """
する すれ すな すべ して した しな しま しょ され せる れる られ でき きる こう
ある あり あっ ない なく なし いる いた いま なる なっ なり なら れば
これ それ あれ どれ この その あの どの どう そう ああ いう
れは れを れが れに れで はこ はそ はど はな はで はと
こと もの ため とき よう ところ ばあ あい
です ます ませ まし だっ であ でし でも ても とも
から まで より ので のに には では との への とし につ いて ついて ため
がで がい がな をど をす をし にす にお おけ ける
うす うか うし うも いか いき かた たら
るこ るの るか ると るが るを るに るで るは るも るま
たこ たの たか たと たが たを たに
のこ のか のと のが のを のに のは のも
なの なか なと なが なに ので うな あな
""".split()
)


def lexical_terms(text: str) -> set[str]:
    """Topical lexical terms: content words plus CJK character bigrams.

    Punctuation is stripped so "retrieval?" and "retrieval" are the same term,
    and function words are dropped in both scripts (`_STOPWORDS`,
    `_JA_FUNCTION_BIGRAMS`). A query left with no terms retrieves nothing,
    which is the intended outcome for a query with no topical content.
    """
    terms = {t for t in _WORD_RE.findall(text.lower()) if t not in _STOPWORDS}
    for run in _CJK_RE.findall(text):
        if len(run) == 1:
            terms.add(run)
        else:
            terms |= {run[i : i + 2] for i in range(len(run) - 1)} - _JA_FUNCTION_BIGRAMS
    return terms


def _match_tags(text: str, table: dict[str, list[str]]) -> list[str]:
    low = text.lower()
    return [tag for tag, kws in table.items() if any(k in low for k in kws)]


def classify_usecase(query: str) -> dict[str, Any]:
    """Deterministic SECRET/customer × industry × regulation tagging from the NL query."""
    industries = _match_tags(query, _INDUSTRY) or ["general"]
    sensitivity = _match_tags(query, _SENSITIVITY) or ["internal"]
    regulations = _match_tags(query, _REGULATION)
    # finance/medical/legal imply APPI by default (conservative)
    if not regulations and any(i in ("finance", "medical", "legal") for i in industries):
        regulations = ["APPI"]
    return {"industries": industries, "sensitivity": sensitivity, "regulations": regulations or ["APPI"]}


@runtime_checkable
class KnowledgeStore(Protocol):
    """Design-guidance KB. `search` returns top-k passages, each shaped:

    {"id": str, "source": str, "text": str, "official_ref": str,
     "effective_date": str | None, "score": float}
    """

    def search(self, query: str, tags: list[str], top_k: int = 6) -> list[dict[str, Any]]: ...


@runtime_checkable
class LLMClient(Protocol):
    """LLM boundary — `generate(prompt) -> str` (narrative only)."""

    def generate(self, prompt: str) -> str: ...


class InMemoryKnowledgeStore:
    """In-memory KnowledgeStore (lexical ranking) for tests / local runs.

    Ranking uses `lexical_terms` (content words + CJK bigrams + function-word
    removal, ported from a sibling template) so Japanese questions actually retrieve;
    the previous ``str.split()`` tokenizer collapsed a Japanese sentence into a
    single term and every Japanese question returned zero passages.
    """

    def __init__(self) -> None:
        self._passages: list[dict[str, Any]] = []

    def add(self, passages: list[dict[str, Any]]) -> None:
        self._passages.extend(passages)

    def search(self, query: str, tags: list[str], top_k: int = 6) -> list[dict[str, Any]]:
        q = lexical_terms(query)
        for tag in tags:
            q |= lexical_terms(str(tag))
        scored = []
        for p in self._passages:
            words = lexical_terms(str(p.get("text", ""))) | lexical_terms(str(p.get("source", "")))
            overlap = len(q & words)
            if overlap:
                scored.append({**p, "score": round(overlap / max(len(q), 1), 4)})
        scored.sort(key=lambda p: p["score"], reverse=True)
        return scored[:top_k]


class StubLLMClient:
    """Deterministic stub LLM (narrative only) — tests / local runs, NEVER bound by default.

    The graph resolves the LLM as explicit `llm_client` > `config["llm"]` > none
    (`resolve_llm_client`); with none, ArchitectureMatch / SandboxDesign omit their
    narrative and the deterministic, cited proposal is still assembled.
    """

    def __init__(self, canned: str | None = None) -> None:
        self._canned = canned

    def generate(self, prompt: str) -> str:
        if self._canned is not None:
            return self._canned
        head = prompt.strip().splitlines()[0][:160] if prompt.strip() else ""
        return f"Recommended design based on the retrieved guidance. {head}"


# ── LLM seam: config["llm"] → LLMClient ───────────────────────────────────────
def _as_text(result: Any) -> str:
    """Coerce a client reply to text: str as-is, message-like objects via `.content`."""
    if isinstance(result, str):
        return result
    content = getattr(result, "content", None)
    if isinstance(content, str):
        return content
    return "" if result is None else str(result)


class ConfigLLMAdapter:
    """Adapt a `config["llm"]` object to this template's `LLMClient` Protocol.

    The fleet entry point places a lazily-resolved chat client under `config["llm"]`
    that answers `invoke(prompt) -> str` (and `complete(prompt, **kw) -> str`); this
    template's nodes speak `generate(prompt) -> str`. The adapter forwards to `invoke`
    first, then `complete`, and never swallows the client's exceptions — a configured
    but failing LLM must surface, not silently degrade.
    """

    def __init__(self, client: Any) -> None:
        call = getattr(client, "invoke", None)
        if not callable(call):
            call = getattr(client, "complete", None)
        if not callable(call):
            raise TypeError(
                "config['llm'] must expose generate(prompt), invoke(prompt) or "
                f"complete(prompt); got {type(client).__name__}"
            )
        self._client = client
        self._call = call

    def generate(self, prompt: str) -> str:
        return _as_text(self._call(prompt))


def resolve_llm_client(explicit: LLMClient | None, config: Any) -> LLMClient | None:
    """Precedence: explicit `llm_client` kw > `config["llm"]` > None.

    None means "no LLM bound". This template's proposal is deterministic (grounded
    skeleton + sandbox controls + cited passages), so a bare run still answers; the
    LLM only adds the narrative sentences, which are omitted (recorded via S-4
    `llm_not_configured`) when no LLM is bound — never substituted by a stub. An
    object under `config["llm"]` that answers none of generate/invoke/complete raises
    at construction (misconfiguration is not a reason to degrade quietly).
    """
    if explicit is not None:
        return explicit
    candidate = config.get("llm") if isinstance(config, dict) else None
    if candidate is None:
        return None
    if isinstance(candidate, LLMClient):
        return candidate
    return ConfigLLMAdapter(candidate)


def seed_knowledge_store() -> InMemoryKnowledgeStore:
    """Offline design-guidance KB seeded with verifiable records only.

    Every record carries an ``official_ref`` that is one of exactly three
    verifiable forms — a statute number, a NAMED external document
    (organisation + 「document title」), or an explicit template-owned
    operational baseline — because a compliance-adjacent template must not
    present unverifiable legal facts as its bare-Graph default.
    The former seed cited "Art.19" of a non-existent 2026 APPI amendment; the
    statutory anchor for repurposing customer documents into an AI knowledge
    base is the CURRENT Act's restriction on use beyond the specified purpose
    (第18条). Versionless guidance records say the omission is deliberate
    (確証の無い版・改正日を断定しないため). Production replaces this store with
    the real curated vector KB; the record shape is identical.
    """
    store = InMemoryKnowledgeStore()
    _APPI_REF = "個人情報の保護に関する法律（平成15年法律第57号）"
    _EGOV = "e-Gov 法令ID 415AC0000000057"
    _TEMPLATE_BASELINE = (
        "本テンプレートの運用設計ベースライン（外部の公的文書を出典としない。" "特定文書・版は意図的に記載しない）"
    )
    store.add(
        [
            {
                # 運用レコードは a sibling template の承認済み先例に合わせ、無名の外部権威に
                # 帰属させず、テンプレ所有の設計ベースラインとして持つ (帰属の確証が
                # 無いままの出典主張は検証不能なため)。
                "id": "mk-01",
                "source": "Template operational guidance (運用) — markitdown invocation",
                "text": (
                    "markitdown converts Office docs (Word/Excel/PDF/PowerPoint) to markdown via a "
                    "subprocess CLI; run it behind a sandbox boundary and treat its output as untrusted. "
                    "markitdown サブプロセス 変換 Office 文書 取り込み サンドボックス"
                ),
                "official_ref": _TEMPLATE_BASELINE,
                "effective_date": None,
            },
            {
                # 旧 seed は存在しない「2026 年改正 APPI の第19条」として顧客文書の取り扱い
                # 義務を提示していた。正しい現行法のアンカー: 顧客文書 (個人情報) を AI
                # ナレッジベースへ転用する行為に効くのは、現行 APPI の目的外利用の制限
                # (第18条 — 特定された利用目的の達成に必要な範囲を超える取扱いには
                # あらかじめ本人の同意が必要)。アクセス制御・保存ポリシーといった運用
                # 統制は条文の主張にせず、sandbox / template baseline レコード側に残す。
                "id": "appi-a18",
                "source": "APPI (in force)",
                "text": (
                    "personal information in customer documents may not be handled beyond the scope "
                    "necessary to achieve the specified purpose of use without the principal's prior "
                    "consent; repurposing existing customer records into an AI knowledge base needs "
                    "that purpose check "
                    "個人情報 顧客 契約書 目的外利用 本人の同意 利用目的 ナレッジベース 取り込み"
                ),
                "official_ref": f"{_APPI_REF}第18条 ({_EGOV})",
                # 令和2年法律第44号による改正の全面施行日 (現行法として参照する基準日)。
                "effective_date": "2022-04-01",
            },
            {
                # 条番号は確証を持たないため主張しない — 法律番号 pin のみ。effective_date
                # も断定しない (改正が多層のため)。旧 id "edoc-07" は条番号を暗示しうる
                # ため改称。
                "id": "edoc-hozon",
                "source": "電子帳簿保存法",
                "text": (
                    "電子帳簿保存法 requires timestamping, search functionality, and tamper-evident "
                    "storage for electronically retained accounting documents. "
                    "電子帳簿 帳簿書類 保存 タイムスタンプ 検索機能 改ざん防止 電子取引"
                ),
                "official_ref": "電子帳簿保存法（平成10年法律第25号）",
                "effective_date": None,
            },
            {
                # 旧 seed の無名帰属 ("FSA guideline") を、名前付き外部文書 (FISC
                # 「安全対策基準」) へ是正。民間ガイダンスであり
                # 法令ではない。版は意図的に記載しない (確証なし)。
                "id": "fisc-anzen",
                "source": "FISC 安全対策基準",
                "text": (
                    "finance-industry document pipelines must isolate customer financial records and "
                    "log all access, per the named financial-industry security baseline. "
                    "金融機関 顧客データ アクセスログ 分離 安全対策基準"
                ),
                "official_ref": "金融情報システムセンター（FISC）「安全対策基準」（版は意図的に記載しない — 確証なし）",
                "effective_date": None,
            },
            {
                "id": "sbx-03",
                "source": "Template operational guidance (運用) — subprocess sandbox",
                "text": (
                    "run the extraction subprocess with a read-only rootfs, dropped Linux capabilities, "
                    "a seccomp profile, no network, and a non-root user (gVisor / K8s SecurityContext). "
                    "サンドボックス サブプロセス 分離 コンテナ"
                ),
                "official_ref": _TEMPLATE_BASELINE,
                "effective_date": None,
            },
            {
                "id": "chunk-05",
                "source": "Template operational guidance (運用) — chunking strategy",
                "text": (
                    "chunk extracted markdown by semantic heading with overlap; cap chunk size to fit "
                    "the embedding model context and preserve table structure. "
                    "チャンク 分割 見出し 埋め込み 表構造"
                ),
                "official_ref": _TEMPLATE_BASELINE,
                "effective_date": None,
            },
        ]
    )
    return store
