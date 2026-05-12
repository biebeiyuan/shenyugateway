<script setup lang="ts">
import { onMounted, ref } from 'vue'
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
  fetchAtomicMemories,
  fetchMem0Config,
  reviewAtomicMemory,
  saveMem0Config,
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
  cold_start_message_limit: null,
  cold_start_idle_minutes: 120,
  model_mapping: {},
})

const savingConfig = ref(false)
const loadingReview = ref(false)
const deletingMemoryId = ref('')
const atomicItems = ref<AtomicMemoryItem[]>([])
const atomicReviewStatus = ref('all')
const atomicReviewSessionTag = ref('')
const atomicReviewLimit = ref(30)

onMounted(async () => {
  await Promise.all([loadConfig(), loadAtomicReview()])
})

async function loadConfig() {
  try {
    config.value = await fetchMem0Config()
  } catch {
    message.error('Failed to load mem0 config')
  }
}

async function doSaveConfig() {
  savingConfig.value = true
  try {
    const result = await saveMem0Config({
      inject_inline_memory_prompt: config.value.inject_inline_memory_prompt,
      default_atomic_memory_limit: config.value.default_atomic_memory_limit,
      atomic_memory_min_score: config.value.atomic_memory_min_score,
    })
    config.value = { ...config.value, ...result.config }
    message.success('Mem0 config saved')
  } catch {
    message.error('Failed to save mem0 config')
  } finally {
    savingConfig.value = false
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
      <NCard title="Mem0 设置" size="small">
        <NForm label-placement="top">
          <NFormItem label="聊天前注入 [mem] 标签提示">
            <NSwitch v-model:value="config.inject_inline_memory_prompt" />
          </NFormItem>
          <div class="cfg-inline">
            <NFormItem label="注入数量">
              <NInputNumber v-model:value="config.default_atomic_memory_limit" :min="1" :max="3" style="width:100%" />
            </NFormItem>
            <NFormItem label="命中阈值">
              <NInputNumber v-model:value="config.atomic_memory_min_score" :min="0" :max="1" :step="0.01" style="width:100%" />
            </NFormItem>
          </div>
        </NForm>
        <NSpace vertical size="small">
          <NButton type="primary" :loading="savingConfig" block @click="doSaveConfig">保存 mem0 配置</NButton>
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
            <span v-if="item.source_model">🤖 {{ item.source_model }}</span>
            <span v-if="item.supersedes_id" style="margin-left:12px">🔄 替代 {{ item.supersedes_id }}</span>
          </div>
          <NFormItem label="便签正文">
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
                  { label: 'emotion', value: 'emotion' },
                  { label: 'commitment', value: 'commitment' },
                  { label: 'fact', value: 'fact' },
                  { label: 'relation', value: 'relation' },
                  { label: 'preference', value: 'preference' },
                  { label: 'boundary', value: 'boundary' },
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
          <span class="rev-pill">{{ item.subject || item.owner || '沈予' }}</span>
          <span class="rev-pill">{{ item.memory_type }}</span>
          <span class="rev-pill">tier {{ item.tier }}</span>
          <span class="rev-pill">importance {{ item.importance }}</span>
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
