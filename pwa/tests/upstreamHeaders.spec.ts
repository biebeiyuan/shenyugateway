import { beforeEach, describe, expect, it } from 'vitest'
import {
  CLAUDE_CODE_USER_AGENT,
  CLAUDE_CODE_SESSION_ID_STORAGE_KEY,
  claudeCodeHeaders,
  UPSTREAM_HEADERS_STORAGE_KEY,
  isClaudeCodeSessionId,
  isClaudeCodeHeaderPreset,
  persistUpstreamHeaders,
  readClaudeCodeSessionId,
  readUpstreamHeaders,
  refreshClaudeCodeSessionId,
  upstreamHeaderSummary,
  upstreamHeadersPayload,
  type UpstreamHeaderEntry,
} from '../src/api/upstreamHeaders'

const claudeCode: UpstreamHeaderEntry[] = [
  ...claudeCodeHeaders('550e8400-e29b-41d4-a716-446655440000'),
]

beforeEach(() => localStorage.clear())

describe('PWA upstream headers', () => {
  it('recognizes the Claude Code preset and builds its request payload', () => {
    expect(isClaudeCodeHeaderPreset(claudeCode)).toBe(true)
    expect(upstreamHeaderSummary(claudeCode)).toBe('Claude Code · 固定会话')
    expect(upstreamHeadersPayload(claudeCode)).toEqual({
      'User-Agent': CLAUDE_CODE_USER_AGENT,
      'X-App': 'cli',
      'X-Claude-Code-Session-Id': '550e8400-e29b-41d4-a716-446655440000',
    })
  })

  it('keeps the Claude Code session id stable until an explicit refresh', () => {
    const first = readClaudeCodeSessionId()
    expect(isClaudeCodeSessionId(first)).toBe(true)
    expect(readClaudeCodeSessionId()).toBe(first)
    expect(localStorage.getItem(CLAUDE_CODE_SESSION_ID_STORAGE_KEY)).toBe(first)
    const second = refreshClaudeCodeSessionId()
    expect(isClaudeCodeSessionId(second)).toBe(true)
    expect(second).not.toBe(first)
    expect(readClaudeCodeSessionId()).toBe(second)
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

  it('upgrades the old single user-agent preset without changing its new session id later', () => {
    localStorage.setItem(UPSTREAM_HEADERS_STORAGE_KEY, JSON.stringify([
      { id: 'legacy', name: 'User-Agent', value: 'claude-cli/2.1.212 (external, cli)' },
    ]))
    const upgraded = readUpstreamHeaders()
    expect(isClaudeCodeHeaderPreset(upgraded)).toBe(true)
    const sessionId = upstreamHeadersPayload(upgraded)['X-Claude-Code-Session-Id']
    expect(sessionId).toBe(readClaudeCodeSessionId())
  })
})
