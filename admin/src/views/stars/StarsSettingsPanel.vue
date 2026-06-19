<script setup lang="ts">
import { NButton, NFormItem, NInputNumber, NSwitch } from 'naive-ui'
import type { GatewayConfig } from '@/api/config'

defineProps<{
  config: Partial<GatewayConfig>
  saving: boolean
}>()

const emit = defineEmits<{
  (event: 'save'): void
  (event: 'quietTools'): void
  (event: 'reset'): void
}>()
</script>

<template>
  <div class="settings-space">
    <div class="toggle-grid">
      <label><NSwitch v-model:value="config.inject_star_prompt" /> <span>Star 提示</span></label>
      <label><NSwitch v-model:value="config.enable_inline_star_capture" /> <span>自动捕获</span></label>
      <label><NSwitch v-model:value="config.inject_stars" /> <span>聊天注入</span></label>
      <label><NSwitch v-model:value="config.enable_gateway_tools" /> <span>网关工具</span></label>
      <label><NSwitch v-model:value="config.enable_star_embeddings" /> <span>embedding</span></label>
    </div>

    <div class="number-grid">
      <NFormItem label="日常注入">
        <NInputNumber v-model:value="config.star_inject_limit" :min="1" :max="5" />
      </NFormItem>
      <NFormItem label="Review 新星">
        <NInputNumber v-model:value="config.star_review_new_limit" :min="1" :max="10" />
      </NFormItem>
      <NFormItem label="每星候选">
        <NInputNumber v-model:value="config.star_review_candidates_per_star" :min="1" :max="5" />
      </NFormItem>
      <NFormItem label="总候选">
        <NInputNumber v-model:value="config.star_review_total_candidate_limit" :min="1" :max="30" />
      </NFormItem>
      <NFormItem label="最低分">
        <NInputNumber v-model:value="config.star_min_score" :min="0" :max="1" :step="0.01" />
      </NFormItem>
      <NFormItem label="相关门槛">
        <NInputNumber v-model:value="config.star_related_min_score" :min="0" :max="1" :step="0.01" />
      </NFormItem>
      <NFormItem label="疲劳小时">
        <NInputNumber v-model:value="config.star_recent_fatigue_hours" :min="0" :max="168" />
      </NFormItem>
      <NFormItem label="疲劳惩罚">
        <NInputNumber v-model:value="config.star_recent_fatigue_penalty" :min="0" :max="1" :step="0.01" />
      </NFormItem>
    </div>

    <details class="advanced-settings">
      <summary>权重</summary>
      <div class="weight-grid">
        <NFormItem label="内容"><NInputNumber v-model:value="config.star_weight_content" :min="0" :max="2" :step="0.01" /></NFormItem>
        <NFormItem label="关键词"><NInputNumber v-model:value="config.star_weight_keyword" :min="0" :max="2" :step="0.01" /></NFormItem>
        <NFormItem label="和声"><NInputNumber v-model:value="config.star_weight_harmony" :min="0" :max="2" :step="0.01" /></NFormItem>
        <NFormItem label="和弦"><NInputNumber v-model:value="config.star_weight_chord" :min="0" :max="2" :step="0.01" /></NFormItem>
        <NFormItem label="亮度"><NInputNumber v-model:value="config.star_weight_actr" :min="0" :max="2" :step="0.01" /></NFormItem>
        <NFormItem label="恒星"><NInputNumber v-model:value="config.star_constant_bonus" :min="0" :max="1" :step="0.01" /></NFormItem>
        <NFormItem label="新鲜"><NInputNumber v-model:value="config.star_novelty_bonus" :min="0" :max="1" :step="0.01" /></NFormItem>
        <NFormItem label="忽略"><NInputNumber v-model:value="config.star_ignored_penalty" :min="0" :max="1" :step="0.01" /></NFormItem>
        <NFormItem label="候选池"><NInputNumber v-model:value="config.star_candidate_limit" :min="50" :max="5000" /></NFormItem>
        <NFormItem label="shadow"><NInputNumber v-model:value="config.star_shadow_candidate_limit" :min="3" :max="100" /></NFormItem>
      </div>
    </details>

    <div class="setting-actions">
      <NButton type="primary" :loading="saving" @click="emit('save')">保存</NButton>
      <NButton :disabled="saving" @click="emit('quietTools')">静音但留工具</NButton>
      <NButton :disabled="saving" @click="emit('reset')">默认</NButton>
    </div>
  </div>
</template>

<style scoped>
.toggle-grid,
.number-grid,
.weight-grid {
  display: grid;
  gap: 10px;
}

.toggle-grid {
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.toggle-grid label {
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

.number-grid {
  margin-top: 12px;
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.advanced-settings {
  margin-top: 12px;
  border: 1px solid #ead4cf;
  border-radius: 8px;
  background: #fffdfc;
}

.advanced-settings summary {
  padding: 11px 12px;
  cursor: pointer;
  color: #846d77;
}

.weight-grid {
  padding: 0 12px 12px;
  grid-template-columns: repeat(5, minmax(0, 1fr));
}

.setting-actions {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-wrap: wrap;
  margin-top: 12px;
}

@media (max-width: 980px) {
  .toggle-grid,
  .number-grid,
  .weight-grid {
    grid-template-columns: 1fr;
  }
}
</style>
