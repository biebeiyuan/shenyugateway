<script setup lang="ts">
// 一张原件上「挂着 / 自动连上的」锚点编辑块。
// 阅读卡（AnchorOriginalsOverlay）与想起木板的阅读层（RecallBoard）共用，
// 自己拉数、自己保存，父级只在 saved 后决定是否刷新网。
import { onMounted, ref, watch } from 'vue'
import { NButton, NSelect, NTag, useMessage } from 'naive-ui'
import { loadSourceAnchors, saveSourceAnchors } from './sourceAnchors'

const props = defineProps<{
  sourceTable?: string
  sourceType: string
  sourceId?: string
  anchorOptions: { label: string; value: string }[]
}>()

const emit = defineEmits<{
  (e: 'saved'): void
}>()

const message = useMessage()
const loaded = ref(false)
const saving = ref(false)
const manualIds = ref<string[]>([])
const autoNames = ref<string[]>([])

onMounted(() => void load())
watch(() => [props.sourceTable, props.sourceId], () => void load())

async function load() {
  loaded.value = false
  manualIds.value = []
  autoNames.value = []
  if (!props.sourceTable || !props.sourceId) {
    loaded.value = true
    return
  }
  try {
    const state = await loadSourceAnchors(props.sourceTable, props.sourceId)
    manualIds.value = [...state.manualIds]
    autoNames.value = [...state.autoNames]
  } catch {
    // 关联查询失败不挡阅读，保存按钮保持禁用外的可用态由 loaded 控制
  } finally {
    loaded.value = true
  }
}

async function save() {
  if (!props.sourceTable || !props.sourceId || saving.value) return
  saving.value = true
  try {
    const state = await saveSourceAnchors({
      source_table: props.sourceTable,
      source_type: props.sourceType,
      source_id: props.sourceId,
      manualIds: manualIds.value,
    })
    manualIds.value = [...state.manualIds]
    autoNames.value = [...state.autoNames]
    message.success('这张纸挂好了')
    emit('saved')
  } catch {
    message.error('保存关联失败')
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <div class="attach">
    <span class="attach-label">挂着</span>
    <NSelect
      :value="manualIds"
      multiple
      filterable
      clearable
      size="small"
      :options="anchorOptions"
      :disabled="!loaded || saving || !sourceTable"
      placeholder="关联锚点"
      class="attach-select"
      @update:value="(v: string[]) => (manualIds = v)"
    />
    <NButton size="small" :disabled="!loaded || !sourceTable" :loading="saving" @click="save">保存关联</NButton>
    <div v-if="autoNames.length" class="attach-auto">
      <span class="attach-label">自动连上的</span>
      <NTag v-for="name in autoNames" :key="name" size="small" :bordered="false">{{ name }}</NTag>
    </div>
  </div>
</template>

<style scoped>
.attach {
  display: grid;
  grid-template-columns: auto 1fr auto;
  gap: 8px;
  align-items: center;
}

.attach-label {
  font-family: var(--sy-cjk, serif);
  font-size: 12px;
  color: var(--sy-mute, rgba(74, 44, 44, 0.55));
}

.attach-select {
  min-width: 0;
}

.attach-auto {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
</style>
