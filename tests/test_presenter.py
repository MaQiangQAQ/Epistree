"""Tests for Presenter — Cytoscape element conversion."""

from epistree_demo.models import (
    CandidateRelation,
    ClaimNode,
    EventNode,
    GraphBundle,
    QuestionNode,
    SourceRef,
    SearchItem,
)
from epistree_demo.presenter import present


def make_source(source_id: str = "zhihu:answer:1", title: str = "Title",
                text: str = "Content") -> SearchItem:
    return SearchItem(
        content_id="1", content_type="answer", title=title,
        content_text=text, url="https://www.zhihu.com/answer/1",
        author_name="Author", source_id=source_id,
    )


class TestPresenter:

    def test_empty_bundle(self):
        bundle = GraphBundle(topic="Test", questions=[], claims=[], events=[], relations=[])
        sources = [make_source()]
        nodes, edges = present(bundle, sources)
        # Only topic node (no source refs to link sources)
        assert len(nodes) == 1
        assert len(edges) == 0  # No edges without nodes to connect

    def test_topic_node_present(self):
        bundle = GraphBundle(topic="MyTopic", questions=[], claims=[], events=[], relations=[])
        sources = []
        nodes, _edges = present(bundle, sources)
        topic_nodes = [n for n in nodes if n["data"]["node_type"] == "topic"]
        assert len(topic_nodes) == 1
        assert topic_nodes[0]["data"]["label"] == "MyTopic"

    def test_questions_and_claims(self):
        bundle = GraphBundle(
            topic="Test",
            questions=[QuestionNode(id="q1", text="?", source_refs=[SourceRef(source_id="zhihu:answer:1")])],
            claims=[ClaimNode(id="c1", text="Claim.", question_id="q1",
                              source_refs=[SourceRef(source_id="zhihu:answer:1")], confidence=0.8)],
            events=[],
            relations=[],
        )
        sources = [make_source()]
        nodes, edges = present(bundle, sources)
        types = {n["data"]["node_type"] for n in nodes}
        assert "question" in types
        assert "claim" in types

    def test_source_nodes_included(self):
        bundle = GraphBundle(
            topic="Test",
            questions=[QuestionNode(id="q1", text="?", source_refs=[SourceRef(source_id="zhihu:answer:1")])],
            claims=[],
            events=[],
            relations=[],
        )
        sources = [make_source("zhihu:answer:1")]
        nodes, _edges = present(bundle, sources)
        source_nodes = [n for n in nodes if n["data"]["node_type"] == "source"]
        assert len(source_nodes) == 1
        assert source_nodes[0]["data"]["source_id"] == "zhihu:answer:1"

    def test_relation_edge_dashed(self):
        bundle = GraphBundle(
            topic="Test",
            questions=[QuestionNode(id="q1", text="?", source_refs=[SourceRef(source_id="zhihu:answer:1")])],
            claims=[
                ClaimNode(id="c1", text="C1", question_id="q1",
                          source_refs=[SourceRef(source_id="zhihu:answer:1")], confidence=0.8),
                ClaimNode(id="c2", text="C2", question_id="q1",
                          source_refs=[SourceRef(source_id="zhihu:answer:2")], confidence=0.8),
            ],
            events=[],
            relations=[
                CandidateRelation(id="r1", source_node_id="c1", target_node_id="c2",
                                  relation_type="contradicts",
                                  source_refs=[SourceRef(source_id="zhihu:answer:1")],
                                  confidence=0.7),
            ],
        )
        sources = [make_source("zhihu:answer:1"), make_source("zhihu:answer:2")]
        _nodes, edges = present(bundle, sources)
        dashed_edges = [e for e in edges if "dashed" in e["classes"].split()]
        assert len(dashed_edges) == 1
        assert dashed_edges[0]["data"]["edge_type"] == "contradicts"
        assert "rel-contradicts" in dashed_edges[0]["classes"].split()

    def test_towering_tree_geometry(self):
        bundle = GraphBundle(
            topic="TreeTest",
            questions=[
                QuestionNode(id="q1", text="Q1", source_refs=[SourceRef(source_id="zhihu:answer:1")]),
                QuestionNode(id="q2", text="Q2", source_refs=[SourceRef(source_id="zhihu:answer:2")]),
            ],
            claims=[
                ClaimNode(id="c1", text="C1", question_id="q1", source_refs=[SourceRef(source_id="zhihu:answer:1")], confidence=0.9),
                ClaimNode(id="c2", text="C2", question_id="q2", source_refs=[SourceRef(source_id="zhihu:answer:2")], confidence=0.85),
            ],
            events=[
                EventNode(id="e1", text="E1", occurred_at="2020", source_refs=[SourceRef(source_id="zhihu:answer:1")], confidence=0.95),
            ],
            relations=[],
        )
        sources = [make_source("zhihu:answer:1"), make_source("zhihu:answer:2")]
        nodes, edges = present(bundle, sources)
        
        by_type = {}
        for n in nodes:
            by_type.setdefault(n["data"]["node_type"], []).append(n)
            assert "position" in n
            assert "x" in n["position"] and "y" in n["position"]

        # Roots (events) should have y > 0 (downwards)
        for e_node in by_type["event"]:
            assert e_node["position"]["y"] > 0, f"Event y should be positive (downward root), got {e_node['position']['y']}"

        # Canopy (questions and claims) should have y < 0 (upward canopy)
        for q_node in by_type["question"]:
            assert q_node["position"]["y"] < 0, f"Question y should be negative (upward bough), got {q_node['position']['y']}"
        for c_node in by_type["claim"]:
            assert c_node["position"]["y"] < 0, f"Claim y should be negative (upward canopy), got {c_node['position']['y']}"

