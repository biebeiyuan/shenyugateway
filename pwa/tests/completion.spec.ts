import { describe, expect, it } from 'vitest'
import { applyChatCompletion } from '../src/stream/completion'
import type { UiMessage } from '../src/types'

function assistant(): UiMessage {
  return { id: 'assistant-1', role: 'assistant', content: '', attachments: [], thinking: '', thinkingSegments: [], events: [], streaming: true }
}

describe('applyChatCompletion', () => {
  it('hydrates content, reasoning, and gateway tool events from a non-stream response', () => {
    const message = assistant()
    applyChatCompletion({
      choices: [{ message: { content: '最后的回答', reasoning_content: '先想一想' } }],
      shenyu: {
        response_meta: {
          context_rounds: 9,
          context_trim_in_rounds: 17,
          cache_read_percent: 75,
          tool_rounds: 2,
          first_tool_round_cache_hit: true,
          heartbeat_captured: true,
        },
        tool_events: [
          { phase: 'tool_start', tool_call_id: 't1', name: 'shenyu_recall' },
          { phase: 'tool_end', tool_call_id: 't1', name: 'shenyu_recall', ok: true },
        ],
      },
    }, message)

    expect(message.content).toBe('最后的回答')
    expect(message.thinking).toBe('先想一想')
    expect(message.thinkingSegments[0].textOffset).toBe(0)
    expect(message.events).toHaveLength(2)
    expect(message.events[1].ok).toBe(true)
    expect(message.responseMeta?.context_rounds).toBe(9)
    expect(message.responseMeta?.context_trim_in_rounds).toBe(17)
    expect(message.responseMeta?.cache_read_percent).toBe(75)
    expect(message.responseMeta?.first_tool_round_cache_hit).toBe(true)
    expect(message.responseMeta?.heartbeat_captured).toBe(true)
  })

  it('accepts text block content and both reasoning field names', () => {
    const message = assistant()
    applyChatCompletion({
      choices: [{ message: {
        content: [{ type: 'text', text: '第一段' }, { type: 'text', content: '第二段' }],
        reasoning_content: 'A',
        reasoning: 'B',
      } }],
    }, message)

    expect(message.content).toBe('第一段第二段')
    expect(message.thinking).toBe('AB')
  })

  it('surfaces an error response', () => {
    expect(() => applyChatCompletion({ error: { message: '上游断开' } }, assistant())).toThrow('上游断开')
  })
})
