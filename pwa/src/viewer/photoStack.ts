/*!
 * 合并照片卡的摆位数学。
 *
 * 移植自 PhotoStack by Wren036 —— https://github.com/Wren036/PhotoStack
 * Required Notice: PhotoStack by Wren036 (https://github.com/Wren036/PhotoStack)
 * License: PolyForm Noncommercial 1.0.0（个人非商用免费；商用需作者书面授权）
 *
 * 全部设计参数（探边距离、每层旋转、缩放递减、快甩阈值、三层守恒、峰形轨迹）
 * 由原作者对微信原版逐帧观察测量得出。**照抄数字，不要凭手感重调。**
 *
 * 与上游的差别：上游直接写 DOM style，这里只算出每张卡的 transform 状态，渲染交给
 * Vue。所以是同一套数学、不同的落地方式。
 */

export type StackOptions = {
  peek: number
  peekStep: number
  rotStep: number
  scaleStep: number
  flingVel: number
}

export const STACK_DEFAULTS: StackOptions = {
  peek: 15,
  peekStep: 12,
  rotStep: 2.2,
  scaleStep: 0.08,
  flingVel: 0.4,
}

// 峰值位移 ≈ 卡宽 × 0.52（上游测量值）
export const PEAK_RATIO = 0.52
// 快甩的防误触位移下限（进度），约 10px
export const FLING_MIN_PROGRESS = 0.04
// 边界弹性区间
export const EDGE_TRAVEL = 24

export type CardState = {
  x: number
  rotate: number
  scale: number
  zIndex: number
  opacity: number
}

/**
 * 可见探边配额：常态左右各一张，位于边界时配额转移到另一侧——保持恒为三层可见。
 */
export function peekQuota(current: number, total: number): [number, number] {
  const left = current
  const right = total - 1 - current
  let L = Math.min(left, 1)
  let R = Math.min(right, 1)
  if (L + R < 2) {
    L = Math.min(left, 2 - R)
    R = Math.min(right, 2 - L)
  }
  return [L, R]
}

/**
 * 静止摆位。拖拽的每一帧也先跑它当复位底座，杜绝中间态残留累积。
 */
export function restingStates(total: number, current: number, options = STACK_DEFAULTS): CardState[] {
  const [L, R] = peekQuota(current, total)
  const states: CardState[] = []
  for (let index = 0; index < total; index++) {
    if (index < current) {
      const depth = current - index
      states.push({
        x: -options.peek - (depth - 1) * options.peekStep,
        rotate: -options.rotStep * depth,
        scale: 1 - options.scaleStep * depth,
        zIndex: 40 - depth,
        opacity: depth > L ? 0 : 1,
      })
    } else if (index === current) {
      states.push({ x: 0, rotate: 0, scale: 1, zIndex: 100, opacity: 1 })
    } else {
      const depth = index - current
      states.push({
        x: options.peek + (depth - 1) * options.peekStep,
        rotate: options.rotStep * depth,
        scale: 1 - options.scaleStep * depth,
        zIndex: 100 - depth,
        opacity: depth > R ? 0 : 1,
      })
    }
  }
  return states
}

/** 手指进度：起点到屏幕边的行程做分母，两个方向共用，保证阻力一致。 */
export function dragProgress(dx: number, travel: number): number {
  return Math.min(1, Math.abs(dx) / Math.max(120, travel || 240))
}

/**
 * 擦洗帧：手指位置就是翻页动画的进度条。
 *
 * 前半程顶卡跟手滑出到峰值；后半程沿轨迹自行回归——缩小、微旋、落进对侧探边位，
 * **不跟随手指反向**。任意时刻松手都是合法状态。
 */
export function scrubStates(
  total: number,
  current: number,
  direction: -1 | 1,
  progress: number,
  stageWidth: number,
  options = STACK_DEFAULTS,
): CardState[] {
  const states = restingStates(total, current, options)
  const maxX = stageWidth * PEAK_RATIO
  const atEdge = (direction < 0 && current >= total - 1) || (direction > 0 && current <= 0)

  if (atEdge) {
    // 边界弹性预览：首张可继续右滑、末张可继续左滑，行程限制在弹性区间内，
    // 下层探边轻微联动——模拟拽动一叠实体照片顶张时下层被带动。
    states[current] = {
      ...states[current],
      x: direction * EDGE_TRAVEL * progress,
      rotate: direction * 2.5 * progress,
      zIndex: 110,
    }
    const first = states[current + direction]
    if (first) {
      first.x = direction * (options.peek + 8 * progress)
      first.rotate = direction * options.rotStep
      first.scale = 1 - options.scaleStep
    }
    const second = states[current + direction * 2]
    if (second) {
      second.x = direction * (options.peek + options.peekStep + 5 * progress)
      second.rotate = direction * options.rotStep * 2
      second.scale = 1 - options.scaleStep * 2
    }
    return states
  }

  // 顶卡：峰形轨迹（滑出 → 峰值 → 回落至对侧探边位）
  let x: number
  let rotate: number
  let scale: number
  if (progress <= 0.5) {
    const q = progress / 0.5
    x = direction * maxX * q
    rotate = direction * 8 * q
    scale = 1
  } else {
    const q = (progress - 0.5) / 0.5
    x = direction * (maxX - (maxX - options.peek) * q)
    rotate = direction * (8 - (8 - options.rotStep) * q)
    scale = 1 - options.scaleStep * q
  }
  states[current] = { x, rotate, scale, zIndex: progress < 0.5 ? 110 : 102, opacity: 1 }

  // 新顶：从对侧探边位插值升顶
  const rising = states[current - direction]
  if (rising) {
    rising.x = -direction * options.peek * (1 - progress)
    rising.rotate = -direction * options.rotStep * (1 - progress)
    rising.scale = 1 - options.scaleStep + options.scaleStep * progress
    rising.opacity = 1
    rising.zIndex = 105
  }

  // 舞台转盘·进场：顶卡到达峰值前新探边不出场；后半程自升顶卡背后沿其边缘滑出，
  // 透明度约 0.55→1、尺寸由小变大（近大远小）。
  const qq = Math.max(0, (progress - 0.5) / 0.5)
  const entering = states[current - direction * 2]
  if (entering) {
    const [Lb, Rb] = peekQuota(current, total)
    if (direction < 0 ? 2 <= Rb : 2 <= Lb) {
      // 边界借位：这张本来就是可见的第二层探边，不参与进场编排，
      // 与升顶卡同步全程走位，保持实体。
      entering.x = -direction * (options.peek + options.peekStep * (1 - progress))
      entering.rotate = -direction * (options.rotStep * 2 - options.rotStep * progress)
      entering.scale = 1 - options.scaleStep * 2 + options.scaleStep * progress
      entering.opacity = 1
    } else {
      const risingX = -direction * options.peek * (1 - progress)
      entering.x = risingX * (1 - qq) + (-direction * options.peek) * qq
      entering.rotate = -direction * (options.rotStep * 2 - options.rotStep * qq)
      entering.scale = 1 - options.scaleStep * 2.5 + options.scaleStep * 1.5 * qq
      entering.opacity = Math.min(1, qq / 0.18) * 0.55 + 0.45 * qq
    }
    entering.zIndex = direction < 0 ? 98 : 38
  }

  // 边界例外：结算后仍属可见集合的旧探边不执行退场，而是提前插值走位到降级后的
  // 外层探边位——顶卡落位时它已就位，无突现无消失。
  const leaving = states[current + direction]
  if (leaving) {
    const nextCurrent = direction < 0 ? Math.min(current + 1, total - 1) : Math.max(current - 1, 0)
    const [L2, R2] = peekQuota(nextCurrent, total)
    const leavingIndex = current + direction
    const stays = leavingIndex < nextCurrent
      ? nextCurrent - leavingIndex <= L2
      : leavingIndex - nextCurrent <= R2
    if (stays) {
      leaving.x = direction * (options.peek + options.peekStep * progress)
      leaving.rotate = direction * (options.rotStep + options.rotStep * progress)
      leaving.scale = 1 - options.scaleStep - options.scaleStep * progress
    } else {
      // 舞台转盘·退场（进场的时间反演）：前半程静止维持三张可见，后半程向回落
      // 顶卡背后收拢，顶卡落位时恰好将其完全遮蔽。
      const eq = 1 - (1 - qq) * (1 - qq)
      leaving.x = direction * options.peek * (1 - eq) + x * eq
      leaving.rotate = direction * options.rotStep
      leaving.scale = 1 - options.scaleStep - options.scaleStep * 1.5 * qq
      leaving.opacity = 1 - (Math.min(1, qq / 0.18) * 0.55 + 0.45 * qq)
    }
  }

  return states
}

/**
 * 松手判定：慢拖过半，或快甩（速度过阈值且方向一致，位移有防误触下限）。
 */
export function shouldTurn(
  dx: number,
  progress: number,
  velocity: number,
  current: number,
  total: number,
  options = STACK_DEFAULTS,
): boolean {
  const direction = dx < 0 ? -1 : 1
  const canTurn = direction < 0 ? current < total - 1 : current > 0
  if (!canTurn) return false
  const fling =
    Math.abs(velocity) > options.flingVel &&
    Math.sign(velocity) === Math.sign(dx) &&
    progress > FLING_MIN_PROGRESS
  return progress > 0.5 || fling
}

/** 释放速度用指数平滑，避免单帧抖动误触发快甩。 */
export function smoothVelocity(previous: number, dx: number, dt: number): number {
  if (dt <= 0) return previous
  return 0.7 * (dx / dt) + 0.3 * previous
}
