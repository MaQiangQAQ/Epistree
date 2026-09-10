"""Tests for Pydantic models — GraphBundle cross-reference validation."""

import json
from pathlib import Path

from epistree_demo.models import (
    CandidateRelation,
    ClaimNode,
    EventNode,
    FlatGraphBundle,
    FlatNode,
    FlatRelation,
    GraphBundle,
    QuestionNode,
    SourceRef,
    flat_to_graph_bundle,
    SearchItem,
    SearchResponse,
    validate_quote,
)

FIXTURE_DIR = Path(__file__).parent / "fixtures"


# ── helpers ──────────────────────────────────────────────────────────────

def make_source(source_id: str = "zhihu:answer:1") -> SourceRef:
    return SourceRef(source_id=source_id)


def make_question(id: str = "q1", text: str = "Test question?",
                  source_ids: list[str] | None = None) -> QuestionNode:
    return QuestionNode(id=id, text=text,
                        source_refs=[make_source(s) for s in (source_ids or ["zhihu:answer:1"])])


def make_claim(id: str = "c1", text: str = "Test claim.", question_id: str = "q1",
               source_ids: list[str] | None = None) -> ClaimNode:
    return ClaimNode(id=id, text=text, question_id=question_id,
                     source_refs=[make_source(s) for s in (source_ids or ["zhihu:answer:1"])],
                     confidence=0.8)


def make_event(id: str = "e1", text: str = "Test event",
               source_ids: list[str] | None = None) -> EventNode:
    return EventNode(id=id, text=text,
                     source_refs=[make_source(s) for s in (source_ids or ["zhihu:answer:1"])],
                     confidence=0.9)


# ── GraphBundle validation tests ─────────────────────────────────────────

class TestGraphBundle:

    def test_valid_bundle(self):
        bundle = GraphBundle(
            topic="Test",
            questions=[make_question()],
            claims=[make_claim()],
            events=[make_event()],
        )
        assert bundle.topic == "Test"

    def test_claim_with_missing_question(self):
        """Unknown question references are rejected, never synthesized."""
        import pytest
        with pytest.raises(ValueError, match="question_id"):
            GraphBundle(topic="Test", questions=[], claims=[make_claim(question_id="nonexistent")], events=[])

    def test_claim_without_source_refs(self):
        import pytest
        with pytest.raises(ValueError, match="has no source_refs"):
            GraphBundle(
                topic="Test",
                questions=[make_question()],
                claims=[ClaimNode(id="c1", text="No refs", question_id="q1",
                                  source_refs=[], confidence=0.5)],
            )

    def test_question_without_source_refs(self):
        import pytest
        with pytest.raises(ValueError, match="has no source_refs"):
            GraphBundle(
                topic="Test",
                questions=[QuestionNode(id="q1", text="?", source_refs=[])],
                claims=[make_claim()],
            )

    def test_relation_endpoints_must_be_claims(self):
        import pytest
        with pytest.raises(ValueError, match="not a Claim ID"):
            GraphBundle(
                topic="Test",
                questions=[make_question()],
                claims=[make_claim()],
                relations=[
                    CandidateRelation(
                        id="r1", source_node_id="nonexistent", target_node_id="c1",
                        relation_type="supports",
                        source_refs=[make_source()], confidence=0.5,
                    )
                ],
            )

    def test_source_refs_non_empty_for_events(self):
        import pytest
        with pytest.raises(ValueError, match="has no source_refs"):
            GraphBundle(
                topic="Test",
                questions=[make_question()],
                claims=[make_claim()],
                events=[EventNode(id="e1", text="e", source_refs=[], confidence=0.5)],
            )


# ── FlatGraphBundle → GraphBundle conversion tests ───────────────────────

class TestFlatToGraphBundle:

    def test_basic_conversion(self):
        flat = FlatGraphBundle(
            topic="Test",
            nodes=[
                FlatNode(id="q1", type="question", text="Q?", source_ids=["zhihu:answer:1"]),
                FlatNode(id="c1", type="claim", text="C1", question_id="q1",
                         source_ids=["zhihu:answer:1"], confidence=0.8),
            ],
            relations=[],
        )
        bundle = flat_to_graph_bundle(flat)
        assert len(bundle.questions) == 1
        assert len(bundle.claims) == 1
        assert bundle.claims[0].question_id == "q1"

    def test_auto_question_generation(self):
        import pytest
        with pytest.raises(ValueError, match="question_id"):
            FlatGraphBundle(
                topic="Test",
                nodes=[FlatNode(id="c1", type="claim", text="C1",
                                source_ids=["zhihu:answer:1"], confidence=0.8)],
                relations=[],
            )

    def test_flat_relation_to_canonical(self):
        flat = FlatGraphBundle(
            topic="Test",
            nodes=[
                FlatNode(id="q1", type="question", text="Q?", source_ids=["zhihu:answer:1"]),
                FlatNode(id="c1", type="claim", text="C1", question_id="q1",
                         source_ids=["zhihu:answer:1"], confidence=0.8),
                FlatNode(id="c2", type="claim", text="C2", question_id="q1",
                         source_ids=["zhihu:answer:2"], confidence=0.8),
            ],
            relations=[
                FlatRelation(id="r1", source_node_id="c1", target_node_id="c2",
                             relation_type="supports",
                             source_ids=["zhihu:answer:1", "zhihu:answer:2"],
                             confidence=0.7),
            ],
        )
        bundle = flat_to_graph_bundle(flat)
        assert len(bundle.relations) == 1
        assert bundle.relations[0].relation_type == "supports"

    def test_relation_on_nonexistent_claim_fails(self):
        import pytest
        with pytest.raises(ValueError, match="not a Claim"):
            FlatGraphBundle(
                topic="Test",
                nodes=[
                    FlatNode(id="q1", type="question", text="Q?", source_ids=["zhihu:answer:1"]),
                    FlatNode(id="c1", type="claim", text="C1", question_id="q1",
                             source_ids=["zhihu:answer:1"], confidence=0.8),
                ],
                relations=[
                    FlatRelation(id="r1", source_node_id="c1", target_node_id="nonexistent",
                                 relation_type="supports",
                                 source_ids=["zhihu:answer:1"], confidence=0.5),
                ],
            )

    def test_duplicate_node_id_fails(self):
        import pytest
        with pytest.raises(ValueError, match="Duplicate"):
            FlatGraphBundle(
                topic="Test",
                nodes=[
                    FlatNode(id="n1", type="question", text="Q?", source_ids=["zhihu:answer:1"]),
                    FlatNode(id="n1", type="claim", text="C1", question_id="n1",
                             source_ids=["zhihu:answer:1"], confidence=0.5),
                ],
                relations=[],
            )


# ── Quote validation tests ───────────────────────────────────────────────

class TestQuoteValidation:

    def test_valid_quote_kept(self):
        ref = SourceRef(source_id="zhihu:answer:1", quote="Transformer")
        result = validate_quote(ref, "基于Transformer架构")
        assert result.quote == "Transformer"

    def test_invalid_quote_dropped(self):
        ref = SourceRef(source_id="zhihu:answer:1", quote="Nonexistent")
        result = validate_quote(ref, "基于Transformer架构")
        assert result.quote is None

    def test_none_quote_unchanged(self):
        ref = SourceRef(source_id="zhihu:answer:1", quote=None)
        result = validate_quote(ref, "基于Transformer架构")
        assert result.quote is None


# ── SearchItem / SearchResponse tests ────────────────────────────────────

class TestSearchModels:

    def test_source_id_generated(self):
        item = SearchItem(
            content_id="123", content_type="answer",
            title="Test", content_text="...",
            url="https://www.zhihu.com/answer/123",
            author_name="Author",
        )
        assert item.source_id == "zhihu:answer:123"

    def test_load_fixture(self):
        with open(FIXTURE_DIR / "zhihu_search.json") as f:
            data = json.load(f)
        items_raw = (data.get("Data", {}) or {}).get("Items", [])
        items = []
        for raw in items_raw:
            item = SearchItem(
                content_id=str(raw.get("ContentID", "")),
                content_type=(raw.get("ContentType", "unknown") or "").lower(),
                title=raw.get("Title", ""),
                content_text=raw.get("ContentText", ""),
                url=raw.get("Url", "https://example.com"),
                author_name=raw.get("AuthorName", ""),
                edit_time=None if not raw.get("EditTime") else None,  # parsed in zhihu_client
                vote_up_count=raw.get("VoteUpCount", 0),
                comment_count=raw.get("CommentCount", 0),
                authority_level=raw.get("AuthorityLevel"),
                ranking_score=raw.get("RankingScore"),
            )
            items.append(item)
        assert len(items) == 3
        assert items[0].source_id == "zhihu:answer:-4522481628176134219"
