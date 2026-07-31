from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from shenyu_gateway.runtime import logger
from shenyu_gateway.utils import normalize_text as _normalize_text


ENTITY_TABLE = "shenyu_entities"
ALIAS_TABLE = "shenyu_entity_aliases"
MENTION_TABLE = "shenyu_entity_mentions"
RELATION_TABLE = "shenyu_entity_relations"
RECALL_INDEX_TABLE = "shenyu_recall_index"
MEM_NOTES_TABLE = "shenyu_mem_notes"

ENTITY_TYPES = {"person", "place", "object", "topic"}
ENTITY_STATUSES = {"active", "archived", "merged"}
FACT_STATUSES = {"confirmed", "suggested", "rejected"}
RELATION_STATUSES = FACT_STATUSES | {"archived"}

_ASCII_WORD_RE = re.compile(r"^[a-z0-9][a-z0-9_.@+-]*$", re.IGNORECASE)


def normalize_alias(value: Any) -> str:
    text = unicodedata.normalize("NFKC", _normalize_text(value)).strip().casefold()
    return re.sub(r"\s+", " ", text)


def alias_matches_text(alias: Any, text: Any) -> bool:
    needle = normalize_alias(alias)
    haystack = unicodedata.normalize("NFKC", _normalize_text(text)).casefold()
    if not needle:
        return False
    if _ASCII_WORD_RE.fullmatch(needle):
        return bool(
            re.search(
                rf"(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])",
                haystack,
                flags=re.IGNORECASE,
            )
        )
    if len(needle) < 2:
        return False
    return needle in haystack


def _in_filter(values: Iterable[Any]) -> str:
    escaped = []
    for value in values:
        text = str(value).replace("\\", "\\\\").replace('"', '\\"')
        escaped.append(f'"{text}"')
    return "in.(" + ",".join(escaped) + ")"


def _clean_id(value: Any) -> str:
    return str(value or "").strip()


def _clean_text(value: Any, *, limit: int = 4000) -> str:
    return _normalize_text(value).strip()[:limit]


def _source_key(row: dict[str, Any]) -> tuple[str, str]:
    return (_clean_id(row.get("source_table")), _clean_id(row.get("source_id")))


def _is_current_relation(row: dict[str, Any]) -> bool:
    valid_to = _clean_text(row.get("valid_to"), limit=100)
    if not valid_to:
        return True
    try:
        parsed = datetime.fromisoformat(valid_to.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed >= datetime.now(timezone.utc)
    except ValueError:
        return False


class MemoryGraphService:
    """Personal graph metadata layered over immutable source-owned content."""

    def __init__(self, supabase: Any):
        self.supabase = supabase

    async def _query_all(
        self,
        table: str,
        params: Optional[dict[str, str]] = None,
        *,
        page_size: int = 1000,
    ) -> list[dict[str, Any]]:
        base = dict(params or {})
        base.pop("limit", None)
        base.pop("offset", None)
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = await self.supabase.query(
                table,
                {**base, "limit": str(page_size), "offset": str(offset)},
            )
            if not isinstance(page, list) or not page:
                break
            rows.extend(page)
            if len(page) < page_size:
                break
            offset += len(page)
        return rows

    async def snapshot(
        self,
        *,
        query: str = "",
        entity_type: Optional[str] = None,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        if not self.supabase:
            return {"ok": False, "available": False, "error": "Supabase is not configured."}
        try:
            entity_params = {"select": "*", "order": "canonical_name.asc"}
            if not include_archived:
                entity_params["status"] = "eq.active"
            if entity_type:
                entity_params["entity_type"] = f"eq.{entity_type}"
            entities = await self._query_all(ENTITY_TABLE, entity_params)
            entity_ids = {_clean_id(item.get("id")) for item in entities}
            aliases = await self._query_all(ALIAS_TABLE, {"select": "*", "order": "is_primary.desc,alias.asc"})
            mentions = await self._query_all(MENTION_TABLE, {"select": "*", "status": "eq.confirmed"})
            relations = await self._query_all(RELATION_TABLE, {"select": "*", "order": "updated_at.desc"})
        except Exception as exc:
            return {
                "ok": False,
                "available": False,
                "entities": [],
                "relations": [],
                "error": f"memory graph is not ready: {exc}",
            }

        aliases_by_entity: dict[str, list[dict[str, Any]]] = {}
        for alias in aliases:
            entity_id = _clean_id(alias.get("entity_id"))
            if entity_id in entity_ids:
                aliases_by_entity.setdefault(entity_id, []).append(alias)
        mention_counts: dict[str, int] = {}
        source_type_counts: dict[str, dict[str, int]] = {}
        last_mentioned: dict[str, str] = {}
        for mention in mentions:
            entity_id = _clean_id(mention.get("entity_id"))
            if entity_id not in entity_ids:
                continue
            mention_counts[entity_id] = mention_counts.get(entity_id, 0) + 1
            source_type = _clean_id(mention.get("source_type"))
            counts = source_type_counts.setdefault(entity_id, {})
            counts[source_type] = counts.get(source_type, 0) + 1
            stamp = _clean_id(mention.get("updated_at")) or _clean_id(mention.get("created_at"))
            if stamp and stamp > last_mentioned.get(entity_id, ""):
                last_mentioned[entity_id] = stamp
        relation_counts: dict[str, int] = {}
        for relation in relations:
            if relation.get("status") not in {"confirmed", "suggested"}:
                continue
            for key in ("source_entity_id", "target_entity_id"):
                entity_id = _clean_id(relation.get(key))
                relation_counts[entity_id] = relation_counts.get(entity_id, 0) + 1

        needle = normalize_alias(query)
        items = []
        for entity in entities:
            entity_id = _clean_id(entity.get("id"))
            item_aliases = aliases_by_entity.get(entity_id, [])
            if needle:
                searchable = " ".join(
                    [
                        normalize_alias(entity.get("canonical_name")),
                        normalize_alias(entity.get("description")),
                        *(normalize_alias(alias.get("alias")) for alias in item_aliases),
                    ]
                )
                if needle not in searchable:
                    continue
            items.append(
                {
                    **entity,
                    "aliases": item_aliases,
                    "mention_count": mention_counts.get(entity_id, 0),
                    "source_type_counts": source_type_counts.get(entity_id, {}),
                    "relation_count": relation_counts.get(entity_id, 0),
                    "last_mentioned_at": last_mentioned.get(entity_id) or None,
                }
            )
        visible_ids = {_clean_id(item.get("id")) for item in items}
        visible_relations = [
            relation
            for relation in relations
            if _clean_id(relation.get("source_entity_id")) in visible_ids
            or _clean_id(relation.get("target_entity_id")) in visible_ids
        ]
        entity_names = {
            _clean_id(entity.get("id")): _clean_text(entity.get("canonical_name"), limit=200)
            for entity in entities
        }
        recent: list[dict[str, Any]] = []
        for mention in mentions:
            entity_id = _clean_id(mention.get("entity_id"))
            if entity_id not in entity_ids:
                continue
            stamp = _clean_id(mention.get("updated_at")) or _clean_id(mention.get("created_at"))
            if not stamp:
                continue
            recent.append(
                {
                    "kind": "mention",
                    "entity_id": entity_id,
                    "entity_name": entity_names.get(entity_id, ""),
                    "source_table": _clean_id(mention.get("source_table")),
                    "source_type": _clean_id(mention.get("source_type")),
                    "source_id": _clean_id(mention.get("source_id")),
                    "at": stamp,
                }
            )
        for relation in relations:
            if relation.get("status") not in {"confirmed", "suggested"}:
                continue
            stamp = _clean_id(relation.get("updated_at")) or _clean_id(relation.get("created_at"))
            if not stamp:
                continue
            source_id = _clean_id(relation.get("source_entity_id"))
            target_id = _clean_id(relation.get("target_entity_id"))
            recent.append(
                {
                    "kind": "relation",
                    "relation_type": _clean_text(relation.get("relation_type"), limit=200),
                    "source_entity_id": source_id,
                    "target_entity_id": target_id,
                    "source_name": entity_names.get(source_id, ""),
                    "target_name": entity_names.get(target_id, ""),
                    "at": stamp,
                }
            )
        recent.sort(key=lambda item: item["at"], reverse=True)
        return {
            "ok": True,
            "available": True,
            "entities": items,
            "relations": visible_relations,
            "entity_count": len(items),
            "relation_count": len(visible_relations),
            "recent": recent[:12],
        }

    async def create_entity(
        self,
        *,
        entity_type: str,
        canonical_name: str,
        description: str = "",
        aliases: Optional[list[str]] = None,
        metadata: Optional[dict[str, Any]] = None,
        created_by: str = "resident",
    ) -> dict[str, Any]:
        kind = _clean_id(entity_type).lower()
        name = _clean_text(canonical_name, limit=200)
        if kind not in ENTITY_TYPES:
            return {"ok": False, "error": "entity_type must be person, place, object, or topic."}
        if not name:
            return {"ok": False, "error": "canonical_name is required."}
        row = await self.supabase.insert(
            ENTITY_TABLE,
            {
                "entity_type": kind,
                "canonical_name": name,
                "description": _clean_text(description),
                "metadata": metadata or {},
                "created_by": _clean_text(created_by, limit=100) or "resident",
            },
        )
        entity_id = _clean_id(row.get("id"))
        alias_values = [name, *(aliases or [])]
        seen: set[str] = set()
        created_aliases = []
        for index, value in enumerate(alias_values):
            normalized = normalize_alias(value)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            created_aliases.append(
                await self.supabase.insert(
                    ALIAS_TABLE,
                    {
                        "entity_id": entity_id,
                        "alias": _clean_text(value, limit=200),
                        "normalized_alias": normalized,
                        "status": "confirmed",
                        "is_primary": index == 0,
                        "provenance": "manual",
                        "created_by": _clean_text(created_by, limit=100) or "resident",
                    },
                )
            )
        return {"ok": True, "entity": {**row, "aliases": created_aliases}}

    async def update_entity(self, entity_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        normalized_id = _clean_id(entity_id)
        allowed = {"entity_type", "canonical_name", "description", "status", "merged_into", "metadata"}
        update = {key: value for key, value in (patch or {}).items() if key in allowed}
        if "entity_type" in update:
            update["entity_type"] = _clean_id(update["entity_type"]).lower()
            if update["entity_type"] not in ENTITY_TYPES:
                return {"ok": False, "error": "invalid entity_type."}
        if "canonical_name" in update:
            update["canonical_name"] = _clean_text(update["canonical_name"], limit=200)
            if not update["canonical_name"]:
                return {"ok": False, "error": "canonical_name is required."}
        if "description" in update:
            update["description"] = _clean_text(update["description"])
        if "status" in update:
            update["status"] = _clean_id(update["status"]).lower()
            if update["status"] not in ENTITY_STATUSES:
                return {"ok": False, "error": "invalid entity status."}
        if not update:
            return {"ok": False, "error": "no supported fields to update."}
        rows = await self.supabase.update(ENTITY_TABLE, {"id": normalized_id}, update)
        if "canonical_name" in update:
            aliases = await self.supabase.query(
                ALIAS_TABLE,
                {"select": "*", "entity_id": f"eq.{normalized_id}", "limit": "500"},
            )
            new_normalized = normalize_alias(update["canonical_name"])
            primary = next((row for row in aliases if row.get("is_primary")), None)
            matching = next(
                (row for row in aliases if normalize_alias(row.get("normalized_alias") or row.get("alias")) == new_normalized),
                None,
            )
            if matching:
                if primary and primary.get("id") != matching.get("id"):
                    await self.supabase.update(ALIAS_TABLE, {"id": _clean_id(primary.get("id"))}, {"is_primary": False})
                await self.supabase.update(
                    ALIAS_TABLE,
                    {"id": _clean_id(matching.get("id"))},
                    {"alias": update["canonical_name"], "normalized_alias": new_normalized, "is_primary": True, "status": "confirmed"},
                )
            elif primary:
                await self.supabase.insert(
                    ALIAS_TABLE,
                    {
                        "entity_id": normalized_id,
                        "alias": update["canonical_name"],
                        "normalized_alias": new_normalized,
                        "status": "confirmed",
                        "is_primary": True,
                        "provenance": "manual",
                        "created_by": "resident",
                    },
                )
                await self.supabase.update(
                    ALIAS_TABLE,
                    {"id": _clean_id(primary.get("id"))},
                    {"is_primary": False},
                )
            else:
                await self.supabase.insert(
                    ALIAS_TABLE,
                    {
                        "entity_id": normalized_id,
                        "alias": update["canonical_name"],
                        "normalized_alias": new_normalized,
                        "status": "confirmed",
                        "is_primary": True,
                        "provenance": "manual",
                        "created_by": "resident",
                    },
                )
        return {"ok": True, "entity": rows[0] if rows else None}

    async def add_alias(
        self,
        entity_id: str,
        *,
        alias: str,
        status: str = "confirmed",
        evidence: str = "",
        provenance: str = "manual",
        created_by: str = "resident",
    ) -> dict[str, Any]:
        value = _clean_text(alias, limit=200)
        normalized = normalize_alias(value)
        resolved_status = _clean_id(status).lower() or "confirmed"
        if not normalized:
            return {"ok": False, "error": "alias is required."}
        if resolved_status not in FACT_STATUSES:
            return {"ok": False, "error": "invalid alias status."}
        row = await self.supabase.insert(
            ALIAS_TABLE,
            {
                "entity_id": _clean_id(entity_id),
                "alias": value,
                "normalized_alias": normalized,
                "status": resolved_status,
                "confidence": 1.0 if resolved_status == "confirmed" else 0.5,
                "provenance": _clean_text(provenance, limit=100) or "manual",
                "evidence": _clean_text(evidence),
                "created_by": _clean_text(created_by, limit=100) or "resident",
            },
        )
        return {"ok": True, "alias": row}

    async def delete_alias(self, alias_id: str) -> dict[str, Any]:
        rows = await self.supabase.delete(ALIAS_TABLE, {"id": _clean_id(alias_id), "is_primary": "eq.false"})
        if not rows:
            return {"ok": False, "error": "alias not found or primary alias cannot be deleted."}
        return {"ok": True, "deleted": rows}

    async def update_alias(self, alias_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = {"status", "evidence"}
        update = {key: value for key, value in (patch or {}).items() if key in allowed}
        if "status" in update:
            update["status"] = _clean_id(update["status"]).lower()
            if update["status"] not in FACT_STATUSES:
                return {"ok": False, "error": "invalid alias status."}
            if update["status"] == "confirmed":
                update["confidence"] = 1.0
        if "evidence" in update:
            update["evidence"] = _clean_text(update["evidence"])
        if not update:
            return {"ok": False, "error": "no supported fields to update."}
        rows = await self.supabase.update(ALIAS_TABLE, {"id": _clean_id(alias_id)}, update)
        if not rows:
            return {"ok": False, "error": "alias not found."}
        return {"ok": True, "alias": rows[0]}

    async def name_candidates(self, *, limit: int = 30) -> dict[str, Any]:
        """Names already extracted into mem-note people/places/objects but not yet anchored."""
        aliases = await self.supabase.query(
            ALIAS_TABLE,
            {"select": "normalized_alias", "limit": "2000"},
        )
        known = {_clean_id(row.get("normalized_alias")) for row in aliases}
        notes = await self.supabase.query(
            MEM_NOTES_TABLE,
            {
                "select": "people,places,objects,status",
                "status": "in.(captured,active)",
                "limit": "1000",
            },
        )
        counts: dict[str, dict[str, Any]] = {}
        for note in notes:
            for field, kind in (("people", "person"), ("places", "place"), ("objects", "object")):
                values = note.get(field) or []
                if not isinstance(values, list):
                    continue
                for value in values:
                    name = _clean_text(value, limit=80)
                    normalized = normalize_alias(name)
                    if len(normalized) < 2 or normalized in known:
                        continue
                    slot = counts.setdefault(normalized, {"name": name, "kind": kind, "count": 0})
                    slot["count"] += 1
        ranked = sorted(counts.values(), key=lambda item: (-item["count"], item["name"]))
        return {"ok": True, "candidates": ranked[: max(1, min(int(limit or 30), 100))]}

    async def create_relation(
        self,
        *,
        source_entity_id: str,
        target_entity_id: str,
        relation_type: str,
        status: str = "confirmed",
        evidence: str = "",
        provenance: str = "manual",
        evidence_source_table: Optional[str] = None,
        evidence_source_type: Optional[str] = None,
        evidence_source_id: Optional[str] = None,
        valid_from: Optional[str] = None,
        valid_to: Optional[str] = None,
        created_by: str = "resident",
    ) -> dict[str, Any]:
        source_id = _clean_id(source_entity_id)
        target_id = _clean_id(target_entity_id)
        relation = _clean_text(relation_type, limit=120)
        resolved_status = _clean_id(status).lower() or "confirmed"
        if not source_id or not target_id or source_id == target_id:
            return {"ok": False, "error": "two different entities are required."}
        if not relation:
            return {"ok": False, "error": "relation_type is required."}
        if resolved_status not in RELATION_STATUSES:
            return {"ok": False, "error": "invalid relation status."}
        row = await self.supabase.insert(
            RELATION_TABLE,
            {
                "source_entity_id": source_id,
                "target_entity_id": target_id,
                "relation_type": relation,
                "status": resolved_status,
                "confidence": 1.0 if resolved_status == "confirmed" else 0.5,
                "evidence": _clean_text(evidence),
                "provenance": _clean_text(provenance, limit=100) or "manual",
                "evidence_source_table": _clean_id(evidence_source_table) or None,
                "evidence_source_type": _clean_id(evidence_source_type) or None,
                "evidence_source_id": _clean_id(evidence_source_id) or None,
                "valid_from": _clean_id(valid_from) or None,
                "valid_to": _clean_id(valid_to) or None,
                "created_by": _clean_text(created_by, limit=100) or "resident",
            },
        )
        return {"ok": True, "relation": row}

    async def update_relation(self, relation_id: str, patch: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "relation_type", "status", "evidence", "provenance", "valid_from", "valid_to",
            "evidence_source_table", "evidence_source_type", "evidence_source_id",
        }
        update = {key: value for key, value in (patch or {}).items() if key in allowed}
        if "relation_type" in update:
            update["relation_type"] = _clean_text(update["relation_type"], limit=120)
            if not update["relation_type"]:
                return {"ok": False, "error": "relation_type is required."}
        if "status" in update:
            update["status"] = _clean_id(update["status"]).lower()
            if update["status"] not in RELATION_STATUSES:
                return {"ok": False, "error": "invalid relation status."}
        rows = await self.supabase.update(RELATION_TABLE, {"id": _clean_id(relation_id)}, update)
        return {"ok": True, "relation": rows[0] if rows else None}

    async def source_entities(
        self,
        source_table: str,
        source_id: str,
    ) -> dict[str, Any]:
        mentions = await self.supabase.query(
            MENTION_TABLE,
            {
                "select": "*",
                "source_table": f"eq.{_clean_id(source_table)}",
                "source_id": f"eq.{_clean_id(source_id)}",
                "status": "eq.confirmed",
                "order": "origin.asc,updated_at.desc",
                "limit": "500",
            },
        )
        entity_ids = {_clean_id(item.get("entity_id")) for item in mentions}
        entities = []
        if entity_ids:
            entities = await self.supabase.query(
                ENTITY_TABLE,
                {"select": "*", "id": _in_filter(entity_ids), "limit": "500"},
            )
        by_id = {_clean_id(item.get("id")): item for item in entities}
        return {
            "ok": True,
            "mentions": [
                {**mention, "entity": by_id.get(_clean_id(mention.get("entity_id")))}
                for mention in mentions
            ],
        }

    async def delete_source_mentions(self, source_table: str, source_id: str) -> int:
        rows = await self.supabase.delete(
            MENTION_TABLE,
            {
                "source_table": _clean_id(source_table),
                "source_id": _clean_id(source_id),
            },
        )
        return len(rows) if isinstance(rows, list) else 0

    async def replace_manual_source_entities(
        self,
        *,
        source_table: str,
        source_type: str,
        source_id: str,
        entity_ids: list[str],
        evidence: str = "",
    ) -> dict[str, Any]:
        table = _clean_id(source_table)
        kind = _clean_id(source_type)
        item_id = _clean_id(source_id)
        if not table or not kind or not item_id:
            return {"ok": False, "error": "source_table, source_type, and source_id are required."}
        selected = {_clean_id(value) for value in entity_ids if _clean_id(value)}
        existing = await self.supabase.query(
            MENTION_TABLE,
            {
                "select": "*",
                "source_table": f"eq.{table}",
                "source_id": f"eq.{item_id}",
                "limit": "500",
            },
        )
        existing_by_entity = {_clean_id(row.get("entity_id")): row for row in existing}
        removed = 0
        for entity_id, row in existing_by_entity.items():
            if row.get("origin") == "manual" and entity_id not in selected:
                await self.supabase.delete(MENTION_TABLE, {"id": _clean_id(row.get("id"))})
                removed += 1
        linked = 0
        for entity_id in selected:
            payload = {
                "source_type": kind,
                "status": "confirmed",
                "origin": "manual",
                "matched_alias": None,
                "confidence": 1.0,
                "evidence": _clean_text(evidence),
                "created_by": "resident",
            }
            current = existing_by_entity.get(entity_id)
            if current:
                await self.supabase.update(MENTION_TABLE, {"id": _clean_id(current.get("id"))}, payload)
            else:
                await self.supabase.insert(
                    MENTION_TABLE,
                    {
                        **payload,
                        "entity_id": entity_id,
                        "source_table": table,
                        "source_id": item_id,
                    },
                )
            linked += 1
        return {"ok": True, "linked": linked, "removed": removed}

    async def confirmed_alias_index(self) -> dict[str, list[dict[str, Any]]]:
        aliases = await self._query_all(
            ALIAS_TABLE,
            {"select": "id,entity_id,alias,normalized_alias,status", "status": "eq.confirmed"},
        )
        entity_ids = {_clean_id(row.get("entity_id")) for row in aliases}
        entities = []
        if entity_ids:
            entities = await self._query_all(
                ENTITY_TABLE,
                {"select": "id,canonical_name,entity_type,status", "status": "eq.active"},
            )
        active = {_clean_id(row.get("id")): row for row in entities}
        index: dict[str, list[dict[str, Any]]] = {}
        for alias in aliases:
            entity_id = _clean_id(alias.get("entity_id"))
            if entity_id not in active:
                continue
            normalized = normalize_alias(alias.get("normalized_alias") or alias.get("alias"))
            if not normalized:
                continue
            index.setdefault(normalized, []).append({**alias, "entity": active[entity_id]})
        return index

    def resolve_text_entities(
        self,
        text: str,
        alias_index: dict[str, list[dict[str, Any]]],
    ) -> dict[str, dict[str, Any]]:
        matched: dict[str, dict[str, Any]] = {}
        for normalized, rows in alias_index.items():
            entity_ids = {_clean_id(row.get("entity_id")) for row in rows}
            if len(entity_ids) != 1 or not alias_matches_text(normalized, text):
                continue
            row = rows[0]
            entity_id = next(iter(entity_ids))
            previous = matched.get(entity_id)
            if not previous or len(normalized) > len(str(previous.get("normalized_alias") or "")):
                matched[entity_id] = row
        return matched

    async def sync_source_alias_mentions(
        self,
        *,
        source_table: str,
        source_type: str,
        source_id: str,
        text: str,
        source_content_hash: Optional[str] = None,
        alias_index: Optional[dict[str, list[dict[str, Any]]]] = None,
    ) -> dict[str, Any]:
        alias_index = alias_index if alias_index is not None else await self.confirmed_alias_index()
        matches = self.resolve_text_entities(text, alias_index)
        existing = await self.supabase.query(
            MENTION_TABLE,
            {
                "select": "*",
                "source_table": f"eq.{_clean_id(source_table)}",
                "source_id": f"eq.{_clean_id(source_id)}",
                "limit": "500",
            },
        )
        existing_by_entity = {_clean_id(row.get("entity_id")): row for row in existing}
        removed = 0
        for entity_id, row in existing_by_entity.items():
            if row.get("origin") == "exact_alias" and entity_id not in matches:
                await self.supabase.delete(MENTION_TABLE, {"id": _clean_id(row.get("id"))})
                removed += 1
        linked = 0
        for entity_id, alias_row in matches.items():
            current = existing_by_entity.get(entity_id)
            if current and current.get("origin") in {"manual", "structural"}:
                continue
            payload = {
                "source_type": _clean_id(source_type),
                "status": "confirmed",
                "origin": "exact_alias",
                "matched_alias": alias_row.get("alias"),
                "confidence": 1.0,
                "evidence": "unique confirmed alias matched source text",
                "source_content_hash": source_content_hash,
                "created_by": "gateway",
            }
            if current:
                await self.supabase.update(MENTION_TABLE, {"id": _clean_id(current.get("id"))}, payload)
            else:
                await self.supabase.insert(
                    MENTION_TABLE,
                    {
                        **payload,
                        "entity_id": entity_id,
                        "source_table": _clean_id(source_table),
                        "source_id": _clean_id(source_id),
                    },
                )
            linked += 1
        return {"ok": True, "matched": len(matches), "linked": linked, "removed": removed}

    async def sync_recall_documents(self, documents: list[Any]) -> dict[str, Any]:
        if not documents:
            return {"ok": True, "sources": 0, "mentions": 0}
        alias_index = await self.confirmed_alias_index()
        grouped: dict[tuple[str, str, str], list[Any]] = {}
        for document in documents:
            key = (
                _clean_id(getattr(document, "source_table", "")),
                _clean_id(getattr(document, "source_type", "")),
                _clean_id(getattr(document, "source_id", "")),
            )
            grouped.setdefault(key, []).append(document)
        sources: list[dict[str, Any]] = []
        for (source_table, source_type, source_id), docs in grouped.items():
            text = "\n".join(
                "\n".join(
                    [
                        _clean_text(getattr(doc, "title", "")),
                        _clean_text(getattr(doc, "body", ""), limit=100000),
                    ]
                )
                for doc in docs
            )
            sources.append({
                "source_table": source_table,
                "source_type": source_type,
                "source_id": source_id,
                "text": text,
                "source_content_hash": _clean_id(getattr(docs[0], "content_hash", "")) or None,
            })
        result = await self._sync_sources_batch(sources, alias_index)
        return {
            "ok": result["ok"],
            "sources": len(grouped),
            "mentions": result["linked"],
            "removed": result["removed"],
            "errors": result["errors"],
        }

    async def _sync_sources_batch(
        self,
        sources: list[dict[str, Any]],
        alias_index: dict[str, list[dict[str, Any]]],
    ) -> dict[str, Any]:
        if not sources:
            return {"ok": True, "linked": 0, "removed": 0, "errors": {}}
        source_keys = {
            (_clean_id(source["source_table"]), _clean_id(source["source_id"]))
            for source in sources
        }
        existing_rows = await self._query_all(MENTION_TABLE, {"select": "*"})
        existing: dict[tuple[str, str, str], dict[str, Any]] = {}
        for row in existing_rows:
            source_key = _source_key(row)
            if source_key not in source_keys:
                continue
            existing[(source_key[0], source_key[1], _clean_id(row.get("entity_id")))] = row

        upsert_rows: list[dict[str, Any]] = []
        stale_ids: list[str] = []
        for source in sources:
            source_table = _clean_id(source["source_table"])
            source_type = _clean_id(source["source_type"])
            source_id = _clean_id(source["source_id"])
            matches = self.resolve_text_entities(_clean_text(source.get("text"), limit=1000000), alias_index)
            matched_ids = set(matches)
            source_existing = {
                entity_id: row
                for (table, item_id, entity_id), row in existing.items()
                if table == source_table and item_id == source_id
            }
            stale_ids.extend(
                _clean_id(row.get("id"))
                for entity_id, row in source_existing.items()
                if row.get("origin") == "exact_alias" and entity_id not in matched_ids and _clean_id(row.get("id"))
            )
            for entity_id, alias_row in matches.items():
                current = source_existing.get(entity_id)
                if current and current.get("origin") in {"manual", "structural"}:
                    continue
                upsert_rows.append({
                    "entity_id": entity_id,
                    "source_table": source_table,
                    "source_type": source_type,
                    "source_id": source_id,
                    "status": "confirmed",
                    "origin": "exact_alias",
                    "matched_alias": alias_row.get("alias"),
                    "confidence": 1.0,
                    "evidence": "unique confirmed alias matched source text",
                    "source_content_hash": source.get("source_content_hash"),
                    "created_by": "gateway",
                })

        errors: dict[str, str] = {}
        for start in range(0, len(upsert_rows), 100):
            batch = upsert_rows[start : start + 100]
            try:
                if hasattr(self.supabase, "upsert"):
                    await self.supabase.upsert(
                        MENTION_TABLE,
                        batch,
                        on_conflict="entity_id,source_table,source_id",
                    )
                else:
                    for row in batch:
                        key = (row["source_table"], row["source_id"], row["entity_id"])
                        current = existing.get(key)
                        if current:
                            await self.supabase.update(MENTION_TABLE, {"id": _clean_id(current.get("id"))}, row)
                        else:
                            await self.supabase.insert(MENTION_TABLE, row)
            except Exception as exc:
                errors[f"upsert:{start}"] = str(exc)
        for start in range(0, len(stale_ids), 100):
            batch = stale_ids[start : start + 100]
            try:
                await self.supabase.delete(MENTION_TABLE, {"id": _in_filter(batch)})
            except Exception as exc:
                errors[f"delete:{start}"] = str(exc)
        return {
            "ok": not errors,
            "linked": len(upsert_rows),
            "removed": len(stale_ids),
            "errors": errors,
        }

    async def backfill_from_recall_index(self, *, max_sources: Optional[int] = None) -> dict[str, Any]:
        rows = await self._query_all(
            RECALL_INDEX_TABLE,
            {"select": "*", "deleted_at": "is.null", "order": "source_table.asc,source_id.asc,chunk_index.asc"},
        )
        alias_index = await self.confirmed_alias_index()
        grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
        for row in rows:
            key = (
                _clean_id(row.get("source_table")),
                _clean_id(row.get("source_type")),
                _clean_id(row.get("source_id")),
            )
            grouped.setdefault(key, []).append(row)
        items = list(grouped.items())
        if max_sources is not None:
            items = items[: max(1, min(int(max_sources), 100000))]
        sources: list[dict[str, Any]] = []
        matched_sources = 0
        for (source_table, source_type, source_id), source_rows in items:
            text = "\n".join(
                "\n".join(
                    [
                        _clean_text(row.get("title")),
                        _clean_text(row.get("body"), limit=100000),
                    ]
                )
                for row in source_rows
            )
            if self.resolve_text_entities(text, alias_index):
                matched_sources += 1
            sources.append({
                "source_table": source_table,
                "source_type": source_type,
                "source_id": source_id,
                "text": text,
                "source_content_hash": _clean_id(source_rows[0].get("content_hash")) or None,
            })
        result = await self._sync_sources_batch(sources, alias_index)
        return {
            "ok": result["ok"],
            "scanned_sources": len(items),
            "matched_sources": matched_sources,
            "linked_mentions": result["linked"],
            "removed_mentions": result["removed"],
            "errors": result["errors"],
        }

    async def recall_rows(
        self,
        query: str,
        *,
        source_types: Optional[list[str]] = None,
        max_mentions: int = 160,
    ) -> list[dict[str, Any]]:
        try:
            alias_index = await self.confirmed_alias_index()
            direct_matches = self.resolve_text_entities(query, alias_index)
            direct_ids = set(direct_matches)
            if not direct_ids:
                return []

            entity_by_id: dict[str, dict[str, Any]] = {}
            for alias_rows in alias_index.values():
                for alias_row in alias_rows:
                    entity = alias_row.get("entity")
                    entity_id = _clean_id(alias_row.get("entity_id"))
                    if entity_id and isinstance(entity, dict):
                        entity_by_id[entity_id] = entity

            def entity_summary(entity_id: str) -> dict[str, str]:
                entity = entity_by_id.get(entity_id) or {}
                return {
                    "id": entity_id,
                    "name": _clean_text(entity.get("canonical_name"), limit=200) or "未命名锚点",
                    "type": _clean_id(entity.get("entity_type")),
                }

            direct_mentions = await self.supabase.query(
                MENTION_TABLE,
                {
                    "select": "*",
                    "entity_id": _in_filter(direct_ids),
                    "status": "eq.confirmed",
                    "order": "updated_at.desc",
                    "limit": str(max_mentions),
                },
            )
            outgoing = await self.supabase.query(
                RELATION_TABLE,
                {
                    "select": "*",
                    "source_entity_id": _in_filter(direct_ids),
                    "status": "eq.confirmed",
                    "limit": "500",
                },
            )
            incoming = await self.supabase.query(
                RELATION_TABLE,
                {
                    "select": "*",
                    "target_entity_id": _in_filter(direct_ids),
                    "status": "eq.confirmed",
                    "limit": "500",
                },
            )
            relations = [row for row in outgoing + incoming if _is_current_relation(row)]
            related_ids: set[str] = set()
            related_paths: dict[str, dict[str, Any]] = {}
            for relation in relations:
                source_id = _clean_id(relation.get("source_entity_id"))
                target_id = _clean_id(relation.get("target_entity_id"))
                if source_id in direct_ids and target_id not in direct_ids:
                    related_ids.add(target_id)
                    related_paths.setdefault(
                        target_id,
                        {
                            "from": entity_summary(source_id),
                            "relation_type": _clean_text(relation.get("relation_type"), limit=200),
                            "to": entity_summary(target_id),
                        },
                    )
                if target_id in direct_ids and source_id not in direct_ids:
                    related_ids.add(source_id)
                    related_paths.setdefault(
                        source_id,
                        {
                            "from": entity_summary(target_id),
                            "relation_type": _clean_text(relation.get("relation_type"), limit=200),
                            "to": entity_summary(source_id),
                        },
                    )
            related_mentions = []
            if related_ids:
                related_mentions = await self.supabase.query(
                    MENTION_TABLE,
                    {
                        "select": "*",
                        "entity_id": _in_filter(related_ids),
                        "status": "eq.confirmed",
                        "order": "updated_at.desc",
                        "limit": str(max_mentions),
                    },
                )
        except Exception as exc:
            logger.info("Memory graph recall unavailable; continuing without graph: %s", exc)
            return []

        source_scores: dict[tuple[str, str], tuple[float, str, dict[str, Any]]] = {}
        for mention in direct_mentions:
            entity_id = _clean_id(mention.get("entity_id"))
            matched = direct_matches.get(entity_id) or {}
            source_scores[_source_key(mention)] = (
                1.0,
                "direct",
                {
                    "kind": "direct",
                    "anchor": entity_summary(entity_id),
                    "matched_alias": _clean_text(matched.get("alias"), limit=200),
                },
            )
        for mention in related_mentions:
            key = _source_key(mention)
            if key not in source_scores:
                entity_id = _clean_id(mention.get("entity_id"))
                source_scores[key] = (
                    0.68,
                    "related",
                    {
                        "kind": "related",
                        "anchor": entity_summary(entity_id),
                        "path": related_paths.get(entity_id),
                    },
                )
        if not source_scores:
            return []
        source_ids = {source_id for _, source_id in source_scores if source_id}
        try:
            rows = []
            ordered_ids = sorted(source_ids)
            for start in range(0, len(ordered_ids), 80):
                rows.extend(await self.supabase.query(
                    RECALL_INDEX_TABLE,
                    {
                        "select": "*",
                        "source_id": _in_filter(ordered_ids[start : start + 80]),
                        "deleted_at": "is.null",
                        "order": "importance.desc,event_date.desc,indexed_at.desc",
                        "limit": "1000",
                    },
                ))
        except Exception as exc:
            logger.info("Memory graph source hydration unavailable; continuing without graph: %s", exc)
            return []
        allowed = set(source_types or [])
        result = []
        for row in rows:
            key = _source_key(row)
            graph = source_scores.get(key)
            if not graph:
                continue
            if allowed and _clean_id(row.get("source_type")) not in allowed:
                continue
            score, reason, info = graph
            result.append(
                {
                    **row,
                    "_graph_score": score,
                    "_graph_reason": reason,
                    "_graph_info": info,
                }
            )
        return result
