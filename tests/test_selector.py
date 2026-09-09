"""Tests for SourceSelector — dedup, round-robin, 12-source limit."""

from epistree_demo.models import SearchItem
from epistree_demo.selector import deduplicate_and_select, compute_payload_sha256, compute_input_hash


def make_item(content_id: str, content_type: str = "answer",
              title: str = "T", text: str = "Content") -> SearchItem:
    return SearchItem(
        content_id=content_id,
        content_type=content_type,
        title=title,
        content_text=text,
        url=f"https://www.zhihu.com/answer/{content_id}",
        author_name="Author",
        ranking_score=0.9,
    )


class TestSelector:

    def test_basic_selection(self):
        q1_items = [make_item("1"), make_item("2")]
        q2_items = [make_item("3"), make_item("4")]
        selected = deduplicate_and_select([("q1", q1_items), ("q2", q2_items)], max_sources=12)
        assert len(selected) == 4

    def test_dedup_across_queries(self):
        q1_items = [make_item("1"), make_item("2")]
        q2_items = [make_item("2"), make_item("3")]  # item 2 duplicates
        selected = deduplicate_and_select([("q1", q1_items), ("q2", q2_items)], max_sources=12)
        assert len(selected) == 3  # 1, 2, 3

    def test_round_robin_fairness(self):
        q1_items = [make_item("1"), make_item("2"), make_item("3")]
        q2_items = [make_item("4")]
        selected = deduplicate_and_select([("q1", q1_items), ("q2", q2_items)], max_sources=12)
        # q2 has only 1 item, q1 has 3 — order should alternate
        assert selected[0].content_id == "1"
        assert selected[1].content_id == "4"

    def test_max_limit(self):
        items = [make_item(str(i)) for i in range(20)]
        selected = deduplicate_and_select([("q1", items)], max_sources=12)
        assert len(selected) <= 12

    def test_empty_input(self):
        selected = deduplicate_and_select([], max_sources=12)
        assert len(selected) == 0

    def test_different_content_types(self):
        a1 = make_item("1", content_type="answer")
        a2 = make_item("1", content_type="article")  # same ID but different type
        selected = deduplicate_and_select([("q1", [a1, a2])], max_sources=12)
        assert len(selected) == 2


class TestPayloadHash:

    def test_consistency(self):
        item = make_item("1")
        h1 = compute_payload_sha256(item)
        h2 = compute_payload_sha256(item)
        assert h1 == h2

    def test_different_content(self):
        i1 = make_item("1", text="Hello")
        i2 = make_item("1", text="World")
        assert compute_payload_sha256(i1) != compute_payload_sha256(i2)
