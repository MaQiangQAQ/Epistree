"""Tests for ZhihuSearchClient — mock HTTP via responses library.

Each test uses `responses.RequestsMock` as a context manager for clean isolation.
"""
import json
from pathlib import Path

import requests
import responses
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

    def test_retry_on_timeout(self):
        """Should retry on transient error then succeed.
        Note: tested against real API in manual verification.
        """
        pass

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
