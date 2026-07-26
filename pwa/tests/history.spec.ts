import { describe, expect, it } from 'vitest'
import {
  coldStartHistoryRows,
  dedupeUiMessagesForRecovery,
  hasExactDuplicateRows,
  sessionHistoryRows,
  sessionMessageContent,
  sessionTagFromLocation,
} from '../src/session/history'
import type { UiMessage } from '../src/types'

function uiMessage(role: 'user' | 'assistant', content: string): UiMessage {
  return { id: `id-${role}-${content}`, role, content, attachments: [], thinking: '', thinkingSegments: [], events: [] }
}

describe('sessionTagFromLocation', () => {
  it('prefers session_tag over legacy parameter names', () => {
    expect(sessionTagFromLocation('?session_tag=a&session=b&thread=c')).toBe('a')
    expect(sessionTagFromLocation('?session=b&thread=c')).toBe('b')
    expect(sessionTagFromLocation('?thread=c')).toBe('c')
  })

  it('returns empty string without a tag and trims whitespace', () => {
    expect(sessionTagFromLocation('')).toBe('')
    expect(sessionTagFromLocation('?session_tag=%20padded%20')).toBe('padded')
  })
})

describe('sessionMessageContent', () => {
  it('passes strings through and stringifies scalars', () => {
    expect(sessionMessageContent('hello')).toBe('hello')
    expect(sessionMessageContent(null)).toBe('')
    expect(sessionMessageContent(undefined)).toBe('')
    expect(sessionMessageContent(42)).toBe('42')
  })

  it('joins only text blocks from block arrays', () => {
    expect(sessionMessageContent([
      { type: 'text', text: '你好' },
      { type: 'image_url', image_url: { url: 'data:...' } },
      'raw',
      { type: 'text', text: '世界' },
    ])).toBe('你好raw世界')
  })
})

describe('sessionHistoryRows source priority', () => {
  const snapshotRows = [{ role: 'user', content: 'from snapshot' }]
  const legacyRows = [{ role: 'user', content: 'from legacy snapshot' }]
  const inspectionRows = [{ role: 'user', content: 'from inspection stream' }]

  it('prefers context_snapshots over everything else', () => {
    const payload = {
      context_snapshots: [{ messages: snapshotRows }],
      request_context_snapshots: [{ messages: legacyRows }],
      recent_messages: inspectionRows,
    }
    expect(sessionHistoryRows(payload)).toEqual(snapshotRows)
  })

  it('falls back to request_context_snapshots when context_snapshots is unusable', () => {
    const payload = {
      context_snapshots: [],
      request_context_snapshots: [{ messages: legacyRows }],
      recent_messages: inspectionRows,
    }
    expect(sessionHistoryRows(payload)).toEqual(legacyRows)
  })

  it('falls back to recent_messages only when no snapshot has rows', () => {
    const payload = {
      context_snapshots: [{ messages: 'not-an-array' }],
      recent_messages: inspectionRows,
    }
    expect(sessionHistoryRows(payload)).toEqual(inspectionRows)
  })

  it('returns empty for an empty payload and drops non-object rows', () => {
    expect(sessionHistoryRows({})).toEqual([])
    expect(sessionHistoryRows({ recent_messages: [null, 'text', ...inspectionRows] })).toEqual(inspectionRows)
  })

  it('only reads the newest snapshot, never older ones', () => {
    const payload = {
      context_snapshots: [{ messages: snapshotRows }, { messages: legacyRows }],
    }
    expect(sessionHistoryRows(payload)).toEqual(snapshotRows)
  })
})

describe('coldStartHistoryRows', () => {
  const cleanRows = [
    { role: 'user', content: 'question' },
    { role: 'assistant', content: 'answer' },
    { role: 'system', content: 'must be dropped' },
  ]

  it('reads the first active snapshot and matches the target session tag', () => {
    const payload = {
      cold_start_snapshots: [
        { active: false, sources: [{ session_tag: 'other', messages: [{ role: 'user', content: 'inactive' }] }] },
        {
          active: true,
          sources: [
            { session_tag: 'other', messages: [{ role: 'user', content: 'wrong tag' }] },
            { session_tag: 'target', messages: cleanRows },
          ],
        },
      ],
    }
    expect(coldStartHistoryRows(payload, 'target')).toEqual(cleanRows.slice(0, 2))
  })

  it('falls back to the first source when no tag matches', () => {
    const payload = {
      cold_start_snapshots: [
        { sources: [{ session_tag: 'other', messages: [{ role: 'user', content: 'first source' }] }] },
      ],
    }
    expect(coldStartHistoryRows(payload, 'missing')).toEqual([{ role: 'user', content: 'first source' }])
  })

  it('returns empty when snapshots are missing or malformed', () => {
    expect(coldStartHistoryRows({}, 'target')).toEqual([])
    expect(coldStartHistoryRows({ cold_start_snapshots: 'nope' }, 'target')).toEqual([])
    expect(coldStartHistoryRows({ cold_start_snapshots: [{ sources: [] }] }, 'target')).toEqual([])
  })
})

describe('duplicate history detection and recovery', () => {
  it('detects exact duplicate role/content pairs', () => {
    expect(hasExactDuplicateRows([
      { role: 'user', content: 'same' },
      { role: 'assistant', content: 'reply' },
      { role: 'user', content: 'same' },
    ])).toBe(true)
  })

  it('does not flag the same content under different roles or non-chat rows', () => {
    expect(hasExactDuplicateRows([
      { role: 'user', content: 'same' },
      { role: 'assistant', content: 'same' },
      { role: 'system', content: 'x' },
      { role: 'system', content: 'x' },
    ])).toBe(false)
  })

  it('handles block-array content when comparing rows', () => {
    expect(hasExactDuplicateRows([
      { role: 'user', content: [{ type: 'text', text: 'same' }] },
      { role: 'user', content: 'same' },
    ])).toBe(true)
  })

  it('keeps the first occurrence and preserves newer distinct messages on recovery', () => {
    const deduped = dedupeUiMessagesForRecovery([
      uiMessage('user', 'a'),
      uiMessage('assistant', 'b'),
      uiMessage('user', 'a'),
      uiMessage('user', 'new message'),
    ])
    expect(deduped.map((message) => message.content)).toEqual(['a', 'b', 'new message'])
  })
})
