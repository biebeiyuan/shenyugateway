import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'
import { describe, expect, it } from 'vitest'

const appSource = readFileSync(resolve(process.cwd(), 'src/App.vue'), 'utf8')

describe('stream checkpoint wiring', () => {
  it('keeps ordinary stream checkpoints at the old three-second cadence without weakening safety checkpoints', () => {
    expect(appSource).toContain('const STREAM_PERSIST_INTERVAL_MS = 3_000')
    expect(appSource).toMatch(/if \(frame\.includes\('shenyu\.tool_event'\) \|\| frame\.includes\('shenyu_tool'\)\) void persistMessages\(\)/)
    expect(appSource).toMatch(/if \(!await persistMessages\(\)\) throw new Error\('本机未能保存这次发送/)
    expect(appSource).toMatch(/finally \{[\s\S]{0,800}await persistMessages\(\)[\s\S]{0,300}busy\.value = false/)
  })
})
