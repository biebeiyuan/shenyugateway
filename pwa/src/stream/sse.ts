import type { ToolEvent } from '../toolLanguage'
import type { ResponseMeta, UiMessage } from '../types'
import { createId, textLength } from '../utils'

// SSE protocol parsing for /v1/chat/completions streams. The gateway sends
// standard OpenAI deltas plus its private `shenyu.tool_event` frames; both are
// folded into the streaming assistant message here. Thinking segments and tool
// events record the content offset and stream order at arrival time so the
// timeline module can interleave them with the streamed text later.

export function toolEventKey(event: ToolEvent): string {
  return event.tool_call_id || `${event.name}:${event.round || 0}`
}

export function nextProcessOrder(message: UiMessage): number {
  const thoughtOrder = message.thinkingSegments.reduce((max, item) => Math.max(max, item.streamOrder), -1)
  const toolOrder = message.events.reduce((max, item) => Math.max(max, item.stream_order || -1), -1)
  return Math.max(thoughtOrder, toolOrder) + 1
}

export function appendToolEvent(message: UiMessage, event: ToolEvent) {
  const key = `${event.phase}:${event.tool_call_id || event.name}`
  const existingIndex = message.events.findIndex((item) => `${item.phase}:${item.tool_call_id || item.name}` === key)
  const existing = existingIndex >= 0 ? message.events[existingIndex] : undefined
  const relatedStart = message.events.find((item) => item.phase === 'tool_start' && toolEventKey(item) === toolEventKey(event))
  const stored = {
    ...event,
    text_offset: existing?.text_offset ?? relatedStart?.text_offset ?? textLength(message.content),
    stream_order: existing?.stream_order ?? relatedStart?.stream_order ?? nextProcessOrder(message),
  }
  if (existingIndex >= 0) message.events.splice(existingIndex, 1, stored)
  else message.events.push(stored)
}

export function appendThinking(message: UiMessage, delta: string) {
  if (!delta) return
  message.thinking += delta
  const textOffset = textLength(message.content)
  const last = message.thinkingSegments[message.thinkingSegments.length - 1]
  if (last && last.textOffset === textOffset) {
    last.content += delta
    return
  }
  message.thinkingSegments.push({
    id: createId('thinking'),
    content: delta,
    textOffset,
    streamOrder: nextProcessOrder(message),
  })
}

// Returns true when the stream signalled completion ([DONE]).
export function parseSseFrame(frame: string, assistant: UiMessage): boolean {
  let eventName = ''
  const dataLines: string[] = []
  for (const line of frame.split(/\r?\n/)) {
    if (line.startsWith('event:')) eventName = line.slice(6).trim()
    if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
  }
  const data = dataLines.join('\n')
  if (!data) return false
  if (data === '[DONE]') return true
  try {
    const payload = JSON.parse(data)
    if (eventName === 'shenyu_meta' || payload.type === 'shenyu.response_meta') {
      const meta = payload.meta
      if (meta && typeof meta === 'object' && !Array.isArray(meta)) {
        assistant.responseMeta = { ...(meta as ResponseMeta) }
      }
      return false
    }
    if (eventName === 'shenyu_tool' || payload.type === 'shenyu.tool_event') {
      const event = payload.event as ToolEvent
      if (event) appendToolEvent(assistant, event)
      return false
    }
    if (payload.error) throw new Error(String(payload.error.message || payload.error))
    const delta = payload.choices?.[0]?.delta || {}
    if (typeof delta.content === 'string') assistant.content += delta.content
    if (typeof delta.reasoning_content === 'string') appendThinking(assistant, delta.reasoning_content)
    if (typeof delta.reasoning === 'string') appendThinking(assistant, delta.reasoning)
    const message = payload.choices?.[0]?.message
    if (message && typeof message.content === 'string') assistant.content += message.content
  } catch (error) {
    if (error instanceof Error && error.message) throw error
  }
  return false
}

// Reads a streaming response body, splitting on blank lines into SSE frames.
// `onFrame` returns true to mark the stream done ([DONE]); remaining frames of
// the current chunk are still delivered, matching upstream flush behavior.
export async function pumpSseStream(
  body: ReadableStream<Uint8Array>,
  onFrame: (frame: string) => boolean,
  onChunkEnd?: () => void,
): Promise<void> {
  const reader = body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let done = false
  while (!done) {
    const chunk = await reader.read()
    buffer += decoder.decode(chunk.value || new Uint8Array(), { stream: !chunk.done })
    const frames = buffer.split(/\r?\n\r?\n/)
    buffer = frames.pop() || ''
    for (const frame of frames) {
      if (onFrame(frame)) done = true
    }
    if (chunk.done) {
      if (buffer.trim()) onFrame(buffer)
      done = true
    }
    onChunkEnd?.()
  }
}
