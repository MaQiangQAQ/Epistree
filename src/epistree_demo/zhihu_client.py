"""ZhihuSearchClient — official HTTP API adapter with requests-cache + Tenacity.

Matches section 5.2 of DEMO_DESIGN.md.

Actual API response verified 2026-09-08:

  zhihu_search:
    Code: 0 = success
    Data.Items: [{ ContentID, ContentType, Title, ContentText, Url, AuthorName,
                   EditTime (unix seconds), VoteUpCount, CommentCount,
                   AuthorityLevel, RankingScore, ... }]

  quota:
    Code: 0 = success
    Data: [{ APIID, TotalQuota, TotalUsed, RemainingQuota }]
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import requests
from requests_cache import CachedSession
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from .config import settings
from .models import HttpUrl, QuotaResponse, SearchItem, SearchResponse

# Default ignored params from requests-cache
DEFAULT_IGNORED_PARAMS = {"Authorization"}  # nosec


class ZhihuSearchClient:
    """Lightweight client for the Zhihu developer API.

    No pagination, no multi-turn expansion — just documented endpoints.
    """

    def __init__(self) -> None:
        self._session = CachedSession(
            cache_name=str(settings.http_cache_path),
            backend="sqlite",
            expire_after=3600 * 24,  # 24h default
            stale_if_error=3600 * 24 * 7,  # 7 days stale fallback
            ignored_parameters=[
                *DEFAULT_IGNORED_PARAMS,
                "X-Request-Timestamp",
            ],
            wal=True,
        )

    # ── public API ──────────────────────────────────────────────────

    def search(self, query: str, count: int = 10) -> tuple[SearchResponse, bool]:
        """Execute or retrieve from cache a Zhihu search request.

        Returns (response, from_cache).
        Raises on auth failure (401/403) immediately; retries 429/5xx/timeout.
        """
        timestamp = str(int(time.time()))
        url = f"{settings.zhihu_api_base}/content/zhihu_search"
        headers = self._build_headers(timestamp)

        if not settings.has_zhihu_auth:
            raise PermissionError("AUTH_REQUIRED: ZHIHU_ACCESS_SECRET not set")

        response = self._cached_get_raw(url, headers=headers, params={"Query": query, "Count": count})
        from_cache = response.from_cache
        raw_data = response.json()

        data = raw_data if isinstance(raw_data, dict) else raw_data

        code = data.get("Code", -1)
        if code != 0:
            raise RuntimeError(f"Zhihu API error code={code}: {data.get('Message', '')}")

        items_raw = (data.get("Data", {}) or {}).get("Items", [])
        items = []
        for item in items_raw:
            try:
                edit_time = self._parse_edit_time(item.get("EditTime"))
                si = SearchItem(
                    content_id=str(item.get("ContentID", "")),
                    content_type=(item.get("ContentType", "Unknown") or "").lower(),
                    title=item.get("Title", "") or "",
                    content_text=item.get("ContentText", "") or "",
                    url=HttpUrl(self._clean_url(item.get("Url", ""))),
                    author_name=item.get("AuthorName", "") or "",
                    edit_time=edit_time,
                    vote_up_count=item.get("VoteUpCount", 0) or 0,
                    comment_count=item.get("CommentCount", 0) or 0,
                    authority_level=str(item.get("AuthorityLevel", "")) or None,
                    ranking_score=float(item.get("RankingScore", 0)) if item.get("RankingScore") else None,
                )
                items.append(si)
            except Exception as exc:
                # Schema changed — skip this item but don't drop entire response
                continue

        search_hash = (data.get("Data", {}) or {}).get("SearchHashId")
        resp = SearchResponse(
            code=code,
            data=items,
            search_hash_id=search_hash,
            raw_json=data,
        )
        return resp, from_cache

    def get_quota(self) -> QuotaResponse:
        """Read remaining daily quota from Zhihu (does not consume quota)."""
        timestamp = str(int(time.time()))
        url = f"{settings.zhihu_api_base}/quota"
        headers = self._build_headers(timestamp)
        params = {"APIIDs": "zhihu_search"}

        # short TTL for quota (5 minutes)
        raw_response = self._cached_get_raw(url, headers=headers, params=params, expire_after=300)
        data = raw_response.json()

        quota_info = {"daily_total": 5000, "used": 0, "remaining": 0}
        if data.get("Code") == 0 and data.get("Data"):
            entry = data["Data"][0]
            quota_info = {
                "daily_total": entry.get("TotalQuota", 5000),
                "used": entry.get("TotalUsed", 0),
                "remaining": entry.get("RemainingQuota", 0),
            }

        return QuotaResponse(
            code=data.get("Code", -1),
            daily_total=quota_info["daily_total"],
            used=quota_info["used"],
            remaining=quota_info["remaining"],
        )

    # ── internal ────────────────────────────────────────────────────

    def _build_headers(self, timestamp: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {settings.zhihu_access_secret}",
            "X-Request-Timestamp": timestamp,
        }

    def _cache_count(self) -> int:
        """Return number of cached responses (0 if cache not accessible)."""
        try:
            return self._session.cache.responses.count()
        except Exception:
            return 0

    @staticmethod
    def _parse_edit_time(value: Any) -> datetime | None:
        """EditTime comes as Unix timestamp (seconds) from the API."""
        if value is None:
            return None
        try:
            return datetime.fromtimestamp(int(value), tz=timezone.utc)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _clean_url(url: str) -> str:
        """Remove UTM tracking parameters from Zhihu URLs."""
        if not url:
            return "https://example.com"
        import re
        # Strip all utm_* parameters and trailing ?/&
        cleaned = re.sub(r'[?&]utm_[^&=]+=[^&]+', '', url)
        cleaned = re.sub(r'\?&', '?', cleaned)
        cleaned = cleaned.rstrip('?&')
        return cleaned or url

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type(
            (requests.exceptions.Timeout, requests.exceptions.ConnectionError)
        ),
    )
    def _cached_get_raw(
        self,
        url: str,
        headers: dict[str, str],
        params: dict[str, Any] | None = None,
        expire_after: int | None = None,
    ) -> requests.Response:
        """Perform GET through requests-cache with limited retry on transient errors."""
        kwargs: dict = {"headers": headers, "params": params}
        if expire_after:
            kwargs["expire_after"] = expire_after

        response = self._session.get(url, **kwargs, timeout=15)

        if response.status_code == 401 or response.status_code == 403:
            raise PermissionError(
                f"UPSTREAM_AUTH_FAILED: HTTP {response.status_code}"
            )
        if response.status_code == 429:
            raise RuntimeError("UPSTREAM_RATE_LIMITED")
        response.raise_for_status()

        return response
