from __future__ import annotations

from typing import Any

from shenyu_gateway.orchard_service import ACTOR_SHENYU, OrchardService


class OrchardToolsMixin:
    """盼圃：一个工具，四个动作。行为都在 `orchard_service.py`。

    沈予调进来的一律记作他自己种的、他自己贴的、他自己摘的——走 Admin API
    那条路进来的才是圆圆。所以 actor 由入口决定，不做参数。
    """

    def _orchard(self) -> OrchardService:
        return OrchardService(self.supabase, cfg=self.cfg, store=self.store)

    async def orchard(
        self,
        *,
        action: Any = "",
        name: Any = "",
        fruit_id: Any = "",
        content: Any = "",
        due_on: Any = None,
        words: Any = "",
        include_picked: Any = True,
        limit: Any = 30,
        actor: str = ACTOR_SHENYU,
    ) -> dict:
        service = self._orchard()
        key = str(action or "").strip().lower()
        if key == "plant":
            return await service.plant(name=name, due_on=due_on, actor=actor)
        if key == "note":
            return await service.add_note(
                fruit_id=fruit_id, content=content, name=name, actor=actor
            )
        if key == "pick":
            return await service.pick(fruit_id=fruit_id, words=words, name=name, actor=actor)
        if key == "look":
            return await service.look(include_picked=bool(include_picked), limit=limit)
        return {
            "ok": False,
            "error": "action must be plant, note, pick, or look",
            "error_kind": "validation",
        }
