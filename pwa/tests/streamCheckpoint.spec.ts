import { readFileSync } from 'node:fs'
import { describe, expect, it } from 'vitest'

const appSource = readFileSync(new URL('../src/App.vue', import.meta.url), 'utf8')

describe('stream checkpoint wiring', () => {
  it('keeps ordinary stream checkpoints at the old three-second cadence without weakening safety checkpoints', () => {
    expect(appSource).toContain('const STREAM_PERSIST_INTERVAL_MS = 3_000')
    expect(appSource).toMatch(/if \(frame\.includes\('shenyu\.tool_event'\) \|\| frame\.includes\('shenyu_tool'\)\) void persistMessages\(\)/)
    expect(appSource).toMatch(/if \(!await persistMessages\(\)\) throw new Error\('本机未能保存这次发送/)
    expect(appSource).toMatch(/finally \{\s+await persistMessages\(\)/)
  })
})
