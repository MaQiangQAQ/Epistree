"""SourceSelector — cross-query ContentID dedup and round-robin selection.

Matches section 5.3–5.4 of DEMO_DESIGN.md.
"""

from __future__ import annotations

import hashlib
import json
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
    """Hash the exact normalized model input, including all model-visible fields."""
    source_inputs = []
    for s in sorted(sources, key=lambda item: item.source_id):
        source_inputs.append({
            "source_id": s.source_id, "title": s.title, "author_name": s.author_name,
            "edit_time": s.edit_time.isoformat() if s.edit_time else None,
            "content_text": s.content_text[:1500],
            "truncated_for_model": len(s.content_text) > 1500,
        })
    raw = json.dumps({
        "topic": topic, "sources": source_inputs, "prompt_version": prompt_version,
        "graph_schema_version": graph_schema_version, "model_name": model_name,
        "input_truncation_version": "first-1500-v1",
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def compute_payload_sha256(item: SearchItem) -> str:
    raw = f"{item.title}|{item.content_text}|{item.author_name}|{item.edit_time}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
