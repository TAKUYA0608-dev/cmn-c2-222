# CMN-C2-222 — Unit/E2E Tests: seed legal provenance + bilingual retrieval
#
# The default seed of a compliance-adjacent template must not present
# unverifiable legal facts, and the provenance must reach the caller;
# applied to sibling templates on the same
# basis). These tests keep the invented "Art.19 of a 2026 APPI amendment" — and
# any other unsourced legal identifier — from being reintroduced into the
# bare-Graph default, and pin the article mapping (use beyond the specified
# purpose = Art.18).

import json
import re

from src.services.service import seed_knowledge_store

_LAW_REF = re.compile(r"法律第\d+号")
# An external-authority reference is only verifiable when it NAMES the document
# (「…」-quoted title). A bare organisation name ("FSA guideline") attributes
# content to an authority without anything a reader can check — the same shape
# as the invented amendment, one step milder — so it is rejected here. Records
# that cite no external source at all must say so explicitly (template-owned
# operational guidance; a sibling template's seed precedent).
_NAMED_EXTERNAL_DOC = re.compile(
    r"(FISC|NISC|METI|経済産業省|内閣サイバーセキュリティセンター|金融情報システムセンター|個人情報保護委員会|デジタル庁).*「.+」"
)
_TEMPLATE_OWNED = re.compile(r"本テンプレートの運用設計ベースライン")


def _records():
    return seed_knowledge_store()._passages


class TestSeedProvenance:
    def test_every_seed_record_has_a_verifiable_official_ref(self):
        records = _records()
        assert len(records) >= 5, "default seed unexpectedly small"
        for rec in records:
            ref = rec.get("official_ref", "")
            assert ref and (_LAW_REF.search(ref) or _NAMED_EXTERNAL_DOC.search(ref) or _TEMPLATE_OWNED.search(ref)), (
                f"seed record {rec.get('id')} must cite a statute number, a "
                f"NAMED external document, or declare itself template-owned "
                f"guidance — vague authority attribution is not verifiable: {ref!r}"
            )

    def test_seed_carries_no_invented_appi_amendment(self):
        # Banned substrings built by concatenation so a repo-wide sweep for the
        # invented-amendment identifier stays at zero hits outside this guard.
        banned = ("appi" + "2026", "appi " + "2026", "2026 amendment", "art." + "19")
        for rec in _records():
            blob = json.dumps(rec, ensure_ascii=False).lower()
            assert not any(
                b in blob for b in banned
            ), f"seed record {rec.get('id')} cites an unverifiable APPI amendment"

    def test_purpose_limitation_record_is_article_18(self):
        """Art.18 (restriction on use beyond the specified purpose) is the
        current-law anchor for repurposing customer documents into an AI
        knowledge base — the earlier seed hung this duty off an invented
        Art.19 of a non-existent 2026 amendment.
        """
        by_id = {r["id"]: r for r in _records()}
        assert "appi-a18" in by_id
        rec = by_id["appi-a18"]
        assert "平成15年法律第57号" in rec["official_ref"]
        assert "第18条" in rec["official_ref"]
        # Act as amended by 令和2年法律第44号, fully in force 2022-04-01.
        assert rec["effective_date"] == "2022-04-01"

    def test_domain_statute_pins_the_act_number_only(self):
        by_id = {r["id"]: r for r in _records()}
        rec = by_id["edoc-hozon"]
        assert "平成10年法律第25号" in rec["official_ref"]
        # No article number is asserted (no verified basis for one).
        assert "条" not in rec["official_ref"]
        assert rec["effective_date"] is None

    def test_finance_guidance_names_its_document(self):
        """The old seed attributed the finance baseline to an unnamed "FSA
        guideline" — an unverifiable authority claim. The record now cites the
        NAMED external document (FISC「安全対策基準」), versionless by design.
        """
        by_id = {r["id"]: r for r in _records()}
        rec = by_id["fisc-anzen"]
        assert _LAW_REF.search(rec["official_ref"]) is None, "guidance record must not cite an act number"
        assert "条" not in rec["official_ref"]
        assert _NAMED_EXTERNAL_DOC.search(rec["official_ref"])
        assert rec["effective_date"] is None

    def test_versionless_guidance_records_say_so_deliberately(self):
        for rec in _records():
            if rec["effective_date"] is None and _LAW_REF.search(rec["official_ref"]) is None:
                assert (
                    "意図的に記載しない" in rec["official_ref"]
                ), f"{rec['id']}: versionless guidance must state the omission is deliberate"


class TestBilingualRetrieval:
    """A Japanese-facing design-advisory KB must actually retrieve for Japanese
    questions. Before this fix the store tokenised with ``str.split()``, so a
    Japanese sentence collapsed into a single term and every Japanese question
    returned zero passages — the structural defect a sibling template hit in
    production. CJK bigrams + function-word removal fix it; the records carry
    EN/JP retrieval vocabulary so both scripts reach the same record.
    """

    _CASES = [
        ("顧客の個人情報の目的外利用に本人の同意は必要ですか", "appi-a18"),
        ("repurposing customer records into an AI knowledge base — consent required?", "appi-a18"),
        ("電子帳簿の保存要件とタイムスタンプを教えて", "edoc-hozon"),
        ("金融機関の顧客データのアクセスログと安全対策基準は？", "fisc-anzen"),
        ("markitdown で Office 文書をサンドボックス内で変換する設計は？", "mk-01"),
        ("markitdown subprocess sandbox conversion of Office docs", "mk-01"),
    ]

    def test_each_question_reaches_its_record_in_both_scripts(self):
        kb = seed_knowledge_store()
        for question, passage_id in self._CASES:
            hits = [h["id"] for h in kb.search(question, [], top_k=3)]
            assert passage_id in hits, f"{question!r} missed {passage_id}: got {hits}"

    def test_an_out_of_scope_japanese_question_retrieves_nothing(self):
        """Function-word removal is what makes this hold: without it a question
        sharing only particles scores highly on any passage.
        """
        assert seed_knowledge_store().search("今日の東京の天気は？", [], top_k=3) == []


class TestProvenanceReachesCallerEndToEnd:
    """Bare ``Graph().invoke()`` — the deployment default with no injected
    store/LLM — must answer a Japanese question through the FULL Cat 2 path
    (outer AgentBaseGraph → main-slot GraphNode → inner workflow) with
    citations that carry ``official_ref`` (provenance must reach the person
    reading the answer, not stop at the KB record).
    """

    def _invoke(self, question):
        from framework.schemas.invocation_context import InvocationContext, TrustLevel

        from src.graph.graph import Graph

        agent = Graph()
        ctx = InvocationContext(caller_id="e2e-provenance", caller_trust_level=TrustLevel.VERIFIED_EXTERNAL)
        return agent.invoke(question, ctx=ctx)

    def test_japanese_purpose_limitation_question_cites_article_18_with_official_ref(self):
        out = self._invoke(
            "顧客の個人情報を含む契約書を markitdown で AI ナレッジベースに取り込む場合、目的外利用の注意点は？"
        )
        assert out["status"] == "success"
        assert (out.get("retrieval_count") or 0) >= 1
        # The grounded inner path (classify → retrieve → architecture → sandbox →
        # compliance-output) actually ran — this is the Cat 2 GraphNode-in-main route.
        assert "Architecture Proposal" in out["answer"]
        assert out.get("architecture_skeleton")
        cits = json.loads(out.get("citations") or "[]")
        assert cits, "no citations reached the caller"
        for c in cits:
            assert c.get("official_ref"), f"citation {c.get('id')} reached the caller without provenance"
        a18 = [c for c in cits if c.get("id") == "appi-a18"]
        assert a18, f"Art.18 record not cited: {[c.get('id') for c in cits]}"
        assert "第18条" in a18[0]["official_ref"]
