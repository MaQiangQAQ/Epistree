"""Warmup data — load pre-warmed GraphBundles into the app.

Warmup files are created by the warmup script and stored in DATA_DIR
as JSON files. The app loads them at startup so they're available
even when offline or budget-exhausted.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from .config import settings
from .models import GraphBundle, SearchItem, validate_bundle_against_sources

logger = logging.getLogger(__name__)
WARMUP_ASSET_VERSION = "v1"


class WarmupAsset(BaseModel):
    asset_version: str = WARMUP_ASSET_VERSION
    topic: str
    queries: list[str] = Field(default_factory=list)
    bundle: GraphBundle
    sources: list[SearchItem] = Field(default_factory=list)
    generated_at: datetime | None = None
    data_observed_at: dict[str, str | None] = Field(default_factory=dict)
    prompt_version: str = "v1"
    model_name: str = ""
    graph_schema_version: str = "v1"

    @classmethod
    def load(cls, path: Path) -> "WarmupAsset":
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("asset_version") not in (None, WARMUP_ASSET_VERSION):
            raise ValueError(f"WARMUP_ASSET_INCOMPATIBLE: {data.get('asset_version')!r}")
        asset = cls.model_validate(data)
        validate_bundle_against_sources(asset.bundle, {s.source_id: s for s in asset.sources})
        return asset


def load_warmup_topics() -> dict[str, dict]:
    """Load all warmup files from DATA_DIR.

    Returns dict of {topic_name: {"bundle": GraphBundle, "sources": [SearchItem]}}
    """
    warmup_dir = Path(settings.data_dir)
    result: dict[str, dict] = {}

    files = list(sorted(warmup_dir.glob("warmup_*.json"))) if warmup_dir.exists() else []
    if not files:
        fallback_dir = Path("./.data")
        if fallback_dir.exists() and fallback_dir.resolve() != warmup_dir.resolve():
            files = list(sorted(fallback_dir.glob("warmup_*.json")))

    for fpath in files:
        try:
            with open(fpath) as f:
                data = json.load(f)
            topic = data.get("topic", "")
            if not topic:
                continue

            if data.get("asset_version") not in (None, WARMUP_ASSET_VERSION):
                raise ValueError(f"WARMUP_ASSET_INCOMPATIBLE: {data.get('asset_version')!r}")
            bundle = GraphBundle.model_validate(data["bundle"])
            sources = [SearchItem.model_validate(s) for s in data.get("sources", [])]
            validate_bundle_against_sources(bundle, {s.source_id: s for s in sources})

            result[topic] = {
                "bundle": bundle,
                "sources": sources,
                # Keep the authored query preview with the offline asset so
                # selecting a warmup topic never needs to rebuild or search.
                "queries": list(data.get("queries") or []),
            }
            logger.info("Loaded warmup topic: %s (%d sources)", topic, len(sources))
        except Exception as exc:
            logger.warning("Failed to load warmup file %s: %s", fpath, exc)

    return result


def get_warmup_topics_list() -> list[str]:
    """Return list of available warmup topic names."""
    data = load_warmup_topics()
    return list(data.keys())
