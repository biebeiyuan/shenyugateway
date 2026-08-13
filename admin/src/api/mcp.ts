import { api } from './http'

export interface McpServer {
  name: string
  url: string
  transport: 'auto' | 'sse'
  headers: Record<string, string>
  enabled: boolean
}

export interface McpServerStatus {
  name: string
  url: string
  transport: string
  ok: boolean
  error: string | null
  tool_count: number
  checked_at: string
}

export interface McpToolSummary {
  name: string
  server: string
  remote_name: string
  description: string
}

export interface McpServersResponse {
  servers: McpServer[]
  status: McpServerStatus[]
  tools: McpToolSummary[]
}

export interface McpTestResult {
  ok: boolean
  tool_count?: number
  tools?: string[]
  error?: string
}

// Mirrors backend validate_mcp_servers (shenyu_gateway/mcp_registry.py).
export const MCP_SERVER_NAME_RE = /^[a-z0-9_]{1,24}$/

export function emptyMcpServer(): McpServer {
  return { name: '', url: '', transport: 'auto', headers: {}, enabled: true }
}

/** Masked read-back from GET /api/mcp/servers; must be sent back untouched. */
export function isMaskedHeaderValue(value: string): boolean {
  return value.includes('****')
}

/** Returns an owner-readable error, or null when the entry is valid. */
export function validateMcpServer(server: McpServer): string | null {
  if (!MCP_SERVER_NAME_RE.test(server.name)) {
    return '名称只能用小写字母、数字、下划线，1-24 位'
  }
  if (!/^https?:\/\//.test(server.url.trim())) {
    return 'URL 必须以 http:// 或 https:// 开头'
  }
  if (server.transport !== 'auto' && server.transport !== 'sse') {
    return 'transport 只能是 auto 或 sse'
  }
  return null
}

/** Validates the whole list (per-entry rules plus duplicate names). */
export function validateMcpServers(servers: McpServer[]): string | null {
  const seen = new Set<string>()
  for (const server of servers) {
    const error = validateMcpServer(server)
    if (error) return `${server.name || '(未命名)'}: ${error}`
    if (seen.has(server.name)) return `服务器名称重复：${server.name}`
    seen.add(server.name)
  }
  return null
}

export async function fetchMcpServers(): Promise<McpServersResponse> {
  const { data } = await api.get('/api/mcp/servers')
  return data
}

export async function saveMcpServers(servers: McpServer[]): Promise<{ ok: boolean; servers: McpServer[] }> {
  const { data } = await api.post('/api/mcp/servers', servers)
  return data
}

export async function testMcpServer(server: McpServer): Promise<McpTestResult> {
  const { data } = await api.post('/api/mcp/test', server)
  return data
}

export async function refreshMcpTools(): Promise<{ ok: boolean; status: McpServerStatus[]; tools: McpToolSummary[] }> {
  const { data } = await api.post('/api/mcp/refresh')
  return data
}
