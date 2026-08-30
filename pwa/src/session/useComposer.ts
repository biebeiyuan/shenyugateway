import { nextTick, type Ref } from 'vue'

// 输入框与滚动的手感：自动增高、软键盘弹出时把输入框抬起来而不是被顶飞、滚到底。
//
// 这块只碰自己的 DOM ref（输入框、消息流、以及输入框所在的 .composer-wrap），
// 和消息、会话、上游都没有关系——所以从 App.vue 搬出来是纯粹的收纳，实现逐字照搬，
// 一个数字都没改（那些延迟档位和 +8 的余量是在真机上试出来的）。

// 输入框最大高度，超过就内部滚动。
const MAX_INPUT_HEIGHT = 144

// 键盘动画期间视口尺寸连续变化，多打几拍比只测一次可靠。
const KEYBOARD_SETTLE_DELAYS = [0, 80, 180, 320, 520, 800]

export type ComposerDeps = {
  draft: Ref<string>
  inputRef: Ref<HTMLTextAreaElement | null>
  streamRef: Ref<HTMLElement | null>
  onSubmit: () => void
}

export function useComposer(deps: ComposerDeps) {
  const { draft, inputRef, streamRef, onSubmit } = deps
  let keyboardTimers: number[] = []

  function scrollToBottom() {
    nextTick(() => {
      if (streamRef.value) streamRef.value.scrollTop = streamRef.value.scrollHeight
    })
  }

  /**
   * 立刻贴底，不等 nextTick、不走动画。首屏定位用它：第一帧就要画在正确位置，
   * 中间过程不该被看到。
   */
  function jumpToBottom() {
    const stream = streamRef.value
    if (!stream) return
    stream.scrollTop = stream.scrollHeight
  }

  /** 视口是否已经贴着底部。补内容前先问它，别把正在往上翻的人拽回来。 */
  function atBottom(slack = 80): boolean {
    const stream = streamRef.value
    if (!stream) return true
    return stream.scrollHeight - stream.scrollTop - stream.clientHeight <= slack
  }

  function resizeInput() {
    const input = inputRef.value
    if (!input) return
    input.style.height = 'auto'
    input.style.height = `${Math.min(input.scrollHeight, MAX_INPUT_HEIGHT)}px`
    input.scrollTop = input.scrollHeight
  }

  function resetInputSize() {
    nextTick(() => {
      const input = inputRef.value
      if (!input) return
      input.style.height = 'auto'
      input.scrollTop = 0
    })
  }

  function updateDraft(event: Event) {
    draft.value = (event.target as HTMLTextAreaElement).value
    resizeInput()
  }

  function clearKeyboardTimers() {
    keyboardTimers.forEach((timer) => window.clearTimeout(timer))
    keyboardTimers = []
  }

  function keyboardViewportBottom(): number {
    const viewport = window.visualViewport
    return viewport ? viewport.offsetTop + viewport.height : window.innerHeight
  }

  // 随键盘移动的元素只许 translateY（`STYLE_AND_CRAFT.md` § 出生清单）：改布局属性
  // 会让整列消息重排。消息流同步补一段 padding，免得最后一条被抬起的输入框压住。
  function keepComposerVisible() {
    const input = inputRef.value
    const stream = streamRef.value
    const wrap = input?.closest<HTMLElement>('.composer-wrap')
    if (!input || !stream || !wrap) return
    if (document.activeElement !== input) {
      wrap.style.transform = ''
      stream.style.paddingBottom = ''
      return
    }
    wrap.style.transform = ''
    const lift = Math.max(0, Math.ceil(wrap.getBoundingClientRect().bottom - keyboardViewportBottom() + 8))
    wrap.style.transform = lift ? `translateY(${-lift}px)` : ''
    stream.style.paddingBottom = lift ? `calc(var(--space-6) + ${lift}px)` : ''
    scrollToBottom()
  }

  function scheduleComposerVisible() {
    clearKeyboardTimers()
    for (const delay of KEYBOARD_SETTLE_DELAYS) {
      keyboardTimers.push(window.setTimeout(keepComposerVisible, delay))
    }
    window.requestAnimationFrame(keepComposerVisible)
  }

  function handleComposerBlur() {
    clearKeyboardTimers()
    keyboardTimers.push(window.setTimeout(keepComposerVisible, 80))
  }

  function onComposerKeydown(event: KeyboardEvent) {
    if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) {
      event.preventDefault()
      onSubmit()
    }
  }

  return {
    scrollToBottom,
    jumpToBottom,
    atBottom,
    resizeInput,
    resetInputSize,
    updateDraft,
    clearKeyboardTimers,
    keepComposerVisible,
    scheduleComposerVisible,
    handleComposerBlur,
    onComposerKeydown,
  }
}
