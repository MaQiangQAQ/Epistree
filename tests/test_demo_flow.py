"""End-to-end Demo flow test — uses static fixture, no network access."""

import json
from pathlib import Path

from epistree_demo.models import (
    GraphBundle,
    SearchItem,
    flat_to_graph_bundle,
    FlatGraphBundle,
    FlatNode,
    FlatRelation,
)
from epistree_demo.presenter import present

FIXTURE_DIR = Path(__file__).parent / "fixtures"


class TestDemoFlow:

    def test_fixture_to_cytoscape_elements(self):
        """Load fixture, convert to FlatGraphBundle, to GraphBundle, to Cytoscape.

        This is the core offline demo flow test.
        """
        # Load fixture
        with open(FIXTURE_DIR / "zhihu_search.json") as f:
            fixture = json.load(f)

        # Parse items using same structure as zhihu_client
        items_raw = (fixture.get("Data", {}) or {}).get("Items", [])
        sources = []
        for raw in items_raw:
            item = SearchItem(
                content_id=str(raw.get("ContentID", "")),
                content_type=(raw.get("ContentType", "unknown") or "").lower(),
                title=raw.get("Title", ""),
                content_text=raw.get("ContentText", ""),
                url=raw.get("Url", "https://example.com"),
                author_name=raw.get("AuthorName", ""),
                vote_up_count=raw.get("VoteUpCount", 0),
                comment_count=raw.get("CommentCount", 0),
                authority_level=raw.get("AuthorityLevel"),
                ranking_score=raw.get("RankingScore"),
            )
            sources.append(item)

        assert len(sources) == 3

        # Create a manual flat bundle (simulating LLM output extraction)
        flat = FlatGraphBundle(
            topic="RAG",
            nodes=[
                FlatNode(id="q1", type="question", text="RAG的核心技术是什么？",
                         source_ids=["zhihu:answer:-4522481628176134219"]),
                FlatNode(id="c1", type="claim", text="RAG通过检索+生成提升准确性",
                         question_id="q1", source_ids=["zhihu:answer:-4522481628176134219"],
                         confidence=0.9),
                FlatNode(id="c2", type="claim", text="RAG适合实时更新场景",
                         question_id="q1", source_ids=["zhihu:answer:8423067469552355783"],
                         confidence=0.85),
                FlatNode(id="e1", type="event", text="RAG在企业客服中广泛应用",
                         source_ids=["zhihu:answer:5737808419566936700"], confidence=0.7),
            ],
            relations=[
                FlatRelation(id="r1", source_node_id="c1", target_node_id="c2",
                             relation_type="supports",
                             source_ids=["zhihu:answer:-4522481628176134219", "zhihu:answer:8423067469552355783"],
                             confidence=0.8),
            ],
        )

        # Convert
        bundle = flat_to_graph_bundle(flat)
        assert isinstance(bundle, GraphBundle)
        assert bundle.topic == "RAG"

        # Present
        nodes, edges = present(bundle, sources)
        assert len(nodes) > 0
        assert len(edges) > 0

        # Verify source nodes exist
        source_node_ids = {n["data"]["source_id"] for n in nodes
                          if n["data"]["node_type"] == "source"}
        assert "zhihu:answer:-4522481628176134219" in source_node_ids

        # Verify edges reference valid node IDs
        node_ids = {n["data"]["id"] for n in nodes}
        for e in edges:
            assert e["data"]["source"] in node_ids
            assert e["data"]["target"] in node_ids

    def test_presenter_no_orphan_edges(self):
        """No edge should reference a non-existent node."""
        bundle = GraphBundle(topic="Orphan", questions=[], claims=[], events=[], relations=[])
        sources = []
        nodes, edges = present(bundle, sources)
        node_ids = {n["data"]["id"] for n in nodes}
        for e in edges:
            assert e["data"]["source"] in node_ids, f"Source {e['data']['source']} not found"
            assert e["data"]["target"] in node_ids, f"Target {e['data']['target']} not found"
