import { describe, expect, it } from 'vitest'
import { SSE_STALL_ERROR, appendEcho, appendThinking, appendToolEvent, parseSseFrame, pumpSseStream, toolEventKey } from '../src/stream/sse'
import type { UiMessage } from '../src/types'

function assistant(): UiMessage {
  return { id: 'assistant-1', role: 'assistant', content: '', echo: '', echoSegments: [], attachments: [], thinking: '', thinkingSegments: [], events: [], streaming: true }
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

  it('collects separate echo passages around a tool in process order', () => {
    const message = assistant()
    parseSseFrame('event: shenyu_echo\ndata: {"type":"shenyu.echo_delta","echo":"先看看"}', message)
    parseSseFrame('event: shenyu_tool\ndata: {"event":{"phase":"tool_start","tool_call_id":"t1","name":"shenyu_recall"}}', message)
    parseSseFrame('event: shenyu_echo\ndata: {"type":"shenyu.echo_delta","echo":"看见了"}', message)
    expect(message.echo).toBe('先看看看见了')
    expect(message.echoSegments.map((item) => item.content)).toEqual(['先看看', '看见了'])
    expect(message.echoSegments.map((item) => item.streamOrder)).toEqual([0, 2])
  })

  it('maps content-free response metadata onto the assistant reply', () => {
    const message = assistant()
    parseSseFrame('event: shenyu_meta\ndata: {"type":"shenyu.response_meta","meta":{"context_rounds":12,"context_trim_in_rounds":17,"cache_read_percent":68.4,"tool_rounds":2,"first_tool_round_cache_hit":true,"heartbeat_captured":true}}', message)
    expect(message.responseMeta).toEqual({
      context_rounds: 12,
      context_trim_in_rounds: 17,
      cache_read_percent: 68.4,
      tool_rounds: 2,
      first_tool_round_cache_hit: true,
      heartbeat_captured: true,
    })
  })

  it('throws on error payloads and unparseable data frames, skips comment frames', () => {
    const message = assistant()
    expect(() => parseSseFrame('data: {"error":{"message":"上游断开"}}', message)).toThrow('上游断开')
    expect(() => parseSseFrame('data: not-json', message)).toThrow()
    expect(parseSseFrame(': keepalive comment', message)).toBe(false)
  })
})

describe('appendThinking and appendToolEvent ordering', () => {
  it('merges consecutive echo deltas until another process item arrives', () => {
    const message = assistant()
    appendEcho(message, 'a')
    appendEcho(message, 'b')
    appendToolEvent(message, { phase: 'tool_start', tool_call_id: 't1', name: 'shenyu_recall' })
    appendEcho(message, 'c')
    expect(message.echoSegments.map((item) => item.content)).toEqual(['ab', 'c'])
  })
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

  it('reports sawDone=true when the stream closes with [DONE]', async () => {
    const message = assistant()
    const { sawDone } = await pumpSseStream(streamOf([
      'data: {"choices":[{"delta":{"content":"完整"}}]}\n\n',
      'data: [DONE]\n\n',
    ]), (frame) => parseSseFrame(frame, message))
    expect(sawDone).toBe(true)
    expect(message.content).toBe('完整')
  })

  it('reports sawDone=false on silent EOF without [DONE]', async () => {
    const message = assistant()
    const { sawDone } = await pumpSseStream(streamOf([
      'data: {"choices":[{"delta":{"content":"半截"}}]}\n\n',
    ]), (frame) => parseSseFrame(frame, message))
    expect(sawDone).toBe(false)
    expect(message.content).toBe('半截')
  })

  it('recognizes [DONE] arriving as the trailing frame without a blank line', async () => {
    const { sawDone } = await pumpSseStream(streamOf(['data: [DONE]']), (frame) => frame.includes('[DONE]'))
    expect(sawDone).toBe(true)
  })

  it('throws the stall error when no chunk arrives within the watchdog window', async () => {
    // A stream that produces one chunk then hangs forever, like a dead NAT socket.
    const encoder = new TextEncoder()
    const hangingStream = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode('data: {"choices":[{"delta":{"content":"开头"}}]}\n\n'))
      },
    })
    const message = assistant()
    await expect(
      pumpSseStream(hangingStream, (frame) => parseSseFrame(frame, message), undefined, 50),
    ).rejects.toThrow(SSE_STALL_ERROR)
    expect(message.content).toBe('开头')
  })

  it('does not stall a healthy stream slower than one chunk per tick', async () => {
    const encoder = new TextEncoder()
    const slowStream = new ReadableStream<Uint8Array>({
      async start(controller) {
        await new Promise((resolve) => setTimeout(resolve, 20))
        controller.enqueue(encoder.encode('data: [DONE]\n\n'))
        controller.close()
      },
    })
    const { sawDone } = await pumpSseStream(slowStream, (frame) => frame.includes('[DONE]'), undefined, 5_000)
    expect(sawDone).toBe(true)
  })
})
