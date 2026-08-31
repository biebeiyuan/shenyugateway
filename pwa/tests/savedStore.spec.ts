import { beforeEach, describe, expect, it } from 'vitest'
import { STORAGE_SAVED, isSaved, loadSaved, removeSaved, toggleSaved } from '../src/session/savedStore'
import type { ArchiveMessage } from '../src/api/archive'

function msg(id: string, content = 'hello', role: 'user' | 'assistant' = 'assistant'): ArchiveMessage {
  return { id, session_tag: 'default', role, content, event_at: '2026-08-19T01:13:00+00:00', archived_at: '2026-08-19T01:13:00+00:00' }
}

beforeEach(() => {
  localStorage.clear()
})

describe('local saved store', () => {
  it('toggles a message in and out, newest first', () => {
    const first = toggleSaved(msg('a', '第一条'))
    expect(first.saved).toBe(true)
    expect(isSaved('a')).toBe(true)

    toggleSaved(msg('b', '第二条'))
    expect(loadSaved().map((r) => r.id)).toEqual(['b', 'a'])

    const off = toggleSaved(msg('a', '第一条'))
    expect(off.saved).toBe(false)
    expect(isSaved('a')).toBe(false)
    expect(loadSaved().map((r) => r.id)).toEqual(['b'])
  })

  it('stores a full snapshot so a soft-deleted archive row still shows', () => {
    toggleSaved(msg('a', '窗台擦干净等你回来'))
    const [row] = loadSaved()
    expect(row.content).toBe('窗台擦干净等你回来')
    expect(row.role).toBe('assistant')
    expect(row.event_at).toBe('2026-08-19T01:13:00+00:00')
    expect(typeof row.saved_at).toBe('string')
  })

  it('removeSaved deletes by id', () => {
    toggleSaved(msg('a'))
    toggleSaved(msg('b'))
    const left = removeSaved('a')
    expect(left.map((r) => r.id)).toEqual(['b'])
  })

  it('survives corrupt storage without throwing', () => {
    localStorage.setItem(STORAGE_SAVED, 'not json')
    expect(loadSaved()).toEqual([])
    localStorage.setItem(STORAGE_SAVED, JSON.stringify([{ nope: true }, { id: 'ok', role: 'user', content: 'x' }]))
    expect(loadSaved().map((r) => r.id)).toEqual(['ok'])
  })
})
