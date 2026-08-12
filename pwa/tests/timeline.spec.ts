import { describe, expect, it } from 'vitest'
import { renderMarkdown } from '../src/markdown'
import { assistantParts, processGroups, processTimeline, traceRows } from '../src/stream/timeline'
import type { UiMessage } from '../src/types'

function assistant(content: string): UiMessage {
  return { id: 'assistant-1', role: 'assistant', content, echo: '', echoSegments: [], attachments: [], thinking: '', thinkingSegments: [], events: [] }
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
  it('places process strips before one intact content part', () => {
    const message = assistant('前半段\n\n后半段')
    message.thinkingSegments = [{ id: 's', content: 'mid thought', textOffset: 5, streamOrder: 0 }]
    const parts = assistantParts(message)
    expect(parts.map((part) => part.kind)).toEqual(['process', 'content'])
    expect(parts[1].kind === 'content' && parts[1].content).toBe(message.content)
  })

  it('always yields at least one content part for a plain message', () => {
    const parts = assistantParts(assistant(''))
    expect(parts).toHaveLength(1)
    expect(parts[0].kind).toBe('content')
  })

  it('keeps unicode content whole while retaining code-point process offsets', () => {
    const message = assistant('😀😀text')
    message.thinkingSegments = [{ id: 's', content: 'after emoji', textOffset: 2, streamOrder: 0 }]
    const parts = assistantParts(message)
    expect(parts[0].kind === 'process' && parts[0].group.textOffset).toBe(2)
    expect(parts[1].kind === 'content' && parts[1].content).toBe('😀😀text')
  })

  it('keeps Markdown delimiters paired when thinking arrives inside the source', () => {
    const message = assistant('**是“克服社交”，是找表演含量低的活法**：远程、小团队。')
    message.thinkingSegments = [{ id: 'late', content: 'late thought', textOffset: 8, streamOrder: 0 }]

    const parts = assistantParts(message)
    const content = parts.find((part) => part.kind === 'content')
    expect(parts[0].kind).toBe('process')
    expect(content?.kind === 'content' && content.content).toBe(message.content)
    expect(renderMarkdown(content?.kind === 'content' ? content.content : '')).toContain(
      '<strong>是“克服社交”，是找表演含量低的活法</strong>：远程、小团队。',
    )
  })
})

describe('processTimeline', () => {
  it('interleaves echo, thinking and tools by stream order', () => {
    const message = assistant('abc')
    message.echo = 'first'
    message.echoSegments = [{ id: 'e1', content: 'first', textOffset: 0, streamOrder: 0 }]
    message.thinkingSegments = [{ id: 's1', content: 'second', textOffset: 0, streamOrder: 1 }]
    message.events = [{ phase: 'tool_start', tool_call_id: 't1', name: 'shenyu_recall', text_offset: 0, stream_order: 2 }]
    const [group] = processGroups(message)
    const timeline = processTimeline(group)
    expect(timeline.map((item) => item.kind)).toEqual(['echo', 'thinking', 'tool'])
  })

  it('returns empty for a missing group', () => {
    expect(processTimeline(undefined)).toEqual([])
  })
})
