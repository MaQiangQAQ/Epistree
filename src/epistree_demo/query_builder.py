"""QueryBuilder — fixed-rule query generation without model calls.

Matches section 5.1 of DEMO_DESIGN.md.
"""

from __future__ import annotations

import hashlib
import unicodedata


def build_queries(topic: str, max_queries: int = 6) -> list[str]:
    """Construct a set of Zhihu search queries from the given topic.

    Returns deduplicated list of normalized queries, at most *max_queries*.
    """
    normalized = _normalize(topic)

    if not normalized or len(normalized) < 2 or len(normalized) > 50:
        raise ValueError(
            f"Topic must be 2–50 characters after normalization, got {len(normalized)}"
        )

    candidates = [
        normalized,
        f"{normalized} 起源",
        f"{normalized} 争议",
        f"{normalized} 变化",
    ]

    seen: set[str] = set()
    result: list[str] = []
    for q in candidates:
        nq = _normalize(q)
        if nq and nq not in seen:
            seen.add(nq)
            result.append(nq)
        if len(result) >= max_queries:
            break

    return result


def sha256_of(query: str) -> str:
    return hashlib.sha256(query.encode("utf-8")).hexdigest()


def _normalize(text: str) -> str:
    """NFKC normalization + strip + collapse whitespace."""
    text = unicodedata.normalize("NFKC", text.strip())
    return " ".join(text.split())
