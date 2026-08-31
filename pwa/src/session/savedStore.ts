import type { ArchiveMessage } from '../api/archive'

// 收藏「只存本地」，复用 PWA 现有的 shenyu_pwa_* localStorage 约定，不建云端表、
// 不碰 IndexedDB。收藏是圆圆私人的、惰性的：不注入上下文、不进沈予的召回。
// 存整条快照（不只 id），因为档案里那条随时可能被软删或滑出窗口，收藏仍要能显示。

export const STORAGE_SAVED = 'shenyu_pwa_saved'
const SAVED_LIMIT = 500

export type SavedItem = {
  id: string
  role: 'user' | 'assistant'
  content: string
  event_at: string | null
  saved_at: string
}

export function loadSaved(): SavedItem[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(STORAGE_SAVED) || '[]')
    if (!Array.isArray(parsed)) return []
    return parsed
      .filter((row): row is SavedItem => !!row && typeof row === 'object' && typeof (row as SavedItem).id === 'string')
      .map((row) => ({
        id: row.id,
        role: row.role === 'user' ? 'user' : 'assistant',
        content: typeof row.content === 'string' ? row.content : '',
        event_at: typeof row.event_at === 'string' ? row.event_at : null,
        saved_at: typeof row.saved_at === 'string' ? row.saved_at : '',
      }))
  } catch {
    return []
  }
}

function persist(items: SavedItem[]): void {
  try {
    localStorage.setItem(STORAGE_SAVED, JSON.stringify(items.slice(0, SAVED_LIMIT)))
  } catch {
    // 配额满了就放弃这次写入；收藏是锦上添花，不该拖垮聊天。
  }
}

export function isSaved(id: string, items = loadSaved()): boolean {
  return items.some((row) => row.id === id)
}

// 新收藏排在最前，saved_at 记下收藏时刻。返回操作后的完整列表。
export function toggleSaved(message: ArchiveMessage): { items: SavedItem[]; saved: boolean } {
  const items = loadSaved()
  const existing = items.findIndex((row) => row.id === message.id)
  if (existing >= 0) {
    items.splice(existing, 1)
    persist(items)
    return { items, saved: false }
  }
  const next: SavedItem[] = [
    {
      id: message.id,
      role: message.role === 'user' ? 'user' : 'assistant',
      content: message.content,
      event_at: message.event_at,
      saved_at: new Date().toISOString(),
    },
    ...items,
  ]
  persist(next)
  return { items: next, saved: true }
}

export function removeSaved(id: string): SavedItem[] {
  const items = loadSaved().filter((row) => row.id !== id)
  persist(items)
  return items
}
