<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NDataTable,
  NDescriptions,
  NDescriptionsItem,
  NEmpty,
  NInput,
  NPopconfirm,
  NSpace,
  NTag,
  useMessage,
  type DataTableColumns,
} from 'naive-ui'
import {
  deleteGatewaySession,
  fetchGatewaySession,
  fetchGatewaySessions,
  type GatewaySession,
  type GatewaySessionDetail,
} from '@/api/sessions'

const message = useMessage()
const loading = ref(false)
const detailLoading = ref(false)
const deletingTag = ref('')
const query = ref('')
const sessions = ref<GatewaySession[]>([])
const selectedTag = ref('')
const detail = ref<GatewaySessionDetail | null>(null)

const selectedSession = computed(() => detail.value?.session || sessions.value.find((item) => item.session_tag === selectedTag.value))

const columns: DataTableColumns<GatewaySession> = [
  {
    title: '会话标识',
    key: 'session_tag',
    minWidth: 180,
    render(row) {
      return row.session_tag
    },
  },
  {
    title: '客户端',
    key: 'client_name',
    width: 150,
    render(row) {
      return row.client_name || 'unknown'
    },
  },
  {
    title: '消息数',
    key: 'stored_message_count',
    width: 110,
    render(row) {
      return row.stored_message_count || row.message_count || 0
    },
  },
  {
    title: '最后活跃',
    key: 'last_active_at',
    width: 190,
    render(row) {
      return formatTime(row.last_active_at)
    },
  },
  {
    title: '操作',
    key: 'actions',
    width: 160,
    render(row) {
      return [
        hButton('查看', () => selectSession(row.session_tag)),
        hDelete(row),
      ]
    },
  },
]

onMounted(loadSessions)

async function loadSessions() {
  loading.value = true
  try {
    const data = await fetchGatewaySessions({ limit: 200, q: query.value.trim() })
    sessions.value = data.sessions
    if (!selectedTag.value && data.sessions.length) {
      await selectSession(data.sessions[0].session_tag)
    } else if (selectedTag.value && !data.sessions.some((item) => item.session_tag === selectedTag.value)) {
      selectedTag.value = ''
      detail.value = null
    }
  } catch {
    message.error('加载会话列表失败')
  } finally {
    loading.value = false
  }
}

async function selectSession(sessionTag: string) {
  selectedTag.value = sessionTag
  detailLoading.value = true
  try {
    detail.value = await fetchGatewaySession(sessionTag)
  } catch {
    detail.value = null
    message.error('加载会话详情失败')
  } finally {
    detailLoading.value = false
  }
}

async function deleteSession(sessionTag: string) {
  deletingTag.value = sessionTag
  try {
    await deleteGatewaySession(sessionTag)
    message.success(`已删除会话: ${sessionTag}`)
    if (selectedTag.value === sessionTag) {
      selectedTag.value = ''
      detail.value = null
    }
    await loadSessions()
  } catch {
    message.error('删除失败')
  } finally {
    deletingTag.value = ''
  }
}

function formatTime(value: string | null | undefined) {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function shortText(value: string | null | undefined, limit = 180) {
  const text = (value || '').trim()
  if (!text) return '(空)'
  return text.length > limit ? `${text.slice(0, limit - 1).trim()}...` : text
}

function roleType(role: string) {
  if (role === 'user') return 'info'
  if (role === 'assistant') return 'success'
  if (role === 'tool') return 'warning'
  return 'default'
}

function hButton(label: string, onClick: () => void) {
  return h(
    NButton,
    {
      size: 'small',
      quaternary: true,
      type: 'primary',
      onClick,
    },
    { default: () => label },
  )
}

function hDelete(row: GatewaySession) {
  return h(
    NPopconfirm,
    {
      positiveText: '删除',
      negativeText: '取消',
      onPositiveClick: () => deleteSession(row.session_tag),
    },
    {
      trigger: () =>
        h(
          NButton,
          {
            size: 'small',
            quaternary: true,
            type: 'error',
            loading: deletingTag.value === row.session_tag,
          },
          { default: () => '删除' },
        ),
      default: () => `确定删除 ${row.session_tag} 及其所有本地 SQLite 数据？`,
    },
  )
}
</script>

<template>
  <main class="sessions-page">
      <NSpace vertical size="medium">
        <NSpace align="center">
          <NInput
            v-model:value="query"
            placeholder="搜索会话标识或客户端名称"
            clearable
            style="max-width: 320px"
            @keyup.enter="loadSessions"
          />
          <NButton type="primary" :loading="loading" @click="loadSessions">搜索</NButton>
          <NButton :loading="loading" @click="loadSessions">刷新</NButton>
          <NTag type="default">分类: 待处理</NTag>
        </NSpace>

        <div class="grid">
          <NCard title="线程列表" size="small">
            <NDataTable
              :columns="columns"
              :data="sessions"
              :loading="loading"
              :row-key="(row: GatewaySession) => row.session_tag"
              size="small"
              striped
              max-height="620"
            />
          </NCard>

          <NCard title="会话详情" size="small" :loading="detailLoading">
            <template v-if="selectedSession && detail">
              <NDescriptions :column="2" size="small" label-placement="left" bordered>
                <NDescriptionsItem label="会话标识">{{ selectedSession.session_tag }}</NDescriptionsItem>
                <NDescriptionsItem label="客户端">{{ selectedSession.client_name || 'unknown' }}</NDescriptionsItem>
                <NDescriptionsItem label="开始时间">{{ formatTime(selectedSession.started_at) }}</NDescriptionsItem>
                <NDescriptionsItem label="最后活跃">{{ formatTime(selectedSession.last_active_at) }}</NDescriptionsItem>
                <NDescriptionsItem label="消息总数">{{ detail.stats.messages }}</NDescriptionsItem>
                <NDescriptionsItem label="产出物">
                  {{ detail.stats.surface_events }} surface · {{ detail.stats.heartbeats }} 心跳 ·
                  {{ detail.stats.cold_start_snapshots }} 冷启动
                </NDescriptionsItem>
              </NDescriptions>

              <div class="section">
                <h2>最近消息</h2>
                <div v-if="detail.recent_messages.length" class="messages">
                  <div v-for="item in detail.recent_messages" :key="item.id" class="message-row">
                    <NTag size="small" :type="roleType(item.role)">{{ item.role }}</NTag>
                    <div>
                      <div class="message-time">{{ formatTime(item.created_at) }}</div>
                      <div class="message-text">{{ shortText(item.content, 360) }}</div>
                      <div v-if="item.tool_name" class="message-tool">{{ item.tool_name }}</div>
                    </div>
                  </div>
                </div>
                <NEmpty v-else description="暂无消息" />
              </div>

              <NPopconfirm
                positive-text="删除"
                negative-text="取消"
                @positive-click="deleteSession(selectedSession.session_tag)"
              >
                <template #trigger>
                  <NButton type="error" :loading="deletingTag === selectedSession.session_tag">
                    删除此线程
                  </NButton>
                </template>
                删除 {{ selectedSession.session_tag }} 及其所有相关本地 SQLite 数据？
              </NPopconfirm>
            </template>
            <NEmpty v-else description="请选择一个线程" />
          </NCard>
        </div>
      </NSpace>
    </main>
</template>

<style>
.sessions-page {
  margin: 0 auto;
  max-width: 1180px;
}

.grid {
  display: grid;
  gap: 16px;
  grid-template-columns: minmax(440px, 1fr) minmax(420px, 1fr);
}

.section {
  margin-top: 16px;
}

.section h2 {
  font-size: 14px;
  margin: 0 0 8px;
}

.section p {
  color: #666;
  line-height: 1.6;
  margin: 0;
  white-space: pre-wrap;
}

.messages {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.message-row {
  border-bottom: 1px solid #e8e8e8;
  display: grid;
  gap: 10px;
  grid-template-columns: 86px 1fr;
  padding-bottom: 10px;
}

.message-time,
.message-tool {
  color: #bbb;
  font-size: 12px;
}

.message-text {
  color: #1f1f1f;
  line-height: 1.5;
  margin-top: 2px;
  white-space: pre-wrap;
  word-break: break-word;
}

@media (max-width: 900px) {
  .grid {
    grid-template-columns: 1fr;
  }
}
</style>
