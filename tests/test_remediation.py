"""Offline acceptance checks for the R0-R5 demo boundaries."""

from __future__ import annotations

import tempfile
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from epistree_demo.db import EpistreeDB
from epistree_demo.service import DemoService
from epistree_demo.models import (
    ClaimNode,
    GraphBundle,
    QuestionNode,
    SearchItem,
    SearchResponse,
    SourceRef,
    validate_bundle_against_sources,
)
from epistree_demo.selector import compute_input_hash
from epistree_demo.zhihu_client import SearchOutcome


def _source(sid: str = "zhihu:answer:1", text: str = "evidence") -> SearchItem:
    return SearchItem(
        source_id=sid, content_id=sid.rsplit(":", 1)[-1], content_type="answer",
        title="Title", content_text=text, url="https://www.zhihu.com/answer/1", author_name="Author",
    )


def test_reserve_daily_call_is_atomic_under_contention() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = EpistreeDB(Path(tmp) / "epistree.sqlite")
        db.init_schema()
        with ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(lambda _: db.reserve_daily_call("2026-01-01", 1), range(2)))
        assert sum(result) == 1
        assert db.get_daily_calls("2026-01-01") == 1


def test_provenance_rejects_fabricated_source() -> None:
    bundle = GraphBundle(
        topic="T",
        questions=[QuestionNode(id="q", text="?", source_refs=[SourceRef(source_id="s1")])],
        claims=[ClaimNode(id="c", text="C", question_id="q", confidence=0.5,
                          source_refs=[SourceRef(source_id="fake")])],
    )
    with pytest.raises(ValueError, match="unknown source_id"):
        validate_bundle_against_sources(bundle, {"s1": _source("s1")})


def test_model_input_hash_tracks_visible_metadata_but_not_hidden_metrics() -> None:
    first = _source(text="same")
    second = first.model_copy(update={"author_name": "Other"})
    assert compute_input_hash([first], "T", "p", "g", "m") != compute_input_hash([second], "T", "p", "g", "m")


def test_snapshot_stores_original_item_not_whole_response() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = EpistreeDB(Path(tmp) / "epistree.sqlite")
        db.init_schema()
        run_id = db.create_run("T")
        query_id = db.get_or_create_query("T", "hash")
        source = _source()
        raw_item = {
            "ContentID": source.content_id,
            "ContentType": "Answer",
            "Title": source.title,
            "ExtraField": "preserved",
        }
        response = SearchResponse(
            code=0,
            data=[source],
            raw_json={"Code": 0, "Data": {"Items": [raw_item]}},
        )
        outcome = SearchOutcome(response, "miss", datetime.now(timezone.utc), 1)
        db.persist_search_observation(run_id, query_id, outcome, [source])
        row = db.connect().execute("SELECT raw_json FROM source_snapshots").fetchone()
        assert json.loads(row["raw_json"]) == raw_item


def test_run_completion_uses_explicit_bundle_id() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = EpistreeDB(Path(tmp) / "epistree.sqlite")
        service = DemoService(db=db)
        source = _source()
        bundle_a = GraphBundle(
            topic="A", questions=[QuestionNode(id="q", text="?", source_refs=[SourceRef(source_id=source.source_id)])],
            claims=[],
        )
        bundle_b = bundle_a.model_copy(update={"topic": "B"})
        id_a = db.save_bundle("bundle-a", "hash-a", "p", "m", bundle_a.model_dump_json())
        id_b = db.save_bundle("bundle-b", "hash-b", "p", "m", bundle_b.model_dump_json())
        run_a, run_b = service.create_run("A"), service.create_run("B")
        db.update_run_status(run_a, "running")
        db.update_run_status(run_b, "running")
        service.complete_run(run_b, bundle_b, {}, id_b)
        service.complete_run(run_a, bundle_a, {}, id_a)
        assert db.get_run(run_a)["graph_bundle_id"] == id_a
        assert db.get_run(run_b)["graph_bundle_id"] == id_b
        assert db.run_bundle_is_consistent(run_a)
        assert db.run_bundle_is_consistent(run_b)


def test_empty_query_list_is_rejected_before_search() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = EpistreeDB(Path(tmp) / "epistree.sqlite")
        service = DemoService(db=db)
        run_id = service.create_run("T")
        with pytest.raises(ValueError, match="query"):
            service.execute_search(run_id, [])


def test_overlong_query_is_rejected_before_search() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = EpistreeDB(Path(tmp) / "epistree.sqlite")
        service = DemoService(db=db)
        run_id = service.create_run("T")
        with pytest.raises(ValueError, match="200"):
            service.execute_search(run_id, ["x" * 201])


def test_cancelled_run_has_terminal_timestamp() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        db = EpistreeDB(Path(tmp) / "epistree.sqlite")
        service = DemoService(db=db)
        run_id = service.create_run("T")
        db.update_run_status(run_id, "running")
        service.cancel_run(run_id)
        run = service.get_run(run_id)
        assert run is not None
        assert run["status"] == "cancelled"
        assert run["finished_at"]


def test_time_filter_uses_source_edit_time_and_event_occurred_at() -> None:
    from epistree_demo.app import _time_filter
    from epistree_demo.presenter import present

    source = _source()
    source = source.model_copy(update={
        "edit_time": datetime(2025, 2, 3, tzinfo=timezone.utc),
    })
    bundle = GraphBundle(
        topic="T",
        questions=[QuestionNode(id="q", text="?", source_refs=[SourceRef(source_id=source.source_id)])],
        claims=[],
        events=[{
            "id": "e", "text": "event", "occurred_at": "2024-01-01",
            "source_refs": [SourceRef(source_id=source.source_id)], "confidence": 0.5,
        }],
    )
    nodes, edges = present(bundle, [source])
    full = nodes + edges
    bundle_data = bundle.model_dump(mode="json")
    source_data = [source.model_dump(mode="json")]

    in_2025 = _time_filter("2025", full, bundle_data, source_data)
    ids_2025 = {item["data"].get("id") for item in in_2025}
    assert "question:q" in ids_2025
    source_node_id = next(item["data"]["id"] for item in full
                          if item["data"].get("node_type") == "source")
    assert source_node_id in ids_2025
    assert "event:e" in ids_2025

    in_2024 = _time_filter("2024", full, bundle_data, source_data)
    ids_2024 = {item["data"].get("id") for item in in_2024}
    assert "event:e" in ids_2024

    restored = _time_filter("all", in_2025, bundle_data, source_data)
    assert {item["data"].get("id") for item in restored} == {
        item["data"].get("id") for item in full
    }


def test_time_filter_unknown_keeps_undated_nodes_and_topic() -> None:
    from epistree_demo.app import _time_filter
    from epistree_demo.presenter import present

    source = _source()
    bundle = GraphBundle(
        topic="T",
        questions=[QuestionNode(
            id="q", text="?", source_refs=[SourceRef(source_id=source.source_id)],
        )],
        claims=[],
    )
    nodes, edges = present(bundle, [source])
    filtered = _time_filter(
        "unknown", nodes + edges, bundle.model_dump(mode="json"),
        [source.model_dump(mode="json")],
    )
    visible_ids = {item["data"].get("id") for item in filtered}
    assert "topic:T" in visible_ids
    assert "question:q" in visible_ids
