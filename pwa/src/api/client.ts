import type { UiMessage } from '../types'

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

export function requestHeaders(ctx: RequestContext): Record<string, string> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    'X-Shenyu-Client': 'shenyu-pwa',
    'X-Shenyu-Tool-Events': 'true',
    'X-Shenyu-Tool-Details': 'true',
    'X-Shenyu-Session-Tag': ctx.sessionTag,
  }
  if (ctx.authToken.trim()) headers.Authorization = `Bearer ${ctx.authToken.trim()}`
  return headers
}

export function wireContent(message: UiMessage): string | Array<Record<string, unknown>> {
  if (!message.attachments.length) return message.content
  const blocks: Array<Record<string, unknown>> = []
  if (message.content.trim()) blocks.push({ type: 'text', text: message.content })
  for (const attachment of message.attachments) {
    blocks.push({ type: 'image_url', image_url: { url: attachment.dataUrl } })
  }
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
  if (!response.ok) throw new Error((await response.text()) || `网关返回 ${response.status}`)
}

async function postChat(ctx: RequestContext, body: Record<string, unknown>, signal: AbortSignal): Promise<Response> {
  const response = await fetch(apiUrl(ctx, '/v1/chat/completions'), {
    method: 'POST',
    headers: requestHeaders(ctx),
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok) {
    const detail = await response.text()
    throw new Error(detail || `网关返回 ${response.status}`)
  }
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
