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

interface UpstreamPreset {
  name: string
  url: string
  key: string
  protocol: string
  proto?: string
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
  enable_openai_cache_control: false,
  hisense_upstream_url: '',
  hisense_api_key: '',
  hisense_protocol: '',
  wake_welcome_message: '',
  supabase_url: '',
  supabase_key: '',
  max_client_messages: null,
  enable_cold_start: true,
  cold_start_message_limit: null,
  cold_start_idle_minutes: 120,
  model_mapping: {},
  enable_upstream_tools: true,
  enable_gateway_tools: true,
  gateway_tool_mode: 'broker',
  inject_inline_memory_prompt: false,
  enable_inline_memory_capture: false,
  inject_mem_notes: false,
})

const health = ref<HealthStatus | null>(null)
const saving = ref(false)
const clearingWelcome = ref(false)
const switchingPreset = ref('')
const presetName = ref('')
const presets = ref<UpstreamPreset[]>([])
const modelEntries = ref<[string, string][]>([])
const overview = ref<GatewayOverview | null>(null)
const coldPreview = ref<ColdStartPreview | null>(null)

const protocolOptions = [
  { label: 'Auto detect', value: 'auto' },
  { label: 'OpenAI compatible', value: 'openai' },
  { label: 'Anthropic', value: 'anthropic' },
]
const inheritedProtocolOptions = [{ label: 'Inherit global', value: '' }, ...protocolOptions]
const toolModeOptions = [
  { label: 'Full schemas', value: 'full' },
  { label: 'Compact broker', value: 'broker' },
]

const activePresetName = computed(() => {
  const match = presets.value.find(
    (preset) =>
      preset.url === config.value.upstream_url &&
      preset.key === config.value.upstream_api_key &&
      preset.protocol === config.value.upstream_protocol,
  )
  return match?.name || null
})

const memPromptAndCapture = computed({
  get: () => Boolean(config.value.inject_inline_memory_prompt && config.value.enable_inline_memory_capture),
  set: (enabled: boolean) => {
    config.value.inject_inline_memory_prompt = enabled
    config.value.enable_inline_memory_capture = enabled
  },
})

let healthTimer: ReturnType<typeof setInterval> | null = null

onMounted(async () => {
  loadPresets()
  await loadConfig()
  await checkHealth()
  await loadOverview()
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
      enable_openai_cache_control: config.value.enable_openai_cache_control,
      hisense_upstream_url: config.value.hisense_upstream_url,
      hisense_api_key: config.value.hisense_api_key,
      hisense_protocol: config.value.hisense_protocol,
      supabase_url: config.value.supabase_url,
      supabase_key: config.value.supabase_key,
      max_client_messages: config.value.max_client_messages || null,
      enable_cold_start: config.value.enable_cold_start,
      cold_start_message_limit: config.value.cold_start_message_limit || null,
      cold_start_idle_minutes: config.value.cold_start_idle_minutes,
      model_mapping: Object.fromEntries(modelEntries.value.filter(([key, value]) => key && value)),
      enable_upstream_tools: config.value.enable_upstream_tools,
      enable_gateway_tools: config.value.enable_gateway_tools,
      inject_inline_memory_prompt: memPromptAndCapture.value,
      enable_inline_memory_capture: memPromptAndCapture.value,
      inject_mem_notes: config.value.inject_mem_notes,
      expose_supabase_tools: config.value.expose_supabase_tools,
      gateway_tool_mode: config.value.gateway_tool_mode,
      max_internal_tool_rounds: config.value.max_internal_tool_rounds,
      default_surface_limit: config.value.default_surface_limit,
    }
    const wakeWelcomeMessage = config.value.wake_welcome_message?.trim()
    if (wakeWelcomeMessage) {
      body.wake_welcome_message = wakeWelcomeMessage
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

async function clearWakeWelcomeMessage() {
  clearingWelcome.value = true
  try {
    const result = await saveConfig({ clear_wake_welcome_message: true })
    config.value = result.config
    modelEntries.value = Object.entries(result.config.model_mapping || {})
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

async function loadColdPreview() {
  try {
    await loadOverview()
    coldPreview.value = await fetchColdStartPreview()
  } catch {
    coldPreview.value = null
    message.error('Cold start preview failed')
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
            <NFormItem label="OpenAI cache_control">
              <NSwitch v-model:value="config.enable_openai_cache_control" />
            </NFormItem>
            <NFormItem label="海信专用接口地址">
              <NInput v-model:value="config.hisense_upstream_url" placeholder="留空继承全局上游" />
            </NFormItem>
            <NFormItem label="海信专用 API Key">
              <NInput v-model:value="config.hisense_api_key" type="password" show-password-on="click" placeholder="留空继承全局 Key" />
            </NFormItem>
            <NFormItem label="海信专用协议">
              <NSelect v-model:value="config.hisense_protocol" :options="inheritedProtocolOptions" />
            </NFormItem>
          </NForm>
        </NSpace>
      </NCard>

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

      <NCard title="功能开关" size="small">
        <NForm label-placement="top">
          <NFormItem label="上游 tools 总开关">
            <NSwitch v-model:value="config.enable_upstream_tools" />
          </NFormItem>
          <NFormItem label="启用 shenyu_* 工具">
            <NSwitch v-model:value="config.enable_gateway_tools" />
          </NFormItem>
          <NFormItem label="Inline Mem 提示 + 捕获">
            <NSwitch v-model:value="memPromptAndCapture" />
          </NFormItem>
          <NFormItem label="Mem 便签反上来">
            <NSwitch v-model:value="config.inject_mem_notes" />
          </NFormItem>
          <NFormItem label="启用 supabase_* 工具">
            <NSwitch v-model:value="config.expose_supabase_tools" />
          </NFormItem>
          <NFormItem label="网关工具模式">
            <NSelect v-model:value="config.gateway_tool_mode" :options="toolModeOptions" />
          </NFormItem>
        </NForm>
      </NCard>

      <NCard title="节奏与窗口" size="small">
        <NForm label-placement="top">
          <div class="cfg-inline">
            <NFormItem label="工具回环轮数">
              <NInputNumber v-model:value="config.max_internal_tool_rounds" :min="1" style="width:100%" />
            </NFormItem>
            <NFormItem label="浮现数量">
              <NInputNumber v-model:value="config.default_surface_limit" :min="1" :max="8" style="width:100%" />
            </NFormItem>
          </div>
          <NFormItem label="客户端上下文保留">
            <NInputNumber v-model:value="config.max_client_messages" :min="1" :max="500" style="width:100%" clearable placeholder="全部" />
          </NFormItem>
          <NFormItem label="启用冷启动注入">
            <NSwitch v-model:value="config.enable_cold_start" />
          </NFormItem>
          <div class="cfg-inline">
            <NFormItem label="换窗补足上限">
              <NInputNumber v-model:value="config.cold_start_message_limit" :min="1" :max="500" style="width:100%" clearable placeholder="跟随客户端上下文保留" />
            </NFormItem>
            <NFormItem label="旧窗口沉寂多久触发（分钟）">
              <NInputNumber v-model:value="config.cold_start_idle_minutes" :min="1" :max="10080" style="width:100%" />
            </NFormItem>
          </div>
        </NForm>
        <div class="rev-toolbar">
          <NButton size="tiny" @click="loadColdPreview">预览下一次冷启动</NButton>
          <NButton size="tiny" @click="loadOverview">刷新统计</NButton>
        </div>
        <div v-if="overview" class="overview-text">
          消息 {{ overview.messages_total }} 条 · 今日 {{ overview.messages_today }} 条 · 窗口 {{ overview.sessions_total }} 个 · 冷启动快照 {{ overview.cold_start_snapshots }} 条
          <br>
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
            <div class="rev-body">{{ (source.messages || []).map((m) => `- ${m.role}: ${m.content}`).join('\n') }}</div>
          </div>
        </div>
      </NCard>

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
  background: #fff;
  color: #4b5563;
  cursor: pointer;
  border: 1px solid #d0d7de;
  transition: 0.15s;
}

.preset-chip:hover {
  background: #f5f5f5;
  color: #1f1f1f;
}

.preset-chip.active {
  background: #eef2ff;
  color: #4f46e5;
  border-color: #4f46e5;
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

.cal-input {
  background: #fff;
  border: 1px solid #d0d7de;
  color: #1f1f1f;
  padding: 4px 8px;
  border-radius: 6px;
  font-size: 12px;
}

.cal-input:focus {
  outline: none;
  border-color: #4f46e5;
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
  color: #6b7280;
  font-size: 12px;
}

.cold-preview {
  display: grid;
  gap: 10px;
}

.rev-card {
  background: #fafafa;
  border: 1px solid #e8e8e8;
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
  background: #f3f4f6;
  border: 1px solid #e5e7eb;
  color: #4b5563;
  border-radius: 999px;
  padding: 2px 8px;
  font-size: 11px;
}

.rev-body {
  font-size: 12px;
  line-height: 1.55;
  color: #1f1f1f;
  white-space: pre-wrap;
}

.model-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

@media (max-width: 900px) {
  .cfg-grid,
  .cfg-inline {
    grid-template-columns: 1fr;
  }
}
</style>
