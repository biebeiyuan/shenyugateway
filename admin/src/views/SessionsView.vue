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
  NLayout,
  NLayoutContent,
  NLayoutHeader,
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
} from '@/api/config'

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
    title: 'Session',
    key: 'session_tag',
    minWidth: 180,
    render(row) {
      return row.session_tag
    },
  },
  {
    title: 'Client',
    key: 'client_name',
    width: 150,
    render(row) {
      return row.client_name || 'unknown'
    },
  },
  {
    title: 'Messages',
    key: 'stored_message_count',
    width: 110,
    render(row) {
      return row.stored_message_count || row.message_count || 0
    },
  },
  {
    title: 'Last Active',
    key: 'last_active_at',
    width: 190,
    render(row) {
      return formatTime(row.last_active_at)
    },
  },
  {
    title: 'Action',
    key: 'actions',
    width: 160,
    render(row) {
      return [
        hButton('View', () => selectSession(row.session_tag)),
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
    message.error('Failed to load sessions')
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
    message.error('Failed to load session detail')
  } finally {
    detailLoading.value = false
  }
}

async function deleteSession(sessionTag: string) {
  deletingTag.value = sessionTag
  try {
    await deleteGatewaySession(sessionTag)
    message.success(`Deleted session: ${sessionTag}`)
    if (selectedTag.value === sessionTag) {
      selectedTag.value = ''
      detail.value = null
    }
    await loadSessions()
  } catch {
    message.error('Delete failed')
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
  if (!text) return '(empty)'
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
      positiveText: 'Delete',
      negativeText: 'Cancel',
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
          { default: () => 'Delete' },
        ),
      default: () => `Delete ${row.session_tag} and its local SQLite data?`,
    },
  )
}
</script>

<template>
  <NLayout>
    <NLayoutHeader bordered class="topbar">
      <h1>Gateway Sessions</h1>
      <NSpace class="status" align="center">
        <RouterLink to="/" class="nav-link">Config</RouterLink>
        <NButton size="small" :loading="loading" @click="loadSessions">Refresh</NButton>
      </NSpace>
    </NLayoutHeader>

    <NLayoutContent content-style="padding: 20px 24px; max-width: 1180px; margin: 0 auto">
      <NSpace vertical size="medium">
        <NSpace align="center">
          <NInput
            v-model:value="query"
            placeholder="Search session tag or client"
            clearable
            style="max-width: 320px"
            @keyup.enter="loadSessions"
          />
          <NButton type="primary" :loading="loading" @click="loadSessions">Search</NButton>
          <NTag type="default">Classification: pending</NTag>
        </NSpace>

        <div class="grid">
          <NCard title="Threads" size="small">
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

          <NCard title="Session Detail" size="small" :loading="detailLoading">
            <template v-if="selectedSession && detail">
              <NDescriptions :column="2" size="small" label-placement="left" bordered>
                <NDescriptionsItem label="Session">{{ selectedSession.session_tag }}</NDescriptionsItem>
                <NDescriptionsItem label="Client">{{ selectedSession.client_name || 'unknown' }}</NDescriptionsItem>
                <NDescriptionsItem label="Started">{{ formatTime(selectedSession.started_at) }}</NDescriptionsItem>
                <NDescriptionsItem label="Last Active">{{ formatTime(selectedSession.last_active_at) }}</NDescriptionsItem>
                <NDescriptionsItem label="Messages">{{ detail.stats.messages }}</NDescriptionsItem>
                <NDescriptionsItem label="Artifacts">
                  {{ detail.stats.surface_events }} surface · {{ detail.stats.heartbeats }} heartbeats ·
                  {{ detail.stats.cold_start_snapshots }} cold starts
                </NDescriptionsItem>
              </NDescriptions>

              <div class="section">
                <h2>Recent Messages</h2>
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
                <NEmpty v-else description="No messages" />
              </div>

              <NPopconfirm
                positive-text="Delete"
                negative-text="Cancel"
                @positive-click="deleteSession(selectedSession.session_tag)"
              >
                <template #trigger>
                  <NButton type="error" :loading="deletingTag === selectedSession.session_tag">
                    Delete This Thread
                  </NButton>
                </template>
                Delete {{ selectedSession.session_tag }} and all related local SQLite rows?
              </NPopconfirm>
            </template>
            <NEmpty v-else description="Select a thread" />
          </NCard>
        </div>
      </NSpace>
    </NLayoutContent>
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
  color: #555;
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
  border-bottom: 1px solid #ececec;
  display: grid;
  gap: 10px;
  grid-template-columns: 86px 1fr;
  padding-bottom: 10px;
}

.message-time,
.message-tool {
  color: #999;
  font-size: 12px;
}

.message-text {
  color: #333;
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
