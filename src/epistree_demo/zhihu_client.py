"""Small, cache-first adapter for the documented Zhihu Open API."""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import requests
from requests_cache import CachedSession

from .config import settings
from .models import HttpUrl, QuotaResponse, SearchItem, SearchResponse


@dataclass
class SearchOutcome:
    """Result contract used by the service and the UI."""

    response: SearchResponse
    cache_state: str  # fresh, stale, miss
    observed_at: datetime
    network_attempts: int = 0
    warning: str | None = None

    @property
    def from_cache(self) -> bool:
        return self.cache_state in {"fresh", "stale"}

    def __iter__(self):
        # Compatibility with the original ``response, from_cache`` contract.
        yield self.response
        yield self.from_cache


class ZhihuSearchClient:
    """Cache-first client. A caller may provide a reservation callback."""

    def __init__(self, reserve_attempt: Callable[[], bool] | None = None,
                 quota_remaining: Callable[[], int | None] | None = None) -> None:
        self._reserve_attempt = reserve_attempt
        self._quota_remaining = quota_remaining
        self._session = CachedSession(
            cache_name=str(settings.http_cache_path), backend="sqlite",
            expire_after=86400, stale_if_error=0,
            ignored_parameters=["Authorization", "X-Request-Timestamp"], wal=True,
            hooks={"response": [self._scrub_sensitive_request_headers]},
        )

    def search(self, query: str, count: int = 10) -> SearchOutcome:
        url = f"{settings.zhihu_api_base}/content/zhihu_search"
        params = {"Query": query, "Count": count}
        # Cache lookup deliberately precedes auth and quota checks.
        cached: requests.Response | None = None
        try:
            cached = self._session.get(url, params=params, only_if_cached=True, timeout=5)
        except Exception:
            cached = None
        # requests-cache represents a cache miss as HTTP 504 and normally
        # hides expired entries during an only-if-cached lookup. Read the
        # matching cached response through its public cache API so an expired
        # response remains available as a stale fallback.
        if cached is None or cached.status_code == 504:
            cached = self._get_cached_including_expired(url, params)
        cache_hit = (
            cached is not None
            and getattr(cached, "from_cache", False)
            and cached.status_code != 504
        )
        if cache_hit and getattr(cached, "is_expired", False) and not self._stale_eligible(cached):
            cached = None
            cache_hit = False
        if cache_hit:
            self._sanitize_cached_entry(url, params)
            state = "stale" if getattr(cached, "is_expired", False) else "fresh"
            if state == "fresh":
                return self._outcome(cached, state, 0)

        if not settings.has_zhihu_auth:
            if cache_hit:
                return self._outcome(cached, "stale", 0, "使用过期缓存：未配置知乎凭据")
            raise PermissionError("AUTH_REQUIRED: ZHIHU_ACCESS_SECRET not set")

        stale = cached if cache_hit else None
        if self._quota_remaining is not None:
            try:
                remaining = self._quota_remaining()
            except Exception as exc:
                if stale is not None:
                    return self._outcome(
                        stale, "stale", 0, "使用过期缓存：官方额度暂时不可用"
                    )
                raise RuntimeError(f"UPSTREAM_QUOTA_FAILED: {exc}") from exc
            if remaining is not None and remaining <= 0:
                if stale is not None:
                    return self._outcome(stale, "stale", 0, "使用过期缓存：官方搜索余额为 0")
                raise RuntimeError("QUOTA_EXHAUSTED: official Zhihu search quota")

        attempts = 0
        last_error: Exception | None = None
        for attempt in range(2):
            if self._reserve_attempt is not None and not self._reserve_attempt():
                if stale is not None:
                    return self._outcome(stale, "stale", attempts, "使用过期缓存：本地 Demo 额度已用尽")
                raise RuntimeError("QUOTA_EXHAUSTED: local demo daily limit")
            attempts += 1
            try:
                response = self._session.get(
                    url, headers=self._build_headers(), params=params,
                    timeout=15, force_refresh=True, expire_after=86400,
                )
                if response.status_code in (401, 403):
                    raise PermissionError(f"UPSTREAM_AUTH_FAILED: HTTP {response.status_code}")
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    msg = "UPSTREAM_RATE_LIMITED"
                    if retry_after:
                        msg += f"; Retry-After={retry_after}"
                    raise RuntimeError(msg)
                response.raise_for_status()
                self._sanitize_cached_entry(url, params)
                return self._outcome(response, "miss", attempts)
            except PermissionError:
                raise
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_error = exc
                if attempt == 0:
                    continue
            except requests.exceptions.HTTPError as exc:
                last_error = exc
                if attempt == 0 and getattr(exc.response, "status_code", 0) >= 500:
                    continue
            except RuntimeError:
                raise
        if stale is not None:
            return self._outcome(stale, "stale", attempts, f"使用过期缓存：{last_error}")
        raise RuntimeError(f"UPSTREAM_TEMPORARY_ERROR: {last_error}") from last_error

    def get_quota(self) -> QuotaResponse:
        if not settings.has_zhihu_auth:
            raise PermissionError("AUTH_REQUIRED: ZHIHU_ACCESS_SECRET not set")
        with self._session.cache_disabled():
            response = self._session.get(
                f"{settings.zhihu_api_base}/quota", headers=self._build_headers(),
                params={"APIIDs": "zhihu_search"}, timeout=15,
            )
        response.raise_for_status()
        data = response.json()
        entry = next(iter(data.get("Data") or []), {})
        if data.get("Code") != 0 or not entry:
            raise RuntimeError(f"UPSTREAM_QUOTA_FAILED: {data.get('Message', '')}")
        return QuotaResponse(
            code=data["Code"], daily_total=int(entry.get("TotalQuota", 0)),
            used=int(entry.get("TotalUsed", 0)), remaining=int(entry.get("RemainingQuota", 0)),
        )

    def _outcome(self, response: requests.Response, state: str, attempts: int,
                 warning: str | None = None) -> SearchOutcome:
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError("UPSTREAM_SCHEMA_CHANGED: invalid search response")
        if data.get("Code") != 0:
            raise RuntimeError(f"Zhihu API error code={data.get('Code', -1)}: {data.get('Message', '')}")
        items: list[SearchItem] = []
        invalid = 0
        for raw in (data.get("Data") or {}).get("Items", []):
            try:
                items.append(SearchItem(
                    content_id=str(raw["ContentID"]), content_type=str(raw.get("ContentType", "unknown")).lower(),
                    title=raw.get("Title", "") or "", content_text=raw.get("ContentText", "") or "",
                    url=HttpUrl(self._clean_url(raw.get("Url", ""))), author_name=raw.get("AuthorName", "") or "",
                    edit_time=self._parse_edit_time(raw.get("EditTime")),
                    vote_up_count=int(raw.get("VoteUpCount", 0) or 0), comment_count=int(raw.get("CommentCount", 0) or 0),
                    authority_level=str(raw.get("AuthorityLevel", "")) or None,
                    ranking_score=float(raw["RankingScore"]) if raw.get("RankingScore") is not None else None,
                ))
            except Exception:
                invalid += 1
        if not items and (data.get("Data") or {}).get("Items"):
            raise RuntimeError("UPSTREAM_SCHEMA_CHANGED: no search items could be parsed")
        if invalid:
            warning = warning or f"{invalid} 条来源字段异常，已跳过"
        observed_at = datetime.now(timezone.utc)
        created_at = getattr(response, "created_at", None)
        if isinstance(created_at, datetime):
            observed_at = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
        elif isinstance(created_at, str):
            try:
                observed_at = datetime.fromisoformat(created_at)
                if observed_at.tzinfo is None:
                    observed_at = observed_at.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return SearchOutcome(
            SearchResponse(code=0, data=items, search_hash_id=(data.get("Data") or {}).get("SearchHashId"), raw_json=data),
            state, observed_at, attempts, warning,
        )

    def _build_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {settings.zhihu_access_secret}", "X-Request-Timestamp": str(int(time.time()))}

    def _get_cached_including_expired(
        self, url: str, params: dict[str, Any]
    ) -> requests.Response | None:
        request = requests.Request("GET", url, params=params)
        prepared = self._session.prepare_request(request)
        key = self._session.cache.create_key(prepared)
        response = self._session.cache.get_response(key)
        return response if response is not None else None

    def _sanitize_cached_entry(self, url: str, params: dict[str, Any]) -> None:
        """Remove sensitive request-header fields from the serialized cache entry."""
        request = requests.Request("GET", url, params=params)
        prepared = self._session.prepare_request(request)
        key = self._session.cache.create_key(prepared)
        cached = self._session.cache.get_response(key)
        if cached is None:
            return
        cached.request.headers.pop("Authorization", None)
        cached.request.headers.pop("X-Request-Timestamp", None)
        self._session.cache.save_response(
            cached, cache_key=key, expires=getattr(cached, "expires", None)
        )

    @staticmethod
    def _stale_eligible(response: requests.Response) -> bool:
        """Only use responses that expired within the seven-day grace period."""
        now = datetime.now(timezone.utc)
        expires = getattr(response, "expires", None)
        if isinstance(expires, str):
            try:
                expires = datetime.fromisoformat(expires)
            except ValueError:
                return False
        if isinstance(expires, datetime):
            if expires.tzinfo is None:
                expires = expires.replace(tzinfo=timezone.utc)
            return now <= expires + timedelta(days=7)
        created_at = getattr(response, "created_at", None)
        if isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at)
            except ValueError:
                return False
        if isinstance(created_at, datetime):
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            return now <= created_at + timedelta(days=8)
        return False

    @staticmethod
    def _scrub_sensitive_request_headers(
        response: requests.Response, *args: object, **kwargs: object
    ) -> requests.Response:
        """Remove credentials and cache-busting timestamps before serialization."""
        request = getattr(response, "request", None)
        if request is not None:
            request.headers.pop("Authorization", None)
            request.headers.pop("X-Request-Timestamp", None)
        return response

    @staticmethod
    def _parse_edit_time(value: Any) -> datetime | None:
        try:
            return datetime.fromtimestamp(int(value), tz=timezone.utc) if value is not None else None
        except (ValueError, TypeError, OSError):
            return None

    @staticmethod
    def _clean_url(url: str) -> str:
        import re
        if not url or not str(url).startswith(
            ("https://www.zhihu.com/", "https://zhuanlan.zhihu.com/")
        ):
            raise ValueError("missing or non-Zhihu source URL")
        return re.sub(r"([?&])utm_[^&=]+=[^&]+", "", str(url)).rstrip("?&")
