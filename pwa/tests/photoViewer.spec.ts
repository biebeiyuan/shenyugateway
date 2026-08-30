import { describe, expect, it, vi } from 'vitest'
import { createApp, h, nextTick, ref } from 'vue'
import PhotoViewer from '../src/components/PhotoViewer.vue'

function mount(props: Record<string, unknown>, handlers: Record<string, unknown> = {}) {
  const host = document.createElement('div')
  document.body.appendChild(host)
  const app = createApp({ setup: () => () => h(PhotoViewer, { ...props, ...handlers }) })
  app.config.errorHandler = () => {}
  app.mount(host)
  return { host, app }
}

const urls = ['data:image/jpeg;base64,AAA', 'data:image/jpeg;base64,BBB', 'data:image/jpeg;base64,CCC']

describe('PhotoViewer', () => {
  it('shows the requested photo and a counter', async () => {
    const { host } = mount({ urls, index: 1 })
    await nextTick()
    expect(host.querySelector('img')?.getAttribute('src')).toBe(urls[1])
    expect(host.textContent).toContain('2 / 3')
  })

  it('omits the counter for a single photo', async () => {
    const { host } = mount({ urls: [urls[0]], index: 0 })
    await nextTick()
    expect(host.textContent).not.toContain('1 / 1')
  })

  it('shows the caption when one is given', async () => {
    const { host } = mount({ urls, index: 0, captions: ['沈予写的那句话'] })
    await nextTick()
    expect(host.textContent).toContain('沈予写的那句话')
  })

  it('closes on the close button and on Escape', async () => {
    const close = vi.fn()
    const { host } = mount({ urls, index: 0 }, { onClose: close })
    await nextTick()
    ;(host.querySelector('.photo-viewer-close') as HTMLElement).click()
    expect(close).toHaveBeenCalled()

    close.mockClear()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))
    expect(close).toHaveBeenCalled()
  })

  // 翻页现在带落位动画（PhotoStack 那条缓动），所以换图和 change 事件发生在动画
  // 结束时，不是按键那一刻——干巴巴的硬切就是圆圆说的手感问题。
  it('pages with the arrow keys and reports the change after settling', async () => {
    const change = vi.fn()
    const { host } = mount({ urls, index: 0 }, { onChange: change })
    await nextTick()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))

    // 动画期间图先滑出，还没换。
    await new Promise((resolve) => setTimeout(resolve, 40))
    await nextTick()
    expect(host.querySelector('.photo-viewer-image')?.getAttribute('style')).toContain('translate3d(-')

    await new Promise((resolve) => setTimeout(resolve, 420))
    await nextTick()
    expect(change).toHaveBeenCalledWith(1)
    expect(host.querySelector('img')?.getAttribute('src')).toBe(urls[1])
  })

  it('does not treat the end of a pinch as a tap', async () => {
    // 圆圆报的：放大后捏回原大小、手指离开，看图器直接关了——最后那根手指几乎没
    // 位移，被判成轻点，而缩放已回到 1 所以 zoomed 是 false。
    const close = vi.fn()
    const { host } = mount({ urls, index: 0 }, { onClose: close })
    await nextTick()
    const stage = host.querySelector('.photo-viewer-stage') as HTMLElement
    const fire = (type: string, id: number, x: number) =>
      stage.dispatchEvent(new PointerEvent(type, { pointerId: id, clientX: x, clientY: 400, bubbles: true }))

    fire('pointerdown', 1, 100)
    fire('pointerdown', 2, 200)
    fire('pointermove', 1, 50)
    fire('pointermove', 2, 250)
    fire('pointermove', 1, 100)
    fire('pointermove', 2, 200)
    fire('pointerup', 1, 100)
    fire('pointerup', 2, 200)
    await new Promise((resolve) => setTimeout(resolve, 360))
    expect(close).not.toHaveBeenCalled()
  })

  it('does not page past either end', async () => {
    const change = vi.fn()
    mount({ urls, index: 0 }, { onChange: change })
    await nextTick()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowLeft' }))
    expect(change).not.toHaveBeenCalled()
  })

  // 看图器自己要处理双击放大和双指捏合，页面缩放会跟它打架；但聊天页面本身不禁
  // 缩放（那是无障碍功能），所以必须关闭时还回去。
  it('locks page zoom only while open', async () => {
    const meta = document.createElement('meta')
    meta.setAttribute('name', 'viewport')
    const original = 'width=device-width, initial-scale=1, viewport-fit=cover'
    meta.setAttribute('content', original)
    document.head.appendChild(meta)

    const { app } = mount({ urls, index: 0 })
    await nextTick()
    expect(meta.getAttribute('content')).toContain('user-scalable=no')

    app.unmount()
    await nextTick()
    expect(meta.getAttribute('content')).toBe(original)
    meta.remove()
  })
})
