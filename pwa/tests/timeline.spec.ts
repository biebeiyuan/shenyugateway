import { describe, expect, it } from 'vitest'
import { assistantParts, processGroups, processTimeline, traceRows } from '../src/stream/timeline'
import type { UiMessage } from '../src/types'

function assistant(content: string): UiMessage {
  return { id: 'assistant-1', role: 'assistant', content, attachments: [], thinking: '', thinkingSegments: [], events: [] }
}

describe('traceRows', () => {
  it('merges tool_end into its tool_start row', () => {
    const message = assistant('')
    message.events = [
      { phase: 'tool_start', tool_call_id: 't1', name: 'shenyu_recall' },
      { phase: 'tool_end', tool_call_id: 't1', name: 'shenyu_recall', ok: true, output: 'found it' },
    ]
    const rows = traceRows(message)
    expect(rows).toHaveLength(1)
    expect(rows[0].ok).toBe(true)
    expect(rows[0].output).toBe('found it')
  })

  it('keeps an orphan tool_end visible', () => {
    const message = assistant('')
    message.events = [{ phase: 'tool_end', tool_call_id: 't9', name: 'shenyu_recall', ok: false }]
    expect(traceRows(message)).toHaveLength(1)
  })
})

describe('processGroups', () => {
  it('groups thinking and tools by their content offset in order', () => {
    const message = assistant('前半段\n\n后半段')
    message.thinkingSegments = [
      { id: 'later', content: 'later thought', textOffset: 5, streamOrder: 2 },
      { id: 'early', content: 'early thought', textOffset: 0, streamOrder: 0 },
    ]
    message.events = [{ phase: 'tool_start', tool_call_id: 't1', name: 'shenyu_recall', text_offset: 5, stream_order: 1 }]
    const groups = processGroups(message)
    expect(groups.map((group) => group.textOffset)).toEqual([0, 5])
    expect(groups[1].thinking[0].id).toBe('later')
    expect(groups[1].tools).toHaveLength(1)
  })

  it('keeps a process split at its original content offset', () => {
    const message = assistant('**一整段粗体内容**')
    message.thinkingSegments = [{ id: 's', content: 'thought', textOffset: 3, streamOrder: 0 }]
    expect(processGroups(message)[0].textOffset).toBe(3)
  })

  it('clamps offsets beyond the content length', () => {
    const message = assistant('ab')
    message.thinkingSegments = [{ id: 's', content: 'x', textOffset: 99, streamOrder: 0 }]
    expect(processGroups(message)[0].textOffset).toBe(2)
  })

  it('falls back to whole-message thinking for restored history', () => {
    const message = assistant('answer')
    message.thinking = 'restored thought'
    const groups = processGroups(message)
    expect(groups).toHaveLength(1)
    expect(groups[0].thinking[0].content).toBe('restored thought')
  })
})

describe('assistantParts', () => {
  it('splices process strips between text segments at their offsets', () => {
    const message = assistant('前半段\n\n后半段')
    message.thinkingSegments = [{ id: 's', content: 'mid thought', textOffset: 5, streamOrder: 0 }]
    const parts = assistantParts(message)
    expect(parts.map((part) => part.kind)).toEqual(['content', 'process', 'content'])
    expect(parts[0].kind === 'content' && parts[0].content).toBe('前半段\n\n')
    expect(parts[2].kind === 'content' && parts[2].content).toBe('后半段')
  })

  it('always yields at least one content part for a plain message', () => {
    const parts = assistantParts(assistant(''))
    expect(parts).toHaveLength(1)
    expect(parts[0].kind).toBe('content')
  })

  it('counts offsets in code points so emoji do not split incorrectly', () => {
    const message = assistant('😀😀text')
    message.thinkingSegments = [{ id: 's', content: 'after emoji', textOffset: 2, streamOrder: 0 }]
    const parts = assistantParts(message)
    expect(parts[0].kind === 'content' && parts[0].content).toBe('😀😀')
    expect(parts[2].kind === 'content' && parts[2].content).toBe('text')
  })
})

describe('processTimeline', () => {
  it('interleaves thinking and tools by stream order', () => {
    const message = assistant('abc')
    message.thinkingSegments = [{ id: 's1', content: 'first', textOffset: 0, streamOrder: 0 }]
    message.events = [{ phase: 'tool_start', tool_call_id: 't1', name: 'shenyu_recall', text_offset: 0, stream_order: 1 }]
    const [group] = processGroups(message)
    const timeline = processTimeline(group)
    expect(timeline.map((item) => item.kind)).toEqual(['thinking', 'tool'])
  })

  it('returns empty for a missing group', () => {
    expect(processTimeline(undefined)).toEqual([])
  })
})
