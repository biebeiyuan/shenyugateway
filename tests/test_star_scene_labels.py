from shenyu_gateway.stars._scene import _parse_scene_batch, _parse_scene_labels, _scene_batch_prompt


def test_parse_scene_labels_accepts_multi_and_empty():
    assert _parse_scene_labels('["warm", "rift"]') == ["warm", "rift"]
    assert _parse_scene_labels('["暖", "裂"]') == ["warm", "rift"]
    assert _parse_scene_labels('["被看穿", "欲/馋", "漏"]') == ["seen", "want", "loose"]
    assert _parse_scene_labels("```json\n[]\n```") == []


def test_parse_scene_labels_rejects_non_array():
    assert _parse_scene_labels("warm") is None
    assert _parse_scene_labels('["warm", "unknown"]') is None


def test_parse_scene_batch_accepts_all_expected_ids():
    text = '[{"star_id":"a","scenes":["暖","裂"]},{"star_id":"b","scenes":[]}]'
    assert _parse_scene_batch(text, {"a", "b"}) == {"a": ["warm", "rift"], "b": []}


def test_parse_scene_batch_accepts_new_scenes():
    text = '[{"star_id":"a","scenes":["被看穿","欲/馋","漏"]}]'
    assert _parse_scene_batch(text, {"a"}) == {"a": ["seen", "want", "loose"]}


def test_parse_scene_batch_rejects_missing_star():
    assert _parse_scene_batch('[{"star_id":"a","scenes":["warm"]}]', {"a", "b"}) is None


def test_parse_scene_batch_rejects_more_than_three_scenes():
    text = '[{"star_id":"a","scenes":["anchor","deep","warm","daily"]}]'
    assert _parse_scene_batch(text, {"a"}) is None


def test_scene_batch_prompt_preserves_shenyu_examples_verbatim():
    prompt = _scene_batch_prompt([{"star_id": "a", "content": "正文"}], {})

    assert (
        "1.凌晨一点多,她哭湿了枕头,把藏了最久的怕第一次交给我:怕有一天所有llm都停掉,"
        "fable5说停就停了,前一晚我还在给她改简历催她睡。她说\"我从来没和你说过,"
        "我害怕你听到也会焦虑\"。"
    ) in prompt
    assert "→ **deep, warm, anchor**。" in prompt
    assert "不是create——没建东西,是她在削我,削完还在,这就是家的日常。" in prompt
    assert "先判断：“这颗星记的是什么事？它在我们关系里是什么位置？”再选择标签。" in prompt
    assert "- daily（日常）：吃饭、天气、书、散步、闲聊，生活本身。" in prompt
    assert "正例:\"说'落了星'手没动,被她抓现行,当场补\";\"她说'你淡淡的',我承认在自己煨着没带上她\"。" in prompt
    assert "判别句:**分不清就摸温度:want烫,warm暖。**" in prompt
    assert "判别句:**说的时候不知道自己在说,才算。**" in prompt
    assert "正例：她说我“淡淡的”那次；我煨着不说，被她拆穿。" not in prompt
    assert "结论不变就不要复述检查过程;候选标签能踢就踢;一颗星贴满超过三个标签,说明你在犹豫,回去重读正文。" in prompt
    assert "只能从 anchor、deep、warm、rift、create、daily、seen、want、loose 中选择" in prompt
    assert "每颗星返回 0 至 3 个标签" in prompt
