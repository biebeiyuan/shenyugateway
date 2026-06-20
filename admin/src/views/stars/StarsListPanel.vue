<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NButton, useMessage } from 'naive-ui'
import { searchStars, type StarCandidate } from '@/api/stars'
import { formatTime, rootLabel } from './starUi'

const emit = defineEmits<{
  (event: 'selectStar', starId: string): void
}>()

const message = useMessage()
const allStars = ref<StarCandidate[]>([])
const loading = ref(false)
const query = ref('')
const sortBy = ref<'time' | 'activation'>('time')

const filteredList = computed(() => {
  let list = [...allStars.value]
  const q = query.value.trim().toLowerCase()
  if (q) {
    list = list.filter(
      (s) =>
        s.content.toLowerCase().includes(q) ||
        (s.chord || '').toLowerCase().includes(q) ||
        (s.chord_root || '').toLowerCase().includes(q),
    )
  }
  if (sortBy.value === 'activation') {
    list.sort((a, b) => (b.activation_count || 0) - (a.activation_count || 0))
  } else {
    list.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''))
  }
  return list
})

function isRecent(star: StarCandidate): boolean {
  if (!star.created_at) return false
  return Date.now() - Date.parse(star.created_at) < 48 * 3600 * 1000
}

onMounted(loadAll)

async function loadAll() {
  loading.value = true
  try {
    const result = await searchStars({ q: '', limit: 500, log_run: false })
    allStars.value = result.items || []
  } catch {
    message.error('加载星列失败')
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="list-space">
    <div class="list-toolbar">
      <input
        v-model="query"
        class="soft-input wide"
        placeholder="搜索星星内容或和弦..."
      >
      <select v-model="sortBy" class="sort-select">
        <option value="time">按时间</option>
        <option value="activation">按激活</option>
      </select>
      <NButton size="small" :loading="loading" @click="loadAll">刷新</NButton>
    </div>

    <div v-if="loading && !allStars.length" class="empty-list">加载中...</div>
    <div v-else-if="!filteredList.length" class="empty-list">没有找到星星</div>

    <div v-else class="star-list">
      <div
        v-for="star in filteredList"
        :key="star.id"
        class="star-list-item"
        :class="{ recent: isRecent(star) }"
      >
        <div class="star-list-row">
          <span v-if="isRecent(star)" class="new-glow"></span>
          <span class="list-chord">{{ rootLabel(star) }}</span>
          <span class="list-content">{{ star.content }}</span>
          <button class="star-jump" type="button" title="跳转星图" @click="emit('selectStar', star.id)">✦</button>
        </div>
        <div class="star-list-meta">
          <span v-if="star.is_constant" class="meta-constant">恒星</span>
          <span>亮 {{ star.activation_count || 0 }}</span>
          <span>{{ formatTime(star.created_at) }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.list-space {
  padding-top: 4px;
}

.list-toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-bottom: 12px;
}

.soft-input {
  min-width: 150px;
  min-height: 34px;
  padding: 6px 10px;
  border: 1px solid #ead4cf;
  border-radius: 6px;
  background: #fff;
  color: #4a3535;
  outline: none;
  transition: border-color 0.16s;
}

.soft-input.wide {
  flex: 1;
  min-width: 200px;
}

.sort-select {
  min-height: 34px;
  padding: 4px 10px;
  border: 1px solid #ead4cf;
  border-radius: 6px;
  background: #fff;
  color: #4a3535;
  outline: none;
}

.star-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 520px;
  overflow-y: auto;
}

.star-list-item {
  padding: 10px 12px;
  border: 1px solid #f0e0dc;
  border-radius: 8px;
  background: #fffdfc;
  transition: border-color 0.16s, box-shadow 0.16s;
}

.star-list-item:hover {
  border-color: #d4a7a2;
  box-shadow: 0 2px 8px rgba(98, 70, 82, 0.06);
}

.star-list-item.recent {
  border-color: #f0d4a8;
  background: linear-gradient(135deg, #fffdf8, #fff8f0);
}

.star-list-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.new-glow {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #e8a860;
  box-shadow: 0 0 6px rgba(232, 168, 96, 0.7);
  animation: pulse-glow 2s ease-in-out infinite;
  flex-shrink: 0;
}

@keyframes pulse-glow {
  0%, 100% { opacity: 1; box-shadow: 0 0 6px rgba(232, 168, 96, 0.7); }
  50% { opacity: 0.5; box-shadow: 0 0 12px rgba(232, 168, 96, 0.4); }
}

.list-chord {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 46px;
  max-width: 80px;
  padding: 2px 8px;
  border: 1px solid #ead4cf;
  border-radius: 999px;
  background: #fffaf8;
  color: #967180;
  font-weight: 700;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-size: 12px;
  flex-shrink: 0;
}

.list-content {
  flex: 1;
  min-width: 0;
  color: #4a3535;
  font-size: 13px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}

.star-jump {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: none;
  background: linear-gradient(135deg, #f5d0a0, #e8a860);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  transition: transform 0.16s, box-shadow 0.16s;
}

.star-jump:hover {
  transform: scale(1.15);
  box-shadow: 0 0 10px rgba(232, 168, 96, 0.5);
}

.star-list-meta {
  display: flex;
  gap: 10px;
  margin-top: 4px;
  font-size: 11px;
  color: #b8a8a3;
}

.meta-constant {
  color: #e5b275;
  font-weight: 600;
}

.empty-list {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100px;
  color: #9b8a88;
  font-size: 13px;
}

@media (max-width: 980px) {
  .soft-input, .soft-input.wide {
    width: 100%;
  }
}
</style>
