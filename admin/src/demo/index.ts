// 演示模式（?demo=1）：把读取类 API 拦在浏览器里，返回 fixtures.ts 的编造样本。
// 用途：本地/隔离预览有内容可看、可点点点，不用推上 VPS。
// 边界：只拦写死的几条读取路径 + 写操作假成功；其余请求照常走真实后端。
// 生产构建同样带这段代码，但不开 ?demo=1 就完全不生效。

import axios, { type AxiosInstance, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios'
import {
  demoEntityMentions,
  demoGraphSnapshot,
  demoMemNotes,
  demoNameCandidates,
  demoRecall,
} from './fixtures'

const STORE_KEY = 'shenyu_admin_demo'

function readFlag(): boolean {
  // URL 优先：?demo=1 开、?demo=0 关（写在 hash 前或 hash 里都认），随后记住选择
  for (const src of [window.location.search, window.location.hash]) {
    const m = src.match(/[?&]demo=(1|0|true|false)/)
    if (m) {
      const on = m[1] === '1' || m[1] === 'true'
      try {
        localStorage.setItem(STORE_KEY, on ? '1' : '0')
      } catch {
        /* localStorage 不可用时只当次生效 */
      }
      return on
    }
  }
  try {
    return localStorage.getItem(STORE_KEY) === '1'
  } catch {
    return false
  }
}

export const demoMode: boolean = readFlag()

export function isDemoMode(): boolean {
  return demoMode
}

function matchDemoRoute(config: InternalAxiosRequestConfig): unknown {
  const method = (config.method || 'get').toLowerCase()
  const url = config.url || ''
  const qIndex = url.indexOf('?')
  const path = qIndex >= 0 ? url.slice(0, qIndex) : url
  const params = new URLSearchParams(qIndex >= 0 ? url.slice(qIndex + 1) : '')

  if (method === 'post' && path === '/api/gateway/memory-graph/recall-preview') {
    let query = ''
    try {
      query = JSON.parse(String(config.data || '{}')).query || ''
    } catch {
      /* 空查询也返回整池 */
    }
    return demoRecall(query)
  }

  if (method === 'get') {
    if (path === '/api/gateway/memory-graph') return demoGraphSnapshot()
    if (path.startsWith('/api/gateway/memory-graph/name-candidates')) return demoNameCandidates()
    if (path.includes('/memory-graph/entities/') && path.endsWith('/mentions')) return { items: demoEntityMentions() }
    if (path.startsWith('/api/gateway/memory-graph/candidate-mentions')) return { items: [], text_hits: [] }
    if (path.startsWith('/api/gateway/memory-graph/sources/')) return { mentions: [] }
    if (path.startsWith('/api/gateway/mem-notes')) return demoMemNotes(params)
    if (path.startsWith('/api/gateway/legacy-atomic-memories')) return { items: [], count: 0 }
    return undefined
  }

  // 写操作在演示模式下假成功、不落数据，让点点点不报错
  if (path.startsWith('/api/gateway/')) {
    return { ok: true, entity: demoGraphSnapshot().entities[0], message: '演示数据，不会真的保存' }
  }
  return undefined
}

/** 演示模式开启时，把 axios 适配器换成「先查演示表、查不到走真实网络」。 */
export function installDemoAdapter(instance: AxiosInstance): void {
  if (!demoMode) return
  // 浏览器包里没有 node 的 http 适配器；给完整候选列表让 axios 自选（浏览器挑 xhr）
  const fallback = axios.getAdapter(['xhr', 'http', 'fetch'])
  instance.defaults.adapter = async (config: InternalAxiosRequestConfig): Promise<AxiosResponse> => {
    const data = matchDemoRoute(config)
    if (data === undefined) return fallback(config)
    await new Promise((r) => setTimeout(r, 120)) // 一点延迟，加载态也看得到
    return { data, status: 200, statusText: 'OK (demo)', headers: {}, config }
  }
}
