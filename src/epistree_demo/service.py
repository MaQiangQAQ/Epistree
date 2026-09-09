"""DemoService — main pipeline orchestrator.

Matches section 4 architecture diagram (DemoService).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from .config import settings
from .db import EpistreeDB
from .extractor import KnowledgeExtractor
from .models import GraphBundle, SearchItem, SearchResponse
from .presenter import present
from .query_builder import build_queries, sha256_of
from .selector import compute_input_hash, compute_payload_sha256, deduplicate_and_select
from .zhihu_client import ZhihuSearchClient


class DemoService:
    """Orchestrates the main pipeline: query → search → dedup → extract → present."""

    def __init__(self) -> None:
        self.db = EpistreeDB(settings.epistree_db_path)
        self.db.init_schema()
        self.client = ZhihuSearchClient()
        self.extractor = KnowledgeExtractor()

    # ── Step 1: Build queries ───────────────────────────────────────

    def build_queries(self, topic: str) -> list[str]:
        return build_queries(topic, max_queries=settings.demo_max_queries)

    # ── Step 2–3: Execute search, persist ──────────────────────────

    def execute_search(
        self,
        run_id: str,
        queries: list[str],
    ) -> tuple[list[SearchItem], dict]:
        """Execute searches, persist observations, return deduplicated sources.

        Returns (selected_sources, stats).
        """
        real_calls = 0
        cache_hits = 0
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        query_results: list[tuple[str, list[SearchItem]]] = []

        for query_text in queries:
            query_sha = sha256_of(query_text)
            query_id = self.db.get_or_create_query(query_text, query_sha)

            # Execute search (with budget check)
            try:
                resp, from_cache = self._search_with_budget(query_text, today)
            except PermissionError:
                raise  # auth failure — let caller handle
            except RuntimeError as exc:
                resp = SearchResponse(code=-1, data=[], search_hash_id=None, raw_json=None)
                from_cache = False
                self.db.update_run_status(
                    run_id, "running",
                    error_code="UPSTREAM_TEMPORARY_ERROR",
                    error_message=str(exc),
                )
                continue

            if not from_cache:
                real_calls += 1
                self.db.increment_daily_calls(today)
            else:
                cache_hits += 1

            # Persist query observation
            obs_id = self.db.create_query_observation(
                run_id=run_id,
                query_id=query_id,
                from_cache=from_cache,
                is_expired=False,
                search_hash_id=resp.search_hash_id,
                item_count=len(resp.data),
            )

            # Persist sources and snapshots
            for rank, item in enumerate(resp.data):
                self.db.upsert_source(
                    source_id=item.source_id,
                    content_id=item.content_id,
                    content_type=item.content_type,
                    canonical_url=str(item.url),
                )
                snap_id = str(uuid.uuid4())
                real_snap_id = self.db.insert_snapshot(
                    snapshot_id=snap_id,
                    source_id=item.source_id,
                    payload_sha256=compute_payload_sha256(item),
                    title=item.title,
                    content_text=item.content_text,
                    author_name=item.author_name,
                    edit_time=item.edit_time.isoformat() if item.edit_time else None,
                    metrics_json=json.dumps({
                        "vote_up_count": item.vote_up_count,
                        "comment_count": item.comment_count,
                        "authority_level": item.authority_level,
                    }),
                    raw_json=json.dumps(resp.raw_json or {}),
                )
                self.db.link_source_to_query_observation(
                    query_observation_id=obs_id,
                    source_snapshot_id=real_snap_id,
                    rank=rank,
                    ranking_score=item.ranking_score,
                )

            query_results.append((query_text, resp.data))

            # Update run stats after each query
            self.db.update_run_status(
                run_id,
                "running",
                real_api_calls=real_calls,
                cache_hits=cache_hits,
            )

        # Dedup and select
        selected = deduplicate_and_select(
            query_results,
            max_sources=settings.demo_max_sources,
        )

        all_items = [item for _, items in query_results for item in items]
        stats = {
            "real_api_calls": real_calls,
            "cache_hits": cache_hits,
            "total_items": len(all_items),
            "unique_selected": len(selected),
        }
        return selected, stats

    def _search_with_budget(self, query: str, today: str) -> tuple[SearchResponse, bool]:
        """Execute search respecting local daily budget.

        If budget exhausted, only cached results are used.
        """
        budget_remaining = self._budget_available(today)
        # If budget ≤ 0, still try — the cached session may return stale data
        return self.client.search(query, count=10)

    # ── Step 4: Extract knowledge ──────────────────────────────────

    def extract_knowledge(
        self,
        topic: str,
        sources: list[SearchItem],
    ) -> GraphBundle:
        """Check extraction cache first; if miss, call model."""
        input_hash = compute_input_hash(
            sources, topic,
            prompt_version=settings.prompt_version,
            graph_schema_version=settings.graph_schema_version,
            model_name=settings.llm_model,
        )

        cached = self.db.get_bundle_by_hash(input_hash)
        if cached:
            return GraphBundle.model_validate_json(cached["bundle_json"])

        bundle = self.extractor.extract(topic, sources)

        bundle_id = str(uuid.uuid4())
        self.db.save_bundle(
            bundle_id=bundle_id,
            input_sha256=input_hash,
            prompt_version=settings.prompt_version,
            model_name=settings.llm_model,
            bundle_json=bundle.model_dump_json(),
        )

        return bundle

    # ── Step 5: Present as Cytoscape elements ─────────────────────

    def present_graph(self, bundle: GraphBundle, sources: list[SearchItem]) -> dict:
        nodes, edges = present(bundle, sources)
        return {"nodes": nodes, "edges": edges}

    # ── Budget ─────────────────────────────────────────────────────

    def _budget_available(self, today: str) -> int:
        used = self.db.get_daily_calls(today)
        return max(0, settings.demo_daily_call_limit - used)

    def get_budget_remaining(self) -> int:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        return self._budget_available(today)

    # ── Lifecycle ──────────────────────────────────────────────────

    def create_run(self, topic: str) -> str:
        return self.db.create_run(topic)

    def get_run(self, run_id: str) -> dict | None:
        return self.db.get_run(run_id)

    def complete_run(self, run_id: str, bundle: GraphBundle, stats: dict) -> None:
        bundle_id = str(uuid.uuid4())
        self.db.update_run_status(
            run_id,
            "completed",
            graph_bundle_id=bundle_id,
            real_api_calls=stats.get("real_api_calls", 0),
            cache_hits=stats.get("cache_hits", 0),
        )

    def fail_run(self, run_id: str, error_code: str, error_message: str) -> None:
        self.db.update_run_status(run_id, "failed", error_code=error_code, error_message=error_message)
