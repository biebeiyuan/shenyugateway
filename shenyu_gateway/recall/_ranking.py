from __future__ import annotations

from typing import Any, Optional

from ._text import _exact_title_query_values, _excerpt, _json_dict, _recency_score, normalize_recall_title


class RankingMixin:
    def _score_row(self, row: dict, query: str, tokens: list[str]) -> tuple[float, list[str]]:
        title = (row.get("title") or "").lower()
        search_text = (row.get("search_text") or "").lower()
        row_tokens = {str(item).lower() for item in row.get("search_tokens") or []}
        token_hits = [token for token in tokens if token in row_tokens or token in search_text]
        token_score = len(token_hits) / max(len(tokens), 1) if tokens else 0.15
        title_hits = [token for token in tokens if token in title]
        title_score = min(1.0, len(title_hits) / max(len(tokens), 1) * 1.5) if tokens else 0.0
        tag_text = " ".join(str(item).lower() for item in (row.get("tags_json") or []) + (row.get("entities_json") or []))
        tag_hits = [token for token in tokens if token in tag_text]
        tag_score = min(1.0, len(tag_hits) / max(len(tokens), 1) * 1.4) if tokens else 0.0
        phrase_bonus = 0.18 if query and query.lower() in search_text else 0.0
        keyword_score = min(1.0, token_score + phrase_bonus)
        field_score = min(1.0, title_score * 0.62 + tag_score * 0.38)
        vector_score = max(0.0, min(float(row.get("_vector_score") or 0.0), 1.0))
        graph_score = max(0.0, min(float(row.get("_graph_score") or 0.0), 1.0))
        importance = self._importance_score(row.get("importance"))
        recency = _recency_score(row.get("event_date") or row.get("source_updated_at"))
        if vector_score > 0:
            score = keyword_score * 0.40 + vector_score * 0.35 + field_score * 0.12 + importance * 0.08 + recency * 0.05
        else:
            score = keyword_score * 0.58 + field_score * 0.22 + importance * 0.10 + recency * 0.10
        if graph_score > 0:
            score += 0.72 if row.get("_graph_reason") == "direct" else 0.24
        reasons = []
        if token_hits:
            reasons.append("keyword:" + ",".join(token_hits[:6]))
        if title_hits:
            reasons.append("title")
        if tag_hits:
            reasons.append("tag/entity")
        if phrase_bonus:
            reasons.append("phrase")
        if vector_score > 0:
            reasons.append("semantic")
        if graph_score > 0:
            reasons.append(f"graph:{row.get('_graph_reason') or 'related'}")
        if importance >= 0.75:
            reasons.append("important")
        return min(score, 1.0), reasons or ["soft-recall"]

    def _match_tier(self, row: dict, query: str, reasons: list[str]) -> int:
        if "graph:direct" in reasons:
            return 5
        title = normalize_recall_title(row.get("title"))
        if title and title in _exact_title_query_values(query):
            return 4
        normalized_query = normalize_recall_title(query)
        if title and normalized_query and (normalized_query in title or title in normalized_query):
            return 3
        if "phrase" in reasons:
            return 2
        if "graph:related" in reasons:
            return 1
        if self._has_direct_match(reasons):
            return 1
        return 0

    def _importance_score(self, value: Any) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return 0.5
        if number <= 0:
            return 0.5
        return max(0.0, min(number, 1.0))

    def _has_direct_match(self, reasons: list[str]) -> bool:
        return any(reason.startswith("keyword:") or reason in {"title", "tag/entity", "phrase"} for reason in reasons)

    def _public_recall_match(self, row: dict[str, Any], reasons: list[str]) -> dict[str, Any]:
        """Expose a human-readable route for the read-only Admin preview only."""
        graph_reason = str(row.get("_graph_reason") or "")
        graph_info = row.get("_graph_info") if isinstance(row.get("_graph_info"), dict) else {}
        if graph_reason == "direct":
            anchor = graph_info.get("anchor") if isinstance(graph_info.get("anchor"), dict) else {}
            name = str(anchor.get("name") or "已确认锚点")
            return {
                "group": "direct",
                "label": f"直达：已确认锚点「{name}」",
                "anchor": anchor,
            }
        if graph_reason == "related":
            path = graph_info.get("path") if isinstance(graph_info.get("path"), dict) else {}
            source = path.get("from") if isinstance(path.get("from"), dict) else {}
            target = path.get("to") if isinstance(path.get("to"), dict) else {}
            relation = str(path.get("relation_type") or "已确认关系")
            source_name = str(source.get("name") or "已确认锚点")
            target_name = str(target.get("name") or "关联锚点")
            return {
                "group": "related",
                "label": f"关联：{source_name} - {relation} - {target_name}",
                "anchor": graph_info.get("anchor") or {},
                "path": path,
            }
        if "semantic" in reasons:
            label = "其他联想：原文语义相近"
        elif "phrase" in reasons:
            label = "其他联想：原文出现完整短语"
        elif "title" in reasons:
            label = "其他联想：标题匹配"
        elif any(reason.startswith("keyword:") for reason in reasons):
            label = "其他联想：原文关键词匹配"
        else:
            label = "其他联想"
        return {"group": "other", "label": label}

    def _public_item(self, row: dict, rows_by_source: dict[tuple[str, str], list[dict]]) -> dict[str, Any]:
        key = (str(row.get("source_table") or ""), str(row.get("source_id") or ""))
        source_rows = rows_by_source.get(key) or [row]
        matched_content = str(row.get("body") or row.get("excerpt") or "").strip()
        content = _excerpt(matched_content)
        item = {
            "content": content,
            "source_id": str(row.get("source_id") or ""),
        }
        if row.get("title"):
            item["title"] = row.get("title") or ""
        source_type = row.get("source_type") or ""
        source_table = row.get("source_table") or ""
        item["source_type"] = source_type
        item["source_table"] = source_table
        metadata = _json_dict(row.get("metadata_json"))
        if source_type == "journal":
            item["content_kind"] = (metadata.get("category") or "diary")
        elif source_type == "windowsill":
            item["content_kind"] = "windowsill"
            if metadata.get("mood"):
                item["mood"] = metadata.get("mood")
            if metadata.get("origin") == "room":
                item["origin"] = "写自房间"
        elif source_type == "album":
            item["content_kind"] = "album"
            # 相册命中时带上 photo_id，好让调用方能翻回那张图。
            if metadata.get("photo_id"):
                item["photo_id"] = metadata.get("photo_id")
            if metadata.get("book_name"):
                item["book_name"] = metadata.get("book_name")
            if metadata.get("mood"):
                item["mood"] = metadata.get("mood")
        elif source_type == "heartbeat":
            item["content_kind"] = "heartbeat"
        elif source_type == "board":
            item["content_kind"] = "message"
        else:
            item["content_kind"] = source_type or source_table
        item["event_date"] = row.get("event_date") or row.get("source_updated_at") or ""
        item["has_more"] = len(source_rows) > 1 or len(matched_content) > len(content)
        return item

    def _dedupe(self, scored: list[tuple[float, list[str], dict]], limit: int) -> list[tuple[float, list[str], dict]]:
        selected = []
        counts: dict[tuple[str, str], int] = {}
        for score, reasons, row in scored:
            key = (str(row.get("source_table") or ""), str(row.get("source_id") or ""))
            if counts.get(key, 0) >= 1:
                continue
            counts[key] = counts.get(key, 0) + 1
            selected.append((score, reasons, row))
            if len(selected) >= limit:
                break
        return selected

    def _rows_by_source(self, rows: list[dict]) -> dict[tuple[str, str], list[dict]]:
        grouped: dict[tuple[str, str], list[dict]] = {}
        for row in rows:
            key = (str(row.get("source_table") or ""), str(row.get("source_id") or ""))
            grouped.setdefault(key, []).append(row)
        for group in grouped.values():
            group.sort(key=lambda item: int(item.get("chunk_index") or 0))
        return grouped

    def _row_visible_for_session(self, row: dict, session_tag: Optional[str]) -> bool:
        visibility = (row.get("visibility") or "").strip().lower()
        row_session = (row.get("session_tag") or "").strip()
        if visibility in {"private", "hidden"}:
            return bool(session_tag and row_session == session_tag)
        return True
