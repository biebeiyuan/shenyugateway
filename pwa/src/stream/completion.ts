import type { ToolEvent } from '../toolLanguage'
import type { ResponseMeta, UiMessage } from '../types'
import { textLength } from '../utils'
import { appendEcho, appendThinking, appendToolEvent } from './sse'

function completionText(value: unknown): string {
  if (typeof value === 'string') return value
  if (!Array.isArray(value)) return ''
  return value.map((block) => {
    if (!block || typeof block !== 'object') return ''
    const candidate = block as Record<string, unknown>
    return typeof candidate.text === 'string'
      ? candidate.text
      : typeof candidate.content === 'string'
        ? candidate.content
        : ''
  }).join('')
}

function completionToolEvents(payload: Record<string, unknown>): ToolEvent[] {
  const shenyu = payload.shenyu
  if (!shenyu || typeof shenyu !== 'object' || Array.isArray(shenyu)) return []
  const events = (shenyu as Record<string, unknown>).tool_events
  if (!Array.isArray(events)) return []
  return events.filter((event): event is ToolEvent => Boolean(
    event
    && typeof event === 'object'
    && typeof (event as ToolEvent).phase === 'string'
    && typeof (event as ToolEvent).name === 'string',
  ))
}

function completionResponseMeta(payload: Record<string, unknown>): ResponseMeta | undefined {
  const shenyu = payload.shenyu
  if (!shenyu || typeof shenyu !== 'object' || Array.isArray(shenyu)) return undefined
  const meta = (shenyu as Record<string, unknown>).response_meta
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return undefined
  return { ...(meta as ResponseMeta) }
}

function completionEchoSegments(payload: Record<string, unknown>): Array<{ content: string; stream_order?: number }> {
  const shenyu = payload.shenyu
  if (!shenyu || typeof shenyu !== 'object' || Array.isArray(shenyu)) return []
  const segments = (shenyu as Record<string, unknown>).echo_segments
  if (Array.isArray(segments)) {
    return segments.flatMap((item) => {
      if (typeof item === 'string') return item ? [{ content: item }] : []
      if (!item || typeof item !== 'object' || Array.isArray(item)) return []
      const segment = item as Record<string, unknown>
      if (typeof segment.content !== 'string' || !segment.content) return []
      return [{
        content: segment.content,
        stream_order: Number.isFinite(Number(segment.stream_order)) ? Number(segment.stream_order) : undefined,
      }]
    })
  }
  const echo = (shenyu as Record<string, unknown>).echo
  return typeof echo === 'string' && echo ? [{ content: echo }] : []
}

export function applyChatCompletion(payload: Record<string, unknown>, assistant: UiMessage): void {
  if (payload.error) {
    const error = payload.error
    const message = error && typeof error === 'object' && !Array.isArray(error)
      ? (error as Record<string, unknown>).message
      : error
    throw new Error(String(message || '请求没有完成'))
  }

  const choices = Array.isArray(payload.choices) ? payload.choices : []
  const choice = choices[0]
  const message = choice && typeof choice === 'object' && !Array.isArray(choice)
    ? (choice as Record<string, unknown>).message
    : undefined
  const reply = message && typeof message === 'object' && !Array.isArray(message)
    ? message as Record<string, unknown>
    : {}

  for (const event of completionToolEvents(payload)) appendToolEvent(assistant, event, true)
  const responseMeta = completionResponseMeta(payload)
  if (responseMeta) assistant.responseMeta = responseMeta
  for (const segment of completionEchoSegments(payload)) {
    if (segment.stream_order !== undefined) {
      assistant.echoSegments ||= []
      assistant.echoSegments.push({
        id: `echo-${segment.stream_order}-${assistant.echoSegments.length}`,
        content: segment.content,
        textOffset: textLength(assistant.content),
        streamOrder: segment.stream_order,
      })
      assistant.echo = (assistant.echo || '') + segment.content
    } else {
      appendEcho(assistant, segment.content)
    }
  }
  appendThinking(assistant, completionText(reply.reasoning_content))
  appendThinking(assistant, completionText(reply.reasoning))
  assistant.content += completionText(reply.content)
}
