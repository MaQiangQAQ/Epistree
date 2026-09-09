"""SourceSelector — cross-query ContentID dedup and round-robin selection.

Matches section 5.3–5.4 of DEMO_DESIGN.md.
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict

from .models import SearchItem


def deduplicate_and_select(
    query_results: list[tuple[str, list[SearchItem]]],
    max_sources: int = 12,
) -> list[SearchItem]:
    """Select up to *max_sources* items via round-robin across queries.

    *query_results* is a list of (query_text, [SearchItem]).
    Returns deduplicated, round-robin-balanced list of SearchItem.
    """
    # Build per-query queues (ordered by API ranking)
    queues: list[list[SearchItem]] = []
    for _query, items in query_results:
        queues.append(list(items))

    seen_content_ids: set[str] = set()
    selected: list[SearchItem] = []
    source_id_order: OrderedDict[str, SearchItem] = OrderedDict()

    while len(selected) < max_sources:
        any_added = False
        for queue in queues:
            if len(selected) >= max_sources:
                break
            while queue:
                item = queue.pop(0)
                key = f"{item.content_type}:{item.content_id}"
                if key not in seen_content_ids:
                    seen_content_ids.add(key)
                    selected.append(item)
                    source_id_order[item.source_id] = item
                    any_added = True
                    break
        if not any_added:
            break

    return selected


def compute_input_hash(
    sources: list[SearchItem],
    topic: str,
    prompt_version: str,
    graph_schema_version: str,
    model_name: str,
) -> str:
    """Compute the extraction cache key — sha256 of sorted inputs + metadata."""
    sorted_sources = sorted(
        sources, key=lambda s: f"{s.source_id}:{s.content_id}"
    )
    parts = "|".join(
        f"{s.source_id}:{s.content_id}:{s.content_text[:1500]}"
        for s in sorted_sources
    )
    raw = f"{parts}|{topic}|{prompt_version}|{graph_schema_version}|{model_name}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_payload_sha256(item: SearchItem) -> str:
    raw = f"{item.title}|{item.content_text}|{item.author_name}|{item.edit_time}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
