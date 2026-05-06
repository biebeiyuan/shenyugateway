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
  NLayout,
  NLayoutContent,
  NLayoutFooter,
  NLayoutHeader,
  NPopconfirm,
  NSelect,
  NSpace,
  NTag,
  useMessage,
} from 'naive-ui'
import { fetchConfig, fetchHealth, saveConfig, type GatewayConfig, type HealthStatus } from '@/api/config'

interface UpstreamPreset {
  name: string
  url: string
  key: string
  protocol: string
  proto?: string
}

const PRESETS_KEY = 'shenyu_upstream_presets'

const message = useMessage()
const config = ref<GatewayConfig>({
  gateway_key: '',
  upstream_url: '',
  upstream_api_key: '',
  upstream_protocol: 'auto',
  supabase_url: '',
  supabase_key: '',
  model_mapping: {},
})

const health = ref<HealthStatus | null>(null)
const saving = ref(false)
const switchingPreset = ref('')
const presetName = ref('')
const presets = ref<UpstreamPreset[]>([])
const modelEntries = ref<[string, string][]>([])

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
  await loadConfig()
  await checkHealth()
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
    message.error('Failed to load config. Log in again if the session expired.')
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
      supabase_url: config.value.supabase_url,
      supabase_key: config.value.supabase_key,
      model_mapping: Object.fromEntries(modelEntries.value.filter(([key, value]) => key && value)),
    }
    const result = await saveConfig(body)
    message.success(`Saved ${result.changed.length} field${result.changed.length === 1 ? '' : 's'} and updated .env`)
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
    message.success(`Switched to ${name}; updated ${result.changed.length} field${result.changed.length === 1 ? '' : 's'}`)
    await checkHealth()
  } catch {
    message.error(`Failed to switch to ${name}`)
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

function addModel() {
  modelEntries.value.push(['', ''])
}

function removeModel(index: number) {
  modelEntries.value.splice(index, 1)
}
</script>

<template>
  <NLayout>
        <NLayoutHeader bordered class="topbar">
          <h1>Shenyu Gateway</h1>
          <NSpace class="status" align="center">
            <template v-if="health">
              <NTag type="success" size="small" round>Running</NTag>
              <NTag :type="health.supabase ? 'success' : 'error'" size="small" round>
                Supabase {{ health.supabase ? 'connected' : 'offline' }}
              </NTag>
              <NTag :type="health.store ? 'success' : 'warning'" size="small" round>
                SQLite {{ health.store ? 'ready' : 'offline' }}
              </NTag>
              <NTag type="default" size="small">{{ health.models?.length || 0 }} models · {{ health.protocol }}</NTag>
            </template>
            <NTag v-else type="error" size="small" round>Disconnected</NTag>
            <RouterLink to="/sessions" class="nav-link">Sessions</RouterLink>
          </NSpace>
        </NLayoutHeader>

        <NLayoutContent content-style="padding: 20px 24px; max-width: 760px; margin: 0 auto">
          <NGrid cols="1" responsive="screen" :x-gap="16" :y-gap="16">
            <NGi>
              <NCard title="Gateway Security" size="small">
                <NForm label-placement="top">
                  <NFormItem label="Gateway API key">
                    <NInput v-model:value="config.gateway_key" type="password" show-password-on="click" />
                  </NFormItem>
                </NForm>
              </NCard>
            </NGi>

            <NGi>
              <NCard title="Upstream API" size="small">
                <NSpace vertical size="medium">
                  <NSpace align="center">
                    <NSelect
                      :value="activePresetName"
                      :options="presetOptions"
                      :loading="!!switchingPreset"
                      placeholder="Switch preset"
                      clearable
                      style="min-width: 220px"
                      @update:value="applyPreset"
                    />
                    <NInput v-model:value="presetName" placeholder="Preset name" style="width: 180px" />
                    <NButton @click="saveCurrentPreset">Save Preset</NButton>
                  </NSpace>

                  <NSpace v-if="presets.length" size="small" wrap>
                    <NTag
                      v-for="preset in presets"
                      :key="preset.name"
                      :type="preset.name === activePresetName ? 'primary' : 'default'"
                      round
                      closable
                      @click="applyPreset(preset.name)"
                      @close="deletePreset(preset.name)"
                    >
                      {{ preset.name }}
                    </NTag>
                  </NSpace>

                  <NForm label-placement="top">
                    <NFormItem label="Base URL">
                      <NInput v-model:value="config.upstream_url" placeholder="https://api.treegpt.top" />
                    </NFormItem>
                    <NFormItem label="API key">
                      <NInput v-model:value="config.upstream_api_key" type="password" show-password-on="click" />
                    </NFormItem>
                    <NFormItem label="Protocol">
                      <NSelect v-model:value="config.upstream_protocol" :options="protocolOptions" />
                    </NFormItem>
                  </NForm>
                </NSpace>
              </NCard>
            </NGi>

            <NGi>
              <NCard title="Supabase" size="small">
                <NForm label-placement="top">
                  <NFormItem label="Project URL">
                    <NInput v-model:value="config.supabase_url" placeholder="https://xxx.supabase.co" />
                  </NFormItem>
                  <NFormItem label="Service role key">
                    <NInput v-model:value="config.supabase_key" type="password" show-password-on="click" />
                  </NFormItem>
                </NForm>
              </NCard>
            </NGi>

            <NGi>
              <NCard title="Model Mapping" size="small">
                <NSpace vertical size="small">
                  <NSpace v-for="(_, index) in modelEntries" :key="index" align="center">
                    <NInput v-model:value="modelEntries[index][0]" placeholder="Display name" style="flex: 2" />
                    <NInput v-model:value="modelEntries[index][1]" placeholder="Upstream model" style="flex: 3" />
                    <NButton size="small" @click="removeModel(index)">Remove</NButton>
                  </NSpace>
                </NSpace>
                <NButton size="small" style="margin-top: 8px" @click="addModel">Add Row</NButton>
              </NCard>
            </NGi>
          </NGrid>

          <div class="actions">
            <NButton type="primary" :loading="saving" block @click="doSave">Save Config</NButton>
          </div>
        </NLayoutContent>

        <NLayoutFooter bordered class="footer">shenyu-gateway v0.3.0</NLayoutFooter>
  </NLayout>
</template>

<style>
body {
  margin: 0;
  background: #f5f5f5;
  font-family: -apple-system, 'Segoe UI', sans-serif;
}

.topbar {
  align-items: center;
  display: flex;
  height: 56px;
  padding: 0 24px;
}

.topbar h1 {
  color: #4f46e5;
  font-size: 18px;
  margin: 0;
}

.status {
  margin-left: auto;
}

.nav-link {
  color: #4f46e5;
  font-size: 13px;
  text-decoration: none;
}

.actions {
  margin-top: 16px;
}

.footer {
  color: #999;
  font-size: 12px;
  padding: 12px;
  text-align: center;
}
</style>
