<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NPopconfirm,
  NSelect,
  NSpace,
  NSwitch,
  useMessage,
} from 'naive-ui'
import type { AtomicMemoryItem, AtomicMemoryReviewPatch, GatewayConfig } from '@/api/config'
import {
  activateInlineMemoryPromptPreset,
  activateMem0PromptPreset,
  extractMem0Now,
  fetchAtomicMemories,
  fetchInlineMemoryPromptPresets,
  fetchMem0Config,
  fetchMem0PromptPresets,
  reviewAtomicMemory,
  saveInlineMemoryPromptPreset,
  saveMem0Config,
  saveMem0PromptPreset,
  type AtomicPromptPreset,
} from '@/api/mem0'

const message = useMessage()

const config = ref<GatewayConfig>({
  gateway_key: '',
  upstream_url: '',
  upstream_api_key: '',
  upstream_protocol: 'auto',
  supabase_url: '',
  supabase_key: '',
  max_client_messages: null,
  enable_cold_start: true,
  cold_start_turns: 3,
  cold_start_message_limit: 8,
  cold_start_idle_minutes: 120,
  model_mapping: {},
})

const presets = ref<AtomicPromptPreset[]>([])
const inlinePresets = ref<AtomicPromptPreset[]>([])
const savingConfig = ref(false)
const savingPreset = ref(false)
const savingInlinePreset = ref(false)
const extractingNow = ref(false)
const loadingReview = ref(false)
const deletingMemoryId = ref('')
const presetName = ref('')
const presetNote = ref('')
const inlinePresetName = ref('')
const inlinePresetNote = ref('')
const extractSessionTag = ref('')
const atomicItems = ref<AtomicMemoryItem[]>([])
const atomicReviewStatus = ref('all')
const atomicReviewSessionTag = ref('')
const atomicReviewLimit = ref(30)

const protocolOptions = [
  { label: 'Auto detect', value: 'auto' },
  { label: 'OpenAI compatible', value: 'openai' },
  { label: 'Anthropic', value: 'anthropic' },
]

const activePresetId = computed(() => presets.value.find((item) => item.is_active)?.id || 'default')
const activeInlinePresetId = computed(() => inlinePresets.value.find((item) => item.is_active)?.id || 'default')
const activePresetContent = computed(() => presets.value.find((item) => item.id === activePresetId.value)?.content || '')
const activeInlinePresetContent = computed(() => inlinePresets.value.find((item) => item.id === activeInlinePresetId.value)?.content || '')
const promptDraft = computed({
  get: () => config.value.atomic_memory_prompt || '',
  set: (value: string) => {
    config.value.atomic_memory_prompt = value
  },
})
const inlinePromptDraft = computed({
  get: () => config.value.inline_memory_prompt || '',
  set: (value: string) => {
    config.value.inline_memory_prompt = value
  },
})

onMounted(async () => {
  await Promise.all([loadConfig(), loadPresets(), loadInlinePresets(), loadAtomicReview()])
})

async function loadConfig() {
  try {
    config.value = await fetchMem0Config()
  } catch {
    message.error('Failed to load mem0 config')
  }
}

async function loadPresets() {
  try {
    const data = await fetchMem0PromptPresets()
    presets.value = data.items || []
  } catch {
    presets.value = []
    message.error('Failed to load prompt presets')
  }
}

async function loadInlinePresets() {
  try {
    const data = await fetchInlineMemoryPromptPresets()
    inlinePresets.value = data.items || []
  } catch {
    inlinePresets.value = []
    message.error('Failed to load inline prompt presets')
  }
}

async function doSaveConfig() {
  savingConfig.value = true
  try {
    const result = await saveMem0Config({
      atomic_memory_upstream_url: config.value.atomic_memory_upstream_url,
      atomic_memory_api_key: config.value.atomic_memory_api_key,
      atomic_memory_protocol: config.value.atomic_memory_protocol,
      atomic_memory_model: config.value.atomic_memory_model,
      atomic_memory_prompt: config.value.atomic_memory_prompt,
      enable_inline_memory_capture: config.value.enable_inline_memory_capture,
      inline_memory_prompt: config.value.inline_memory_prompt,
      extract_atomic_memories: config.value.extract_atomic_memories,
      inject_atomic_memories: config.value.inject_atomic_memories,
      default_atomic_memory_limit: config.value.default_atomic_memory_limit,
      atomic_memory_max_tokens: config.value.atomic_memory_max_tokens,
      atomic_memory_extract_every_turns: config.value.atomic_memory_extract_every_turns,
      atomic_memory_min_score: config.value.atomic_memory_min_score,
      atomic_memory_auto_activate_min_confidence: config.value.atomic_memory_auto_activate_min_confidence,
    })
    config.value = { ...config.value, ...result.config }
    message.success('Mem0 config saved')
  } catch {
    message.error('Failed to save mem0 config')
  } finally {
    savingConfig.value = false
  }
}

async function doSavePreset() {
  const name = presetName.value.trim()
  if (!name) {
    message.warning('Name the prompt preset first')
    return
  }
  savingPreset.value = true
  try {
    await saveMem0PromptPreset({
      name,
      note: presetNote.value.trim(),
      content: config.value.atomic_memory_prompt || '',
      is_active: true,
    })
    presetName.value = ''
    presetNote.value = ''
    message.success('Prompt preset saved and activated')
    await Promise.all([loadConfig(), loadPresets()])
  } catch {
    message.error('Failed to save prompt preset')
  } finally {
    savingPreset.value = false
  }
}

async function useBuiltInDefault() {
  try {
    await activateMem0PromptPreset('default')
    await Promise.all([loadConfig(), loadPresets()])
    message.success('Built-in default prompt activated')
  } catch {
    message.error('Failed to activate built-in default')
  }
}

async function activatePreset(item: AtomicPromptPreset) {
  try {
    await activateMem0PromptPreset(item.id)
    await Promise.all([loadConfig(), loadPresets()])
    message.success(`Activated ${item.name}`)
  } catch {
    message.error(`Failed to activate ${item.name}`)
  }
}

async function useInlineBuiltInDefault() {
  try {
    await activateInlineMemoryPromptPreset('default')
    await Promise.all([loadConfig(), loadInlinePresets()])
    message.success('Inline default prompt activated')
  } catch {
    message.error('Failed to activate inline default')
  }
}

async function activateInlinePreset(item: AtomicPromptPreset) {
  try {
    await activateInlineMemoryPromptPreset(item.id)
    await Promise.all([loadConfig(), loadInlinePresets()])
    message.success(`Activated ${item.name}`)
  } catch {
    message.error(`Failed to activate ${item.name}`)
  }
}

async function doSaveInlinePreset() {
  const name = inlinePresetName.value.trim()
  if (!name) {
    message.warning('Name the inline prompt preset first')
    return
  }
  savingInlinePreset.value = true
  try {
    await saveInlineMemoryPromptPreset({
      name,
      note: inlinePresetNote.value.trim(),
      content: config.value.inline_memory_prompt || '',
      is_active: true,
    })
    inlinePresetName.value = ''
    inlinePresetNote.value = ''
    message.success('Inline prompt preset saved and activated')
    await Promise.all([loadConfig(), loadInlinePresets()])
  } catch {
    message.error('Failed to save inline prompt preset')
  } finally {
    savingInlinePreset.value = false
  }
}

async function doExtractNow() {
  extractingNow.value = true
  try {
    const result = await extractMem0Now({
      session_tag: extractSessionTag.value.trim() || undefined,
      model: config.value.atomic_memory_model?.trim() || undefined,
    })
    if (result.ok) {
      message.success(`Extraction finished: ${result.candidate_count || 0} candidates, ${result.inserted_count || 0} inserted`)
      await loadAtomicReview()
    } else {
      message.warning(result.reason || result.error || 'Extraction did not run')
    }
  } catch (error: any) {
    message.error(error?.response?.data?.detail || 'Manual extraction failed')
  } finally {
    extractingNow.value = false
  }
}

async function loadAtomicReview() {
  loadingReview.value = true
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
  } finally {
    loadingReview.value = false
  }
}

function atomicReviewPatch(item: AtomicMemoryItem, status: string): AtomicMemoryReviewPatch {
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
  if (deletingMemoryId.value) return
  deletingMemoryId.value = item.id
  try {
    await reviewAtomicMemory(item.id, { status: 'delete' })
    message.success('Memory deleted')
    await loadAtomicReview()
  } catch {
    message.error('Delete failed')
  } finally {
    deletingMemoryId.value = ''
  }
}
</script>

<template>
  <div class="mem0-page">
    <div class="mem0-grid">
      <NCard title="Mem0 上游与开关" size="small">
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
          <NFormItem label="回复后异步提取原子记忆">
            <NSwitch v-model:value="config.extract_atomic_memories" />
          </NFormItem>
          <NFormItem label="聊天前注入 active 原子记忆">
            <NSwitch v-model:value="config.inject_atomic_memories" />
          </NFormItem>
          <NFormItem label="捕获回复里的 <mem> 内联便签">
            <NSwitch v-model:value="config.enable_inline_memory_capture" />
          </NFormItem>
          <div class="cfg-inline">
            <NFormItem label="注入数量">
              <NInputNumber v-model:value="config.default_atomic_memory_limit" :min="1" :max="8" style="width:100%" />
            </NFormItem>
            <NFormItem label="命中阈值">
              <NInputNumber v-model:value="config.atomic_memory_min_score" :min="0" :max="1" :step="0.01" style="width:100%" />
            </NFormItem>
          </div>
          <div class="cfg-inline">
            <NFormItem label="输出预算">
              <NInputNumber v-model:value="config.atomic_memory_max_tokens" :min="512" :max="65536" :step="512" style="width:100%" />
            </NFormItem>
            <NFormItem label="每 N 轮提取一次">
              <NInputNumber v-model:value="config.atomic_memory_extract_every_turns" :min="1" :max="50" style="width:100%" />
            </NFormItem>
          </div>
          <NFormItem label="自动激活阈值（当前后端默认进 proposed）">
            <NInputNumber v-model:value="config.atomic_memory_auto_activate_min_confidence" :min="0" :max="1" :step="0.01" style="width:100%" />
          </NFormItem>
        </NForm>
        <NSpace vertical size="small">
          <NButton type="primary" :loading="savingConfig" block @click="doSaveConfig">保存 mem0 配置</NButton>
          <div class="extract-row">
            <NInput v-model:value="extractSessionTag" placeholder="session_tag；留空使用 default" />
            <NButton :loading="extractingNow" @click="doExtractNow">立即提取最近 N 轮</NButton>
          </div>
        </NSpace>
      </NCard>

      <NCard title="提示词管理" size="small">
        <NSpace vertical size="small">
          <div class="preset-bar">
            <div class="preset-chip" :class="{ active: activePresetId === 'default' }" @click="useBuiltInDefault">
              Built-in Default
            </div>
            <div
              v-for="item in presets"
              :key="item.id"
              class="preset-chip"
              :class="{ active: item.id === activePresetId }"
              @click="activatePreset(item)"
            >
              {{ item.name }} v{{ item.version }}
            </div>
          </div>
          <NInput
            v-model:value="promptDraft"
            type="textarea"
            :autosize="{ minRows: 8, maxRows: 16 }"
            placeholder="留空时使用内置默认提示词；填写后会覆盖 mem0 system prompt"
          />
          <NInput
            v-if="!promptDraft && activePresetContent"
            :value="activePresetContent"
            type="textarea"
            readonly
            :autosize="{ minRows: 6, maxRows: 10 }"
            placeholder="当前生效的内置默认提示词"
          />
          <div class="preset-save-row">
            <input v-model="presetName" class="cal-input" placeholder="输入名称保存当前提示词…" style="flex:1">
            <input v-model="presetNote" class="cal-input" placeholder="备注（可选）" style="flex:1">
            <NButton size="small" :loading="savingPreset" @click="doSavePreset">保存为预设</NButton>
          </div>
          <div class="hint-text">
            当前编辑框就是实时生效草稿。保存 mem0 配置会直接写入当前 prompt；保存为预设会顺便激活该预设。
          </div>
        </NSpace>
      </NCard>

      <NCard title="Inline <mem> 提示词管理" size="small">
        <NSpace vertical size="small">
          <div class="hint-text">
            沈予回复里的 &lt;mem&gt;...&lt;/mem&gt; 会被过滤，不展示给圆圆；开启后进入后台清洗并默认生成 proposed 候选。
          </div>
          <div class="preset-bar">
            <div class="preset-chip" :class="{ active: activeInlinePresetId === 'default' }" @click="useInlineBuiltInDefault">
              Inline Default
            </div>
            <div
              v-for="item in inlinePresets"
              :key="item.id"
              class="preset-chip"
              :class="{ active: item.id === activeInlinePresetId }"
              @click="activateInlinePreset(item)"
            >
              {{ item.name }} v{{ item.version }}
            </div>
          </div>
          <NInput
            v-model:value="inlinePromptDraft"
            type="textarea"
            :autosize="{ minRows: 8, maxRows: 16 }"
            placeholder="留空时使用内置 inline <mem> 默认提示词"
          />
          <NInput
            v-if="!inlinePromptDraft && activeInlinePresetContent"
            :value="activeInlinePresetContent"
            type="textarea"
            readonly
            :autosize="{ minRows: 6, maxRows: 10 }"
            placeholder="当前生效的 inline 默认提示词"
          />
          <div class="preset-save-row">
            <input v-model="inlinePresetName" class="cal-input" placeholder="输入名称保存 inline prompt" style="flex:1">
            <input v-model="inlinePresetNote" class="cal-input" placeholder="备注（可选）" style="flex:1">
            <NButton size="small" :loading="savingInlinePreset" @click="doSaveInlinePreset">保存 inline 预设</NButton>
          </div>
        </NSpace>
      </NCard>
    </div>

    <NCard title="原子记忆审核" size="small" style="margin-top:12px">
      <div class="rev-toolbar">
        <select v-model="atomicReviewStatus" class="cal-input" style="width:160px">
          <option value="all">all</option>
          <option value="proposed">proposed</option>
          <option value="active">active</option>
          <option value="deprecated">deprecated</option>
        </select>
        <input v-model="atomicReviewSessionTag" class="cal-input" style="width:180px" placeholder="session_tag（可选）">
        <input v-model="atomicReviewLimit" class="cal-input" style="width:100px" type="number" min="1" max="200">
        <NButton size="small" :loading="loadingReview" @click="loadAtomicReview">刷新</NButton>
      </div>
      <div v-if="!atomicItems.length" class="rev-empty">当前筛选没有纸条</div>
      <div v-for="item in atomicItems" :key="item.id" class="rev-card">
        <NForm label-placement="top">
          <div class="hint-text" style="margin-bottom:8px">
            <span v-if="item.source_model">???{{ item.source_model }}</span>
            <span v-if="item.supersedes_id" style="margin-left:12px">??????{{ item.supersedes_id }}</span>
            <span v-if="item.valence !== null && item.valence !== undefined" style="margin-left:12px">valence?{{ item.valence }}</span>
            <span v-if="item.arousal !== null && item.arousal !== undefined" style="margin-left:12px">arousal?{{ item.arousal }}</span>
          </div>
          <NFormItem label="便签正文">
            <NInput v-model:value="item.content_canonical" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" />
          </NFormItem>
          <NFormItem label="展示语气">
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
          <span class="rev-pill">{{ item.session_tag || 'default' }}</span>
        </div>
        <div v-if="item.source_excerpt" class="rev-body">
          <b>source:</b><br>{{ item.source_excerpt }}
        </div>
        <div class="rev-actions">
          <NButton size="small" type="primary" @click="doReviewAtomic(item, 'active')">确认放行</NButton>
          <NButton size="small" @click="doReviewAtomic(item, 'proposed')">重新挂起</NButton>
          <NPopconfirm
            positive-text="确认删除"
            negative-text="取消"
            @positive-click="deleteAtomic(item)"
          >
            <template #trigger>
              <NButton size="small" :loading="deletingMemoryId === item.id">删除</NButton>
            </template>
            确定要删除这条原子记忆吗？这个操作会直接删除 Supabase 里的记录。
          </NPopconfirm>
        </div>
      </div>
    </NCard>
  </div>
</template>

<style scoped>
.mem0-page {
  margin: 0 auto;
  max-width: 1200px;
}

.mem0-grid {
  display: grid;
  gap: 12px;
  grid-template-columns: 1fr 1fr;
}

.cfg-inline {
  display: grid;
  gap: 10px;
  grid-template-columns: 1fr 1fr;
}

.preset-bar {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.preset-chip {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: 0 10px;
  border: 1px solid #d0d7de;
  border-radius: 999px;
  background: #fff;
  color: #4b5563;
  cursor: pointer;
}

.preset-chip.active {
  border-color: #4f46e5;
  color: #4f46e5;
  background: #eef2ff;
}

.preset-save-row {
  display: flex;
  gap: 8px;
  align-items: center;
}

.cal-input {
  min-height: 34px;
  padding: 6px 10px;
  border: 1px solid #d0d7de;
  border-radius: 6px;
  background: #fff;
}

.hint-text {
  font-size: 12px;
  color: #6b7280;
}

.extract-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 8px;
}

.rev-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 10px;
}

.rev-empty {
  padding: 18px 0;
  text-align: center;
  color: #6b7280;
  font-size: 12px;
}

.rev-card {
  margin-top: 10px;
  padding: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
}

.rev-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  margin: 8px 0;
}

.rev-pill {
  padding: 2px 8px;
  border-radius: 999px;
  background: #f3f4f6;
  font-size: 11px;
  color: #4b5563;
}

.rev-body {
  margin-top: 8px;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 12px;
  line-height: 1.6;
}

.rev-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
}

@media (max-width: 980px) {
  .mem0-grid,
  .cfg-inline,
  .extract-row {
    grid-template-columns: 1fr;
  }
}
</style>
