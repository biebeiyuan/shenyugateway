<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import {
  NButton,
  NCard,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NInputNumber,
  NLayoutFooter,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  useMessage,
  useNotification,
} from 'naive-ui'
import {
  fetchConfig,
  fetchHealth,
  saveConfig,
  fetchGatewayOverview,
  fetchColdStartPreview,
  fetchAtomicMemories,
  reviewAtomicMemory,
  type GatewayConfig,
  type HealthStatus,
  type GatewayOverview,
  type ColdStartPreview,
  type AtomicMemoryItem,
} from '@/api/config'

interface UpstreamPreset {
  name: string
  url: string
  key: string
  protocol: string
  proto?: string
}

const PRESETS_KEY = 'shenyu_upstream_presets'
const ATOMIC_PROMPT_PRESETS_KEY = 'shenyu_atomic_memory_prompt_presets'

const message = useMessage()
const notification = useNotification()
const config = ref<GatewayConfig>({
  gateway_key: '',
  upstream_url: '',
  upstream_api_key: '',
  upstream_protocol: 'auto',
  upstream_proxy: '',
  upstream_trust_env: false,
  supabase_url: '',
  supabase_key: '',
  max_client_messages: null,
  enable_cold_start: true,
  cold_start_turns: 3,
  cold_start_message_limit: 8,
  cold_start_idle_minutes: 120,
  model_mapping: {},
})

const health = ref<HealthStatus | null>(null)
const saving = ref(false)
const switchingPreset = ref('')
const presetName = ref('')
const presets = ref<UpstreamPreset[]>([])
const atomicPromptPresetName = ref('')
const atomicPromptPresets = ref<Record<string, string>>({})
const modelEntries = ref<[string, string][]>([])
const overview = ref<GatewayOverview | null>(null)
const coldPreview = ref<ColdStartPreview | null>(null)
const atomicItems = ref<AtomicMemoryItem[]>([])
const atomicReviewStatus = ref('all')
const atomicReviewSessionTag = ref('')
const atomicReviewLimit = ref(30)

const protocolOptions = [
  { label: 'Auto detect', value: 'auto' },
  { label: 'OpenAI compatible', value: 'openai' },
  { label: 'Anthropic', value: 'anthropic' },
]

const presetOptions = computed(() =>
  presets.value.map((preset) => ({
    label: preset.name,
    value: preset.name,
  })),
)

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
  loadAtomicPromptPresets()
  await loadConfig()
  await checkHealth()
  await loadOverview()
  await loadAtomicReview()
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
      },
    ]),
  )
  localStorage.setItem(PRESETS_KEY, JSON.stringify(raw))
}

function loadAtomicPromptPresets() {
  try {
    const raw = JSON.parse(localStorage.getItem(ATOMIC_PROMPT_PRESETS_KEY) || '{}')
    atomicPromptPresets.value = Object.fromEntries(
      Object.entries(raw)
        .map(([name, value]) => [name, String(value || '')])
        .filter(([name]) => name.trim()),
    )
  } catch {
    atomicPromptPresets.value = {}
  }
}

function persistAtomicPromptPresets() {
  localStorage.setItem(ATOMIC_PROMPT_PRESETS_KEY, JSON.stringify(atomicPromptPresets.value))
}

function saveAtomicPromptPreset() {
  const name = atomicPromptPresetName.value.trim()
  if (!name) {
    message.warning('Name the prompt preset first')
    return
  }
  atomicPromptPresets.value = {
    ...atomicPromptPresets.value,
    [name]: config.value.atomic_memory_prompt || '',
  }
  persistAtomicPromptPresets()
  atomicPromptPresetName.value = ''
  message.success(`Prompt preset saved: ${name}`)
}

function applyAtomicPromptPreset(name: string) {
  config.value.atomic_memory_prompt = atomicPromptPresets.value[name] || ''
  message.success(`Prompt preset loaded: ${name}`)
}

function deleteAtomicPromptPreset(name: string) {
  const next = { ...atomicPromptPresets.value }
  delete next[name]
  atomicPromptPresets.value = next
  persistAtomicPromptPresets()
  message.success(`Prompt preset deleted: ${name}`)
}

async function loadConfig() {
  try {
    const data = await fetchConfig()
    config.value = data
    modelEntries.value = Object.entries(data.model_mapping || {})
  } catch {
    message.error('Failed to load config')
  }
}

async function doSave() {
  saving.value = true
  try {
    const body: Partial<GatewayConfig> = {
      gateway_key: config.value.gateway_key,
      upstream_url: config.value.upstream_url,
      upstream_api_key: config.value.upstream_api_key,
      upstream_protocol: config.value.upstream_protocol,
      upstream_proxy: config.value.upstream_proxy,
      upstream_trust_env: config.value.upstream_trust_env,
      supabase_url: config.value.supabase_url,
      supabase_key: config.value.supabase_key,
      max_client_messages: config.value.max_client_messages || null,
      enable_cold_start: config.value.enable_cold_start,
      cold_start_turns: config.value.cold_start_turns,
      cold_start_message_limit: config.value.cold_start_message_limit,
      cold_start_idle_minutes: config.value.cold_start_idle_minutes,
      model_mapping: Object.fromEntries(modelEntries.value.filter(([key, value]) => key && value)),
      // atomic memory
      atomic_memory_upstream_url: config.value.atomic_memory_upstream_url,
      atomic_memory_api_key: config.value.atomic_memory_api_key,
      atomic_memory_protocol: config.value.atomic_memory_protocol,
      atomic_memory_model: config.value.atomic_memory_model,
      atomic_memory_prompt: config.value.atomic_memory_prompt,
      extract_atomic_memories: config.value.extract_atomic_memories,
      inject_atomic_memories: config.value.inject_atomic_memories,
      default_atomic_memory_limit: config.value.default_atomic_memory_limit,
      atomic_memory_max_tokens: config.value.atomic_memory_max_tokens,
      atomic_memory_extract_every_turns: config.value.atomic_memory_extract_every_turns,
      atomic_memory_min_score: config.value.atomic_memory_min_score,
      atomic_memory_auto_activate_min_confidence: config.value.atomic_memory_auto_activate_min_confidence,
      // feature toggles
      inject_briefing: config.value.inject_briefing,
      inject_meta_summaries: config.value.inject_meta_summaries,
      inject_surface_passages: config.value.inject_surface_passages,
      enable_gateway_tools: config.value.enable_gateway_tools,
      expose_supabase_tools: config.value.expose_supabase_tools,
      max_internal_tool_rounds: config.value.max_internal_tool_rounds,
      default_surface_limit: config.value.default_surface_limit,
      daily_briefing_ttl_minutes: config.value.daily_briefing_ttl_minutes,
    }
    const result = await saveConfig(body)
    config.value = result.config
    modelEntries.value = Object.entries(result.config.model_mapping || {})
    message.success(`Saved ${result.changed.length} field${result.changed.length === 1 ? '' : 's'}`)
    await checkHealth()
  } catch {
    message.error('Save failed')
  } finally {
    saving.value = false
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

  config.value.upstream_url = preset.url
  config.value.upstream_api_key = preset.key
  config.value.upstream_protocol = preset.protocol

  switchingPreset.value = name
  try {
    const result = await saveConfig({
      upstream_url: preset.url,
      upstream_api_key: preset.key,
      upstream_protocol: preset.protocol,
    })
    config.value = result.config
    modelEntries.value = Object.entries(result.config.model_mapping || {})
    message.success(`Switched to ${name}`)
    notification.success({
      title: '上游预设已切换',
      content: `${name} · ${preset.protocol || 'auto'} · ${preset.url || '未填写 URL'}`,
      duration: 4500,
    })
    await checkHealth()
  } catch {
    message.error(`Failed to switch to ${name}`)
    notification.error({
      title: '上游预设切换失败',
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

async function loadColdPreview() {
  try {
    await loadOverview()
    coldPreview.value = await fetchColdStartPreview()
  } catch {
    coldPreview.value = null
    message.error('Cold start preview failed')
  }
}

async function loadAtomicReview() {
  try {
    const result = await fetchAtomicMemories({
      status: atomicReviewStatus.value,
      limit: Math.max(1, Math.min(200, atomicReviewLimit.value)),
      session_tag: atomicReviewSessionTag.value.trim() || undefined,
    })
    atomicItems.value = result.items || []
  } catch {
    atomicItems.value = []
    message.error('Failed to load atomic memories')
  }
}

function atomicReviewPatch(item: AtomicMemoryItem, status: string) {
  return {
    status,
    content_canonical: item.content_canonical,
    content_surface: item.content_surface,
    quote: item.quote,
    time_hint: item.time_hint,
    subject: item.subject,
    owner: item.owner,
    memory_type: item.memory_type,
    tier: item.tier,
    importance: item.importance,
  }
}

async function doReviewAtomic(item: AtomicMemoryItem, status: string) {
  try {
    await reviewAtomicMemory(item.id, atomicReviewPatch(item, status))
    message.success(status === 'active' ? 'Memory approved' : `Memory ${status}`)
    await loadAtomicReview()
  } catch {
    message.error('Review failed')
  }
}

async function deleteAtomic(item: AtomicMemoryItem) {
  try {
    await reviewAtomicMemory(item.id, { status: 'delete' })
    message.success('Memory returned and deleted')
    await loadAtomicReview()
  } catch {
    message.error('Delete failed')
  }
}

function addModel() {
  modelEntries.value.push(['', ''])
}

function removeModel(index: number) {
  modelEntries.value.splice(index, 1)
}
</script>

<template>
  <div class="config-page">
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
      <!-- Upstream API -->
      <NCard title="上游 API" size="small">
        <NSpace vertical size="medium">
          <div>
            <div style="font-size:12px;color:#7d8590;margin-bottom:6px">预设</div>
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
                <span class="del" @click.stop="deletePreset(preset.name)">✕</span>
              </div>
            </div>
            <div class="preset-save-row">
              <input v-model="presetName" placeholder="输入名称保存当前配置…" class="cal-input" style="flex:1">
              <NButton size="tiny" @click="saveCurrentPreset">保存预设</NButton>
            </div>
          </div>

          <NForm label-placement="top">
            <NFormItem label="接口地址">
              <NInput v-model:value="config.upstream_url" placeholder="https://api.anthropic.com" />
            </NFormItem>
            <NFormItem label="API Key">
              <NInput v-model:value="config.upstream_api_key" type="password" show-password-on="click" />
            </NFormItem>
            <NFormItem label="协议">
              <NSelect v-model:value="config.upstream_protocol" :options="protocolOptions" />
            </NFormItem>
            <NFormItem label="上游代理">
              <NInput v-model:value="config.upstream_proxy" placeholder="可选，例如 http://127.0.0.1:7897" />
            </NFormItem>
            <NFormItem label="读取环境代理">
              <NSwitch v-model:value="config.upstream_trust_env" />
            </NFormItem>
          </NForm>
        </NSpace>
      </NCard>

      <!-- Gateway Security & Supabase -->
      <NCard title="安全与数据库" size="small">
        <NForm label-placement="top">
          <NFormItem label="网关 API Key（留空不校验）">
            <NInput v-model:value="config.gateway_key" type="password" show-password-on="click" />
          </NFormItem>
          <NFormItem label="Supabase Project URL">
            <NInput v-model:value="config.supabase_url" placeholder="https://xxx.supabase.co" />
          </NFormItem>
          <NFormItem label="Supabase Service Key">
            <NInput v-model:value="config.supabase_key" type="password" show-password-on="click" />
          </NFormItem>
        </NForm>
      </NCard>

      <!-- 原子记忆小模型 -->
      <NCard title="原子记忆小模型" size="small">
        <div class="cfg-split">
          <div>
            <NForm label-placement="top">
              <NFormItem label="小模型 URL">
                <NInput v-model:value="config.atomic_memory_upstream_url" placeholder="留空继承日历上游，再留空继承主上游" />
              </NFormItem>
              <NFormItem label="小模型 API Key">
                <NInput v-model:value="config.atomic_memory_api_key" type="password" placeholder="留空继承上游 key" />
              </NFormItem>
              <NFormItem label="小模型协议">
                <NSelect v-model:value="config.atomic_memory_protocol" :options="protocolOptions" />
              </NFormItem>
              <NFormItem label="小模型名">
                <NInput v-model:value="config.atomic_memory_model" placeholder="deepseek-chat / gpt-4.1-mini / claude-3-5-haiku" />
              </NFormItem>
              <NFormItem label="mem0 提取提示词">
                <NSpace vertical size="small">
                  <div class="preset-bar">
                    <span v-if="!Object.keys(atomicPromptPresets).length" style="font-size:11px;color:#484f58">暂无提示词预设</span>
                    <div
                      v-for="(_, name) in atomicPromptPresets"
                      :key="name"
                      class="preset-chip"
                      @click="applyAtomicPromptPreset(String(name))"
                    >
                      {{ name }}
                      <span class="del" @click.stop="deleteAtomicPromptPreset(String(name))">×</span>
                    </div>
                  </div>
                  <div class="preset-save-row">
                    <input v-model="atomicPromptPresetName" placeholder="输入名称保存当前提示词…" class="cal-input" style="flex:1">
                    <NButton size="tiny" @click="saveAtomicPromptPreset">保存提示词预设</NButton>
                  </div>
                  <NInput
                    v-model:value="config.atomic_memory_prompt"
                    type="textarea"
                    :autosize="{ minRows: 5, maxRows: 12 }"
                    placeholder="留空使用内置默认提示词；填写后会完整替换发给 mem0/atomic memory 模型的 system prompt"
                  />
                </NSpace>
              </NFormItem>
            </NForm>
          </div>
          <div>
            <NForm label-placement="top">
              <NFormItem label="回复后异步提取原子记忆">
                <NSwitch v-model:value="config.extract_atomic_memories" />
              </NFormItem>
              <NFormItem label="聊天前注入 active 原子记忆">
                <NSwitch v-model:value="config.inject_atomic_memories" />
              </NFormItem>
              <div class="cfg-inline">
                <NFormItem label="注入数量">
                  <NInputNumber v-model:value="config.default_atomic_memory_limit" :min="1" :max="8" style="width:100%" />
                </NFormItem>
                <NFormItem label="命中阈值 (0-1)">
                  <NInputNumber v-model:value="config.atomic_memory_min_score" :min="0" :max="1" :step="0.01" style="width:100%" />
                </NFormItem>
              </div>
              <NFormItem label="小模型输出预算">
                <NInputNumber v-model:value="config.atomic_memory_max_tokens" :min="512" :max="65536" :step="512" style="width:100%" />
              </NFormItem>
              <NFormItem label="每 N 轮提取一次">
                <NInputNumber v-model:value="config.atomic_memory_extract_every_turns" :min="1" :max="50" style="width:100%" />
              </NFormItem>
              <NFormItem label="自动激活阈值 (0-1)">
                <NInputNumber v-model:value="config.atomic_memory_auto_activate_min_confidence" :min="0" :max="1" :step="0.01" style="width:100%" />
              </NFormItem>
            </NForm>
          </div>
        </div>
      </NCard>

      <!-- 功能开关 -->
      <NCard title="功能开关" size="small">
        <NForm label-placement="top">
          <NFormItem label="注入简报">
            <NSwitch v-model:value="config.inject_briefing" />
          </NFormItem>
          <NFormItem label="注入元摘要">
            <NSwitch v-model:value="config.inject_meta_summaries" />
          </NFormItem>
          <NFormItem label="自动浮现正文">
            <NSwitch v-model:value="config.inject_surface_passages" />
          </NFormItem>
          <NFormItem label="启用 shenyu_* 工具">
            <NSwitch v-model:value="config.enable_gateway_tools" />
          </NFormItem>
          <NFormItem label="启用 supabase_* 工具">
            <NSwitch v-model:value="config.expose_supabase_tools" />
          </NFormItem>
        </NForm>
      </NCard>

      <!-- 节奏参数 + 冷启动 -->
      <NCard title="节奏与窗口" size="small">
        <NForm label-placement="top">
          <div class="cfg-inline">
            <NFormItem label="工具回环轮数 (1-8)">
              <NInputNumber v-model:value="config.max_internal_tool_rounds" :min="1" :max="8" style="width:100%" />
            </NFormItem>
            <NFormItem label="浮现数量">
              <NInputNumber v-model:value="config.default_surface_limit" :min="1" :max="8" style="width:100%" />
            </NFormItem>
          </div>
          <div class="cfg-inline">
            <NFormItem label="简报缓存 (分钟)">
              <NInputNumber v-model:value="config.daily_briefing_ttl_minutes" :min="5" :max="1440" style="width:100%" />
            </NFormItem>
            <NFormItem label="客户端上下文保留 (条，空=全部)">
              <NInputNumber v-model:value="config.max_client_messages" :min="1" :max="500" style="width:100%" clearable placeholder="全部" />
            </NFormItem>
          </div>
          <NFormItem label="启用冷启动注入">
            <NSwitch v-model:value="config.enable_cold_start" />
          </NFormItem>
          <div class="cfg-inline">
            <NFormItem label="冷启动请求数">
              <NInputNumber v-model:value="config.cold_start_turns" :min="1" :max="20" style="width:100%" />
            </NFormItem>
            <NFormItem label="冷启动消息数">
              <NInputNumber v-model:value="config.cold_start_message_limit" :min="1" :max="50" style="width:100%" />
            </NFormItem>
          </div>
          <NFormItem label="旧窗口沉寂多久触发 (分钟)">
            <NInputNumber v-model:value="config.cold_start_idle_minutes" :min="1" :max="10080" style="width:100%" />
          </NFormItem>
        </NForm>
        <div class="rev-toolbar">
          <NButton size="tiny" @click="loadColdPreview">预览下一次冷启动</NButton>
          <NButton size="tiny" @click="loadOverview">刷新统计</NButton>
        </div>
        <div v-if="overview" class="overview-text">
          消息 {{ overview.messages_total }} 条 · 今日 {{ overview.messages_today }} 条 · 窗口 {{ overview.sessions_total }} 个 · 冷启动快照 {{ overview.cold_start_snapshots }} 张<br>
          最早：{{ overview.earliest_message_at || '-' }} · 最新：{{ overview.latest_message_at || '-' }}
        </div>
        <div v-else class="rev-empty">尚未加载统计</div>
        <div v-if="coldPreview" class="cold-preview">
          <div v-if="!coldPreview.would_inject" class="rev-empty">按当前配置，下一次不会注入冷启动内容</div>
          <div v-else v-for="source in coldPreview.sources" :key="source.session_tag" class="rev-card">
            <h4>{{ source.session_tag }} · {{ source.client_name }}</h4>
            <div class="rev-meta">
              <span class="rev-pill">{{ coldPreview.reason }}</span>
              <span class="rev-pill">{{ source.snapshot_at }}</span>
            </div>
            <div class="rev-body">{{ (source.messages || []).map(m => `- ${m.role}: ${m.content}`).join('\n') }}</div>
          </div>
        </div>
      </NCard>

      <!-- Model Mapping -->
      <NCard title="模型映射" size="small">
        <NSpace vertical size="small">
          <div v-for="(_, index) in modelEntries" :key="index" class="model-row">
            <NInput v-model:value="modelEntries[index][0]" placeholder="Display name" style="flex:2" />
            <NInput v-model:value="modelEntries[index][1]" placeholder="Upstream model" style="flex:3" />
            <NButton size="tiny" @click="removeModel(index)">Remove</NButton>
          </div>
        </NSpace>
        <NButton size="tiny" style="margin-top:8px" @click="addModel">Add Row</NButton>
      </NCard>

      <!-- 原子记忆审核 -->
      <NCard title="原子记忆审核" size="small">
        <div class="rev-toolbar">
          <select v-model="atomicReviewStatus" class="cal-input" style="width:160px">
            <option value="all">all</option>
            <option value="proposed">proposed</option>
            <option value="active">active</option>
            <option value="deprecated">deprecated</option>
          </select>
          <input v-model="atomicReviewSessionTag" class="cal-input" style="width:180px" placeholder="session_tag（可选）">
          <input v-model="atomicReviewLimit" class="cal-input" style="width:100px" type="number" min="1" max="200">
          <NButton size="tiny" @click="loadAtomicReview">刷新</NButton>
        </div>
        <div v-if="!atomicItems.length" class="rev-empty">当前筛选没有纸条</div>
        <div v-for="item in atomicItems" :key="item.id" class="rev-card">
          <NForm label-placement="top">
            <NFormItem label="便签正文">
              <NInput v-model:value="item.content_canonical" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" />
            </NFormItem>
            <NFormItem label="前端展示语气">
              <NInput v-model:value="item.content_surface" type="textarea" :autosize="{ minRows: 1, maxRows: 4 }" />
            </NFormItem>
            <div class="cfg-inline">
              <NFormItem label="主体">
                <NSelect
                  v-model:value="item.subject"
                  :options="[
                    { label: '圆圆', value: '圆圆' },
                    { label: '沈予', value: '沈予' },
                    { label: '我们', value: '我们' },
                  ]"
                />
              </NFormItem>
              <NFormItem label="类型">
                <NSelect
                  v-model:value="item.memory_type"
                  :options="[
                    { label: 'preference', value: 'preference' },
                    { label: 'health', value: 'health' },
                    { label: 'emotion', value: 'emotion' },
                    { label: 'commitment', value: 'commitment' },
                    { label: 'project', value: 'project' },
                    { label: 'relation', value: 'relation' },
                    { label: 'boundary', value: 'boundary' },
                    { label: 'routine', value: 'routine' },
                    { label: 'identity', value: 'identity' },
                    { label: 'event', value: 'event' },
                    { label: 'other', value: 'other' },
                  ]"
                />
              </NFormItem>
            </div>
            <div class="cfg-inline">
              <NFormItem label="tier">
                <NInputNumber v-model:value="item.tier" :min="1" :max="4" style="width:100%" />
              </NFormItem>
              <NFormItem label="importance">
                <NInputNumber v-model:value="item.importance" :min="1" :max="5" style="width:100%" />
              </NFormItem>
            </div>
            <div class="cfg-inline">
              <NFormItem label="quote">
                <NInput v-model:value="item.quote" />
              </NFormItem>
              <NFormItem label="time">
                <NInput v-model:value="item.time_hint" />
              </NFormItem>
            </div>
          </NForm>
          <div class="rev-meta">
            <span class="rev-pill">{{ item.status }}</span>
            <span class="rev-pill">{{ item.subject || item.owner || '我们' }}</span>
            <span class="rev-pill">{{ item.memory_type }}</span>
            <span class="rev-pill">tier {{ item.tier }}</span>
            <span class="rev-pill">importance {{ item.importance }}</span>
            <span class="rev-pill">conf {{ item.confidence?.toFixed(2) }}</span>
            <span class="rev-pill">heat {{ item.heat?.toFixed(2) }}</span>
            <span class="rev-pill">{{ item.session_tag || 'default' }}</span>
          </div>
          <div v-if="item.source_excerpt" class="rev-body">
            <b>source:</b><br>{{ item.source_excerpt }}
          </div>
          <div v-if="(item.tags_json?.length || item.entities_json?.length)" class="rev-body">
            <b>tags/entities:</b> {{ (item.tags_json || []).join(', ') }}{{ item.tags_json?.length && item.entities_json?.length ? ' | ' : '' }}{{ (item.entities_json || []).join(', ') }}
          </div>
          <div class="rev-actions">
            <NButton size="tiny" type="primary" @click="doReviewAtomic(item, 'active')">确认放行</NButton>
            <NButton size="tiny" @click="deleteAtomic(item)" style="--n-border:1px solid #f85149;--n-text-color:#f85149">退回（删除）</NButton>
            <NButton size="tiny" @click="doReviewAtomic(item, 'proposed')">重新写</NButton>
          </div>
        </div>
      </NCard>
    </div>

    <div class="actions">
      <NButton type="primary" :loading="saving" block @click="doSave">保存配置</NButton>
    </div>

    <NLayoutFooter bordered class="footer">shenyu-gateway v0.3.0</NLayoutFooter>
  </div>
</template>

<style scoped>
.config-page {
  margin: 0 auto;
  max-width: 860px;
}

.status-bar {
  justify-content: flex-end;
  margin: 0 auto 12px;
  max-width: 860px;
}

.cfg-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: 1fr 1fr;
}

.cfg-split {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
}

.cfg-inline {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 10px;
}

.actions {
  margin-top: 16px;
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
  border-radius: 14px;
  font-size: 11px;
  background: #21262d;
  color: #7d8590;
  cursor: pointer;
  border: 1px solid #30363d;
  transition: 0.15s;
}

.preset-chip:hover {
  background: #30363d;
  color: #e1e4e8;
}

.preset-chip.active {
  background: #8b5cf630;
  color: #a78bfa;
  border-color: #8b5cf6;
}

.preset-chip .del {
  font-size: 9px;
  opacity: 0.5;
  margin-left: 2px;
  cursor: pointer;
}

.preset-chip .del:hover {
  opacity: 1;
  color: #f85149;
}

.preset-save-row {
  display: flex;
  gap: 6px;
  align-items: center;
}

.cal-input {
  background: #0d1117;
  border: 1px solid #30363d;
  color: #e1e4e8;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
}

.cal-input:focus {
  outline: none;
  border-color: #8b5cf6;
}

.rev-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.overview-text {
  font-size: 12px;
  color: #7d8590;
  line-height: 1.6;
  margin-bottom: 10px;
}

.rev-empty {
  padding: 18px 0;
  text-align: center;
  color: #484f58;
  font-size: 12px;
}

.cold-preview {
  display: grid;
  gap: 10px;
}

.rev-card {
  background: #0d1117;
  border: 1px solid #21262d;
  border-radius: 8px;
  padding: 10px;
}

.rev-card h4 {
  font-size: 13px;
  color: #e1e4e8;
  margin-bottom: 6px;
}

.rev-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.rev-pill {
  padding: 2px 7px;
  border-radius: 999px;
  font-size: 10px;
  background: #21262d;
  color: #7d8590;
}

.rev-body {
  font-size: 12px;
  line-height: 1.55;
  color: #c9d1d9;
  white-space: pre-wrap;
  word-break: break-word;
}

.rev-body + .rev-body {
  margin-top: 8px;
}

.rev-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
}

.model-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

@media (max-width: 720px) {
  .cfg-grid,
  .cfg-split,
  .cfg-inline {
    grid-template-columns: 1fr;
  }
}
</style>
