import { describe, expect, it } from 'vitest'
import { clampErrorText, gatewayErrorMessage } from '../src/api/errors'

// 2026-08-29 线上现场：502 时 Cloudflare 返回整张 HTML 错误页，PWA 把它整篇
// 当成一句错误话渲染，顶飞了对话和输入框，还跟着 error 落盘每次重开复发。
const CLOUDFLARE_502 = `<!DOCTYPE html>
<!--[if lt IE 7]> <html class="no-js ie6 oldie" lang="en-US"> <![endif]-->
<html class="no-js" lang="en-US"><head>
<title>yuanuwuclaude.uk | 502: Bad gateway</title>
<meta charset="UTF-8" />
<link rel="stylesheet" id="cf_styles-css" href="/cdn-cgi/styles/main.css" />
</head><body><div id="cf-wrapper"><h1><span>Bad gateway</span>
<span class="code-label">Error code 502</span></h1>
<div class="mt-3">2026-08-25 16:03:14 UTC</div></body></html>`

describe('gatewayErrorMessage', () => {
  it('never carries an HTML error page into the message', () => {
    const message = gatewayErrorMessage(502, CLOUDFLARE_502)
    expect(message).toBe('网关暂时没应答（502），过一会儿再试。')
    expect(message).not.toContain('<')
    expect(message).not.toContain('DOCTYPE')
    expect(message.length).toBeLessThan(60)
  })

  it('keeps the FastAPI detail our own gateway returns', () => {
    expect(gatewayErrorMessage(400, JSON.stringify({ detail: '连接上游超时 https://upstream/v1' })))
      .toBe('连接上游超时 https://upstream/v1')
  })

  it('reaches a nested upstream error message', () => {
    const body = JSON.stringify({ detail: { error: { type: 'overloaded_error', message: 'Overloaded' } } })
    expect(gatewayErrorMessage(529, body)).toBe('Overloaded')
  })

  it('falls back to a status sentence when the body is empty', () => {
    expect(gatewayErrorMessage(401, '')).toContain('令牌')
    expect(gatewayErrorMessage(429, '   ')).toContain('限流')
    expect(gatewayErrorMessage(418, '')).toBe('网关返回 418。')
  })

  it('truncates a long plain-text body instead of passing it through', () => {
    const message = gatewayErrorMessage(500, 'x'.repeat(5000))
    expect(message.length).toBeLessThanOrEqual(301)
    expect(message.endsWith('…')).toBe(true)
  })

  it('collapses newlines so one error cannot become many lines', () => {
    expect(gatewayErrorMessage(500, 'first line\n\n\nsecond line')).toBe('first line second line')
  })

  it('refuses HTML that arrived inside a JSON string field', () => {
    const body = JSON.stringify({ detail: CLOUDFLARE_502 })
    expect(gatewayErrorMessage(502, body)).toBe('网关暂时没应答（502），过一会儿再试。')
  })
})

describe('clampErrorText', () => {
  it('bounds whatever is already stored', () => {
    expect(clampErrorText('y'.repeat(4000)).length).toBeLessThanOrEqual(301)
  })

  it('leaves a normal message untouched', () => {
    expect(clampErrorText('请求没有完成')).toBe('请求没有完成')
  })

  it('tolerates empty input', () => {
    expect(clampErrorText('')).toBe('')
  })
})
