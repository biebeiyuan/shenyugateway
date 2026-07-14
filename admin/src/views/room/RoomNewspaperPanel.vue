<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NEmpty, NPopconfirm, NSpin, NTag, useMessage } from 'naive-ui'
import {
  discardNewspaper,
  fetchNewspapers,
  generateNewspaper,
  publishNewspaper,
  type NewspaperIssue,
} from '@/api/room'

const emit = defineEmits<{
  (event: 'published'): void
}>()

const message = useMessage()
const loading = ref(false)
const generating = ref(false)
const publishing = ref(false)
const issues = ref<NewspaperIssue[]>([])

const draftNewspaper = computed(() => issues.value.find((issue) => issue.status === 'draft') || null)
const publishedNewspaper = computed(() => issues.value.find((issue) => issue.status === 'published') || null)
const displayedNewspaper = computed(() => draftNewspaper.value || publishedNewspaper.value)
const sourceFailures = computed(() => displayedNewspaper.value?.source_status?.filter((source) => !source.ok) || [])
const sourceWarnings = computed(() => displayedNewspaper.value?.source_status?.filter((source) => source.warning) || [])

async function reload() {
  loading.value = true
  try {
    const data = await fetchNewspapers(10)
    issues.value = data.issues
  } catch {
    issues.value = []
  } finally {
    loading.value = false
  }
}

async function makeNewspaper() {
  generating.value = true
  try {
    const data = await generateNewspaper()
    message.success(`新一期草稿做好了，共 ${data.issue.item_count} 条`)
    await reload()
  } catch {
    message.error('做报纸失败，请展开来源状态或查看网关日志')
  } finally {
    generating.value = false
  }
}

async function putNewspaperOnSill() {
  const issue = draftNewspaper.value
  if (!issue) return
  publishing.value = true
  try {
    await publishNewspaper(issue.id)
    message.success('报纸已经放到窗台上了')
    emit('published')
    await reload()
  } catch {
    message.error('放到窗台失败')
  } finally {
    publishing.value = false
  }
}

async function throwAwayDraft() {
  const issue = draftNewspaper.value
  if (!issue) return
  try {
    await discardNewspaper(issue.id)
    message.success('草稿已经作废')
    await reload()
  } catch {
    message.error('作废失败')
  }
}

function newspaperDate(iso?: string | null) {
  return iso ? iso.slice(0, 10) : '日期未提供'
}

defineExpose({ reload })
</script>

<template>
  <section class="newspaper-band">
    <div class="section-head newspaper-head">
      <div>
        <span class="panel-kicker">窗台</span>
        <h2>订阅报纸</h2>
      </div>
      <div class="newspaper-actions">
        <NButton size="small" :loading="generating" @click="makeNewspaper">
          {{ draftNewspaper ? '重新做一期' : '做一期新的' }}
        </NButton>
        <NButton
          v-if="draftNewspaper"
          size="small"
          type="primary"
          :loading="publishing"
          @click="putNewspaperOnSill"
        >
          放到窗台
        </NButton>
        <NPopconfirm v-if="draftNewspaper" @positive-click="throwAwayDraft">
          <template #trigger>
            <NButton size="small" quaternary>作废</NButton>
          </template>
          作废这期草稿？
        </NPopconfirm>
      </div>
    </div>

    <NSpin :show="loading || generating || publishing">
      <template v-if="displayedNewspaper">
        <div class="newspaper-meta">
          <NTag size="small" :bordered="false" :type="draftNewspaper ? 'warning' : 'success'">
            {{ draftNewspaper ? '草稿' : (displayedNewspaper.delivered_at ? '沈予翻过了' : '等沈予来翻') }}
          </NTag>
          <span>{{ newspaperDate(displayedNewspaper.published_at || displayedNewspaper.created_at) }}</span>
          <span>{{ displayedNewspaper.item_count }} 条</span>
          <span>兴趣 {{ displayedNewspaper.interest_count }} · 随机 {{ displayedNewspaper.random_count }}</span>
        </div>

        <ol class="newspaper-list">
          <li v-for="item in displayedNewspaper.items" :key="item.id" class="newspaper-item">
            <a :href="item.url" target="_blank" rel="noopener noreferrer">{{ item.title }}</a>
            <p v-if="item.summary">{{ item.summary }}</p>
            <p v-else class="no-summary">这个 RSS 没有提供摘要。</p>
            <div class="newspaper-byline">
              <span>{{ item.source_name }}</span>
              <span>{{ newspaperDate(item.published_at) }}</span>
              <span>{{ item.bucket === 'random' ? '随机页' : '兴趣页' }}</span>
            </div>
          </li>
        </ol>

        <details v-if="draftNewspaper" class="newspaper-details">
          <summary>
            来源 {{ displayedNewspaper.source_status.filter((source) => source.ok).length }}/{{ displayedNewspaper.source_status.length }}
            · 质检{{ displayedNewspaper.qa_detail?.used ? `已运行${displayedNewspaper.qa_detail.model ? ` (${displayedNewspaper.qa_detail.model})` : ''}` : '未运行' }}
          </summary>
          <p v-if="displayedNewspaper.qa_detail?.warning" class="newspaper-warning">
            {{ displayedNewspaper.qa_detail.warning }}
          </p>
          <p v-if="displayedNewspaper.qa_detail?.dropped?.length" class="newspaper-muted">
            质检剔除 {{ displayedNewspaper.qa_detail.dropped.length }} 条。
          </p>
          <div v-if="sourceFailures.length" class="source-failures">
            <div v-for="source in sourceFailures" :key="source.source_id">
              <strong>{{ source.name }}</strong>
              <span>{{ source.error || '没有可用条目' }}</span>
            </div>
          </div>
          <div v-if="sourceWarnings.length" class="source-failures">
            <div v-for="source in sourceWarnings" :key="source.source_id">
              <strong>{{ source.name }}</strong>
              <span>抓到 {{ source.count }} 条，但没有任何一条提供真实摘要，本期未采用。</span>
            </div>
          </div>
          <p v-if="!sourceFailures.length && !sourceWarnings.length" class="newspaper-muted">
            所有来源都成功返回了带摘要的可用条目。
          </p>
        </details>
      </template>
      <NEmpty v-else description="窗台上还没有报纸" class="soft-empty" />
    </NSpin>
  </section>
</template>

<style scoped>
.newspaper-band {
  margin-top: 20px;
  padding: 18px 2px 20px;
  border-top: 1px solid var(--room-line);
  border-bottom: 1px solid var(--room-line);
}

.section-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.newspaper-head {
  align-items: center;
  padding: 0 2px;
}

.panel-kicker {
  display: block;
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 11px;
  color: var(--room-sea);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

h2 {
  margin-top: 3px;
  font-size: 18px;
  font-weight: 600;
  color: var(--room-ink);
  letter-spacing: 0;
}

.newspaper-actions,
.newspaper-meta,
.newspaper-byline {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
}

.newspaper-actions {
  justify-content: flex-end;
  gap: 7px;
}

.newspaper-meta {
  gap: 8px 14px;
  margin-bottom: 6px;
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 12px;
  color: var(--room-muted);
}

.newspaper-list {
  display: grid;
  margin: 0;
  padding: 0;
  list-style: none;
}

.newspaper-item {
  min-width: 0;
  padding: 15px 2px;
  border-bottom: 1px solid #eee6df;
}

.newspaper-item:last-child {
  border-bottom: 0;
}

.newspaper-item > a {
  color: var(--room-ink);
  font-family: Georgia, 'Times New Roman', serif;
  font-size: 17px;
  font-weight: 600;
  line-height: 1.45;
  overflow-wrap: anywhere;
  text-decoration-color: #c9b8ad;
  text-underline-offset: 3px;
}

.newspaper-item > a:hover {
  color: var(--room-sea);
}

.newspaper-item > p {
  max-width: 900px;
  margin: 8px 0 0;
  font-size: 14px;
  line-height: 1.72;
  color: #4e4743;
}

.newspaper-item > p.no-summary {
  color: var(--room-muted);
  font-style: italic;
}

.newspaper-byline {
  gap: 8px 12px;
  margin-top: 8px;
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 11px;
  color: var(--room-muted);
}

.newspaper-details {
  margin-top: 10px;
  padding-top: 12px;
  border-top: 1px dashed var(--room-line);
  font-family: -apple-system, 'Segoe UI', sans-serif;
  font-size: 12px;
  color: var(--room-muted);
}

.newspaper-details summary {
  cursor: pointer;
  user-select: none;
}

.newspaper-warning {
  color: #9a5b39;
}

.newspaper-muted {
  color: var(--room-muted);
}

.source-failures {
  display: grid;
  gap: 7px;
  margin-top: 10px;
}

.source-failures div {
  display: grid;
  gap: 2px;
}

.source-failures strong {
  color: var(--room-ink);
}

.soft-empty {
  padding: 18px 0;
}

@media (max-width: 860px) {
  .newspaper-head {
    align-items: flex-start;
    flex-direction: column;
  }

  .newspaper-actions {
    justify-content: flex-start;
  }
}
</style>
