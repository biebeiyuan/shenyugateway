import { describe, expect, it } from 'vitest'
import { parsePwaBuildInfo, samePwaBuild } from '../src/buildInfo'

const build = {
  schema: 1 as const,
  buildId: '50bc717-20260729T083000',
  revision: '50bc717d623d700c2eea7c5ebc90a6c1ee5b0c70',
  builtAt: '2026-07-29T08:30:00.000Z',
}

describe('PWA build information', () => {
  it('accepts only a complete deployed build manifest', () => {
    expect(parsePwaBuildInfo(build)).toEqual(build)
    expect(parsePwaBuildInfo({ ...build, buildId: '' })).toBeNull()
    expect(parsePwaBuildInfo({ ...build, schema: 2 })).toBeNull()
    expect(parsePwaBuildInfo(null)).toBeNull()
  })

  it('uses the exact build identity for deployment matching', () => {
    expect(samePwaBuild(build, { ...build })).toBe(true)
    expect(samePwaBuild(build, { ...build, buildId: 'newer-build' })).toBe(false)
  })
})
