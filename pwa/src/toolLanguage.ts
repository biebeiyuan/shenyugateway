export type ToolEvent = {
  phase: string
  tool_call_id: string
  name: string
  target_tool?: string
  round?: number
  cached?: boolean
  duration_ms?: number
  ok?: boolean | null
  error_kind?: string
  input?: unknown
  output?: string
  text_offset?: number
  stream_order?: number
}

export function toolName(event: ToolEvent): string {
  return String(event.target_tool || event.name || 'gateway_tool').replace(/^shenyu_/, '')
}

export function toolWarmCopy(event: ToolEvent): string {
  const target = toolName(event).toLowerCase()
  if (target.includes('web_read')) return '把那页带回来读了'
  if (target.includes('web')) return '往窗外看了看'
  if (target.includes('write_mem') || target.includes('note')) return '在窗台写了点东西'
  if (target.includes('recall') || target.includes('memory') || target.includes('search')) return '翻了翻便签'
  if (target.includes('calendar') || target.includes('date')) return '看了看日历'
  if (target.includes('star')) return '拨了拨星星'
  if (target.includes('book') || target.includes('shelf')) return '翻了翻书架'
  if (target.includes('room') || target.includes('window')) return '在窗台看了看'
  if (target.includes('heartbeat')) return '听了听心跳'
  return '认真处理了一下'
}

export function toolState(event: ToolEvent): string {
  if (event.phase === 'tool_start') return '进行中'
  if (event.ok === false) return '遇到一点阻塞'
  return '完成'
}
