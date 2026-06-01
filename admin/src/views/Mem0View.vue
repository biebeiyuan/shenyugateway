<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NCheckbox,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NPopconfirm,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  useMessage,
} from 'naive-ui'
import type {
  GatewayConfig,
  LegacyAtomicMemoryItem,
  MemNoteItem,
  MemNotePatch,
  MemNoteStatus,
  MemNoteType,
} from '@/api/config'
import {
  bulkUpdateMemNotes,
  deleteMemNote,
  fetchLegacyAtomicMemories,
  fetchMem0Config,
  fetchMemNotes,
  saveMem0Config,
  updateMemNote,
} from '@/api/mem0'

const message = useMessage()

const memTypeOptions: Array<{ label: string; value: MemNoteType | '' }> = [
  { label: '未分类', value: '' },
  { label: '她为我做的事', value: '她为我做的事' },
  { label: '我为她做的事', value: '我为她做的事' },
  { label: '关于她的事实', value: '关于她的事实' },
  { label: '关于我的事', value: '关于我的事' },
  { label: '心里那一档', value: '心里那一档' },
  { label: '承诺', value: '承诺' },
]

const statusOptions: Array<{ label: string; value: MemNoteStatus | 'all' }> = [
  { label: '待整理', value: 'captured' },
  { label: '会反上来', value: 'active' },
  { label: '暂停', value: 'paused' },
  { label: '归档', value: 'archived' },
  { label: '全部', value: 'all' },
]

const editStatusOptions = statusOptions.filter((item) => item.value !== 'all')

const config = ref<Partial<GatewayConfig>>({})
const savingConfig = ref(false)

const notes = ref<MemNoteItem[]>([])
const loadingNotes = ref(false)
const savingNoteId = ref('')
const deletingNoteId = ref('')
const bulkSaving = ref(false)
const selectedNoteIds = ref<string[]>([])
const keywordDrafts = ref<Record<string, string>>({})

const noteStatus = ref<MemNoteStatus | 'all'>('captured')
const noteType = ref<MemNoteType | ''>('')
const noteSessionTag = ref('')
const noteQuery = ref('')
const noteLimit = ref(50)

const legacyItems = ref<LegacyAtomicMemoryItem[]>([])
const loadingLegacy = ref(false)
const legacyQuery = ref('')
const legacySessionTag = ref('')
const legacyLimit = ref(30)

const memPromptAndCapture = computed({
  get: () => Boolean(config.value.inject_inline_memory_prompt && config.value.enable_inline_memory_capture),
  set: (enabled: boolean) => {
    config.value.inject_inline_memory_prompt = enabled
    config.value.enable_inline_memory_capture = enabled
  },
})

const selectedNotes = computed(() => notes.value.filter((item) => selectedNoteIds.value.includes(item.id)))
const selectedActivationMissing = computed(() => {
  const missing = selectedNotes.value.map((item) => activationMissing(item)).filter(Boolean)
  return missing[0] || ''
})

onMounted(async () => {
  await Promise.all([loadConfig(), loadNotes()])
})

async function loadConfig() {
  try {
    config.value = await fetchMem0Config()
  } catch {
    message.error('Failed to load mem config')
  }
}

async function saveSettings() {
  savingConfig.value = true
  try {
    const result = await saveMem0Config({
      inject_inline_memory_prompt: memPromptAndCapture.value,
      enable_inline_memory_capture: memPromptAndCapture.value,
      inject_mem_notes: config.value.inject_mem_notes,
      mem_note_limit: config.value.mem_note_limit,
      mem_note_min_score: config.value.mem_note_min_score,
      mem_note_default_cooldown_hours: config.value.mem_note_default_cooldown_hours,
      enable_mem0_management_tools: config.value.enable_mem0_management_tools,
    })
    config.value = { ...config.value, ...result.config }
    message.success('Mem 设置已保存')
  } catch {
    message.error('保存失败')
  } finally {
    savingConfig.value = false
  }
}

async function loadNotes() {
  loadingNotes.value = true
  try {
    const result = await fetchMemNotes({
      status: noteStatus.value,
      limit: Math.max(1, Math.min(200, Number(noteLimit.value || 50))),
      session_tag: noteSessionTag.value.trim() || undefined,
      q: noteQuery.value.trim() || undefined,
      mem_type: noteType.value || undefined,
    })
    notes.value = result.items || []
    keywordDrafts.value = Object.fromEntries(
      notes.value.map((item) => [item.id, (item.trigger_keywords || []).join('，')]),
    )
    const visibleIds = new Set(notes.value.map((item) => item.id))
    selectedNoteIds.value = selectedNoteIds.value.filter((id) => visibleIds.has(id))
  } catch {
    notes.value = []
    keywordDrafts.value = {}
    message.error('读取便签失败')
  } finally {
    loadingNotes.value = false
  }
}

function splitKeywords(value: string): string[] {
  return value
    .split(/[,，、\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function suggestionKeywordsText(item: MemNoteItem): string {
  return (item.suggested_trigger_keywords || []).join('，')
}

function toggleSelected(id: string, checked: boolean) {
  if (checked) {
    if (!selectedNoteIds.value.includes(id)) selectedNoteIds.value = [...selectedNoteIds.value, id]
    return
  }
  selectedNoteIds.value = selectedNoteIds.value.filter((item) => item !== id)
}

function selectVisibleNotes() {
  selectedNoteIds.value = notes.value.map((item) => item.id)
}

function clearSelectedNotes() {
  selectedNoteIds.value = []
}

function applySuggestion(item: MemNoteItem) {
  if (!item.mem_type && item.suggested_mem_type) item.mem_type = item.suggested_mem_type
  if (!(item.trigger_text || '').trim() && item.suggested_trigger_text) item.trigger_text = item.suggested_trigger_text
  if (!splitKeywords(keywordDrafts.value[item.id] || '').length && item.suggested_trigger_keywords?.length) {
    keywordDrafts.value[item.id] = suggestionKeywordsText(item)
  }
}

function applySuggestionsToSelection() {
  const target = selectedNotes.value.length ? selectedNotes.value : notes.value
  target.forEach(applySuggestion)
  message.success(selectedNotes.value.length ? '已给所选便签套用建议' : '已给本页便签套用建议')
}

function notePatch(item: MemNoteItem, status?: MemNoteStatus): MemNotePatch {
  return {
    content: item.content,
    mem_type: item.mem_type || null,
    trigger_text: item.trigger_text || '',
    trigger_keywords: splitKeywords(keywordDrafts.value[item.id] || ''),
    status: status || item.status,
    cooldown_hours: item.cooldown_hours,
    review_note: item.review_note || '',
  }
}

function activationMissing(item: MemNoteItem): string {
  const hasType = Boolean(item.mem_type)
  const hasTrigger = Boolean((item.trigger_text || '').trim()) || splitKeywords(keywordDrafts.value[item.id] || '').length > 0
  if (!hasType && !hasTrigger) return '激活前需要补 type 和触发条件'
  if (!hasType) return '激活前需要补 type'
  if (!hasTrigger) return '激活前需要补触发条件'
  return ''
}

function canActivate(item: MemNoteItem): boolean {
  return !activationMissing(item)
}

async function saveSelectedNotes(status?: MemNoteStatus) {
  if (bulkSaving.value || !selectedNotes.value.length) return
  const missing = status === 'active' ? selectedActivationMissing.value : ''
  if (missing) {
    message.warning(missing)
    return
  }
  bulkSaving.value = true
  try {
    const result = await bulkUpdateMemNotes({
      updates: selectedNotes.value.map((item) => ({
        id: item.id,
        patch: notePatch(item, status),
      })),
    })
    if (!result.ok && result.max_count) {
      message.error(`一次最多处理 ${result.max_count} 条，当前 ${result.requested_count} 条`)
      return
    }
    if (result.failed_count) {
      message.warning(`已保存 ${result.updated_count} 条，失败 ${result.failed_count} 条`)
    } else {
      message.success(status === 'active' ? `已激活 ${result.updated_count} 条` : `已保存 ${result.updated_count} 条`)
    }
    await loadNotes()
  } catch {
    message.error(status === 'active' ? '批量激活失败' : '批量保存失败')
  } finally {
    bulkSaving.value = false
  }
}

async function activateSelectedWithSuggestions() {
  if (bulkSaving.value || !selectedNotes.value.length) return
  bulkSaving.value = true
  try {
    const result = await bulkUpdateMemNotes({
      ids: selectedNoteIds.value,
      patch: { status: 'active' },
      use_suggestions: true,
    })
    if (!result.ok && result.max_count) {
      message.error(`一次最多处理 ${result.max_count} 条，当前 ${result.requested_count} 条`)
      return
    }
    if (result.failed_count) {
      message.warning(`已激活 ${result.updated_count} 条，失败 ${result.failed_count} 条`)
    } else {
      message.success(`已用建议激活 ${result.updated_count} 条`)
    }
    await loadNotes()
  } catch {
    message.error('用建议批量激活失败')
  } finally {
    bulkSaving.value = false
  }
}

async function saveNote(item: MemNoteItem, status?: MemNoteStatus) {
  if (savingNoteId.value) return
  const targetStatus = status || item.status
  const missing = targetStatus === 'active' ? activationMissing(item) : ''
  if (missing) {
    message.warning(missing)
    return
  }
  savingNoteId.value = item.id
  try {
    await updateMemNote(item.id, notePatch(item, status))
    message.success('便签已保存')
    await loadNotes()
  } catch {
    message.error('保存便签失败')
  } finally {
    savingNoteId.value = ''
  }
}

async function removeNote(item: MemNoteItem) {
  if (deletingNoteId.value) return
  deletingNoteId.value = item.id
  try {
    await deleteMemNote(item.id)
    message.success('便签已删除')
    await loadNotes()
  } catch {
    message.error('删除失败')
  } finally {
    deletingNoteId.value = ''
  }
}

async function loadLegacy() {
  loadingLegacy.value = true
  try {
    const result = await fetchLegacyAtomicMemories({
      limit: Math.max(1, Math.min(100, Number(legacyLimit.value || 30))),
      session_tag: legacySessionTag.value.trim() || undefined,
      q: legacyQuery.value.trim() || undefined,
    })
    legacyItems.value = result.items || []
  } catch {
    legacyItems.value = []
    message.error('读取旧表失败')
  } finally {
    loadingLegacy.value = false
  }
}

function statusTagType(status: string) {
  if (status === 'active') return 'success'
  if (status === 'captured') return 'warning'
  if (status === 'paused') return 'info'
  if (status === 'archived') return 'default'
  return 'default'
}

function formatTime(value?: string | null) {
  if (!value) return '-'
  return value.replace('T', ' ').replace(/\.\d+Z?$/, '').replace(/Z$/, '')
}
</script>

<template>
  <div class="mem0-page">
    <NCard title="Mem 设置" size="small">
      <NForm label-placement="top">
        <div class="cfg-inline">
          <NFormItem label="Inline Mem 提示 + 捕获">
            <NSwitch v-model:value="memPromptAndCapture" />
          </NFormItem>
          <NFormItem label="便签反上来">
            <NSwitch v-model:value="config.inject_mem_notes" />
          </NFormItem>
          <NFormItem label="整理工具">
            <NSwitch v-model:value="config.enable_mem0_management_tools" />
          </NFormItem>
        </div>
        <div class="cfg-inline">
          <NFormItem label="反上数量">
            <NInputNumber v-model:value="config.mem_note_limit" :min="1" :max="5" style="width:100%" />
          </NFormItem>
          <NFormItem label="命中阈值">
            <NInputNumber v-model:value="config.mem_note_min_score" :min="0" :max="1" :step="0.01" style="width:100%" />
          </NFormItem>
          <NFormItem label="默认冷却小时">
            <NInputNumber v-model:value="config.mem_note_default_cooldown_hours" :min="0" :max="8760" style="width:100%" />
          </NFormItem>
        </div>
      </NForm>
      <NSpace>
        <NButton type="primary" :loading="savingConfig" @click="saveSettings">保存设置</NButton>
      </NSpace>
    </NCard>

    <NCard title="便签整理" size="small" class="section-card">
      <div class="rev-toolbar">
        <NSelect v-model:value="noteStatus" :options="statusOptions" style="width:140px" />
        <NSelect v-model:value="noteType" :options="memTypeOptions" style="width:170px" />
        <input v-model="noteQuery" class="cal-input" placeholder="搜索正文或触发">
        <input v-model="noteSessionTag" class="cal-input short" placeholder="session_tag">
        <input v-model="noteLimit" class="cal-input tiny" type="number" min="1" max="200">
        <NButton size="small" :loading="loadingNotes" @click="loadNotes">刷新</NButton>
        <NButton size="small" :disabled="!notes.length" @click="selectVisibleNotes">全选本页</NButton>
        <NButton size="small" :disabled="!selectedNoteIds.length" @click="clearSelectedNotes">清空选择</NButton>
        <NButton size="small" :disabled="!notes.length" @click="applySuggestionsToSelection">用建议补齐</NButton>
        <NButton size="small" :loading="bulkSaving" :disabled="!selectedNoteIds.length" @click="saveSelectedNotes()">批量保存</NButton>
        <NButton size="small" type="primary" :loading="bulkSaving" :disabled="!selectedNoteIds.length || Boolean(selectedActivationMissing)" @click="saveSelectedNotes('active')">批量激活</NButton>
        <NPopconfirm positive-text="用建议并激活" negative-text="取消" @positive-click="activateSelectedWithSuggestions">
          <template #trigger>
            <NButton size="small" :loading="bulkSaving" :disabled="!selectedNoteIds.length">建议并激活</NButton>
          </template>
          会把所选便签缺失的 type 和触发条件用建议补齐，然后设为 active。
        </NPopconfirm>
        <NTag v-if="selectedNoteIds.length" size="small">已选 {{ selectedNoteIds.length }}</NTag>
      </div>
      <div v-if="selectedNoteIds.length && selectedActivationMissing" class="ready-hint">
        所选便签里还有：{{ selectedActivationMissing }}
      </div>

      <div v-if="!notes.length" class="rev-empty">当前筛选没有便签</div>
      <div v-for="item in notes" :key="item.id" class="rev-card">
        <div class="rev-meta">
          <NCheckbox :checked="selectedNoteIds.includes(item.id)" @update:checked="(checked) => toggleSelected(item.id, checked)" />
          <NTag size="small" :type="statusTagType(item.status)">{{ item.status }}</NTag>
          <NTag size="small">{{ item.mem_type || '未分类' }}</NTag>
          <NTag v-if="item.suggested_mem_type && item.suggested_mem_type !== item.mem_type" size="small" type="info">
            建议 {{ item.suggested_mem_type }}
          </NTag>
          <NTag size="small">{{ item.session_tag || 'default' }}</NTag>
          <NTag size="small">反上 {{ item.trigger_count || 0 }} 次</NTag>
          <NTag size="small">上次 {{ formatTime(item.last_triggered_at) }}</NTag>
        </div>

        <div v-if="item.suggested_mem_type" class="suggestion-row">
          <span>建议：{{ item.suggested_mem_type }}</span>
          <span v-if="item.suggestion_reason">{{ item.suggestion_reason }}</span>
          <span v-if="suggestionKeywordsText(item)">触发词 {{ suggestionKeywordsText(item) }}</span>
          <NButton size="tiny" @click="applySuggestion(item)">用建议</NButton>
        </div>

        <NForm label-placement="top">
          <NFormItem label="一段话">
            <NInput v-model:value="item.content" type="textarea" :autosize="{ minRows: 2, maxRows: 7 }" />
          </NFormItem>
          <div class="cfg-inline">
            <NFormItem label="type">
              <NSelect v-model:value="item.mem_type" :options="memTypeOptions" />
            </NFormItem>
            <NFormItem label="状态">
              <NSelect v-model:value="item.status" :options="editStatusOptions" />
            </NFormItem>
            <NFormItem label="冷却小时">
              <NInputNumber v-model:value="item.cooldown_hours" :min="0" :max="8760" style="width:100%" />
            </NFormItem>
          </div>
          <NFormItem label="trigger_text（参与命中）">
            <NInput v-model:value="item.trigger_text" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" />
          </NFormItem>
          <div class="cfg-inline two">
            <NFormItem label="trigger_keywords（也参与命中）">
              <NInput v-model:value="keywordDrafts[item.id]" placeholder="用逗号分开" />
            </NFormItem>
            <NFormItem label="整理备注">
              <NInput v-model:value="item.review_note" />
            </NFormItem>
          </div>
        </NForm>

        <div v-if="item.source_excerpt" class="rev-body">
          <b>source</b><br>{{ item.source_excerpt }}
        </div>
        <div v-if="activationMissing(item)" class="ready-hint">
          {{ activationMissing(item) }}
        </div>
        <div class="rev-actions">
          <NButton size="small" type="primary" :loading="savingNoteId === item.id" @click="saveNote(item)">保存</NButton>
          <NButton size="small" :disabled="!canActivate(item)" @click="saveNote(item, 'active')">激活</NButton>
          <NButton size="small" @click="saveNote(item, 'paused')">暂停</NButton>
          <NButton size="small" @click="saveNote(item, 'archived')">归档</NButton>
          <NPopconfirm positive-text="确认删除" negative-text="取消" @positive-click="removeNote(item)">
            <template #trigger>
              <NButton size="small" :loading="deletingNoteId === item.id">删除</NButton>
            </template>
            确定删除这条便签吗？
          </NPopconfirm>
        </div>
      </div>
    </NCard>

    <NCard title="旧 atomic 只读迁移" size="small" class="section-card">
      <div class="rev-toolbar">
        <input v-model="legacyQuery" class="cal-input" placeholder="搜索旧表">
        <input v-model="legacySessionTag" class="cal-input short" placeholder="session_tag">
        <input v-model="legacyLimit" class="cal-input tiny" type="number" min="1" max="100">
        <NButton size="small" :loading="loadingLegacy" @click="loadLegacy">读取旧表</NButton>
      </div>

      <div v-if="!legacyItems.length" class="rev-empty">还没有读取旧表记录</div>
      <div v-for="item in legacyItems" :key="item.id" class="legacy-row">
        <div class="rev-meta">
          <NTag size="small">{{ item.status }}</NTag>
          <NTag size="small">{{ item.subject || item.owner || 'unknown' }}</NTag>
          <NTag size="small">{{ item.memory_type }}</NTag>
          <NTag size="small">{{ item.session_tag || 'default' }}</NTag>
        </div>
        <div class="legacy-main">{{ item.content_surface || item.quote || item.source_excerpt || '-' }}</div>
        <div v-if="item.source_excerpt && item.source_excerpt !== item.content_surface" class="rev-body">
          {{ item.source_excerpt }}
        </div>
      </div>
    </NCard>
  </div>
</template>

<style scoped>
.mem0-page {
  margin: 0 auto;
  max-width: 1180px;
}

.section-card {
  margin-top: 12px;
}

.cfg-inline {
  display: grid;
  gap: 10px;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.cfg-inline.two {
  grid-template-columns: 1fr 1fr;
}

.cal-input {
  min-height: 34px;
  min-width: 180px;
  padding: 6px 10px;
  border: 1px solid #d0d7de;
  border-radius: 6px;
  background: #fff;
}

.cal-input.short {
  min-width: 140px;
}

.cal-input.tiny {
  min-width: 80px;
  width: 90px;
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

.rev-card,
.legacy-row {
  margin-top: 10px;
  padding: 12px;
  border: 1px solid #e5e7eb;
  border-radius: 6px;
  background: #fff;
}

.rev-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  align-items: center;
  margin-bottom: 10px;
}

.suggestion-row {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 10px;
  color: #475569;
  font-size: 12px;
}

.rev-body {
  margin-top: 8px;
  white-space: pre-wrap;
  word-break: break-word;
  color: #4b5563;
  font-size: 12px;
  line-height: 1.6;
}

.rev-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 10px;
}

.ready-hint {
  margin-top: 8px;
  color: #9a3412;
  font-size: 12px;
}

.legacy-main {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}

@media (max-width: 980px) {
  .cfg-inline,
  .cfg-inline.two {
    grid-template-columns: 1fr;
  }

  .cal-input {
    width: 100%;
  }
}
</style>
