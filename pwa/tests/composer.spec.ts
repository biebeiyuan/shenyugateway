import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ref } from 'vue'
import { useComposer } from '../src/session/useComposer'

// keepComposerVisible 只在「点进输入框那刻本来就贴底」时才钉回底部；往上翻着读再
// 点进来打字的人不该被拽下来（2026-08-31 圆圆报的「返回上面打字会跳下来」）。

function makeStream(opts: { scrollTop: number; scrollHeight: number; clientHeight: number }) {
  const el = document.createElement('div')
  Object.defineProperty(el, 'scrollHeight', { get: () => opts.scrollHeight, configurable: true })
  Object.defineProperty(el, 'clientHeight', { get: () => opts.clientHeight, configurable: true })
  let top = opts.scrollTop
  Object.defineProperty(el, 'scrollTop', { get: () => top, set: (v) => { top = v }, configurable: true })
  return el
}

// 造一个在 .composer-wrap 里、且 document.activeElement 指向它的 textarea。
function mountInput() {
  const wrap = document.createElement('div')
  wrap.className = 'composer-wrap'
  const input = document.createElement('textarea')
  wrap.appendChild(input)
  document.body.appendChild(wrap)
  input.focus()
  wrap.getBoundingClientRect = () => ({ bottom: 800 }) as DOMRect
  return input
}

beforeEach(() => {
  document.body.innerHTML = ''
  vi.stubGlobal('visualViewport', { offsetTop: 0, height: 800, addEventListener() {}, removeEventListener() {} })
})

describe('composer keeps your place when typing', () => {
  it('pins to bottom only when focus happened at the bottom', async () => {
    const input = mountInput()
    // 贴底：scrollHeight - scrollTop - clientHeight = 0
    const streamRef = ref(makeStream({ scrollTop: 400, scrollHeight: 1000, clientHeight: 600 }))
    const inputRef = ref(input)
    const c = useComposer({ draft: ref(''), inputRef, streamRef, onSubmit: () => {} })

    c.onComposerFocus()
    c.keepComposerVisible()
    await Promise.resolve()
    expect(streamRef.value!.scrollTop).toBe(streamRef.value!.scrollHeight) // 被钉到底
  })

  it('leaves you alone when you scrolled up before focusing', async () => {
    const input = mountInput()
    // 往上翻了：距底部很远
    const streamRef = ref(makeStream({ scrollTop: 100, scrollHeight: 3000, clientHeight: 600 }))
    const inputRef = ref(input)
    const c = useComposer({ draft: ref(''), inputRef, streamRef, onSubmit: () => {} })

    c.onComposerFocus()
    c.keepComposerVisible()
    await Promise.resolve()
    expect(streamRef.value!.scrollTop).toBe(100) // 停在原处，没被拽下去
  })
})
