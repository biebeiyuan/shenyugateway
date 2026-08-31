// 演示模式（?demo=1）：把回看相关的读取 API 拦在浏览器里，返回 fixtures 的编造样本，
// 并在首屏种一段示例对话。用途：本地/隔离预览有内容可看可点，不用连真网关、不用推上线。
// 边界：只拦写死的几条读取路径；其余请求照常走真实后端。生产构建同样带这段代码，
// 但不开 ?demo=1 就完全不生效（与 admin `src/demo/` 同一套哲学）。

import { demoArchive, demoSeedTranscript, type DemoArchiveRow } from './fixtures'

const STORE_KEY = 'shenyu_pwa_demo'

function readFlag(): boolean {
  for (const src of [window.location.search, window.location.hash]) {
    const m = src.match(/[?&]demo=(1|0|true|false)/)
    if (m) {
      const on = m[1] === '1' || m[1] === 'true'
      try { localStorage.setItem(STORE_KEY, on ? '1' : '0') } catch { /* 不可用时只当次生效 */ }
      return on
    }
  }
  try { return localStorage.getItem(STORE_KEY) === '1' } catch { return false }
}

export const demoMode: boolean = readFlag()
export function isDemoMode(): boolean { return demoMode }

const cst = (iso: string) => {
  try { return new Date(iso).toLocaleDateString('en-CA', { timeZone: 'Asia/Shanghai' }) } catch { return iso.slice(0, 10) }
}
const strip = (rows: DemoArchiveRow[]) => rows.map(({ content_hash, ...rest }) => rest)

// 命中一条演示读取路径就返回数据，否则返回 undefined（调用方继续走真实 fetch）。
export function demoRead(path: string, params: URLSearchParams): unknown | undefined {
  if (!demoMode) return undefined

  if (path === '/api/archive/search') {
    const q = (params.get('q') || '').trim().toLowerCase()
    const role = params.get('role')
    if (!q) return { results: [], count: 0, query: '' }
    let hits = demoArchive.filter((r) => r.content.toLowerCase().includes(q))
    if (role === 'user' || role === 'assistant') hits = hits.filter((r) => r.role === role)
    hits = [...hits].sort((a, b) => (a.event_at < b.event_at ? 1 : -1))
    return { results: strip(hits), count: hits.length, query: q }
  }

  if (path === '/api/archive/days') {
    const month = params.get('month')
    const days: Record<string, number> = {}
    for (const r of demoArchive) {
      const d = cst(r.event_at)
      if (month && !d.startsWith(month)) continue
      days[d] = (days[d] || 0) + 1
    }
    return { days: Object.entries(days).sort().map(([date, count]) => ({ date, count })) }
  }

  if (path === '/api/archive/messages') {
    const date = params.get('date')
    const before = params.get('before')
    const after = params.get('after')
    const around = Math.max(0, Math.min(Number(params.get('around_days') || 0), 7))
    const limit = Math.max(1, Math.min(Number(params.get('limit') || 200), 1000))
    const asc = (a: DemoArchiveRow, b: DemoArchiveRow) => (a.event_at < b.event_at ? -1 : 1)
    let rows: DemoArchiveRow[]
    if (date) {
      const anchor = new Date(`${date}T00:00:00+08:00`)
      const lo = new Date(anchor); lo.setDate(lo.getDate() - around)
      const hi = new Date(anchor); hi.setDate(hi.getDate() + around + 1)
      rows = demoArchive.filter((r) => { const t = new Date(r.event_at); return t >= lo && t < hi }).sort(asc)
    } else if (before) {
      rows = demoArchive.filter((r) => r.event_at < before).sort(asc).slice(-limit)
    } else if (after) {
      rows = demoArchive.filter((r) => r.event_at > after).sort(asc).slice(0, limit)
    } else {
      rows = [...demoArchive].sort(asc)
    }
    return { messages: strip(rows), count: rows.length }
  }

  return undefined
}

export { demoSeedTranscript }
