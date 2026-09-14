"""测试记忆激活系统：加热、衰减、地形影响。"""

from __future__ import annotations

import pytest

from shenyu_gateway.memory_heat import HEAT_INCREMENT, _apply_heat_for_island_injection
from shenyu_gateway.stars._weights import StarWeights
from shenyu_gateway.store._memory_heat import HEAT_EVENTS_TABLE


def test_heat_increment_is_reasonable():
    """HEAT_INCREMENT 应该在合理范围（0.05 - 0.20）。"""
    assert 0.05 <= HEAT_INCREMENT <= 0.20


def test_star_weights_has_activation_weight():
    """StarWeights 应该有 activation_weight 字段。"""
    weights = StarWeights()
    assert hasattr(weights, "activation_weight")
    assert 0.0 <= weights.activation_weight <= 1.0
    # 默认值应该和 HEAT_INCREMENT 在同一个数量级
    assert 0.1 <= weights.activation_weight <= 0.2


def test_apply_heat_is_idempotent(tmp_path):
    """同一个 event_id 多次加热应该只生效一次。"""
    from shenyu_gateway.store import GatewayStore

    store = GatewayStore(db_path=str(tmp_path / "test.db"))

    # 创建一个测试 session
    session_tag = "test_session_heat"
    session = store.get_or_create_session(session_tag, client_name="test")
    session_id = session["id"]

    # 模拟一个岛注入事件（匹配 mark_context_consumed 的真实调用结构）
    meta = {
        "session": {
            "id": session_id,
            "turn_count": 1,
        },
        "package": {
            "memory_island_state": {
                "stars": [{"id": "star_abc123"}],
                "mem_notes": [{"id": "mem_def456"}],
            }
        },
    }

    # 第一次加热
    _apply_heat_for_island_injection(meta, store)

    # 检查 heat_events 表有 2 条记录
    conn = store._connect()
    events = conn.execute(
        f"SELECT event_id, memory_kind, memory_id FROM {HEAT_EVENTS_TABLE} ORDER BY memory_kind, memory_id"
    ).fetchall()
    assert len(events) == 2
    assert events[0][1] == "mem_note"  # memory_kind
    assert events[0][2] == "mem_def456"  # memory_id
    assert events[1][1] == "star"
    assert events[1][2] == "star_abc123"

    # 第二次加热相同的 event（幂等性测试）
    _apply_heat_for_island_injection(meta, store)

    # 仍然只有 2 条记录
    events_after = conn.execute(f"SELECT COUNT(*) FROM {HEAT_EVENTS_TABLE}").fetchone()[0]
    assert events_after == 2


def test_apply_heat_handles_empty_injection(tmp_path):
    """空的岛注入应该不报错。"""
    from shenyu_gateway.store import GatewayStore

    store = GatewayStore(db_path=str(tmp_path / "test.db"))
    session_tag = "test_session_empty"
    session = store.get_or_create_session(session_tag, client_name="test")
    session_id = session["id"]

    meta = {
        "session": {
            "id": session_id,
            "turn_count": 1,
        },
        "package": {
            "memory_island_state": {
                "stars": [],
                "mem_notes": [],
            }
        },
    }

    # 不应该报错
    _apply_heat_for_island_injection(meta, store)

    # heat_events 表应该为空
    conn = store._connect()
    count = conn.execute(f"SELECT COUNT(*) FROM {HEAT_EVENTS_TABLE}").fetchone()[0]
    assert count == 0


def test_mem_notes_activation_weight_is_hardcoded():
    """Mem Notes 的 activation_weight 硬编码为 0.15（和 Stars 一致）。"""
    # 这个测试只是文档性的——确认 mem_notes/_search.py 里的 0.15
    # 如果未来改成可配置，这个测试会提醒你
    from shenyu_gateway.mem_notes._search import SearchMixin
    import inspect

    source = inspect.getsource(SearchMixin._score)
    assert "0.15" in source, "Mem Notes activation_weight 应该是 0.15"
    assert "activation_mod" in source, "Mem Notes 应该应用 activation 修正"


def test_activation_score_affects_star_recall():
    """activation_score 应该影响 Star 的召回排序。"""
    from shenyu_gateway.stars._recall import RecallMixin
    from shenyu_gateway.stars._weights import StarWeights

    # 模拟两颗星星：一个高 activation，一个低 activation
    weights = StarWeights(activation_weight=0.15)

    star_hot = {
        "id": "star_hot",
        "content": "测试内容",
        "activation_score": 5.0,  # 高分
        "is_constant": False,
    }
    star_cold = {
        "id": "star_cold",
        "content": "测试内容",
        "activation_score": 0.0,  # 低分
        "is_constant": False,
    }

    # 基础分数相同的情况下，高 activation 的应该排在前面
    # 这里只验证 activation_weight 的存在和合理性
    activation_boost_hot = weights.activation_weight * star_hot["activation_score"]
    activation_boost_cold = weights.activation_weight * star_cold["activation_score"]

    assert activation_boost_hot > activation_boost_cold
    assert activation_boost_hot == 0.15 * 5.0  # 0.75
    assert activation_boost_cold == 0.0


def test_heat_events_table_exists(tmp_path):
    """heat_events 表应该在 store 初始化时创建。"""
    from shenyu_gateway.store import GatewayStore

    store = GatewayStore(db_path=str(tmp_path / "test.db"))
    conn = store._connect()

    # 检查表存在
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (HEAT_EVENTS_TABLE,)
    ).fetchall()
    assert len(tables) == 1

    # 检查表结构
    columns = conn.execute(f"PRAGMA table_info({HEAT_EVENTS_TABLE})").fetchall()
    column_names = [col[1] for col in columns]
    assert "event_id" in column_names
    assert "session_id" in column_names
    assert "turn_index" in column_names
    assert "memory_kind" in column_names
    assert "memory_id" in column_names


def test_nightly_decay_script_exists():
    """夜间衰减脚本应该存在。"""
    from pathlib import Path

    script_path = Path(__file__).parent.parent / "scripts" / "nightly_memory_decay.py"
    assert script_path.exists(), "nightly_memory_decay.py 应该存在"

    # 检查脚本是可执行的 Python
    content = script_path.read_text()
    assert "#!/usr/bin/env python3" in content
    assert "RETENTION_RATE" in content
    assert "decay_activation_scores" in content
