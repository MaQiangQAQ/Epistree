"""Tests for QueryBuilder — NFKC, dedup, length limits."""

from epistree_demo.query_builder import build_queries


class TestQueryBuilder:

    def test_basic_queries(self):
        queries = build_queries("RAG")
        assert len(queries) == 4
        assert "RAG" in queries
        assert "RAG 起源" in queries
        assert "RAG 争议" in queries
        assert "RAG 变化" in queries

    def test_nfkc_normalization(self):
        # Full-width characters should be normalized
        queries = build_queries("ＲＡＧ")  # full-width RAG
        assert "RAG" in queries[0]  # NFKC normalizes full-width to half-width

    def test_whitespace_collapse(self):
        queries = build_queries("  RAG  技术  ")
        assert queries[0] == "RAG 技术"

    def test_too_short(self):
        import pytest
        with pytest.raises(ValueError):
            build_queries("A")

    def test_too_long(self):
        import pytest
        with pytest.raises(ValueError):
            build_queries("A" * 51)

    def test_max_queries(self):
        queries = build_queries("RAG", max_queries=2)
        assert len(queries) <= 2
