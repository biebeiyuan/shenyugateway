<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { NButton, NInput, NSelect, NSwitch, NTag } from 'naive-ui'
import {
  emptyMcpServer,
  fetchMcpServers,
  refreshMcpTools,
  saveMcpServers,
  testMcpServer,
  validateMcpServer,
  validateMcpServers,
  type McpServer,
  type McpServerStatus,
  type McpTestResult,
  type McpToolSummary,
} from '@/api/mcp'

interface HeaderRow {
  key: string
  value: string
}

const servers = ref<McpServer[]>([])
const status = ref<McpServerStatus[]>([])
const tools = ref<McpToolSummary[]>([])
const loading = ref(false)
const saving = ref(false)
const refreshing = ref(false)
const testing = ref(false)
const feedback = ref('')
const feedbackKind = ref<'ok' | 'error' | ''>('')
const deleteConfirmName = ref('')

const editIndex = ref<number | null>(null)
const form = ref<McpServer>(emptyMcpServer())
const headerRows = ref<HeaderRow[]>([])
const formError = ref('')
const testResult = ref<McpTestResult | null>(null)

const transportOptions = [
  { label: 'auto（streamable HTTP，失败退 SSE）', value: 'auto' },
  { label: 'sse（旧版 SSE）', value: 'sse' },
]

const statusByName = computed(() => {
  const map = new Map<string, McpServerStatus>()
  for (const item of status.value) map.set(item.name, item)
  return map
})

function say(kind: 'ok' | 'error', text: string) {
  feedbackKind.value = kind
  feedback.value = text
}

function formatCheckedAt(iso: string | undefined): string {
  if (!iso) return '未检查'
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return iso
  return date.toLocaleString('zh-CN', { hour12: false })
}

function headersToRows(headers: Record<string, string>): HeaderRow[] {
  return Object.entries(headers || {}).map(([key, value]) => ({ key, value }))
}

function rowsToHeaders(rows: HeaderRow[]): Record<string, string> {
  const headers: Record<string, string> = {}
  for (const row of rows) {
    const key = row.key.trim()
    if (key) headers[key] = row.value
  }
  return headers
}

async function load() {
  loading.value = true
  try {
    const data = await fetchMcpServers()
    servers.value = data.servers
    status.value = data.status
    tools.value = data.tools
  } catch {
    say('error', '加载 MCP 服务器列表失败')
  } finally {
    loading.value = false
  }
}

async function persist(next: McpServer[], successText: string): Promise<boolean> {
  const listError = validateMcpServers(next)
  if (listError) {
    say('error', listError)
    return false
  }
  saving.value = true
  try {
    const result = await saveMcpServers(next)
    servers.value = result.servers
    say('ok', successText)
    await load()
    return true
  } catch (error) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    say('error', detail || '保存失败')
    return false
  } finally {
    saving.value = false
  }
}

function startAdd() {
  editIndex.value = -1
  form.value = emptyMcpServer()
  headerRows.value = []
  formError.value = ''
  testResult.value = null
}

function startEdit(index: number) {
  const server = servers.value[index]
  editIndex.value = index
  form.value = { ...server, headers: { ...server.headers } }
  headerRows.value = headersToRows(server.headers)
  formError.value = ''
  testResult.value = null
}

function cancelEdit() {
  editIndex.value = null
  formError.value = ''
  testResult.value = null
}

function formServer(): McpServer {
  return {
    ...form.value,
    name: form.value.name.trim().toLowerCase(),
    url: form.value.url.trim(),
    headers: rowsToHeaders(headerRows.value),
  }
}

async function submitForm() {
  const candidate = formServer()
  const error = validateMcpServer(candidate)
  if (error) {
    formError.value = error
    return
  }
  const next = [...servers.value]
  if (editIndex.value === -1) {
    next.push(candidate)
  } else if (editIndex.value !== null) {
    next.splice(editIndex.value, 1, candidate)
  }
  formError.value = ''
  if (await persist(next, `已保存 ${candidate.name}`)) {
    editIndex.value = null
  }
}

async function runTest() {
  const candidate = formServer()
  const error = validateMcpServer(candidate)
  if (error) {
    formError.value = error
    return
  }
  formError.value = ''
  testing.value = true
  testResult.value = null
  try {
    testResult.value = await testMcpServer(candidate)
  } catch (error) {
    const detail = (error as { response?: { data?: { detail?: string } } })?.response?.data?.detail
    testResult.value = { ok: false, error: detail || '测试请求失败' }
  } finally {
    testing.value = false
  }
}

async function toggleEnabled(index: number, enabled: boolean) {
  const next = servers.value.map((server, i) => (i === index ? { ...server, enabled } : server))
  await persist(next, enabled ? '已启用' : '已停用')
}

async function removeServer(name: string) {
  if (deleteConfirmName.value !== name) {
    deleteConfirmName.value = name
    return
  }
  deleteConfirmName.value = ''
  const next = servers.value.filter((server) => server.name !== name)
  await persist(next, `已删除 ${name}`)
}

async function refresh() {
  refreshing.value = true
  try {
    const data = await refreshMcpTools()
    status.value = data.status
    tools.value = data.tools
    const failed = data.status.filter((item) => !item.ok)
    say(failed.length ? 'error' : 'ok', failed.length
      ? `刷新完成，${failed.map((item) => item.name).join('、')} 连不上`
      : `刷新完成，共 ${data.tools.length} 个工具`)
  } catch {
    say('error', '刷新失败')
  } finally {
    refreshing.value = false
  }
}

function addHeaderRow() {
  headerRows.value.push({ key: '', value: '' })
}

function removeHeaderRow(index: number) {
  headerRows.value.splice(index, 1)
}

onMounted(load)
</script>

<template>
  <div class="mcp-card" data-testid="config-mcp-card">
    <div class="mcp-toolbar">
      <span class="mcp-hint">网关作为 MCP 客户端连接这些外部服务器；远端工具以 mcp_服务器名_工具名 并入工具桌面。改动即时保存并写入 .env。</span>
      <div class="mcp-toolbar-buttons">
        <NButton size="small" data-testid="mcp-refresh-tools" :loading="refreshing" @click="refresh">刷新工具</NButton>
        <NButton size="small" type="primary" data-testid="mcp-add-server" @click="startAdd">新增服务器</NButton>
      </div>
    </div>

    <div v-if="feedback" class="mcp-feedback" :class="feedbackKind" data-testid="mcp-feedback">{{ feedback }}</div>

    <div v-if="!servers.length && !loading" class="mcp-empty" data-testid="mcp-empty">还没有配置 MCP 服务器。</div>

    <div
      v-for="(server, index) in servers"
      :key="server.name"
      class="mcp-server-row"
      :data-testid="`mcp-server-row-${server.name}`"
    >
      <span
        class="mcp-status-dot"
        :class="{
          ok: statusByName.get(server.name)?.ok,
          error: statusByName.get(server.name) && !statusByName.get(server.name)?.ok,
        }"
        :title="statusByName.get(server.name)?.error || (statusByName.get(server.name)?.ok ? '连接正常' : '尚未检查')"
      />
      <div class="mcp-server-main">
        <div class="mcp-server-title">
          <strong>{{ server.name }}</strong>
          <NTag size="small" :bordered="false">{{ server.transport }}</NTag>
          <NTag v-if="!server.enabled" size="small" type="warning" :bordered="false">已停用</NTag>
        </div>
        <div class="mcp-server-url">{{ server.url }}</div>
        <div class="mcp-server-meta">
          工具 {{ statusByName.get(server.name)?.tool_count ?? '—' }} 个
          · 最后检查 {{ formatCheckedAt(statusByName.get(server.name)?.checked_at) }}
          <span v-if="statusByName.get(server.name)?.error" class="mcp-error-text">
            · {{ statusByName.get(server.name)?.error }}
          </span>
        </div>
      </div>
      <div class="mcp-server-actions">
        <NSwitch
          size="small"
          :value="server.enabled"
          :data-testid="`mcp-toggle-${server.name}`"
          @update:value="(value: boolean) => toggleEnabled(index, value)"
        />
        <NButton size="tiny" :data-testid="`mcp-edit-${server.name}`" @click="startEdit(index)">编辑</NButton>
        <NButton
          size="tiny"
          :type="deleteConfirmName === server.name ? 'error' : 'default'"
          :data-testid="`mcp-delete-${server.name}`"
          @click="removeServer(server.name)"
        >
          {{ deleteConfirmName === server.name ? '确认删除' : '删除' }}
        </NButton>
      </div>
    </div>

    <div v-if="editIndex !== null" class="mcp-form" data-testid="mcp-form">
      <div class="mcp-form-grid">
        <label>
          名称
          <NInput
            v-model:value="form.name"
            data-testid="mcp-form-name"
            placeholder="小写字母/数字/下划线，1-24 位"
            :disabled="editIndex !== -1"
          />
        </label>
        <label>
          URL
          <NInput v-model:value="form.url" data-testid="mcp-form-url" placeholder="https://host/mcp" />
        </label>
        <label>
          传输
          <NSelect v-model:value="form.transport" data-testid="mcp-form-transport" :options="transportOptions" />
        </label>
      </div>
      <div class="mcp-headers">
        <div class="mcp-headers-title">
          请求头（可选，值保存后打码显示；保持打码值不动即沿用原密钥）
          <NButton size="tiny" data-testid="mcp-header-add" @click="addHeaderRow">加一行</NButton>
        </div>
        <div v-for="(row, index) in headerRows" :key="index" class="mcp-header-row">
          <NInput v-model:value="row.key" :data-testid="`mcp-header-key-${index}`" placeholder="Authorization" />
          <NInput v-model:value="row.value" :data-testid="`mcp-header-value-${index}`" placeholder="Bearer ..." />
          <NButton size="tiny" @click="removeHeaderRow(index)">去掉</NButton>
        </div>
      </div>
      <div v-if="formError" class="mcp-form-error" data-testid="mcp-form-error">{{ formError }}</div>
      <div v-if="testResult" class="mcp-test-result" data-testid="mcp-test-result">
        <template v-if="testResult.ok">连接成功，{{ testResult.tool_count }} 个工具：{{ (testResult.tools || []).join('、') }}</template>
        <template v-else>连接失败：{{ testResult.error }}</template>
      </div>
      <div class="mcp-form-actions">
        <NButton size="small" data-testid="mcp-test-server" :loading="testing" @click="runTest">测试连接</NButton>
        <NButton size="small" type="primary" data-testid="mcp-form-save" :loading="saving" @click="submitForm">保存</NButton>
        <NButton size="small" data-testid="mcp-form-cancel" @click="cancelEdit">取消</NButton>
      </div>
    </div>

    <details v-if="tools.length" class="mcp-tools" data-testid="mcp-tools">
      <summary>当前并入的工具（{{ tools.length }}）</summary>
      <div v-for="tool in tools" :key="tool.name" class="mcp-tool-row">
        <code>{{ tool.name }}</code>
        <span class="mcp-tool-desc">{{ tool.description || tool.remote_name }}</span>
      </div>
    </details>
  </div>
</template>

<style scoped>
.mcp-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.mcp-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}
.mcp-toolbar-buttons {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.mcp-hint {
  font-size: 12px;
  color: var(--n-text-color-disabled, #999);
  line-height: 1.5;
}
.mcp-feedback {
  font-size: 12px;
  padding: 4px 8px;
  border-radius: 4px;
}
.mcp-feedback.ok {
  color: #18a058;
  background: rgba(24, 160, 88, 0.08);
}
.mcp-feedback.error {
  color: #d03050;
  background: rgba(208, 48, 80, 0.08);
}
.mcp-empty {
  font-size: 13px;
  color: #999;
}
.mcp-server-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 8px 10px;
  border: 1px solid rgba(128, 128, 128, 0.2);
  border-radius: 6px;
}
.mcp-status-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #bbb;
  margin-top: 5px;
  flex-shrink: 0;
}
.mcp-status-dot.ok {
  background: #18a058;
}
.mcp-status-dot.error {
  background: #d03050;
}
.mcp-server-main {
  flex: 1;
  min-width: 0;
}
.mcp-server-title {
  display: flex;
  align-items: center;
  gap: 6px;
}
.mcp-server-url {
  font-size: 12px;
  color: #888;
  word-break: break-all;
}
.mcp-server-meta {
  font-size: 12px;
  color: #888;
}
.mcp-error-text {
  color: #d03050;
}
.mcp-server-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.mcp-form {
  border: 1px dashed rgba(128, 128, 128, 0.35);
  border-radius: 6px;
  padding: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.mcp-form-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px;
}
.mcp-form-grid label {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: #888;
}
.mcp-headers-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
  color: #888;
  margin-bottom: 6px;
}
.mcp-header-row {
  display: grid;
  grid-template-columns: 1fr 2fr auto;
  gap: 8px;
  margin-bottom: 6px;
}
.mcp-form-error {
  color: #d03050;
  font-size: 12px;
}
.mcp-test-result {
  font-size: 12px;
  color: #555;
  word-break: break-all;
}
.mcp-form-actions {
  display: flex;
  gap: 8px;
}
.mcp-tools {
  font-size: 12px;
}
.mcp-tools summary {
  cursor: pointer;
  color: #888;
}
.mcp-tool-row {
  display: flex;
  gap: 8px;
  padding: 3px 0 3px 14px;
  align-items: baseline;
}
.mcp-tool-desc {
  color: #888;
}
</style>
