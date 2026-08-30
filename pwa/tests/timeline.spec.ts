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
  // 2026-08-30 恢复交错渲染：过程条插回正文中间，读起来是「写一段 → 做了点事 →
  // 再写一段」。7 月删掉它的原因是按字符偏移切会切坏 Markdown；现在切点由
  // marked.lexer 给，只落在块边界上。
  it('interleaves a process strip between two blocks', () => {
    const message = assistant('前半段\n\n后半段')
    message.thinkingSegments = [{ id: 's', content: 'mid thought', textOffset: 5, streamOrder: 0 }]
    const parts = assistantParts(message)
    expect(parts.map((part) => part.kind)).toEqual(['content', 'process', 'content'])
    // 正文按块产出，拼回来仍等于原文——一个字都不能丢。
    const rejoined = parts.filter((p) => p.kind === 'content').map((p: any) => p.content).join('')
    expect(rejoined).toBe(message.content)
  })

  it('snaps a mid-block offset to after that block, never inside it', () => {
    const message = assistant('第一段。\n\n```python\ndef a():\n\n    pass\n```\n\n最后。')
    // 偏移落在代码块内部
    message.thinkingSegments = [{ id: 's', content: 'x', textOffset: 12, streamOrder: 0 }]
    const parts = assistantParts(message)
    const contents = parts.filter((p) => p.kind === 'content').map((p: any) => p.content)
    expect(contents.join('')).toBe(message.content)
    // 代码块所在的那一块必须完整（首尾都有 ```），否则渲染会坏
    const codeBlock = contents.find((c) => c.includes('```python'))
    expect(codeBlock?.trimEnd().endsWith('```')).toBe(true)
    // 过程条落在代码块之后，而不是把它切开
    const processIndex = parts.findIndex((p) => p.kind === 'process')
    const codeIndex = contents.findIndex((c) => c.includes('```python'))
    expect(processIndex).toBeGreaterThan(codeIndex)
  })

  it('always yields at least one content part for a plain message', () => {
    const parts = assistantParts(assistant(''))
    expect(parts).toHaveLength(1)
    expect(parts[0].kind).toBe('content')
  })

  it('keeps a still-empty reply renderable while tools run', () => {
    const message = assistant('')
    message.thinkingSegments = [{ id: 's', content: 'thinking first', textOffset: 0, streamOrder: 0 }]
    const parts = assistantParts(message)
    expect(parts.map((part) => part.kind)).toEqual(['process', 'content'])
  })

  it('keeps unicode content whole while retaining code-point process offsets', () => {
    const message = assistant('😀😀text')
    message.thinkingSegments = [{ id: 's', content: 'after emoji', textOffset: 2, streamOrder: 0 }]
    const parts = assistantParts(message)
    // 单块正文：偏移落在块内 → 吸附到块之后，所以正文在前、过程条在后。
    const contents = parts.filter((p) => p.kind === 'content').map((p: any) => p.content)
    expect(contents.join('')).toBe('😀😀text')
    const strip = parts.find((part) => part.kind === 'process')
    expect(strip?.kind === 'process' && strip.group.textOffset).toBe(2)
  })

  it('keeps Markdown delimiters paired when thinking arrives inside the source', () => {
    const message = assistant('**是“克服社交”，是找表演含量低的活法**：远程、小团队。')
    message.thinkingSegments = [{ id: 'late', content: 'late thought', textOffset: 8, streamOrder: 0 }]

    const parts = assistantParts(message)
    const contents = parts.filter((part) => part.kind === 'content').map((p: any) => p.content)
    // 这一段只有一个块，绝不能被切开——切开就会渲染成裸的 **
    expect(contents).toHaveLength(1)
    expect(contents[0]).toBe(message.content)
    expect(renderMarkdown(contents[0])).toContain(
      '<strong>是“克服社交”，是找表演含量低的活法</strong>：远程、小团队。',
    )
  })

  it('never drops a process strip whose offset is out of range', () => {
    const message = assistant('短正文')
    message.thinkingSegments = [{ id: 'far', content: 'beyond', textOffset: 9999, streamOrder: 0 }]
    const parts = assistantParts(message)
    expect(parts.some((part) => part.kind === 'process')).toBe(true)
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
