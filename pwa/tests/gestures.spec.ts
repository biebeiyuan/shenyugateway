import { describe, expect, it } from 'vitest'
import {
  DOUBLE_TAP_SCALE,
  IDENTITY,
  MAX_SCALE,
  clampView,
  dismissProgress,
  doubleTapView,
  fittedSize,
  panBounds,
  scaleAround,
  swipeIntent,
} from '../src/viewer/gestures'

const container = { width: 390, height: 780 }
const wideImage = { width: 2000, height: 1000 }
const tallImage = { width: 1000, height: 3000 }

describe('fittedSize', () => {
  it('fits by the limiting axis', () => {
    // 宽图受宽度限制：390 宽 → 195 高
    expect(fittedSize(wideImage, container)).toEqual({ width: 390, height: 195 })
    // 长图受高度限制：780 高 → 260 宽
    expect(fittedSize(tallImage, container)).toEqual({ width: 260, height: 780 })
  })

  it('tolerates a not-yet-loaded image', () => {
    expect(fittedSize({ width: 0, height: 0 }, container)).toEqual({ width: 0, height: 0 })
  })
})

describe('panBounds', () => {
  it('locks the axis where the image is smaller than the container', () => {
    // 宽图未放大时高度只有 195，纵向不该能拖动
    expect(panBounds(wideImage, container, 1)).toEqual({ width: 0, height: 0 })
  })

  it('opens up as the scale grows', () => {
    const bounds = panBounds(wideImage, container, 2)
    expect(bounds.width).toBe(195)
    expect(bounds.height).toBe(0)
  })
})

describe('clampView', () => {
  it('never lets the image be dragged out of view', () => {
    const dragged = clampView({ scale: 2, x: 9999, y: 9999 }, wideImage, container)
    const bounds = panBounds(wideImage, container, 2)
    expect(dragged.x).toBe(bounds.width)
    expect(dragged.y).toBe(bounds.height)
  })

  it('clamps the scale into range', () => {
    expect(clampView({ scale: 99, x: 0, y: 0 }, wideImage, container).scale).toBe(MAX_SCALE)
    expect(clampView({ scale: 0.1, x: 0, y: 0 }, wideImage, container).scale).toBe(1)
  })

  it('recenters when zooming back out', () => {
    const zoomedOut = clampView({ scale: 1, x: 150, y: 40 }, wideImage, container)
    expect(zoomedOut).toEqual({ scale: 1, x: 0, y: 0 })
  })
})

describe('scaleAround', () => {
  it('keeps the anchor point visually fixed', () => {
    const origin = { x: 100, y: 0 }
    const zoomed = scaleAround(IDENTITY, 2, origin, wideImage, container)
    // 锚点在图上的位置不动：(origin - x) / scale 应当守恒
    const beforeOnImage = (origin.x - IDENTITY.x) / IDENTITY.scale
    const afterOnImage = (origin.x - zoomed.x) / zoomed.scale
    expect(afterOnImage).toBeCloseTo(beforeOnImage, 5)
  })
})

describe('doubleTapView', () => {
  it('zooms in from rest and resets when already zoomed', () => {
    const zoomed = doubleTapView(IDENTITY, { x: 0, y: 0 }, wideImage, container)
    expect(zoomed.scale).toBe(DOUBLE_TAP_SCALE)
    expect(doubleTapView(zoomed, { x: 0, y: 0 }, wideImage, container)).toEqual(IDENTITY)
  })
})

describe('swipeIntent', () => {
  it('separates horizontal paging from downward dismiss by main axis', () => {
    expect(swipeIntent(-200, 10, container)).toBe('next')
    expect(swipeIntent(200, 10, container)).toBe('prev')
    expect(swipeIntent(10, 200, container)).toBe('dismiss')
  })

  it('ignores small drags', () => {
    expect(swipeIntent(20, 5, container)).toBe('none')
    expect(swipeIntent(5, 20, container)).toBe('none')
  })

  it('does nothing on an upward drag', () => {
    // 上拖多半是系统手势区，抢它会让人误退出。
    expect(swipeIntent(0, -300, container)).toBe('none')
  })

  it('prefers the dominant axis on a diagonal drag', () => {
    expect(swipeIntent(-200, 150, container)).toBe('next')
    expect(swipeIntent(-60, 300, container)).toBe('dismiss')
  })
})

describe('dismissProgress', () => {
  it('grows with the drag and saturates at 1', () => {
    expect(dismissProgress(0, container)).toBe(0)
    expect(dismissProgress(-50, container)).toBe(0)
    expect(dismissProgress(156, container)).toBeCloseTo(0.5, 2)
    expect(dismissProgress(9999, container)).toBe(1)
  })
})
