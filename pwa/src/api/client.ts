import type { UiMessage } from '../types'
import { joinEcho } from '../echo'
import { parsePwaBuildInfo, type PwaBuildInfo } from '../buildInfo'
import { gatewayErrorMessage } from './errors'

// Thin gateway HTTP layer. Every request carries the PWA client identity
// headers; interpretation of payload fields stays with the caller.

export type RequestContext = {
  gatewayUrl: string
  authToken: string
  sessionTag: string
}

export function apiUrl(ctx: RequestContext, path: string): string {
  const base = ctx.gatewayUrl.trim().replace(/\/$/, '')
  return `${base}${path}`
}

function authHeader(ctx: RequestContext): Record<string, string> {
  return ctx.authToken.trim() ? { Authorization: `Bearer ${ctx.authToken.trim()}` } : {}
}

export function requestHeaders(ctx: RequestContext): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Shenyu-Client': 'shenyu-pwa',
    'X-Shenyu-Tool-Events': 'true',
    'X-Shenyu-Tool-Details': 'true',
    'X-Shenyu-Session-Tag': ctx.sessionTag,
  }
  return { ...headers, ...authHeader(ctx) }
}

// 过期图的线上形状。网关的两个图片块判别器都认它是图片块，所以历史归一化会
// 跳过它，与「这里原本是一张图」完全等价——分支检测看不见，prompt cache epoch
// 不会被重置（`context_window.py` § 分支检测）。fingerprint 是图片字节的
// sha256，网关据此认出这张图是不是沈予存进相册的那张。
//
// 刻意不复用网关自己的 `shenyu_history_image`：那个标记的 fingerprint 是 JSON
// 块的哈希，与相册的字节哈希不是一回事，同名会把两者悄悄混为一谈。
export const EXPIRED_IMAGE_MARKER = 'shenyu_expired_image'

function expiredImageBlock(fingerprint: string): Record<string, unknown> {
  return { type: 'image', source: { type: EXPIRED_IMAGE_MARKER, fingerprint } }
}

export function wireContent(message: UiMessage): string | Array<Record<string, unknown>> {
  const content = message.role === 'assistant' ? joinEcho(message.content, message.echo || '') : message.content
  if (!message.attachments.length) return content
  const blocks: Array<Record<string, unknown>> = []
  if (content.trim()) blocks.push({ type: 'text', text: content })
  for (const attachment of message.attachments) {
    if (attachment.dataUrl) {
      blocks.push({ type: 'image_url', image_url: { url: attachment.dataUrl } })
    } else if (attachment.fingerprint) {
      // 本机已淘汰这张图：送指纹，不送字节。10 张图的会话实测从 3.82MB/请求
      // 降到约 800KB，而网关本来也只把最近两轮的图转给上游。
      blocks.push(expiredImageBlock(attachment.fingerprint))
    }
  }
  // 图全过期又没有指纹时，别退化成 [] —— 那会丢掉这一轮的文字。
  if (!blocks.length) return content
  return blocks
}

export function wireMessages(source: UiMessage[]) {
  return source.map((message) => ({
    role: message.role,
    content: wireContent(message),
  }))
}

export async function fetchRuntimeConfig(ctx: RequestContext): Promise<Record<string, unknown>> {
  const response = await fetch(apiUrl(ctx, '/api/config'), { headers: requestHeaders(ctx) })
  if (!response.ok) throw new Error('config unavailable')
  return await response.json()
}

export async function fetchDeployedPwaBuildInfo(ctx: RequestContext): Promise<PwaBuildInfo> {
  const response = await fetch(apiUrl(ctx, '/chat/build-info.json'), {
    headers: authHeader(ctx),
    cache: 'no-store',
  })
  if (!response.ok) throw new Error(`线上版本暂时拿不到（${response.status}）`)
  const buildInfo = parsePwaBuildInfo(await response.json())
  if (!buildInfo) throw new Error('线上版本文件格式不正确')
  return buildInfo
}

export async function fetchModels(ctx: RequestContext): Promise<Record<string, unknown>> {
  const response = await fetch(apiUrl(ctx, '/v1/models'), { headers: requestHeaders(ctx) })
  if (!response.ok) throw new Error('模型列表暂时拿不到')
  return await response.json()
}

export async function fetchSessions(ctx: RequestContext, limit: number): Promise<Record<string, unknown>> {
  const response = await fetch(apiUrl(ctx, `/api/gateway/sessions?limit=${limit}`), { headers: requestHeaders(ctx) })
  if (!response.ok) throw new Error('session list unavailable')
  return await response.json()
}

export async function fetchSessionDetail(ctx: RequestContext, sessionTag: string, messagesLimit: number): Promise<Record<string, unknown>> {
  const response = await fetch(apiUrl(ctx, `/api/gateway/sessions/${encodeURIComponent(sessionTag)}?messages_limit=${messagesLimit}`), {
    headers: requestHeaders(ctx),
  })
  if (!response.ok) throw new Error('session unavailable')
  return await response.json()
}

export async function renameSession(ctx: RequestContext, sessionTag: string, displayName: string): Promise<Record<string, unknown>> {
  const response = await fetch(apiUrl(ctx, `/api/gateway/sessions/${encodeURIComponent(sessionTag)}`), {
    method: 'PATCH',
    headers: requestHeaders(ctx),
    body: JSON.stringify({ display_name: displayName }),
  })
  if (!response.ok) throw new Error('改名没有成功')
  return await response.json()
}

export async function deleteSession(ctx: RequestContext, sessionTag: string): Promise<Record<string, unknown>> {
  const response = await fetch(apiUrl(ctx, `/api/gateway/sessions/${encodeURIComponent(sessionTag)}`), {
    method: 'DELETE',
    headers: requestHeaders(ctx),
    body: JSON.stringify({ confirm: sessionTag }),
  })
  if (!response.ok) throw new Error('删除没有成功')
  return await response.json()
}

export async function fetchWeather(ctx: RequestContext): Promise<Record<string, unknown>> {
  const response = await fetch(apiUrl(ctx, '/api/gateway/weather'), { headers: requestHeaders(ctx) })
  if (!response.ok) throw new Error('weather unavailable')
  return await response.json()
}

export async function postUpstreamConfig(ctx: RequestContext, body: Record<string, unknown>): Promise<void> {
  const response = await fetch(apiUrl(ctx, '/api/config'), {
    method: 'POST',
    headers: requestHeaders(ctx),
    body: JSON.stringify(body),
  })
  if (!response.ok) throw new Error(gatewayErrorMessage(response.status, await response.text()))
}

async function postChat(ctx: RequestContext, body: Record<string, unknown>, signal: AbortSignal): Promise<Response> {
  const response = await fetch(apiUrl(ctx, '/v1/chat/completions'), {
    method: 'POST',
    headers: requestHeaders(ctx),
    body: JSON.stringify(body),
    signal,
  })
  // 这里是错误正文的唯一入口：502 时上游代理返回的是整张 HTML 页，提取必须
  // 发生在这一步，不能让它进 Error.message 再指望渲染侧收拾。
  if (!response.ok) throw new Error(gatewayErrorMessage(response.status, await response.text()))
  return response
}

export async function postChatStream(ctx: RequestContext, body: Record<string, unknown>, signal: AbortSignal): Promise<ReadableStream<Uint8Array>> {
  const response = await postChat(ctx, body, signal)
  if (!response.body) throw new Error('没有收到流式回应')
  return response.body
}

export async function postChatCompletion(ctx: RequestContext, body: Record<string, unknown>, signal: AbortSignal): Promise<Record<string, unknown>> {
  const response = await postChat(ctx, body, signal)
  const payload: unknown = await response.json()
  if (!payload || typeof payload !== 'object' || Array.isArray(payload)) throw new Error('没有收到可识别的回应')
  return payload as Record<string, unknown>
}
