import { beforeEach, describe, expect, it } from 'vitest'
import {
  CLAUDE_CODE_DEVICE_ID_STORAGE_KEY,
  CLAUDE_CODE_USER_AGENT,
  CLAUDE_CODE_SESSION_ID_STORAGE_KEY,
  claudeCodeHeaders,
  claudeCodeMetadata,
  claudeCodeSessionIdFromHeaders,
  UPSTREAM_HEADERS_STORAGE_KEY,
  isClaudeCodeSessionId,
  isClaudeCodeHeaderPreset,
  persistUpstreamHeaders,
  readClaudeCodeDeviceId,
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
    expect(upstreamHeaderSummary(claudeCode)).toBe('Claude Code · 完整模拟')
    expect(upstreamHeadersPayload(claudeCode)).toEqual({
      'User-Agent': CLAUDE_CODE_USER_AGENT,
      Accept: 'application/json',
      'Anthropic-Beta': 'claude-code-20250219,interleaved-thinking-2025-05-14,effort-2025-11-24',
      'Anthropic-Dangerous-Direct-Browser-Access': 'true',
      'X-App': 'cli',
      'X-Stainless-Arch': 'x64',
      'X-Stainless-Lang': 'js',
      'X-Stainless-Os': 'Linux',
      'X-Stainless-Package-Version': '0.94.0',
      'X-Stainless-Retry-Count': '0',
      'X-Stainless-Runtime': 'node',
      'X-Stainless-Runtime-Version': 'v26.3.0',
      'X-Stainless-Timeout': '600',
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

  it('keeps a separate browser device id and builds Claude Code metadata', () => {
    const deviceId = readClaudeCodeDeviceId()
    expect(deviceId).toMatch(/^[0-9a-f]{64}$/)
    expect(readClaudeCodeDeviceId()).toBe(deviceId)
    expect(localStorage.getItem(CLAUDE_CODE_DEVICE_ID_STORAGE_KEY)).toBe(deviceId)
    expect(claudeCodeMetadata(
      '550e8400-e29b-41d4-a716-446655440000',
      'a'.repeat(64),
    )).toEqual({
      user_id: JSON.stringify({
        device_id: 'a'.repeat(64),
        account_uuid: '',
        session_id: '550e8400-e29b-41d4-a716-446655440000',
      }),
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

  it('upgrades the old single user-agent preset without changing its new session id later', () => {
    localStorage.setItem(UPSTREAM_HEADERS_STORAGE_KEY, JSON.stringify([
      { id: 'legacy', name: 'User-Agent', value: 'claude-cli/2.1.212 (external, cli)' },
    ]))
    const upgraded = readUpstreamHeaders()
    expect(isClaudeCodeHeaderPreset(upgraded)).toBe(true)
    const sessionId = claudeCodeSessionIdFromHeaders(upgraded)
    expect(sessionId).toBe(readClaudeCodeSessionId())
  })

  it('upgrades the compact three-header preset without rotating its session id', () => {
    const sessionId = 'f53c8a1c-9cf2-42c2-a86d-78a83985a6d2'
    localStorage.setItem(UPSTREAM_HEADERS_STORAGE_KEY, JSON.stringify([
      { id: 'ua', name: 'User-Agent', value: 'claude-cli/2.1.226 (external, cli)' },
      { id: 'app', name: 'X-App', value: 'cli' },
      { id: 'session', name: 'X-Claude-Code-Session-Id', value: sessionId },
    ]))
    const upgraded = readUpstreamHeaders()
    expect(isClaudeCodeHeaderPreset(upgraded)).toBe(true)
    expect(claudeCodeSessionIdFromHeaders(upgraded)).toBe(sessionId)
    expect(localStorage.getItem(CLAUDE_CODE_SESSION_ID_STORAGE_KEY)).toBe(sessionId)
  })
})
