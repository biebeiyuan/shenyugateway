import type { ToolEvent } from '../toolLanguage'
import type { UiMessage } from '../types'
import { appendThinking, appendToolEvent } from './sse'

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

  for (const event of completionToolEvents(payload)) appendToolEvent(assistant, event)
  appendThinking(assistant, completionText(reply.reasoning_content))
  appendThinking(assistant, completionText(reply.reasoning))
  assistant.content += completionText(reply.content)
}
