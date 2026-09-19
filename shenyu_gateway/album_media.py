"""Photo reference contracts; display references are not model vision inputs."""
from __future__ import annotations

import re
import base64
import json
from copy import deepcopy
from typing import Any

MAX_MEDIA_ITEMS = 9
PHOTO_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp", "image/gif"})
ALBUM_VIEW_KEY = "_shenyu_album_view"
TOOL_IMAGES_KEY = "_shenyu_tool_images"
PHOTO_ID = re.compile(r"^phot_[a-zA-Z0-9_-]{1,100}$")
FINGERPRINT = re.compile(r"^[a-f0-9]{64}$")


def photo_reference(row: dict) -> dict[str, str]:
    return {
        "title": str(row.get("book_name") or ""),
        "content": "\n".join(str(row.get(key) or "") for key in ("note", "mood") if row.get(key)),
        "photo_id": str(row.get("id") or ""),
    }


class AlbumToolResult(dict):
    """Private effect attributes never appear in JSON/log/tool-result text."""

    def __init__(self, photo: dict, *, view: bool = False, send: bool = False):
        super().__init__(ok=True, data=photo_reference(photo))
        self.view_photo_id = str(photo["id"]) if view else ""
        self.send_photo_id = str(photo["id"]) if send else ""
        self.shared_media: dict | None = None


def clean_media(value: Any, *, album: bool = False) -> list[dict]:
    """Whitelist metadata; never copy URLs, bytes or unknown nested fields."""
    if not isinstance(value, list):
        return []
    cleaned: list[dict] = []
    seen: set[str] = set()
    for item in value[:MAX_MEDIA_ITEMS]:
        if not isinstance(item, dict):
            continue
        identity = item.get("id")
        if not isinstance(identity, str) or not identity or len(identity) > 160 or identity in seen:
            continue
        seen.add(identity)
        row = {"id": identity, "name": str(item.get("name") or "照片")[:256],
               "mime": str(item.get("mime") or "image/jpeg")[:80]}
        digest = item.get("fingerprint")
        if isinstance(digest, str) and FINGERPRINT.fullmatch(digest):
            row["fingerprint"] = digest
        photo_id = item.get("photo_id")
        if album and isinstance(photo_id, str) and PHOTO_ID.fullmatch(photo_id):
            row["photo_id"] = photo_id
            row["title"] = str(item.get("title") or "")
            row["content"] = str(item.get("content") or "")
        cleaned.append(row)
    return cleaned


def finish_album_action(ctx: Any, result: dict, tool_call_id: str) -> dict:
    """Commit an explicit share before reporting success or emitting its event."""
    if not isinstance(result, AlbumToolResult) or not result.send_photo_id:
        return result
    from .chat_archive import parse_archive_event
    event = parse_archive_event(ctx.meta.get("reply_archive_event"))
    profile = ctx.meta.get("client_profile") or {}
    if not profile.get("emit_album_photos") or not event or not tool_call_id:
        return {"ok": False, "error": "当前客户端还不能接收相册图片消息，请用新版 PWA。",
                "error_kind": "validation"}
    try:
        result.shared_media = ctx.store.record_album_share(
            ctx.session_tag, event["id"], tool_call_id, result.send_photo_id,
        )
        shared = ctx.meta.setdefault("album_shared_media", [])
        if not any(item["id"] == result.shared_media["id"] for item in shared):
            shared.append(result.shared_media)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "error_kind": "validation"}
    except Exception:
        from .runtime import logger
        logger.exception("[Album] 分享引用没有保存")
        return {"ok": False, "error": "这次没能把照片放进回复，请再试一次。", "error_kind": "exception"}
    return result


def retain_request_media(messages: list[dict], session_tag: str, store: Any) -> None:
    """Bind metadata to an exact user event; never accept client-forged shares."""
    from .chat_archive import parse_archive_event
    from .client_extra import expired_image_fingerprint
    from .context_layers import _is_image_content_block
    from .gateway_tools._album import _decode_image_block
    from .store import photo_fingerprint
    from .runtime import logger

    events = [(str(m.get("role")), event["id"]) for m in messages
              if (event := parse_archive_event(m.get("archive_event")))]
    for message in messages:
        raw_media = message.pop("media", None)
        incoming = clean_media(raw_media)
        event = parse_archive_event(message.get("archive_event"))
        if not event or message.get("role") != "user":
            continue
        content = message.get("content")
        blocks = [b for b in content if _is_image_content_block(b)] if isinstance(content, list) else []
        explicit_slots = isinstance(raw_media, list) and any(
            isinstance(item, dict) and "image_index" in item for item in raw_media
        )
        slots = {item.get("id"): item.get("image_index") for item in (raw_media or [])
                 if isinstance(item, dict)} if explicit_slots else {}
        metadata = [dict(item) for item in incoming] if explicit_slots else []
        for index, block in enumerate(blocks[:MAX_MEDIA_ITEMS]):
            candidates = [i for i, item in enumerate(incoming)
                          if type(slots.get(item["id"])) is int and slots[item["id"]] == index]
            target = candidates[0] if len(candidates) == 1 else None
            if explicit_slots and target is not None:
                item = metadata[target]
            elif not explicit_slots and index < len(incoming) and len(incoming) == len(blocks):
                item = dict(incoming[index])
                metadata.append(item)
            else:
                item = {"id": f"{event['id'][:120]}:image:{index}", "name": "照片", "mime": "image/jpeg"}
                metadata.append(item)
            decoded = _decode_image_block(block)
            digest = photo_fingerprint(decoded[0]) if decoded else expired_image_fingerprint(block)
            if decoded:
                item["mime"] = decoded[1]
            if digest and FINGERPRINT.fullmatch(digest):
                item["fingerprint"] = digest
            else:
                item.pop("fingerprint", None)
        # Old snapshots can carry metadata but no pixels. Keep the association,
        # not a newly invented image; IDs are immutable within an archive event.
        # Apply the same boundary before both in-memory use and persistence.
        # Malformed slots may add synthetic rows; a failed store/readback must
        # not leave a different, oversized media shape in the transcript.
        metadata = clean_media(metadata or incoming)
        if metadata:
            message["media"] = metadata
            try:
                store.retain_message_media(session_tag, event["id"], "user", metadata)
            except Exception:
                logger.warning("[Album] 附件引用保存失败", exc_info=True)
    try:
        retained = store.message_media_batch(session_tag, events)
    except Exception:
        logger.warning("[Album] 附件引用读取失败", exc_info=True)
        retained = {}
    for message in messages:
        event = parse_archive_event(message.get("archive_event"))
        if event:
            media = retained.get(f"{message.get('role')}:{event['id']}")
            if media:
                message["media"] = media


def media_context(messages: list[dict]) -> list[dict]:
    """Upstream-only text receipt. Do not mutate user text or stored snapshots."""
    result = []
    for message in messages:
        clean = dict(message)
        media = clean.pop("media", None)
        if message.get("role") == "assistant" and isinstance(media, list):
            references = [m for m in clean_media(media, album=True) if m.get("photo_id")]
            if references:
                receipt = "\n".join(
                    f"[已分享相册照片：{m.get('title') or '照片'}；照片引用：{m['photo_id']}]"
                    for m in references
                )
                content = clean.get("content") or ""
                if isinstance(content, list):
                    clean["content"] = [*content, {"type": "text", "text": receipt}]
                else:
                    clean["content"] = f"{content}\n{receipt}".lstrip("\n")
        result.append(clean)
    return result


def enrich_history_media(messages: list[dict], session_tag: str, store: Any) -> list[dict]:
    """Read-only recovery by event/reply ID, never by equal visible text."""
    from .chat_archive import parse_archive_event
    def identity(row: dict) -> str:
        event = parse_archive_event(row.get("archive_event"))
        if event:
            return event["id"]
        if row.get("role") == "assistant" and row.get("source_table") == "reply_version":
            return str(row.get("source_id") or "")
        return ""
    keys = [(str(m.get("role")), identity(m)) for m in messages]
    try:
        found = store.message_media_batch(session_tag, keys)
    except Exception:
        from .runtime import logger
        logger.warning("[Album] 历史图片引用暂时读不到，保留原消息", exc_info=True)
        return messages
    return [{**m, "media": found[key]} if key in found else m
            for m, (role, event_id) in zip(messages, keys)
            for key in [f"{role}:{event_id}"]]


def hydrate_album_views(
    messages: list[dict], store: Any, *, view_cache: dict[tuple[str, str], dict] | None = None,
) -> list[dict]:
    """Freeze each observation for this request, without changing its transcript.

    The tool loop owns the memo locally, never in serializable request metadata.
    Both success and failure belong to a call ID; a new open can retry without
    rewriting the old observation. A standalone/pending handoff resolves once.
    """
    resolved = view_cache if view_cache is not None else {}
    result = []
    for message in messages:
        photo_id = message.get(ALBUM_VIEW_KEY)
        if message.get("role") != "tool" or not isinstance(photo_id, str):
            result.append(message)
            continue
        clean = {k: v for k, v in message.items() if k not in {ALBUM_VIEW_KEY, TOOL_IMAGES_KEY}}
        key = (str(message.get("tool_call_id") or ""), photo_id)
        if key not in resolved:
            try:
                photo = store.album_photo_bytes(photo_id)
                if not photo or not photo["bytes"] or photo["mime"] not in PHOTO_MIME_TYPES:
                    raise ValueError("photo unavailable")
                resolved[key] = {TOOL_IMAGES_KEY: [{"type": "image_url", "image_url": {
                    "url": f"data:{photo['mime']};base64,{base64.b64encode(photo['bytes']).decode()}",
                }}]}
            except Exception:
                resolved[key] = {"content": json.dumps(
                    {"ok": False, "error": "本次没能读取照片，尚未看到画面。"}, ensure_ascii=False,
                )}
        # Adapters may annotate content blocks; never let one payload mutate
        # the memo used for an earlier prefix in the next tool round.
        clean.update(deepcopy(resolved[key]))
        result.append(clean)
    return result