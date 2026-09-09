"""CytoscapePresenter — domain objects → Dash Cytoscape elements.

Matches section 5.6 of DEMO_DESIGN.md.
"""

from __future__ import annotations

from .models import (
    CandidateRelation,
    ClaimNode,
    EventNode,
    GraphBundle,
    QuestionNode,
    SearchItem,
)


def present(bundle: GraphBundle, sources: list[SearchItem]) -> tuple[list[dict], list[dict]]:
    """Convert GraphBundle + sources to Cytoscape nodes and edges.

    Returns (nodes, edges) lists suitable for Dash Cytoscape `elements`.
    """
    source_map = {s.source_id: s for s in sources}
    nodes: list[dict] = []
    edges: list[dict] = []
    node_ids: set[str] = set()

    # Topic node
    topic_id = f"topic:{_safe_id(bundle.topic)}"
    nodes.append({
        "data": {
            "id": topic_id,
            "label": bundle.topic[:40],
            "node_type": "topic",
            "full_text": bundle.topic,
        },
        "classes": "topic",
    })
    node_ids.add(topic_id)

    # Question nodes
    for q in bundle.questions:
        qid = _ensure_id(q.id, "question", node_ids)
        nodes.append({
            "data": {
                "id": qid,
                "label": q.text[:50],
                "node_type": "question",
                "full_text": q.text,
                "source_refs": [r.model_dump() for r in q.source_refs],
            },
            "classes": "question",
        })
        edges.append({
            "data": {
                "id": f"e:{qid}->{topic_id}",
                "source": qid,
                "target": topic_id,
                "label": "answers",
                "edge_type": "contains",
            },
            "classes": "solid",
        })

    # Claim nodes
    claim_id_map: dict[str, str] = {}
    for c in bundle.claims:
        cid = _ensure_id(c.id, "claim", node_ids)
        claim_id_map[c.id] = cid
        nodes.append({
            "data": {
                "id": cid,
                "label": c.text[:60],
                "node_type": "claim",
                "full_text": c.text,
                "confidence": c.confidence,
                "source_refs": [r.model_dump() for r in c.source_refs],
            },
            "classes": "claim",
        })
        # Edge: Claim -> Question
        qid_target = f"question:{_safe_id(c.question_id)}"
        if qid_target in node_ids:
            edges.append({
                "data": {
                    "id": f"e:{cid}->{qid_target}",
                    "source": cid,
                    "target": qid_target,
                    "label": "contains",
                    "edge_type": "contains",
                },
                "classes": "solid",
            })

    # Event nodes
    for e in bundle.events:
        eid = _ensure_id(e.id, "event", node_ids)
        nodes.append({
            "data": {
                "id": eid,
                "label": f"{e.text[:40]} ({e.occurred_at or '?'})",
                "node_type": "event",
                "full_text": e.text,
                "occurred_at": e.occurred_at or "",
                "confidence": e.confidence,
                "source_refs": [r.model_dump() for r in e.source_refs],
            },
            "classes": "event",
        })
        # Event -> Topic
        edges.append({
            "data": {
                "id": f"e:{eid}->{topic_id}",
                "source": eid,
                "target": topic_id,
                "label": "mentioned_in",
                "edge_type": "contains",
            },
            "classes": "solid",
        })

    # Candidate relations (edges between claims)
    for r in bundle.relations:
        src = claim_id_map.get(r.source_node_id)
        tgt = claim_id_map.get(r.target_node_id)
        if src and tgt:
            edges.append({
                "data": {
                    "id": f"e:{r.id}",
                    "source": src,
                    "target": tgt,
                    "label": r.relation_type,
                    "edge_type": r.relation_type,
                    "confidence": r.confidence,
                    "source_refs": [s.model_dump() for s in r.source_refs],
                },
                "classes": "dashed",
            })

    # Source nodes (linked to topic)
    seen_source_ids = _collect_all_source_ids(bundle)
    for sid in seen_source_ids:
        src = source_map.get(sid)
        if not src:
            continue
        sid_clean = _safe_id(sid)
        snid = f"source:{sid_clean}"
        if snid in node_ids:
            continue
        node_ids.add(snid)
        title = src.title or src.author_name or sid[:20]
        nodes.append({
            "data": {
                "id": snid,
                "label": title[:40],
                "node_type": "source",
                "full_text": src.content_text[:300],
                "url": str(src.url),
                "author_name": src.author_name,
                "edit_time": src.edit_time.isoformat() if src.edit_time else None,
                "source_id": sid,
            },
            "classes": "source",
        })
        edges.append({
            "data": {
                "id": f"e:{snid}->{topic_id}",
                "source": snid,
                "target": topic_id,
                "label": "mentioned_in",
                "edge_type": "contains",
            },
            "classes": "solid",
        })

    return nodes, edges


# ── helpers ───────────────────────────────────────────────────────────────

def _safe_id(text: str) -> str:
    """Produce a Cytoscape-safe ID from arbitrary text."""
    import hashlib
    if not text:
        return "unknown"
    if len(text) < 64 and all(c.isalnum() or c in "-_" for c in text):
        return text
    return hashlib.md5(text.encode("utf-8")).hexdigest()[:12]


def _ensure_id(original_id: str, prefix: str, existing: set[str]) -> str:
    candidate = f"{prefix}:{_safe_id(original_id)}"
    if candidate not in existing:
        existing.add(candidate)
        return candidate
    # collision rarely happens, but handle it
    for i in range(100):
        candidate = f"{prefix}:{_safe_id(original_id)}_{i}"
        if candidate not in existing:
            existing.add(candidate)
            return candidate
    return candidate  # fallback


def _collect_all_source_ids(bundle: GraphBundle) -> set[str]:
    ids: set[str] = set()
    for q in bundle.questions:
        for r in q.source_refs:
            ids.add(r.source_id)
    for c in bundle.claims:
        for r in c.source_refs:
            ids.add(r.source_id)
    for e in bundle.events:
        for r in e.source_refs:
            ids.add(r.source_id)
    for r in bundle.relations:
        for sr in r.source_refs:
            ids.add(sr.source_id)
    return ids
