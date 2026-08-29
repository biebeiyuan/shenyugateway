// 网关错误正文 → 一句能看的话。
//
// 502 时 Cloudflare 返回的是整张 HTML 错误页；直接把响应体塞进 Error.message，
// 那几千个字符会一路流到 message.error 和 errorNotice，把对话和输入框一起顶出
// 屏幕，还会跟着 error 落盘、每次重开 App 复发一遍。所以提取必须发生在入口，
// 而不是靠渲染侧截断——渲染侧的上限是第二道墙，不是第一道。

// 一条错误提示允许的最大长度。够放下上游的真实原因，放不下一张网页。
const MESSAGE_LIMIT = 300

const HTML_MARKERS = ['<!doctype html', '<html', '<head', '<body']

function truncate(text: string): string {
  const compact = text.replace(/\s+/g, ' ').trim()
  return compact.length > MESSAGE_LIMIT ? `${compact.slice(0, MESSAGE_LIMIT)}…` : compact
}

function looksLikeHtml(body: string): boolean {
  const head = body.slice(0, 200).toLowerCase()
  return HTML_MARKERS.some((marker) => head.includes(marker))
}

// FastAPI 是 {"detail": ...}；上游可能是 {"error": {"message": ...}}，也可能把
// 这两层嵌在一起。只往下找已知的几个键名，找不到就当没有结构。
function reasonFromValue(value: unknown, depth = 0): string {
  if (depth > 4) return ''
  if (typeof value === 'string') return value.trim()
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (Array.isArray(value)) {
    for (const item of value) {
      const reason = reasonFromValue(item, depth + 1)
      if (reason) return reason
    }
    return ''
  }
  if (!value || typeof value !== 'object') return ''
  const record = value as Record<string, unknown>
  for (const key of ['detail', 'error', 'message', 'error_description', 'msg']) {
    const reason = reasonFromValue(record[key], depth + 1)
    if (reason) return reason
  }
  return ''
}

function statusFallback(status: number): string {
  if (status === 401 || status === 403) return `网关没有认证通过（${status}），检查聊天设置里的令牌。`
  if (status === 404) return `这个网关地址上没有这个接口（404）。`
  if (status === 429) return `上游正忙，请求被限流了（429）。`
  if (status === 502 || status === 503) return `网关暂时没应答（${status}），过一会儿再试。`
  if (status === 504) return `网关等上游超时了（504）。`
  return `网关返回 ${status}。`
}

/**
 * 把一次失败响应变成一句人话。HTML 错误页只报状态码，绝不搬正文。
 */
export function gatewayErrorMessage(status: number, body: string): string {
  const raw = (body || '').trim()
  if (!raw) return statusFallback(status)
  if (looksLikeHtml(raw)) return statusFallback(status)

  try {
    const reason = reasonFromValue(JSON.parse(raw))
    if (reason) return truncate(looksLikeHtml(reason) ? statusFallback(status) : reason)
  } catch {
    // 不是 JSON，按纯文本处理。
  }
  return truncate(raw)
}

/**
 * 渲染与落盘共用的第二道墙：任何来路不明的长字符串都只能占这么多。
 */
export function clampErrorText(text: string): string {
  return truncate(String(text || ''))
}
