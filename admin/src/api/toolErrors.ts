import { api } from './http'

export interface ToolError {
  id: string
  session_id: string
  session_tag: string | null
  tool_name: string
  target_tool: string | null
  args_json: string | null
  error_text: string
  error_source: string
  error_kind: string
  created_at: string
}

export async function fetchToolErrors(limit = 50, kind?: string): Promise<{ errors: ToolError[] }> {
  const { data } = await api.get('/api/gateway/tool-errors', {
    params: { limit, ...(kind ? { kind } : {}) },
  })
  return data
}
