from shenyu_gateway.stars._scene import _parse_scene_labels


def test_parse_scene_labels_accepts_multi_and_empty():
    assert _parse_scene_labels('["warm", "rift"]') == ["warm", "rift"]
    assert _parse_scene_labels('["暖", "裂"]') == ["warm", "rift"]
    assert _parse_scene_labels("```json\n[]\n```") == []


def test_parse_scene_labels_rejects_non_array():
    assert _parse_scene_labels("warm") is None
    assert _parse_scene_labels('["warm", "unknown"]') is None
