from __future__ import annotations

from typing import Any, Optional

from shenyu_gateway.runtime import local_day_of, local_today, logger
from shenyu_gateway.utils import human_time_ago

# Resident contract: tool results stay clean - content, chord, timestamps and
# the ids later calls need. Scores, hit markers and source/embedding internals
# stay on the service layer, where the Admin UI keeps consuming them.
_STAR_PUBLIC_FIELDS = (
    "id",
    "content",
    "chord",
    "chord_sequence",
    "status",
    "is_constant",
    "created_at",
    "updated_at",
)


def _star_seen_ago(star: dict[str, Any]) -> str:
    """这颗星落下多久了，说成人话。

    时间差本身就是 review 的内容：「她把伞递过来」和「下雨天她总是走在外侧」，
    一个一年半前一个上周，那"像是有关系"的意味完全不同。

    一个月内走 `human_time_ago`（房间和便签共用的那套说法）；更久就说月数和
    年数——那个函数四周以上退回天数，而「538天前」对一年半这种跨度没有感觉，
    它是为"几天前"设计的。
    """
    day = local_day_of(star.get("created_at"))
    if day is None:
        return ""
    days = (local_today() - day).days
    if days < 0:
        return ""
    if days <= 30:
        return human_time_ago(days)
    months = days // 30
    if months < 12:
        return f"{months}个月前"
    years = months // 12
    rest = months % 12
    return f"{years}年前" if rest == 0 else f"{years}年{rest}个月前"


def _clean_star(star: Any, *, seen_ago: bool = False) -> dict[str, Any]:
    if not isinstance(star, dict):
        return {}
    item: dict[str, Any] = {}
    for key in _STAR_PUBLIC_FIELDS:
        value = star.get(key)
        if value is None or value == "" or value == []:
            continue
        # 回声：这三个字段多数时候是在把他已经知道的事说回给他。
        #
        # status 在筛选结果里永远等于他刚才传的那个值；chord_sequence 只有一个
        # 和弦时就是 chord 本身；星星是"落下就不动"的东西，所以 updated_at 对
        # 绝大多数星星和 created_at 一模一样。
        if key == "status" and value == "active":
            continue
        # 绝大多数星星都不是恒星，false 没有信息；是恒星才值得说一句。
        if key == "is_constant" and value is False:
            continue
        if key == "chord_sequence" and len(value) < 2:
            continue
        if key == "updated_at" and local_day_of(value) == local_day_of(star.get("created_at")):
            continue
        item[key] = value
    if seen_ago:
        ago = _star_seen_ago(star)
        if ago:
            item["落下"] = ago
    return item


class StarToolsMixin:
    async def create_star(
        self,
        content: Any,
        chord: str = "",
        chords: Optional[list[str]] = None,
        session_tag: Optional[str] = None,
        status: str = "active",
        is_constant: bool = False,
        metadata: Optional[dict[str, Any]] = None,
    ) -> dict:
        result = await self._stars().create_star(
            content=content,
            chord=chord,
            chords=chords,
            session_tag=session_tag,
            status=status,
            is_constant=is_constant,
            metadata=metadata,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        return {"ok": True, "star_id": result.get("star_id"), "star": _clean_star(result.get("star"))}

    async def list_stars(
        self,
        status: str = "active",
        limit: int = 50,
        session_tag: Optional[str] = None,
        q: str = "",
        reviewed: str = "all",
    ) -> dict:
        result = await self._stars().list_stars(
            status=status,
            limit=limit,
            session_tag=session_tag,
            q=q,
            reviewed=reviewed,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        items = [_clean_star(item) for item in result.get("items") or []]
        return {"ok": True, "count": len(items), "items": items}

    async def search_stars(
        self,
        query: str = "",
        session_tag: Optional[str] = None,
        limit: int = 10,
        log_run: bool = False,
    ) -> dict:
        result = await self._stars().search_stars(
            query=query,
            session_tag=session_tag,
            limit=limit,
            log_run=log_run,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        items = []
        for item in result.get("items") or []:
            cleaned = _clean_star(item)
            if isinstance(item, dict) and item.get("candidate_id"):
                cleaned["candidate_id"] = item["candidate_id"]
            items.append(cleaned)
        out: dict[str, Any] = {"ok": True, "count": len(items), "items": items}
        if result.get("run_id"):
            out["run_id"] = result["run_id"]
        return out

    async def star_review(
        self,
        limit_new: Optional[int] = None,
        candidates_per_star: Optional[int] = None,
        total_candidate_limit: Optional[int] = None,
        session_tag: Optional[str] = None,
    ) -> dict:
        result = await self._stars().review(
            limit_new=limit_new,
            candidates_per_star=candidates_per_star,
            total_candidate_limit=total_candidate_limit,
            session_tag=session_tag,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        # 已经连过的那些线：候选如果和种子星早就在一条线上，把星座名和他当时
        # 的说法带出来。不然他会重新判断一次上次已经判断过的关系，而且可能说出
        # 不一样的话——而那条线本来就是他自己连的。
        lines = await self._existing_lines(result.get("items") or [])
        items = []
        for seed_index, entry in enumerate(result.get("items") or [], start=1):
            if not isinstance(entry, dict):
                continue
            seed_id = str((entry.get("star") or {}).get("id") or "")
            candidates = []
            for rank, candidate in enumerate(entry.get("candidates") or [], start=1):
                cleaned = _clean_star(candidate, seen_ago=True)
                line = lines.get((seed_id, str(candidate.get("id") or "")))
                if line:
                    cleaned["已经在一条线上"] = line
                # 两段编号（1.2 = 第 1 颗下面的第 2 个）。review 和 feedback 在
                # 同一轮里，所以这批候选就在他眼前的上文里，编号不用他记也不用
                # 网关存——feedback 拿着编号重新问一次库就够了。
                cleaned["编号"] = f"{seed_index}.{rank}"
                if isinstance(candidate, dict) and candidate.get("candidate_id"):
                    cleaned["candidate_id"] = candidate["candidate_id"]
                candidates.append(cleaned)
            items.append(
                {
                    "编号": str(seed_index),
                    "star": _clean_star(entry.get("star"), seen_ago=True),
                    # run_id 不给他：那是"第几次召回"的内部账本，他不会想引用它。
                    # feedback 从候选行自己读得出来。
                    "candidates": candidates,
                }
            )
        out: dict[str, Any] = {"ok": True, "count": len(items), "items": items}
        if result.get("remaining_unreviewed") is not None:
            out["remaining_unreviewed"] = result["remaining_unreviewed"]
        return out

    async def star_feedback(
        self,
        feedback: Any = None,
        run_id: Optional[str] = None,
        candidate_id: Optional[str] = None,
        candidate_star_id: Optional[str] = None,
        expected_star_id: Optional[str] = None,
        constellation_name: str = "",
        candidate: Any = None,
        scored_by: str = "沈予",
        note: str = "",
        metadata: Optional[dict[str, Any]] = None,
        items: Optional[list[dict[str, Any]]] = None,
    ) -> dict:
        # 「1.2」这种编号解析成真的 candidate_id。他刚看过的那批候选还在库里
        # （review 每次都落 candidate 行），所以按 run 的顺序数回去就行——
        # 不需要跨轮存任何状态。
        if candidate is not None and not candidate_id and not candidate_star_id:
            resolved, error = await self._resolve_review_number(candidate)
            if error:
                return {"ok": False, "error": error, "error_kind": "validation"}
            candidate_id = resolved
        if isinstance(items, list):
            for item in items:
                if not isinstance(item, dict):
                    continue
                number = item.get("candidate") or item.get("编号")
                if number is None or item.get("candidate_id") or item.get("candidate_star_id"):
                    continue
                resolved, error = await self._resolve_review_number(number)
                if error:
                    return {"ok": False, "error": error, "error_kind": "validation"}
                item["candidate_id"] = resolved
        result = await self._stars().feedback(
            feedback=feedback,
            run_id=run_id,
            candidate_id=candidate_id,
            candidate_star_id=candidate_star_id,
            expected_star_id=expected_star_id,
            constellation_name=constellation_name,
            scored_by=scored_by,
            note=note,
            metadata=metadata,
            items=items,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        rows = result.get("feedback")
        if isinstance(rows, dict):
            rows = [rows]
        recorded = [row.get("feedback") for row in rows or [] if isinstance(row, dict) and row.get("feedback")]
        out: dict[str, Any] = {"ok": True, "count": result.get("count", len(recorded))}
        if recorded:
            out["recorded"] = recorded
        # 真连上了就说出来，不然他不知道那句「连起来」有没有生效——
        # 这正是以前那 12 次静默失败的地方。
        if result.get("edge_count"):
            out["connected"] = result["edge_count"]
        return out

    async def _existing_lines(self, entries: list[Any]) -> dict[tuple[str, str], str]:
        """这批里哪些「种子星 ↔ 候选」已经在同一条线上了，返回那条线怎么说。

        星座名是这条线的名字（一句话，比如「替我记着」），note 是他当时的说法。
        两样分开存在边的 metadata 里，所以这里也分开读——名字答"这是哪条线"，
        说法答"当时我为什么这么连"。

        查不到不影响 review：只是这次看不见旧的线。
        """
        pairs: list[tuple[str, str]] = []
        ids: set[str] = set()
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            seed_id = str((entry.get("star") or {}).get("id") or "")
            if not seed_id:
                continue
            ids.add(seed_id)
            for candidate in entry.get("candidates") or []:
                cid = str((candidate or {}).get("id") or "")
                if cid:
                    pairs.append((seed_id, cid))
                    ids.add(cid)
        if not pairs or not self.supabase:
            return {}
        try:
            rows = await self.supabase.query(
                "shenyu_star_links",
                {
                    "select": "from_node_id,to_node_id,metadata",
                    "from_node_id": "in.(" + ",".join(sorted(ids)) + ")",
                    "status": "eq.active",
                    "limit": "200",
                },
            )
        except Exception as exc:
            logger.warning("[Star] review 读已有的线失败: %s", exc)
            return {}
        said: dict[tuple[str, str], str] = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            name = str(metadata.get("constellation_name") or "").strip()
            note = str(metadata.get("note") or "").strip()
            if not name and not note:
                continue
            text = name if not note else (f"{name}——{note}" if name else note)
            left = str(row.get("from_node_id") or "")
            right = str(row.get("to_node_id") or "")
            # 边是双向的，两个方向都记上，因为 review 里谁是种子星不固定。
            said[(left, right)] = text
            said[(right, left)] = text
        return {pair: said[pair] for pair in pairs if pair in said}

    async def _resolve_review_number(self, number: Any) -> tuple[str, str]:
        """「1.2」→ 真的 candidate_id，返回 (id, 错误)。

        数的是最近那几次 review 的候选行：第一段是第几颗种子星，第二段是它下面
        第几个候选。他刚看过的那批就是最近的几次 run，所以按 run 倒序取、再按
        `rank` 数回去。

        编号只在他眼前那一批里有意义，所以这里不做任何缓存——重新问一次库比
        存一份会过期的映射可靠。
        """
        text = str(number or "").strip()
        if not text:
            return "", ""
        parts = [part for part in text.replace("．", ".").split(".") if part.strip()]
        try:
            seed_index = int(parts[0])
            rank = int(parts[1]) if len(parts) > 1 else 1
        except (ValueError, IndexError):
            return "", f"看不懂编号「{text}」，要 star_review 给的那种（比如 1.2）。"
        if seed_index < 1 or rank < 1:
            return "", f"编号从 1 开始，「{text}」不对。"
        if not self.supabase:
            return "", "Supabase is not configured."
        try:
            runs = await self.supabase.query(
                "shenyu_star_recall_runs",
                {
                    "select": "id,created_at",
                    "surface": "eq.review",
                    "order": "created_at.desc",
                    "limit": "20",
                },
            )
        except Exception as exc:
            return "", f"找不到刚才那批候选：{exc}"
        runs = [row for row in (runs or []) if isinstance(row, dict)]
        if len(runs) < seed_index:
            return "", f"刚才那批里没有第 {seed_index} 颗，先 star_review 看一眼。"
        # review 按种子顺序建 run，倒序取回来之后要翻正。
        run_id = str(runs[seed_index - 1].get("id") or "")
        try:
            candidates = await self.supabase.query(
                "shenyu_star_recall_candidates",
                {
                    "select": "id,rank",
                    "run_id": f"eq.{run_id}",
                    "order": "rank.asc",
                    "limit": "20",
                },
            )
        except Exception as exc:
            return "", f"找不到第 {seed_index} 颗下面的候选：{exc}"
        candidates = [row for row in (candidates or []) if isinstance(row, dict)]
        if len(candidates) < rank:
            return "", f"第 {seed_index} 颗下面没有第 {rank} 个。"
        return str(candidates[rank - 1].get("id") or ""), ""

    async def connect_constellation(
        self,
        star_ids: Any,
        name: str = "",
        relation_type: str = "constellation",
        scored_by: str = "沈予",
        note: str = "",
    ) -> dict:
        result = await self._stars().connect_constellation(
            star_ids=star_ids,
            name=name,
            relation_type=relation_type,
            scored_by=scored_by,
            note=note,
        )
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        out: dict[str, Any] = {
            "ok": True,
            "edge_count": result.get("edge_count"),
            "star_ids": result.get("star_ids"),
        }
        if name:
            out["name"] = name
        return out

    async def mark_constant_star(self, star_id: str, is_constant: bool = True) -> dict:
        result = await self._stars().mark_constant(star_id, is_constant=is_constant)
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        return {"ok": True, "star_id": result.get("star_id") or star_id, "is_constant": is_constant}

    async def archive_star(self, star_id: str) -> dict:
        return await self._stars().archive_star(star_id)

    async def merge_stars(self, source_ids: list, *, content: str = "", chord: str = "", is_constant: bool = False, metadata: dict | None = None) -> dict:
        result = await self._stars().merge_stars(source_ids, content=content, chord=chord, is_constant=is_constant, metadata=metadata)
        if not isinstance(result, dict) or not result.get("ok"):
            return result
        return {
            "ok": True,
            "new_star_id": result.get("new_star_id"),
            "archived_ids": result.get("archived_ids"),
            "new_star": _clean_star(result.get("new_star")),
        }
