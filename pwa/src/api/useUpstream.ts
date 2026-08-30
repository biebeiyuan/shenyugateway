import { computed, ref, watch, type Ref } from 'vue'
import { fetchModels, fetchRuntimeConfig, postUpstreamConfig, type RequestContext } from './client'
import { readUpstreamPresets } from './presets'
import {
  claudeCodeHeaders,
  isClaudeCodeHeaderPreset,
  persistUpstreamHeaders,
  readUpstreamHeaders,
  refreshClaudeCodeSessionId,
  upstreamHeaderSummary,
  upstreamHeadersPayload,
  type UpstreamHeaderEntry,
} from './upstreamHeaders'
import type { ModelOption, UpstreamPreset } from '../types'
import { createId } from '../utils'

// 上游配置：模型、reasoning effort、预设、自定义请求头、运行时上游信息。
//
// 这一整块和聊天本身没有耦合——它只通过 status/errorNotice/busy 说话，所以那三个
// 由调用方注入。从 App.vue 搬出来是因为「改预设文案」不该让人翻到流式代码旁边。
// 行为与搬出前逐字一致，没有顺手改任何东西。

export const STORAGE_MODEL = 'shenyu_pwa_model'
export const STORAGE_EFFORT = 'shenyu_pwa_effort'
export const STORAGE_EXTENDED = 'shenyu_pwa_extended'
export const STORAGE_PRESET = 'shenyu_pwa_preset'
export const STORAGE_STREAM = 'shenyu_pwa_stream'

// 自定义请求头上限。超过就拒绝新增，避免把一屏塞满。
const MAX_UPSTREAM_HEADERS = 20

export type UpstreamDeps = {
  clientContext: () => RequestContext
  status: Ref<string>
  errorNotice: Ref<string>
  busy: Ref<boolean>
}

export function useUpstream(deps: UpstreamDeps) {
  const { clientContext, status, errorNotice, busy } = deps

  const models = ref<ModelOption[]>([])
  const presets = ref<UpstreamPreset[]>([])
  const selectedModel = ref(localStorage.getItem(STORAGE_MODEL) || 'default')
  const effort = ref(localStorage.getItem(STORAGE_EFFORT) || 'medium')
  const extendedThinking = ref(localStorage.getItem(STORAGE_EXTENDED) !== 'false')
  const selectedPresetName = ref(localStorage.getItem(STORAGE_PRESET) || '')
  const streamResponses = ref(localStorage.getItem(STORAGE_STREAM) !== 'false')
  const switchingPreset = ref('')
  const runtimeUpstream = ref({ url: '', protocol: '', extraBody: '' })
  const upstreamHeaders = ref<UpstreamHeaderEntry[]>(readUpstreamHeaders())
  const maxClientMessages = ref<number | null>(null)

  watch(upstreamHeaders, (entries) => persistUpstreamHeaders(entries), { deep: true })

  const currentModel = computed(() => models.value.find((model) => model.id === selectedModel.value))
  const primaryModels = computed(() => models.value.filter((model) => model.primary !== false))
  const secondaryModels = computed(() => models.value.filter((model) => model.primary === false))
  const effectiveEffort = computed(() => (extendedThinking.value ? 'max' : effort.value))
  const customHeaderSummary = computed(() => upstreamHeaderSummary(upstreamHeaders.value))
  const hasActiveUpstreamHeaders = computed(() => Object.keys(upstreamHeadersPayload(upstreamHeaders.value)).length > 0)
  const claudeCodeHeaderSelected = computed(() => isClaudeCodeHeaderPreset(upstreamHeaders.value))
  const currentPreset = computed(() => {
    if (!selectedPresetName.value) return undefined
    return presets.value.find((preset) => preset.name === selectedPresetName.value)
  })

  function modelLabel(model?: ModelOption): string {
    if (model?.label) return model.label
    const id = model?.id || selectedModel.value
    if (id === 'default') return 'Sonnet 4.6'
    const family = /sonnet/i.test(id) ? 'Sonnet' : /opus/i.test(id) ? 'Opus' : /haiku/i.test(id) ? 'Haiku' : ''
    if (family) {
      const match = id.match(new RegExp(`${family}[-_ ]?(\\d+(?:[-_]\\d+)?)`, 'i'))
      const version = match?.[1]?.replace(/[-_]/g, '.')
      return version ? `${family} ${version}` : family
    }
    if (/gpt[-_]?4o/i.test(id)) return 'GPT-4o'
    if (/gpt[-_]?4/i.test(id)) return 'GPT-4'
    if (/gemini/i.test(id)) return 'Gemini'
    return id.replace(/[-_]+/g, ' ')
  }

  function modelDescription(model?: ModelOption): string {
    if (model?.desc) return model.desc
    if (model?.id === 'default' || selectedModel.value === 'default') return 'Fast and capable'
    if (model?.owned_by === 'shenyu' || model?.owned_by === 'shenyu-alias') return 'Gateway alias'
    return currentPreset.value ? `${currentPreset.value.name} model` : 'Default gateway model'
  }

  function modelUpstreamId(model?: ModelOption): string {
    return model?.id || selectedModel.value
  }

  function loadPresets() {
    presets.value = readUpstreamPresets()
  }

  async function loadRuntimeUpstream() {
    try {
      const payload = await fetchRuntimeConfig(clientContext())
      const configuredMessageLimit = Number(payload.max_client_messages)
      maxClientMessages.value = Number.isFinite(configuredMessageLimit) && configuredMessageLimit > 0
        ? Math.floor(configuredMessageLimit)
        : null
      runtimeUpstream.value = {
        url: String(payload.upstream_url || ''),
        protocol: String(payload.upstream_protocol || 'auto'),
        extraBody: JSON.stringify(payload.upstream_extra_body || {}),
      }
      const matching = presets.value.find(
        (preset) => preset.url === runtimeUpstream.value.url && preset.protocol === runtimeUpstream.value.protocol,
      )
      if (matching) {
        selectedPresetName.value = matching.name
        localStorage.setItem(STORAGE_PRESET, matching.name)
      }
    } catch {
      // The preset selector remains usable even when config read access is protected.
    }
  }

  async function loadModels() {
    try {
      const payload = await fetchModels(clientContext())
      const list = Array.isArray(payload.data) ? payload.data : []
      models.value = list as ModelOption[]
    } catch {
      models.value = []
    }
  }

  function selectModel(id: string) {
    selectedModel.value = id
    localStorage.setItem(STORAGE_MODEL, id)
  }

  async function selectPreset(preset: UpstreamPreset): Promise<boolean> {
    if (switchingPreset.value) return false
    let extraBody: Record<string, unknown> = {}
    if (preset.extra_body?.trim()) {
      try {
        const parsed = JSON.parse(preset.extra_body)
        if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) throw new Error('extra body must be an object')
        extraBody = parsed as Record<string, unknown>
      } catch {
        errorNotice.value = `预设 ${preset.name} 的 extra body 不是有效 JSON。`
        return false
      }
    }
    const body: Record<string, unknown> = {
      upstream_url: preset.url,
      upstream_protocol: preset.protocol || 'auto',
      upstream_extra_body: extraBody,
      upstream_passthrough_headers: [...(preset.passthrough_headers || [])],
    }
    if (preset.key) body.upstream_api_key = preset.key
    switchingPreset.value = preset.name
    errorNotice.value = ''
    try {
      await postUpstreamConfig(clientContext(), body)
      runtimeUpstream.value = { url: preset.url, protocol: preset.protocol || 'auto', extraBody: JSON.stringify(extraBody) }
      selectedPresetName.value = preset.name
      localStorage.setItem(STORAGE_PRESET, preset.name)
      models.value = []
      await loadModels()
      status.value = `已切换到 ${preset.name}`
      window.setTimeout(() => { if (!busy.value) status.value = '' }, 1800)
      return true
    } catch (error) {
      errorNotice.value = error instanceof Error ? `预设切换失败：${error.message}` : '预设切换失败。'
      return false
    } finally {
      switchingPreset.value = ''
    }
  }

  function selectEffort(id: string) {
    effort.value = id
    localStorage.setItem(STORAGE_EFFORT, id)
  }

  function toggleExtended() {
    extendedThinking.value = !extendedThinking.value
    localStorage.setItem(STORAGE_EXTENDED, String(extendedThinking.value))
  }

  function toggleStreamResponses() {
    streamResponses.value = !streamResponses.value
    localStorage.setItem(STORAGE_STREAM, String(streamResponses.value))
  }

  function clearUpstreamHeaders() {
    upstreamHeaders.value = []
  }

  function selectClaudeCodeHeaders() {
    upstreamHeaders.value = claudeCodeHeaders()
  }

  function refreshClaudeCodeHeaders() {
    refreshClaudeCodeSessionId()
    upstreamHeaders.value = claudeCodeHeaders()
  }

  function addUpstreamHeader() {
    if (upstreamHeaders.value.length >= MAX_UPSTREAM_HEADERS) {
      errorNotice.value = `自定义请求头最多 ${MAX_UPSTREAM_HEADERS} 项。`
      return
    }
    upstreamHeaders.value = [...upstreamHeaders.value, { id: createId('header'), name: '', value: '' }]
  }

  function removeUpstreamHeader(id: string) {
    upstreamHeaders.value = upstreamHeaders.value.filter((entry) => entry.id !== id)
  }

  return {
    models,
    presets,
    selectedModel,
    effort,
    extendedThinking,
    selectedPresetName,
    streamResponses,
    switchingPreset,
    runtimeUpstream,
    upstreamHeaders,
    maxClientMessages,
    currentModel,
    currentPreset,
    primaryModels,
    secondaryModels,
    effectiveEffort,
    customHeaderSummary,
    hasActiveUpstreamHeaders,
    claudeCodeHeaderSelected,
    modelLabel,
    modelDescription,
    modelUpstreamId,
    loadPresets,
    loadRuntimeUpstream,
    loadModels,
    selectModel,
    selectPreset,
    selectEffort,
    toggleExtended,
    toggleStreamResponses,
    clearUpstreamHeaders,
    selectClaudeCodeHeaders,
    refreshClaudeCodeHeaders,
    addUpstreamHeader,
    removeUpstreamHeader,
  }
}
