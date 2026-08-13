import { describe, expect, it } from 'vitest'
import { applyReconciledTail, tailNeedsReconcile } from '../src/session/reconcile'
import type { UiMessage } from '../src/types'

function uiMessage(role: 'user' | 'assistant', content: string, extra: Partial<UiMessage> = {}): UiMessage {
  return { id: `id-${role}-${content.slice(0, 8)}`, role, content, echo: '', echoSegments: [], attachments: [], thinking: '', thinkingSegments: [], events: [], ...extra }
}

function payloadOf(rows: Array<Record<string, unknown>>): Record<string, unknown> {
  return { recent_messages: rows }
}

describe('tailNeedsReconcile', () => {
  it('flags a trailing user message and an assistant with error or truncated', () => {
    expect(tailNeedsReconcile([uiMessage('user', '问题')])).toBe(true)
    expect(tailNeedsReconcile([uiMessage('user', '问题'), uiMessage('assistant', '半截', { truncated: true })])).toBe(true)
    expect(tailNeedsReconcile([uiMessage('user', '问题'), uiMessage('assistant', '', { error: '连接停滞' })])).toBe(true)
  })

  it('leaves a complete tail and an empty transcript alone', () => {
    expect(tailNeedsReconcile([uiMessage('user', '问题'), uiMessage('assistant', '完整回复')])).toBe(false)
    expect(tailNeedsReconcile([])).toBe(false)
  })
})

describe('applyReconciledTail — append branch', () => {
  it('appends the server reply when the local tail is an unanswered user message', () => {
    const messages = [uiMessage('user', '今晚吃什么')]
    const changed = applyReconciledTail(messages, payloadOf([
      { id: 'r1', role: 'user', content: '今晚吃什么' },
      { id: 'r2', role: 'assistant', content: '吃火锅吧' },
    ]))
    expect(changed).toBe(true)
    expect(messages).toHaveLength(2)
    expect(messages[1].role).toBe('assistant')
    expect(messages[1].content).toBe('吃火锅吧')
    expect(messages[1].streaming).toBe(false)
  })

  it('splits the echo marker out of the recovered reply', () => {
    const messages = [uiMessage('user', '在吗')]
    applyReconciledTail(messages, payloadOf([
      { role: 'user', content: '在吗' },
      { role: 'assistant', content: '[回响]低头看了一眼[/回响]在的' },
    ]))
    expect(messages[1].content).toBe('在的')
    expect(messages[1].echo).toBe('低头看了一眼')
    expect(messages[1].echoSegments).toHaveLength(1)
  })

  it('hydrates tool events from tool rows preceding the recovered reply', () => {
    const messages = [uiMessage('user', '查一下')]
    applyReconciledTail(messages, payloadOf([
      { role: 'user', content: '查一下' },
      { id: 't1', role: 'tool', tool_name: 'shenyu_recall', tool_args_json: '{"query":"x"}', content: '{"ok":true}' },
      { role: 'assistant', content: '查到了' },
    ]))
    expect(messages[1].content).toBe('查到了')
    expect(messages[1].events).toHaveLength(2)
    expect(messages[1].events[0].name).toBe('shenyu_recall')
    expect(messages[1].events[1].ok).toBe(true)
  })

  it('takes the last assistant row of the round when drain wrote several', () => {
    const messages = [uiMessage('user', '继续')]
    applyReconciledTail(messages, payloadOf([
      { role: 'user', content: '继续' },
      { role: 'assistant', content: '第一段' },
      { role: 'assistant', content: '第二段更完整' },
    ]))
    expect(messages[1].content).toBe('第二段更完整')
  })
})

describe('applyReconciledTail — replace branch', () => {
  it('replaces a truncated assistant tail when the server text is longer', () => {
    const messages = [
      uiMessage('user', '讲个长故事'),
      uiMessage('assistant', '从前有座山', { truncated: true, error: '连接停滞，可能已断开' }),
    ]
    const changed = applyReconciledTail(messages, payloadOf([
      { role: 'user', content: '讲个长故事' },
      { role: 'assistant', content: '从前有座山，山里有座庙，庙里有个老和尚' },
    ]))
    expect(changed).toBe(true)
    expect(messages).toHaveLength(2)
    expect(messages[1].content).toBe('从前有座山，山里有座庙，庙里有个老和尚')
    expect(messages[1].truncated).toBeUndefined()
    expect(messages[1].error).toBeUndefined()
    expect(messages[1].streaming).toBe(false)
  })

  it('keeps the local tail when the server text is not longer', () => {
    const messages = [
      uiMessage('user', '讲个长故事'),
      uiMessage('assistant', '本地已经拿到的更长回复', { truncated: true }),
    ]
    const changed = applyReconciledTail(messages, payloadOf([
      { role: 'user', content: '讲个长故事' },
      { role: 'assistant', content: '短的' },
    ]))
    expect(changed).toBe(false)
    expect(messages[1].content).toBe('本地已经拿到的更长回复')
    expect(messages[1].truncated).toBe(true)
  })

  it('counts echo plus content when comparing lengths', () => {
    const messages = [
      uiMessage('user', '在吗'),
      uiMessage('assistant', '在的', { truncated: true }),
    ]
    const changed = applyReconciledTail(messages, payloadOf([
      { role: 'user', content: '在吗' },
      { role: 'assistant', content: '[回响]抬起头来看着你[/回响]在的' },
    ]))
    expect(changed).toBe(true)
    expect(messages[1].echo).toBe('抬起头来看着你')
    expect(messages[1].content).toBe('在的')
  })
})

describe('applyReconciledTail — no-op branch', () => {
  it('does nothing when the tail is already complete', () => {
    const messages = [uiMessage('user', '问题'), uiMessage('assistant', '完整回复')]
    expect(applyReconciledTail(messages, payloadOf([
      { role: 'user', content: '问题' },
      { role: 'assistant', content: '完整回复但是更长的服务端版本' },
    ]))).toBe(false)
    expect(messages[1].content).toBe('完整回复')
  })

  it('does nothing when the server tail is behind the local anchor (drain not finished)', () => {
    const messages = [uiMessage('user', '最新的问题')]
    expect(applyReconciledTail(messages, payloadOf([
      { role: 'user', content: '上一轮的问题' },
      { role: 'assistant', content: '上一轮的回复' },
    ]))).toBe(false)
    expect(messages).toHaveLength(1)
  })

  it('does nothing when the anchor matches but no reply row follows yet', () => {
    const messages = [uiMessage('user', '最新的问题')]
    expect(applyReconciledTail(messages, payloadOf([
      { role: 'user', content: '最新的问题' },
    ]))).toBe(false)
    expect(messages).toHaveLength(1)
  })

  it('ignores replies that belong to the next user turn', () => {
    const messages = [
      uiMessage('user', '第一问'),
      uiMessage('assistant', '', { error: 'boom' }),
    ]
    // 服务端已经进入下一轮：锚定的 user 行不再是最新 user 行 → 不能拿别轮回复充数。
    expect(applyReconciledTail(messages, payloadOf([
      { role: 'user', content: '第一问' },
      { role: 'user', content: '第二问' },
      { role: 'assistant', content: '第二问的回复' },
    ]))).toBe(false)
  })

  it('survives an empty or missing recent_messages payload', () => {
    const messages = [uiMessage('user', '问题')]
    expect(applyReconciledTail(messages, payloadOf([]))).toBe(false)
    expect(applyReconciledTail(messages, {})).toBe(false)
  })
})
