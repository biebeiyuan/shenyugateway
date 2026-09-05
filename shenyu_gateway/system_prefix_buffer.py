"""系统前缀缓冲闸：让 heartbeat / 日历的刷新憋一会儿再顶上去。

`stable / slow(日历) / heartbeat / tool_policy / format` 五层拼成系统前缀，共享一个
缓存断点 `system.end`（`context_layers.py::assemble_layered_messages`）。heartbeat 满
一批注入、或写了日历，系统前缀内容一变，那个断点前的一大块缓存就得重写。

这里给 `slow` 和 `heartbeat` 两层加一道版本闸——形状照抄 `memory_island.py::
resolve_memory_island`（存旧版、够格才换）。规则很朴素：**内容一变就先憋着，直到
下面两个之一发生，才把新前缀顶上去**：

- 距上次刷新超过 `buffer_seconds`（到点，`ttl_elapsed`）；
- 这次本来就在裁剪、缓存反正要重建（`epoch_reset`，白嫖顺手换，`epoch_rebuild`）。

憋着期间沿用上一次生效的文本，于是 `system.end` 前缀逐字节不变，缓存照旧命中。

这两个触发点正是缓存本来就会失效的时刻，所以憋着期间被换掉的旧内容（沈予清掉的
日历页、滚出窗口的旧心跳）最多多留一个 buffer 窗口就消失，不额外损耗缓存——这是
刻意的取舍，换来「一小时内前缀不因心跳/日历抖动」。

早先这里还有一条 `content_removed` 强刷分支（「旧文本里有、新文本里没有的行 =
撤东西，立即刷」）。它对心跳从来都是误判：心跳层是 pending↔digest 两个互斥集合的
整批替换（`context_builder.py::_normal_heartbeat_context`），窗口一滚旧行全不在了，
被当成「撤东西」而短路掉时间闸——正是这道闸想省的那次刷新反被它顶掉。心跳内容从不
被真正删除（`mark_heartbeats_injected` 只打注入戳），所以那条分支删掉，闸退回上面
两个触发点。

只缓冲 `slow` 和 `heartbeat`。`stable / tool_policy / format` 只在配置或 charter 变时
才动，本来就稳定，纳入闸只会把判定复杂化、并无收益。

沈予主动读心跳走 `shenyu_read_heartbeat` 工具，直接查库，是另一条路，不受这里影响。
"""

from __future__ import annotations

from typing import Any, Optional

from .runtime import iso_now, parse_ts

# anthropic_cache_ttl 是受限字符串（config.py 只允许 "5m" / "1h"）。缓冲上限直接
# 跟它走：反正缓存到点也失效了，憋过 TTL 再刷没有意义。取不到就退化成 0 = 不缓冲。
_TTL_SECONDS = {"5m": 300, "1h": 3600}


def buffer_seconds_from_ttl(ttl: Any) -> int:
    """把 ANTHROPIC_CACHE_TTL（"5m"/"1h"）解析成秒。认不出就返回 0。

    返回 0 是 fail-open：闸退化成「每次都刷」，也就是没有这个功能之前的行为——
    宁可不省缓存，也不把旧内容永久钉死在前缀里。
    """
    return _TTL_SECONDS.get(str(ttl or "").strip().lower(), 0)


def _elapsed_seconds(refreshed_at: str, now: str) -> Optional[float]:
    old = parse_ts(refreshed_at)
    new = parse_ts(now)
    if old is None or new is None:
        return None
    return (new - old).total_seconds()


def resolve_system_prefix(
    previous_state: Optional[dict[str, Any]],
    new_slow: str,
    new_heartbeat: str,
    *,
    buffer_seconds: int,
    epoch_reset: bool,
    now: Optional[str] = None,
) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
    """决定这次系统前缀用「新渲染的」还是「憋着的旧快照」。

    返回 `(chosen_slow, chosen_heartbeat, new_state, decision)`：
    - chosen_*：这次真正塞进系统前缀的两层文本。
    - new_state：要存回 window_state 的 `system_prefix_state`。
    - decision：content-free 的决策记录，落进 window 事件日志用来观测缓冲命中。
    """
    previous_state = previous_state or {}
    now = now or iso_now()

    old_slow = str(previous_state.get("slow_text") or "")
    old_heartbeat = str(previous_state.get("heartbeat_text") or "")
    had_snapshot = bool(previous_state.get("refreshed_at"))

    changed = (new_slow != old_slow) or (new_heartbeat != old_heartbeat)

    def _apply(reason: str) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
        state = {
            "slow_text": new_slow,
            "heartbeat_text": new_heartbeat,
            "refreshed_at": now,
        }
        return new_slow, new_heartbeat, state, {"decision": "refreshed", "reason": reason}

    def _hold(reason: str) -> tuple[str, str, dict[str, Any], dict[str, Any]]:
        # 沿用旧文本，state 原样留着（refreshed_at 不动，好让下次继续按同一个起点计时）。
        state = {
            "slow_text": old_slow,
            "heartbeat_text": old_heartbeat,
            "refreshed_at": str(previous_state.get("refreshed_at") or ""),
        }
        return old_slow, old_heartbeat, state, {"decision": "held", "reason": reason}

    # 第一次、或没有旧快照可沿用：直接落一版，没什么可憋的。
    if not had_snapshot:
        return _apply("first_snapshot")

    # 内容没变：连时间戳都不用动，沿用旧的（它俩逐字节相等，随便用哪份）。
    if not changed:
        return _hold("unchanged")

    # 这次本来就要重建缓存：白嫖，顺手把新前缀顶上去。
    if epoch_reset:
        return _apply("epoch_rebuild")

    # buffer_seconds <= 0：闸关闭（TTL 认不出的 fail-open），每次都刷。
    if buffer_seconds <= 0:
        return _apply("buffer_disabled")

    elapsed = _elapsed_seconds(str(previous_state.get("refreshed_at") or ""), now)
    if elapsed is None or elapsed >= buffer_seconds:
        # 时间戳坏了也当作到点——宁可多刷一次，不把旧内容钉死。
        return _apply("ttl_elapsed")

    # 内容变了、但还没到点、也没在裁剪：憋着，沿用旧文本，缓存继续命中。
    return _hold("buffered")
