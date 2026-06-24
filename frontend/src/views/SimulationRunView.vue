<template>
  <div class="main-view">
    <header class="app-header">
      <div class="header-left">
        <div class="brand" @click="router.push('/')">GOALFISH</div>
      </div>

      <div class="header-center">
        <div class="view-switcher">
          <button
            v-for="mode in ['graph', 'split', 'workbench']"
            :key="mode"
            class="switch-btn"
            :class="{ active: viewMode === mode }"
            @click="viewMode = mode"
          >
            {{ { graph: $t('main.layoutGraph'), split: $t('main.layoutSplit'), workbench: $t('main.layoutWorkbench') }[mode] }}
          </button>
        </div>
      </div>

      <div class="header-right">
        <LanguageSwitcher />
        <div class="step-divider"></div>
        <div class="workflow-step">
          <span class="step-num">{{ t('main.stepProgress', { step: 3, total: 5 }) }}</span>
          <span class="step-name">{{ $tm('main.stepNames')[2] }}</span>
        </div>
        <div class="step-divider"></div>
        <span class="status-indicator" :class="statusClass">
          <span class="dot"></span>
          {{ statusText }}
        </span>
      </div>
    </header>

    <main class="content-area">
      <div class="panel-wrapper left" :style="leftPanelStyle">
        <GraphPanel
          :graphData="graphData"
          :ontology="projectData?.ontology"
          :loading="graphLoading"
          :currentPhase="3"
          :isSimulating="currentStatus === 'processing'"
          @refresh="refreshGraph"
          @toggle-maximize="toggleMaximize('graph')"
        />
      </div>

      <div class="panel-wrapper right" :style="rightPanelStyle">
        <Step3Simulation
          :predictionRunId="currentPredictionRunId"
          :predictionConfigId="currentPredictionConfigId"
          :projectData="projectData"
          :graphData="graphData"
          :systemLogs="systemLogs"
          @go-back="handleGoBack"
          @next-step="handleNextStep"
          @add-log="addLog"
          @update-status="updateStatus"
        />
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import GraphPanel from '../components/GraphPanel.vue'
import Step3Simulation from '../components/Step3Simulation.vue'
import { getProject, getGraphData } from '../api/graph'
import { getPredictionStatus } from '../api/prediction'
import { getProjectWorkflow } from '../api/projectWorkflow'
import LanguageSwitcher from '../components/LanguageSwitcher.vue'

const { t } = useI18n()
const route = useRoute()
const router = useRouter()
const isStaticDemo = typeof window !== 'undefined' && window.__GOALFISH_STATIC_DEMO__ === true
const routePredictionRunId = () => route.params.predictionRunId || null
const routePredictionConfigId = () => route.query.prediction_config_id || null

const viewMode = ref('split')
const currentProjectId = ref(route.params.projectId)
const currentPredictionRunId = ref(routePredictionRunId())
const currentPredictionConfigId = ref(routePredictionConfigId())
const projectData = ref(null)
const graphData = ref(null)
const graphLoading = ref(false)
const systemLogs = ref([])
const currentStatus = ref('processing')
const workflowLoaded = ref(false)

const leftPanelStyle = computed(() => {
  if (viewMode.value === 'graph') return { width: '100%', opacity: 1, transform: 'translateX(0)' }
  if (viewMode.value === 'workbench') return { width: '0%', opacity: 0, transform: 'translateX(-20px)' }
  return { width: '50%', opacity: 1, transform: 'translateX(0)' }
})

const rightPanelStyle = computed(() => {
  if (viewMode.value === 'workbench') return { width: '100%', opacity: 1, transform: 'translateX(0)' }
  if (viewMode.value === 'graph') return { width: '0%', opacity: 0, transform: 'translateX(20px)' }
  return { width: '50%', opacity: 1, transform: 'translateX(0)' }
})

const statusClass = computed(() => currentStatus.value)

const statusText = computed(() => {
  if (currentStatus.value === 'error') return t('common.error')
  if (currentStatus.value === 'completed') return t('common.completed')
  return t('common.running')
})

const addLog = (msg) => {
  const now = new Date()
  const time = now.toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit'
  }) + '.' + now.getMilliseconds().toString().padStart(3, '0')
  systemLogs.value.push({ time, msg })
  if (systemLogs.value.length > 200) systemLogs.value.shift()
}

const updateStatus = (status) => {
  currentStatus.value = status
}

const toggleMaximize = (target) => {
  viewMode.value = viewMode.value === target ? 'split' : target
}

const handleGoBack = () => {
  router.push({ name: 'Simulation', params: { projectId: currentProjectId.value } })
}

const handleNextStep = ({ reportId } = {}) => {
  if (reportId) {
    addLog(t('log.enterStep4'))
  }
}

const replaceRouteWithActiveWorkflow = (active = {}) => {
  const params = { projectId: currentProjectId.value }
  if (active.prediction_run_id) {
    params.predictionRunId = active.prediction_run_id
  }

  const query = {}
  if (active.prediction_config_id) {
    query.prediction_config_id = active.prediction_config_id
  }

  const routeRunId = route.params.predictionRunId || null
  const routeConfigId = route.query.prediction_config_id || null
  if (routeRunId !== (active.prediction_run_id || null) || routeConfigId !== (active.prediction_config_id || null)) {
    router.replace({ name: 'SimulationRun', params, query })
  }
}

const recoverConfigFromRouteRun = async (active = {}) => {
  const resolved = { ...active }
  const routeRunId = routePredictionRunId()
  const routeConfigId = routePredictionConfigId()

  if (!resolved.prediction_run_id && routeRunId) {
    resolved.prediction_run_id = routeRunId
  }
  if (!resolved.prediction_config_id && routeConfigId) {
    resolved.prediction_config_id = routeConfigId
  }
  if (!resolved.prediction_config_id && resolved.prediction_run_id && !isStaticDemo) {
    try {
      const statusRes = await getPredictionStatus(resolved.prediction_run_id)
      resolved.prediction_config_id = statusRes.data?.prediction_config_id || null
    } catch (err) {
      addLog(t('log.restoreConfigFromRunFailed', { error: err.message }))
    }
  }
  return resolved
}

const syncActiveWorkflow = async () => {
  if (!currentProjectId.value) return
  try {
    const workflowRes = await getProjectWorkflow(currentProjectId.value)
    const active = await recoverConfigFromRouteRun(workflowRes.data?.active_artifacts || {})
    workflowLoaded.value = true

    currentPredictionConfigId.value = active.prediction_config_id || null
    currentPredictionRunId.value = active.prediction_run_id || null

    if (route.params.predictionRunId && route.params.predictionRunId !== active.prediction_run_id) {
      addLog(active.prediction_run_id
        ? t('log.oldStep3RouteSwitched')
        : t('log.oldStep3RouteIgnored'))
    }

    replaceRouteWithActiveWorkflow(active)
    currentStatus.value = active.prediction_run_id ? currentStatus.value : 'processing'
  } catch (err) {
    workflowLoaded.value = true
    currentPredictionRunId.value = null
    currentPredictionConfigId.value = null
    currentStatus.value = 'error'
    addLog(t('log.activeWorkflowLoadFailed', { error: err.message }))
  }
}

const loadProjectData = async () => {
  try {
    graphData.value = null
    addLog(t('log.loadSimulationProject', { id: currentProjectId.value }))
    const projRes = await getProject(currentProjectId.value)
    if (!projRes.success || !projRes.data) {
      currentStatus.value = 'error'
      addLog(t('log.loadProjectFailed', { error: projRes.error || t('common.unknownError') }))
      return
    }
    projectData.value = projRes.data
    await syncActiveWorkflow()

    if (projRes.data.graph_id) {
      await loadGraph(projRes.data.graph_id)
    }
  } catch (err) {
    currentStatus.value = 'error'
    addLog(t('log.loadSimulationProjectException', { error: err.message }))
  }
}

const loadGraph = async (graphId) => {
  graphLoading.value = currentStatus.value !== 'processing'
  try {
    const res = await getGraphData(graphId)
    if (res.success) {
      graphData.value = res.data
      addLog(t('log.graphLoaded'))
    }
  } catch (err) {
    addLog(t('log.graphLoadFailed', { error: err.message }))
  } finally {
    graphLoading.value = false
  }
}

const refreshGraph = () => {
  if (projectData.value?.graph_id) {
    loadGraph(projectData.value.graph_id)
  }
}

watch(() => route.params.predictionRunId, () => {
  if (workflowLoaded.value) {
    syncActiveWorkflow()
  }
})

watch(() => route.query.prediction_config_id, () => {
  if (workflowLoaded.value) {
    syncActiveWorkflow()
  }
})

onMounted(loadProjectData)
</script>

<style scoped>
.main-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #FFF;
  overflow: hidden;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
}

.app-header {
  height: 60px;
  border-bottom: 1px solid #EAEAEA;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: #FFF;
  z-index: 100;
  position: relative;
}

.header-center {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
}

.brand {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 800;
  font-size: 18px;
  letter-spacing: 1px;
  cursor: pointer;
}

.view-switcher {
  display: flex;
  background: #F5F5F5;
  padding: 4px;
  border-radius: 6px;
  gap: 4px;
}

.switch-btn {
  border: none;
  background: transparent;
  padding: 6px 16px;
  font-size: 12px;
  font-weight: 600;
  color: #666;
  border-radius: 4px;
  cursor: pointer;
}

.switch-btn.active {
  background: #FFF;
  color: #000;
  box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}

.header-right,
.workflow-step,
.status-indicator {
  display: flex;
  align-items: center;
}

.header-right {
  gap: 16px;
}

.workflow-step,
.status-indicator {
  gap: 8px;
  font-size: 14px;
}

.step-num {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  color: #999;
}

.step-name {
  font-weight: 700;
  color: #000;
}

.step-divider {
  width: 1px;
  height: 14px;
  background-color: #E0E0E0;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #CCC;
}

.status-indicator.processing .dot { background: #FF5722; animation: pulse 1s infinite; }
.status-indicator.completed .dot { background: #4CAF50; }
.status-indicator.error .dot { background: #F44336; }

@keyframes pulse { 50% { opacity: 0.5; } }

.content-area {
  flex: 1;
  display: flex;
  overflow: hidden;
}

.panel-wrapper {
  height: 100%;
  overflow: hidden;
  transition: width .4s cubic-bezier(.25,.8,.25,1), opacity .3s ease, transform .3s ease;
}

.panel-wrapper.left {
  border-right: 1px solid #EAEAEA;
}
</style>
