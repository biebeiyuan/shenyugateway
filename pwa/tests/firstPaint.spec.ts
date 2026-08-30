import { describe, expect, it } from 'vitest'

// 首屏只画最后 20 条的窗口逻辑。index 必须是完整 messages 里的下标——重试、编辑、
// 变体切换都按它定位，用窗口内的相对下标会操作到错误的消息上。
// 这里复刻 App.vue 里 visibleMessages 的算法并断言这条不变量。
function windowOf<T>(all: T[], tail: number | null): { message: T; index: number }[] {
  if (tail === null || all.length <= tail) {
    return all.map((message, index) => ({ message, index }))
  }
  const start = all.length - tail
  return all.slice(start).map((message, offset) => ({ message, index: start + offset }))
}

describe('first-paint window', () => {
  const all = Array.from({ length: 240 }, (_, i) => `m${i}`)

  it('keeps only the newest slice on the first pass', () => {
    const shown = windowOf(all, 20)
    expect(shown).toHaveLength(20)
    expect(shown[0].message).toBe('m220')
    expect(shown[19].message).toBe('m239')
  })

  it('reports absolute indices so retry and edit hit the right message', () => {
    const shown = windowOf(all, 20)
    // 窗口第一条在完整数组里的下标是 220，不是 0
    expect(shown[0].index).toBe(220)
    expect(shown[19].index).toBe(239)
    for (const { message, index } of shown) {
      expect(all[index]).toBe(message)
    }
  })

  it('shows everything once the second pass lifts the cap', () => {
    const shown = windowOf(all, null)
    expect(shown).toHaveLength(240)
    expect(shown[0].index).toBe(0)
  })

  it('does not slice a conversation shorter than the window', () => {
    const short = ['a', 'b', 'c']
    const shown = windowOf(short, 20)
    expect(shown.map((entry) => entry.index)).toEqual([0, 1, 2])
  })

  it('handles an empty transcript', () => {
    expect(windowOf([], 20)).toEqual([])
  })
})
