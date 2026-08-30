import { describe, expect, it } from 'vitest'
import {
  PEAK_RATIO,
  STACK_DEFAULTS,
  dragProgress,
  peekQuota,
  restingStates,
  scrubStates,
  shouldTurn,
  smoothVelocity,
} from '../src/viewer/photoStack'

// 这些断言守的是上游逐帧测量出来的规则（PhotoStack by Wren036）。
// 数字改了就说明摆位偏离了原版，不要靠手感调。

describe('peekQuota', () => {
  it('keeps three cards visible by moving the quota at the edges', () => {
    // 中间：左右各一张探边
    expect(peekQuota(3, 7)).toEqual([1, 1])
    // 第一张：左边没有了，配额转到右侧
    expect(peekQuota(0, 7)).toEqual([0, 2])
    // 最后一张：反过来
    expect(peekQuota(6, 7)).toEqual([2, 0])
  })

  it('degrades gracefully for tiny stacks', () => {
    expect(peekQuota(0, 1)).toEqual([0, 0])
    expect(peekQuota(0, 2)).toEqual([0, 1])
    expect(peekQuota(1, 2)).toEqual([1, 0])
  })
})

describe('restingStates', () => {
  const states = restingStates(6, 2)

  it('puts the current card upright and on top', () => {
    expect(states[2]).toMatchObject({ x: 0, rotate: 0, scale: 1, zIndex: 100, opacity: 1 })
  })

  it('offsets, rotates and shrinks each peeking layer', () => {
    expect(states[3].x).toBe(STACK_DEFAULTS.peek)
    expect(states[3].rotate).toBeCloseTo(STACK_DEFAULTS.rotStep, 5)
    expect(states[3].scale).toBeCloseTo(1 - STACK_DEFAULTS.scaleStep, 5)
    expect(states[1].x).toBe(-STACK_DEFAULTS.peek)
    expect(states[1].rotate).toBeCloseTo(-STACK_DEFAULTS.rotStep, 5)
  })

  it('hides everything past the peek quota', () => {
    // 恒定三层可见：当前 + 左一 + 右一
    const visible = states.filter((state) => state.opacity > 0)
    expect(visible).toHaveLength(3)
  })

  it('still shows three at the first card by borrowing to the right', () => {
    const edge = restingStates(6, 0)
    expect(edge.filter((state) => state.opacity > 0)).toHaveLength(3)
    expect(edge[2].opacity).toBe(1)
  })
})

describe('scrubStates', () => {
  const total = 6
  const current = 2
  const stage = 142

  it('follows the finger out to the peak in the first half', () => {
    const half = scrubStates(total, current, -1, 0.5, stage)
    expect(half[current].x).toBeCloseTo(-stage * PEAK_RATIO, 5)
    expect(half[current].scale).toBe(1)
  })

  it('returns along the trajectory in the second half instead of tracking the finger', () => {
    const peak = scrubStates(total, current, -1, 0.5, stage)[current].x
    const later = scrubStates(total, current, -1, 0.9, stage)[current].x
    // 位移绝对值必须回落，而不是继续跟手增大
    expect(Math.abs(later)).toBeLessThan(Math.abs(peak))
  })

  it('sinks the top card below the rising one after the peak', () => {
    expect(scrubStates(total, current, -1, 0.4, stage)[current].zIndex).toBe(110)
    expect(scrubStates(total, current, -1, 0.6, stage)[current].zIndex).toBe(102)
  })

  it('lands exactly on the resting layout at p=1 so settling is a no-op', () => {
    const scrubbed = scrubStates(total, current, -1, 1, stage)
    const settled = restingStates(total, current + 1)
    // 上游的「结算零跳变」：擦洗 p=1 与翻页后静止态在数学上相等
    expect(scrubbed[current].x).toBeCloseTo(settled[current].x, 4)
    expect(scrubbed[current].scale).toBeCloseTo(settled[current].scale, 4)
    expect(scrubbed[current - 1 + 1].x).toBeCloseTo(settled[current + 1 - 1 + 1 - 1].x, 4)
  })

  // 上游 README 说「任意时刻可见卡不超过三张」，那是观感描述而非字面不变量：
  // 行程中段退场与进场同时在渐变（0.22 / 0.78），实体感只有两张半。这里断言的是
  // 「完全实体的卡不超过三张」，并用上游原码在同一帧核对过数值一致。
  it('keeps three solid cards at the ends and two mid-flight', () => {
    // 上游原话：「任意时刻可见卡不超过三张，行程中段实际仅两张在场」——中段是
    // 退场与进场同时渐变，所以实体只有两张，加上两张半透明共四个非零。
    const solid = (p: number) => scrubStates(total, current, -1, p, stage).filter((s) => s.opacity > 0.99).length
    expect(solid(0)).toBe(3)
    expect(solid(0.5)).toBe(3)
    expect(solid(1)).toBe(3)
    expect(solid(0.75)).toBe(2)
  })

  it('matches upstream opacities at the mid-flight frame', () => {
    // 上游原码在 cur=2、dir=-1、p=0.75 下算出 1:0.225 2:1 3:1 4:0.775
    const states = scrubStates(total, current, -1, 0.75, stage)
    expect(states[1].opacity).toBeCloseTo(0.225, 3)
    expect(states[4].opacity).toBeCloseTo(0.775, 3)
  })

  it('limits travel at the edges and nudges the layers below', () => {
    const first = scrubStates(total, 0, 1, 1, stage)
    expect(Math.abs(first[0].x)).toBeLessThanOrEqual(24)
    // 下层探边有轻微联动位移
    expect(first[1].x).toBeGreaterThan(STACK_DEFAULTS.peek)
  })
})

describe('shouldTurn', () => {
  it('turns on a slow drag past halfway', () => {
    expect(shouldTurn(-100, 0.6, 0, 2, 6)).toBe(true)
    expect(shouldTurn(-100, 0.4, 0, 2, 6)).toBe(false)
  })

  it('turns on a fling even when the drag is short', () => {
    expect(shouldTurn(-20, 0.1, -0.8, 2, 6)).toBe(true)
  })

  it('ignores a fling whose direction disagrees with the drag', () => {
    expect(shouldTurn(-20, 0.1, 0.8, 2, 6)).toBe(false)
  })

  it('ignores a tap-sized jitter', () => {
    expect(shouldTurn(-2, 0.01, -2, 2, 6)).toBe(false)
  })

  it('refuses to turn past either end', () => {
    expect(shouldTurn(-200, 0.9, -1, 5, 6)).toBe(false)
    expect(shouldTurn(200, 0.9, 1, 0, 6)).toBe(false)
  })
})

describe('dragProgress and smoothVelocity', () => {
  it('shares one travel denominator so both directions feel the same', () => {
    expect(dragProgress(-120, 240)).toBeCloseTo(0.5, 5)
    expect(dragProgress(120, 240)).toBeCloseTo(0.5, 5)
  })

  it('has a travel floor so a narrow start does not make it hair-trigger', () => {
    expect(dragProgress(60, 10)).toBeCloseTo(0.5, 5)
  })

  it('smooths velocity so one jittery frame cannot trigger a fling', () => {
    expect(smoothVelocity(0, 10, 10)).toBeCloseTo(0.7, 5)
    expect(smoothVelocity(1, 0, 0)).toBe(1)
  })
})
