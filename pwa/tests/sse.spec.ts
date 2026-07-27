import { describe, expect, it } from 'vitest'
import { appendThinking, appendToolEvent, parseSseFrame, pumpSseStream, toolEventKey } from '../src/stream/sse'
import { MAX_THINKING_BUDGET_TOKENS, thinkingRequestForEffort } from '../src/api/client'
import type { UiMessage } from '../src/types'

function assistant(): UiMessage {
  return { id: 'assistant-1', role: 'assistant', content: '', attachments: [], thinking: '', thinkingSegments: [], events: [], streaming: true }
}

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder()
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk))
      controller.close()
    },
  })
}

describe('thinking request contract', () => {
  it('uses a bounded explicit Thinking budget instead of adaptive effort for Max', () => {
    expect(thinkingRequestForEffort('max')).toEqual({
      thinking: { type: 'enabled', budget_tokens: MAX_THINKING_BUDGET_TOKENS },
    })
    expect(MAX_THINKING_BUDGET_TOKENS).toBe(32768)
    expect(thinkingRequestForEffort('high')).toEqual({ reasoning_effort: 'high' })
  })
})

describe('parseSseFrame', () => {
  it('appends content deltas and returns done only for [DONE]', () => {
    const message = assistant()
    expect(parseSseFrame('data: {"choices":[{"delta":{"content":"你好"}}]}', message)).toBe(false)
    expect(parseSseFrame('data: {"choices":[{"delta":{"content":"，世界"}}]}', message)).toBe(false)
    expect(message.content).toBe('你好，世界')
    expect(parseSseFrame('data: [DONE]', message)).toBe(true)
  })

  it('collects reasoning deltas as thinking segments anchored to the content offset', () => {
    const message = assistant()
    parseSseFrame('data: {"choices":[{"delta":{"reasoning_content":"先想想"}}]}', message)
    parseSseFrame('data: {"choices":[{"delta":{"content":"回答"}}]}', message)
    parseSseFrame('data: {"choices":[{"delta":{"reasoning":"再想想"}}]}', message)
    expect(message.thinking).toBe('先想想再想想')
    expect(message.thinkingSegments).toHaveLength(2)
    expect(message.thinkingSegments[0].textOffset).toBe(0)
    expect(message.thinkingSegments[1].textOffset).toBe(2)
  })

  it('routes shenyu tool events by event name or payload type', () => {
    const message = assistant()
    parseSseFrame('event: shenyu_tool\ndata: {"event":{"phase":"tool_start","tool_call_id":"t1","name":"shenyu_recall"}}', message)
    parseSseFrame('data: {"type":"shenyu.tool_event","event":{"phase":"tool_end","tool_call_id":"t1","name":"shenyu_recall","ok":true}}', message)
    expect(message.events).toHaveLength(2)
    expect(message.events[1].ok).toBe(true)
  })

  it('throws on error payloads and unparseable data frames, skips comment frames', () => {
    const message = assistant()
    expect(() => parseSseFrame('data: {"error":{"message":"上游断开"}}', message)).toThrow('上游断开')
    expect(() => parseSseFrame('data: not-json', message)).toThrow()
    expect(parseSseFrame(': keepalive comment', message)).toBe(false)
  })
})

describe('appendThinking and appendToolEvent ordering', () => {
  it('merges consecutive thinking at the same offset into one segment', () => {
    const message = assistant()
    appendThinking(message, 'a')
    appendThinking(message, 'b')
    expect(message.thinkingSegments).toHaveLength(1)
    expect(message.thinkingSegments[0].content).toBe('ab')
  })

  it('keeps tool_end at the offset and order of its tool_start', () => {
    const message = assistant()
    appendToolEvent(message, { phase: 'tool_start', tool_call_id: 't1', name: 'shenyu_recall' })
    message.content = '中间输出了一些文字'
    appendToolEvent(message, { phase: 'tool_end', tool_call_id: 't1', name: 'shenyu_recall', ok: true })
    const end = message.events.find((event) => event.phase === 'tool_end')
    const start = message.events.find((event) => event.phase === 'tool_start')
    expect(end?.text_offset).toBe(start?.text_offset)
    expect(end?.stream_order).toBe(start?.stream_order)
  })

  it('updates an existing event in place instead of duplicating it', () => {
    const message = assistant()
    appendToolEvent(message, { phase: 'tool_end', tool_call_id: 't1', name: 'shenyu_recall', ok: false })
    appendToolEvent(message, { phase: 'tool_end', tool_call_id: 't1', name: 'shenyu_recall', ok: true })
    expect(message.events).toHaveLength(1)
    expect(message.events[0].ok).toBe(true)
  })
})

describe('toolEventKey', () => {
  it('prefers tool_call_id and falls back to name and round', () => {
    expect(toolEventKey({ phase: 'tool_start', tool_call_id: 't1', name: 'a' })).toBe('t1')
    expect(toolEventKey({ phase: 'tool_start', tool_call_id: '', name: 'a', round: 2 })).toBe('a:2')
    expect(toolEventKey({ phase: 'tool_start', tool_call_id: '', name: 'a' })).toBe('a:0')
  })
})

describe('pumpSseStream', () => {
  it('reassembles frames split across chunk boundaries', async () => {
    const message = assistant()
    await pumpSseStream(streamOf([
      'data: {"choices":[{"delta":{"content":"He',
      'llo"}}]}\n\ndata: {"choices":[{"delta":{"content":" world"}}]}\n\n',
      'data: [DONE]\n\n',
    ]), (frame) => parseSseFrame(frame, message))
    expect(message.content).toBe('Hello world')
  })

  it('parses a trailing frame without a final blank line', async () => {
    const message = assistant()
    await pumpSseStream(streamOf(['data: {"choices":[{"delta":{"content":"tail"}}]}']), (frame) => parseSseFrame(frame, message))
    expect(message.content).toBe('tail')
  })

  it('notifies after each chunk for scroll syncing', async () => {
    let chunkEnds = 0
    await pumpSseStream(streamOf(['data: [DONE]\n\n']), () => true, () => { chunkEnds += 1 })
    expect(chunkEnds).toBeGreaterThan(0)
  })
})
