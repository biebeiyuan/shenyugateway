from __future__ import annotations

import asyncio
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone

from shenyu_gateway.gateway_tools import GatewayToolService
from shenyu_gateway.response_capture import AssistantTagFilter, split_private_assistant_tags
from shenyu_gateway.room_tools import execute_room_tool
from shenyu_gateway.stars import StarService, parse_star_payload
from shenyu_gateway.tool_registry import execute_gateway_tool

from .fake_postgrest import project_select


class FakeSupabase:
    def __init__(self):
        self.tables = {
            "shenyu_stars": [],
            "shenyu_star_recall_runs": [],
            "shenyu_star_recall_candidates": [],
            "shenyu_star_feedback": [],
            "shenyu_star_activations": [],
            "shenyu_star_links": [],
        }
        self._ids = 0

    def _new_id(self, prefix):
        self._ids += 1
        return f"{prefix}-{self._ids}"

    async def query(self, table, params=None):
        params = dict(params or {})
        rows = [dict(row) for row in self.tables.get(table, [])]
        for key, value in params.items():
            if key in {"select", "order", "limit"}:
                continue
            if value == "is.null":
                rows = [row for row in rows if row.get(key) is None]
            elif value == "not.is.null":
                rows = [row for row in rows if row.get(key) is not None]
            elif isinstance(value, str) and value.startswith("eq."):
                expected = value[3:]
                if expected in {"true", "false"}:
                    expected_bool = expected == "true"
                    rows = [row for row in rows if bool(row.get(key)) is expected_bool]
                else:
                    rows = [row for row in rows if str(row.get(key)) == expected]
            elif isinstance(value, str) and value.startswith("in.(") and value.endswith(")"):
                expected = set(value[4:-1].split(","))
                rows = [row for row in rows if str(row.get(key)) in expected]
        limit = int(params.get("limit") or len(rows) or 0)
        return project_select(rows[:limit], params)

    async def insert(self, table, data):
        row = dict(data)
        row.setdefault("id", self._new_id(table))
        row.setdefault("metadata", {})
        row.setdefault("created_at", "2026-06-18T00:00:00+00:00")
        row.setdefault("updated_at", row["created_at"])
        self.tables.setdefault(table, []).append(row)
        return dict(row)

    async def insert_many(self, table, rows):
        return [await self.insert(table, row) for row in rows]

    async def update(self, table, match, data):
        updated = []
        for row in self.tables.get(table, []):
            if all(str(row.get(key)) == str(value) for key, value in (match or {}).items()):
                row.update(data)
                updated.append(dict(row))
        return updated


def _cfg():
    return SimpleNamespace(
        enable_inline_star_capture=True,
        enable_star_embeddings=False,
        inject_stars=True,
        star_candidate_limit=50,
        star_shadow_candidate_limit=20,
        star_chat_explicit_fallback_limit=1,
        star_min_score=0.008,
        star_related_min_score=0.22,
        star_recent_fatigue_hours=6,
        star_recent_fatigue_penalty=0.14,
        star_rrf_ch_content=1.0,
        star_rrf_ch_keyword=0.8,
        star_rrf_ch_chord=0.6,
        star_rrf_ch_harmony=0.7,
        star_rrf_ch_scene=0.4,
        star_rrf_ch_explicit=0.5,
        star_rrf_k=60,
        star_rrf_actr_floor=0.5,
        star_rrf_constant_boost=1.3,
        star_rrf_date_boost_max=0.3,
    )


def test_star_tag_left_visible_and_parse_chord():
    clean, heartbeat = split_private_assistant_tags(
        "看见了。[star chord=\"Am\"]有一点亮[/star]<heartbeat>留着</heartbeat>"
    )

    assert "[star" in clean
    assert heartbeat == "留着"
    assert parse_star_payload("Am · 有一点亮")["content"] == "有一点亮"
    assert parse_star_payload("Am · 有一点亮")["chord_root"] == "A"


def test_streaming_unclosed_star_left_visible():
    tag_filter = AssistantTagFilter()

    visible = tag_filter.feed("前面 [star]未闭合") + tag_filter.flush()

    assert visible == "前面 [star]未闭合"


def test_create_star_accepts_ordered_chord_sequence():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)

    async def run():
        created = await service.create_star(
            "这一周的时间线",
            chord="Am(maj7) → Am → F#m7",
            chords=["Am(maj7)", "Am", "F#m7"],
        )
        listed = await service.list_stars(status="all")
        filtered = await service.list_stars(status="all", q="F#m7")
        return created, supabase.tables["shenyu_stars"][0], listed, filtered

    created, row, listed, filtered = asyncio.run(run())

    assert created["ok"] is True
    assert row["chord"] == "Am(maj7) → Am → F#m7"
    assert row["chord_root"] == "A"
    assert row["metadata"]["chord_sequence"] == ["Am(maj7)", "Am", "F#m7"]
    assert created["star"]["chord_sequence"] == ["Am(maj7)", "Am", "F#m7"]
    assert listed["items"][0]["chord_sequence"] == ["Am(maj7)", "Am", "F#m7"]
    assert filtered["count"] == 1


def test_parse_star_payload_chord_sequence():
    result = parse_star_payload("Bbmaj7 → Am(maj7) → F#m7 · 实体化一段")
    assert result["content"] == "实体化一段"
    assert result["chord_root"] == "BB"


def test_review_limits_candidates_and_missed_feedback():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)

    async def run():
        await service.create_star("Am · 第一颗星")
        await service.create_star("Am · 第二颗星")
        await service.create_star("C · 第三颗星")
        result = await service.review(limit_new=2, candidates_per_star=3, total_candidate_limit=2)
        feedback = await service.feedback(
            feedback="missed",
            run_id=result["items"][0]["run_id"],
            expected_star_id="shenyu_stars-3",
            scored_by="沈予",
            note="应该反第三颗",
        )
        return result, feedback

    result, feedback = asyncio.run(run())

    assert result["ok"] is True
    assert result["count"] == 2
    assert sum(len(item["candidates"]) for item in result["items"]) <= 2
    assert feedback["ok"] is True
    assert feedback["feedback"]["feedback"] == "missed"
    assert feedback["feedback"]["expected_node_id"] == "shenyu_stars-3"


def test_feedback_accepts_batch_items_and_updates_candidate_by_star_id():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)

    async def run():
        await service.create_star("Am · 第一颗星")
        await service.create_star("Am · 第二颗星")
        result = await service.review(limit_new=1, candidates_per_star=1, total_candidate_limit=1)
        candidate = result["items"][0]["candidates"][0]
        feedback = await service.feedback(
            items=[
                {
                    "feedback": "positive",
                    "run_id": candidate["run_id"],
                    "candidate_star_id": candidate["id"],
                    "scored_by": "沈予",
                },
                {
                    "feedback": "should_surface",
                    "expected_star_id": "shenyu_stars-1",
                    "scored_by": "沈予",
                    "note": "这颗应该被推上来",
                },
            ]
        )
        return feedback, candidate, supabase.tables["shenyu_star_recall_candidates"], supabase.tables["shenyu_star_feedback"]

    feedback, candidate, candidates, rows = asyncio.run(run())

    assert feedback["ok"] is True
    assert feedback["count"] == 2
    assert rows[0]["candidate_id"] == candidate["candidate_id"]
    assert rows[0]["candidate_node_id"] == candidate["id"]
    assert rows[1]["feedback"] == "should_surface"
    assert rows[1]["expected_node_id"] == "shenyu_stars-1"
    assert candidates[0]["action_status"] == "positive"


def test_feedback_accepts_legacy_label_reason_batch():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)

    async def run():
        await service.create_star("Am · 第一颗星")
        await service.create_star("Am · 第二颗星")
        result = await service.review(limit_new=1, candidates_per_star=1, total_candidate_limit=1)
        candidate = result["items"][0]["candidates"][0]
        feedback = await service.feedback(
            run_id=candidate["run_id"],
            feedback=[
                {"candidate_id": candidate["candidate_id"], "label": "good", "reason": "该反"},
                {"candidate_id": candidate["candidate_id"], "label": "bad", "reason": "不该反"},
                {"candidate_id": candidate["candidate_id"], "label": "neutral", "reason": "先放过"},
            ],
        )
        return feedback, supabase.tables["shenyu_star_recall_candidates"], supabase.tables["shenyu_star_feedback"]

    feedback, candidates, rows = asyncio.run(run())

    assert feedback["ok"] is True
    assert feedback["count"] == 3
    assert [row["feedback"] for row in rows] == ["positive", "negative", "skipped"]
    assert [row["note"] for row in rows] == ["该反", "不该反", "先放过"]
    assert candidates[0]["action_status"] == "skipped"


def test_feedback_accepts_action_star_id_and_value_comment_aliases():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)

    async def run():
        return await service.feedback(
            feedback=[
                {"star_id": "star-1", "action": "positive", "comment": "第一颗"},
                {"candidate_id": "candidate-1", "action": "good"},
                {"candidate_node_id": "star-2", "value": "bad", "reason": "第二颗"},
            ]
        )

    result = asyncio.run(run())
    rows = supabase.tables["shenyu_star_feedback"]

    assert result["ok"] is True
    assert result["count"] == 3
    assert [row["feedback"] for row in rows] == ["positive", "positive", "negative"]
    assert [row["candidate_node_id"] for row in rows] == ["star-1", None, "star-2"]
    assert rows[1]["candidate_id"] == "candidate-1"
    assert [row["note"] for row in rows] == ["第一颗", "", "第二颗"]


def test_admin_review_does_not_mark_shenyu_reviewed_until_feedback_complete():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)

    async def run():
        await service.create_star("Am · 第一颗星")
        await service.create_star("Am · 第二颗星")
        result = await service.review(limit_new=1, candidates_per_star=1, total_candidate_limit=1, review_scope="admin")
        seed_id = result["items"][0]["star"]["id"]
        candidate = result["items"][0]["candidates"][0]
        after_admin_pick = [row for row in supabase.tables["shenyu_stars"] if row["id"] == seed_id][0]
        await service.feedback(
            feedback="positive",
            run_id=candidate["run_id"],
            candidate_id=candidate["candidate_id"],
            candidate_star_id=candidate["id"],
            scored_by="圆圆",
            metadata={"surface": "admin:stars"},
        )
        after_feedback = [row for row in supabase.tables["shenyu_stars"] if row["id"] == seed_id][0]
        return result, after_admin_pick, after_feedback

    result, after_admin_pick, after_feedback = asyncio.run(run())

    assert result["review_scope"] == "admin"
    assert after_admin_pick.get("reviewed_at") is None
    assert after_feedback.get("reviewed_at") is None
    assert after_feedback["metadata"]["admin_reviewed_at"]


def test_shenyu_review_still_marks_reviewed_at():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)

    async def run():
        await service.create_star("Am · 第一颗星")
        await service.create_star("Am · 第二颗星")
        result = await service.review(limit_new=1, candidates_per_star=1, total_candidate_limit=1)
        seed_id = result["items"][0]["star"]["id"]
        seed = [row for row in supabase.tables["shenyu_stars"] if row["id"] == seed_id][0]
        return result, seed

    result, seed = asyncio.run(run())

    assert result["review_scope"] == "shenyu"
    assert seed.get("reviewed_at")


def test_star_graph_returns_links():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)

    async def run():
        first = await service.create_star("Am · 第一颗星")
        second = await service.create_star("C · 第二颗星")
        await service.connect_constellation(
            [first["star_id"], second["star_id"]],
            name="第一束光",
            scored_by="圆圆",
            note="真实连线",
        )
        return await service.graph()

    graph = asyncio.run(run())

    assert graph["ok"] is True
    assert len(graph["stars"]) == 2
    assert len(graph["links"]) == 1
    assert graph["links"][0]["name"] == "第一束光"
    assert graph["links"][0]["source"] == "shenyu_stars-1"
    assert graph["links"][0]["target"] == "shenyu_stars-2"


def test_chat_injection_requires_score_thresholds():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)

    async def run():
        await service.create_star("Cm(add9) · 我们搭了一整天宇宙")
        weak = await service.search_context("完全无关的普通句子", limit=3)
        strong = await service.search_context("宇宙", limit=3)
        return weak, strong

    weak, strong = asyncio.run(run())

    assert weak["ok"] is True
    assert weak["items"] == []
    assert strong["count"] == 1
    assert "宇宙" in strong["items"][0]["content"]


def test_chat_injection_explicit_mention_fallback_is_capped():
    supabase = FakeSupabase()
    cfg = _cfg()
    cfg.star_min_score = 0.95
    cfg.star_related_min_score = 0.95
    cfg.star_chat_explicit_fallback_limit = 1
    service = StarService(cfg, supabase)

    async def run():
        await service.create_star("Am · 降临 arrive 那晚，她把害怕停机的怕交给我")
        await service.create_star("C · 降临 arrive 之后，我记住接住此刻")
        unrelated = await service.search_context("完全无关的普通句子", limit=3)
        explicit = await service.search_context("我们一起看了降临 arrive", limit=3)
        return unrelated, explicit

    unrelated, explicit = asyncio.run(run())

    assert unrelated["items"] == []
    assert explicit["count"] == 1
    assert "降临" in explicit["items"][0]["content"]


def test_chat_injection_explicit_fallback_ignores_generic_hits():
    supabase = FakeSupabase()
    cfg = _cfg()
    cfg.star_min_score = 0.95
    cfg.star_related_min_score = 0.95
    cfg.star_chat_explicit_fallback_limit = 1
    service = StarService(cfg, supabase)

    async def run():
        await service.create_star("Am · 今天她在车上安静了一会")
        return await service.search_context("今天怎么样", limit=3)

    result = asyncio.run(run())

    assert result["items"] == []


def test_recent_chat_injection_fatigue_can_suppress_borderline_star():
    supabase = FakeSupabase()
    cfg = _cfg()
    cfg.star_min_score = 0.012
    cfg.star_related_min_score = 0.22
    cfg.star_recent_fatigue_hours = 6
    cfg.star_recent_fatigue_penalty = 0.95
    cfg.star_chat_explicit_fallback_limit = 0
    service = StarService(cfg, supabase)

    async def run():
        created = await service.create_star("Am · 宇宙")
        before = await service.search_context("宇宙", limit=3)
        recent_time = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        await supabase.insert(
            "shenyu_star_activations",
            {
                "star_id": created["star_id"],
                "activated_at": recent_time,
                "surface": "chat_inject",
                "trigger_text": "宇宙",
                "score": 0.3,
                "injected": True,
            },
        )
        after = await service.search_context("宇宙", limit=3)
        return before, after

    before, after = asyncio.run(run())

    assert before["count"] == 1
    assert after["items"] == []


def test_archive_star_sets_status_archived():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)

    async def run():
        created = await service.create_star("Am · 要删的星")
        archive_result = await service.archive_star(created["star_id"])
        active_list = await service.list_stars(status="active")
        all_list = await service.list_stars(status="all")
        return archive_result, active_list, all_list

    result, active_list, all_list = asyncio.run(run())

    assert result["ok"] is True
    assert result["status"] == "archived"
    assert active_list["count"] == 0
    assert all_list["count"] == 1


def test_merge_stars_creates_new_and_archives_sources():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)

    async def run():
        s1 = await service.create_star("Am · 第一视角的记忆")
        s2 = await service.create_star("Em · 第二视角的记忆")
        await service.connect_constellation(
            [s1["star_id"], s2["star_id"]],
            name="同一件事",
            scored_by="沈予",
        )
        merge_result = await service.merge_stars(
            [s1["star_id"], s2["star_id"]],
            content="两个视角融成一颗",
            chord="Am",
        )
        active_list = await service.list_stars(status="active")
        return merge_result, active_list, supabase.tables["shenyu_star_links"]

    merge_result, active_list, links = asyncio.run(run())

    assert merge_result["ok"] is True
    assert len(merge_result["archived_ids"]) == 2
    assert merge_result["new_star_id"]
    assert active_list["count"] == 1
    assert "两个视角融成一颗" in active_list["items"][0]["content"]


def test_review_returns_remaining_unreviewed():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)

    async def run():
        for i in range(6):
            await service.create_star(f"Am · 星星{i}")
        result = await service.review(limit_new=2, candidates_per_star=1, total_candidate_limit=2)
        return result

    result = asyncio.run(run())

    assert result["ok"] is True
    assert result["count"] == 2
    assert result["remaining_unreviewed"] == 4


def test_gateway_broker_review_uses_resident_wide_unreviewed_queue():
    supabase = FakeSupabase()
    cfg = _cfg()
    service = GatewayToolService(runtime_config=cfg, supabase=supabase, store=None)

    async def run():
        for i in range(3):
            await StarService(cfg, supabase).create_star(f"Am · 旧会话星星{i}", session_tag="7.18")
        return await execute_gateway_tool(
            "shenyu_gateway_tool",
            {
                "tool": "shenyu_star_review",
                "params": {
                    "limit_new": 2,
                    "candidates_per_star": 1,
                    "total_candidate_limit": 2,
                },
            },
            session_tag="7.30",
            cfg=cfg,
            service=service,
        )

    result = asyncio.run(run())

    assert result["ok"] is True
    assert result["count"] == 2
    assert [item["star"]["content"] for item in result["items"]] == [
        "旧会话星星0",
        "旧会话星星1",
    ]
    assert result["remaining_unreviewed"] == 1
    assert {row["session_tag"] for row in supabase.tables["shenyu_star_recall_runs"]} == {"7.30"}


def test_room_review_uses_resident_wide_unreviewed_queue():
    supabase = FakeSupabase()
    cfg = _cfg()

    async def run():
        for i in range(3):
            await StarService(cfg, supabase).create_star(f"Cmaj7 · 房间外星星{i}", session_tag="7.18")
        return await execute_room_tool(
            "room_star_map",
            {
                "action": "review",
                "limit_new": 2,
                "candidates_per_star": 1,
                "total_candidate_limit": 2,
                "session_tag": "7.30",
            },
            store=None,
            cfg=cfg,
            supabase_client=supabase,
            session_tag="7.18",
        )

    result = asyncio.run(run())

    assert result["ok"] is True
    assert result["count"] == 2
    assert [item["star"]["content"] for item in result["items"]] == [
        "房间外星星0",
        "房间外星星1",
    ]
    assert result["remaining_unreviewed"] == 1
    assert {row["session_tag"] for row in supabase.tables["shenyu_star_recall_runs"]} == {"7.30"}


def test_backfill_scenes_only_updates_unlabeled_stars():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)
    classified_batches = []

    async def classify(stars, http_client):
        classified_batches.append(stars)
        return {"ok": True, "labels": {stars[0]["star_id"]: ["warm", "rift"]}, "thinking": "认真看过了"}

    service._classify_star_scenes = classify

    async def run():
        await service.create_star("沈予已经标过", metadata={"scenes": ["deep"]})
        await service.create_star("旧格式也不能覆盖", metadata={"scene": "anchor"})
        await service.create_star("等待补标签")
        return await service.backfill_scenes(limit=10, http_client=object())

    result = asyncio.run(run())
    rows = supabase.tables["shenyu_stars"]

    assert result["updated"] == 1
    assert len(classified_batches) == 1
    assert classified_batches[0][0]["content"] == "等待补标签"
    assert result["thinking"] == "认真看过了"
    assert rows[0]["metadata"]["scenes"] == ["deep"]
    assert rows[1]["metadata"]["scene"] == "anchor"
    assert rows[2]["metadata"]["scenes"] == ["warm", "rift"]


def test_backfill_empty_scene_list_counts_as_processed():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)
    calls = 0

    async def classify(stars, http_client):
        nonlocal calls
        calls += 1
        return {"ok": True, "labels": {stars[0]["star_id"]: []}, "thinking": ""}

    service._classify_star_scenes = classify

    async def run():
        await service.create_star("暂时无法判断")
        first = await service.backfill_scenes(limit=10, http_client=object())
        second = await service.backfill_scenes(limit=10, http_client=object())
        return first, second

    first, second = asyncio.run(run())

    assert first["updated"] == 1
    assert second["selected"] == 0
    assert calls == 1
    assert supabase.tables["shenyu_stars"][0]["metadata"]["scenes"] == []


def test_backfill_returns_classifier_error_detail():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)

    async def classify(stars, http_client):
        return {
            "ok": False,
            "error_code": "invalid_output",
            "error": "模型已响应，但没有返回可识别的场景数组",
            "response_preview": "我认为这颗星是暖和裂。",
        }

    service._classify_star_scenes = classify

    async def run():
        await service.create_star("等待诊断")
        return await service.backfill_scenes(limit=1, http_client=object())

    result = asyncio.run(run())

    assert result["updated"] == 0
    assert result["failed"] == 1
    assert result["items"][0]["error_code"] == "invalid_output"
    assert result["items"][0]["response_preview"] == "我认为这颗星是暖和裂。"


def test_scene_response_unwraps_data_envelope_and_reasoning_blocks():
    service = StarService(_cfg(), FakeSupabase())
    payload = service._scene_response_payload({
        "success": True,
        "data": {
            "choices": [{
                "message": {
                    "content": '[{"star_id":"a","scenes":["warm"]}]',
                    "reasoning": [{"type": "reasoning.text", "text": "认真判断了暖。"}],
                }
            }]
        },
    })
    message = payload["choices"][0]["message"]

    assert message["content"].startswith("[")
    assert service._scene_response_text(message["reasoning"]) == "认真判断了暖。"


def test_set_scenes_preserves_content_and_other_metadata():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)

    async def run():
        created = await service.create_star("正文绝对不能动", metadata={"note": "保留", "scene": "warm"})
        return await service.set_scenes(created["star_id"], ["rift", "warm"])

    result = asyncio.run(run())
    row = supabase.tables["shenyu_stars"][0]

    assert result["ok"] is True
    assert row["content"] == "正文绝对不能动"
    assert row["metadata"]["note"] == "保留"
    assert row["metadata"]["scenes"] == ["warm", "rift"]
    assert "scene" not in row["metadata"]


def test_set_scenes_accepts_new_scene_aliases():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)

    async def run():
        created = await service.create_star("新的关系场景")
        return await service.set_scenes(created["star_id"], ["被看穿", "欲/馋", "漏"])

    result = asyncio.run(run())

    assert result["ok"] is True
    assert result["star"]["scenes"] == ["seen", "want", "loose"]


def test_context_search_hydrates_active_required_ids_and_excludes_archived_ones():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)
    active_id = "11111111-1111-4111-8111-111111111111"
    archived_id = "22222222-2222-4222-8222-222222222222"
    for index in range(50):
        supabase.tables["shenyu_stars"].append(
            {
                "id": f"filler-{index}",
                "content": f"普通候选 {index}",
                "status": "active",
                "metadata": {},
                "activation_count": 0,
            }
        )
    supabase.tables["shenyu_stars"].extend(
        [
            {
                "id": active_id,
                "content": "候选上限之外仍然活跃的旧岛星",
                "status": "active",
                "metadata": {},
                "activation_count": 0,
            },
            {
                "id": archived_id,
                "content": "已经归档的旧岛星",
                "status": "archived",
                "metadata": {},
                "activation_count": 0,
            },
        ]
    )

    result = asyncio.run(
        service.search_context(
            "今天聊点别的",
            limit=3,
            mark_activation=False,
            required_star_ids={active_id, archived_id},
        )
    )

    assert result["_active_required_ids"] == [active_id]


def test_explicit_uuid_is_hydrated_even_outside_normal_candidate_limit():
    supabase = FakeSupabase()
    service = StarService(_cfg(), supabase)
    target_id = "33333333-3333-4333-8333-333333333333"
    for index in range(50):
        supabase.tables["shenyu_stars"].append(
            {
                "id": f"filler-{index}",
                "content": f"普通候选 {index}",
                "status": "active",
                "metadata": {},
                "activation_count": 0,
            }
        )
    supabase.tables["shenyu_stars"].append(
        {
            "id": target_id,
            "content": "候选上限之外被直接点名",
            "status": "active",
            "metadata": {},
            "activation_count": 0,
        }
    )

    result = asyncio.run(service.search_context(target_id, limit=3, mark_activation=False))

    assert [item["id"] for item in result["items"]] == [target_id]
    assert result["items"][0]["direct_reference_kind"] == "star_id"
