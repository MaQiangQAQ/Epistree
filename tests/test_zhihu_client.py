"""Tests for ZhihuSearchClient — mock HTTP via responses library.

Each test uses `responses.RequestsMock` as a context manager for clean isolation.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests
import responses
import pytest
from responses.matchers import query_string_matcher

from epistree_demo.zhihu_client import ZhihuSearchClient

FIXTURE_DIR = Path(__file__).parent / "fixtures"

import os
os.environ["ZHIHU_ACCESS_SECRET"] = "test_secret_12345"


def _load_fixture():
    with open(FIXTURE_DIR / "zhihu_search.json") as f:
        return json.load(f)


class TestZhihuClient:

    def test_search_success(self):
        fixture = _load_fixture()
        with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
            rsps.add(
                responses.GET,
                "https://developer.zhihu.com/api/v1/content/zhihu_search",
                json=fixture,
                status=200,
            )
            client = ZhihuSearchClient()
            resp, _ = client.search("RAG", count=3)
            assert resp.code == 0
            assert len(resp.data) == 3
            assert resp.data[0].content_type == "answer"

    def test_search_auth_failure(self):
        import pytest
        with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
            rsps.add(
                responses.GET,
                "https://developer.zhihu.com/api/v1/content/zhihu_search",
                status=401,
            )
            client = ZhihuSearchClient()
            with pytest.raises(PermissionError, match="UPSTREAM_AUTH_FAILED"):
                client.search("__AUTHX__")

    def test_quota_success(self):
        with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
            rsps.add(
                responses.GET,
                "https://developer.zhihu.com/api/v1/quota",
                json={"Code": 0, "Message": "success",
                      "Data": [{"APIID": "zhihu_search", "TotalQuota": 5000,
                                "TotalUsed": 3, "RemainingQuota": 4997}]},
                status=200,
            )
            client = ZhihuSearchClient()
            quota = client.get_quota()
            assert quota.code == 0
            assert quota.used == 3
            assert quota.remaining == 4997

    def test_quota_refreshes_between_runs(self):
        """A new run must observe the current official value, not a cached one."""
        with responses.RequestsMock(assert_all_requests_are_fired=True) as rsps:
            for remaining in (1, 0):
                rsps.add(
                    responses.GET,
                    "https://developer.zhihu.com/api/v1/quota",
                    json={"Code": 0, "Message": "success", "Data": [{
                        "APIID": "zhihu_search", "TotalQuota": 2,
                        "TotalUsed": 2 - remaining, "RemainingQuota": remaining,
                    }]},
                    status=200,
                )
            client = ZhihuSearchClient()
            assert client.get_quota().remaining == 1
            assert client.get_quota().remaining == 0
            assert len(rsps.calls) == 2

    def test_expired_cache_is_stale_fallback_after_two_timeouts(self):
        """The public requests-cache API must expose an expired stale candidate."""
        url = "https://developer.zhihu.com/api/v1/content/zhihu_search"
        fixture = _load_fixture()
        with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
            rsps.add(responses.GET, url, json=fixture, status=200)
            client = ZhihuSearchClient()
            first = client.search("__STALE_FALLBACK__")
            assert first.cache_state == "miss"

            prepared = client._session.prepare_request(requests.Request("GET", url, params={
                "Query": "__STALE_FALLBACK__", "Count": 10,
            }))
            key = client._session.cache.create_key(prepared)
            cached = client._session.cache.get_response(key)
            assert cached is not None
            expired_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            client._session.cache.save_response(cached, cache_key=key, expires=expired_at)

            rsps.add(responses.GET, url, body=requests.exceptions.Timeout("t1"))
            rsps.add(responses.GET, url, body=requests.exceptions.Timeout("t2"))
            outcome = client.search("__STALE_FALLBACK__")
            assert outcome.cache_state == "stale"
            assert outcome.network_attempts == 2
            assert len(outcome.response.data) == len(fixture["Data"]["Items"])

    def test_cache_older_than_grace_period_is_not_used(self):
        url = "https://developer.zhihu.com/api/v1/content/zhihu_search"
        fixture = _load_fixture()
        with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
            rsps.add(responses.GET, url, json=fixture, status=200)
            client = ZhihuSearchClient()
            client.search("__TOO_OLD_STALE__")
            prepared = client._session.prepare_request(requests.Request(
                "GET", url, params={"Query": "__TOO_OLD_STALE__", "Count": 10},
            ))
            key = client._session.cache.create_key(prepared)
            cached = client._session.cache.get_response(key)
            assert cached is not None
            client._session.cache.save_response(
                cached,
                cache_key=key,
                expires=datetime.now(timezone.utc) - timedelta(days=8),
            )
            rsps.add(responses.GET, url, body=requests.exceptions.Timeout("t1"))
            rsps.add(responses.GET, url, body=requests.exceptions.Timeout("t2"))
            with pytest.raises(RuntimeError, match="UPSTREAM_TEMPORARY_ERROR"):
                client.search("__TOO_OLD_STALE__")

    def test_retry_on_timeout(self):
        """A transient failure consumes one budget slot per real attempt."""
        fixture = _load_fixture()
        reservations = []
        with responses.RequestsMock(assert_all_requests_are_fired=True) as rsps:
            rsps.add(
                responses.GET,
                "https://developer.zhihu.com/api/v1/content/zhihu_search",
                body=requests.exceptions.Timeout("first attempt"),
            )
            rsps.add(
                responses.GET,
                "https://developer.zhihu.com/api/v1/content/zhihu_search",
                json=fixture,
                status=200,
            )
            client = ZhihuSearchClient(
                reserve_attempt=lambda: not reservations.append(True),
                quota_remaining=lambda: 10,
            )
            outcome = client.search("__RETRY_TIMEOUT__")
        assert outcome.network_attempts == 2
        assert len(reservations) == 2

    def test_cached_response_does_not_persist_sensitive_request_headers(self):
        fixture = _load_fixture()
        url = "https://developer.zhihu.com/api/v1/content/zhihu_search"
        with responses.RequestsMock(assert_all_requests_are_fired=True) as rsps:
            rsps.add(responses.GET, url, json=fixture, status=200)
            client = ZhihuSearchClient()
            client.search("__CACHE_HEADERS__")
        prepared = client._session.prepare_request(requests.Request(
            "GET", url, params={"Query": "__CACHE_HEADERS__", "Count": 10},
        ))
        cached = client._session.cache.get_response(client._session.cache.create_key(prepared))
        assert cached is not None
        assert "Authorization" not in cached.request.headers
        assert "X-Request-Timestamp" not in cached.request.headers

    def test_quota_failure_does_not_become_zero_quota(self):
        client = ZhihuSearchClient(
            reserve_attempt=lambda: True,
            quota_remaining=lambda: (_ for _ in ()).throw(RuntimeError("quota offline")),
        )
        with pytest.raises(RuntimeError, match="UPSTREAM_QUOTA_FAILED"):
            client.search("__QUOTA_FAILURE__")

    def test_error_code_handling(self):
        import pytest
        with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
            rsps.add(
                responses.GET,
                "https://developer.zhihu.com/api/v1/content/zhihu_search",
                json={"Code": 1001, "Message": "rate limit"},
                status=200,
            )
            client = ZhihuSearchClient()
            with pytest.raises(RuntimeError, match="error code=1001"):
                client.search("__ERR__")

    def test_utm_cleanup(self):
        with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
            rsps.add(
                responses.GET,
                "https://developer.zhihu.com/api/v1/content/zhihu_search",
                json={
                    "Code": 0, "Message": "ok",
                    "Data": {"Items": [{
                        "ContentID": "1", "ContentType": "Answer",
                        "Title": "T", "ContentText": "C",
                        "Url": "https://zhuanlan.zhihu.com/p/123456?utm_medium=openapi&utm_source=app",
                        "AuthorName": "A", "EditTime": 1700000000,
                        "VoteUpCount": 0, "CommentCount": 0,
                        "AuthorityLevel": "4", "RankingScore": 0.5
                    }]}
                },
                status=200,
            )
            client = ZhihuSearchClient()
            resp, _ = client.search("__UTM__")
            url = str(resp.data[0].url)
            assert "utm_" not in url
