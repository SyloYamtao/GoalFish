<template>
  <Teleport to="body">
    <transition name="modal">
      <div v-if="open" class="modal-mask" @click.self="$emit('close')">
        <section class="modal-panel" role="dialog" aria-modal="true" aria-labelledby="dataset-title" @keydown.esc="$emit('close')">
          <header class="modal-header">
            <h3 id="dataset-title">{{ t('prediction.datasetTitle') }}</h3>
            <button type="button" class="modal-close" @click="$emit('close')">×</button>
          </header>

          <div class="dataset-list">
            <label
              v-for="dataset in datasets"
              :key="dataset.dataset_id"
              class="dataset-row"
              :class="{ active: selectedId === dataset.dataset_id }"
            >
              <input v-model="selectedId" type="radio" :value="dataset.dataset_id" />
              <span class="dataset-radio"></span>
              <span class="dataset-main">
                <b>{{ dataset.dataset_id }} <em v-if="dataset.dataset_id === currentDatasetId">({{ t('prediction.currentDataset') }})</em></b>
                <small>{{ dataset.scope_label || '-' }} · {{ t('prediction.teamsPlayers', { teams: dataset.teams_count || 0, players: dataset.players_count || 0 }) }}</small>
                <small class="mono">{{ t('prediction.importedAt', { date: shortDate(dataset.created_at) }) }}</small>
                <small v-if="dataset.match_scope && dataset.match_scope.matches_compatible === false" class="dataset-warn">
                  {{ t('prediction.datasetIncompatible') }}
                </small>
              </span>
            </label>
            <div v-if="datasets.length === 0" class="dataset-empty">{{ t('prediction.noDatasets') }}</div>
          </div>

          <footer class="modal-footer">
            <button class="ghost-btn" type="button" @click="$emit('close')">{{ t('common.cancel') }}</button>
            <button class="primary-btn" type="button" :disabled="!selectedId || selectedId === currentDatasetId || loading" @click="$emit('apply', selectedId)">
              {{ loading ? t('prediction.applying') : t('prediction.applyRegenerate') }}
            </button>
          </footer>
        </section>
      </div>
    </transition>
  </Teleport>
</template>

<script setup>
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  open: { type: Boolean, default: false },
  datasets: { type: Array, default: () => [] },
  currentDatasetId: { type: String, default: '' },
  loading: { type: Boolean, default: false }
})

defineEmits(['close', 'apply'])

const { t } = useI18n()
const selectedId = ref('')

watch(() => props.open, (open) => {
  if (open) selectedId.value = props.currentDatasetId || props.datasets[0]?.dataset_id || ''
})

watch(() => props.currentDatasetId, (value) => {
  if (props.open) selectedId.value = value || ''
})

const shortDate = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10)
  return date.toISOString().slice(0, 10)
}
</script>

<style scoped>
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 1100;
  background: rgba(0, 0, 0, .28);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
}

.modal-panel {
  width: min(620px, 100%);
  max-height: min(720px, 92vh);
  background: #FFF;
  border: 1px solid #EAEAEA;
  border-radius: 8px;
  display: flex;
  flex-direction: column;
}

.modal-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 16px 20px;
  border-bottom: 1px solid #EAEAEA;
}

.modal-header h3 {
  margin: 0;
  flex: 1;
}

.modal-close {
  border: none;
  background: transparent;
  font-size: 24px;
  cursor: pointer;
  color: #555;
}

.dataset-list {
  overflow-y: auto;
  padding: 12px;
}

.dataset-row {
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  gap: 12px;
  padding: 12px;
  border: 1px solid #EFEFEF;
  border-radius: 8px;
  cursor: pointer;
  margin-bottom: 10px;
}

.dataset-row.active {
  border-color: #111;
}

.dataset-row input {
  display: none;
}

.dataset-radio {
  width: 14px;
  height: 14px;
  border: 1.5px solid #111;
  border-radius: 50%;
  margin-top: 2px;
}

.dataset-row.active .dataset-radio {
  box-shadow: inset 0 0 0 3px #FFF;
  background: #111;
}

.dataset-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.dataset-main b {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.dataset-main em {
  color: #777;
  font-style: normal;
  font-size: 12px;
}

.dataset-main small {
  color: #666;
  font-size: 12px;
}

.dataset-warn {
  color: #8A4B00 !important;
}

.dataset-empty {
  padding: 20px;
  color: #777;
  text-align: center;
}

.modal-footer {
  border-top: 1px solid #EAEAEA;
  padding: 14px 20px;
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.modal-enter-active,
.modal-leave-active {
  transition: opacity .16s ease;
}

.modal-enter-from,
.modal-leave-to {
  opacity: 0;
}
</style>
