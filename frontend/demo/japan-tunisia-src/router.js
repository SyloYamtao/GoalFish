import { createRouter, createWebHashHistory } from 'vue-router'
import Home from '../../src/views/Home.vue'
import Process from '../../src/views/MainView.vue'
import SimulationView from '../../src/views/SimulationView.vue'
import SimulationRunView from '../../src/views/SimulationRunView.vue'
import ReportView from '../../src/views/ReportView.vue'
import InteractionView from '../../src/views/InteractionView.vue'

const PROJECT_ID = 'proj_2aa9775eb4c6'
const CONFIG_ID = 'cfg_1ff5f12a8387'
const RUN_ID = 'run_a2e40af7653c'
const REPORT_ID = 'report_3d10b1c6e73c'

const isMissingRouteParam = (value) => {
  const normalized = Array.isArray(value) ? value[0] : value
  return !normalized || normalized === 'undefined' || normalized === 'null'
}

const routes = [
  { path: '/', name: 'Home', component: Home },
  { path: '/process/:projectId', name: 'Process', component: Process, props: true },
  { path: '/prediction/:projectId/setup', name: 'Simulation', component: SimulationView, props: true },
  { path: '/prediction/:projectId/run/:predictionRunId?', name: 'SimulationRun', component: SimulationRunView, props: true },
  { path: '/report/:reportId', name: 'Report', component: ReportView, props: true },
  { path: '/interaction/:reportId', name: 'Interaction', component: InteractionView, props: true },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.beforeEach((to) => {
  if (to.name === 'SimulationRun') {
    const params = { ...to.params }
    const query = { ...to.query }
    let changed = false

    if (!params.projectId || params.projectId === 'new') {
      params.projectId = PROJECT_ID
      changed = true
    }
    if (!params.predictionRunId) {
      params.predictionRunId = RUN_ID
      changed = true
    }
    if (!query.prediction_config_id) {
      query.prediction_config_id = CONFIG_ID
      changed = true
    }

    if (changed) return { name: 'SimulationRun', params, query, replace: true }
  }

  if (to.name === 'Report' && isMissingRouteParam(to.params.reportId)) {
    return { name: 'Report', params: { reportId: REPORT_ID }, replace: true }
  }

  if (to.name === 'Interaction' && isMissingRouteParam(to.params.reportId)) {
    return { name: 'Interaction', params: { reportId: REPORT_ID }, replace: true }
  }

  return true
})

export default router
