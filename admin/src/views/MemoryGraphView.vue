<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  NButton,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NPopconfirm,
  NSelect,
  NSpin,
  NTag,
  useMessage,
} from 'naive-ui'
import {
  addMemoryEntityAlias,
  archiveMemoryEntityRelation,
  backfillMemoryGraph,
  createMemoryEntity,
  createMemoryEntityRelation,
  deleteMemoryEntityAlias,
  fetchMemoryGraph,
  fetchSourceEntityMentions,
  previewMemoryGraphRecall,
  replaceSourceEntities,
  updateMemoryEntity,
  type MemoryEntity,
  type MemoryEntityRelation,
  type MemoryGraphRecallPreviewItem,
  type MemoryEntityType,
  type SourceEntityMention,
} from '@/api/memoryGraph'

const message = useMessage()
const entities = ref<MemoryEntity[]>([])
const relations = ref<MemoryEntityRelation[]>([])
const anchorEntities = ref<MemoryEntity[]>([])
const available = ref(true)
const loadError = ref('')
const loading = ref(false)
const saving = ref(false)
const backfilling = ref(false)
const query = ref('')
const typeFilter = ref<MemoryEntityType | ''>('')
const selectedId = ref('')

const createType = ref<MemoryEntityType>('person')
const createName = ref('')
const createAliases = ref('')
const createDescription = ref('')

const editName = ref('')
const editDescription = ref('')
const aliasDraft = ref('')
const relationTarget = ref('')
const relationType = ref('')
const relationEvidence = ref('')

const recallQuery = ref('')
const recalling = ref(false)
const recallHasRun = ref(false)
const recallError = ref('')
const recallItems = ref<MemoryGraphRecallPreviewItem[]>([])
const recallManualAnchorIds = ref<Record<string, string[]>>({})
const recallSourceMentions = ref<Record<string, SourceEntityMention[]>>({})
const recallSourceMentionsLoaded = ref<Record<string, boolean>>({})
const savingRecallSourceKey = ref('')

const entityTypeOptions = [
  { label: '人物', value: 'person' },
  { label: '地点', value: 'place' },
  { label: '物件', value: 'object' },
  { label: '主题', value: 'topic' },
]

const filterTypeOptions = [{ label: '全部类型', value: '' }, ...entityTypeOptions]
const selected = computed(() => entities.value.find((item) => item.id === selectedId.value) || null)
const entityById = computed(() => Object.fromEntries(entities.value.map((item) => [item.id, item])))
const targetOptions = computed(() => anchorEntities.value
  .filter((item) => item.id !== selectedId.value && item.status === 'active')
  .map((item) => ({ label: `${item.canonical_name} · ${typeLabel(item.entity_type)}`, value: item.id })))
const recallAnchorOptions = computed(() => anchorEntities.value
  .filter((item) => item.status === 'active')
  .map((item) => ({ label: `${item.canonical_name} · ${typeLabel(item.entity_type)}`, value: item.id })))
const selectedRelations = computed(() => relations.value.filter((item) => (
  item.source_entity_id === selectedId.value || item.target_entity_id === selectedId.value
)))
const recallGroups = computed(() => [
  { key: 'direct', label: '直达', items: recallItems.value.filter((item) => item.recall_match?.group === 'direct') },
  { key: 'related', label: '确认关系', items: recallItems.value.filter((item) => item.recall_match?.group === 'related') },
  { key: 'other', label: '其他联想', items: recallItems.value.filter((item) => item.recall_match?.group === 'other') },
].filter((group) => group.items.length))

onMounted(async () => {
  await Promise.all([loadGraph(), loadAnchorEntities()])
})

function splitAliases(value: string): string[] {
  return [...new Set(value.split(/[,，、\n]+/).map((item) => item.trim()).filter(Boolean))]
}

function typeLabel(type: string): string {
  return ({ person: '人物', place: '地点', object: '物件', topic: '主题' } as Record<string, string>)[type] || type
}

function sourceLabel(type: string): string {
  return ({
    journal: '日记',
    windowsill: '窗台',
    heartbeat: '心跳',
    room: '房间',
    board: '留言',
    memory: '旧记忆',
    calendar: '日历',
    mem_note: 'Mem',
    notebook: '笔记',
  } as Record<string, string>)[type] || type
}

function sourceKey(item: Pick<MemoryGraphRecallPreviewItem, 'source_table' | 'source_id'>): string {
  return `${item.source_table}\u0000${item.source_id}`
}

function sourceMentions(item: MemoryGraphRecallPreviewItem): SourceEntityMention[] {
  return recallSourceMentions.value[sourceKey(item)] || []
}

function sourceDate(item: MemoryGraphRecallPreviewItem): string {
  return (item.event_date || '').replace('T', ' ').replace(/\.\d+Z?$/, '').replace(/Z$/, '')
}

function selectEntity(entity: MemoryEntity) {
  selectedId.value = entity.id
  editName.value = entity.canonical_name
  editDescription.value = entity.description || ''
  aliasDraft.value = ''
  relationTarget.value = ''
  relationType.value = ''
  relationEvidence.value = ''
}

async function loadGraph(keepSelection = true) {
  loading.value = true
  try {
    const result = await fetchMemoryGraph({
      q: query.value.trim() || undefined,
      entity_type: typeFilter.value || undefined,
    })
    available.value = result.available
    loadError.value = result.error || ''
    entities.value = result.entities || []
    relations.value = result.relations || []
    if (!keepSelection || !entities.value.some((item) => item.id === selectedId.value)) {
      selectedId.value = ''
    } else if (selected.value) {
      selectEntity(selected.value)
    }
  } catch {
    message.error('读取记忆网络失败')
  } finally {
    loading.value = false
  }
}

async function loadAnchorEntities() {
  try {
    const result = await fetchMemoryGraph()
    anchorEntities.value = result.entities || []
  } catch {
    anchorEntities.value = []
  }
}

async function createEntity() {
  if (!createName.value.trim()) return
  saving.value = true
  try {
    const entity = await createMemoryEntity({
      entity_type: createType.value,
      canonical_name: createName.value.trim(),
      description: createDescription.value.trim(),
      aliases: splitAliases(createAliases.value),
    })
    createName.value = ''
    createAliases.value = ''
    createDescription.value = ''
    await Promise.all([loadGraph(false), loadAnchorEntities()])
    const created = entities.value.find((item) => item.id === entity.id)
    if (created) selectEntity(created)
    message.success('锚点已建立')
  } catch {
    message.error('建立锚点失败')
  } finally {
    saving.value = false
  }
}

async function saveEntity() {
  if (!selected.value || !editName.value.trim()) return
  saving.value = true
  try {
    await updateMemoryEntity(selected.value.id, {
      canonical_name: editName.value.trim(),
      description: editDescription.value.trim(),
    })
    await Promise.all([loadGraph(), loadAnchorEntities()])
    message.success('锚点已保存')
  } catch {
    message.error('保存锚点失败')
  } finally {
    saving.value = false
  }
}

async function archiveEntity() {
  if (!selected.value) return
  saving.value = true
  try {
    await updateMemoryEntity(selected.value.id, { status: 'archived' })
    await Promise.all([loadGraph(false), loadAnchorEntities()])
    message.success('锚点已归档')
  } catch {
    message.error('归档失败')
  } finally {
    saving.value = false
  }
}

async function addAlias() {
  if (!selected.value || !aliasDraft.value.trim()) return
  saving.value = true
  try {
    await addMemoryEntityAlias(selected.value.id, aliasDraft.value.trim())
    aliasDraft.value = ''
    await Promise.all([loadGraph(), loadAnchorEntities()])
    message.success('别名已确认')
  } catch {
    message.error('添加别名失败')
  } finally {
    saving.value = false
  }
}

async function removeAlias(aliasId: string) {
  saving.value = true
  try {
    await deleteMemoryEntityAlias(aliasId)
    await Promise.all([loadGraph(), loadAnchorEntities()])
    message.success('别名已移除')
  } catch {
    message.error('主名称不能移除')
  } finally {
    saving.value = false
  }
}

async function addRelation() {
  if (!selected.value || !relationTarget.value || !relationType.value.trim()) return
  saving.value = true
  try {
    await createMemoryEntityRelation({
      source_entity_id: selected.value.id,
      target_entity_id: relationTarget.value,
      relation_type: relationType.value.trim(),
      evidence: relationEvidence.value.trim(),
    })
    relationTarget.value = ''
    relationType.value = ''
    relationEvidence.value = ''
    await loadGraph()
    message.success('关系已确认')
  } catch {
    message.error('建立关系失败')
  } finally {
    saving.value = false
  }
}

async function archiveRelation(relationId: string) {
  saving.value = true
  try {
    await archiveMemoryEntityRelation(relationId)
    await loadGraph()
    message.success('关系已收起')
  } catch {
    message.error('收起关系失败')
  } finally {
    saving.value = false
  }
}

async function runBackfill() {
  backfilling.value = true
  try {
    const result = await backfillMemoryGraph()
    await loadGraph()
    message.success(`扫描 ${result.scanned_sources} 个原件，连上 ${result.matched_sources} 个`)
  } catch {
    message.error('历史关联扫描失败')
  } finally {
    backfilling.value = false
  }
}

async function loadRecallSourceMentions(items: MemoryGraphRecallPreviewItem[]) {
  const manual: Record<string, string[]> = Object.fromEntries(items.map((item) => [sourceKey(item), []]))
  const mentionsBySource: Record<string, SourceEntityMention[]> = {}
  const loaded: Record<string, boolean> = Object.fromEntries(items.map((item) => [sourceKey(item), false]))
  recallManualAnchorIds.value = manual
  recallSourceMentions.value = mentionsBySource
  recallSourceMentionsLoaded.value = loaded
  if (!available.value) return
  await Promise.all(items.map(async (item) => {
    try {
      const mentions = await fetchSourceEntityMentions(item.source_table, item.source_id)
      const key = sourceKey(item)
      mentionsBySource[key] = mentions
      loaded[key] = true
      manual[key] = mentions
        .filter((mention) => mention.origin === 'manual')
        .map((mention) => mention.entity_id)
    } catch {
      // A preview result remains usable even if its optional anchor lookup fails.
    }
  }))
  recallSourceMentions.value = { ...mentionsBySource }
  recallManualAnchorIds.value = { ...manual }
  recallSourceMentionsLoaded.value = { ...loaded }
}

async function runRecallPreview() {
  const text = recallQuery.value.trim()
  if (!text) return
  recalling.value = true
  recallHasRun.value = true
  recallError.value = ''
  try {
    const result = await previewMemoryGraphRecall(text)
    if (!result.ok) {
      recallItems.value = []
      recallError.value = result.error || '这次没有读到 recall 结果'
      return
    }
    recallItems.value = result.items || []
    await loadRecallSourceMentions(recallItems.value)
  } catch {
    recallItems.value = []
    recallError.value = '试着想起时没有读到结果'
  } finally {
    recalling.value = false
  }
}

async function saveRecallAnchors(item: MemoryGraphRecallPreviewItem) {
  const key = sourceKey(item)
  if (savingRecallSourceKey.value || !recallSourceMentionsLoaded.value[key]) return
  savingRecallSourceKey.value = key
  try {
    await replaceSourceEntities({
      source_table: item.source_table,
      source_type: item.source_type,
      source_id: item.source_id,
      entity_ids: recallManualAnchorIds.value[key] || [],
      evidence: '记忆网络试着想起页手动确认',
    })
    const mentions = await fetchSourceEntityMentions(item.source_table, item.source_id)
    recallSourceMentions.value = { ...recallSourceMentions.value, [key]: mentions }
    recallSourceMentionsLoaded.value = { ...recallSourceMentionsLoaded.value, [key]: true }
    recallManualAnchorIds.value = {
      ...recallManualAnchorIds.value,
      [key]: mentions.filter((mention) => mention.origin === 'manual').map((mention) => mention.entity_id),
    }
    message.success('关联已保存')
  } catch {
    message.error('保存关联失败')
  } finally {
    savingRecallSourceKey.value = ''
  }
}

function otherEntity(relation: MemoryEntityRelation): MemoryEntity | undefined {
  const otherId = relation.source_entity_id === selectedId.value
    ? relation.target_entity_id
    : relation.source_entity_id
  return entityById.value[otherId]
}
</script>

<template>
  <div class="graph-page" data-testid="page-memory-graph">
    <header class="page-head">
      <div>
        <h2>记忆网络</h2>
        <span>{{ entities.length }} 个锚点 · {{ relations.filter(r => r.status === 'confirmed').length }} 条关系</span>
      </div>
      <NButton :loading="backfilling" :disabled="!available" @click="runBackfill">扫描历史关联</NButton>
    </header>

    <div v-if="!available" class="unavailable">
      <b>记忆网络尚未启用</b>
      <span>{{ loadError }}</span>
    </div>

    <section class="create-band">
      <NSelect v-model:value="createType" :options="entityTypeOptions" aria-label="锚点类型" />
      <NInput v-model:value="createName" placeholder="名称" @keyup.enter="createEntity" />
      <NInput v-model:value="createAliases" placeholder="别名，用逗号分开" />
      <NInput v-model:value="createDescription" placeholder="备注" />
      <NButton type="primary" :loading="saving" :disabled="!available || !createName.trim()" @click="createEntity">建立锚点</NButton>
    </section>

    <section class="recall-preview" data-testid="memory-graph-recall-preview">
      <div class="recall-preview-head">
        <h3>试着想起</h3>
        <div class="recall-query">
          <NInput
            v-model:value="recallQuery"
            clearable
            placeholder="人、地点、一段话或心情"
            data-testid="memory-graph-recall-input"
            @keyup.enter="runRecallPreview"
          />
          <NButton type="primary" :loading="recalling" :disabled="!recallQuery.trim()" @click="runRecallPreview">想起</NButton>
        </div>
      </div>
      <p v-if="recallError" class="recall-error">{{ recallError }}</p>
      <NEmpty v-else-if="recallHasRun && !recalling && !recallItems.length" description="还没有找到相连的原件" />
      <div v-else-if="recallGroups.length" class="recall-groups">
        <section v-for="group in recallGroups" :key="group.key" class="recall-group">
          <h4>{{ group.label }}</h4>
          <article v-for="item in group.items" :key="sourceKey(item)" class="recall-item">
            <header class="recall-item-head">
              <div>
                <b>{{ item.title || sourceLabel(item.source_type) }}</b>
                <span>{{ sourceLabel(item.source_type) }}<template v-if="sourceDate(item)"> · {{ sourceDate(item) }}</template></span>
              </div>
              <NTag size="small" :bordered="false">{{ item.recall_match.label }}</NTag>
            </header>
            <pre class="recall-content">{{ item.content }}</pre>
            <p v-if="item.content_complete === false" class="recall-incomplete">原文暂时无法完整读取：{{ item.content_error }}</p>
            <div v-if="available" class="recall-anchor-editor">
              <NSelect
                v-model:value="recallManualAnchorIds[sourceKey(item)]"
                multiple
                filterable
                clearable
                :options="recallAnchorOptions"
                placeholder="关联锚点"
              />
              <NButton
                size="small"
                :disabled="!recallSourceMentionsLoaded[sourceKey(item)]"
                :loading="savingRecallSourceKey === sourceKey(item)"
                @click="saveRecallAnchors(item)"
              >保存关联</NButton>
              <div v-if="sourceMentions(item).filter(m => m.origin !== 'manual').length" class="recall-auto-anchors">
                <NTag
                  v-for="mention in sourceMentions(item).filter(m => m.origin !== 'manual')"
                  :key="mention.id"
                  size="small"
                  :bordered="false"
                >{{ mention.entity?.canonical_name || mention.matched_alias }}</NTag>
              </div>
            </div>
          </article>
        </section>
      </div>
    </section>

    <div class="workspace">
      <aside class="entity-pane">
        <div class="filters">
          <NInput v-model:value="query" clearable placeholder="搜索名称或别名" data-testid="memory-graph-search" @keyup.enter="loadGraph(false)" />
          <NSelect v-model:value="typeFilter" :options="filterTypeOptions" @update:value="loadGraph(false)" />
        </div>
        <NSpin :show="loading">
          <div v-if="entities.length" class="entity-list">
            <button
              v-for="entity in entities"
              :key="entity.id"
              class="entity-row"
              :class="{ selected: entity.id === selectedId }"
              @click="selectEntity(entity)"
            >
              <span class="entity-name">{{ entity.canonical_name }}</span>
              <span class="entity-meta">{{ typeLabel(entity.entity_type) }} · {{ entity.mention_count }} 个原件</span>
              <span class="alias-preview">{{ entity.aliases.map(a => a.alias).join(' · ') }}</span>
            </button>
          </div>
          <NEmpty v-else description="还没有锚点" />
        </NSpin>
      </aside>

      <main class="detail-pane">
        <template v-if="selected">
          <div class="detail-title">
            <div>
              <h3>{{ selected.canonical_name }}</h3>
              <span>{{ typeLabel(selected.entity_type) }} · {{ selected.mention_count }} 个原件 · {{ selected.relation_count }} 条关系</span>
            </div>
            <NPopconfirm positive-text="归档" negative-text="取消" @positive-click="archiveEntity">
              <template #trigger><NButton size="small">归档锚点</NButton></template>
              归档后不再参与自动连线。
            </NPopconfirm>
          </div>

          <section class="detail-section">
            <h4>基本信息</h4>
            <NForm label-placement="top">
              <div class="two-columns">
                <NFormItem label="名称"><NInput v-model:value="editName" /></NFormItem>
                <NFormItem label="备注"><NInput v-model:value="editDescription" /></NFormItem>
              </div>
              <NButton type="primary" size="small" :loading="saving" @click="saveEntity">保存</NButton>
            </NForm>
          </section>

          <section class="detail-section">
            <h4>确认别名</h4>
            <div class="tag-list">
              <NTag v-for="alias in selected.aliases" :key="alias.id" :bordered="false">
                {{ alias.alias }}
                <span v-if="alias.status !== 'confirmed'" class="suggested">候选</span>
                <button v-if="!alias.is_primary" class="tag-remove" title="移除别名" @click="removeAlias(alias.id)">×</button>
              </NTag>
            </div>
            <div class="inline-form">
              <NInput v-model:value="aliasDraft" placeholder="新增别名" @keyup.enter="addAlias" />
              <NButton :loading="saving" :disabled="!aliasDraft.trim()" @click="addAlias">确认别名</NButton>
            </div>
          </section>

          <section class="detail-section">
            <h4>原件分布</h4>
            <div class="source-counts">
              <span v-for="(count, source) in selected.source_type_counts" :key="source">
                {{ sourceLabel(source) }} <b>{{ count }}</b>
              </span>
              <span v-if="!Object.keys(selected.source_type_counts).length">暂无关联原件</span>
            </div>
          </section>

          <section class="detail-section">
            <h4>关系</h4>
            <div v-if="selectedRelations.length" class="relation-list">
              <div v-for="relation in selectedRelations" :key="relation.id" class="relation-row">
                <div>
                  <b>{{ relation.relation_type }}</b>
                  <span>{{ otherEntity(relation)?.canonical_name || '未知锚点' }}</span>
                  <small v-if="relation.evidence">{{ relation.evidence }}</small>
                  <small v-if="relation.status === 'suggested'" class="suggested">系统候选，尚未确认</small>
                </div>
                <NButton v-if="relation.status !== 'archived'" size="tiny" quaternary @click="archiveRelation(relation.id)">收起</NButton>
              </div>
            </div>
            <div class="relation-form">
              <NSelect v-model:value="relationTarget" filterable :options="targetOptions" placeholder="连接到" />
              <NInput v-model:value="relationType" placeholder="关系，例如：闺蜜、常去、一起读" />
              <NInput v-model:value="relationEvidence" placeholder="依据或备注" />
              <NButton :loading="saving" :disabled="!relationTarget || !relationType.trim()" @click="addRelation">确认关系</NButton>
            </div>
          </section>
        </template>
        <NEmpty v-else description="选择一个锚点" />
      </main>
    </div>
  </div>
</template>

<style scoped>
.graph-page {
  width: min(1180px, calc(100vw - 32px));
  margin: 0 auto;
  padding: 20px 0 40px;
}

.page-head,
.detail-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}

.page-head h2,
.detail-title h3 {
  font-size: 22px;
  letter-spacing: 0;
  font-weight: 600;
}

.page-head span,
.detail-title span,
.entity-meta,
.alias-preview {
  color: #927f7a;
  font-size: 12px;
}

.unavailable {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 16px;
  padding: 12px 14px;
  border-left: 3px solid #c8956a;
  background: #fff8f1;
  color: #76594a;
}

.create-band {
  display: grid;
  grid-template-columns: 130px minmax(140px, 1fr) minmax(180px, 1.2fr) minmax(180px, 1.4fr) auto;
  gap: 8px;
  margin: 18px 0;
  padding: 12px;
  border-top: 1px solid #eadbd6;
  border-bottom: 1px solid #eadbd6;
  background: rgba(255, 255, 255, 0.55);
}

.recall-preview {
  margin: 0 0 18px;
  padding: 16px 0 0;
  border-top: 1px solid #eadbd6;
  border-bottom: 1px solid #eadbd6;
}

.recall-preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 0 14px 14px;
}

.recall-preview-head h3,
.recall-group h4 {
  margin: 0;
  color: #5e4850;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0;
}

.recall-query {
  display: grid;
  grid-template-columns: minmax(220px, 440px) auto;
  gap: 8px;
  width: min(100%, 560px);
}

.recall-error,
.recall-incomplete {
  margin: 0;
  padding: 10px 14px;
  color: #8d4c25;
  background: #fff7ed;
  border-top: 1px solid #eadbd6;
  font-size: 12px;
}

.recall-groups {
  border-top: 1px solid #eee3df;
}

.recall-group h4 {
  padding: 12px 14px 8px;
  background: #fffaf8;
}

.recall-item {
  padding: 14px;
  border-top: 1px solid #eee3df;
}

.recall-item-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.recall-item-head > div {
  display: grid;
  gap: 3px;
  min-width: 0;
}

.recall-item-head b {
  color: #49373a;
  font-size: 14px;
  overflow-wrap: anywhere;
}

.recall-item-head span {
  color: #927f7a;
  font-size: 12px;
}

.recall-item-head :deep(.n-tag) {
  max-width: min(48vw, 360px);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.recall-content {
  margin: 12px 0;
  color: #342d2f;
  font-family: inherit;
  font-size: 13px;
  line-height: 1.72;
  white-space: pre-wrap;
  word-break: break-word;
}

.recall-anchor-editor {
  display: grid;
  grid-template-columns: minmax(180px, 1fr) auto;
  gap: 8px;
  padding-top: 12px;
  border-top: 1px dashed #eadbd6;
}

.recall-auto-anchors {
  grid-column: 1 / -1;
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.workspace {
  display: grid;
  grid-template-columns: minmax(280px, 360px) minmax(0, 1fr);
  min-height: 620px;
  border: 1px solid #eadbd6;
  background: #fff;
}

.entity-pane {
  border-right: 1px solid #eadbd6;
}

.filters {
  display: grid;
  grid-template-columns: 1fr 118px;
  gap: 8px;
  padding: 12px;
  border-bottom: 1px solid #eee3df;
}

.entity-list {
  max-height: 680px;
  overflow: auto;
}

.entity-row {
  width: 100%;
  min-height: 76px;
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: 3px;
  padding: 12px 14px;
  border: 0;
  border-bottom: 1px solid #f1e7e3;
  background: #fff;
  color: #4a3535;
  text-align: left;
  cursor: pointer;
}

.entity-row:hover,
.entity-row.selected {
  background: #fbf3f1;
}

.entity-row.selected {
  box-shadow: inset 3px 0 #b58b9e;
}

.entity-name {
  font-size: 15px;
  font-weight: 600;
}

.alias-preview {
  width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.detail-pane {
  min-width: 0;
  padding: 20px 22px;
}

.detail-section {
  padding: 18px 0;
  border-bottom: 1px solid #eee3df;
}

.detail-section h4 {
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0;
  color: #765f68;
}

.two-columns,
.inline-form,
.relation-form {
  display: grid;
  gap: 8px;
}

.two-columns {
  grid-template-columns: 1fr 1.5fr;
}

.inline-form {
  grid-template-columns: minmax(180px, 1fr) auto;
  margin-top: 10px;
}

.relation-form {
  grid-template-columns: minmax(150px, 1fr) minmax(160px, 1fr) minmax(180px, 1.2fr) auto;
  margin-top: 12px;
}

.tag-list,
.source-counts {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.tag-remove {
  margin-left: 6px;
  border: 0;
  background: transparent;
  color: #a48e88;
  cursor: pointer;
}

.source-counts span {
  padding: 6px 9px;
  border: 1px solid #eadbd6;
  font-size: 12px;
  color: #765f68;
}

.relation-list {
  border-top: 1px solid #eee3df;
}

.relation-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 2px;
  border-bottom: 1px solid #eee3df;
}

.relation-row div {
  display: grid;
  grid-template-columns: minmax(90px, auto) minmax(120px, 1fr);
  gap: 4px 12px;
  align-items: baseline;
}

.relation-row small {
  grid-column: 1 / -1;
  color: #927f7a;
}

.suggested {
  color: #b2734f;
  font-size: 11px;
}

@media (max-width: 820px) {
  .create-band,
  .workspace,
  .two-columns,
  .relation-form,
  .recall-anchor-editor {
    grid-template-columns: 1fr;
  }

  .recall-preview-head,
  .recall-item-head {
    align-items: stretch;
    flex-direction: column;
  }

  .recall-query {
    width: 100%;
    grid-template-columns: 1fr auto;
  }

  .workspace {
    min-height: 0;
  }

  .entity-pane {
    border-right: 0;
    border-bottom: 1px solid #eadbd6;
  }

  .entity-list {
    max-height: 300px;
  }

  .detail-pane {
    padding: 16px;
  }
}
</style>
