// 看图器的手势数学。
//
// 刻意做成纯函数：手势的难点是「缩放后还能不能拖到图外面」「双击该放大到哪」这类
// 边界算术，那些用真机试是最慢的验证方式。这里只算数，DOM 与事件在组件里。

export type Rect = { width: number; height: number }

export type ViewState = {
  scale: number
  x: number
  y: number
}

export const MIN_SCALE = 1
export const MAX_SCALE = 4
// 双击放大到这一档；再双击回到 1。比 MAX 小一点，留手动放大的余量。
export const DOUBLE_TAP_SCALE = 2.5

export const IDENTITY: ViewState = { scale: 1, x: 0, y: 0 }

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value))
}

/**
 * 图片以 contain 方式放进容器后的显示尺寸。平移边界要按这个算，而不是容器尺寸——
 * 否则一张长图在短边方向会被允许拖出视野。
 */
export function fittedSize(image: Rect, container: Rect): Rect {
  if (!image.width || !image.height) return { width: 0, height: 0 }
  const ratio = Math.min(container.width / image.width, container.height / image.height)
  return { width: image.width * ratio, height: image.height * ratio }
}

/**
 * 当前缩放下允许的平移半径。图比容器小的那个方向锁死为 0（居中），
 * 大的方向允许拖到刚好露出边缘为止。
 */
export function panBounds(image: Rect, container: Rect, scale: number): Rect {
  const fitted = fittedSize(image, container)
  return {
    width: Math.max(0, (fitted.width * scale - container.width) / 2),
    height: Math.max(0, (fitted.height * scale - container.height) / 2),
  }
}

/** 把一个视图状态收进合法范围：缩放夹到区间内，平移夹到边界内。 */
export function clampView(view: ViewState, image: Rect, container: Rect): ViewState {
  const scale = clamp(view.scale, MIN_SCALE, MAX_SCALE)
  const bounds = panBounds(image, container, scale)
  return {
    scale,
    x: clamp(view.x, -bounds.width, bounds.width),
    y: clamp(view.y, -bounds.height, bounds.height),
  }
}

/**
 * 以某一点为锚缩放：那一点在屏幕上的位置保持不动，符合捏合的直觉。
 * `origin` 是相对容器中心的坐标。
 */
export function scaleAround(
  view: ViewState,
  nextScale: number,
  origin: { x: number; y: number },
  image: Rect,
  container: Rect,
): ViewState {
  const scale = clamp(nextScale, MIN_SCALE, MAX_SCALE)
  const factor = scale / view.scale
  return clampView(
    {
      scale,
      x: origin.x - (origin.x - view.x) * factor,
      y: origin.y - (origin.y - view.y) * factor,
    },
    image,
    container,
  )
}

/** 双击：没放大就放大到锚点，已放大就回到原状。 */
export function doubleTapView(
  view: ViewState,
  origin: { x: number; y: number },
  image: Rect,
  container: Rect,
): ViewState {
  if (view.scale > MIN_SCALE + 0.01) return { ...IDENTITY }
  return scaleAround(view, DOUBLE_TAP_SCALE, origin, image, container)
}

export type SwipeIntent = 'prev' | 'next' | 'dismiss' | 'none'

/**
 * 未放大时一次拖拽的意图。
 *
 * 横向切图、下拖关闭，两者按主轴区分——否则斜着拖会同时触发。上拖不做事：
 * 上拖在手机上通常是系统手势区，抢它会让人误退出。
 */
export function swipeIntent(dx: number, dy: number, container: Rect): SwipeIntent {
  const horizontal = Math.abs(dx)
  const vertical = Math.abs(dy)
  // 阈值按容器取，小屏不至于要拖很远。
  const horizontalThreshold = Math.max(48, container.width * 0.18)
  const verticalThreshold = Math.max(72, container.height * 0.16)
  if (horizontal > vertical) {
    if (horizontal < horizontalThreshold) return 'none'
    return dx < 0 ? 'next' : 'prev'
  }
  if (dy > verticalThreshold) return 'dismiss'
  return 'none'
}

/** 下拖关闭时的背景透明度：拖得越远越透，给出「正在关」的反馈。 */
export function dismissProgress(dy: number, container: Rect): number {
  if (dy <= 0) return 0
  const travel = Math.max(1, container.height * 0.4)
  return clamp(dy / travel, 0, 1)
}

/**
 * 翻页时的横向位移：手指走多远图就跟多远，到边界时阻力递增（橡皮筋）。
 *
 * 借 PhotoStack 的边界弹性思路：能翻的方向跟手 1:1，翻不动的方向只给一小段带
 * 阻尼的行程，让"到头了"这件事被手感告知而不是靠猜。
 */
export function pageOffset(dx: number, canGo: boolean, container: Rect): number {
  if (canGo) return dx
  const limit = Math.max(24, container.width * 0.08)
  // 阻尼：位移越大增量越小，渐近到 limit。
  return Math.sign(dx) * limit * (1 - 1 / (1 + Math.abs(dx) / limit))
}

/** 翻页落位动画的时长：剩下的行程越长走得越久，和 PhotoStack 的完成动画同构。 */
export function settleDuration(remaining: number, container: Rect): number {
  const ratio = clamp(remaining / Math.max(1, container.width), 0, 1)
  return Math.round(160 + ratio * 180)
}

/** 两指之间的距离，用于捏合缩放。 */
export function pinchDistance(a: { x: number; y: number }, b: { x: number; y: number }): number {
  return Math.hypot(a.x - b.x, a.y - b.y)
}
