import { describe, expect, it } from 'vitest'
import { hydrateToolEvents } from '../src/session/toolHydration'
import { traceRows } from '../src/stream/timeline'
import type { UiMessage } from '../src/types'

function uiMessage(role: 'user' | 'assistant', content: string): UiMessage {
  return { id: `id-${role}-${content}`, role, content, attachments: [], thinking: '', thinkingSegments: [], events: [] }
}

const toolRow = (id: number, name: string, args: unknown, result: unknown) => ({
  id,
  role: 'tool',
  tool_name: name,
  tool_args_json: JSON.stringify(args),
  content: typeof result === 'string' ? result : JSON.stringify(result),
  tool_result_summary: '',
})

describe('hydrateToolEvents', () => {
  it('attaches consecutive tool rows to the assistant row that follows them', () => {
    const messages = [uiMessage('user', '帮我查查'), uiMessage('assistant', '查到了。')]
    const recent = [
      { id: 1, role: 'user', content: '帮我查查' },
      toolRow(2, 'shenyu_recall', { query: 'x' }, { ok: true, notes: ['a'] }),
      { id: 3, role: 'assistant', content: '查到了。' },
    ]
    expect(hydrateToolEvents(messages, recent)).toBe(1)
    const rows = traceRows(messages[1])
    expect(rows).toHaveLength(1)
    expect(rows[0].name).toBe('shenyu_recall')
    expect(rows[0].input).toEqual({ query: 'x' })
    expect(rows[0].ok).toBe(true)
    expect(rows[0].output).toContain('notes')
    expect(rows[0].tool_call_id).toBe('hydrated-2')
  })

  it('matches from the tail so retry-duplicated assistant rows do not steal tools', () => {
    const messages = [uiMessage('assistant', '同一句话'), uiMessage('assistant', '同一句话')]
    const recent = [
      { role: 'assistant', content: '同一句话' },
      toolRow(9, 'shenyu_star', {}, { ok: true }),
      { role: 'assistant', content: '同一句话' },
    ]
    hydrateToolEvents(messages, recent)
    // 最后一条 UiMessage 先消费最后一个 assistant 行（带工具组）。
    expect(messages[1].events).toHaveLength(2)
    expect(messages[0].events).toHaveLength(0)
  })

  it('normalizes whitespace when matching and infers failure from the result JSON', () => {
    const messages = [uiMessage('assistant', '  有点  受阻。 ')]
    const recent = [
      toolRow(4, 'shenyu_recall', { q: 1 }, { error: 'not found' }),
      { role: 'assistant', content: '有点 受阻。' },
    ]
    hydrateToolEvents(messages, recent)
    const [row] = traceRows(messages[0])
    expect(row.ok).toBe(false)
  })

  it('breaks tool continuity at user rows and never throws on garbage', () => {
    const messages = [uiMessage('assistant', '答复')]
    const recent = [
      toolRow(5, 'shenyu_recall', {}, { ok: true }),
      { role: 'user', content: '打断' },
      { role: 'assistant', content: '答复' },
      null,
      'garbage',
    ]
    expect(() => hydrateToolEvents(messages, recent)).not.toThrow()
    expect(messages[0].events).toEqual([])
    expect(hydrateToolEvents(messages, undefined)).toBe(0)
  })

  it('falls back to the summary and defaults ok=true when the result is not JSON', () => {
    const messages = [uiMessage('assistant', '好了')]
    const recent = [
      { id: 7, role: 'tool', tool_name: 'shenyu_note', tool_args_json: 'not json', content: '', tool_result_summary: '写好了' },
      { role: 'assistant', content: '好了' },
    ]
    hydrateToolEvents(messages, recent)
    const [row] = traceRows(messages[0])
    expect(row.ok).toBe(true)
    expect(row.output).toBe('写好了')
    expect(row.input).toBe('not json')
  })
})
