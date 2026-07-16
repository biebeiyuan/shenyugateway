<script setup lang="ts">
import { NButton, NFormItem, NInput, NInputNumber, NSelect, NSwitch } from 'naive-ui'
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

const protocolOptions = [
  { label: '继承主上游', value: '' },
  { label: 'OpenAI compatible', value: 'openai' },
  { label: 'Anthropic', value: 'anthropic' },
  { label: '自动识别', value: 'auto' },
]
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
      <NFormItem label="软点名冷却（轮）">
        <NInputNumber
          v-model:value="config.star_soft_direct_cooldown_turns"
          data-testid="stars-soft-direct-cooldown"
          :min="0"
          :max="100"
        />
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

    <section class="scene-model-card">
      <div class="scene-model-copy">
        <span>Scene Labeler</span>
        <h3>场景标注模型</h3>
        <p>只在你点击“帮我补标签”时调用。URL、Key、协议留空会继承主上游；模型名可单独指定更轻的小模型。</p>
      </div>
      <div class="scene-model-grid">
        <NFormItem label="模型">
          <NInput v-model:value="config.star_scene_llm_model" placeholder="例如 gpt-4.1-mini" />
        </NFormItem>
        <NFormItem label="协议">
          <NSelect v-model:value="config.star_scene_llm_protocol" :options="protocolOptions" />
        </NFormItem>
        <NFormItem label="模型 URL">
          <NInput v-model:value="config.star_scene_llm_url" placeholder="留空继承主上游 URL" />
        </NFormItem>
        <NFormItem label="API Key">
          <NInput
            v-model:value="config.star_scene_llm_api_key"
            type="password"
            show-password-on="click"
            :placeholder="config.star_scene_llm_api_key_configured ? '已配置；留空保持不变' : '留空继承主上游 Key'"
          />
        </NFormItem>
      </div>
    </section>

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

.scene-model-card {
  display: grid;
  grid-template-columns: minmax(220px, .8fr) minmax(420px, 1.6fr);
  gap: 24px;
  margin-top: 14px;
  padding: 20px;
  border: 1px solid rgba(111, 95, 154, .18);
  border-radius: 15px;
  background: linear-gradient(135deg, #fffdfc, #f8f5fb);
}

.scene-model-copy span { color: #8e83b7; font-size: 10px; letter-spacing: .16em; text-transform: uppercase; }
.scene-model-copy h3 { margin: 4px 0 7px; color: #594d67; font-size: 17px; }
.scene-model-copy p { margin: 0; color: #8b7d8c; font-size: 12px; line-height: 1.65; }
.scene-model-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 0 12px; }

@media (max-width: 980px) {
  .toggle-grid,
  .number-grid,
  .weight-grid {
    grid-template-columns: 1fr;
  }
  .scene-model-card { grid-template-columns: 1fr; }
  .scene-model-grid { grid-template-columns: 1fr; }
}
</style>
