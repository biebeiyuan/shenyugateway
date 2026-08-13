<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NLayoutFooter,
  NPopconfirm,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  useMessage,
  useNotification,
} from 'naive-ui'
import {
  fetchColdStartPreview,
  fetchConfig,
  fetchGatewayOverview,
  fetchHealth,
  saveConfig,
  type ColdStartPreview,
  type GatewayConfig,
  type GatewayOverview,
  type HealthStatus,
} from '@/api/config'
import { fetchGatewaySessions, type GatewaySession } from '@/api/sessions'
import McpServersCard from '@/components/McpServersCard.vue'

interface UpstreamPreset {
  name: string
  url: string
  key: string
  protocol: string
  proto?: string
  extra_body?: string
  passthrough_headers?: string[]
}

const PRESETS_KEY = 'shenyu_upstream_presets'

const message = useMessage()
const notification = useNotification()

const config = ref<GatewayConfig>({
  gateway_key: '',
  upstream_url: '',
  upstream_api_key: '',
  upstream_protocol: 'auto',
  upstream_proxy: '',
  upstream_trust_env: false,
  enable_openai_cache_control: true,
  enable_anthropic_cache_control: true,
  openai_cache_ttl: '5m',
  anthropic_cache_ttl: '1h',
  enable_anthropic_auto_thinking: false,
  anthropic_auto_thinking_effort: '',
  upstream_extra_body: {},
  upstream_passthrough_headers: ['x-api-key'],
  wake_welcome_message: '',
  echo_prompt: '',
  echo_retention_turns: 1,
  weather_city: '',
  qweather_api_key: '',
  qweather_api_host: '',
  serper_api_key: '',
  jina_api_key: '',
  supabase_url: '',
  supabase_key: '',
  max_client_messages: 75,
  enable_cold_start: true,
  cold_start_message_limit: null,
  cold_start_idle_minutes: 120,
  model_mapping: {},
  enable_upstream_tools: true,
  enable_gateway_tools: true,
  enable_mem0_management_tools: true,
  expose_supabase_tools: true,
  enable_mcp_tools: true,
  mcp_call_timeout_seconds: 60,
  mcp_list_timeout_seconds: 10,
  mcp_tools_cache_seconds: 300,
  mcp_tool_result_keep_recent: 3,
  gateway_tool_mode: 'broker',
  gateway_tool_surface: 'full',
  client_tool_surface: 'all',
  max_internal_tool_rounds: 15,
  gateway_log_full_payloads: false,
  room_newspaper_qa_enabled: false,
  room_newspaper_llm_model: '',
  room_newspaper_llm_url: '',
  room_newspaper_llm_api_key: '',
  room_newspaper_llm_protocol: '',
})

const health = ref<HealthStatus | null>(null)
const saving = ref(false)
const clearingWelcome = ref(false)
const switchingPreset = ref('')
const presetName = ref('')
const presets = ref<UpstreamPreset[]>([])
const upstreamExtraBodyText = ref('')
const overview = ref<GatewayOverview | null>(null)
const dailyColdResult = ref<ColdStartPreview | null>(null)
const lightColdResult = ref<ColdStartPreview | null>(null)
const sessions = ref<GatewaySession[]>([])
const dailyColdTag = ref('')
const lightColdTag = ref('')
const lightColdSource = ref('__auto__')
const lightColdLimit = ref(8)
const dailyColdLoading = ref(false)
const lightColdLoading = ref(false)

const protocolOptions = [
  { label: 'Auto detect', value: 'auto' },
  { label: 'OpenAI compatible', value: 'openai' },
  { label: 'Anthropic', value: 'anthropic' },
]
const inheritedProtocolOptions = [{ label: 'Inherit global', value: '' }, ...protocolOptions]
const cacheTtlOptions = [
  { label: '5 分钟', value: '5m' },
  { label: '1 小时', value: '1h' },
]
const anthropicThinkingEffortOptions = [
  { label: '默认（不发送 effort）', value: '' },
  { label: 'XHigh（Opus 4.6 不兼容）', value: 'xhigh' },
  { label: 'Max', value: 'max' },
]
const toolModeOptions = [
  { label: 'Full schemas（不用 broker）', value: 'full' },
  { label: 'Compact broker（推荐）', value: 'broker' },
]
const gatewayToolSurfaceOptions = [
  { label: 'broker 内：全量清单', value: 'full' },
  { label: 'broker 内：日常清单', value: 'daily' },
]
const clientToolSurfaceOptions = [
  { label: '全部客户端工具', value: 'all' },
  { label: '日常客户端工具', value: 'daily' },
  { label: '不暴露客户端工具', value: 'none' },
]
const extraBodySnippets = [
  { label: 'provider 字符串 · Amazon Bedrock', value: '{"provider":"Amazon Bedrock"}' },
  { label: 'provider.order 对象', value: '{"provider":{"order":["Amazon Bedrock"]}}' },
  { label: '自定义模型列表', value: '{"models":["claude-opus-4-7"]}' },
]
const headerPresetOptions = [
  { label: 'x-api-key（Anthropic 风格）', value: 'x-api-key' },
  { label: 'x-request-id（链路追踪）', value: 'x-request-id' },
]
const protectedHeaders = ['authorization', 'content-type', 'x-shenyu-session-tag', 'x-session-tag', 'x-shenyu-client', 'x-client-name']
const sessionOptions = computed(() => sessions.value.map((item) => ({
  label: `${item.session_tag}${item.latest_user_text ? ` · ${item.latest_user_text.slice(0, 24)}` : ''}`,
  value: item.session_tag,
})))
const sourceSessionOptions = computed(() => [
  { label: '最新老线程', value: '__auto__' },
  ...sessionOptions.value,
])
const coldHeader = (sessionTag: string) => `X-Shenyu-Session-Tag: ${sessionTag}`

const activePresetName = computed(() => {
  const match = presets.value.find(
    (preset) =>
      preset.url === config.value.upstream_url &&
      preset.key === config.value.upstream_api_key &&
      preset.protocol === config.value.upstream_protocol,
  )
  return match?.name || null
})

let healthTimer: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  loadPresets()
  await loadConfig()
  await checkHealth()
  await loadOverview()
  await loadSessions()
  healthTimer = setInterval(checkHealth, 15000)
})

onUnmounted(() => {
  if (healthTimer) clearInterval(healthTimer)
})

function loadPresets() {
  try {
    const raw = JSON.parse(localStorage.getItem(PRESETS_KEY) || '{}')
    presets.value = Object.entries(raw).map(([name, value]) => {
      const preset = value as Partial<UpstreamPreset>
      return {
        name,
        url: preset.url || '',
        key: preset.key || '',
        protocol: preset.protocol || preset.proto || 'auto',
        extra_body: preset.extra_body || '',
        passthrough_headers: preset.passthrough_headers || [],
      }
    })
  } catch {
    presets.value = []
  }
}

function persistPresets() {
  const raw = Object.fromEntries(
    presets.value.map((preset) => [
      preset.name,
      {
        url: preset.url,
        key: preset.key,
        protocol: preset.protocol,
        extra_body: preset.extra_body || '',
        passthrough_headers: preset.passthrough_headers || [],
      },
    ]),
  )
  localStorage.setItem(PRESETS_KEY, JSON.stringify(raw))
}

function formatExtraBody(value: unknown) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return ''
  const entries = Object.keys(value as Record<string, unknown>)
  return entries.length ? JSON.stringify(value, null, 2) : ''
}

function parseExtraBody() {
  const raw = upstreamExtraBodyText.value.trim()
  if (!raw) return {}
  let parsed: unknown
  try {
    parsed = JSON.parse(raw)
  } catch {
    throw new Error('上游 extra_body 必须是有效 JSON object')
  }
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    throw new Error('上游 extra_body 必须是 JSON object')
  }
  return parsed as Record<string, unknown>
}

function insertExtraBodySnippet(snippet: string) {
  let current: Record<string, unknown> = {}
  try {
    current = parseExtraBody()
  } catch (error) {
    message.error(error instanceof Error ? error.message : 'extra_body 解析失败')
    return
  }
  let patch: Record<string, unknown> = {}
  try {
    patch = JSON.parse(snippet) as Record<string, unknown>
  } catch {
    message.error('片段 JSON 无效')
    return
  }
  const merged = { ...current, ...patch }
  upstreamExtraBodyText.value = Object.keys(merged).length ? JSON.stringify(merged, null, 2) : ''
}

function addPassthroughHeader(name: string) {
  const normalized = name.trim().toLowerCase()
  if (!normalized) return
  const existing = config.value.upstream_passthrough_headers || []
  if (existing.includes(normalized)) return
  config.value.upstream_passthrough_headers = [...existing, normalized]
}

function showSaveWarnings(warnings?: string[]) {
  if (!warnings || !warnings.length) return
  notification.warning({
    title: '保存提醒',
    content: warnings.join('\n'),
    duration: 8000,
  })
}

async function loadConfig() {
  try {
    const data = await fetchConfig()
    config.value = data
    upstreamExtraBodyText.value = formatExtraBody(data.upstream_extra_body)
  } catch {
    message.error('Failed to load config')
  }
}

async function doSave() {
  saving.value = true
  try {
    const upstreamExtraBody = parseExtraBody()
    const body: Partial<GatewayConfig> = {
      gateway_key: config.value.gateway_key,
      upstream_url: config.value.upstream_url,
      upstream_api_key: config.value.upstream_api_key,
      upstream_protocol: config.value.upstream_protocol,
      enable_openai_cache_control: config.value.enable_openai_cache_control,
      enable_anthropic_cache_control: config.value.enable_anthropic_cache_control,
      openai_cache_ttl: config.value.openai_cache_ttl,
      anthropic_cache_ttl: config.value.anthropic_cache_ttl,
      enable_anthropic_auto_thinking: config.value.enable_anthropic_auto_thinking,
      anthropic_auto_thinking_effort: config.value.anthropic_auto_thinking_effort || '',
      upstream_extra_body: upstreamExtraBody,
      upstream_passthrough_headers: config.value.upstream_passthrough_headers || [],
      weather_city: config.value.weather_city,
      qweather_api_host: config.value.qweather_api_host,
      supabase_url: config.value.supabase_url,
      max_client_messages: config.value.max_client_messages || null,
      enable_cold_start: config.value.enable_cold_start,
      enable_upstream_tools: config.value.enable_upstream_tools,
      enable_gateway_tools: config.value.enable_gateway_tools,
      enable_mem0_management_tools: config.value.enable_mem0_management_tools,
      expose_supabase_tools: config.value.expose_supabase_tools,
      enable_mcp_tools: config.value.enable_mcp_tools,
      mcp_call_timeout_seconds: config.value.mcp_call_timeout_seconds,
      mcp_list_timeout_seconds: config.value.mcp_list_timeout_seconds,
      mcp_tools_cache_seconds: config.value.mcp_tools_cache_seconds,
      mcp_tool_result_keep_recent: config.value.mcp_tool_result_keep_recent,
      gateway_tool_mode: config.value.gateway_tool_mode,
      gateway_tool_surface: config.value.gateway_tool_surface,
      client_tool_surface: config.value.client_tool_surface,
      max_internal_tool_rounds: config.value.max_internal_tool_rounds,
      echo_prompt: config.value.echo_prompt || '',
      echo_retention_turns: config.value.echo_retention_turns ?? 1,
      gateway_log_full_payloads: config.value.gateway_log_full_payloads,
      room_newspaper_qa_enabled: config.value.room_newspaper_qa_enabled,
      room_newspaper_llm_model: config.value.room_newspaper_llm_model,
      room_newspaper_llm_url: config.value.room_newspaper_llm_url,
      room_newspaper_llm_protocol: config.value.room_newspaper_llm_protocol,
    }
    if (config.value.supabase_key?.trim()) body.supabase_key = config.value.supabase_key.trim()
    if (config.value.qweather_api_key?.trim()) {
      body.qweather_api_key = config.value.qweather_api_key.trim()
    }
    if (config.value.serper_api_key?.trim()) {
      body.serper_api_key = config.value.serper_api_key.trim()
    }
    if (config.value.jina_api_key?.trim()) {
      body.jina_api_key = config.value.jina_api_key.trim()
    }
    if (config.value.room_newspaper_llm_api_key?.trim()) {
      body.room_newspaper_llm_api_key = config.value.room_newspaper_llm_api_key.trim()
    }
    const wakeWelcomeMessage = config.value.wake_welcome_message?.trim()
    if (wakeWelcomeMessage) body.wake_welcome_message = wakeWelcomeMessage
    const result = await saveConfig(body)
    config.value = result.config
    upstreamExtraBodyText.value = formatExtraBody(result.config.upstream_extra_body)
    message.success(`Saved ${result.changed.length} field${result.changed.length === 1 ? '' : 's'}`)
    showSaveWarnings(result.warnings)
    await checkHealth()
  } catch (error) {
    message.error(error instanceof Error ? error.message : 'Save failed')
  } finally {
    saving.value = false
  }
}

async function clearWakeWelcomeMessage() {
  clearingWelcome.value = true
  try {
    const result = await saveConfig({ clear_wake_welcome_message: true })
    config.value = result.config
    upstreamExtraBodyText.value = formatExtraBody(result.config.upstream_extra_body)
    message.success('已清空醒来欢迎词')
  } catch {
    message.error('清空失败')
  } finally {
    clearingWelcome.value = false
  }
}

function saveCurrentPreset() {
  const name = presetName.value.trim()
  if (!name) {
    message.warning('Name the preset first')
    return
  }
  const nextPreset: UpstreamPreset = {
    name,
    url: config.value.upstream_url,
    key: config.value.upstream_api_key,
    protocol: config.value.upstream_protocol || 'auto',
    extra_body: upstreamExtraBodyText.value,
    passthrough_headers: [...(config.value.upstream_passthrough_headers || [])],
  }
  const existingIndex = presets.value.findIndex((preset) => preset.name === name)
  if (existingIndex >= 0) {
    presets.value.splice(existingIndex, 1, nextPreset)
  } else {
    presets.value.push(nextPreset)
  }
  persistPresets()
  presetName.value = ''
  message.success(`Preset saved: ${name}`)
}

async function applyPreset(name: string | null) {
  if (!name) return
  const preset = presets.value.find((item) => item.name === name)
  if (!preset) return
  const upstreamApiKey = preset.key || config.value.upstream_api_key

  config.value.upstream_url = preset.url
  config.value.upstream_api_key = upstreamApiKey
  config.value.upstream_protocol = preset.protocol
  const presetHeaders = [...(preset.passthrough_headers || [])]
  config.value.upstream_passthrough_headers = presetHeaders
  let presetExtraBody: Record<string, unknown> = {}
  if (preset.extra_body) {
    upstreamExtraBodyText.value = preset.extra_body
    try {
      presetExtraBody = JSON.parse(preset.extra_body) as Record<string, unknown>
    } catch {
      presetExtraBody = {}
    }
  } else {
    upstreamExtraBodyText.value = ''
  }
  config.value.upstream_extra_body = presetExtraBody

  switchingPreset.value = name
  try {
    const result = await saveConfig({
      upstream_url: preset.url,
      upstream_api_key: upstreamApiKey,
      upstream_protocol: preset.protocol,
      upstream_extra_body: presetExtraBody,
      upstream_passthrough_headers: presetHeaders,
    })
    config.value = result.config
    upstreamExtraBodyText.value = formatExtraBody(result.config.upstream_extra_body)
    showSaveWarnings(result.warnings)
    if (!preset.key) {
      message.warning(`预设 ${name} 的旧密钥已丢失，本次保留当前上游 Key；请重新输入正确 Key 后覆盖保存该预设`)
    }
    message.success(`Switched to ${name}`)
    notification.success({
      title: 'Upstream preset switched',
      content: `${name} · ${preset.protocol || 'auto'} · ${preset.url || 'URL not set'}`,
      duration: 4500,
    })
    await checkHealth()
  } catch {
    message.error(`Failed to switch to ${name}`)
    notification.error({
      title: 'Upstream preset switch failed',
      content: name,
      duration: 6000,
    })
  } finally {
    switchingPreset.value = ''
  }
}

function deletePreset(name: string) {
  presets.value = presets.value.filter((preset) => preset.name !== name)
  persistPresets()
  message.success(`Preset deleted: ${name}`)
}

async function checkHealth() {
  try {
    health.value = await fetchHealth()
  } catch {
    health.value = null
  }
}

async function loadOverview() {
  try {
    overview.value = await fetchGatewayOverview()
  } catch {
    overview.value = null
  }
}

async function loadSessions() {
  try {
    const data = await fetchGatewaySessions({ limit: 80 })
    sessions.value = data.sessions
  } catch {
    sessions.value = []
  }
}

async function generateDailyColdStart() {
  const target = dailyColdTag.value.trim()
  if (!target) {
    message.warning('请先填写新线程名称')
    return
  }
  dailyColdLoading.value = true
  try {
    await Promise.all([loadOverview(), loadSessions()])
    dailyColdResult.value = await fetchColdStartPreview({
      target_session_tag: target,
      message_limit: config.value.max_client_messages || undefined,
      persist: true,
    })
    if (dailyColdResult.value.persisted) {
      message.success('日常冷启动已固定，可以复制请求头')
    }
  } catch {
    dailyColdResult.value = null
    message.error('生成日常冷启动失败')
  } finally {
    dailyColdLoading.value = false
  }
}

async function generateLightColdStart() {
  const target = lightColdTag.value.trim()
  if (!target) {
    message.warning('请先填写新线程名称')
    return
  }
  lightColdLoading.value = true
  try {
    await loadSessions()
    lightColdResult.value = await fetchColdStartPreview({
      target_session_tag: target,
      source_session_tag: lightColdSource.value === '__auto__' ? undefined : lightColdSource.value,
      message_limit: lightColdLimit.value || 1,
      persist: true,
    })
    if (lightColdResult.value.persisted) {
      message.success('轻量冷启动已固定，可以复制请求头')
    }
  } catch {
    lightColdResult.value = null
    message.error('生成轻量冷启动失败')
  } finally {
    lightColdLoading.value = false
  }
}

async function copyColdHeader(sessionTag: string) {
  await navigator.clipboard.writeText(coldHeader(sessionTag))
  message.success('请求头已复制')
}

</script>

<template>
  <div class="config-page" data-testid="page-config">
    <NSpace class="status-bar" align="center">
      <template v-if="health">
        <NTag size="small" round class="tag-ok">Running</NTag>
        <NTag :type="health.supabase ? 'success' : 'error'" size="small" round>
          Supabase {{ health.supabase ? 'connected' : 'offline' }}
        </NTag>
        <NTag :type="health.store ? 'success' : 'warning'" size="small" round>
          SQLite {{ health.store ? 'ready' : 'offline' }}
        </NTag>
        <NTag size="small">{{ health.protocol }}</NTag>
      </template>
      <NTag v-else size="small" round class="tag-err">Disconnected</NTag>
    </NSpace>

    <div class="cfg-grid">
      <NCard title="上游 API" size="small">
        <NSpace vertical size="medium">
          <div>
            <div style="font-size:12px;color:var(--sy-mute);margin-bottom:6px">预设</div>
            <div class="preset-bar">
              <span v-if="!presets.length" style="font-size:11px;color:#484f58">暂无预设，输入名称保存当前上游配置</span>
              <div
                v-for="preset in presets"
                :key="preset.name"
                class="preset-chip"
                :class="{ active: preset.name === activePresetName }"
                @click="applyPreset(preset.name)"
              >
                {{ preset.name }}
                <span class="del" @click.stop="deletePreset(preset.name)">×</span>
              </div>
            </div>
            <div class="preset-save-row">
              <input v-model="presetName" placeholder="输入名称保存当前配置…" class="cal-input" style="flex:1">
              <NButton size="tiny" @click="saveCurrentPreset">保存预设</NButton>
            </div>
          </div>

          <NForm label-placement="top">
            <NFormItem label="接口地址">
              <NInput data-testid="config-upstream-url" v-model:value="config.upstream_url" placeholder="https://api.anthropic.com" />
            </NFormItem>
            <NFormItem label="API Key">
              <NInput v-model:value="config.upstream_api_key" type="password" show-password-on="click" />
            </NFormItem>
            <NFormItem label="协议">
              <NSelect v-model:value="config.upstream_protocol" :options="protocolOptions" />
            </NFormItem>
            <NFormItem label="OpenAI 格式缓存断点">
              <div class="switch-row">
                <NSwitch v-model:value="config.enable_openai_cache_control" />
                <NSelect
                  v-model:value="config.openai_cache_ttl"
                  :options="cacheTtlOptions"
                  :disabled="!config.enable_openai_cache_control"
                  style="width: 120px"
                />
              </div>
            </NFormItem>
            <NFormItem label="Anthropic 格式缓存断点">
              <div class="switch-row">
                <NSwitch v-model:value="config.enable_anthropic_cache_control" />
                <NSelect
                  v-model:value="config.anthropic_cache_ttl"
                  :options="cacheTtlOptions"
                  :disabled="!config.enable_anthropic_cache_control"
                  style="width: 120px"
                />
              </div>
            </NFormItem>
            <NFormItem label="Anthropic adaptive thinking">
              <div class="switch-row">
                <NSwitch
                  v-model:value="config.enable_anthropic_auto_thinking"
                  :disabled="config.upstream_protocol !== 'anthropic'"
                />
                <NSelect
                  v-model:value="config.anthropic_auto_thinking_effort"
                  :options="anthropicThinkingEffortOptions"
                  :disabled="config.upstream_protocol !== 'anthropic' || !config.enable_anthropic_auto_thinking"
                  style="width: 220px"
                />
                <span class="switch-hint">默认档不添加 effort；Max 与 XHigh 只影响新回合，工具续轮沿用开始时的档位。</span>
              </div>
            </NFormItem>
            <div class="upstream-custom-box">
              <div class="upstream-custom-title">请求主体定制（extra body）</div>
              <div class="snippet-row">
                <span class="snippet-label">片段预设：</span>
                <NButton
                  v-for="snippet in extraBodySnippets"
                  :key="snippet.value"
                  size="tiny"
                  quaternary
                  @click="insertExtraBodySnippet(snippet.value)"
                >
                  {{ snippet.label }}
                </NButton>
              </div>
              <NInput
                v-model:value="upstreamExtraBodyText"
                type="textarea"
                :autosize="{ minRows: 4, maxRows: 10 }"
                placeholder='{"provider":"Amazon Bedrock"} 或 {"models":["claude-opus-4-7"]}'
              />
              <div class="provider-order-hint">
                保存为 JSON object，会合并进最终请求主体（可覆盖网关内置字段；覆盖 model/messages/tools 会在保存时提醒）。provider 在这里写即可，无需单独开关。
              </div>
            </div>
            <div class="upstream-custom-box">
              <div class="upstream-custom-title">请求头透传白名单</div>
              <div class="snippet-row">
                <span class="snippet-label">常用头：</span>
                <NButton
                  v-for="opt in headerPresetOptions"
                  :key="opt.value"
                  size="tiny"
                  quaternary
                  @click="addPassthroughHeader(opt.value)"
                >
                  {{ opt.label }}
                </NButton>
              </div>
              <NSelect
                v-model:value="config.upstream_passthrough_headers"
                multiple
                filterable
                tag
                clearable
                :options="[]"
                placeholder="输入回车添加，例如 x-api-key"
              />
              <div class="provider-order-hint">
                白名单：只有这里的请求头会从客户端透传到上游。默认 x-api-key。
              </div>
              <div class="protected-headers">
                <span class="snippet-label">始终由网关接管（不透传）：</span>
                <NTag v-for="h in protectedHeaders" :key="h" size="tiny" round>{{ h }}</NTag>
              </div>
            </div>
          </NForm>
        </NSpace>
      </NCard>

      <NCard title="安全与数据库" size="small">
        <NForm label-placement="top">
          <NFormItem label="网关 API Key（留空不校验）">
            <NInput v-model:value="config.gateway_key" type="password" show-password-on="click" placeholder="留空不校验" />
          </NFormItem>
          <NFormItem label="Supabase Project URL">
            <NInput v-model:value="config.supabase_url" placeholder="https://xxx.supabase.co" />
          </NFormItem>
          <NFormItem label="Supabase Service Key">
            <NInput v-model:value="config.supabase_key" type="password" show-password-on="click" :placeholder="config.supabase_key_configured ? '已配置；留空保持不变' : '输入 Service Key'" />
          </NFormItem>
        </NForm>
      </NCard>

      <NCard title="醒来欢迎词" size="small">
        <NForm label-placement="top">
          <NFormItem label="追加到“给醒来的我”之后">
            <NInput
              v-model:value="config.wake_welcome_message"
              type="textarea"
              :autosize="{ minRows: 5, maxRows: 12 }"
              placeholder="留空则保留上一次保存的欢迎词"
            />
            <div class="welcome-actions">
              <NPopconfirm @positive-click="clearWakeWelcomeMessage">
                <template #trigger>
                  <NButton
                    size="tiny"
                    type="error"
                    quaternary
                    :loading="clearingWelcome"
                  >
                    清空欢迎词
                  </NButton>
                </template>
                确认清空醒来欢迎词？
              </NPopconfirm>
            </div>
          </NFormItem>
        </NForm>
      </NCard>

      <NCard title="回响" size="small">
        <NForm label-placement="top">
          <NFormItem label="回响提示词（放在 Heartbeat 之前）">
            <NInput
              v-model:value="config.echo_prompt"
              type="textarea"
              :autosize="{ minRows: 8, maxRows: 18 }"
              placeholder="留空则不要求沈予写回响"
            />
          </NFormItem>
          <NFormItem label="回响随正文保留的后续轮数">
            <NInputNumber v-model:value="config.echo_retention_turns" :min="0" :max="20" style="width: 100%" />
            <div class="provider-order-hint">按后续用户轮数计算；0 表示下一次请求就不再带回。PWA 的历史显示不受这个数字影响。</div>
          </NFormItem>
        </NForm>
      </NCard>

      <NCard title="功能开关" size="small">
        <NForm label-placement="top">
          <NFormItem label="上游 tools 总开关">
            <NSwitch v-model:value="config.enable_upstream_tools" />
          </NFormItem>
          <NFormItem label="启用 shenyu_* 工具">
            <NSwitch v-model:value="config.enable_gateway_tools" />
          </NFormItem>
          <NFormItem label="启用 supabase_* 工具">
            <NSwitch v-model:value="config.expose_supabase_tools" />
          </NFormItem>
          <NFormItem label="网关工具模式">
            <NSelect v-model:value="config.gateway_tool_mode" :options="toolModeOptions" />
          </NFormItem>
          <NFormItem label="普通线程 shenyu_gateway_tool 清单">
            <NSelect v-model:value="config.gateway_tool_surface" :options="gatewayToolSurfaceOptions" />
          </NFormItem>
          <NFormItem label="普通线程客户端工具桌面">
            <NSelect v-model:value="config.client_tool_surface" :options="clientToolSurfaceOptions" />
          </NFormItem>
          <NFormItem label="启用 MCP 外部工具">
            <div class="switch-row">
              <NSwitch v-model:value="config.enable_mcp_tools" data-testid="config-enable-mcp-tools" />
              <span class="switch-hint">关闭后所有 mcp_* 工具从桌面消失，服务器配置保留。</span>
            </div>
          </NFormItem>
        </NForm>
      </NCard>

      <NCard title="MCP 服务器" size="small">
        <McpServersCard />
        <NForm label-placement="top" class="mcp-numbers">
          <NFormItem label="单次调用超时（秒）">
            <NInputNumber v-model:value="config.mcp_call_timeout_seconds" :min="5" :max="600" style="width:100%" />
          </NFormItem>
          <NFormItem label="列工具超时（秒）">
            <NInputNumber v-model:value="config.mcp_list_timeout_seconds" :min="2" :max="120" style="width:100%" />
          </NFormItem>
          <NFormItem label="工具清单缓存（秒）">
            <NInputNumber v-model:value="config.mcp_tools_cache_seconds" :min="10" :max="86400" style="width:100%" />
          </NFormItem>
          <NFormItem label="历史保留最近几条 MCP 结果">
            <NInputNumber v-model:value="config.mcp_tool_result_keep_recent" :min="0" :max="50" style="width:100%" />
            <div class="provider-order-hint">更早的 MCP 工具结果在发给上游前替换成占位符，省 token；0 表示全部替换。这四个数值随页面底部「保存」一起生效。</div>
          </NFormItem>
        </NForm>
      </NCard>

      <NCard title="请求日志" size="small">
        <NForm label-placement="top">
          <NFormItem label="保留完整请求内容">
            <div class="switch-row">
              <NSwitch v-model:value="config.gateway_log_full_payloads" />
              <span class="switch-hint">开启后，新请求在进程内最近 30 条日志里保留完整 Messages、Upstream payload 和 Response；重启后退回预览，持久化历史始终只存安全摘要。这些内容是真实对话，看完建议关掉。</span>
            </div>
          </NFormItem>
        </NForm>
      </NCard>

      <NCard title="窗边报纸质检" size="small">
        <NForm label-placement="top">
          <NFormItem label="启用小模型质检">
            <div class="switch-row">
              <NSwitch v-model:value="config.room_newspaper_qa_enabled" />
              <span class="switch-hint">关闭时由脚本按八二比例随机组刊；开启后模型只能剔除坏条目，不能改写原文。</span>
            </div>
          </NFormItem>
          <NFormItem label="模型">
            <NInput
              v-model:value="config.room_newspaper_llm_model"
              :disabled="!config.room_newspaper_qa_enabled"
              placeholder="例如 gpt-4.1-mini"
            />
          </NFormItem>
          <NFormItem label="协议">
            <NSelect
              v-model:value="config.room_newspaper_llm_protocol"
              :disabled="!config.room_newspaper_qa_enabled"
              :options="inheritedProtocolOptions"
            />
          </NFormItem>
          <NFormItem label="模型 URL">
            <NInput
              v-model:value="config.room_newspaper_llm_url"
              :disabled="!config.room_newspaper_qa_enabled"
              placeholder="留空继承全局上游 URL"
            />
          </NFormItem>
          <NFormItem label="API Key">
            <NInput
              v-model:value="config.room_newspaper_llm_api_key"
              type="password"
              show-password-on="click"
              :disabled="!config.room_newspaper_qa_enabled"
              :placeholder="config.room_newspaper_llm_api_key_configured ? '已配置；留空保持不变' : '留空继承全局 Key'"
            />
          </NFormItem>
        </NForm>
      </NCard>

      <NCard title="天气" size="small">
        <NForm label-placement="top">
          <NFormItem label="城市">
            <NInput v-model:value="config.weather_city" placeholder="邵阳" />
          </NFormItem>
          <NFormItem label="和风 API Key">
            <NInput
              v-model:value="config.qweather_api_key"
              type="password"
              show-password-on="click"
              :placeholder="config.qweather_api_key_configured ? '已配置；留空保持不变' : '留空则天气功能关闭'"
            />
          </NFormItem>
          <NFormItem label="和风 API Host">
            <NInput v-model:value="config.qweather_api_host" placeholder="abcxyz.qweatherapi.com（账号专属 host）" />
          </NFormItem>
          <div class="provider-order-hint">
            Key 或 Host 未配置、上游失败时，状态后缀与 /api/gateway/weather 的天气段自动省略，不影响其他功能。
          </div>
        </NForm>
      </NCard>

      <NCard title="窗外（联网搜索）" size="small">
        <NForm label-placement="top">
          <NFormItem label="Serper API Key">
            <NInput
              v-model:value="config.serper_api_key"
              type="password"
              show-password-on="click"
              :placeholder="config.serper_api_key_configured ? '已配置；留空保持不变' : '留空则 shenyu_web_search 返回未配置'"
            />
          </NFormItem>
          <NFormItem label="Jina Reader API Key">
            <NInput
              v-model:value="config.jina_api_key"
              type="password"
              show-password-on="click"
              :placeholder="config.jina_api_key_configured ? '已配置；留空保持不变' : '留空则 shenyu_web_read 会被 Jina 拒绝（机房 IP 不给匿名读）'"
            />
          </NFormItem>
          <div class="provider-order-hint">
            shenyu_web_search 走 Serper（Google 结果，gl=cn/hl=zh-cn）；shenyu_web_read 走 r.jina.ai 取正文。
            Jina 对机房 IP 不开放匿名读，VPS 上必须配 Key（jina.ai 免费注册）。
            Key 缺失或上游失败只影响这两个工具本身，不影响聊天。
          </div>
        </NForm>
      </NCard>

      <NCard title="节奏与窗口" size="small">
        <NForm label-placement="top">
          <NFormItem label="工具回环轮数">
            <NInputNumber v-model:value="config.max_internal_tool_rounds" :min="1" style="width:100%" />
          </NFormItem>
          <NFormItem label="客户端上下文保留">
            <NInputNumber v-model:value="config.max_client_messages" :min="1" :max="500" style="width:100%" clearable placeholder="全部" />
          </NFormItem>
          <NFormItem label="启用冷启动注入">
            <NSwitch v-model:value="config.enable_cold_start" />
          </NFormItem>
          <div class="provider-order-hint">陌生的新请求头会自动接续最新线程；已有旧线程恢复时不会自动跨线程注入。</div>
        </NForm>
        <div class="cold-generator">
          <h3>日常冷启动</h3>
          <div class="provider-order-hint">固定最新线程当前有效窗口，带入数量与“客户端上下文保留”一致。</div>
          <NForm label-placement="top">
            <NFormItem label="新线程名称">
              <NInput v-model:value="dailyColdTag" placeholder="例如 7.12" />
            </NFormItem>
          </NForm>
          <NButton size="small" type="primary" :loading="dailyColdLoading" @click="generateDailyColdStart">生成并固定</NButton>
          <div v-if="dailyColdResult" class="cold-preview">
            <div v-if="!dailyColdResult.would_inject" class="rev-empty">{{ dailyColdResult.skip_reason || '没有可固定的聊天记录' }}</div>
            <template v-else>
              <div class="header-output">
                <code>{{ coldHeader(dailyColdResult.target_session_tag || dailyColdTag.trim()) }}</code>
                <NButton size="tiny" @click="copyColdHeader(dailyColdResult.target_session_tag || dailyColdTag.trim())">复制</NButton>
              </div>
              <div class="rev-meta">
                <span class="rev-pill">来源 {{ dailyColdResult.source_session_tag || '-' }}</span>
                <span class="rev-pill">已固定 {{ dailyColdResult.snapshot?.source_message_count || 0 }} 条</span>
              </div>
            </template>
          </div>
        </div>

        <div class="cold-generator">
          <h3>轻量冷启动</h3>
          <div class="provider-order-hint">为 debug 或分支线程指定来源，只固定少量聊天记录。</div>
          <NForm label-placement="top" class="cold-preview-form">
            <div class="cold-preview-grid">
              <NFormItem label="新线程名称">
                <NInput v-model:value="lightColdTag" placeholder="例如 7.12-debug" />
              </NFormItem>
              <NFormItem label="来源线程">
                <NSelect v-model:value="lightColdSource" filterable :options="sourceSessionOptions" />
              </NFormItem>
              <NFormItem label="带入消息数">
                <NInputNumber v-model:value="lightColdLimit" :min="1" :max="500" style="width:100%" />
              </NFormItem>
            </div>
          </NForm>
          <NButton size="small" type="primary" :loading="lightColdLoading" @click="generateLightColdStart">生成并固定</NButton>
          <div v-if="lightColdResult" class="cold-preview">
            <div v-if="!lightColdResult.would_inject" class="rev-empty">{{ lightColdResult.skip_reason || '没有可固定的聊天记录' }}</div>
            <template v-else>
              <div class="header-output">
                <code>{{ coldHeader(lightColdResult.target_session_tag || lightColdTag.trim()) }}</code>
                <NButton size="tiny" @click="copyColdHeader(lightColdResult.target_session_tag || lightColdTag.trim())">复制</NButton>
              </div>
              <div class="rev-meta">
                <span class="rev-pill">来源 {{ lightColdResult.source_session_tag || '-' }}</span>
                <span class="rev-pill">已固定 {{ lightColdResult.snapshot?.source_message_count || 0 }} 条</span>
              </div>
            </template>
          </div>
        </div>
        <div class="rev-toolbar"><NButton size="tiny" @click="loadOverview">刷新统计</NButton></div>
        <div v-if="overview" class="overview-text">
          消息 {{ overview.messages_total }} 条 · 今日 {{ overview.messages_today }} 条 · 窗口 {{ overview.sessions_total }} 个 · 冷启动快照 {{ overview.cold_start_snapshots }} 条
          <br>
          最早：{{ overview.earliest_message_at || '-' }} · 最新：{{ overview.latest_message_at || '-' }}
        </div>
        <div v-else class="rev-empty">尚未加载统计</div>
      </NCard>

    </div>

    <div class="actions">
      <NButton type="primary" :loading="saving || !!switchingPreset" block @click="doSave">保存配置</NButton>
    </div>

    <NLayoutFooter bordered class="footer">shenyu-gateway v0.3.0</NLayoutFooter>
  </div>
</template>

<style scoped>
.config-page {
  margin: 0 auto;
  max-width: 980px;
}

.status-bar {
  justify-content: flex-end;
  margin: 0 auto 12px;
  max-width: 980px;
}

.cfg-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: 1fr 1fr;
}

.cfg-inline {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.actions {
  margin-top: 16px;
}

.welcome-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}

.footer {
  color: #484f58;
  font-size: 12px;
  padding: 12px;
  text-align: center;
  margin-top: 16px;
}

.preset-bar {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 10px;
}

.preset-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 999px;
  font-size: 11px;
  background: var(--sy-paper, #fff);
  color: #4b5563;
  cursor: pointer;
  border: 1px solid #d0d7de;
  transition: 0.15s;
}

.preset-chip:hover {
  background: #f5f5f5;
  color: var(--sy-ink);
}

.preset-chip.active {
  background: var(--sy-rose-soft);
  color: var(--sy-rose-d);
  border-color: var(--sy-accent);
}

.preset-chip .del {
  font-size: 9px;
  opacity: 0.5;
  margin-left: 2px;
  cursor: pointer;
}

.preset-chip .del:hover {
  opacity: 1;
  color: #e53e3e;
}

.preset-save-row {
  display: flex;
  gap: 6px;
  align-items: center;
}

.provider-order-hint {
  color: var(--sy-mute);
  font-size: 11px;
  line-height: 1.5;
}

.provider-order-hint {
  margin-top: 6px;
}

.upstream-custom-box {
  border: 1px solid var(--sy-hair-2);
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 12px;
}

.upstream-custom-title {
  color: var(--sy-ink);
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 8px;
}

.snippet-row {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
  margin-bottom: 8px;
}

.snippet-label {
  color: var(--sy-mute);
  font-size: 11px;
}

.protected-headers {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
  margin-top: 8px;
}

.switch-row {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.switch-hint {
  color: var(--sy-mute);
  font-size: 11px;
  line-height: 1.5;
}

.cal-input {
  background: var(--sy-paper, #fff);
  border: 1px solid #d0d7de;
  color: var(--sy-ink);
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
}

.cal-input:focus {
  outline: none;
  border-color: var(--sy-accent);
}

.rev-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.cold-generator {
  border-top: 1px solid #eceff3;
  margin-top: 14px;
  padding-top: 14px;
}

.cold-generator h3 {
  font-size: 14px;
  margin: 0 0 6px;
}

.header-output {
  align-items: center;
  background: #f6f8fa;
  border: 1px solid #d8dee4;
  border-radius: 8px;
  display: flex;
  gap: 8px;
  justify-content: space-between;
  padding: 8px 10px;
}

.header-output code {
  overflow-wrap: anywhere;
}

.cold-preview-form {
  margin-top: 8px;
}

.cold-preview-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: 1.2fr 1.2fr 0.8fr;
}

.cold-preview-grid :deep(.n-form-item) {
  margin-bottom: 0;
}

.overview-text {
  font-size: 12px;
  color: var(--sy-mute);
  line-height: 1.6;
  margin-bottom: 10px;
}

.rev-empty {
  padding: 18px 0;
  text-align: center;
  color: #6b7280;
  font-size: 12px;
}

.cold-preview {
  display: grid;
  gap: 10px;
}

.rev-card {
  background: var(--sy-paper, #fafafa);
  border: 1px solid var(--sy-hair-2);
  border-radius: 8px;
  padding: 10px;
}

.rev-card h4 {
  font-size: 13px;
  color: #333;
  margin-bottom: 6px;
}

.rev-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.rev-pill {
  background: var(--sy-sys-surface);
  border: 1px solid #e5e7eb;
  color: #4b5563;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 11px;
}

.rev-body {
  font-size: 12px;
  line-height: 1.55;
  color: var(--sy-ink);
  white-space: pre-wrap;
}

.model-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

@media (max-width: 900px) {
  .cfg-grid,
  .cfg-inline,
  .cold-preview-grid {
    grid-template-columns: 1fr;
  }
}
</style>
