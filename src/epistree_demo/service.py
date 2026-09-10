"""Demo pipeline orchestration with explicit budget and provenance boundaries."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from .config import settings
from .db import EpistreeDB
from .extractor import KnowledgeExtractor
from .models import GraphBundle, SearchItem, validate_bundle_against_sources
from .presenter import present
from .query_builder import build_queries, sha256_of
from .selector import compute_input_hash, deduplicate_and_select
from .zhihu_client import SearchOutcome, ZhihuSearchClient


class DemoService:
    """Serial query/search/extract pipeline used by both Dash and tests."""

    def __init__(self, db: EpistreeDB | None = None, client: ZhihuSearchClient | None = None) -> None:
        self.db = db or EpistreeDB(settings.epistree_db_path)
        self.db.init_schema()
        self.client = client
        self.extractor: KnowledgeExtractor | None = None

    def build_queries(self, topic: str) -> list[str]:
        return build_queries(topic, max_queries=settings.demo_max_queries)

    def execute_search(self, run_id: str, queries: list[str]) -> tuple[list[SearchItem], dict]:
        """Search only the submitted, normalized queries and persist observations."""
        if len(queries) > settings.demo_max_queries:
            raise ValueError(f"At most {settings.demo_max_queries} queries are allowed")
        clean: list[str] = []
        seen: set[str] = set()
        for query in queries:
            q = " ".join(str(query).split())
            if len(q) > 200:
                raise ValueError("Each query must be at most 200 characters")
            if q and q not in seen:
                seen.add(q)
                clean.append(q)
        if not clean:
            raise ValueError("At least one query is required")
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        quota_state: dict[str, int | None] = {"remaining": None}

        def quota_guard() -> int | None:
            if quota_state["remaining"] is None:
                quota_state["remaining"] = self._client().get_quota().remaining
            return quota_state["remaining"]

        client = self.client or ZhihuSearchClient(
            reserve_attempt=lambda: self.db.reserve_daily_call(today, settings.demo_daily_call_limit),
            quota_remaining=quota_guard,
        )
        query_results: list[tuple[str, list[SearchItem]]] = []
        real_calls = cache_hits = stale_hits = 0
        warnings: list[str] = []
        for query_text in clean:
            query_id = self.db.get_or_create_query(query_text, sha256_of(query_text))
            outcome = client.search(query_text, count=10)
            if not isinstance(outcome, SearchOutcome):
                response, cached = outcome
                outcome = SearchOutcome(response, "fresh" if cached else "miss", datetime.now(timezone.utc), 0)
            real_calls += outcome.network_attempts
            if outcome.network_attempts and quota_state["remaining"] is not None:
                quota_state["remaining"] = max(
                    0, quota_state["remaining"] - outcome.network_attempts
                )
            if outcome.cache_state == "fresh":
                cache_hits += 1
            elif outcome.cache_state == "stale":
                stale_hits += 1
            if outcome.warning:
                warnings.append(outcome.warning)
            resp = outcome.response
            self.db.persist_search_observation(run_id, query_id, outcome, resp.data)
            query_results.append((query_text, resp.data))
            self.db.update_run_status(run_id, "running", real_api_calls=real_calls, cache_hits=cache_hits)
        selected = deduplicate_and_select(query_results, max_sources=settings.demo_max_sources)
        stats = {"real_api_calls": real_calls, "cache_hits": cache_hits, "stale_hits": stale_hits,
                 "total_items": sum(len(items) for _, items in query_results),
                 "unique_selected": len(selected), "warnings": warnings,
                 "official_remaining": quota_state["remaining"]}
        return selected, stats

    def _client(self) -> ZhihuSearchClient:
        return self.client or ZhihuSearchClient()

    def extract_knowledge(self, topic: str, sources: list[SearchItem]) -> GraphBundle:
        bundle, _bundle_id = self.extract_knowledge_with_id(topic, sources)
        return bundle

    def extract_knowledge_with_id(
        self, topic: str, sources: list[SearchItem]
    ) -> tuple[GraphBundle, str]:
        """Return the validated bundle together with its persisted ID."""
        input_hash = compute_input_hash(sources, topic, settings.prompt_version,
                                        settings.graph_schema_version, settings.llm_model)
        cached = self.db.get_bundle_by_hash(input_hash)
        if cached:
            return GraphBundle.model_validate_json(cached["bundle_json"]), cached["id"]
        if self.extractor is None:
            self.extractor = KnowledgeExtractor()
        bundle = self.extractor.extract(topic, sources)
        source_map = {s.source_id: s for s in sources}
        bundle = validate_bundle_against_sources(bundle, source_map)
        bundle_id = self.db.save_bundle(str(uuid.uuid4()), input_hash, settings.prompt_version,
                                        settings.llm_model, bundle.model_dump_json())
        return bundle, bundle_id

    def present_graph(self, bundle: GraphBundle, sources: list[SearchItem]) -> dict:
        nodes, edges = present(bundle, sources)
        return {"nodes": nodes, "edges": edges}

    def get_budget_remaining(self) -> int:
        date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return max(0, settings.demo_daily_call_limit - self.db.get_daily_calls(date))

    def create_run(self, topic: str) -> str:
        return self.db.create_run(topic)

    def get_run(self, run_id: str) -> dict | None:
        return self.db.get_run(run_id)

    def complete_run(self, run_id: str, bundle: GraphBundle, stats: dict, bundle_id: str) -> None:
        # Exact bundle_id is supplied by extract_knowledge_with_id.
        persisted = self.db.get_bundle_by_id(bundle_id)
        if persisted is None:
            raise RuntimeError("BUNDLE_NOT_PERSISTED")
        if GraphBundle.model_validate_json(persisted["bundle_json"]) != bundle:
            raise RuntimeError("BUNDLE_ID_MISMATCH")
        self.db.update_run_status(run_id, "completed", graph_bundle_id=bundle_id,
                                  real_api_calls=stats.get("real_api_calls", 0),
                                  cache_hits=stats.get("cache_hits", 0))

    def fail_run(self, run_id: str, error_code: str, error_message: str) -> None:
        if self.db.get_run(run_id):
            self.db.update_run_status(run_id, "failed", error_code=error_code, error_message=error_message)

    def cancel_run(self, run_id: str) -> None:
        if self.db.get_run(run_id):
            self.db.update_run_status(run_id, "cancelled")
