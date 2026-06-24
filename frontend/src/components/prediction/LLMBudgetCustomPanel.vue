<template>
  <div class="custom-panel">
    <div class="custom-row custom-row-wide">
      <div class="custom-row-label">
        <span>
          {{ t('prediction.roleEnable') }}
          <InfoTooltip
            align="left"
            :title="t('prediction.roleEnable')"
            :text="t('prediction.roleEnableTooltip')"
          />
        </span>
        <div class="custom-row-actions">
          <button class="ghost-btn-xs" type="button" :disabled="disabled" @click="selectAll">{{ t('prediction.selectAll') }}</button>
          <button class="ghost-btn-xs" type="button" :disabled="disabled" @click="selectCore">{{ t('prediction.coreOnly') }}</button>
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
        {{ t('prediction.discussionRounds') }}
        <InfoTooltip
          :title="t('prediction.discussionRounds')"
          :text="t('prediction.discussionRoundsTooltip')"
        />
      </span>
      <div class="stepper">
        <button type="button" :disabled="disabled" @click="dec('coach_deliberation_rounds', 1)">−</button>
        <span class="mono">{{ value.coach_deliberation_rounds }}</span>
        <button type="button" :disabled="disabled" @click="inc('coach_deliberation_rounds', 3)">+</button>
      </div>
      <small>{{ value.coach_deliberation_rounds === 1 ? t('prediction.singleRound') : t('prediction.withRebuttalRound') }}</small>
    </div>

    <div class="custom-row">
      <span class="custom-row-label-text">
        {{ t('prediction.llmDataExtraction') }}
        <InfoTooltip
          :title="t('prediction.llmDataExtraction')"
          :text="t('prediction.llmDataExtractionTooltip')"
        />
      </span>
      <Toggle :model-value="value.enable_llm_data_extraction" :disabled="disabled" @update:model-value="update({ enable_llm_data_extraction: $event })" />
      <small>{{ value.enable_llm_data_extraction ? t('prediction.enabled') : t('prediction.disabled') }}</small>
    </div>

    <div class="custom-row">
      <span class="custom-row-label-text">
        {{ t('prediction.narrativePolish') }}
        <InfoTooltip
          :title="t('prediction.narrativePolish')"
          :text="t('prediction.narrativePolishTooltip')"
        />
      </span>
      <div class="stepper">
        <button type="button" :disabled="disabled" @click="dec('narrative_polish_count', 0)">−</button>
        <span class="mono">{{ value.narrative_polish_count }}</span>
        <button type="button" :disabled="disabled" @click="inc('narrative_polish_count', 9)">+</button>
      </div>
      <small>{{ t('prediction.scenarioCountRange') }}</small>
    </div>

    <div class="custom-row custom-row-wide">
      <div class="custom-row-label">
        <span>
          {{ t('prediction.analystNoteSpaces') }}
          <InfoTooltip
            :title="t('prediction.analystNoteSpaces')"
            :text="t('prediction.analystNoteSpacesTooltip')"
          />
        </span>
        <div class="custom-row-actions">
          <button
            class="ghost-btn-xs"
            type="button"
            :disabled="disabled"
            @click="toggleAllSpaces(!allSpacesSelected)"
          >
            {{ t('prediction.selectAll') }}
          </button>
          <button class="ghost-btn-xs" type="button" :disabled="disabled" @click="selectBaselineSpace">{{ t('prediction.baselineOnly') }}</button>
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
        {{ t('prediction.postCoachReview') }}
        <InfoTooltip
          :title="t('prediction.postCoachReview')"
          :text="t('prediction.postCoachReviewTooltip')"
        />
      </span>
      <div class="stepper">
        <button type="button" :disabled="disabled" @click="decReview">−</button>
        <span class="mono">{{ value.coach_review_roles.length }}</span>
        <button type="button" :disabled="disabled" @click="incReview">+</button>
      </div>
      <small>{{ t('prediction.roleCountRange') }}</small>
    </div>

    <div class="custom-row">
      <span class="custom-row-label-text">
        {{ t('prediction.mcSamples') }}
        <InfoTooltip
          :title="t('prediction.mcSamples')"
          :text="t('prediction.mcSamplesTooltip')"
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
          :text="t('prediction.statsBombTooltip')"
        />
      </span>
      <Toggle :model-value="value.enable_statsbomb" :disabled="disabled" @update:model-value="update({ enable_statsbomb: $event })" />
      <small>{{ value.enable_statsbomb ? t('prediction.enabled') : t('prediction.skip') }}</small>
    </div>

    <div class="custom-row">
      <span class="custom-row-label-text">
        {{ t('prediction.hardCap') }}
        <InfoTooltip
          :title="t('prediction.hardCap')"
          :text="t('prediction.hardCapTooltip')"
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
      <span>{{ t('prediction.totalCallsPreview', { count: estimatedCalls }) }}</span>
      <span>{{ t('prediction.hardCapPreview', { count: value.hard_cap_calls }) }}</span>
      <span class="custom-preview-note">{{ t('prediction.customPreviewNote') }}</span>
      <button class="ghost-btn ghost-btn-sm" type="button" :disabled="disabled" @click="$emit('apply')">{{ t('prediction.apply') }}</button>
      <button class="ghost-btn ghost-btn-sm" type="button" :disabled="disabled" @click="reset">{{ t('prediction.reset') }}</button>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import InfoTooltip from './InfoTooltip.vue'
import Toggle from './Toggle.vue'
import { estimateLLMBudgetCalls, MAX_LLM_HARD_CAP_CALLS } from '../../utils/llmBudget.js'

const props = defineProps({
  modelValue: { type: Object, required: true },
  disabled: { type: Boolean, default: false }
})

const emit = defineEmits(['update:modelValue', 'apply'])
const { t } = useI18n()

const roleKeys = ['head_coach', 'attack', 'defense', 'transition', 'set_piece', 'goalkeeper', 'fitness', 'risk']
const spaceKeys = ['baseline', 'home_upside', 'away_upside', 'home_error', 'away_error', 'volatility']
const roles = computed(() => roleKeys.map(key => ({ key, label: t(`prediction.role_${key}`) })))
const spaces = computed(() => spaceKeys.map(key => ({ key, label: t(`prediction.space_${key}`) })))

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
const allSpacesSelected = computed(() => spaceKeys.every(key => value.value.analyst_note_groups.includes(key)))

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

const selectAll = () => update({ coach_panel_roles: roleKeys })
const selectCore = () => update({ coach_panel_roles: ['head_coach', 'attack', 'defense', 'risk'] })
const toggleAllSpaces = (checked) => update({ analyst_note_groups: checked ? spaceKeys : [] })
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
  coach_panel_roles: roleKeys,
  coach_deliberation_rounds: 3,
  enable_llm_data_extraction: true,
  narrative_polish_count: 9,
  analyst_note_groups: spaceKeys,
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
