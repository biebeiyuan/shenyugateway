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

export type MessageVariant = {
  content: string
  thinking: string
  thinkingSegments: ThinkingSegment[]
  events: ToolEvent[]
  error?: string
}

export type UiMessage = {
  id: string
  role: Role
  content: string
  attachments: Attachment[]
  thinking: string
  thinkingSegments: ThinkingSegment[]
  events: ToolEvent[]
  streaming?: boolean
  error?: string
  expanded?: boolean
  variants?: MessageVariant[]
  selectedVariantIndex?: number
}

export type ProcessGroup = {
  textOffset: number
  thinking: ThinkingSegment[]
  tools: ToolEvent[]
}

export type ProcessTimelineItem =
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
  view: 'summary' | 'thinking' | 'tool'
  textOffset?: number
  thinkingKey?: string
  toolKey?: string
}
