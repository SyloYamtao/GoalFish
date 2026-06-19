<template>
  <div class="custom-panel">
    <div class="custom-row custom-row-wide">
      <div class="custom-row-label">
        <span>
          角色启用
          <InfoTooltip
            align="left"
            title="角色启用"
            text="选择哪些教练角色参与 LLM 评审。角色越多，战术视角越完整，但调用数会上升；未启用角色仍会生成代理资料，只是不参与昂贵讨论。"
          />
        </span>
        <div class="custom-row-actions">
          <button class="ghost-btn-xs" type="button" :disabled="disabled" @click="selectAll">全选</button>
          <button class="ghost-btn-xs" type="button" :disabled="disabled" @click="selectCore">仅核心</button>
        </div>
      </div>
      <div class="role-grid">
        <label v-for="role in roles" :key="role.key" class="role-checkbox">
          <input type="checkbox" :checked="value.coach_panel_roles.includes(role.key)" :disabled="disabled" @change="toggleList('coach_panel_roles', role.key)" />
          <span class="role-checkbox-box"></span>
          <span>{{ role.label }}</span>
        </label>
      </div>
    </div>

    <div class="custom-row">
      <span class="custom-row-label-text">
        讨论轮数
        <InfoTooltip
          title="讨论轮数"
          text="每个启用角色参与几轮教练讨论。1 轮用于快速形成观点；2-3 轮会加入反驳和修正，适合复杂或争议大的比赛。"
        />
      </span>
      <div class="stepper">
        <button type="button" :disabled="disabled" @click="dec('coach_deliberation_rounds', 1)">−</button>
        <span class="mono">{{ value.coach_deliberation_rounds }}</span>
        <button type="button" :disabled="disabled" @click="inc('coach_deliberation_rounds', 3)">+</button>
      </div>
      <small>{{ value.coach_deliberation_rounds === 1 ? '单论' : '含反驳轮' }}</small>
    </div>

    <div class="custom-row">
      <span class="custom-row-label-text">
        LLM 数据抽取
        <InfoTooltip
          title="LLM 数据抽取"
          text="让 LLM 从图谱文本中补抽伤停、战术、天气、赛制等非结构化信号。关闭后更快，但更多依赖已有结构化字段和规则解析。"
        />
      </span>
      <Toggle :model-value="value.enable_llm_data_extraction" :disabled="disabled" @update:model-value="update({ enable_llm_data_extraction: $event })" />
      <small>{{ value.enable_llm_data_extraction ? '启用' : '关闭' }}</small>
    </div>

    <div class="custom-row">
      <span class="custom-row-label-text">
        场景叙述润色
        <InfoTooltip
          title="场景叙述润色"
          text="选择多少个场景交给 LLM 写成更自然的赛事情境说明。数值越高，报告可读性越强；0 表示只保留模板化摘要。"
        />
      </span>
      <div class="stepper">
        <button type="button" :disabled="disabled" @click="dec('narrative_polish_count', 0)">−</button>
        <span class="mono">{{ value.narrative_polish_count }}</span>
        <button type="button" :disabled="disabled" @click="inc('narrative_polish_count', 9)">+</button>
      </div>
      <small>0..9 场景</small>
    </div>

    <div class="custom-row custom-row-wide">
      <div class="custom-row-label">
        <span>
          分析师笔记空间
          <InfoTooltip
            title="分析师笔记空间"
            text="指定哪些不确定性场景需要额外分析师笔记。baseline 是基准判断，upside/error/volatility 用来解释上行、失误和高波动路径。"
          />
        </span>
        <div class="custom-row-actions">
          <button
            class="ghost-btn-xs"
            type="button"
            :disabled="disabled"
            @click="toggleAllSpaces(!allSpacesSelected)"
          >
            全选
          </button>
          <button class="ghost-btn-xs" type="button" :disabled="disabled" @click="selectBaselineSpace">仅基准</button>
        </div>
      </div>
      <div class="space-grid">
        <label
          v-for="space in spaces"
          :key="space.key"
          class="role-checkbox"
        >
          <input
            type="checkbox"
            :checked="value.analyst_note_groups.includes(space.key)"
            :disabled="disabled"
            @change="toggleList('analyst_note_groups', space.key)"
          />
          <span class="role-checkbox-box"></span>
          <span>
          {{ space.label }}
          </span>
        </label>
      </div>
    </div>

    <div class="custom-row">
      <span class="custom-row-label-text">
        教练事后复核
        <InfoTooltip
          title="教练事后复核"
          text="预测事件生成后，再让少数教练角色检查结果是否和前面判断一致。可减少明显矛盾，但每个复核角色会增加一批调用。"
        />
      </span>
      <div class="stepper">
        <button type="button" :disabled="disabled" @click="decReview">−</button>
        <span class="mono">{{ value.coach_review_roles.length }}</span>
        <button type="button" :disabled="disabled" @click="incReview">+</button>
      </div>
      <small>0..3 角色</small>
    </div>

    <div class="custom-row">
      <span class="custom-row-label-text">
        MC 样本
        <InfoTooltip
          title="Monte Carlo 样本"
          text="比赛过程模拟次数。样本越多，比分分布和概率更稳定，但运行更慢；500 用于快速预览，2000-3000 通常足够稳定。"
        />
      </span>
      <div class="stepper stepper-wide">
        <button type="button" :disabled="disabled" @click="step('n_sims', -500, 500, 5000)">−</button>
        <span class="mono">{{ value.n_sims }}</span>
        <button type="button" :disabled="disabled" @click="step('n_sims', 500, 500, 5000)">+</button>
      </div>
      <small>500..5000</small>
    </div>

    <div class="custom-row">
      <span class="custom-row-label-text">
        StatsBomb
        <InfoTooltip
          title="StatsBomb"
          text="尝试使用 StatsBomb 或本地可用 xG/事件数据补充机会质量。没有可用数据时会自动跳过，不会阻塞配置生成。"
        />
      </span>
      <Toggle :model-value="value.enable_statsbomb" :disabled="disabled" @update:model-value="update({ enable_statsbomb: $event })" />
      <small>{{ value.enable_statsbomb ? '启用' : '跳过' }}</small>
    </div>

    <div class="custom-row">
      <span class="custom-row-label-text">
        硬上限
        <InfoTooltip
          title="硬上限"
          text="本次配置允许的最大 LLM 调用数，范围 1-130。深度档和最大自定义需要更高上限，否则后续 LLM 步骤会降级为模板或缓存结果。"
        />
      </span>
      <div class="stepper">
        <button type="button" :disabled="disabled" @click="dec('hard_cap_calls', 1)">−</button>
        <span class="mono">{{ value.hard_cap_calls }}</span>
        <button type="button" :disabled="disabled" @click="inc('hard_cap_calls', MAX_LLM_HARD_CAP_CALLS)">+</button>
      </div>
      <small>1..{{ MAX_LLM_HARD_CAP_CALLS }} calls</small>
    </div>

    <div class="custom-preview">
      <span>共 <b class="mono">{{ estimatedCalls }}</b> 次调用</span>
      <span>硬上限 <b class="mono">{{ value.hard_cap_calls }}</b></span>
      <span class="custom-preview-note">启用项越多，耗时和模型费用通常越高</span>
      <button class="ghost-btn ghost-btn-sm" type="button" :disabled="disabled" @click="$emit('apply')">应用</button>
      <button class="ghost-btn ghost-btn-sm" type="button" :disabled="disabled" @click="reset">重置</button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import InfoTooltip from './InfoTooltip.vue'
import Toggle from './Toggle.vue'
import { estimateLLMBudgetCalls, MAX_LLM_HARD_CAP_CALLS } from '../../utils/llmBudget.js'

const props = defineProps({
  modelValue: { type: Object, required: true },
  disabled: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'apply'])

const roles = [
  { key: 'head_coach', label: '主教练' },
  { key: 'attack', label: '进攻' },
  { key: 'defense', label: '防守' },
  { key: 'transition', label: '转换' },
  { key: 'set_piece', label: '定位球' },
  { key: 'goalkeeper', label: '门将' },
  { key: 'fitness', label: '体能' },
  { key: 'risk', label: '风险' }
]

const spaces = [
  { key: 'baseline', label: '基准' },
  { key: 'home_upside', label: '主队上行' },
  { key: 'away_upside', label: '客队上行' },
  { key: 'home_error', label: '主队失误' },
  { key: 'away_error', label: '客队失误' },
  { key: 'volatility', label: '高波动' }
]

const value = computed(() => ({
  profile_key: 'custom',
  coach_panel_roles: [],
  coach_deliberation_rounds: 1,
  enable_llm_data_extraction: false,
  narrative_polish_count: 0,
  analyst_note_groups: [],
  coach_review_roles: [],
  n_sims: 500,
  enable_statsbomb: false,
  hard_cap_calls: 1,
  ...(props.modelValue || {})
}))

const estimatedCalls = computed(() => estimateLLMBudgetCalls(value.value))
const allSpacesSelected = computed(() => spaces.every(space => value.value.analyst_note_groups.includes(space.key)))

const update = (patch) => {
  if (props.disabled) return
  emit('update:modelValue', {
    ...value.value,
    ...patch,
    profile_key: 'custom'
  })
}

const toggleList = (field, item) => {
  if (props.disabled) return
  const set = new Set(value.value[field] || [])
  if (set.has(item)) set.delete(item)
  else set.add(item)
  update({ [field]: Array.from(set) })
}

const inc = (field, max) => update({ [field]: Math.min(max, Number(value.value[field] || 0) + 1) })
const dec = (field, min) => update({ [field]: Math.max(min, Number(value.value[field] || 0) - 1) })

const step = (field, delta, min, max) => {
  if (props.disabled) return
  const next = Math.min(max, Math.max(min, Number(value.value[field] || min) + delta))
  update({ [field]: next })
}

const selectAll = () => update({ coach_panel_roles: roles.map(role => role.key) })
const selectCore = () => update({ coach_panel_roles: ['head_coach', 'attack', 'defense', 'risk'] })
const toggleAllSpaces = (checked) => update({ analyst_note_groups: checked ? spaces.map(space => space.key) : [] })
const selectBaselineSpace = () => update({ analyst_note_groups: ['baseline'] })

const incReview = () => {
  if (props.disabled) return
  const priority = ['head_coach', 'risk', 'attack']
  const current = [...value.value.coach_review_roles]
  const next = priority.find(role => !current.includes(role))
  if (next && current.length < 3) {
    update({
      coach_review_roles: [...current, next],
      hard_cap_calls: Math.max(Number(value.value.hard_cap_calls || 0), MAX_LLM_HARD_CAP_CALLS)
    })
  }
}

const decReview = () => update({ coach_review_roles: value.value.coach_review_roles.slice(0, -1) })

const reset = () => update({
  coach_panel_roles: roles.map(role => role.key),
  coach_deliberation_rounds: 3,
  enable_llm_data_extraction: true,
  narrative_polish_count: 9,
  analyst_note_groups: spaces.map(space => space.key),
  coach_review_roles: ['head_coach', 'risk', 'attack'],
  n_sims: 5000,
  enable_statsbomb: true,
  hard_cap_calls: MAX_LLM_HARD_CAP_CALLS
})
</script>

<style scoped>
.custom-panel {
  background: #FCFCFC;
  border: 1px solid #EFEFEF;
  border-radius: 8px;
  padding: 16px;
  margin-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.custom-row {
  display: grid;
  grid-template-columns: 140px minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
}

.custom-row-wide {
  align-items: start;
}

.custom-row-label {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.custom-row-label span,
.custom-row-label-text {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: #555;
  font-size: 13px;
}

.custom-row-actions {
  display: flex;
  align-items: center;
  gap: 6px;
}

.custom-row small {
  color: #777;
  font-size: 11px;
}

.role-grid,
.space-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 8px;
}

.role-checkbox {
  display: flex;
  align-items: center;
  gap: 6px;
  cursor: pointer;
  font-size: 12px;
  color: #555;
  min-width: 0;
}

.role-checkbox input {
  display: none;
}

.role-checkbox-box {
  width: 14px;
  height: 14px;
  border: 1.5px solid #111;
  border-radius: 2px;
  background: #FFF;
  position: relative;
  flex: 0 0 auto;
}

.role-checkbox input:checked + .role-checkbox-box {
  background: #111;
}

.role-checkbox input:checked + .role-checkbox-box::after {
  content: '✓';
  color: #FFF;
  font-size: 10px;
  position: absolute;
  left: 2px;
  top: -1px;
}

.stepper {
  display: inline-flex;
  align-items: center;
  gap: 8px;
}

.stepper button {
  width: 24px;
  height: 24px;
  border: 1px solid #111;
  background: #FFF;
  cursor: pointer;
  border-radius: 4px;
  font-weight: 800;
}

.stepper button:disabled,
.ghost-btn-xs:disabled,
.ghost-btn-sm:disabled {
  opacity: .45;
  cursor: not-allowed;
}

.stepper span {
  min-width: 24px;
  text-align: center;
}

.stepper-wide span {
  min-width: 42px;
}

.custom-preview {
  display: flex;
  gap: 16px;
  align-items: center;
  padding-top: 12px;
  border-top: 1px solid #EFEFEF;
  font-size: 13px;
  flex-wrap: wrap;
}

.custom-preview-note {
  margin-left: auto;
  color: #555;
  font-size: 12px;
}

.ghost-btn-xs {
  padding: 4px 8px;
  font-size: 11px;
  border: 1px solid #111;
  background: #FFF;
  border-radius: 4px;
  cursor: pointer;
}

.ghost-btn-sm {
  padding: 6px 10px;
  font-size: 12px;
}

@media (max-width: 760px) {
  .custom-row {
    grid-template-columns: 1fr;
  }

  .role-grid,
  .space-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .custom-preview-note {
    margin-left: 0;
  }
}
</style>
