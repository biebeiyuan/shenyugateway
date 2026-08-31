"""盼圃的读写：种果子、贴纸条、摘果子、看盼圃。

园况算法在 `orchard.py`（纯函数）。这里只管 Supabase 两张表和四个动作。

两件事在这里刻意做成现在这样：

- **谁挂上去的自动认。** 走网关工具进来的是沈予，走 Admin API 进来的是圆圆，
  调用方传 actor，不让人填。
- **"谁先看见谁摘"要摔得好看。** 两个人同时摘，第二个不该看到报错，该看到
  "已经被摘了"，连谁摘的、他写了什么一起看到。所以摘是条件更新
  （`status=eq.green`），空结果不是失败，是这一局输了。
"""

from __future__ import annotations

from typing import Any, Optional

from .orchard import (
    classify_weather,
    fruit_took_scar,
    garden_line,
    green_condition,
    pick_condition,
)
from .recall import RecallIndexService
from .runtime import iso_now, local_day_of, local_today, logger, parse_local_date
from .weather import QWeatherService

FRUITS_TABLE = "shenyu_orchard_fruits"
NOTES_TABLE = "shenyu_orchard_notes"
# 天气不在 Supabase：它在本机卷的 `orchard_weather`（`store/_orchard.py`）。

ACTOR_SHENYU = "沈予"
ACTOR_YUANYUAN = "圆圆"

_FRUIT_FIELDS = (
    "id,name,planted_by,planted_at,due_on,status,"
    "picked_at,picked_by,picked_words,picked_condition,picked_condition_text"
)
_NOTE_FIELDS = "id,fruit_id,author,content,created_at"

# 一次「看盼圃」最多带回多少颗。挂着的果子没有上限压力（这面墙本来就是让人
# 看的），但一次返回太多会让工具结果本身变成噪音。
DEFAULT_LOOK_LIMIT = 30
MAX_LOOK_LIMIT = 100
# 每颗果子在列表里最多带几张纸条。要的是"底下贴着话"这个事实和最近说了什么，
# 完整的一串在摘的时候连纸条一起收进果壳里。
#
# 省略掉的那几张必须说出来（`earlier_notes`）。只给 note_count 配一个短数组，
# 沈予读到的是"这颗果子底下就这三句"——而被省掉的往往是最早那句，
# 也就是这场等待的开头。数字和数组对不上是静默的，所以这里明说。
NOTES_PER_FRUIT = 3


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _days_until(due_on: Any) -> Optional[int]:
    """离那天还有几天。负数表示过了——过了不是过期，只是还挂着。"""
    day = parse_local_date(due_on)
    return (day - local_today()).days if day else None


class OrchardService:
    """盼圃。没有任何自动注入路径——沈予不调工具，它就不在提示词里。"""

    def __init__(self, supabase: Any, cfg: Any = None, store: Any = None):
        self.supabase = supabase
        self.cfg = cfg
        # 果子和纸条在 Supabase，天气在本机卷。没有 store 时天气整层静默缺席，
        # 盼圃照旧能挂能贴能摘——天气是给它添真实感的，不是它的前提。
        self.store = store

    def _recall_index(self) -> RecallIndexService:
        return RecallIndexService(self.supabase, cfg=self.cfg)

    def _weather_service(self) -> QWeatherService:
        return QWeatherService(self.cfg)

    # ── 天气 ──────────────────────────────────────────────────────────
    # 四个动作都顺手做这一件事：读实况，若是极端天气就记一行。天气永远不该
    # 让盼圃打不开，所以整条路径 fail-soft——取不到就当今天是平常天气。

    async def _weather_now(self) -> dict[str, Any]:
        try:
            return await self._weather_service().current() or {}
        except Exception as exc:
            logger.warning("[Orchard] 读天气失败: %s", exc)
            return {}

    async def _garden_today(self) -> str:
        """园子今天什么天，顺带把极端天气记进本机库。"""
        weather = await self._weather_now()
        extreme = classify_weather(weather)
        if extreme:
            self._record_weather(extreme[0], extreme[1], weather)
        return garden_line(weather)

    def _record_weather(self, kind: str, detail: str, weather: dict[str, Any]) -> None:
        """记一场值得记的天气，写本机卷的 SQLite。

        `(on_day, kind)` 是唯一约束，所以同一天同一类天气只会有一行，四个动作
        都能放心地顺手写——重复和并发都靠约束挡掉，这里不查重。
        """
        if not self.store:
            return
        temp_c = None
        temp = weather.get("temp_c")
        if temp is not None:
            try:
                temp_c = int(round(float(temp)))
            except (TypeError, ValueError):
                temp_c = None
        try:
            self.store.record_orchard_weather(
                kind=kind,
                detail=detail,
                observed_text=_clean(weather.get("text")),
                temp_c=temp_c,
            )
        except Exception as exc:
            # 记不上就记不上：这一场天气不会在果子上留疤，但果子照旧能挂能摘。
            logger.warning("[Orchard] 记天气失败: %s", exc)

    def _weather_while_hanging(self, fruit: dict[str, Any]) -> list[dict[str, Any]]:
        """这颗果子挂着期间过过的天气，按日子正序。只在摘的时候读。"""
        if not self.store:
            return []
        planted_day = local_day_of(fruit.get("planted_at")) or parse_local_date(
            fruit.get("planted_at")
        )
        if planted_day is None:
            return []
        try:
            return self.store.orchard_weather_since(planted_day.isoformat())
        except Exception as exc:
            logger.warning("[Orchard] 读天气记录失败: %s", exc)
            return []

    def _unavailable(self) -> dict[str, Any]:
        return {"ok": False, "error": "Supabase is not configured.", "error_kind": "config"}

    # ── 种果子 ────────────────────────────────────────────────────────

    async def plant(
        self,
        *,
        name: Any,
        due_on: Any = None,
        actor: str = ACTOR_SHENYU,
    ) -> dict[str, Any]:
        if not self.supabase:
            return self._unavailable()
        title = _clean(name)
        if not title:
            return {"ok": False, "error": "果子得有个名字。一句话就行。", "error_kind": "validation"}

        payload: dict[str, Any] = {"name": title, "planted_by": actor}
        raw_due = _clean(due_on)
        if raw_due:
            parsed = parse_local_date(raw_due)
            if parsed is None:
                return {
                    "ok": False,
                    "error": "预计日期看不懂，要 YYYY-MM-DD。没日子就别传——没日子的果子就一直挂着等。",
                    "error_kind": "validation",
                }
            payload["due_on"] = parsed.isoformat()

        try:
            row = await self.supabase.insert(FRUITS_TABLE, payload)
        except Exception as exc:
            logger.warning("[Orchard] 种果子失败: %s", exc)
            return {"ok": False, "error": str(exc), "error_kind": "exception"}

        fruit = row if isinstance(row, dict) else {}
        return {
            "ok": True,
            "data": {
                "fruit": self._render_fruit(fruit, notes=[], note_count=0),
                "garden": await self._garden_today(),
            },
        }

    # ── 贴纸条 ────────────────────────────────────────────────────────

    async def add_note(
        self,
        *,
        fruit_id: Any = "",
        content: Any,
        name: Any = "",
        actor: str = ACTOR_SHENYU,
    ) -> dict[str, Any]:
        if not self.supabase:
            return self._unavailable()
        body = _clean(content)
        if not body:
            return {"ok": False, "error": "纸条上得写点什么。", "error_kind": "validation"}

        found = await self._resolve_fruit(fruit_id, name, action="贴")
        if not found.get("ok"):
            return found
        fruit = found["fruit"]
        target = _clean(fruit.get("id"))

        try:
            row = await self.supabase.insert(
                NOTES_TABLE,
                {"fruit_id": target, "author": actor, "content": body},
            )
        except Exception as exc:
            logger.warning("[Orchard] 贴纸条失败: %s", exc)
            return {"ok": False, "error": str(exc), "error_kind": "exception"}

        notes = await self._load_notes([target])
        fruit_notes = notes.get(target, [])
        # 刚贴的这张必须在末尾。按 created_at 排序时，库里的时间和这一行的时间
        # 理论上一致，但只要有一点偏差（时钟、默认值、同一秒并列）新纸条就会
        # 排到中间，读起来像是"最后一句话不是我刚说的那句"。
        new_id = _clean(row.get("id")) if isinstance(row, dict) else ""
        if new_id and fruit_notes and _clean(fruit_notes[-1].get("id")) != new_id:
            fruit_notes = [item for item in fruit_notes if _clean(item.get("id")) != new_id]
            fruit_notes.append(row)
        return {
            "ok": True,
            "data": {
                # 刚贴的那张不单独再列一遍：它就是 fruit.notes 的最后一条。
                # 同一句话出现两次会让人以为贴了两张。
                "fruit": self._render_fruit(
                    fruit,
                    notes=fruit_notes[-NOTES_PER_FRUIT:],
                    note_count=len(fruit_notes),
                ),
                "garden": await self._garden_today(),
            },
        }

    # ── 摘果子 ────────────────────────────────────────────────────────

    async def pick(
        self,
        *,
        fruit_id: Any = "",
        words: Any = "",
        name: Any = "",
        actor: str = ACTOR_SHENYU,
    ) -> dict[str, Any]:
        if not self.supabase:
            return self._unavailable()

        found = await self._resolve_fruit(fruit_id, name, action="摘")
        if not found.get("ok"):
            return found
        fruit = found["fruit"]
        target = _clean(fruit.get("id"))
        if _clean(fruit.get("status")) == "picked":
            return self._already_picked(fruit)

        notes = (await self._load_notes([target])).get(target, [])
        # 今天的天气也算它挂着期间的一场——先记，再连同旧的一起读回来，
        # 所以"今天下冰雹，我现在去摘"这件事真的会留在这颗果子上。
        garden = await self._garden_today()
        weather_events = self._weather_while_hanging(fruit)
        bucket, text = pick_condition(
            fruit,
            note_count=len(notes),
            last_note_at=notes[-1].get("created_at") if notes else None,
            weather_events=weather_events,
        )

        try:
            # 条件更新：只有还青着的那一行会被改到。两个人同时摘时，
            # 输的那个拿回空列表，而不是把对方的摘果感言覆盖掉。
            updated = await self.supabase.update(
                FRUITS_TABLE,
                {"id": f"eq.{target}", "status": "eq.green"},
                {
                    "status": "picked",
                    "picked_at": iso_now(),
                    "picked_by": actor,
                    "picked_words": _clean(words),
                    "picked_condition": bucket,
                    "picked_condition_text": text,
                },
            )
        except Exception as exc:
            logger.warning("[Orchard] 摘果子失败: %s", exc)
            return {"ok": False, "error": str(exc), "error_kind": "exception"}

        rows = updated if isinstance(updated, list) else []
        if not rows:
            # 这一局输了。重新读一遍，把对方摘的样子给出来。
            latest = await self._load_fruit(target)
            if latest and _clean(latest.get("status")) == "picked":
                return self._already_picked(latest)
            return {"ok": False, "error": "这颗果子刚才被动过，没摘成。", "error_kind": "conflict"}

        picked = rows[0] if isinstance(rows[0], dict) else {}
        # 摘了才进 Recall——青果子还在等，等的过程属于那面墙。索引失败不回滚：
        # 果子已经摘了是既成事实，只是这次它暂时不会被自动想起来。
        indexed = False
        try:
            index_result = await self._recall_index().index_orchard_fruit_row(picked, notes)
            indexed = bool(index_result.get("ok"))
            if not indexed:
                logger.warning("[Orchard] Recall indexing skipped: %s", index_result.get("error"))
        except Exception as exc:
            logger.warning("[Orchard] Recall indexing failed: %s", exc)

        return {
            "ok": True,
            "data": {
                "recallable": indexed,
                # 摘的时候连纸条一起收进果壳里——完整的一串在 fruit.notes 里，
                # 不在外面再列一遍：同一批东西出现两次会让人以为有两组。
                "fruit": self._render_fruit(picked, notes=notes, note_count=len(notes)),
                "garden": garden,
                # 只说真的留在这颗果子上的那场天气。挂着期间过过的每一场都列出来
                # 会让一颗挂三个月的果子甩回十几行跟它无关的天气——那才是噪音。
                "weathered": self._scar_story(picked, weather_events),
            },
        }

    def _scar_story(
        self,
        fruit: dict[str, Any],
        weather_events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """这颗果子真正挨到的那几场天气，让"为什么长成这样"能说清。

        用的是和留疤同一个判定（`fruit_took_scar`），所以这里列出来的每一场都
        确实打到了它。没打到的不列——那些是园子里的事，不是这颗果子的事。
        """
        fruit_id = _clean(fruit.get("id"))
        story = []
        for event in weather_events:
            kind = _clean(event.get("kind"))
            if not kind or not fruit_took_scar(fruit_id, event.get("on_day"), kind):
                continue
            story.append(
                {"on_day": event.get("on_day"), "detail": _clean(event.get("detail"))}
            )
        return story

    def _already_picked(self, fruit: dict[str, Any]) -> dict[str, Any]:
        who = _clean(fruit.get("picked_by")) or "有人"
        words = _clean(fruit.get("picked_words"))
        message = f"这颗已经被{who}摘了。"
        if words:
            message += f"他写的是：{words}"
        return {
            "ok": True,
            "data": {
                "already_picked": True,
                "message": message,
                "fruit": self._render_fruit(fruit, notes=[], note_count=0),
            },
        }

    # ── 看盼圃 ────────────────────────────────────────────────────────

    async def look(
        self,
        *,
        include_picked: bool = True,
        limit: int = DEFAULT_LOOK_LIMIT,
    ) -> dict[str, Any]:
        """青果子挂上面，摘了的沉下面。"""
        if not self.supabase:
            return self._unavailable()
        try:
            clamped = max(1, min(int(limit or DEFAULT_LOOK_LIMIT), MAX_LOOK_LIMIT))
        except (TypeError, ValueError):
            clamped = DEFAULT_LOOK_LIMIT

        try:
            green_rows = await self._query_fruits(
                {
                    "select": _FRUIT_FIELDS,
                    "status": "eq.green",
                    # 有日子的排前面、按日子近的先来；没日子的跟在后面按挂上去的顺序。
                    "order": "due_on.asc.nullslast,planted_at.asc",
                    "limit": str(clamped),
                }
            )
            picked_rows = []
            if include_picked:
                picked_rows = await self._query_fruits(
                    {
                        "select": _FRUIT_FIELDS,
                        "status": "eq.picked",
                        "order": "picked_at.desc",
                        "limit": str(clamped),
                    }
                )
        except Exception as exc:
            logger.warning("[Orchard] 看盼圃失败: %s", exc)
            return {"ok": False, "error": str(exc), "error_kind": "exception"}

        # 只数纸条，不取正文。看一眼墙需要知道的是"底下贴着几张"，具体说了
        # 什么在碰那颗果子的时候才看——十颗果子各带三张全文就是两千多 token。
        ids = [_clean(row.get("id")) for row in [*green_rows, *picked_rows]]
        counts = await self._note_counts([item for item in ids if item])

        def wall(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
            items = []
            for row in rows:
                count, last_at = counts.get(_clean(row.get("id")), (0, None))
                items.append(self._wall_fruit(row, note_count=count, last_note_at=last_at))
            return items

        return {
            "ok": True,
            "count": len(green_rows) + len(picked_rows),
            "data": {
                "today": local_today().isoformat(),
                "garden": await self._garden_today(),
                "hanging": wall(green_rows),
                "picked": wall(picked_rows),
            },
        }

    # ── 渲染 ──────────────────────────────────────────────────────────
    #
    # 两种粒度，刻意分开：
    #
    # - `_wall_fruit`：看整面墙时的一颗。只有名字、谁哪天挂的、还有几天、
    #   此刻什么样、底下有几张纸条。**不带纸条正文，不带 uuid。**
    # - `_render_fruit`：碰到某一颗时的那一颗。纸条正文、摘果感言、它挨过的
    #   天气都在这里。
    #
    # 分开的理由是体积：十颗果子各带三张纸条全文就是两千多 token，而沈予多数
    # 时候只是想看一眼墙上都挂着什么。想看某一颗的话，贴纸条或摘的时候自然
    # 就看到了。

    def _wall_fruit(
        self,
        fruit: dict[str, Any],
        *,
        note_count: int,
        last_note_at: Any = None,
    ) -> dict[str, Any]:
        """墙上的一颗，一眼扫过的粒度。"""
        status = _clean(fruit.get("status")) or "green"
        planted_day = local_day_of(fruit.get("planted_at"))
        item: dict[str, Any] = {
            "name": _clean(fruit.get("name")),
            # 挂的人和挂的日子说清就够，不给完整时间戳。
            "planted": f"{_clean(fruit.get('planted_by')) or '有人'}"
            f"{planted_day.isoformat() if planted_day else ''}挂的",
        }
        if note_count:
            item["notes"] = note_count
        if status == "picked":
            picked_day = local_day_of(fruit.get("picked_at"))
            item["picked"] = (
                f"{_clean(fruit.get('picked_by')) or '有人'}"
                f"{picked_day.isoformat() if picked_day else ''}摘的"
            )
            if _clean(fruit.get("picked_words")):
                item["words"] = _clean(fruit.get("picked_words"))
            item["condition"] = _clean(fruit.get("picked_condition_text"))
            return item

        due = _clean(fruit.get("due_on"))
        if due:
            days = _days_until(due)
            if days is None:
                item["due"] = due
            elif days > 0:
                item["due"] = f"{due}（还有 {days} 天）"
            elif days == 0:
                item["due"] = f"{due}（就是今天）"
            else:
                item["due"] = f"{due}（过了 {-days} 天，还挂着）"
        _bucket, text = green_condition(
            fruit, note_count=note_count, last_note_at=last_note_at
        )
        item["condition"] = text
        return item

    def _render_fruit(
        self,
        fruit: dict[str, Any],
        *,
        notes: list[dict[str, Any]],
        note_count: int,
    ) -> dict[str, Any]:
        status = _clean(fruit.get("status")) or "green"
        item: dict[str, Any] = {
            "id": _clean(fruit.get("id")),
            "name": _clean(fruit.get("name")),
            "planted_by": _clean(fruit.get("planted_by")),
            "planted_at": fruit.get("planted_at"),
            "due_on": _clean(fruit.get("due_on")) or None,
            "status": status,
            "note_count": note_count,
            # 只留作者、正文和时间：fruit_id 在外层已经有了，纸条自己的 id
            # 没有任何动作用得上——盼圃不能改也不能删纸条。
            "notes": [
                {
                    "author": _clean(note.get("author")),
                    "content": _clean(note.get("content")),
                    "at": note.get("created_at"),
                }
                for note in notes
            ],
        }
        if note_count > len(notes):
            item["earlier_notes"] = note_count - len(notes)
        if status == "picked":
            item["picked_at"] = fruit.get("picked_at")
            item["picked_by"] = _clean(fruit.get("picked_by"))
            item["picked_words"] = _clean(fruit.get("picked_words"))
            # 摘了的果子读库里定格的那句，绝不重算——重算就等于每次翻墙底下
            # 那排都在重新掷骰子，那条线就没了。
            #
            # 档位 key（ripe / tended…）不出现在返回里：那是网关内部算出来的
            # 标签，对读的人没用，而且它一度和墙上的 `condition` 同名不同义
            # ——同一个键在两个动作里是两种东西，比缺个字段更难读。
            item["condition"] = _clean(fruit.get("picked_condition_text"))
            return item

        _bucket, text = green_condition(
            fruit,
            note_count=note_count,
            last_note_at=notes[-1].get("created_at") if notes else None,
        )
        item["condition"] = text
        return item

    # ── 库 ────────────────────────────────────────────────────────────

    async def _query_fruits(self, params: dict[str, str]) -> list[dict[str, Any]]:
        rows = await self.supabase.query(FRUITS_TABLE, params)
        return [row for row in (rows or []) if isinstance(row, dict)]

    async def _resolve_fruit(self, fruit_id: Any, name: Any, *, action: str) -> dict[str, Any]:
        """认出说的是哪颗果子：给 id 或者直接给名字。

        果子的名字本来就是一句话（「蒜冒尖」），比 uuid 更像人会说的话，所以
        不该逼他先 look 一次抄个 id 回来——`shenyu_books` 的 read 也是 book_id
        或精确书名两条路都通。

        同名多颗时**不猜**，把那几颗列出来让他挑。贴错纸条等于把话说到另一件
        事上，那比多问一句糟得多。
        """
        target = _clean(fruit_id)
        if target:
            fruit = await self._load_fruit(target)
            if fruit is None:
                return {"ok": False, "error": "墙上没有这颗果子。", "error_kind": "not_found"}
            return {"ok": True, "fruit": fruit}

        title = _clean(name)
        if not title:
            return {
                "ok": False,
                "error": f"{action}哪颗？给 fruit_id，或者直接给果子的名字。",
                "error_kind": "validation",
            }

        # 先在青着的里面找：摘了的果子不该被"蒜冒尖"这个名字重新翻出来贴纸条。
        matches = await self._fruits_named(title, status="green")
        if not matches:
            matches = await self._fruits_named(title, status="")
        if not matches:
            return {
                "ok": False,
                "error": f"墙上没有叫「{title}」的果子。",
                "error_kind": "not_found",
            }
        if len(matches) > 1:
            listed = "；".join(
                f"{_clean(row.get('id'))}（{_clean(row.get('planted_by')) or '有人'}"
                f"{(_clean(row.get('planted_at'))[:10] or '')}挂的）"
                for row in matches[:5]
            )
            return {
                "ok": False,
                "error": f"墙上有 {len(matches)} 颗都叫「{title}」，说清是哪颗：{listed}",
                "error_kind": "ambiguous",
            }
        return {"ok": True, "fruit": matches[0]}

    async def _fruits_named(self, title: str, *, status: str) -> list[dict[str, Any]]:
        params = {
            "select": _FRUIT_FIELDS,
            "name": f"eq.{title}",
            "order": "planted_at.asc",
            "limit": "10",
        }
        if status:
            params["status"] = f"eq.{status}"
        try:
            return await self._query_fruits(params)
        except Exception as exc:
            logger.warning("[Orchard] 按名字找果子失败: %s", exc)
            return []

    async def _load_fruit(self, fruit_id: str) -> Optional[dict[str, Any]]:
        try:
            rows = await self._query_fruits(
                {"select": _FRUIT_FIELDS, "id": f"eq.{fruit_id}", "limit": "1"}
            )
        except Exception as exc:
            logger.warning("[Orchard] 读果子失败: %s", exc)
            return None
        return rows[0] if rows else None

    async def _note_counts(self, fruit_ids: list[str]) -> dict[str, tuple[int, Any]]:
        """每颗果子有几张纸条、最后一张是什么时候，不取正文。

        园况要"多久没人碰过"这个量，所以最后一张的时间必须拿到；正文不必——
        看一眼墙的时候，"底下贴着 3 张"就够了。
        """
        counts: dict[str, tuple[int, Any]] = {}
        unique = [item for item in dict.fromkeys(fruit_ids) if item]
        if not unique:
            return counts
        try:
            rows = await self.supabase.query(
                NOTES_TABLE,
                {
                    "select": "fruit_id,created_at",
                    "fruit_id": "in.(" + ",".join(unique) + ")",
                    "order": "created_at.asc",
                },
            )
        except Exception as exc:
            # 数不出来不该让整面墙打不开：果子照旧显示，只是不知道底下有几张。
            logger.warning("[Orchard] 数纸条失败: %s", exc)
            return counts
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            key = _clean(row.get("fruit_id"))
            previous = counts.get(key, (0, None))
            counts[key] = (previous[0] + 1, row.get("created_at"))
        return counts

    async def _load_notes(self, fruit_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
        """一次把这批果子的纸条全取回来，按时间正序分组。

        纸条读不出来不该让整面墙打不开：失败时返回空分组，果子照旧显示，
        只是这次看不到底下贴的话。
        """
        grouped: dict[str, list[dict[str, Any]]] = {}
        unique = [item for item in dict.fromkeys(fruit_ids) if item]
        if not unique:
            return grouped
        try:
            rows = await self.supabase.query(
                NOTES_TABLE,
                {
                    "select": _NOTE_FIELDS,
                    "fruit_id": "in.(" + ",".join(unique) + ")",
                    "order": "created_at.asc",
                },
            )
        except Exception as exc:
            logger.warning("[Orchard] 读纸条失败: %s", exc)
            return grouped
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            grouped.setdefault(_clean(row.get("fruit_id")), []).append(row)
        return grouped
