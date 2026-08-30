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

  it('pages with the arrow keys and reports the change', async () => {
    const change = vi.fn()
    const { host } = mount({ urls, index: 0 }, { onChange: change })
    await nextTick()
    window.dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight' }))
    await nextTick()
    expect(change).toHaveBeenCalledWith(1)
    expect(host.querySelector('img')?.getAttribute('src')).toBe(urls[1])
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
