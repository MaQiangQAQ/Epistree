from epistree_demo.app import WARMUP_TOPICS, _warmup_topic_for_trigger


def test_warmup_trigger_resolves_matching_topic() -> None:
    for index, topic in enumerate(WARMUP_TOPICS):
        assert _warmup_topic_for_trigger(f"warmup-{index}") == topic


def test_warmup_trigger_rejects_invalid_ids() -> None:
    assert _warmup_topic_for_trigger(None) is None
    assert _warmup_topic_for_trigger("topic-input") is None
    assert _warmup_topic_for_trigger("warmup-invalid") is None
    assert _warmup_topic_for_trigger(f"warmup-{len(WARMUP_TOPICS)}") is None


def test_warmup_topics_count() -> None:
    expected_topics = [
        "RAG",
        "大模型微调",
        "视觉大模型",
        "AI Agent 智能体",
        "大模型推理加速与量化",
        "大模型强化学习与长思维链",
    ]
    assert WARMUP_TOPICS == expected_topics


def test_warmup_topics_load_and_present_tree() -> None:
    from pathlib import Path
    from epistree_demo.presenter import present
    from epistree_demo.warmup import WarmupAsset

    data_dir = Path(".data")
    assert data_dir.exists()

    expected_topics = [
        "RAG",
        "大模型微调",
        "视觉大模型",
        "AI Agent 智能体",
        "大模型推理加速与量化",
        "大模型强化学习与长思维链",
    ]

    for topic_name in expected_topics:
        asset_file = data_dir / f"warmup_{topic_name}.json"
        assert asset_file.exists(), f"Asset {asset_file} must exist"
        asset = WarmupAsset.load(asset_file)
        bundle = asset.bundle
        sources = asset.sources
        assert len(bundle.questions) == 16
        assert len(bundle.claims) == 80
        assert len(bundle.events) == 20
        assert len(sources) >= 100

        # Verify Cytoscape rendering and tree geometry
        nodes, edges = present(bundle, sources)
        assert len(nodes) >= 220
        assert len(edges) >= 400
        assert (len(nodes) + len(edges)) >= 650

        # Verify root (event) nodes are situated downwards (y > 0)
        event_nodes = [
            n for n in nodes
            if n.get("data", {}).get("node_type") == "event"
        ]
        assert len(event_nodes) == 20
        for r in event_nodes:
            assert r["position"]["y"] > 0, f"Event/root {r['data']['id']} should be underground (y > 0)"

        root_edges = [
            e for e in edges
            if "root" in e.get("classes", "")
        ]
        assert len(root_edges) == 20


def test_precomputed_topics_and_instant_switch() -> None:
    import time
    from unittest.mock import patch
    from epistree_demo.app import WARMUP_TOPICS, _PRECOMPUTED_TOPICS, _show_warmup, _prepare_playback

    assert len(_PRECOMPUTED_TOPICS) == len(WARMUP_TOPICS)
    for topic in WARMUP_TOPICS:
        cached = _PRECOMPUTED_TOPICS[topic]
        assert len(cached["elements"]) >= 650
        assert len(cached["years"]) >= 4

    for i, topic in enumerate(WARMUP_TOPICS):
        with patch("epistree_demo.app.ctx") as mock_ctx:
            mock_ctx.triggered_id = f"warmup-{i}"
            clicks = [1 if j == i else 0 for j in range(len(WARMUP_TOPICS))]
            t0 = time.perf_counter()
            res = _show_warmup(*clicks)
            t1 = time.perf_counter()
            assert (t1 - t0) < 0.05, f"Switching to {topic} took {t1-t0}s, must be < 50ms"
            assert len(res[0]) >= 650

            t2 = time.perf_counter()
            prep = _prepare_playback(res[5], res[6])
            t3 = time.perf_counter()
            assert (t3 - t2) < 0.05, f"Playback prep took {t3-t2}s, must be < 50ms"
            assert len(prep[0]) >= 650


def test_focus_subgraph_preservation_and_multi_channel_unfocus() -> None:
    from epistree_demo.app import _PRECOMPUTED_TOPICS, _focus_node, _esc_unfocus

    cached = _PRECOMPUTED_TOPICS["RAG"]
    elements = cached["elements"]
    assert len(elements) >= 650

    # Find a question node
    q_node = next(el for el in elements if el.get("data", {}).get("node_type") == "question")
    qid = q_node["data"]["id"]

    # Focus on Question
    focused_elements, focus_data = _focus_node(q_node["data"], elements, {"node_id": None})
    assert focus_data["node_id"] == qid
    assert len(focused_elements) == len(elements), "All elements must be preserved (never deleted)"

    # Check that question, its claims, and sources of those claims are highlighted
    hl_count = sum(1 for el in focused_elements if "highlighted" in el.get("classes", ""))
    faded_count = sum(1 for el in focused_elements if "faded" in el.get("classes", ""))
    assert hl_count > 0, "Highlighted elements must exist"
    assert faded_count > 0, "Non-focused elements must be marked faded for soft background recession (其余隐去)"
    assert (hl_count + faded_count) == len(elements), "All elements must be preserved"

    # Click same node again to toggle off focus
    unfocused_elements, unfocus_data = _focus_node(q_node["data"], focused_elements, {"node_id": qid})
    assert unfocus_data["node_id"] is None
    assert all("faded" not in el.get("classes", "") for el in unfocused_elements)
    assert all("highlighted" not in el.get("classes", "") for el in unfocused_elements)

    # Focus again on question
    focused_elements, focus_data = _focus_node(q_node["data"], elements, {"node_id": None})
    assert focus_data["node_id"] == qid

    # Test multi-channel unfocus via btn-reset-focus / btn-unfocus-panel / btn-esc
    restored_els, restored_focus, detail_text = _esc_unfocus(1, 1, 1, focused_elements, focus_data)
    assert restored_focus["node_id"] is None
    assert all("faded" not in el.get("classes", "") for el in restored_els)
    assert all("highlighted" not in el.get("classes", "") for el in restored_els)
    assert "点击树上任意节点" in detail_text


def test_playback_pause_and_resume() -> None:
    from unittest.mock import patch
    from epistree_demo.app import _PRECOMPUTED_TOPICS, _playback, _build_steps

    cached = _PRECOMPUTED_TOPICS["RAG"]
    elements = cached["elements"]
    years = cached["years"]
    steps = _build_steps(elements)
    assert len(steps) > 10

    # 1. 初始点击播放：从种子 -1 开始长
    with patch("epistree_demo.app.ctx") as mock_ctx:
        mock_ctx.triggered_id = "btn-play"
        state = {"playing": False, "step_idx": -1}
        els, layout, state_out, disabled, time_band = _playback(1, None, None, state, elements, years)
        assert state_out["playing"] is True
        assert state_out["step_idx"] == -1
        assert disabled is False

    # 2. 定时器生长到第 5 步
    with patch("epistree_demo.app.ctx") as mock_ctx:
        mock_ctx.triggered_id = "playback-interval"
        state = {"playing": True, "step_idx": 4}
        els, layout, state_out, disabled, time_band = _playback(None, 5, None, state, elements, years)
        assert state_out["playing"] is True
        assert state_out["step_idx"] == 5
        assert disabled is False

    # 3. 点击暂停：停在第 5 步，保留 step_idx=5，定时器停止
    with patch("epistree_demo.app.ctx") as mock_ctx:
        mock_ctx.triggered_id = "btn-play"
        state = {"playing": True, "step_idx": 5}
        els, layout, state_out, disabled, time_band = _playback(2, None, None, state, elements, years)
        assert state_out["playing"] is False
        assert state_out["step_idx"] == 5
        assert disabled is True

    # 4. 点击继续播放：必须从第 5 步继续，绝对不能重置到 -1
    with patch("epistree_demo.app.ctx") as mock_ctx:
        mock_ctx.triggered_id = "btn-play"
        state = {"playing": False, "step_idx": 5}
        els, layout, state_out, disabled, time_band = _playback(3, None, None, state, elements, years)
        assert state_out["playing"] is True
        assert state_out["step_idx"] == 5, f"Expected step_idx=5 to resume, got {state_out['step_idx']}"
        assert disabled is False

    # 5. 下一帧定时器触发：平滑生长至第 6 步
    with patch("epistree_demo.app.ctx") as mock_ctx:
        mock_ctx.triggered_id = "playback-interval"
        state = {"playing": True, "step_idx": 5}
        els, layout, state_out, disabled, time_band = _playback(None, 6, None, state, elements, years)
        assert state_out["playing"] is True
        assert state_out["step_idx"] == 6
        assert disabled is False

    # 6. 回放完毕后（step_idx >= len(steps)），再次点击播放从头开始
    with patch("epistree_demo.app.ctx") as mock_ctx:
        mock_ctx.triggered_id = "btn-play"
        state = {"playing": False, "step_idx": len(steps)}
        els, layout, state_out, disabled, time_band = _playback(4, None, None, state, elements, years)
        assert state_out["playing"] is True
        assert state_out["step_idx"] == -1
        assert disabled is False

