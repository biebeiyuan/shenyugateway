from shenyu_gateway.stars._scene import _parse_scene_batch, _parse_scene_labels


def test_parse_scene_labels_accepts_multi_and_empty():
    assert _parse_scene_labels('["warm", "rift"]') == ["warm", "rift"]
    assert _parse_scene_labels('["暖", "裂"]') == ["warm", "rift"]
    assert _parse_scene_labels("```json\n[]\n```") == []


def test_parse_scene_labels_rejects_non_array():
    assert _parse_scene_labels("warm") is None
    assert _parse_scene_labels('["warm", "unknown"]') is None


def test_parse_scene_batch_accepts_all_expected_ids():
    text = '[{"star_id":"a","scenes":["暖","裂"]},{"star_id":"b","scenes":[]}]'
    assert _parse_scene_batch(text, {"a", "b"}) == {"a": ["warm", "rift"], "b": []}


def test_parse_scene_batch_rejects_missing_star():
    assert _parse_scene_batch('[{"star_id":"a","scenes":["warm"]}]', {"a", "b"}) is None
