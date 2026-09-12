import { describe, expect, it } from 'vitest'
import { applyReconciledTail, applyReplyRecovery, tailNeedsReconcile } from '../src/session/reconcile'
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

  it('concatenates all assistant rows in a multi-turn tool round', () => {
    const messages = [uiMessage('user', '继续')]
    applyReconciledTail(messages, payloadOf([
      { role: 'user', content: '继续' },
      { role: 'assistant', content: '第一段' },
      { role: 'assistant', content: '第二段更完整' },
    ]))
    expect(messages[1].content).toBe('第一段\n\n第二段更完整')
  })
})

describe('applyReconciledTail — replace branch', () => {
  it('rejects server reply when it would make content shorter (even with version id match)', () => {
    const messages = [
      uiMessage('user', '本地问题带有不同表示'),
      uiMessage('assistant', '本地残片比服务器长', {
        replyVersionId: 'reply-roll-2',
        truncated: true,
        selectedVariantIndex: 1,
        variants: [
          { content: '旧版本', echo: '', echoSegments: [], thinking: '', thinkingSegments: [], events: [], replyVersionId: 'reply-roll-1' },
          { content: '本地残片比服务器长', echo: '', echoSegments: [], thinking: '', thinkingSegments: [], events: [], replyVersionId: 'reply-roll-2' },
        ],
      }),
    ]
    // 服务端虽然有版本号匹配，但内容更短（即使加上回响），拒绝以防止削短
    const changed = applyReconciledTail(messages, payloadOf([
      { role: 'user', content: '服务器侧已经整理过的表示' },
      { role: 'assistant', source_id: 'reply-roll-1', content: '旧版本' },
      { role: 'assistant', source_id: 'reply-roll-2', content: '[回响]回来[/回响]短答' },
    ]))
    expect(changed).toBe(false)
    // 本地内容应该保持不变，truncated 标记也保留
    expect(messages[1].content).toBe('本地残片比服务器长')
    expect(messages[1].truncated).toBe(true)
  })

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

describe('applyReplyRecovery — durable roll group', () => {
  it('merges all same-user rolls into one switchable assistant bubble', () => {
    const messages = [
      uiMessage('user', '最后一个问题 【状态】'),
      uiMessage('assistant', '当前版本', { replyVersionId: 'v3' }),
    ]
    const changed = applyReplyRecovery(messages, {
      replies: [
        { id: 'a1', reply_version_id: 'v1', content: '第一版' },
        { id: 'a2', reply_version_id: 'v2', content: '[回响]看着你[/回响]第二版' },
        { id: 'a3', reply_version_id: 'v3', content: '当前版本' },
      ],
    })
    expect(changed).toBe(true)
    expect(messages[1].variants).toHaveLength(3)
    expect(messages[1].variants?.map((item) => item.replyVersionId)).toEqual(['v1', 'v2', 'v3'])
    expect(messages[1].replyVersionId).toBe('v3')
    expect(messages[1].content).toBe('当前版本')
  })

  it('does not duplicate an already recovered roll on polling', () => {
    const messages = [uiMessage('user', '问题'), uiMessage('assistant', '一版')]
    expect(applyReplyRecovery(messages, { replies: [{ reply_version_id: 'v1', content: '一版' }] })).toBe(true)
    expect(applyReplyRecovery(messages, { replies: [{ reply_version_id: 'v1', content: '一版' }] })).toBe(false)
    expect(messages[1].variants).toHaveLength(1)
  })

  it('cleans duplicate legacy snapshot entries while upgrading the durable id', () => {
    const messages = [
      uiMessage('user', '问题'),
      uiMessage('assistant', '同一版', {
        variants: [
          { content: '同一版', echo: '', echoSegments: [], thinking: '', thinkingSegments: [], events: [] },
          { content: '同一版', echo: '', echoSegments: [], thinking: '', thinkingSegments: [], events: [] },
        ],
      }),
    ]
    expect(applyReplyRecovery(messages, { replies: [{ reply_version_id: 'stable', content: '同一版' }] })).toBe(true)
    expect(messages[1].variants).toHaveLength(1)
    expect(messages[1].variants?.[0].replyVersionId).toBe('stable')
  })

  it('does not overwrite complete messages that were received normally', () => {
    const messages = [
      uiMessage('user', '问题'),
      uiMessage('assistant', '完整回复', {
        thinking: 'Let me think...',
        thinkingSegments: [{ id: 'th1', content: 'Let me think...', textOffset: 0, streamOrder: 0 }],
        events: [{ phase: 'call', tool_call_id: 'tc1', name: 'test_tool', input: '{}' }],
      }),
    ]
    const changed = applyReplyRecovery(messages, {
      replies: [{ reply_version_id: 'v1', content: '完整回复' }],
    })
    // Should only add variants, not overwrite the complete message
    expect(changed).toBe(false)
    expect(messages[1].content).toBe('完整回复')
    expect(messages[1].thinking).toBe('Let me think...')
    expect(messages[1].thinkingSegments).toHaveLength(1)
    expect(messages[1].events).toHaveLength(1)
  })

  it('preserves thinking when merging server variants into existing variants', () => {
    const messages = [
      uiMessage('user', '问题'),
      uiMessage('assistant', '版本一', {
        replyVersionId: 'v1',
        thinking: 'Original thinking',
        thinkingSegments: [{ id: 'th1', content: 'Original thinking', textOffset: 0, streamOrder: 0 }],
        variants: [
          {
            content: '版本一',
            echo: '',
            echoSegments: [],
            thinking: 'Original thinking',
            thinkingSegments: [{ id: 'th1', content: 'Original thinking', textOffset: 0, streamOrder: 0 }],
            events: [],
            replyVersionId: 'v1',
          },
        ],
      }),
    ]
    const changed = applyReplyRecovery(messages, {
      replies: [
        { reply_version_id: 'v1', content: '版本一' },
        { reply_version_id: 'v2', content: '版本二' },
      ],
    })
    expect(changed).toBe(true)
    expect(messages[1].variants).toHaveLength(2)
    // First variant should preserve thinking
    expect(messages[1].variants?.[0].thinking).toBe('Original thinking')
    expect(messages[1].variants?.[0].thinkingSegments).toHaveLength(1)
    // Current message should also preserve thinking
    expect(messages[1].thinking).toBe('Original thinking')
    expect(messages[1].thinkingSegments).toHaveLength(1)
  })

  it('recovers incomplete messages with truncated or error flags', () => {
    const messages = [
      uiMessage('user', '问题'),
      uiMessage('assistant', '半截', {
        truncated: true,
        thinking: 'Some thinking',
        thinkingSegments: [{ id: 'th1', content: 'Some thinking', textOffset: 0, streamOrder: 0 }],
      }),
    ]
    const changed = applyReplyRecovery(messages, {
      replies: [{ reply_version_id: 'v1', content: '完整版本' }],
    })
    expect(changed).toBe(true)
    expect(messages[1].content).toBe('完整版本')
    expect(messages[1].truncated).toBeUndefined()
    // Should preserve thinking even when recovering
    expect(messages[1].thinking).toBe('Some thinking')
    expect(messages[1].thinkingSegments).toHaveLength(1)
  })

  it('returns false when tail is complete and no new variants arrive', () => {
    const messages = [
      uiMessage('user', '问题'),
      uiMessage('assistant', '完整回复', {
        replyVersionId: 'v1',
        thinking: 'Deep analysis',
        thinkingSegments: [{ id: 'th1', content: 'Deep analysis', textOffset: 0, streamOrder: 0 }],
        events: [
          { phase: 'call', tool_call_id: 'tc1', name: 'search', input: '{"q":"test"}' },
          { phase: 'result', tool_call_id: 'tc1', ok: true, result: '{}' },
        ],
      }),
    ]
    // 服务端返回同一个版本，本地已有，没有新变体
    const changed = applyReplyRecovery(messages, {
      replies: [{ reply_version_id: 'v1', content: '完整回复' }],
    })
    expect(changed).toBe(false)
    expect(messages[1].thinking).toBe('Deep analysis')
    expect(messages[1].thinkingSegments).toHaveLength(1)
    expect(messages[1].events).toHaveLength(2)
  })

  it('does not flip-flop variants when candidate has no reply_version_id', () => {
    const messages = [
      uiMessage('user', '问题'),
      uiMessage('assistant', '旧快照版本', {
        variants: [
          { content: '旧快照版本', echo: '', echoSegments: [], thinking: '', thinkingSegments: [], events: [] },
        ],
      }),
    ]
    // 第一次恢复：没有 reply_version_id 的候选者
    applyReplyRecovery(messages, {
      replies: [{ content: '旧快照版本' }],
    })
    const firstLength = messages[1].variants?.length || 0
    // 第二次恢复：同样的候选者，不应该重复插入
    const changed = applyReplyRecovery(messages, {
      replies: [{ content: '旧快照版本' }],
    })
    expect(changed).toBe(false)
    expect(messages[1].variants?.length).toBe(firstLength)
  })

  it('preserves local thinking and events when server variant has none', () => {
    const messages = [
      uiMessage('user', '问题'),
      uiMessage('assistant', '回复', {
        replyVersionId: 'v1',
        thinking: 'Let me analyze this carefully',
        thinkingSegments: [{ id: 'th1', content: 'Let me analyze this carefully', textOffset: 0, streamOrder: 0 }],
        events: [
          { phase: 'call', tool_call_id: 'tc1', name: 'search', input: '{"q":"test"}', textOffset: 50, streamOrder: 2 },
          { phase: 'result', tool_call_id: 'tc1', ok: true, result: '{"found":true}', textOffset: 50, streamOrder: 3 },
        ],
        variants: [
          {
            content: '回复',
            echo: '',
            echoSegments: [],
            thinking: 'Let me analyze this carefully',
            thinkingSegments: [{ id: 'th1', content: 'Let me analyze this carefully', textOffset: 0, streamOrder: 0 }],
            events: [
              { phase: 'call', tool_call_id: 'tc1', name: 'search', input: '{"q":"test"}', textOffset: 50, streamOrder: 2 },
              { phase: 'result', tool_call_id: 'tc1', ok: true, result: '{"found":true}', textOffset: 50, streamOrder: 3 },
            ],
            replyVersionId: 'v1',
          },
        ],
      }),
    ]
    // 服务端发来同一版本，但没有 thinking 和正确的 events（tool 补水会塌到 offset 0）
    const changed = applyReplyRecovery(messages, {
      replies: [{ reply_version_id: 'v1', content: '回复' }],
    })
    // 不应该覆盖，因为内容相同且本地有完整数据
    expect(changed).toBe(false)
    expect(messages[1].thinking).toBe('Let me analyze this carefully')
    expect(messages[1].thinkingSegments).toHaveLength(1)
    expect(messages[1].events).toHaveLength(2)
    expect(messages[1].events[0].textOffset).toBe(50)
    expect(messages[1].variants?.[0].thinking).toBe('Let me analyze this carefully')
    expect(messages[1].variants?.[0].events).toHaveLength(2)
  })

  it('keeps truncated when the server has nothing better yet', () => {
    const messages = [
      uiMessage('user', '问题'),
      uiMessage('assistant', '半截', { replyVersionId: 'v1', truncated: true }),
    ]
    applyReplyRecovery(messages, { replies: [{ reply_version_id: 'v1', content: '半截' }] })
    expect(messages[1].truncated).toBe(true)
    expect(tailNeedsReconcile(messages)).toBe(true)
  })

  it('rejects server content that is longer but does not include local text', () => {
    const messages = [uiMessage('user', '问题'), uiMessage('assistant', '第一段\n\n第二段')]
    const changed = applyReplyRecovery(messages, {
      replies: [{ reply_version_id: 'v1', content: '完全不同的更长内容，但不包含本地文本' }],
    })
    // 新 variant 会被添加（changed = true），但不会覆盖本地内容
    expect(changed).toBe(true)
    expect(messages[1].content).toBe('第一段\n\n第二段')
    expect(messages[1].variants.length).toBe(2)
  })

  it('preserves multi-segment echoSegments when guard allows recovery', () => {
    const messages = [
      uiMessage('user', '问题'),
      uiMessage('assistant', '我先查', {
        truncated: true,
        echo: '看了一眼',
        echoSegments: [
          { id: 'e1', content: '看了', textOffset: 0, streamOrder: 0 },
          { id: 'e2', content: '一眼', textOffset: 10, streamOrder: 2 },
        ],
      }),
    ]
    const changed = applyReplyRecovery(messages, {
      replies: [{ reply_version_id: 'v1', content: '[回响]看了一眼[/回响]我先查天气，然后查日历' }],
    })
    expect(changed).toBe(true)
    // 护栏放行后，echoSegments 应该保留原有的多段分布
    expect(messages[1].echoSegments.length).toBe(2)
    expect(messages[1].echoSegments[0].textOffset).toBe(0)
    expect(messages[1].echoSegments[1].textOffset).toBe(10)
  })

  it('keeps every roll when repairing a truncated tail', () => {
    const messages = [
      uiMessage('user', '问题'),
      uiMessage('assistant', '半截', { truncated: true }),
    ]
    applyReplyRecovery(messages, {
      replies: [
        { reply_version_id: 'v1', content: '第一版' },
        { reply_version_id: 'v2', content: '第二版' },
      ],
    })
    expect(messages[1].variants).toHaveLength(2)
    expect(messages[1].content).toBe('第二版')
  })

  it('preserves responseMeta during recovery', () => {
    const messages = [
      uiMessage('user', '问题'),
      uiMessage('assistant', '回复', {
        replyVersionId: 'v1',
        variants: [
          {
            content: '回复',
            echo: '',
            echoSegments: [],
            thinking: '',
            thinkingSegments: [],
            events: [],
            replyVersionId: 'v1',
            responseMeta: { model: 'claude-opus-5', usage: { input_tokens: 100, output_tokens: 50 } },
          },
        ],
      }),
    ]
    applyReplyRecovery(messages, { replies: [{ reply_version_id: 'v1', content: '回复' }] })
    expect(messages[1].variants?.[0].responseMeta).toEqual({
      model: 'claude-opus-5',
      usage: { input_tokens: 100, output_tokens: 50 },
    })
  })

  it('preserves full multi-turn tool content from server', () => {
    const messages = [
      uiMessage('user', '查一下'),
      // 本地流式接收时包含换行符，服务端拼接时也会加 \n\n
      uiMessage('assistant', '我先查天气。\n\n查到了,再查日历。\n\n结论是明天可以去。', {
        truncated: true,
        events: [
          { phase: 'call', tool_call_id: 'tc1', name: 'weather', input: '{}', textOffset: 6, streamOrder: 0 },
          { phase: 'result', tool_call_id: 'tc1', ok: true, result: '{"ok":true}', textOffset: 6, streamOrder: 1 },
          { phase: 'call', tool_call_id: 'tc2', name: 'calendar', input: '{}', textOffset: 20, streamOrder: 2 },
          { phase: 'result', tool_call_id: 'tc2', ok: true, result: '{"ok":true}', textOffset: 20, streamOrder: 3 },
        ],
      }),
    ]
    const changed = applyReconciledTail(messages, payloadOf([
      { role: 'user', content: '查一下' },
      { role: 'assistant', content: '我先查天气。' },
      { role: 'tool', tool_name: 'weather', content: '{"ok":true}' },
      { role: 'assistant', content: '查到了,再查日历。' },
      { role: 'tool', tool_name: 'calendar', content: '{"ok":true}' },
      { role: 'assistant', content: '结论是明天可以去。' },
    ]))
    expect(changed).toBe(true)
    expect(messages[1].content).toContain('我先查天气')
    expect(messages[1].content).toContain('查到了,再查日历')
    expect(messages[1].content).toContain('结论是明天可以去')
    expect(messages[1].events.length).toBeGreaterThanOrEqual(4)
  })

  it('rejects server content when shorter than local', () => {
    const messages = [
      uiMessage('user', '问题'),
      uiMessage('assistant', '完整的长回复内容'),
    ]
    const changed = applyReconciledTail(messages, payloadOf([
      { role: 'user', content: '问题' },
      { role: 'assistant', content: '短回复' },
    ]))
    expect(changed).toBe(false)
    expect(messages[1].content).toBe('完整的长回复内容')
  })
})

