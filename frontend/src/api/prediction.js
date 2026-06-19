import service, { requestWithRetry } from './index'

export const preparePredictionConfig = (projectId, data = {}) => {
  return service.post(`/api/prediction/${projectId}/prepare`, data, { timeout: 900000 })
}

export const getPredictionConfig = (predictionConfigId) => {
  return service.get(`/api/prediction/configs/${predictionConfigId}`)
}

export const getPredictionConfigStatus = (predictionConfigId) => {
  return service.get(`/api/prediction/configs/${predictionConfigId}/status`)
}

export const getPredictionConfigProgress = (predictionConfigId) => {
  return service.get(`/api/prediction/configs/${predictionConfigId}/progress`)
}

export const getPredictionDatasets = () => {
  return service.get('/api/prediction/datasets')
}

export const getLatestPredictionConfig = (projectId, params = {}) => {
  return service.get(`/api/prediction/${projectId}/configs/latest`, { params })
}

export const switchPredictionConfigDataset = (predictionConfigId, playerDatasetId) => {
  return service.patch(`/api/prediction/configs/${predictionConfigId}/dataset`, {
    player_dataset_id: playerDatasetId
  })
}

export const getPredictionConfigRoster = (predictionConfigId) => {
  return service.get(`/api/prediction/configs/${predictionConfigId}/roster`)
}

export const getPredictionCoachAgents = (predictionConfigId) => {
  return service.get(`/api/prediction/configs/${predictionConfigId}/coach-agents`)
}

export const getPredictionCoachDiscussions = (predictionConfigId) => {
  return service.get(`/api/prediction/configs/${predictionConfigId}/coach-discussions`)
}

export const getPredictionScenarioDesign = (predictionConfigId) => {
  return service.get(`/api/prediction/configs/${predictionConfigId}/scenario-design`)
}

export const getPredictionResumePolicy = (predictionConfigId) => {
  return service.get(`/api/prediction/configs/${predictionConfigId}/resume-policy`)
}

export const getPredictionConfigTeamStrengths = (predictionConfigId) => {
  return service.get(`/api/prediction/configs/${predictionConfigId}/team-strengths`)
}

export const runPrediction = (projectId, data = {}) => {
  return requestWithRetry(() => service.post(`/api/prediction/${projectId}/run`, data, { timeout: 30000 }), 3, 1000)
}

export const resumePrediction = (predictionRunId) => {
  return service.post(`/api/prediction/${predictionRunId}/resume`)
}

export const getPredictionStatus = (predictionRunId) => {
  return service.get(`/api/prediction/${predictionRunId}/status`)
}

export const getPredictionRunRoster = (predictionRunId) => {
  return service.get(`/api/prediction/${predictionRunId}/roster`)
}

export const getPredictionBudgetUsage = (predictionRunId) => {
  return service.get(`/api/prediction/${predictionRunId}/budget-usage`)
}

export const getScenarioCases = (predictionRunId) => {
  return service.get(`/api/prediction/${predictionRunId}/scenario-cases`)
}

export const getScenarioSpaces = (predictionRunId) => {
  return service.get(`/api/prediction/${predictionRunId}/scenario-spaces`)
}

export const getTeamStrengths = (predictionRunId) => {
  return service.get(`/api/prediction/${predictionRunId}/team-strengths`)
}

export const getScorelines = (predictionRunId) => {
  return service.get(`/api/prediction/${predictionRunId}/scorelines`)
}

export const getMatchEvents = (predictionRunId) => {
  return service.get(`/api/prediction/${predictionRunId}/match-events`)
}

export const getAnalystNotes = (predictionRunId) => {
  return service.get(`/api/prediction/${predictionRunId}/analyst-notes`)
}

export const getPredictionResult = (predictionRunId) => {
  return service.get(`/api/prediction/${predictionRunId}/result`)
}

export const createPredictionReport = (predictionRunId, data = {}) => {
  return requestWithRetry(() => service.post(`/api/prediction/${predictionRunId}/report`, data), 3, 1000)
}

export const createPredictionReportForProject = (projectId, data = {}) => {
  return requestWithRetry(
    () => service.post('/api/report/generate', {
      project_id: projectId,
      prediction_run_id: data.prediction_run_id || data.predictionRunId,
      prediction_config_id: data.prediction_config_id || data.predictionConfigId,
      force_regenerate: Boolean(data.force_regenerate),
    }),
    3,
    1000
  )
}

export const getPredictionHistory = (limit = 20) => {
  return service.get('/api/prediction/history', { params: { limit } })
}
