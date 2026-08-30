from __future__ import annotations

import base64
import binascii
from typing import Any, Optional

from shenyu_gateway.runtime import logger
from shenyu_gateway.store import DEFAULT_ALBUM_NAME, MAX_PHOTO_BYTES, photo_fingerprint

ALBUM_NOTES_TABLE = "shenyu_album_notes"

# 沈予自己的相册。他挑一张图存下来，配上自己的描述和心情；之后这张图在聊天里
# 过期了，他再看到的就是他当时写的那句话，而不是一句通用占位。
#
# 两处住所是刻意的：图片字节在本机卷的 SQLite（不占 Supabase 额度），备注文字
# 在 Supabase 并进 Recall（Recall 的适配器全部只读 Supabase）。卷万一出事，
# 丢的是图，他写的话还在。


def _image_blocks(content: Any) -> list[dict]:
    """一条消息里带 data URL 的图片块，按出现顺序。"""
    if not isinstance(content, list):
        return []
    blocks = []
    for item in content:
        if not isinstance(item, dict):
            continue
        image_url = item.get("image_url")
        url = image_url.get("url") if isinstance(image_url, dict) else image_url
        if isinstance(url, str) and url.startswith("data:"):
            blocks.append(item)
            continue
        source = item.get("source")
        if isinstance(source, dict) and str(source.get("media_type") or "").startswith("image/"):
            if source.get("data"):
                blocks.append(item)
    return blocks


def _decode_image_block(block: dict) -> Optional[tuple[bytes, str]]:
    """图片块 → (字节, mime)。认 OpenAI 的 data URL 和 Anthropic 的 source.data。"""
    image_url = block.get("image_url")
    url = image_url.get("url") if isinstance(image_url, dict) else image_url
    if isinstance(url, str) and url.startswith("data:"):
        header, _, payload = url.partition(",")
        if not payload:
            return None
        mime = header[5:].split(";")[0] or "image/jpeg"
        try:
            return base64.b64decode(payload, validate=False), mime
        except (binascii.Error, ValueError):
            return None
    source = block.get("source")
    if isinstance(source, dict) and source.get("data"):
        mime = str(source.get("media_type") or "image/jpeg")
        try:
            return base64.b64decode(str(source["data"]), validate=False), mime
        except (binascii.Error, ValueError):
            return None
    return None


def latest_turn_images(messages: Any) -> list[dict]:
    """最近一条带图 user 消息里的图片块。

    "存这张" 不需要在正文里放可引用的标记——模型此刻正看着图，最新那轮就是它。
    正文一个字都不能动，否则历史归一化结果改变、分支检测会误判成 branch 并重置
    prompt cache epoch（见 `context_window.py` § 分支检测）。
    """
    if not isinstance(messages, list):
        return []
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        blocks = _image_blocks(message.get("content"))
        if blocks:
            return blocks
    return []


class AlbumToolsMixin:
    async def album_save(
        self,
        note: Any = "",
        mood: Any = "",
        book: Any = DEFAULT_ALBUM_NAME,
        which: Any = 1,
        *,
        images: Optional[list[dict]] = None,
        session_tag: Any = "",
    ) -> dict:
        if not self.store:
            return {"ok": False, "error": "Local store is not configured.", "error_kind": "config"}
        blocks = images or []
        if not blocks:
            return {
                "ok": False,
                "error": "这一轮里没有看到图片。相册只收这次对话里出现的图。",
                "error_kind": "validation",
            }
        try:
            index = max(1, int(which or 1))
        except (TypeError, ValueError):
            index = 1
        if index > len(blocks):
            return {
                "ok": False,
                "error": f"这一轮只有 {len(blocks)} 张图，找不到第 {index} 张。",
                "error_kind": "validation",
            }
        decoded = _decode_image_block(blocks[index - 1])
        if not decoded:
            return {"ok": False, "error": "这张图读不出来。", "error_kind": "validation"}
        raw, mime = decoded
        if len(raw) > MAX_PHOTO_BYTES:
            return {
                "ok": False,
                "error": f"这张图比 {MAX_PHOTO_BYTES // (1024 * 1024)}MB 还大，先压小一点。",
                "error_kind": "validation",
            }

        try:
            saved = self.store.save_album_photo(
                raw=raw,
                mime=mime,
                note=note,
                mood=mood,
                book_name=book,
                fingerprint=photo_fingerprint(raw),
                source_session_tag=str(session_tag or ""),
            )
        except ValueError as exc:
            return {"ok": False, "error": str(exc), "error_kind": "validation"}
        except Exception as exc:
            logger.exception("[Album] 存图失败")
            return {"ok": False, "error": str(exc), "error_kind": "exception"}

        # 备注同步到 Supabase 并进 Recall。这一步失败不影响图已经存下来——
        # 图在本机是既成事实，只是这次它暂时不会被自动想起来。
        note_synced = False
        if (saved.get("note") or saved.get("mood")) and self.supabase:
            try:
                row = await self.supabase.insert(
                    ALBUM_NOTES_TABLE,
                    {
                        "photo_id": saved["id"],
                        "book_name": saved["book_name"],
                        "note": saved["note"],
                        "mood": saved["mood"],
                        "fingerprint": saved["fingerprint"],
                        "saved_at": saved["saved_at"],
                    },
                )
                if isinstance(row, dict) and row.get("id"):
                    self.store.set_album_photo_note_ref(saved["id"], str(row["id"]))
                    note_synced = True
                    try:
                        index_result = await self._recall_index().index_album_note_row(row)
                        if not index_result.get("ok"):
                            logger.warning("[Album] Recall indexing skipped: %s", index_result.get("error"))
                    except Exception as exc:
                        logger.warning("[Album] Recall indexing failed: %s", exc)
            except Exception as exc:
                logger.warning("[Album] 备注没能同步到 Supabase: %s", exc)

        return {
            "ok": True,
            "data": {
                "photo_id": saved["id"],
                "book": saved["book_name"],
                "note": saved["note"],
                "mood": saved["mood"],
                "byte_size": saved["byte_size"],
                "saved_at": saved["saved_at"],
                "note_searchable": note_synced,
            },
        }

    async def album_list(self, book: Any = "", limit: Any = 20) -> dict:
        if not self.store:
            return {"ok": False, "error": "Local store is not configured.", "error_kind": "config"}
        try:
            clamped = max(1, min(int(limit or 20), 100))
        except (TypeError, ValueError):
            clamped = 20
        try:
            book_name = str(book or "").strip()
            if not book_name:
                books = self.store.list_album_books()
                return {"ok": True, "count": len(books), "data": {"books": books}}
            photos = self.store.list_album_photos(book_name=book_name, limit=clamped)
            return {"ok": True, "count": len(photos), "data": {"book": book_name, "photos": photos}}
        except Exception as exc:
            logger.exception("[Album] 翻相册失败")
            return {"ok": False, "error": str(exc), "error_kind": "exception"}
