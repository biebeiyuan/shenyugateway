import { describe, expect, it } from 'vitest'
import { demoArchive, demoSeedTranscript } from '../src/demo/fixtures'

// demoRead 的 flag 依赖 window.location，vitest 环境固定为非 demo，所以这里直接测
// fixtures 的形状与种子逻辑；flag→拦截的端到端在 Playwright 里验（plain dist + ?demo=1）。

describe('demo fixtures', () => {
  it('archive rows carry a stable id, role and CST event_at', () => {
    expect(demoArchive.length).toBeGreaterThan(10)
    for (const r of demoArchive) {
      expect(r.id).toMatch(/^demo-\d+$/)
      expect(r.role === 'user' || r.role === 'assistant').toBe(true)
      expect(r.event_at).toContain('+08:00')
    }
  })

  it('literal search over fixtures finds 焦糖 but not a semantic neighbour', () => {
    const hit = (q: string) => demoArchive.filter((r) => r.content.toLowerCase().includes(q.toLowerCase()))
    expect(hit('焦糖').length).toBeGreaterThan(0)
    expect(hit('布丁').length).toBeGreaterThan(0)
    expect(hit('甜点').length).toBe(0) // 字面，不是语义
  })

  it('seed transcript is a valid, non-empty UiMessage list', () => {
    const seed = demoSeedTranscript()
    expect(seed.length).toBeGreaterThan(0)
    for (const m of seed) {
      expect(m.id).toContain('seed-')
      expect(typeof m.content).toBe('string')
      expect(Array.isArray(m.echoSegments)).toBe(true)
      expect(Array.isArray(m.attachments)).toBe(true)
    }
  })
})
