import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

const here = dirname(fileURLToPath(import.meta.url))
import { describe, expect, it, vi } from 'vitest'
import { createApp, h, nextTick, ref } from 'vue'
import ChatMessageRow from '../src/components/ChatMessageRow.vue'
import MarkdownBody from '../src/components/MarkdownBody.vue'
import { clearMarkdownCache } from '../src/markdown'
import type { UiMessage } from '../src/types'

function uiMessage(role: 'user' | 'assistant', content: string, extra: Partial<UiMessage> = {}): UiMessage {
  return {
    id: `id-${role}-${content.slice(0, 8)}`,
    role,
    content,
    echo: '',
    echoSegments: [],
    attachments: [],
    thinking: '',
    thinkingSegments: [],
    events: [],
    ...extra,
  }
}

function mount(component: any) {
  const host = document.createElement('div')
  const app = createApp(component)
  app.config.errorHandler = () => {}
  app.mount(host)
  return { host, app }
}

describe('ChatMessageRow blast radius', () => {
  // 拆组件之前，任何一条消息的渲染异常都会让 Vue 卸载整棵树——手机上就是白屏，
  // 而且 App.vue 里那 1800 行全在同一个组件里，等于所有渲染共用一根保险丝。
  //
  // 故障用「user 消息少了 attachments 数组」注入：模板会读 .length，这正是快照
  // 恢复或数据形状变更真实出错的样子，比塞 null 更像会发生的事。
  it('contains a render failure to the one bad row', async () => {
    const messages = ref([
      uiMessage('assistant', 'first answer'),
      uiMessage('user', 'second message'),
      uiMessage('assistant', 'third answer'),
    ])
    const bad = ref(false)
    const App = {
      setup() {
        return () => h('div', [
          h('header', 'topbar'),
          ...messages.value.map((message, index) => h(ChatMessageRow, {
            key: message.id,
            message: bad.value && index === 1
              ? ({ ...message, attachments: undefined } as unknown as UiMessage)
              : message,
            metaLabel: '',
          })),
        ])
      },
    }
    const { host } = mount(App)
    await nextTick()
    expect(host.textContent).toContain('first answer')

    vi.spyOn(console, 'error').mockImplementation(() => {})
    bad.value = true
    await nextTick()
    await nextTick()

    expect(host.textContent).toContain('topbar')
    expect(host.textContent).toContain('first answer')
    expect(host.textContent).toContain('third answer')
    // 保险丝的作用是让坏掉那条留下一句话；没有它，这一行会静默变空白。
    expect(host.textContent).toContain('这条消息没能显示出来')
    vi.restoreAllMocks()
  })

  // 上面那条测的是"坏一条留一句话"。这条测的是"为什么必须拆成子组件"：
  // 消息内联在根组件的 render 里时（拆分前 App.vue 的样子），一条坏消息会让整棵
  // 树塌成一个空注释节点——顶栏、输入框、其余所有消息一起消失，就是白屏。
  it('documents why inline rendering in the root render collapses the whole tree', async () => {
    const bad = ref(false)
    const Inline = {
      setup() {
        return () => h('div', [
          h('header', 'topbar'),
          ...['a', 'b', 'c'].map((text, index) =>
            h('p', { key: index }, bad.value && index === 1 ? (null as any).boom : text)),
        ])
      },
    }
    const { host } = mount(Inline)
    await nextTick()
    expect(host.textContent).toContain('topbar')

    vi.spyOn(console, 'error').mockImplementation(() => {})
    bad.value = true
    await nextTick()
    expect(host.innerHTML).toBe('<!---->')
    vi.restoreAllMocks()
  })
})

describe('transcript re-render isolation', () => {
  // 实测：单组件结构下输入框敲一个字会让 40 条消息全部重新渲染 Markdown
  // （4.95ms × 40 ≈ 200ms 主线程阻塞）。子组件的 props 没变就不该重渲染。
  it('does not re-render history rows when an unrelated parent ref changes', async () => {
    clearMarkdownCache()
    let renders = 0
    const Probe = {
      props: { content: { type: String, required: true } },
      setup(props: any) {
        return () => { renders++; return h('p', props.content) }
      },
    }
    const draft = ref('')
    const messages = ref(Array.from({ length: 40 }, (_, index) => `msg ${index}`))
    const App = {
      setup() {
        return () => h('div', [
          h('textarea', { value: draft.value }),
          ...messages.value.map((content, index) => h(Probe, { key: index, content })),
        ])
      },
    }
    mount(App)
    await nextTick()
    const afterMount = renders
    expect(afterMount).toBe(40)

    draft.value = 'a'
    await nextTick()
    expect(renders - afterMount).toBe(0)

    // 流式来一个 chunk 只应重渲染尾巴那一条。
    messages.value[39] += ' delta'
    await nextTick()
    expect(renders - afterMount).toBe(1)
  })
})

describe('MarkdownBody', () => {
  it('renders Markdown while streaming so the reply does not reflow at the end', async () => {
    clearMarkdownCache()
    const streaming = ref(true)
    const App = {
      setup() {
        return () => h(MarkdownBody, { content: '**加粗**的正文', streaming: streaming.value })
      },
    }
    const { host } = mount(App)
    await nextTick()
    // 流式期间就已经是 <strong>，收尾不再从纯文本整段换成 Markdown。
    expect(host.innerHTML).toContain('<strong>加粗</strong>')

    const streamingHtml = host.querySelector('.markdown-content')?.innerHTML
    streaming.value = false
    await nextTick()
    expect(host.querySelector('.markdown-content')?.innerHTML).toBe(streamingHtml)
  })

  it('skips syntax highlighting while streaming and applies it on completion', async () => {
    clearMarkdownCache()
    const streaming = ref(true)
    const App = {
      setup() {
        return () => h(MarkdownBody, {
          content: '```python\nimport json\n```',
          streaming: streaming.value,
        })
      },
    }
    const { host } = mount(App)
    await nextTick()
    expect(host.innerHTML).not.toContain('hljs')

    streaming.value = false
    await nextTick()
    expect(host.innerHTML).toContain('hljs')
  })
})

describe('photos in a message row', () => {
  const live = (n: number) => ({ id: `l${n}`, name: 'p.jpg', mime: 'image/jpeg', fingerprint: 'f'.repeat(64), dataUrl: `data:image/jpeg;base64,A${n}` })
  const expired = (n: number) => ({ id: `d${n}`, name: 'p.jpg', mime: 'image/jpeg', fingerprint: 'g'.repeat(64) })

  function render(attachments: any[]) {
    const message = uiMessage('user', '看这个', { attachments })
    const { host } = mount({ setup: () => () => h(ChatMessageRow, { message, metaLabel: '' }) })
    return host
  }

  it('shows a single photo plainly, not as a fake stack', async () => {
    const host = render([live(1)])
    await nextTick()
    expect(host.querySelector('.photo-stack')).toBeNull()
    expect(host.querySelectorAll('.message-images img')).toHaveLength(1)
  })

  it('collapses several photos into one stack card', async () => {
    const host = render([live(1), live(2), live(3)])
    await nextTick()
    expect(host.querySelector('.photo-stack')).not.toBeNull()
    expect(host.querySelectorAll('.photo-stack-card')).toHaveLength(3)
  })

  it('still notes the expired ones beside a stack', async () => {
    // 一叠里有过期的图时要留痕迹，否则会以为圆圆没发那几张。
    const host = render([live(1), live(2), expired(1)])
    await nextTick()
    expect(host.querySelectorAll('.photo-stack-card')).toHaveLength(2)
    expect(host.querySelector('.message-image-expired')?.textContent).toContain('另有 1 张过期了')
  })

  it('falls back to plain expiry markers when nothing is left to show', async () => {
    const host = render([expired(1), expired(2)])
    await nextTick()
    expect(host.querySelector('.photo-stack')).toBeNull()
    expect(host.querySelectorAll('.message-image-expired')).toHaveLength(2)
  })
})

describe('the stack card must not widen the transcript', () => {
  // 圆圆在真机底部看到一条灰色横条：探边卡比舞台宽约 27px，把 .message-stream
  // 撑出了横向滚动条。探边溢出是设计要求，滚动不是——所以 CSS 侧两头都要挡：
  // 卡片留出侧边距，容器显式关掉 overflow-x。
  it('reserves side room for the peeking cards in CSS', () => {
    const css = readFileSync(resolve(here, '../src/styles.css'), 'utf8')
    const stack = css.match(/\.photo-stack \{[^}]*\}/)?.[0] || ''
    expect(stack).toContain('margin: 0 27px')
    const stream = css.match(/\.message-stream \{[^}]*\}/)?.[0] || ''
    expect(stream).toContain('overflow-x: hidden')
  })
})
