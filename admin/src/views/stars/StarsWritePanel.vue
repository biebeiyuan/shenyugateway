<script setup lang="ts">
import { NButton, NCheckbox, NInput } from 'naive-ui'
import type { StarCandidate } from '@/api/stars'
import { rootLabel } from './starUi'

defineProps<{
  content: string
  chord: string
  sessionTag: string
  constant: boolean
  query: string
  results: StarCandidate[]
  creating: boolean
  searching: boolean
}>()

const emit = defineEmits<{
  (event: 'update:content', value: string): void
  (event: 'update:chord', value: string): void
  (event: 'update:sessionTag', value: string): void
  (event: 'update:constant', value: boolean): void
  (event: 'update:query', value: string): void
  (event: 'create'): void
  (event: 'search'): void
  (event: 'selectStar', starId: string): void
}>()
</script>

<template>
  <div class="write-space">
    <div class="write-grid">
      <input
        :value="chord"
        class="soft-input"
        placeholder="Am / Cmaj7"
        @input="emit('update:chord', ($event.target as HTMLInputElement).value)"
      >
      <input
        :value="sessionTag"
        class="soft-input"
        placeholder="session_tag"
        @input="emit('update:sessionTag', ($event.target as HTMLInputElement).value)"
      >
      <label class="constant-check">
        <NCheckbox :checked="constant" @update:checked="emit('update:constant', Boolean($event))" />
        恒星
      </label>
    </div>
    <NInput
      :value="content"
      type="textarea"
      :autosize="{ minRows: 4, maxRows: 9 }"
      placeholder="写下这一颗星"
      @update:value="emit('update:content', $event)"
    />
    <div class="write-actions">
      <NButton type="primary" :loading="creating" :disabled="!content.trim()" @click="emit('create')">写入星图</NButton>
    </div>

    <div class="search-strip">
      <input
        :value="query"
        class="soft-input wide"
        placeholder="搜一颗星"
        @input="emit('update:query', ($event.target as HTMLInputElement).value)"
      >
      <NButton size="small" :loading="searching" @click="emit('search')">搜索</NButton>
    </div>
    <div v-if="results.length" class="search-results">
      <button v-for="star in results" :key="star.id" type="button" @click="emit('selectStar', star.id)">
        <span>{{ rootLabel(star) }}</span>
        {{ star.content }}
      </button>
    </div>
  </div>
</template>

<style scoped>
.write-grid {
  display: grid;
  gap: 10px;
  grid-template-columns: 1fr 1fr auto;
  margin-bottom: 10px;
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
  transition: border-color 0.16s, background 0.16s;
}

.soft-input.wide {
  flex: 1;
  min-width: 240px;
}

.constant-check {
  display: flex;
  gap: 8px;
  align-items: center;
  min-height: 38px;
  padding: 0 10px;
  border: 1px solid #ead4cf;
  border-radius: 7px;
  background: #fff;
  color: #6b555b;
}

.write-actions,
.search-strip {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
}

.write-actions {
  margin-top: 10px;
  justify-content: flex-end;
}

.search-strip {
  margin-top: 16px;
}

.search-results {
  display: grid;
  gap: 8px;
  margin-top: 10px;
}

.search-results button {
  padding: 10px;
  border: 1px solid #ead4cf;
  border-radius: 7px;
  background: #fff;
  color: #4a3535;
  text-align: left;
  cursor: pointer;
}

.search-results span {
  margin-right: 8px;
  color: #967180;
  font-weight: 700;
}

@media (max-width: 980px) {
  .write-grid {
    grid-template-columns: 1fr;
  }

  .soft-input,
  .soft-input.wide {
    width: 100%;
  }
}
</style>
