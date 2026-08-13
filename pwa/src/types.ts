import type { ToolEvent } from './toolLanguage'

export type Role = 'user' | 'assistant'

export type Attachment = {
  id: string
  name: string
  mime: string
  dataUrl: string
}

export type ThinkingSegment = {
  id: string
  content: string
  textOffset: number
  streamOrder: number
}

export type EchoSegment = {
  id: string
  content: string
  textOffset: number
  streamOrder: number
}

export type MessageVariant = {
  content: string
  echo: string
  echoSegments: EchoSegment[]
  thinking: string
  thinkingSegments: ThinkingSegment[]
  events: ToolEvent[]
  error?: string
  responseMeta?: ResponseMeta
}

export type ResponseMeta = {
  context_rounds?: number
  context_trim_in_rounds?: number | null
  cache_read_percent?: number | null
  cache_read_input_tokens?: number
  cache_total_input_tokens?: number
  tool_rounds?: number
  first_tool_round_cache_hit?: boolean
  heartbeat_captured?: boolean
}

export type UiMessage = {
  id: string
  role: Role
  content: string
  echo: string
  echoSegments: EchoSegment[]
  attachments: Attachment[]
  thinking: string
  thinkingSegments: ThinkingSegment[]
  events: ToolEvent[]
  streaming?: boolean
  error?: string
  // 流在收到 [DONE] 之前就结束了（静默截断/进程被杀）；等待 reconcile 找回全文。
  truncated?: boolean
  expanded?: boolean
  variants?: MessageVariant[]
  selectedVariantIndex?: number
  responseMeta?: ResponseMeta
}

export type ProcessGroup = {
  textOffset: number
  echo: EchoSegment[]
  thinking: ThinkingSegment[]
  tools: ToolEvent[]
}

export type ProcessTimelineItem =
  | { kind: 'echo'; key: string; echo: EchoSegment; streamOrder: number }
  | { kind: 'thinking'; key: string; thinking: ThinkingSegment; streamOrder: number }
  | { kind: 'tool'; key: string; tool: ToolEvent; streamOrder: number }

export type AssistantPart =
  | { kind: 'content'; key: string; content: string }
  | { kind: 'process'; key: string; group: ProcessGroup }

export type ModelOption = {
  id: string
  object?: string
  owned_by?: string
  label?: string
  desc?: string
  thinking?: string
  primary?: boolean
}

export type GatewaySession = {
  session_tag: string
  client_name?: string
  display_name?: string | null
  last_active_at?: string
  latest_user_text?: string
  message_count?: number
  user_message_count?: number
}

export type WorkspaceId = 'chats' | 'projects' | 'artifacts' | 'memory' | 'diary'

export type UpstreamPreset = {
  name: string
  url: string
  key: string
  protocol: string
  proto?: string
  extra_body?: string
  passthrough_headers?: string[]
}

export type ProcessSheet = {
  messageId: string
  view: 'summary' | 'echo' | 'thinking' | 'tool'
  textOffset?: number
  echoKey?: string
  thinkingKey?: string
  toolKey?: string
}
