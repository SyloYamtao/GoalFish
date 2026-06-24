<template>
  <div class="ds-card">
    <div class="ds-card-title">
      <span>{{ t('prediction.dataSourcesTitle') }}</span>
      <InfoTooltip
        align="left"
        :title="t('prediction.dataSourcesTitle')"
        :text="t('prediction.dataSourcesTooltip')"
      />
    </div>
    <div class="ds-list">
      <button
        v-for="src in normalizedSources"
        :key="src.key"
        class="ds-row"
        type="button"
        :class="{ 'ds-disabled': src.status !== 'synced' }"
        @click="toggleExpand(src.key)"
      >
        <span class="ds-dot" :class="`ds-dot-${src.status}`"></span>
        <span class="ds-row-main">
          <b>{{ src.label }}</b>
          <small class="mono">{{ src.statusLabel }}</small>
        </span>
        <span class="ds-row-meta mono">
          <span>{{ src.updatedAtShort }}</span>
          <span v-if="src.rows"> · {{ t('prediction.rowsUnit', { count: src.rows.toLocaleString() }) }}</span>
        </span>
        <span v-if="expandedKey === src.key" class="ds-detail">
          <span><b>{{ t('prediction.fieldEtag') }}</b><em class="mono">{{ src.etag || '-' }}</em></span>
          <span><b>{{ t('prediction.fieldFetched') }}</b><em class="mono">{{ src.fetchedAt || '-' }}</em></span>
          <span v-if="src.url"><b>{{ t('prediction.fieldUrl') }}</b><em>{{ src.url }}</em></span>
          <span v-if="src.error"><b>{{ t('prediction.fieldError') }}</b><em>{{ src.error }}</em></span>
        </span>
      </button>
      <div v-if="normalizedSources.length === 0" class="ds-empty">{{ t('prediction.noDataSources') }}</div>
    </div>
    <div class="ds-actions">
      <button class="ghost-btn ghost-btn-sm" type="button" @click="$emit('refresh')">{{ t('prediction.refreshNow') }}</button>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import InfoTooltip from './InfoTooltip.vue'

const props = defineProps({
  sources: { type: Array, default: () => [] }
})

defineEmits(['refresh'])

const { t } = useI18n()
const expandedKey = ref(null)

const statusLabels = {
  synced: ['prediction.status_synced', 'Synced'],
  stale: ['prediction.status_stale', 'Stale cache'],
  error: ['prediction.status_error', 'Fetch failed'],
  skipped: ['prediction.status_skipped', 'Skipped']
}

const sourceLabels = {
  intl_results: ['prediction.source_intl_results', 'International results'],
  elo: ['prediction.source_elo', 'Elo rating'],
  national_elo: ['prediction.source_national_elo', 'Elo rating'],
  fifa_ranking: ['prediction.source_fifa_ranking', 'FIFA ranking'],
  fifa_rankings: ['prediction.source_fifa_rankings', 'FIFA ranking'],
  statsbomb_xg: ['prediction.source_statsbomb_xg', 'StatsBomb xG']
}

const normalizedSources = computed(() => (props.sources || []).map(src => {
  const status = src.status || 'skipped'
  const fetchedAt = src.fetched_at || src.fetchedAt || src.updated_at || null
  return {
    ...src,
    key: src.key,
    label: src.label || translateEntry(sourceLabels[src.key]) || src.key,
    status,
    statusLabel: src.statusLabel || translateEntry(statusLabels[status]) || status,
    fetchedAt,
    updatedAtShort: src.updated_at_short || shortDate(fetchedAt),
    rows: Number(src.rows || 0) || null,
    etag: src.etag || src.fingerprint || null,
    url: src.url || null,
    error: src.error || null
  }
}))

const toggleExpand = (key) => {
  expandedKey.value = expandedKey.value === key ? null : key
}

const shortDate = (value) => {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value).slice(0, 10)
  return date.toISOString().slice(0, 10)
}

const translateEntry = (entry) => {
  if (!entry) return ''
  const [key, fallback] = entry
  const translated = t(key)
  return translated && translated !== key ? translated : fallback
}
</script>

<style scoped>
.ds-card {
  border: 1px solid #EFEFEF;
  border-radius: 8px;
  background: #FCFCFC;
  padding: 12px;
  min-width: 0;
}

.ds-card-title {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #555;
  font-size: 13px;
  font-weight: 800;
  margin-bottom: 10px;
}

.ds-list {
  border: 1px solid #EFEFEF;
  border-radius: 8px;
  background: #FFF;
  overflow: hidden;
}

.ds-row {
  width: 100%;
  display: grid;
  grid-template-columns: 12px minmax(0, 1fr) auto;
  gap: 10px;
  padding: 10px 12px;
  border: none;
  border-bottom: 1px solid #EFEFEF;
  cursor: pointer;
  align-items: center;
  background: transparent;
  text-align: left;
  font-family: inherit;
}

.ds-row:last-child {
  border-bottom: none;
}

.ds-row.ds-disabled {
  opacity: .58;
}

.ds-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #CCC;
}

.ds-dot-synced { background: #22863A; }
.ds-dot-error { background: #8A1F2D; }
.ds-dot-stale { background: #FF4500; }
.ds-dot-skipped { background: #CCC; }

.ds-row-main {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.ds-row-main b {
  font-size: 13px;
  color: #111;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ds-row-main small,
.ds-row-meta {
  color: #777;
  font-size: 11px;
}

.ds-detail {
  grid-column: 1 / -1;
  display: grid;
  gap: 4px;
  padding: 8px 0 0 22px;
  font-size: 11px;
  color: #555;
}

.ds-detail span {
  display: grid;
  grid-template-columns: 56px minmax(0, 1fr);
  gap: 6px;
}

.ds-detail b {
  color: #777;
}

.ds-detail em {
  font-style: normal;
  overflow-wrap: anywhere;
}

.ds-empty {
  padding: 18px;
  color: #777;
  font-size: 13px;
  text-align: center;
}

.ds-actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}

.ghost-btn-sm {
  padding: 6px 10px;
  font-size: 12px;
}
</style>
