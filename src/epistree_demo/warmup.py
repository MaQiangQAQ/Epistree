"""Warmup data — load pre-warmed GraphBundles into the app.

Warmup files are created by the warmup script and stored in DATA_DIR
as JSON files. The app loads them at startup so they're available
even when offline or budget-exhausted.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .config import settings
from .models import GraphBundle, SearchItem

logger = logging.getLogger(__name__)


def load_warmup_topics() -> dict[str, dict]:
    """Load all warmup files from DATA_DIR.

    Returns dict of {topic_name: {"bundle": GraphBundle, "sources": [SearchItem]}}
    """
    warmup_dir = Path(settings.data_dir)
    result: dict[str, dict] = {}

    if not warmup_dir.exists():
        return result

    for fpath in sorted(warmup_dir.glob("warmup_*.json")):
        try:
            with open(fpath) as f:
                data = json.load(f)
            topic = data.get("topic", "")
            if not topic:
                continue

            bundle = GraphBundle.model_validate(data["bundle"])
            sources = [SearchItem.model_validate(s) for s in data.get("sources", [])]

            result[topic] = {"bundle": bundle, "sources": sources}
            logger.info("Loaded warmup topic: %s (%d sources)", topic, len(sources))
        except Exception as exc:
            logger.warning("Failed to load warmup file %s: %s", fpath, exc)

    return result


def get_warmup_topics_list() -> list[str]:
    """Return list of available warmup topic names."""
    data = load_warmup_topics()
    return list(data.keys())
