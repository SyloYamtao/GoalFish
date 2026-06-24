<template>
  <div class="budget-grid" role="radiogroup" :aria-label="t('prediction.budgetAria')">
    <div
      v-for="(opt, index) in options"
      :key="opt.profile_key"
      class="budget-card-shell"
    >
      <button
      class="budget-card"
      type="button"
      role="radio"
      :aria-checked="modelValue?.profile_key === opt.profile_key"
      :disabled="disabled"
      :class="{ active: modelValue?.profile_key === opt.profile_key }"
      @click="select(opt)"
      @keydown.left.prevent="selectByIndex(index - 1)"
      @keydown.right.prevent="selectByIndex(index + 1)"
      @keydown.enter.prevent="select(opt)"
      @keydown.space.prevent="select(opt)"
    >
      <span class="budget-card-label">{{ opt.label }}</span>
      <span class="budget-card-num mono">{{ opt.calls }} {{ t('prediction.callsUnit') }}</span>
      <span class="budget-card-desc">{{ opt.desc }}</span>
      </button>
      <InfoTooltip
        class="budget-card-info"
        align="right"
        :title="opt.label"
        :text="opt.detail"
      />
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import InfoTooltip from './InfoTooltip.vue'
import { MAX_LLM_HARD_CAP_CALLS } from '../../utils/llmBudget.js'

const props = defineProps({
  modelValue: { type: Object, default: () => ({ profile_key: 'max' }) },
  preview: { type: Object, default: null },
  disabled: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue'])
const { t } = useI18n()

const options = computed(() => [
  {
    profile_key: 'max',
    label: t('prediction.budgetProfile_max_label'),
    calls: 113,
    desc: t('prediction.budgetProfile_max_desc'),
    detail: t('prediction.budgetProfile_max_detail'),
    coach_panel_roles: ['head_coach', 'attack', 'defense', 'transition', 'set_piece', 'goalkeeper', 'fitness', 'risk'],
    coach_deliberation_rounds: 2,
    enable_llm_data_extraction: true,
    narrative_polish_count: 9,
    analyst_note_groups: ['baseline', 'home_upside', 'away_upside', 'home_error', 'away_error', 'volatility'],
    coach_review_roles: ['head_coach', 'risk'],
    n_sims: 3000,
    enable_statsbomb: true,
    hard_cap_calls: MAX_LLM_HARD_CAP_CALLS
  },
  {
    profile_key: 'custom',
    label: t('prediction.budgetProfile_custom_label'),
    calls: props.preview?.calls || '—',
    desc: t('prediction.budgetProfile_custom_desc'),
    detail: t('prediction.budgetProfile_custom_detail'),
    coach_panel_roles: ['head_coach', 'attack', 'defense', 'transition', 'set_piece', 'goalkeeper', 'fitness', 'risk'],
    coach_deliberation_rounds: 3,
    enable_llm_data_extraction: true,
    narrative_polish_count: 9,
    analyst_note_groups: ['baseline', 'home_upside', 'away_upside', 'home_error', 'away_error', 'volatility'],
    coach_review_roles: ['head_coach', 'risk', 'attack'],
    n_sims: 5000,
    enable_statsbomb: true,
    hard_cap_calls: MAX_LLM_HARD_CAP_CALLS
  }
])

const select = (option) => {
  if (props.disabled) return
  emit('update:modelValue', cloneProfile(option))
}

const selectByIndex = (index) => {
  if (props.disabled) return
  const normalized = (index + options.value.length) % options.value.length
  select(options.value[normalized])
}

const cloneProfile = (option) => {
  const { label, calls, desc, ...profile } = option
  return {
    ...profile,
    coach_panel_roles: [...profile.coach_panel_roles],
    analyst_note_groups: [...profile.analyst_note_groups],
    coach_review_roles: [...profile.coach_review_roles]
  }
}
</script>

<style scoped>
.budget-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}

.budget-card {
  width: 100%;
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 14px;
  background: #FFF;
  border: 1px solid #EAEAEA;
  border-radius: 8px;
  cursor: pointer;
  text-align: left;
  font-family: inherit;
  position: relative;
  min-width: 0;
}

.budget-card:disabled {
  opacity: .55;
  cursor: not-allowed;
}

.budget-card-shell {
  position: relative;
  min-width: 0;
}

.budget-card-info {
  position: absolute;
  top: 10px;
  right: 10px;
}

.budget-card.active {
  border-color: #111;
  border-width: 2px;
  padding: 13px;
}

.budget-card.active::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 0;
  height: 0;
  border-top: 8px solid #FF4500;
  border-right: 8px solid transparent;
}

.budget-card-label {
  color: #777;
  font-size: 11px;
  text-transform: uppercase;
  font-family: 'JetBrains Mono', monospace;
}

.budget-card-num {
  font-size: 18px;
  font-weight: 800;
  color: #111;
}

.budget-card-desc {
  color: #555;
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 900px) {
  .budget-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
