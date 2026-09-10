from epistree_demo.app import WARMUP_TOPICS, _warmup_topic_for_trigger


def test_warmup_trigger_resolves_matching_topic() -> None:
    for index, topic in enumerate(WARMUP_TOPICS):
        assert _warmup_topic_for_trigger(f"warmup-{index}") == topic


def test_warmup_trigger_rejects_invalid_ids() -> None:
    assert _warmup_topic_for_trigger(None) is None
    assert _warmup_topic_for_trigger("topic-input") is None
    assert _warmup_topic_for_trigger("warmup-invalid") is None
    assert _warmup_topic_for_trigger(f"warmup-{len(WARMUP_TOPICS)}") is None
