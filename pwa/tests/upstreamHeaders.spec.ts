import { beforeEach, describe, expect, it } from 'vitest'
import {
  CLAUDE_CODE_USER_AGENT,
  UPSTREAM_HEADERS_STORAGE_KEY,
  isClaudeCodeHeaderPreset,
  persistUpstreamHeaders,
  readUpstreamHeaders,
  upstreamHeaderSummary,
  upstreamHeadersPayload,
  type UpstreamHeaderEntry,
} from '../src/api/upstreamHeaders'

const claudeCode: UpstreamHeaderEntry[] = [
  { id: 'header-1', name: 'User-Agent', value: CLAUDE_CODE_USER_AGENT },
]

beforeEach(() => localStorage.clear())

describe('PWA upstream headers', () => {
  it('recognizes the Claude Code preset and builds its request payload', () => {
    expect(isClaudeCodeHeaderPreset(claudeCode)).toBe(true)
    expect(upstreamHeaderSummary(claudeCode)).toBe('Claude Code')
    expect(upstreamHeadersPayload(claudeCode)).toEqual({
      'User-Agent': 'claude-cli/2.1.212 (external, cli)',
    })
  })

  it('keeps complete custom rows and omits unfinished rows', () => {
    const entries: UpstreamHeaderEntry[] = [
      { id: 'one', name: ' X-Trace-Id ', value: ' abc ' },
      { id: 'two', name: 'X-Empty', value: '' },
      { id: 'three', name: 'x-trace-id', value: 'latest' },
    ]
    expect(upstreamHeadersPayload(entries)).toEqual({ 'x-trace-id': 'latest' })
    expect(upstreamHeaderSummary(entries)).toBe('自定义 · 1')
  })

  it('round-trips browser-local entries and tolerates corrupt storage', () => {
    persistUpstreamHeaders(claudeCode)
    expect(readUpstreamHeaders()).toEqual(claudeCode)
    localStorage.setItem(UPSTREAM_HEADERS_STORAGE_KEY, '{broken')
    expect(readUpstreamHeaders()).toEqual([])
  })
})
