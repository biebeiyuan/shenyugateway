import { describe, expect, it } from 'vitest'
import {
  emptyMcpServer,
  isMaskedHeaderValue,
  validateMcpServer,
  validateMcpServers,
  type McpServer,
} from './mcp'

function server(overrides: Partial<McpServer> = {}): McpServer {
  return { ...emptyMcpServer(), name: 'everything', url: 'http://127.0.0.1:3001/mcp', ...overrides }
}

describe('validateMcpServer', () => {
  it('accepts a plain valid entry', () => {
    expect(validateMcpServer(server())).toBeNull()
  })

  it('rejects names outside [a-z0-9_]{1,24}', () => {
    for (const name of ['', 'Big', 'has space', 'has-dash', '中文', 'x'.repeat(25)]) {
      expect(validateMcpServer(server({ name })), name).toContain('名称')
    }
    expect(validateMcpServer(server({ name: 'ok_name_9' }))).toBeNull()
  })

  it('rejects URLs that do not start with http(s)://', () => {
    for (const url of ['', 'ws://x', 'ftp://x', 'localhost:3001']) {
      expect(validateMcpServer(server({ url })), url).toContain('URL')
    }
    expect(validateMcpServer(server({ url: 'https://mcp.example.com/sse' }))).toBeNull()
  })

  it('rejects unknown transports', () => {
    expect(validateMcpServer(server({ transport: 'grpc' as McpServer['transport'] }))).toContain('transport')
    expect(validateMcpServer(server({ transport: 'sse' }))).toBeNull()
  })
})

describe('validateMcpServers', () => {
  it('flags duplicate names across the list', () => {
    expect(validateMcpServers([server(), server({ url: 'http://other/mcp' })])).toContain('重复')
  })

  it('passes a valid multi-entry list', () => {
    expect(validateMcpServers([server(), server({ name: 'second' })])).toBeNull()
  })
})

describe('isMaskedHeaderValue', () => {
  it('recognises the backend mask placeholder', () => {
    expect(isMaskedHeaderValue('sk-1****cdef')).toBe(true)
    expect(isMaskedHeaderValue('Bearer real-token')).toBe(false)
  })
})
